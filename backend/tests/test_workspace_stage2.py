"""Stage 2 isolated facts, review records, migrations and controlled tools."""
import asyncio
import time
from datetime import date,datetime,timezone
from copy import deepcopy
import pytest
from sqlalchemy import select,text,event,inspect
from sqlalchemy.orm import Session
from app.models import Task,Plan,PlanItem,AssistantSession,GrowthChangeDraft,WorkspaceMetadata
from app.services import conversation_tools,conversation_runs,claude_client
from app.workspace_schemas import ToolPlan


def call(client,method,path,**kwargs):
    r=client.request(method,path,**kwargs);assert r.status_code<300,r.text;return r.json()


def wait(client,sid,rid):
    for _ in range(100):
        r=call(client,'GET',f'/api/conversations/{sid}/runs/{rid}')
        if r['status']!='running':return r
        time.sleep(.02)
    raise AssertionError('run did not finish')


@pytest.fixture
def mock_reply(monkeypatch):
    async def events(request):
        yield {'type':'mode','value':'streaming'}
        yield {'type':'delta','text':'已读取真实工具结果，草案尚未正式保存。'}
    monkeypatch.setattr(conversation_runs,'reply_events',events)


def test_calendar_range_midnight_segments_courses_and_no_writes(client,test_engine):
    task=call(client,'POST','/api/tasks',json={'title':'跨午夜正式任务','duration_minutes':60,'deadline':'2026-10-16T20:00:00+08:00'})
    call(client,'POST','/api/time-rules',json={'title':'周期课程','kind':'course','recurrence':'weekly','weekday':4,'start_time':'09:00','end_time':'10:00'})
    with Session(test_engine) as db:
        p=Plan(week_start=date(2026,10,12),status='confirmed',source_revision=0,task_ids=[task['id']]);db.add(p);db.flush()
        db.add(PlanItem(plan_id=p.id,task_id=task['id'],kind='task',title_snapshot=task['title'],start_at=datetime.fromisoformat('2026-10-14T23:30:00+08:00'),end_at=datetime.fromisoformat('2026-10-15T00:30:00+08:00')));db.commit()
    before=call(client,'GET','/api/data/export')
    day=call(client,'GET','/api/calendar/events?start=2026-10-15&end=2026-10-16')
    assert len([e for e in day['events'] if e['kind']=='formal_task'])==1
    assert len([e for e in day['events'] if e['kind']=='course'])==1
    assert call(client,'GET','/api/calendar/events?start=2026-10-16&end=2026-10-17')['events'][0]['kind']=='deadline'
    year=call(client,'GET','/api/calendar/events?start=2026-01-01&end=2027-01-01')
    assert len({e['id'] for e in year['events']})==len(year['events'])
    after=call(client,'GET','/api/data/export');assert before['tables']==after['tables']
    assert client.get('/api/calendar/events?start=2026-01-01&end=2028-01-01').status_code==422


