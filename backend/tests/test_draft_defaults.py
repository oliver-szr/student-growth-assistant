"""Default-first drafts use anonymous databases and never real providers."""
import json
from datetime import datetime
import pytest
from app.services import draft_defaults, conversation_tools, conversation_runs, claude_client, assistant_clock
from app.workspace_schemas import ToolPlan
from tests.test_ai_skills import call, send, real_plan


@pytest.mark.parametrize('text,minutes', [('一个半小时',90),('两小时',120),('半小时',30),('1个半小时',90),('90分钟',90)])
def test_chinese_work_minutes(text,minutes):
    assert draft_defaults.duration(text)==minutes


@pytest.fixture
def defaults_chat(client,monkeypatch):
    async def empty(request):return ToolPlan()
    async def reply(request):yield {'type':'delta','text':'初稿已生成，尚未正式保存。'}
    monkeypatch.setattr(conversation_tools,'plan',empty)
    monkeypatch.setattr(conversation_runs,'reply_events',reply)
    return call(client,'/api/conversations',{'client_request_id':'defaults'})['id']


def ref_of(result):
    assert result['status']=='completed',result
    results=result['content']['tools']
    assert any(r.get('draft') for r in results),results
    return next(r['draft'] for r in results if r.get('draft'))


def test_first_task_statement_creates_default_draft_instead_of_repeated_questions(client,defaults_chat,monkeypatch):
    async def questions(request):
        return ToolPlan(questions=['明天几点开始？','需要多长时间？','任务名称用写云计算PPT吗？'])
    monkeypatch.setattr(conversation_tools,'plan',questions)
    result=send(client,defaults_chat,'我明天要写云计算ppt')
    ref=ref_of(result);value=ref['content']['schedule']
    assert value['title']=='云计算ppt' and value['day']=='2026-10-15'
    assert value['start_time']=='09:00' and value['duration_minutes']==60
    assert value['deadline'] is None and ref['status']=='needs_input'
    assert ref['field_sources']['title']=='user_explicit'
    assert all(ref['field_sources'][field]=='system_default' for field in ('start_time','duration_minutes'))
    assert len(ref['unresolved'])==1 and ref['items']
    assert result['content']['questions']==[] and result['content']['business_status']=='awaiting_confirmation'
    assert call(client,'/api/tasks')==[]


def test_generate_draft_recovers_existing_conversation_and_reuses_preview(client,defaults_chat):
    from tests.test_workspace_stage2 import wait
    call(client,f'/api/conversations/{defaults_chat}/messages',{'client_message_id':'previous','text':'我明天要写云计算ppt'})
    ref=ref_of(send(client,defaults_chat,'帮我生成草案'))
    assert ref['content']['schedule']['title']=='云计算ppt'
    assert ref['content']['schedule']['day']=='2026-10-15'
    assert ref['field_sources']['title']=='conversation_context'
    run=call(client,f'/api/conversations/{defaults_chat}/runs',{'client_message_id':'again','text':'帮我生成草案',
        'draft_versions':[{'kind':'planning','id':ref['id'],'version':ref['version']}]})
    repeated=ref_of(wait(client,defaults_chat,run['id']))
    assert repeated['id']==ref['id'] and call(client,'/api/tasks')==[]


def test_os_homework_no_deadline_defaults_real_draft(client,defaults_chat):
    sid=defaults_chat
    call(client,f'/api/conversations/{sid}/messages',{'client_message_id':'first','text':'我今天晚上要完成操作系统作业。'})
    result=send(client,sid,'大概一个半小时，你帮我安排一下。')
    ref=ref_of(result);value=ref['content']['schedule']
    assert value['title']=='操作系统作业' and value['duration_minutes']==90
    assert value['start_time']=='19:00' and value['deadline'] is None
    assert ref['items'] and all(i['start_at']>='2026-10-14T19:00' for i in ref['items'])
    assert ref['unresolved'] and ref['field_sources']['title']=='conversation_context'
    assert call(client,'/api/tasks')==[]
    denied=client.post(f"/api/workspace/drafts/planning/{ref['id']}/confirm",json={'expected_version':ref['version']})
    assert denied.status_code==422
    raw=call(client,f"/api/workspace/drafts/planning/{ref['id']}")
    assert raw['id']==ref['id'] and raw['content']['schedule']['deadline'] is None


def test_minimal_draft_is_editable_but_placeholder_not_confirmable(client,defaults_chat):
    ref=ref_of(send(client,defaults_chat,'帮我安排一下学习'))
    assert ref['content']['schedule']['duration_minutes']==60
    assert ref['content']['schedule']['title']=='待命名任务'
    assert ref['content']['schedule']['start_time']=='09:00'
    assert len(ref['unresolved'])==2


