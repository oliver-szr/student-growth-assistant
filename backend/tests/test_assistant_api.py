from datetime import datetime
import uuid
import pytest


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch):
    from app.services import assistant_clock
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-07T18:00:00+08:00'))


def session(client):
    r=client.post('/api/assistant/sessions',json={})
    assert r.status_code==201
    return r.json()['id']


def new_action(title='实验报告'):
    return dict(op='add',fields=dict(title=title,duration_minutes=120,deadline='2026-10-09T20:00:00+08:00',priority='normal'))


def proposal(client,sid,actions):
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id=str(uuid.uuid4()),text='手动录入',actions=actions))
    assert r.status_code==200,r.text
    return r.json()


def test_candidate_confirm_atomic_and_idempotent(client):
    sid=session(client)
    p=proposal(client,sid,[new_action()])
    assert p['status']=='ready',p
    assert client.get('/api/tasks').json()==[]
    r=client.post(f"/api/assistant/proposals/{p['id']}/confirm")
    assert r.status_code==200,r.text
    tasks=client.get('/api/tasks').json()
    assert len(tasks)==1 and tasks[0]['title']=='实验报告'
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    assert len(client.get('/api/tasks').json())==1
    restored=client.get(f'/api/assistant/sessions/{sid}').json()
    assert restored['proposal']['status']=='applied'
    assert restored['tasks'][0]['deadline'].startswith('2026-10-09')


def test_duplicate_message_and_discard_do_not_write_tasks(client):
    sid=session(client)
    body=dict(client_message_id='unique',text='录入',actions=[new_action()])
    p=client.post(f'/api/assistant/sessions/{sid}/messages',json=body).json()
    again=client.post(f'/api/assistant/sessions/{sid}/messages',json=body).json()
    assert again['id']==p['id']
    assert client.post(f"/api/assistant/proposals/{p['id']}/discard").status_code==200
    assert client.get('/api/tasks').json()==[]
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==409


def test_stale_candidate_and_time_advance_are_rejected(client,monkeypatch):
    sid=session(client); p=proposal(client,sid,[new_action()])
    client.post('/api/tasks',json=new_action('其他')['fields'])
    r=client.post(f"/api/assistant/proposals/{p['id']}/confirm")
    assert r.status_code==409 and r.json()['detail']['code']=='STALE_CANDIDATE'
    p=proposal(client,sid,[new_action()])
    from app.services import assistant_clock
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-09T21:00:00+08:00'))
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==409
    assert len(client.get('/api/tasks').json())==1


def test_missing_information_and_two_adds(client):
    sid=session(client)
    p=proposal(client,sid,[dict(op='add',fields=dict(title='报告'))])
    assert p['status']=='needs_input'
    assert p['questions']
    assert client.get('/api/tasks').json()==[]
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id='two',text='两个',actions=[new_action(),new_action('其他')]))
    assert r.status_code==422


def test_off_grid_unknown_target_and_lock_require_confirmation(client):
    sid=session(client)
    a=new_action(); a['fields']['duration_minutes']=43
    p=proposal(client,sid,[a]); assert p['status']=='needs_input'
    p=proposal(client,sid,[dict(op='update',target='task:999',fields=dict(priority='high'))])
    assert p['status']=='needs_input'


def test_ai_unavailable_keeps_message_and_offers_manual_entry(client):
    sid=session(client)
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id='noai',text='明天要交报告'))
    assert r.status_code==200
    assert r.json()['status']=='needs_input'
    assert r.json()['ai_error']=='AI_NOT_CONFIGURED'
    assert client.get('/api/tasks').json()==[]


def test_reject_add_with_existing_task_ref(client):
    sid=session(client)
    a=new_action();a['target']='task:1'
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id='badref',text='新增',actions=[a]))
    assert r.status_code==422


def test_new_done_task_requires_complete_information(client):
    sid=session(client)
    p=proposal(client,sid,[dict(op='add',fields=dict(title='报告',status='done'))])
    assert p['status']=='needs_input'
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==409


