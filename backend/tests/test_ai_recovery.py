"""Actual HTTP adapter -> JSON/schema -> tools -> persisted draft, no live AI."""
import json
import time
import logging
from datetime import datetime
import httpx
import pytest
from app.services import claude_client,conversation_tools,conversation_runs,assistant_clock,conversation_context
from app.services.claude_client import ClaudeConfig
from tests.test_ai_skills import call,send,real_plan


@pytest.fixture
def wire(client,monkeypatch):
    state={'mode':'invalid_json','requests':[],'stream_broken':False,'network_broken':False}
    original=httpx.AsyncClient
    config=ClaudeConfig('test-secret-do-not-log','offline-model','https://offline.example',api_format='openai')
    def handler(request):
        body=json.loads(request.content);state['requests'].append(body)
        if body.get('stream'):
            frame='data: '+json.dumps({'choices':[{'delta':{'content':'真实收到的回复片段'}}]},ensure_ascii=False)+'\r\n\r\n'
            if state['network_broken']:
                class Broken(httpx.AsyncByteStream):
                    async def __aiter__(self):
                        yield frame.encode()
                        raise httpx.ReadError('private transport detail must not be logged')
                return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Broken())
            if not state['stream_broken']:
                frame+='data: '+json.dumps({'choices':[{'delta':{},'finish_reason':'stop'}]})+'\r\n\r\ndata: [DONE]'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},text=frame)
        count=sum(not r.get('stream') for r in state['requests'])
        if state['mode']=='timeout':raise httpx.ReadTimeout('private timeout detail')
        if state['mode']=='empty':plan={'calls':[]}
        elif state['mode']=='review_aliases':
            if 'facts' in body['messages'][1]['content'] and 'allowed_tools' not in body['messages'][1]['content']:
                plan={'title':'本周观察','summary':'当前没有执行反馈，不能推断投入。','conclusion':'先记录实际执行。','next_steps':''}
            elif count==1:
                plan={'calls':[{'name':'review','arguments':{'start_date':'2026-10-12','end_date':'2026-10-19','period':'week'}}],'continue_after_read':True}
            else:
                plan={'calls':[{'name':'review_draft','arguments':{'start_date':'2026-10-12','end_date':'2026-10-19','period':'week'}}]}
        elif state['mode']=='bad_review_aliases':
            plan={'calls':[{'name':'review','arguments':{'start_date':'2026-10-12','end_date':'2026-10-19','owner_id':'untrusted'}}],'continue_after_read':True}
        elif state['mode']=='repaired_review':
            args={'start':'2026-10-12','end':'2026-10-19'}
            if count==1:args['unexpected']='untrusted'
            plan={'calls':[{'name':'review','arguments':args}],'continue_after_read':count==1}
        elif state['mode']=='repeated_reads':
            plan={'calls':[{'name':'tasks'} for _ in range(4)],'continue_after_read':True}
        elif state['mode']=='distinct_reads':
            plan={'calls':[{'name':'tasks','arguments':{'offset':i}} for i in range(4)]}
        elif state['mode']=='write_then_stream':
            plan={'calls':[{'name':'tasks'},{'name':'planning_draft'}]}
        elif state['mode']=='fenced':plan={'calls':[{'name':'planning_draft'}]}
        elif state['mode']=='query':plan={'calls':[{'name':'tasks'}]}
        elif state['mode']=='read_then_invalid' and count==1:
            plan={'calls':[{'name':'tasks'}],'continue_after_read':True}
        elif state['mode']=='schema':plan={'calls':[{'name':'planning_draft','arguments':[]}],'private-field-name':'private-value'}
        else:plan=None
        content=json.dumps(plan) if plan is not None else '{invalid-json'
        if state['mode']=='fenced':content='```json\n'+content+'\n```'
        return httpx.Response(200,json={'choices':[{'finish_reason':'length' if state['mode']=='truncated' else 'stop','message':{'content':content}}]})
    monkeypatch.setattr(claude_client.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:config)
    monkeypatch.setattr(conversation_tools,'plan',real_plan)
    state['sid']=call(client,'/api/conversations',{'client_request_id':'wire-recovery'})['id']
    return state