def test_same_draft_chat_edits_breaks_version_and_receipt(client,defaults_chat):
    sid=defaults_chat
    ref=ref_of(send(client,sid,'今晚帮我安排操作系统作业，90分钟'))
    from tests.test_workspace_stage2 import wait
    def edit(text,key,old):
        run=call(client,f'/api/conversations/{sid}/runs',{'client_message_id':key,'text':text,
            'draft_versions':[{'kind':'planning','id':old['id'],'version':old['version']}]})
        return ref_of(wait(client,sid,run['id']))
    changed=edit('改成晚上八点，两个小时','edit',ref)
    assert changed['id']==ref['id'] and changed['version']!=ref['version']
    assert changed['content']['schedule']['duration_minutes']==120
    assert changed['content']['schedule']['start_time']=='20:00'
    split=edit('分成两段，每段45分钟，中间休息十分钟','split',changed)
    assert split['id']==ref['id'] and split['content']['schedule']['duration_minutes']==90
    assert len(split['items'])==2
    a,b=split['items']
    assert (datetime.fromisoformat(b['start_at'])-datetime.fromisoformat(a['end_at'])).total_seconds()==600
    stale=client.patch(f"/api/workspace/drafts/planning/{ref['id']}",json={'expected_version':ref['version'],'content':ref['content']})
    assert stale.status_code==409
    final=edit('截止今晚22点','deadline',split)
    assert final['status']=='ready' and not final['unresolved']
    assert final['content']['schedule']['start_time']=='20:00'
    assert call(client,'/api/tasks')==[]
    saved=call(client,f"/api/workspace/drafts/planning/{ref['id']}/confirm",{'expected_version':final['version']})
    again=call(client,f"/api/workspace/drafts/planning/{ref['id']}/confirm",{'expected_version':final['version']})
    assert saved['receipt']==again['receipt'] and len(call(client,'/api/tasks'))==1


@pytest.mark.parametrize('failure',['AI_RESPONSE_INVALID','AI_UNAVAILABLE'])
def test_invalid_plan_repaired_once_then_trusted_fallback(client,defaults_chat,monkeypatch,failure):
    attempts=[]
    async def invalid(request):attempts.append(request);raise claude_client.AIServiceError(failure)
    monkeypatch.setattr(conversation_tools,'plan',invalid)
    result=send(client,defaults_chat,'今晚有个操作系统作业，90分钟，帮我安排一下')
    ref=ref_of(result)
    assert len(attempts)==(2 if failure=='AI_RESPONSE_INVALID' else 1)
    assert ref['content']['schedule']['title']=='操作系统作业'
    assert result['content']['tools'][-1]['fallback']=='trusted_defaults'
    assert call(client,'/api/tasks')==[]


def test_after_21_no_past_or_silent_tomorrow(client,defaults_chat,monkeypatch):
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-14T21:01:00+08:00'))
    # Modules normally import the function once; patch both trusted clock aliases.
    monkeypatch.setattr(conversation_tools,'assistant_now',assistant_clock.assistant_now)
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业，90分钟'))
    assert ref['content']['schedule']['day']=='2026-10-14'
    assert not ref['items'] and ref['diagnostics']
    assert any('剩余' in note for note in ref['notices'])


def test_course_conflict_no_overlap(client,defaults_chat):
    call(client,'/api/time-rules',{'title':'匿名课程','kind':'course','recurrence':'once','date':'2026-10-14','start_time':'19:00','end_time':'20:00'})
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业，90分钟'))
    assert ref['items'] and all(item['start_at']>='2026-10-14T20:00' for item in ref['items'])


def test_review_default_blank_and_real_sources(client,defaults_chat):
    ref=ref_of(send(client,defaults_chat,'帮我复盘一下'))
    assert ref['kind']=='review_record' and ref['content']['period']=='week'
    assert ref['content']['title']=='本周学习复盘'
    assert ref['content']['conclusion']=='' and ref['content']['next_steps']==''
    assert call(client,'/api/reviews/records')['items']==[]


@pytest.mark.parametrize('text',['先别安排，我只是问问。','如果晚上七点学习怎么样？','今天有点累。'])
def test_fallback_never_grants_permission(client,defaults_chat,text):
    result=send(client,defaults_chat,text)
    assert not result['content']['tools']
    assert call(client,'/api/tasks')==[]