def test_personal_preferences_are_editable_and_versioned(client):
    first=client.get('/api/assistant/preferences')
    assert first.status_code==200
    assert first.json()['is_sample'] is True
    assert first.json()['task_windows']['writing']
    body={'task_windows':{'writing':[{'start':'08:00','end':'12:00'}],'reading':[{'start':'19:00','end':'22:00'}]},'avoid_windows':[],'deadline_buffer_hours':24,'adjustment_mode':'balanced'}
    saved=client.put('/api/assistant/preferences',json=body)
    assert saved.status_code==200,saved.text
    assert saved.json()['is_sample'] is False
    assert client.get('/api/assistant/preferences').json()['task_windows']['writing']==body['task_windows']['writing']


def test_invalid_personal_preference_does_not_overwrite_saved_value(client):
    original=client.get('/api/assistant/preferences').json()
    result=client.put('/api/assistant/preferences',json={'task_windows':{'writing':[{'start':'22:00','end':'08:00'}]},'avoid_windows':[],'deadline_buffer_hours':24,'adjustment_mode':'balanced'})
    assert result.status_code==422
    assert client.get('/api/assistant/preferences').json()==original


def test_ai_run_is_idempotent_and_returns_a_verified_recommendation(client,monkeypatch):
    import time
    from app.services import assistant_ai
    from app.assistant_schemas import ParsedCommand,Action,Fields
    calls=[]
    async def parse(text,context):
        calls.append(text)
        return ParsedCommand(actions=[Action(op='add',fields=Fields(title='写作任务',duration_minutes=60,deadline='2026-10-11T22:00:00+08:00',priority='normal',task_type='writing'))])
    async def recommend(payload): return {'candidate_id':payload['candidate_options'][0]['candidate_id'],'reason_codes':['follows_task_window']}
    monkeypatch.setattr(assistant_ai,'parse_message',parse); monkeypatch.setattr(assistant_ai,'recommend',recommend)
    sid=session(client); body={'client_message_id':'run-once','text':'周日晚上前完成写作任务，一小时'}
    first=client.post(f'/api/assistant/sessions/{sid}/runs',json=body)
    assert first.status_code==202,first.text
    duplicate=client.post(f'/api/assistant/sessions/{sid}/runs',json=body)
    assert duplicate.json()['id']==first.json()['id']
    result=None
    for _ in range(100):
        result=client.get(f"/api/assistant/runs/{first.json()['id']}").json()
        if result['status']!='running': break
        time.sleep(.01)
    assert result['status']=='completed',result
    restored=client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    assert restored['status']=='ready'
    assert restored['recommendation']['source']=='ai'
    assert restored['selected_candidate_id'] in {x['candidate_id'] for x in restored['candidate_options']}
    assert 1<=len(restored['candidate_options'])<=3
    assert len({str(x['items']) for x in restored['candidate_options']})==len(restored['candidate_options'])
    assert len(calls)==1
    assert client.get('/api/tasks').json()==[]
    option=next((x for x in restored['candidate_options'] if x['candidate_id']!=restored['selected_candidate_id']),restored['candidate_options'][0])
    selected=client.post(f"/api/assistant/proposals/{restored['id']}/preview",json={'candidate_id':option['candidate_id']})
    assert selected.status_code==200 and selected.json()['selected_candidate_id']==option['candidate_id']
    assert selected.json()['recommendation']['source']=='user_selected'
    assert selected.json()['recommendation']['reason_text']==[]
    assert client.post(f"/api/assistant/proposals/{restored['id']}/confirm").status_code==200
    assert client.get('/api/tasks').json()[0]['title']=='写作任务'
    assert client.get(f'/api/assistant/sessions/{sid}').json()['tasks'][0]['task_type']=='writing'
    assert client.get(f'/api/assistant/preferences').json()['is_sample'] is True