def trace_for(client,sid,rid):
    for _ in range(100):
        current=call(client,f'/api/conversations/{sid}/runs/{rid}')
        if current['content'].get('diagnostics'):return current['content']['diagnostics']
        time.sleep(.01)
    raise AssertionError('diagnostics not persisted')


@pytest.mark.parametrize('mode',['invalid_json','schema','read_then_invalid','repeated_reads','distinct_reads','fenced','truncated','timeout'])
def test_real_protocol_failure_or_query_loop_still_persists_editable_draft(client,wire,mode,caplog):
    caplog.set_level(logging.INFO,logger='app.services.ai_diagnostics')
    wire['mode']=mode
    result=send(client,wire['sid'],'我今天晚上要完成操作系统作业，大概一个半小时，你帮我安排一下。')
    assert result['status']=='completed',result
    drafts=[r['draft'] for r in result['content']['tools'] if r.get('draft')]
    assert len(drafts)==1
    draft=drafts[0];value=draft['content']['schedule']
    assert draft['schedule_target'] and any(item['ref']==draft['schedule_target'] for item in draft['items'])
    assert value['title']=='操作系统作业' and value['duration_minutes']==90 and value['deadline'] is None
    assert draft['items'] and call(client,'/api/tasks')==[]
    trace=trace_for(client,wire['sid'],result['id'])
    assert trace['run_id']==result['id'] and trace['attempt']==1
    stages=[e['stage'] for e in trace['events']]
    assert 'skills.selected' in stages and 'planning_draft.persisted' in stages
    selected=next(e for e in trace['events'] if e['stage']=='skills.selected')
    loaded=call(client,'/api/health')['runtime']['skill_hashes']
    assert all(loaded[name]==digest for name,digest in selected['hashes'].items())
    defaults=next(e for e in trace['events'] if e['stage']=='planning_draft.persisted')
    assert defaults['draft_id']==draft['id'] and defaults['duration_minutes']==90 and not defaults['hard_deadline_present']
    if mode=='truncated':assert any(e.get('finish_reason')=='length' for e in trace['events'])
    if mode=='timeout':assert len(wire['requests'])==1 and 'provider.network_failed' in stages
    if mode=='schema':
        errors=next(e['errors'] for e in trace['events'] if e['stage']=='tool_plan.schema_failed')
        assert errors[0]['path']==['calls',0,'arguments']
    if mode in ('invalid_json','read_then_invalid'):assert 'tool_plan.json_failed' in stages
    if mode=='repeated_reads':
        assert len([r for r in result['content']['tools'] if r['tool']=='tasks'])==1
        assert 'tool.read_reused' in stages and len(wire['requests'])==2
    if mode=='distinct_reads':assert 'tool.budget_reserved' in stages
    encoded=json.dumps(trace,ensure_ascii=False)
    assert 'test-secret' not in encoded and '操作系统作业' not in encoded and 'offline.example' not in encoded
    assert 'private-field-name' not in encoded and 'private-value' not in encoded
    assert 'test-secret' not in caplog.text and '操作系统作业' not in caplog.text


@pytest.mark.parametrize('now,has_items',[('2026-10-14T19:10:00+08:00',True),('2026-10-14T21:10:00+08:00',False)])
def test_late_evening_uses_real_validator_and_never_changes_date(client,wire,monkeypatch,now,has_items):
    clock=lambda:datetime.fromisoformat(now)
    for module in (assistant_clock,conversation_tools,conversation_context):monkeypatch.setattr(module,'assistant_now',clock)
    result=send(client,wire['sid'],'今晚操作系统作业，90分钟，帮我安排一下')
    draft=next(r['draft'] for r in result['content']['tools'] if r.get('draft'))
    assert bool(draft['items'])==has_items
    assert draft['content']['schedule']['day']=='2026-10-14'
    assert all(datetime.fromisoformat(i['start_at'])>=clock() for i in draft['items'])
    if not has_items:assert draft['diagnostics'] and any('剩余' in n for n in draft['notices'])