def test_review_facts_explicit_record_version_snapshot_search(client):
    t=call(client,'POST','/api/tasks',json={'title':'完成一次','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    call(client,'POST',f"/api/tasks/{t['id']}/feedback",json={'client_action_id':'feedback','outcome':'completed','actual_minutes':25})
    facts=call(client,'GET','/api/reviews/facts?start=2026-10-14&end=2026-10-15')
    assert facts['completed_count']==1 and facts['known_minutes']==25
    assert facts['sources'][0]['task_id']==t['id']
    content=dict(client_request_id='record',period='day',start_date='2026-10-14',end_date='2026-10-15',title='我的观察',summary='事实',conclusion='感觉不错',next_steps='')
    r=call(client,'POST','/api/reviews/records',json=content)
    assert r['version']==1 and r['facts']['known_minutes']==25
    assert call(client,'POST','/api/reviews/records',json=content)['id']==r['id']
    edit={k:v for k,v in content.items() if k!='client_request_id'};edit.update(expected_version=1,conclusion='新的结论')
    changed=call(client,'PATCH',f"/api/reviews/records/{r['id']}",json=edit)
    assert changed['version']==2 and len(changed['history'])==1 and changed['facts']==r['facts']
    edit['conclusion']='冲突';assert client.patch(f"/api/reviews/records/{r['id']}",json=edit).status_code==409
    assert len(call(client,'GET','/api/reviews/records?q=新的结论')['items'])==1


def test_allowlisted_tools_create_and_edit_same_breakdown_before_confirm(client,test_engine,monkeypatch,mock_reply):
    async def decompose(request,now):
        return {'parent':{'title':request['title'],'deadline':request['deadline']},'children':[{'title':'准备','deadline':request['deadline'],'duration_minutes':60,'sort_order':0}]}
    from app.services import assistant_ai
    monkeypatch.setattr(assistant_ai,'decompose_task',decompose)
    async def choose(request):return ToolPlan(calls=[{'name':'tasks','arguments':{}},{'name':'breakdown_draft','arguments':{'title':'汇报','text':'汇报60分钟','deadline':'2026-10-16T20:00:00+08:00','expected_duration_minutes':60}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'conversation'})['id']
    r=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'send','text':'拆解汇报60分钟，周五20点截止'})
    done=wait(client,sid,r['id']);assert done['status']=='completed'
    ref=done['content']['tools'][1]['draft'];assert call(client,'GET','/api/tasks')==[]
    content=deepcopy(ref['content']);content['children'][0]['duration_minutes']=45
    updated=call(client,'PATCH',f"/api/workspace/drafts/breakdown/{ref['id']}",json={'expected_version':ref['version'],'content':content})
    assert updated['version']!=ref['version']
    assert client.post(f"/api/workspace/drafts/breakdown/{ref['id']}/confirm",json={'expected_version':ref['version']}).status_code==409
    async def change(request):
        assert request['current_drafts'][0]['content']['children'][0]['duration_minutes']==45
        content['children'][0]['title']='继续最新编辑'
        return ToolPlan(calls=[{'name':'edit_draft','arguments':{'kind':'breakdown','id':ref['id'],'version':updated['version'],'content':content}}])
    monkeypatch.setattr(conversation_tools,'plan',change)
    follow=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'follow','text':'保留45分钟，名称改成继续最新编辑','draft_versions':[{'kind':'breakdown','id':ref['id'],'version':updated['version']}]})
    done=wait(client,sid,follow['id']);assert done['content']['tools'][0]['draft']['id']==ref['id']
    latest=call(client,'GET',f"/api/workspace/drafts/breakdown/{ref['id']}")
    result=call(client,'POST',f"/api/workspace/drafts/breakdown/{ref['id']}/confirm",json={'expected_version':latest['version']})
    again=call(client,'POST',f"/api/workspace/drafts/breakdown/{ref['id']}/confirm",json={'expected_version':latest['version']})
    assert result['status']==again['status']=='applied' and len(call(client,'GET','/api/tasks'))==2


def test_tools_never_confirm_and_ordinary_chat_does_not_write_business(client,monkeypatch,mock_reply):
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'chat'})['id']
    r=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'normal','text':'讨论学习方向'})
    assert wait(client,sid,r['id'])['status']=='completed'
    assert call(client,'GET','/api/tasks')==[] and call(client,'GET','/api/reviews/records')['items']==[]
    with pytest.raises(Exception):ToolPlan(calls=[{'name':'execute_sql','arguments':{}}])


def test_v4_and_explicit_v3_conversion_cannot_erase_new_records(client):
    snapshot=call(client,'GET','/api/data/export');assert snapshot['format_version']==5
    legacy=deepcopy(snapshot);legacy['format_version']=3;del legacy['tables']['review_records'];del legacy['tables']['memory_entries']
    assert client.post('/api/data/import',json=legacy).status_code==200
    call(client,'POST','/api/reviews/records',json=dict(client_request_id='r',title='不能丢失',start_date='2026-10-12',end_date='2026-10-19'))
    assert client.post('/api/data/import',json=legacy).status_code==409
    v4=call(client,'GET','/api/data/export');assert client.post('/api/data/import',json=v4).status_code==200
    assert len(call(client,'GET','/api/reviews/records')['items'])==1


