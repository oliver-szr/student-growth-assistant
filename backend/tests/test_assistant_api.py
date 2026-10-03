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
    a=new_action(); a['fields']['duration_minutes']=45
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


def test_manual_preview_retry_is_idempotent(client):
    sid=session(client);p=proposal(client,sid,[new_action()])
    body={'client_message_id':'preview-retry','actions':[dict(op='add',fields=new_action('其他')['fields'])]}
    a=client.post(f"/api/assistant/proposals/{p['id']}/preview",json=body)
    b=client.post(f"/api/assistant/proposals/{p['id']}/preview",json=body)
    assert a.status_code==200,a.text
    assert b.json()['id']==a.json()['id']
    assert sum(x['op']=='add' for x in b.json()['actions'])==2


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