def test_eof_is_accepted_query_stream_failure_is_real_and_draft_receipt_needs_no_stream(client,wire):
    wire['mode']='query'
    first=send(client,wire['sid'],'今天有什么安排','query')
    assert first['status']=='completed' and '真实收到' in first['delta']
    trace=trace_for(client,wire['sid'],first['id'])
    assert next(e for e in trace['events'] if e['stage']=='provider.stream_end')['complete']
    wire['stream_broken']=True
    broken=send(client,wire['sid'],'再查询今天安排','broken-query')
    assert broken['status']=='failed' and broken['error_code']=='AI_RESPONSE_INVALID'
    trace=trace_for(client,wire['sid'],broken['id'])
    assert next(e for e in trace['events'] if e['stage']=='run.failed')['phase']=='final_reply'
    assert broken['content']['tools'][0]['tool']=='tasks'
    wire['stream_broken']=False
    call(client,f"/api/conversations/{wire['sid']}/runs/{broken['id']}/retry",{'expected_attempt':1})
    from tests.test_workspace_stage2 import wait
    resumed=wait(client,wire['sid'],broken['id'])
    assert resumed['status']=='completed'
    assert len([r for r in wire['requests'] if not r.get('stream')])==2
    wire['mode']='write_then_stream';wire['stream_broken']=True
    streams=sum(bool(r.get('stream')) for r in wire['requests'])
    written=send(client,wire['sid'],'今晚帮我安排操作系统作业，90分钟','write')
    assert written['status']=='completed' and any(r.get('draft') for r in written['content']['tools'])
    assert sum(bool(r.get('stream')) for r in wire['requests'])==streams
    assert call(client,'/api/tasks')==[]


def test_real_stream_network_error_is_not_json_error_or_draft_failure(client,wire):
    wire['mode']='query';wire['network_broken']=True
    result=send(client,wire['sid'],'查询今天有哪些安排')
    assert result['status']=='failed' and result['error_code']=='AI_UNAVAILABLE'
    assert result['content']['tools'][0]['tool']=='tasks'
    trace=trace_for(client,wire['sid'],result['id'])
    assert any(e['stage']=='provider.stream_network_failed' and e['error_type']=='ReadError' for e in trace['events'])
    assert 'private transport' not in json.dumps(trace)


def test_compound_followup_edits_same_draft_and_uses_real_receipt(client,wire):
    from tests.test_workspace_stage2 import wait
    wire['mode']='fenced'
    first=send(client,wire['sid'],'请帮我安排【示例】操作系统作业：今天晚上19:00开始，90分钟。','first')
    draft=next(r['draft'] for r in first['content']['tools'] if r.get('draft'))
    assert draft['content']['schedule']['title']=='操作系统作业'
    wire['mode']='empty'
    started=call(client,f"/api/conversations/{wire['sid']}/runs",{
        'client_message_id':'edit','text':'我今天晚上要完成操作系统作业，把当前草案改为20:00开始，持续90分钟，截止时间是今晚22:00。请更新已有草案，保留待我确认状态。',
        'draft_versions':[{'kind':'planning','id':draft['id'],'version':draft['version']}]})
    result=wait(client,wire['sid'],started['id'])
    changed=next(r['draft'] for r in result['content']['tools'] if r.get('draft'))
    assert result['status']=='completed' and changed['id']==draft['id'] and changed['version']!=draft['version']
    assert changed['content']['schedule']['start_time']=='20:00' and changed['content']['schedule']['deadline'].endswith('22:00:00+08:00')
    assert '20:00' in result['delta'] and '90' in result['delta'] and '尚未' in result['delta']
    assert not any(r.get('stream') for r in wire['requests']), 'Business outcomes must come from saved results, not free narration'
    assert call(client,'/api/tasks')==[]
    saved=call(client,f"/api/workspace/drafts/planning/{changed['id']}/confirm",{'expected_version':changed['version']})
    assert saved['status']=='applied' and len(call(client,'/api/tasks'))==1