def test_explicit_ai_review_is_only_a_draft_and_confirms_once(client,monkeypatch):
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    async def synthesize(*args):
        return '{"title":"这一周","summary":"暂无执行事实","conclusion":"先观察","next_steps":""}'
    monkeypatch.setattr(claude_client,'request_claude',synthesize)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'review-chat'})['id']
    body=dict(client_request_id='review-once',start_date='2026-10-12',end_date='2026-10-19',period='week')
    draft=call(client,'POST',f'/api/conversations/{sid}/review-drafts',json=body)
    assert draft['status']=='ready' and call(client,'GET','/api/reviews/records')['items']==[]
    assert call(client,'POST',f'/api/conversations/{sid}/review-drafts',json=body)['id']==draft['id']
    assert client.post(f'/api/conversations/{sid}/review-drafts',json={**body,'end_date':'2026-10-20'}).status_code==409
    saved=call(client,'POST',f"/api/workspace/drafts/review_record/{draft['id']}/confirm",json={'expected_version':draft['version']})
    assert saved['status']=='applied'
    call(client,'POST',f"/api/workspace/drafts/review_record/{draft['id']}/confirm",json={'expected_version':draft['version']})
    records=call(client,'GET','/api/reviews/records')['items']
    assert len(records)==1 and call(client,'GET',f"/api/reviews/records/{records[0]['id']}")['sources']['conversation_id']==sid
    assert call(client,'GET','/api/tasks')==[]