def test_personal_preference_change_is_only_saved_after_confirmation(client,monkeypatch):
    from app.services import assistant_ai
    from app.assistant_schemas import ParsedCommand,PreferencePatch
    async def parse(text,context):return ParsedCommand(preference_updates=PreferencePatch(deadline_buffer_hours=12))
    async def recommend(payload):return {'candidate_id':payload['candidate_options'][0]['candidate_id'],'reason_codes':[]}
    monkeypatch.setattr(assistant_ai,'parse_message',parse); monkeypatch.setattr(assistant_ai,'recommend',recommend)
    sid=session(client); body={'client_message_id':'pref-only','text':'以后重要任务提前半天安排'}
    started=client.post(f'/api/assistant/sessions/{sid}/runs',json=body).json()
    import time
    for _ in range(100):
        result=client.get(f"/api/assistant/runs/{started['id']}").json()
        if result['status']!='running':break
        time.sleep(.01)
    assert result['status']=='completed'
    assert client.get('/api/assistant/preferences').json()['is_sample'] is True
    proposal=client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    assert proposal['preference_updates']['settings']['deadline_buffer_hours']==12
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code==200
    saved=client.get('/api/assistant/preferences').json()
    assert saved['is_sample'] is False and saved['deadline_buffer_hours']==12


def test_temporary_no_study_window_changes_candidate_but_is_not_saved(client,monkeypatch):
    from app.services import assistant_ai
    from app.assistant_schemas import ParsedCommand,Action,Fields,TemporaryPreferences,DateTimeWindow
    async def parse(text,context):
        return ParsedCommand(actions=[Action(op='add',fields=Fields(title='临时任务',duration_minutes=60,deadline='2026-10-08T23:00:00+08:00',priority='normal',task_type='writing'))],temporary_preferences=TemporaryPreferences(blocked_windows=[DateTimeWindow(start_at='2026-10-07T19:00:00+08:00',end_at='2026-10-07T22:00:00+08:00')]))
    async def recommend(payload):return {'candidate_id':payload['candidate_options'][0]['candidate_id'],'reason_codes':[]}
    monkeypatch.setattr(assistant_ai,'parse_message',parse);monkeypatch.setattr(assistant_ai,'recommend',recommend)
    sid=session(client);started=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':'temporary-evening','text':'今晚不学习，帮我安排临时任务'}).json()
    import time
    for _ in range(100):
        result=client.get(f"/api/assistant/runs/{started['id']}").json()
        if result['status']!='running':break
        time.sleep(.01)
    assert result['status']=='completed',result
    proposal=client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    assert proposal['temporary_preferences']['blocked_windows'][0]['start_at'].startswith('2026-10-07T19:00')
    assert all(not (x['start_at']<'2026-10-07T22:00:00+08:00' and x['end_at']>'2026-10-07T19:00:00+08:00') for x in proposal['items'])
    assert client.get('/api/assistant/preferences').json()['is_sample'] is True


def test_cancelled_ai_run_does_not_publish_a_candidate(client,monkeypatch):
    import asyncio
    from app.services import assistant_ai
    async def slow_parse(text,context):await asyncio.sleep(1)
    monkeypatch.setattr(assistant_ai,'parse_message',slow_parse)
    sid=session(client);started=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':'cancel-run','text':'重新安排这周'}).json()
    stopped=client.post(f"/api/assistant/runs/{started['id']}/cancel")
    assert stopped.status_code==200 and stopped.json()['status']=='cancelled'
    assert client.get(f'/api/assistant/sessions/{sid}').json()['proposal'] is None


def test_new_task_can_be_locked_while_still_in_a_candidate(client):
    sid=session(client);p=proposal(client,sid,[new_action()])
    draft=next(t for t in p['tasks'] if t['title']=='实验报告')
    locked=client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'actions':[dict(op='update',target=draft['ref'],fields={'profile':{'locked':True}})]})
    assert locked.status_code==200 and locked.json()['status']=='ready',locked.text
    confirmed=client.post(f"/api/assistant/proposals/{locked.json()['id']}/confirm")
    assert confirmed.status_code==200,confirmed.text