def test_defaults_priority_and_preference_provenance():
    now=datetime.fromisoformat('2026-10-14T18:50:00+08:00')
    request={'message':'大概一个半小时，你帮我安排一下','history':[{'role':'user','text':'今晚写操作系统作业'}]}
    value,sources=draft_defaults.schedule(request,now,preferences={'task_windows':{'*':[{'start':'20:00','end':'22:00','weekdays':[3]}]}})
    assert value.duration_minutes==90 and sources['duration_minutes']=='user_explicit'
    assert value.start_time=='20:00' and sources['start_time']=='confirmed_preference'
    value,sources=draft_defaults.schedule({**request,'message':'改成晚上八点，两个小时'},now,base=value.model_dump(mode='json'),sources=sources)
    assert value.start_time=='20:00' and value.duration_minutes==120 and sources['start_time']=='user_explicit'
    assert value.title=='操作系统作业'


def test_provider_invalid_json_reproduces_real_planner_failure_and_recovers(client,defaults_chat,monkeypatch):
    requests=[]
    async def invalid(prompt,*args):requests.append(json.loads(prompt));return '{"calls": [{"name": "planning_draft"}'
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    monkeypatch.setattr(claude_client,'request_claude',invalid)
    monkeypatch.setattr(conversation_tools,'plan',real_plan)
    ref=ref_of(send(client,defaults_chat,'今晚帮我安排操作系统作业，90分钟'))
    assert len(requests)==2 and requests[1]['decision_feedback']['code']=='INVALID_TOOL_PLAN'
    assert ref['items'] and ref['id']>0


def test_invalid_tool_arguments_do_not_feed_model_text_into_fallback(client,defaults_chat,monkeypatch):
    async def invalid(request):return ToolPlan(calls=[{'name':'planning_draft','arguments':{'actions':['invented SQL']}}])
    monkeypatch.setattr(conversation_tools,'plan',invalid)
    result=send(client,defaults_chat,'今晚帮我安排操作系统作业，90分钟')
    ref=ref_of(result)
    assert ref['content']['schedule']['title']=='操作系统作业'
    assert result['content']['tools'][0]['error']=='INVALID_TOOL_ARGUMENTS'
    assert result['content']['tools'][0]['recovered_by']=='trusted_defaults'


def test_uncoordinated_or_stale_chat_edit_keeps_original(client,defaults_chat):
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业，90分钟'))
    result=send(client,defaults_chat,'改成晚上八点，两个小时','uncoordinated')
    assert result['content']['tools'][-1]['error']=='DRAFT_COORDINATION_REQUIRED'
    assert call(client,f"/api/workspace/drafts/planning/{ref['id']}")['version']==ref['version']


def test_business_receipt_keeps_draft_query_and_context_without_second_narration(client,defaults_chat,monkeypatch):
    async def planning(request):return ToolPlan(calls=[{'name':'tasks'},{'name':'planning_draft'}])
    async def partial(request):
        raise AssertionError('persisted business results must not be narrated by another model')
        yield
    monkeypatch.setattr(conversation_tools,'plan',planning)
    monkeypatch.setattr(conversation_runs,'reply_events',partial)
    result=send(client,defaults_chat,'今晚安排操作系统作业，90分钟')
    assert result['status']=='completed' and '已生成' in result['delta'] and '尚未' in result['delta']
    assert result['content']['tools'][0]['tool']=='tasks'
    ref=result['content']['tools'][1]['draft']
    assert ref['id']>0 and call(client,'/api/tasks')==[]
    history=call(client,f'/api/conversations/{defaults_chat}/messages')['items']
    assert any(m['role']=='user' and '操作系统作业' in m['text'] for m in history)


def test_same_form_edit_retry_and_discard_never_writes_task(client,defaults_chat):
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业，90分钟'))
    content=ref['content'];content['schedule']['duration_minutes']=60
    body={'expected_version':ref['version'],'content':content}
    first=client.patch(f"/api/workspace/drafts/planning/{ref['id']}",json=body)
    assert first.status_code==200,first.text
    second=client.patch(f"/api/workspace/drafts/planning/{ref['id']}",json=body)
    assert second.json()['version']==first.json()['version']
    discarded=call(client,f"/api/workspace/drafts/planning/{ref['id']}/discard",{'expected_version':first.json()['version']})
    assert discarded['status']=='discarded' and call(client,'/api/tasks')==[]


def test_existing_named_task_is_reused_without_overwriting_duration(client,defaults_chat):
    task=call(client,'/api/tasks',{'title':'操作系统作业','duration_minutes':90,'priority':'high','deadline':'2026-10-16T20:00:00+08:00'})
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业'))
    value=ref['content']['schedule']
    assert value['task_id']==task['id'] and value['duration_minutes']==90 and value['priority']=='high'
    assert ref['field_sources']['duration_minutes']=='formal_task'
    assert len(call(client,'/api/tasks'))==1


