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
        if state['mode']=='repeated_reads':
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


def test_eof_final_frame_is_accepted_but_real_missing_finish_preserves_draft(client,wire):
    wire['mode']='query'
    first=send(client,wire['sid'],'今天有什么安排','query')
    assert first['status']=='completed' and '真实收到' in first['delta']
    trace=trace_for(client,wire['sid'],first['id'])
    assert next(e for e in trace['events'] if e['stage']=='provider.stream_end')['complete']
    wire['mode']='write_then_stream';wire['stream_broken']=True
    broken=send(client,wire['sid'],'今晚帮我安排操作系统作业，90分钟','write')
    assert broken['status']=='failed' and broken['error_code']=='AI_RESPONSE_INVALID'
    draft=next(r['draft'] for r in broken['content']['tools'] if r.get('draft'))
    trace=trace_for(client,wire['sid'],broken['id'])
    assert next(e for e in trace['events'] if e['stage']=='run.failed')['phase']=='final_reply'
    assert call(client,f"/api/workspace/drafts/planning/{draft['id']}")['id']==draft['id']
    wire['stream_broken']=False
    call(client,f"/api/conversations/{wire['sid']}/runs/{broken['id']}/retry",{'expected_attempt':1})
    from tests.test_workspace_stage2 import wait
    resumed=wait(client,wire['sid'],broken['id'])
    assert resumed['status']=='completed'
    assert next(r['draft'] for r in resumed['content']['tools'] if r.get('draft'))['id']==draft['id']
    assert len([r for r in wire['requests'] if not r.get('stream')])==2
    assert call(client,'/api/tasks')==[]


def test_real_stream_network_error_is_not_json_error_or_draft_failure(client,wire):
    wire['mode']='write_then_stream';wire['network_broken']=True
    result=send(client,wire['sid'],'今晚帮我安排操作系统作业，90分钟')
    assert result['status']=='failed' and result['error_code']=='AI_UNAVAILABLE'
    assert any(r.get('draft') for r in result['content']['tools'])
    trace=trace_for(client,wire['sid'],result['id'])
    assert any(e['stage']=='provider.stream_network_failed' and e['error_type']=='ReadError' for e in trace['events'])
    assert 'private transport' not in json.dumps(trace)