def test_async_run_rejects_oversized_message_and_id(client):
    sid=session(client)
    long_message=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':'too-long-text','text':'x'*2001})
    long_id=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':'x'*101,'text':'重新安排本周'})
    assert long_message.status_code==422
    assert long_id.status_code==422
    assert client.get(f'/api/assistant/sessions/{sid}').json()['runs']==[]


def test_completed_started_task_keeps_its_original_block(client,test_engine):
    from sqlalchemy.orm import Session
    from app.models import Plan,PlanItem,Task
    r=client.post('/api/tasks',json=new_action('正在做')['fields']);tid=r.json()['id']
    with Session(test_engine) as db:
        p=Plan(week_start=datetime(2026,10,5).date(),status='confirmed',source_revision=0,task_ids=[tid]);db.add(p);db.flush()
        db.add(PlanItem(plan_id=p.id,kind='task',task_id=tid,title_snapshot='正在做',start_at=datetime.fromisoformat('2026-10-07T17:00:00+08:00'),end_at=datetime.fromisoformat('2026-10-07T19:00:00+08:00')));db.commit()
    sid=session(client);p=proposal(client,sid,[dict(op='update',target=f'task:{tid}',fields=dict(status='done'))])
    assert p['status']=='ready'
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    d=client.get(f'/api/assistant/sessions/{sid}').json()
    assert d['confirmed_items'][0]['start_at']=='2026-10-07T17:00:00+08:00'


def test_required_nulls_are_rejected_not_500(client):
    sid=session(client)
    a=new_action();a['fields']['priority']=None
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json=dict(client_message_id='null',text='报告',actions=[a]))
    assert r.status_code==422


def test_cancel_future_task_has_explicit_removal(client,test_engine):
    from sqlalchemy.orm import Session
    from app.models import Plan,PlanItem
    r=client.post('/api/tasks',json=new_action()['fields']);tid=r.json()['id']
    with Session(test_engine) as db:
        plan=Plan(week_start=datetime(2026,10,5).date(),status='confirmed',source_revision=0,task_ids=[tid]);db.add(plan);db.flush()
        db.add(PlanItem(plan_id=plan.id,kind='task',task_id=tid,title_snapshot='实验报告',start_at=datetime.fromisoformat('2026-10-08T19:00:00+08:00'),end_at=datetime.fromisoformat('2026-10-08T21:00:00+08:00')));db.commit()
    sid=session(client);p=proposal(client,sid,[dict(op='update',target=f'task:{tid}',fields=dict(status='cancelled'))])
    assert p['status']=='ready'
    assert p['changes'][0]['kind']=='removed'
    assert p['removed_refs']==[f'task:{tid}']


def test_followup_run_inherits_pending_preferences_and_temporary_requirements(client,monkeypatch):
    import time
    from app.services import assistant_ai
    from app.assistant_schemas import ParsedCommand,Action,Fields,PreferencePatch,TemporaryPreferences,DateTimeWindow
    parsed_calls=[]
    async def parse(text,context):
        parsed_calls.append(context)
        if len(parsed_calls)==1:
            return ParsedCommand(actions=[Action(op='add',fields=Fields(title='连续编辑任务',duration_minutes=60,deadline='2026-10-11T20:00:00+08:00',priority='normal',task_type='writing'))],preference_updates=PreferencePatch(task_windows={'writing':[{'start':'08:00','end':'12:00'}]}),temporary_preferences=TemporaryPreferences(blocked_windows=[DateTimeWindow(start_at='2026-10-07T19:00:00+08:00',end_at='2026-10-07T22:00:00+08:00')]))
        assert context['current_candidate']['items']
        return ParsedCommand(actions=[Action(op='update',target=context['current_candidate']['tasks'][0]['ref'],fields=Fields(duration_minutes=90))])
    async def recommend(payload):return {'candidate_id':payload['candidate_options'][0]['candidate_id'],'reason_codes':[]}
    monkeypatch.setattr(assistant_ai,'parse_message',parse);monkeypatch.setattr(assistant_ai,'recommend',recommend)
    sid=session(client)
    def run(message,client_id):
        started=client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':client_id,'text':message}).json()
        for _ in range(300):
            state=client.get(f"/api/assistant/runs/{started['id']}").json()
            if state['status']!='running':break
            time.sleep(.01)
        assert state['status']=='completed',state
        return client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    first=run('新增写作任务，并记住上午偏好；今晚不学习','inherit-1')
    second=run('把这个任务增加半小时','inherit-2')
    assert parsed_calls[1]['current_candidate']['selected_candidate_id']==first['selected_candidate_id']
    assert second['preference_updates']['settings']['task_windows']['writing'][0]['start']=='08:00'
    assert second['temporary_preferences']['blocked_windows'][0]['start_at'].startswith('2026-10-07T19:00')
    assert client.get('/api/assistant/preferences').json()['is_sample'] is True