def test_task_breakdown_can_keep_empty_deadline_without_formal_write(client,defaults_chat,monkeypatch):
    async def choose(request):return ToolPlan(calls=[{'name':'breakdown_draft','arguments':{}}])
    from app.services import assistant_ai
    async def unavailable(*args):raise claude_client.AIServiceError('AI_UNAVAILABLE')
    monkeypatch.setattr(assistant_ai,'decompose_task',unavailable)
    monkeypatch.setattr(conversation_tools,'plan',choose)
    ref=ref_of(send(client,defaults_chat,'帮我拆解软件工程报告'))
    assert ref['content']['parent']['deadline'] is None and ref['unresolved']
    assert ref['content']['children']==[]
    assert call(client,'/api/tasks')==[]


def test_short_eight_oclock_edit_keeps_evening_context_and_confirm_phrase_is_readonly(client,defaults_chat):
    from tests.test_workspace_stage2 import wait
    ref=ref_of(send(client,defaults_chat,'今晚安排操作系统作业，90分钟'))
    run=call(client,f'/api/conversations/{defaults_chat}/runs',{'client_message_id':'eight','text':'改成八点开始',
        'draft_versions':[{'kind':'planning','id':ref['id'],'version':ref['version']}]})
    changed=ref_of(wait(client,defaults_chat,run['id']))
    assert changed['content']['schedule']['start_time']=='20:00'
    final=ref_of(send(client,defaults_chat,'就用这个方案','confirm-phrase'))
    assert final['id']==ref['id'] and final['version']==changed['version']
    assert call(client,'/api/tasks')==[]


def test_failed_first_reply_does_not_drop_user_homework_context(client,defaults_chat,monkeypatch):
    async def broken(request):raise claude_client.AIServiceError('AI_UNAVAILABLE');yield
    monkeypatch.setattr(conversation_runs,'reply_events',broken)
    assert send(client,defaults_chat,'操作系统作业，今晚完成。','first')['status']=='failed'
    ref=ref_of(send(client,defaults_chat,'大概一个半小时，你帮我安排一下。','second'))
    assert ref['content']['schedule']['title']=='操作系统作业' and ref['content']['schedule']['duration_minutes']==90


def test_stop_during_solver_prevents_late_draft_persistence(client,defaults_chat,monkeypatch,test_engine):
    from sqlalchemy.orm import Session
    from sqlalchemy import select
    from app.models import AssistantRun,AssistantProposal
    from app.services import schedule_preview
    original=schedule_preview.calculate
    def stop_inside(*args,**kwargs):
        value=original(*args,**kwargs)
        with Session(test_engine) as db:
            run=db.scalar(select(AssistantRun).where(AssistantRun.session_id==defaults_chat))
            run.status='cancelled';db.commit()
        return value
    monkeypatch.setattr(schedule_preview,'calculate',stop_inside)
    result=send(client,defaults_chat,'今晚安排操作系统作业，90分钟')
    assert result['status']=='cancelled'
    with Session(test_engine) as db:assert db.scalar(select(AssistantProposal)) is None


def test_task_skill_does_not_duplicate_existing_formal_title(client,defaults_chat,monkeypatch):
    call(client,'/api/tasks',{'title':'软件工程报告','duration_minutes':60,'deadline':'2026-10-16T20:00:00+08:00'})
    async def choose(request):return ToolPlan(calls=[{'name':'breakdown_draft','arguments':{'title':'软件工程报告'}}])
    monkeypatch.setattr(conversation_tools,'plan',choose)
    result=send(client,defaults_chat,'帮我拆解软件工程报告')
    assert result['content']['tools'][0]['error']=='TASK_ALREADY_EXISTS'
    assert len(call(client,'/api/tasks'))==1


def test_task_model_cannot_invent_child_deadline_when_user_gave_none(client,defaults_chat,monkeypatch):
    from app.services import assistant_ai
    async def choose(request):return ToolPlan(calls=[{'name':'breakdown_draft','arguments':{'title':'报告'}}])
    async def invent(request,now):return {'parent':{'title':request['title'],'deadline':None},
        'children':[{'title':'步骤','deadline':'2026-10-16T20:00:00+08:00','duration_minutes':60,'sort_order':0}]}
    monkeypatch.setattr(conversation_tools,'plan',choose);monkeypatch.setattr(assistant_ai,'decompose_task',invent)
    ref=ref_of(send(client,defaults_chat,'帮我拆解报告'))
    assert ref['content']['children']==[] and ref['content']['parent']['deadline'] is None