def test_review_generation_errors_and_source_revision_guard(client,monkeypatch):
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'review-errors'})['id']
    body=dict(client_request_id='r',start_date='2026-10-12',end_date='2026-10-19')
    assert client.post(f'/api/conversations/{sid}/review-drafts',json=body).json()['detail']['code']=='AI_NOT_CONFIGURED'
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    async def invalid(*args):return '[]'
    monkeypatch.setattr(claude_client,'request_claude',invalid)
    assert client.post(f'/api/conversations/{sid}/review-drafts',json=body).status_code==502
    async def valid(*args):return '{"title":"旧事实","summary":"","conclusion":""}'
    monkeypatch.setattr(claude_client,'request_claude',valid)
    draft=call(client,'POST',f'/api/conversations/{sid}/review-drafts',json=body)
    call(client,'POST','/api/tasks',json={'title':'事实已变','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    response=client.post(f"/api/workspace/drafts/review_record/{draft['id']}/confirm",json={'expected_version':draft['version']})
    assert response.json()['detail']['code']=='REVIEW_FACTS_CHANGED'
    assert call(client,'GET','/api/reviews/records')['items']==[]


def test_planning_tool_uses_existing_confirmation_and_retry_receipt(client,monkeypatch,mock_reply):
    async def choose(request):return ToolPlan(calls=[{'name':'planning_draft','arguments':{'actions':[{'op':'add','fields':{'title':'真实待确认安排','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'}}]}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'planning'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'plan','text':'创建30分钟任务，周五20点截止'})
    done=wait(client,sid,run['id']);assert done['status']=='completed'
    assert 'draft' in done['content']['tools'][0],done
    ref=done['content']['tools'][0]['draft'];assert ref['status']=='ready'
    assert call(client,'GET','/api/tasks')==[]
    meta=call(client,'GET',f'/api/conversations/{sid}')
    blocked=client.patch(f'/api/conversations/{sid}',json={'expected_version':meta['version'],'archived':True})
    assert blocked.json()['detail']['code']=='CONVERSATION_HAS_DRAFTS'
    body={'expected_version':ref['version'],'content':ref['content']}
    edited=call(client,'PATCH',f"/api/workspace/drafts/planning/{ref['id']}",json=body)
    repeated=call(client,'PATCH',f"/api/workspace/drafts/planning/{ref['id']}",json=body)
    assert edited['id']==repeated['id'] and edited['id']!=ref['id']
    assert client.post(f"/api/workspace/drafts/planning/{ref['id']}/confirm",json={'expected_version':ref['version']}).status_code==409
    call(client,'POST',f"/api/workspace/drafts/planning/{edited['id']}/confirm",json={'expected_version':edited['version']})
    call(client,'POST',f"/api/workspace/drafts/planning/{edited['id']}/confirm",json={'expected_version':edited['version']})
    assert len(call(client,'GET','/api/tasks'))==1
    assert any(e['kind']=='formal_task' for e in call(client,'GET','/api/calendar/events?start=2026-10-14&end=2026-10-19')['events'])


@pytest.mark.parametrize('question_source',['selector','tool','validator'])
def test_scheduling_clarification_survives_reply_and_continues_to_confirm(client,monkeypatch,question_source):
    question='今晚最晚几点前完成操作系统作业？'
    actions=[{'op':'add','fields':{'title':'操作系统作业','duration_minutes':90}}]
    requests=[]
    async def choose(request):
        requests.append(request)
        if request['message']=='大概1个半小时，你帮我安排一下':
            arguments={'actions':actions,'replan':True}
            if question_source!='validator':arguments['questions']=[question]
            return ToolPlan(questions=[question] if question_source=='selector' else [],
                calls=[{'name':'planning_draft','arguments':arguments}])
        assert request['message']=='今晚22点前完成'
        assert any(item['text']=='我今天晚上要完成操作系统作业' for item in request['history'])
        assert any(item['text']=='大概1个半小时，你帮我安排一下' for item in request['history'])
        action={'op':'add','fields':{**actions[0]['fields'],'deadline':'2026-10-14T22:00:00+08:00'}}
        pending=next((d for d in request.get('current_drafts',[]) if d['kind']=='planning' and d['status']=='needs_input'),None)
        if pending:action['target']=pending['content']['actions'][0]['target']
        return ToolPlan(calls=[{'name':'planning_draft','arguments':{'actions':[action]}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    async def reply(request):
        # A model must not replace a required clarification with informal advice.
        assert request['message']=='今晚22点前完成'
        yield {'type':'delta','text':'已生成待审核日程方案，请打开草案确认采用。'}
    monkeypatch.setattr(conversation_runs,'reply_events',reply)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'clarify'})['id']
    call(client,'POST',f'/api/conversations/{sid}/messages',json={'client_message_id':'initial','text':'我今天晚上要完成操作系统作业'})
    body={'client_message_id':'duration','text':'大概1个半小时，你帮我安排一下'}
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json=body)
    pending=wait(client,sid,run['id'])
    assert pending['status']=='completed',pending
    questions=pending['content']['questions']
    assert questions and all(q in pending['delta'] for q in questions)
    if question_source!='validator':assert questions==[question]
    else:assert any('具体截止时间' in q for q in questions)
    assert pending['delivery']=='full'
    assert '审核' in pending['delta'] and '正式' in pending['delta']
    assert call(client,'GET','/api/tasks')==[]
    assert not any(e['kind']=='formal_task' for e in call(client,'GET','/api/calendar/events?start=2026-10-14&end=2026-10-15')['events'])
    repeated=call(client,'POST',f'/api/conversations/{sid}/runs',json=body)
    assert repeated['id']==run['id'] and repeated['content']['questions']==questions
    assert len(requests)==1
    following=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'deadline','text':'今晚22点前完成'})
    done=wait(client,sid,following['id'])
    assert done['status']=='completed',done
    ref=done['content']['tools'][0]['draft']
    assert ref['status']=='ready' and call(client,'GET','/api/tasks')==[]
    assert not done['content'].get('questions')
    body={'expected_version':ref['version']}
    call(client,'POST',f"/api/workspace/drafts/planning/{ref['id']}/confirm",json=body)
    call(client,'POST',f"/api/workspace/drafts/planning/{ref['id']}/confirm",json=body)
    tasks=call(client,'GET','/api/tasks')
    assert len(tasks)==1 and tasks[0]['duration_minutes']==90 and tasks[0]['title']=='操作系统作业'
    assert any(e['kind']=='formal_task' for e in call(client,'GET','/api/calendar/events?start=2026-10-14&end=2026-10-15')['events'])


@pytest.mark.parametrize('kind,operations',[
    ('profile',[{'op':'create_goal','title':'明确目标','metric_kind':'count','weekly_target':2}]),
    ('feedback',[{'op':'record_feedback','task_id':1,'outcome':'completed','actual_minutes':20}]),
])
def test_profile_feedback_tools_validate_and_write_only_after_confirm(client,monkeypatch,mock_reply,kind,operations):
    task=call(client,'POST','/api/tasks',json={'title':'反馈来源','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    if kind=='feedback':operations=[{**operations[0],'task_id':task['id']}]
    async def choose(request):return ToolPlan(calls=[{'name':kind+'_draft','arguments':{'operations':operations}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':kind})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'business','text':'明确提出业务修改'})
    done=wait(client,sid,run['id']);ref=done['content']['tools'][0]['draft']
    assert call(client,'GET','/api/tasks')[0]['status']=='todo'
    if kind=='profile':assert call(client,'GET','/api/goals')['goals']==[]
    call(client,'POST',f"/api/workspace/drafts/{kind}/{ref['id']}/confirm",json={'expected_version':ref['version']})
    call(client,'POST',f"/api/workspace/drafts/{kind}/{ref['id']}/confirm",json={'expected_version':ref['version']})
    if kind=='profile':assert len(call(client,'GET','/api/goals')['goals'])==1
    else:assert call(client,'GET','/api/reviews/facts?start=2026-10-14&end=2026-10-15')['completed_count']==1


def test_tool_failure_does_not_hide_successful_receipts_and_retry_is_safe(client,monkeypatch):
    async def choose(request):return ToolPlan(calls=[{'name':'calendar','arguments':{'start':'2026-10-14','end':'2026-10-15'}},{'name':'profile_draft','arguments':{'operations':[{'op':'execute_sql'}]}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    attempts=[]
    async def flaky(request):
        attempts.append(1)
        if len(attempts)==1:raise claude_client.AIServiceError('AI_UNAVAILABLE')
        yield {'type':'delta','text':'工具未执行修改，没有正式保存。'}
    monkeypatch.setattr(conversation_runs,'reply_events',flaky)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'failure'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'once','text':'查询并提建议'})
    failed=wait(client,sid,run['id']);assert failed['status']=='failed'
    assert len(failed['content']['tools'])==2,failed
    assert failed['content']['tools'][1]['error']=='INVALID_DRAFT'
    call(client,'POST',f"/api/conversations/{sid}/runs/{run['id']}/retry",json={'expected_attempt':1})
    done=wait(client,sid,run['id']);assert done['status']=='completed'
    assert done['content']['tools']==failed['content']['tools'] and call(client,'GET','/api/tasks')==[]


def test_v3_restore_refuses_to_erase_stage2_tool_receipts(client,monkeypatch,mock_reply):
    old=call(client,'GET','/api/data/export');old['format_version']=3;del old['tables']['review_records'];del old['tables']['memory_entries']
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'tool-backup'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'msg','text':'你好'})
    assert wait(client,sid,run['id'])['status']=='completed'
    response=client.post('/api/data/import',json=old)
    assert response.status_code==409 and response.json()['detail']['code']=='LEGACY_RESTORE_TOOLS_PRESENT'
    current=call(client,'GET','/api/data/export')
    assert client.post('/api/data/import',json=current).status_code==200


def test_draft_preference_validation_cannot_disable_a_formal_rule(client,test_engine,monkeypatch,mock_reply):
    from app.models import PreferenceRule
    with Session(test_engine) as db:
        rule=PreferenceRule(name='原取舍',kind='adjustment_mode',parameters={'mode':'stable'},enabled=True)
        db.add(rule);db.commit();rid=rule.id;before_ids=[r.id for r in db.scalars(select(PreferenceRule))]
    operations=[{'op':'create_preference_rule','name':'建议取舍','kind':'adjustment_mode','parameters':{'mode':'balanced'}}]
    async def choose(request):return ToolPlan(calls=[{'name':'profile_draft','arguments':{'operations':operations}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'pref'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'pref','text':'请给我偏好草案'})
    result=wait(client,sid,run['id']);ref=result['content']['tools'][0]['draft']
    body={'expected_version':ref['version'],'content':{'operations':[{**operations[0],'name':'手改名称'}]}}
    updated=call(client,'PATCH',f"/api/workspace/drafts/profile/{ref['id']}",json=body)
    again=call(client,'PATCH',f"/api/workspace/drafts/profile/{ref['id']}",json=body)
    assert updated['version']==again['version']
    with Session(test_engine) as db:
        assert db.get(PreferenceRule,rid).enabled and [r.id for r in db.scalars(select(PreferenceRule))]==before_ids


def test_review_unknown_effort_never_becomes_zero_and_completion_is_deduplicated(client):
    task=call(client,'POST','/api/tasks',json={'title':'未知投入','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    call(client,'POST',f"/api/tasks/{task['id']}/feedback",json={'client_action_id':'unknown','outcome':'partial','remaining_minutes':25})
    facts=call(client,'GET','/api/reviews/facts?start=2026-10-14&end=2026-10-15')
    assert facts['minutes'] is None and facts['unknown_count']==1 and facts['partial_count']==1
    assert facts['sources'][0]['feedback_ids'] and facts['known_minutes']==0
    assert facts['by_day'][0]['minutes'] is None


def test_calendar_year_queries_are_bounded_and_constant_count(client,test_engine):
    counts=[]
    def count(*args):counts.append(1)
    event.listen(test_engine,'before_cursor_execute',count)
    try:
        assert client.get('/api/calendar/events?start=2026-01-01&end=2027-01-01').status_code==200
        assert len(counts)<=8
    finally:event.remove(test_engine,'before_cursor_execute',count)


def test_missing_information_is_asked_and_invalid_tools_do_not_change_facts(client,monkeypatch,mock_reply):
    async def choose(request):return ToolPlan(questions=['请提供截止日期和预计时长。'])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'ask'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'ask','text':'帮我安排报告'})
    assert wait(client,sid,run['id'])['status']=='completed'
    assert call(client,'GET','/api/tasks')==[]


def test_read_then_plan_uses_real_query_results_and_durable_steps(client,monkeypatch,mock_reply):
    task=call(client,'POST','/api/tasks',json={'title':'先查询再反馈','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'})
    steps=[]
    async def choose(request):
        steps.append(1)
        if not request['previous_tool_results']:
            return ToolPlan(calls=[{'name':'tasks'}],continue_after_read=True)
        actual=request['previous_tool_results'][0]['items'][0]
        assert actual['id']==task['id']
        return ToolPlan(calls=[{'name':'feedback_draft','arguments':{'operations':[{'op':'record_feedback','task_id':actual['id'],'outcome':'completed','actual_minutes':20}]}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'steps'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'steps','text':'先找到这个任务，再帮我整理反馈草案'})
    result=wait(client,sid,run['id'])
    assert len(steps)==2 and [r['tool'] for r in result['content']['tools']]==['tasks','feedback_draft']
    assert call(client,'GET','/api/tasks')[0]['status']=='todo'


def test_tools_never_loop_unbounded_and_cannot_continue_after_a_write(client,monkeypatch,mock_reply):
    with pytest.raises(Exception):ToolPlan(calls=[{'name':'profile_draft'}],continue_after_read=True)
    calls=[]
    async def query(request):calls.append(1);return ToolPlan(calls=[{'name':'tasks'}],continue_after_read=True)
    monkeypatch.setattr(conversation_tools,'plan',query)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'bounds'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'bounds','text':'查询'})
    assert len(wait(client,sid,run['id'])['content']['tools'])==4 and len(calls)==4


def test_invalid_shared_edit_returns_422_without_replacing_draft(client,monkeypatch,mock_reply):
    from app.services import assistant_ai
    async def decompose(request,now):return {'parent':{'title':request['title'],'deadline':request['deadline']},'children':[{'title':'子项','duration_minutes':30,'deadline':request['deadline'],'sort_order':0}]}
    monkeypatch.setattr(assistant_ai,'decompose_task',decompose)
    row=call(client,'POST','/api/tasks/breakdown-drafts',json={'client_request_id':'invalid-edit','source':'ai','text':'test','title':'task','deadline':'2026-10-16T20:00:00+08:00','expected_duration_minutes':30})
    current=call(client,'GET',f"/api/workspace/drafts/breakdown/{row['id']}")
    invalid=deepcopy(current['content']);invalid['children'][0]['duration_minutes']=7
    response=client.patch(f"/api/workspace/drafts/breakdown/{row['id']}",json={'expected_version':current['version'],'content':invalid})
    assert response.status_code==422
    assert call(client,'GET',f"/api/workspace/drafts/breakdown/{row['id']}")['version']==current['version']


def test_multiple_feedback_operations_use_distinct_server_keys(client,monkeypatch,mock_reply):
    tasks=[call(client,'POST','/api/tasks',json={'title':f'反馈{n}','duration_minutes':30,'deadline':'2026-10-16T20:00:00+08:00'}) for n in range(2)]
    async def choose(request):return ToolPlan(calls=[{'name':'feedback_draft','arguments':{'operations':[{'op':'record_feedback','task_id':t['id'],'outcome':'completed','actual_minutes':20} for t in tasks]}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'batch-feedback'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'batch','text':'两项均完成，各投入20分钟'})
    ref=wait(client,sid,run['id'])['content']['tools'][0]['draft']
    for _ in range(2):call(client,'POST',f"/api/workspace/drafts/feedback/{ref['id']}/confirm",json={'expected_version':ref['version']})
    facts=call(client,'GET','/api/reviews/facts?start=2026-10-14&end=2026-10-15')
    assert facts['completed_count']==2 and facts['known_minutes']==40


def test_stop_after_tool_receipt_then_retry_cannot_duplicate_draft(client,test_engine,monkeypatch):
    planner_calls=[]
    async def choose(request):
        planner_calls.append(1)
        return ToolPlan(calls=[{'name':'profile_draft','arguments':{'operations':[{'op':'create_goal','title':'仅一份草案','metric_kind':'count','weekly_target':1}]}}])
    async def slow(request):
        yield {'type':'mode','value':'streaming'}
        for _ in range(10):
            await asyncio.sleep(.05)
            yield {'type':'delta','text':'核对草案。'}
    monkeypatch.setattr(conversation_tools,'plan',choose)
    monkeypatch.setattr(conversation_runs,'reply_events',slow)
    sid=call(client,'POST','/api/conversations',json={'client_request_id':'stop-tools'})['id']
    run=call(client,'POST',f'/api/conversations/{sid}/runs',json={'client_message_id':'stop','text':'生成目标建议'})
    for _ in range(100):
        current=call(client,'GET',f"/api/conversations/{sid}/runs/{run['id']}")
        if current['content'].get('tools'):break
        time.sleep(.01)
    assert current['status']=='running' and current['content']['tools']
    ref=current['content']['tools'][0]['draft']
    assert call(client,'POST',f"/api/conversations/{sid}/runs/{run['id']}/stop",json={'expected_attempt':1})['status']=='cancelled'
    call(client,'POST',f"/api/conversations/{sid}/runs/{run['id']}/retry",json={'expected_attempt':1})
    result=wait(client,sid,run['id'])
    assert result['status']=='completed' and result['content']['tools'][0]['draft']['id']==ref['id']
    assert len(planner_calls)==1
    with Session(test_engine) as db:assert len(db.scalars(select(GrowthChangeDraft).where(GrowthChangeDraft.payload['tool_key'].as_string()==f"tool:{run['id']}:0")).all())==1
    assert call(client,'GET','/api/goals')['goals']==[]