def test_balanced_reason_requires_real_cross_candidate_tradeoff():
    from app.routers.assistant import _reason_codes
    option={'candidate_id':'balanced:0','strategy':'balanced','metrics':{'changed_tasks_weight':0,'preference_misses_weight':3,'avoided_tasks_weight':0,'temporary_avoided_tasks_weight':0,'deadline_buffer_shortfall_hours':0}}
    assert _reason_codes(['balanced_tradeoff'],option,[option],{})==[]
    other={'candidate_id':'preference:0','strategy':'preference','metrics':{'changed_tasks_weight':0,'preference_misses_weight':0,'avoided_tasks_weight':0,'temporary_avoided_tasks_weight':0,'deadline_buffer_shortfall_hours':12}}
    assert 'balanced_tradeoff' in _reason_codes(['balanced_tradeoff'],option,[option,other],{})


def test_manual_preview_retry_is_idempotent(client):
    sid=session(client);p=proposal(client,sid,[new_action()])
    body={'client_message_id':'preview-retry','actions':[dict(op='add',fields=new_action('其他')['fields'])]}
    a=client.post(f"/api/assistant/proposals/{p['id']}/preview",json=body)
    b=client.post(f"/api/assistant/proposals/{p['id']}/preview",json=body)
    assert a.status_code==200,a.text
    assert b.json()['id']==a.json()['id']
    assert sum(x['op']=='add' for x in b.json()['actions'])==2


def test_stale_candidate_cannot_be_rebased_by_preview_and_overwrite_external_edit(client):
    task=client.post('/api/tasks',json=new_action()['fields']).json()
    sid=session(client)
    p=proposal(client,sid,[dict(op='update',target=f"task:{task['id']}",fields={'title':'候选中的旧标题','profile':{'fixed_start':'2026-10-08T19:00:00+08:00'}})])
    assert p['status']=='ready'
    updated=client.patch(f"/api/tasks/{task['id']}",json={'title':'任务管理页的新标题'})
    assert updated.status_code==200
    session_state=client.get(f'/api/assistant/sessions/{sid}').json()
    assert session_state['proposal']['status']=='stale'
    r=client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'actions':[dict(op='update',target=f"task:{task['id']}",fields={'profile':{'fixed_start':'2026-10-08T19:30:00+08:00'}})]})
    assert r.status_code==409
    assert r.json()['detail']['code']=='STALE_CANDIDATE'
    assert client.get('/api/tasks').json()[0]['title']=='任务管理页的新标题'


def test_chat_after_stale_candidate_starts_from_current_task_data(client):
    task=client.post('/api/tasks',json=new_action()['fields']).json()
    sid=session(client)
    p=proposal(client,sid,[dict(op='update',target=f"task:{task['id']}",fields={'title':'候选中的旧标题','profile':{'fixed_start':'2026-10-08T19:00:00+08:00'}})])
    assert p['status']=='ready'
    assert client.patch(f"/api/tasks/{task['id']}",json={'title':'最新任务名称'}).status_code==200
    refreshed=proposal(client,sid,[dict(op='update',target=f"task:{task['id']}",fields={'profile':{'fixed_start':'2026-10-08T19:00:00+08:00'}})])
    assert refreshed['status']=='ready'
    assert next(t for t in refreshed['tasks'] if t['ref']==f"task:{task['id']}")['title']=='最新任务名称'
    action=next(a for a in refreshed['actions'] if a['target']==f"task:{task['id']}")
    assert 'title' not in action['fields']
    assert client.post(f"/api/assistant/proposals/{refreshed['id']}/confirm").status_code==200
    assert client.get('/api/tasks').json()[0]['title']=='最新任务名称'


