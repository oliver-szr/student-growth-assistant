from datetime import datetime
from uuid import uuid4
from app.services import assistant_clock

def send(client,sid,actions):
    r=client.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':uuid4().hex,'text':'验证任务','actions':actions})
    assert r.status_code==200,r.text
    return r.json()

def test_split_crossweek_feedback_rollover_same_identity(client,monkeypatch):
    clock=[datetime.fromisoformat('2026-10-18T21:00:00+08:00')]
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:clock[0])
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    windows=[{'start_at':'2026-10-19T08:05:00+08:00','end_at':'2026-10-19T09:35:00+08:00'},{'start_at':'2026-10-20T08:05:00+08:00','end_at':'2026-10-20T09:35:00+08:00'}]
    p=send(client,sid,[{'op':'add','fields':{'title':'跨周报告','duration_minutes':180,'deadline':'2026-10-21T12:00:00+08:00','profile':{'splittable':True,'min_block_minutes':30,'max_segments':2,'allowed_windows':windows}}}])
    assert p['status']=='ready' and len(p['items'])==2
    assert client.get('/api/tasks').json()==[]
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    tasks=client.get('/api/tasks').json();assert len(tasks)==1
    task_id=tasks[0]['id']
    restored=client.get(f'/api/assistant/sessions/{sid}').json()
    assert len(restored['confirmed_items'])==2
    clock[0]=datetime.fromisoformat('2026-10-19T10:00:00+08:00')
    r=client.post(f'/api/tasks/{task_id}/feedback',json={'client_action_id':'partial-once','outcome':'partial','actual_minutes':60,'remaining_minutes':120,'occurred_at':clock[0].isoformat()})
    assert r.status_code==201,r.text
    assert client.post(f'/api/tasks/{task_id}/feedback',json={'client_action_id':'partial-once','outcome':'partial','actual_minutes':60,'remaining_minutes':120}).status_code==200
    sid2=client.post('/api/assistant/sessions',json={}).json()['id']
    p2=send(client,sid2,[{'op':'update','target':f'task:{task_id}','fields':{'profile':{'allowed_windows':[]}}}])
    assert p2['status']=='ready',p2
    assert sum((datetime.fromisoformat(x['end_at'])-datetime.fromisoformat(x['start_at'])).total_seconds()/60 for x in p2['items'])==120
    assert len(p2['retained'])==1
    assert client.post(f"/api/assistant/proposals/{p2['id']}/confirm").status_code==200
    assert len(client.get('/api/tasks').json())==1
    assert client.get(f'/api/tasks/{task_id}/feedback').json()['entries'][0]['cumulative_actual_minutes']==60

def test_confirmation_time_advance_rejects_both_weeks(client,monkeypatch):
    clock=[datetime.fromisoformat('2026-10-18T21:00:00+08:00')]
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:clock[0])
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    p=send(client,sid,[{'op':'add','fields':{'title':'短任务','duration_minutes':45,'deadline':'2026-10-21T12:00:00+08:00','profile':{'fixed_start':'2026-10-18T21:00:00+08:00'}}}])
    assert p['status']=='ready'
    clock[0]=datetime.fromisoformat('2026-10-18T21:05:00+08:00')
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==409
    assert client.get('/api/tasks').json()==[]

def test_goal_link_preview_feedback_review_replan(client,monkeypatch):
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat('2026-10-14T18:00:00+08:00'))
    goal=client.post('/api/goals',json={'title':'课程项目','priority':1,'metric_kind':'time','weekly_target':120,'unit_label':'分钟'}).json()
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    proposal=send(client,sid,[{'op':'add','fields':{'title':'项目报告','duration_minutes':75,'goal_id':goal['id'],'task_type':'writing','deadline':'2026-10-21T12:00:00+08:00'}}])
    draft=next(t for t in proposal['tasks'] if t['title']=='项目报告')
    assert draft['goal']['priority']==1
    assert client.get('/api/tasks').json()==[]
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code==200
    task_id=client.get('/api/tasks').json()[0]['id']
    assert client.post(f'/api/tasks/{task_id}/feedback',json={'client_action_id':'goal-partial','outcome':'partial','actual_minutes':15,'remaining_minutes':60,'occurred_at':'2026-10-14T18:00:00+08:00'}).status_code==201
    review=client.post('/api/growth/reviews',json={'week_start':'2026-10-12'})
    assert review.status_code in (200,201),review.text
    progress=next(g for g in review.json()['facts']['goal_progress'] if g['goal_id']==goal['id'])
    assert progress['actual']==15
    p=send(client,sid,[{'op':'update','target':f'task:{task_id}','fields':{'duration_minutes':60}}])
    assert p['status']=='ready'
    assert sum((datetime.fromisoformat(x['end_at'])-datetime.fromisoformat(x['start_at'])).total_seconds()/60 for x in p['items'])==60