def test_review_range_aliases_query_once_then_generate_actual_review_text(client,wire):
    wire['mode']='review_aliases'
    result=send(client,wire['sid'],'请帮我复盘本周的真实执行记录，并整理为可编辑复盘记录草稿。')
    assert result['status']=='completed'
    tools=result['content']['tools']
    assert [r['tool'] for r in tools]==['review','review_draft'] and not any(r.get('error') for r in tools)
    draft=tools[-1]['draft']
    assert draft['content']['summary']=='当前没有执行反馈，不能推断投入。'
    assert not tools[-1].get('fallback') and not draft['notices']
    assert len(wire['requests'])==3 and not any(r.get('stream') for r in wire['requests'])
    assert call(client,'/api/reviews/records')['items']==[]


def test_repeated_invalid_review_arguments_do_not_loop_or_claim_success(client,wire):
    wire['mode']='bad_review_aliases'
    result=send(client,wire['sid'],'只查询本周回顾记录')
    assert result['status']=='completed' and '未完成' in result['delta']
    assert len(wire['requests'])<=2 and not any(r.get('stream') for r in wire['requests'])
    assert all(r.get('error') for r in result['content']['tools'])
    assert call(client,'/api/reviews/records')['items']==[]


def test_one_argument_repair_preserves_history_and_returns_real_query(client,wire):
    wire['mode']='repaired_review'
    result=send(client,wire['sid'],'只查询本周回顾')
    assert result['status']=='completed' and result['content']['business_status']=='queried'
    assert result['content']['tools'][0]['recovered_by']=='argument_repair'
    assert result['content']['tools'][1]['start_date']=='2026-10-12'
    packets=[json.loads(r['messages'][1]['content']) for r in wire['requests'] if not r.get('stream')]
    assert len(packets)==2 and packets[1]['decision_feedback']['code']=='INVALID_TOOL_ARGUMENTS'
    assert packets[1]['previous_tool_results'][0]['error']=='INVALID_TOOL_ARGUMENTS'
    assert call(client,'/api/tasks')==[] and call(client,'/api/reviews/records')['items']==[]


@pytest.mark.parametrize('args',[
    {'start':'2026-10-12','start_date':'2026-10-13','end':'2026-10-19'},
    {'start_date':'2026-10-12','end_date':'2026-10-19','owner_id':1},
    {'start_date':'2026-10-12','end_date':'2026-10-19','period':'all'},
])
def test_range_aliases_never_discard_unknown_or_conflicting_arguments(args):
    from fastapi import HTTPException
    from pydantic import ValidationError
    with pytest.raises((ValidationError,HTTPException)):
        conversation_tools.range_arguments('review',args)


def test_review_edit_never_replaces_pending_draft_with_a_new_record(client,wire):
    from tests.test_workspace_stage2 import wait
    wire['mode']='review_aliases'
    created=send(client,wire['sid'],'帮我复盘本周并生成复盘初稿','review-first')
    draft=next(r['draft'] for r in created['content']['tools'] if r.get('draft'))
    before=len(wire['requests']);wire['mode']='review_aliases'
    initial=call(client,f"/api/conversations/{wire['sid']}/runs",{
        'client_message_id':'review-edit','text':'请修改当前复盘草案，把结论改成需要继续记录。',
        'draft_versions':[{'kind':'review_record','id':draft['id'],'version':draft['version']}]})
    result=wait(client,wire['sid'],initial['id'])
    assert result['status']=='completed' and '不会另建' in result['delta']
    assert not any(r.get('draft') for r in result['content']['tools'])
    assert call(client,f"/api/workspace/drafts/review_record/{draft['id']}")['version']==draft['version']
    assert not any(r.get('stream') for r in wire['requests'][before:])