def test_unmet_soft_preference_is_visible(client):
    client.post('/api/time-rules',json=dict(kind='protected',title='不能安排',recurrence='once',date='2026-10-08',start_time='14:00',end_time='18:00'))
    sid=session(client);a=new_action()
    a['fields']['profile']={'preferred_windows':[{'start_at':'2026-10-08T14:00:00+08:00','end_at':'2026-10-08T18:00:00+08:00'}]}
    p=proposal(client,sid,[a])
    assert p['status']=='ready'
    assert len(p['unmet_preferences'])==1
    assert p['unmet_preferences'][0]['title']=='实验报告'


def test_assistant_memory_uses_shanghai_deadline_and_move_keeps_ddl(client):
    r=client.post('/api/tasks',json=new_action()['fields']);tid=r.json()['id']
    sid=session(client)
    data=client.get(f'/api/assistant/sessions/{sid}').json()
    assert data['tasks'][0]['deadline']=='2026-10-09T20:00:00+08:00'
    p=proposal(client,sid,[dict(op='update',target=f'task:{tid}',fields={'profile':{'fixed_start':'2026-10-08T19:00:00+08:00'}})])
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    data=client.get(f'/api/assistant/sessions/{sid}').json()
    assert data['tasks'][0]['deadline']=='2026-10-09T20:00:00+08:00'
def test_profile_workspace_chat_requires_confirmation_before_saving(client, monkeypatch):
    from app.services import assistant_ai

    async def profile_reply(scope, text, context):
        assert scope == "profile"
        return {"reply": "我理解你想修改长期方向。", "questions": [], "operations": [{"op": "set_direction", "direction": "准备保研"}]}

    monkeypatch.setattr(assistant_ai, "workspace_message", profile_reply)
    opened = client.post("/api/assistant/sessions/open", json={"scope": "profile"}).json()
    run = client.post(f"/api/assistant/sessions/{opened['id']}/runs", json={"client_message_id": "profile-chat-1", "text": "我的长期方向改为准备保研"}).json()
    for _ in range(30):
        state = client.get(f"/api/assistant/runs/{run['id']}").json()
        if state["status"] != "running":
            break
        import time; time.sleep(.03)
    session = client.get(f"/api/assistant/sessions/{opened['id']}").json()
    assert session["draft"]["operations"][0]["direction"] == "准备保研"
    assert client.get("/api/growth/profile").json()["direction"] == ""
    saved = client.post(f"/api/assistant/drafts/{session['draft']['id']}/confirm")
    assert saved.status_code == 200
    assert client.get("/api/growth/profile").json()["direction"] == "准备保研"


def test_profile_workspace_can_create_a_goal_as_a_confirmable_draft(client, monkeypatch):
    from app.services import assistant_ai

    async def profile_reply(scope, text, context):
        return {"reply": "已整理目标，请核对。", "questions": [], "operations": [{
            "op": "create_goal", "title": "每周阅读", "motivation": "准备科研", "goal_type": "long_term",
            "priority": 1, "metric_kind": "count", "weekly_target": 2, "unit_label": "篇", "due_date": None, "status": "active",
        }]}

    monkeypatch.setattr(assistant_ai, "workspace_message", profile_reply)
    opened = client.post("/api/assistant/sessions/open", json={"scope": "profile"}).json()
    run = client.post(f"/api/assistant/sessions/{opened['id']}/runs", json={"client_message_id": "profile-goal-1", "text": "新建每周阅读两篇的目标"}).json()
    for _ in range(30):
        state = client.get(f"/api/assistant/runs/{run['id']}").json()
        if state["status"] != "running": break
        import time; time.sleep(.03)
    session = client.get(f"/api/assistant/sessions/{opened['id']}").json()
    assert client.post(f"/api/assistant/drafts/{session['draft']['id']}/confirm").status_code == 200
    goals = client.get("/api/goals").json()["goals"]
    assert len(goals) == 1 and goals[0]["title"] == "每周阅读"


def test_profile_workspace_applies_category_preference_and_goal_together(client, monkeypatch):
    from app.services import assistant_ai

    async def profile_reply(scope, text, context):
        assert scope == "profile"
        return {"reply": "我整理了类别、偏好和目标，请核对。", "questions": [], "operations": [
            {"op": "create_category", "name": "编程", "temp_ref": "draftcat:programming"},
            {"op": "create_preference_rule", "name": "编程尽量下午做", "description": "代码练习安排在下午。", "kind": "prefer_time", "category_ref": "draftcat:programming", "weekdays": None, "parameters": {"start": "14:00", "end": "18:00"}},
            {"op": "create_goal", "title": "每周编程练习", "motivation": "稳步提升", "goal_type": "long_term", "priority": 1, "metric_kind": "time", "weekly_target": 120, "unit_label": "分钟", "due_date": None, "status": "active"},
        ]}

    monkeypatch.setattr(assistant_ai, "workspace_message", profile_reply)
    opened = client.post("/api/assistant/sessions/open", json={"scope": "profile"}).json()
    run = client.post(f"/api/assistant/sessions/{opened['id']}/runs", json={"client_message_id": "profile-multi-change-1", "text": "新增编程类别、下午偏好和每周编程目标"}).json()
    import time
    for _ in range(50):
        state = client.get(f"/api/assistant/runs/{run['id']}").json()
        if state["status"] != "running": break
        time.sleep(.02)
    assert state["status"] == "completed", state
    session_data = client.get(f"/api/assistant/sessions/{opened['id']}").json()
    assert len(session_data["draft"]["changes"]) == 3
    categories_before = client.get("/api/task-categories").json()["categories"]
    assert all(item["name"] != "编程" for item in categories_before)
    saved = client.post(f"/api/assistant/drafts/{session_data['draft']['id']}/confirm")
    assert saved.status_code == 200, saved.text
    categories = client.get("/api/task-categories").json()["categories"]
    programming = next(item for item in categories if item["name"] == "编程")
    rules = client.get("/api/assistant/preference-rules").json()["rules"]
    programming_rule = next(item for item in rules if item["name"] == "编程尽量下午做")
    assert programming_rule["category_key"] == programming["key"]
    assert programming_rule["category_name"] == "编程"
    assert client.get("/api/assistant/preferences").json()["task_windows"][programming["key"]] == [{"start": "14:00", "end": "18:00"}]
    assert client.get("/api/goals").json()["goals"][0]["title"] == "每周编程练习"


def test_category_rename_keeps_rule_identity_and_duplicate_names_are_rejected(client):
    category = client.post("/api/task-categories", json={"name": "实验"})
    assert category.status_code == 201, category.text
    key = category.json()["key"]
    rule = client.post("/api/assistant/preference-rules", json={"name": "实验上午做", "description": "", "kind": "prefer_time", "category_key": key, "weekdays": [1, 3], "parameters": {"start": "08:00", "end": "12:00"}})
    assert rule.status_code == 201, rule.text
    renamed = client.patch(f"/api/task-categories/{key}", json={"name": "实验报告"})
    assert renamed.status_code == 200
    saved_rule = next(item for item in client.get("/api/assistant/preference-rules").json()["rules"] if item["id"] == rule.json()["id"])
    assert saved_rule["category_key"] == key and saved_rule["category_name"] == "实验报告"
    assert client.post("/api/task-categories", json={"name": "实验报告"}).status_code == 409


def test_review_workspace_chat_saves_confirmed_execution_feedback(client, monkeypatch):
    from app.services import assistant_ai
    from app.services.assistant_clock import assistant_now
    from datetime import timedelta

    task = client.post("/api/tasks", json={"title": "课程报告", "duration_minutes": 90, "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal"}).json()

    async def review_reply(scope, text, context):
        assert scope == "review"
        return {"reply": "我整理了一条执行反馈，请确认。", "questions": [], "operations": [{"op": "record_feedback", "task_id": task["id"], "outcome": "completed", "actual_minutes": 75}]}

    monkeypatch.setattr(assistant_ai, "workspace_message", review_reply)
    opened = client.post("/api/assistant/sessions/open", json={"scope": "review"}).json()
    run = client.post(f"/api/assistant/sessions/{opened['id']}/runs", json={"client_message_id": "review-chat-1", "text": "报告完成，用了75分钟"}).json()
    for _ in range(30):
        state = client.get(f"/api/assistant/runs/{run['id']}").json()
        if state["status"] != "running":
            break
        import time; time.sleep(.03)
    session = client.get(f"/api/assistant/sessions/{opened['id']}").json()
    assert session["draft"] is not None
    result = client.post(f"/api/assistant/drafts/{session['draft']['id']}/confirm")
    assert result.status_code == 200
    saved_tasks = client.get("/api/tasks").json()
    assert next(item for item in saved_tasks if item["id"] == task["id"])["status"] == "done"

def test_profile_draft_updates_existing_preference_fields_without_duplicate_keywords(client, monkeypatch):
    import time
    from app.services import assistant_ai
    rule=client.post('/api/assistant/preference-rules',json={'name':'写作上午','kind':'prefer_time','parameters':{'start':'08:00','end':'12:00'}}).json()
    async def reply(scope,text,context):
        return {'reply':'请核对','questions':[],'operations':[{'op':'update_preference_rule','id':rule['id'],'fields':{'name':'写作下午','parameters':{'start':'14:00','end':'17:00'}}}]}
    monkeypatch.setattr(assistant_ai,'workspace_message',reply)
    opened=client.post('/api/assistant/sessions/open',json={'scope':'profile'}).json()
    run=client.post(f"/api/assistant/sessions/{opened['id']}/runs",json={'client_message_id':'rename-rule-regression','text':'写作偏好改名并改时间'}).json()
    for _ in range(100):
        result=client.get(f"/api/assistant/runs/{run['id']}").json()
        if result['status']!='running':break
        time.sleep(.02)
    assert result['status']=='completed',result
    draft=client.get(f"/api/assistant/sessions/{opened['id']}").json()['draft']
    assert next(item for item in client.get('/api/assistant/preference-rules').json()['rules'] if item['id']==rule['id'])['name']=='写作上午'
    saved=client.post(f"/api/assistant/drafts/{draft['id']}/confirm")
    assert saved.status_code==200,saved.text
    updated=next(item for item in client.get('/api/assistant/preference-rules').json()['rules'] if item['id']==rule['id'])
    assert updated['name']=='写作下午' and updated['parameters']=={'start':'14:00','end':'17:00'}
    assert client.post(f"/api/assistant/drafts/{draft['id']}/confirm").status_code==200
def test_failed_schedule_does_not_report_formal_tasks_removed(client):
    sid=session(client)
    existing=new_action('原有会议')
    existing['fields'].update(duration_minutes=60,profile={'fixed_start':'2026-10-08T19:00:00+08:00'})
    first=proposal(client,sid,[existing])
    assert client.post(f"/api/assistant/proposals/{first['id']}/confirm").status_code==200
    incoming=new_action('紧急会议')
    incoming['fields'].update(duration_minutes=60,profile={'fixed_start':'2026-10-08T19:00:00+08:00'})
    failed=proposal(client,sid,[incoming])
    assert failed['status']!='ready'
    assert any(d['code']=='FIXED_TASK_CONFLICT' for d in failed['diagnostics'])
    assert failed['changes']==[]
    assert failed['removed_refs']==[]
    assert len(client.get(f'/api/assistant/sessions/{sid}').json()['confirmed_items'])==1
