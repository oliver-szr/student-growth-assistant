"""Fixed-clock business facts, not simulated user history or live AI."""
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import Plan, PlanItem, Task, TaskFeedback, TaskWorkSession
from app.services import assistant_clock, assistant_ai

URL = '/api/growth/statistics'


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    now = [datetime.fromisoformat('2027-01-06T18:00:00+08:00')]
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:now[0])
    async def no_model(*args,**kwargs):
        raise AssertionError('statistics must never request AI')
    monkeypatch.setattr(assistant_ai,'request_claude',no_model)
    return now


def task(client, **fields):
    response=client.post('/api/tasks',json={'title':'匿名任务','duration_minutes':60,'deadline':'2027-01-31T20:00:00+08:00',**fields})
    assert response.status_code==201,response.text
    return response.json()


def feedback(client, task_id, at='2027-01-05T10:00:00+08:00', **fields):
    payload={'client_action_id':uuid4().hex,'outcome':'completed','actual_minutes':70,'occurred_at':at,'completed_at':at,**fields}
    if payload['outcome']!='completed':payload.pop('completed_at',None)
    response=client.post(f'/api/tasks/{task_id}/feedback',json=payload)
    assert response.status_code==201,response.text
    return response.json()


def get(client, **params):
    response=client.get(URL,params=params)
    assert response.status_code==200,response.text
    return response.json()


def plan(engine, rows, status='confirmed', week='2027-01-04'):
    with Session(engine) as db:
        p=Plan(week_start=datetime.fromisoformat(week).date(),status=status,source_revision=0,task_ids=sorted({row[0] for row in rows}))
        db.add(p);db.flush()
        for task_id,start,end in rows:
            db.add(PlanItem(plan_id=p.id,kind='task',task_id=task_id,title_snapshot='匿名片段',start_at=datetime.fromisoformat(start),end_at=datetime.fromisoformat(end)))
        db.commit()


def legacy_feedback(engine,task_id,**fields):
    with Session(engine) as db:
        row=TaskFeedback(task_id=task_id,client_action_id=uuid4().hex,outcome='completed',actual_minutes=0,
            title_snapshot='匿名旧记录',deadline_snapshot=datetime.fromisoformat('2027-01-31T20:00:00+08:00'),
            priority_snapshot='normal',initial_estimate_minutes=60,occurred_at=datetime.fromisoformat('2027-01-05T10:00:00+08:00'),**fields)
        db.add(row);db.commit();return row.id


def test_empty_and_unstarted_do_not_invent_execution(client):
    data=get(client)
    assert data['overview']['completed_count']==0 and data['overview']['actual_minutes'] is None
    assert data['overview']['data_state']=='no_records'
    assert data['estimation']['sample_count']==0 and data['estimation']['actual_minutes'] is None
    assert all(w['actual_minutes'] is None for w in data['weekly'])
    assert data['categories']==[] and data['goals']==[]
    task(client)
    assert get(client)['totals']==data['totals']


def test_one_valid_sample_and_complete_unknown_are_distinct(client):
    a=task(client);b=task(client)
    feedback(client,a['id'])
    data=get(client)
    assert data['overview']['actual_minutes']==70 and data['overview']['completed_count']==1
    assert data['estimation']['difference_minutes']==10 and data['estimation']['status']=='insufficient_data'
    feedback(client,b['id'],actual_minutes=None)
    data=get(client)
    assert data['overview']['actual_minutes'] is None
    assert data['overview']['known_actual_minutes']==70 and data['overview']['unknown_actual_count']==1
    assert data['estimation']['sample_count']==1 and data['estimation']['excluded_unknown_time']==1


def test_partial_effort_is_not_full_task_accuracy_and_timer_is_never_added(client,test_engine):
    a=task(client)
    feedback(client,a['id'],outcome='partial',actual_minutes=25,remaining_minutes=30)
    with Session(test_engine) as db:
        db.add(TaskWorkSession(task_id=a['id'],client_action_id='timer',status='stopped',accumulated_seconds=3600))
        db.commit()
    data=get(client)
    assert data['overview']['actual_minutes']==25 and data['overview']['completed_count']==0
    assert data['overview']['partial_task_count']==1 and data['estimation']['sample_count']==0
    feedback(client,a['id'],at='2027-01-06T09:00:00+08:00',actual_minutes=45)
    data=get(client)
    assert data['overview']['actual_minutes']==70
    assert data['estimation']['tasks'][0]['actual_minutes']==70
    assert data['estimation']['tasks'][0]['estimated_minutes']==60


def test_cancelled_state_is_current_snapshot_not_a_historical_event(client):
    a=task(client)
    feedback(client,a['id'],outcome='partial',actual_minutes=20,remaining_minutes=40)
    assert client.patch(f"/api/tasks/{a['id']}",json={'status':'cancelled'}).status_code==200
    data=get(client)
    assert data['current_cancelled_task_count']==1
    assert data['overview']['cancelled_event_count'] is None and data['overview']['completion_rate'] is None
    assert data['overview']['completed_count']==0 and data['overview']['actual_minutes']==20


def test_reopen_retracts_completion_and_correction_replaces_old_time(client):
    a=task(client)
    saved=feedback(client,a['id'])
    replacement=feedback(client,a['id'],at='2027-01-06T09:00:00+08:00',actual_minutes=90,corrects_feedback_id=saved['id'])
    data=get(client)
    assert data['overview']['actual_minutes']==90 and data['overview']['completed_count']==1
    assert data['estimation']['actual_minutes']==90
    assert client.patch(f"/api/tasks/{a['id']}",json={'status':'todo'}).status_code==200
    assert get(client)['totals']['completed_count']==0
    assert get(client)['totals']['actual_minutes'] is None


def test_correction_moves_completion_between_weeks_and_updates_both_views(client):
    a=task(client)
    old=feedback(client,a['id'],at='2026-12-28T10:00:00+08:00')
    assert get(client)['weekly'][-2]['completed_count']==1
    feedback(client,a['id'],at='2027-01-04T10:00:00+08:00',actual_minutes=80,corrects_feedback_id=old['id'])
    data=get(client)
    assert data['weekly'][-2]['completed_count']==0 and data['weekly'][-2]['actual_minutes'] is None
    assert data['weekly'][-1]['completed_count']==1 and data['weekly'][-1]['actual_minutes']==80


def test_legacy_zero_is_known_but_new_api_zero_still_refused(client,test_engine):
    a=task(client)
    legacy_feedback(test_engine,a['id'])
    data=get(client)
    assert data['totals']['actual_minutes']==0 and data['estimation']['actual_minutes']==0
    assert data['estimation']['difference_minutes']==-60
    response=client.post(f"/api/tasks/{a['id']}/feedback",json={'client_action_id':'zero','outcome':'completed','actual_minutes':0})
    assert response.status_code==422  # Stage 3 does not change the execution contract.


def test_parent_children_goal_and_progress_do_not_double_count(client):
    goal=client.post('/api/goals',json={'title':'交付课程项目','metric_kind':'deliverable','weekly_target':3}).json()
    parent=task(client,task_kind='container',duration_minutes=180)
    client.put(f"/api/tasks/{parent['id']}/growth-context",json={'family':'writing','goal_id':goal['id']})
    children=[task(client,parent_task_id=parent['id']) for _ in range(3)]
    feedback(client,children[0]['id'],actual_minutes=50)
    feedback(client,children[1]['id'],outcome='partial',actual_minutes=30,remaining_minutes=30)
    client.patch(f"/api/tasks/{children[2]['id']}",json={'status':'cancelled'})
    data=get(client)
    assert data['totals']['completed_count']==1 and data['totals']['actual_minutes']==80
    progress=data['goals'][0]
    assert (progress['actual'],progress['linked_task_count'],progress['linked_done_count'],progress['linked_cancelled_count'])==(1,3,1,1)
    hierarchy=client.get('/api/tasks/dashboard').json()['tasks'][0]['progress']
    assert hierarchy['completed_children']==1 and hierarchy['total_children']==3 and hierarchy['cancelled_children']==1


def test_legacy_container_feedback_and_planned_work_are_excluded(client,test_engine):
    parent=task(client,task_kind='container')
    legacy_feedback(test_engine,parent['id'])
    plan(test_engine,[(parent['id'],'2027-01-05T08:00:00+08:00','2027-01-05T09:00:00+08:00')])
    data=get(client)
    assert data['totals']['feedback_count']==0 and data['totals']['planned_minutes']==0
    assert data['estimation']['sample_count']==0


def test_split_cross_week_plans_count_minutes_but_one_completion(client,test_engine):
    a=task(client)
    plan(test_engine,[(a['id'],'2027-01-03T20:00:00+08:00','2027-01-03T20:30:00+08:00'),(a['id'],'2027-01-03T21:00:00+08:00','2027-01-03T21:30:00+08:00')],week='2026-12-28')
    plan(test_engine,[(a['id'],'2027-01-04T08:00:00+08:00','2027-01-04T09:00:00+08:00')])
    feedback(client,a['id'])
    data=get(client)
    assert data['weekly'][-2]['planned_task_count']==1 and data['weekly'][-2]['planned_minutes']==60
    assert data['weekly'][-1]['planned_task_count']==1
    assert data['totals']['planned_task_count']==1 and data['totals']['planned_minutes']==120
    assert sum(w['completed_count'] for w in data['weekly'])==1


@pytest.mark.parametrize('at,expected',[('2027-01-03T15:59:59Z',-2),('2027-01-03T16:00:00Z',-1),('2026-12-31T16:00:00Z',-2)])
def test_shanghai_midnight_month_year_and_monday_boundaries(client,at,expected):
    a=task(client);feedback(client,a['id'],at=at)
    data=get(client)
    assert data['weekly'][expected]['completed_count']==1
    assert data['weekly'][-2]['start_date']=='2026-12-28'
    assert data['weekly'][-1]['start_date']=='2027-01-04'


def test_completion_and_effort_use_their_own_recorded_dates(client):
    a=task(client)
    feedback(client,a['id'],at='2027-01-05T10:00:00+08:00',completed_at='2027-01-03T22:00:00+08:00')
    data=get(client)
    assert data['weekly'][-2]['completed_count']==1 and data['weekly'][-2]['actual_minutes'] is None
    assert data['weekly'][-1]['completed_count']==0 and data['weekly'][-1]['actual_minutes']==70
    for week in data['weekly'][-2:]:
        review=client.post('/api/growth/reviews',json={'week_start':week['start_date']})
        assert review.status_code==201,review.text
        assert review.json()['facts']['completed_count']==week['completed_count']
        assert review.json()['facts']['confirmed_actual_minutes']==week['known_actual_minutes']


@pytest.mark.parametrize('params',[{'weeks':0},{'weeks':13},{'weeks':6},{'weeks':'bad'},{'end_week':'2027-01-05'},{'end_week':'2027-01-11'},{'end_week':'bad'},{'end_week':'0001-01-01','weeks':12}])
def test_illegal_ranges_rejected(client,params):
    assert client.get(URL,params=params).status_code==422


def test_ranges_are_chronological_and_query_order_does_not_change_results(client):
    a=task(client);feedback(client,a['id'],at='2026-11-30T10:00:00+08:00')
    four=get(client,weeks=4);eight=get(client,weeks=8);twelve=get(client,weeks=12)
    assert four['weekly']==eight['weekly'][-4:]==twelve['weekly'][-4:]
    assert four['totals']['completed_count']==0 and eight['totals']['completed_count']==1
    assert eight==get(client,weeks=8)
    assert twelve['weekly']==sorted(twelve['weekly'],key=lambda w:w['start_date'])


def test_historical_range_cannot_use_future_feedback_or_current_done_status(client):
    a=task(client);feedback(client,a['id'])
    old=get(client,end_week='2026-12-28')
    assert old['totals']['completed_count']==0 and old['totals']['actual_minutes'] is None
    assert old['as_of'].startswith('2027-01-04T00:00:00+08:00')


def test_category_history_rename_inactive_and_unclassified(client,test_engine):
    category=client.post('/api/task-categories',json={'name':'算法实验'}).json()
    a=task(client);b=task(client)
    feedback(client,a['id'],family=category['key'],actual_minutes=100)
    feedback(client,b['id'],actual_minutes=None)
    client.patch(f"/api/task-categories/{category['key']}",json={'name':'算法与工程','active':False})
    client.put(f"/api/tasks/{a['id']}/growth-context",json={'family':'reading'})
    data=get(client);groups={g['key']:g for g in data['categories']}
    assert groups[category['key']]['name']=='算法与工程' and groups[category['key']]['actual_minutes']==100
    assert groups['']['name']=='未分类' and groups['']['actual_minutes'] is None
    assert groups[category['key']]['known_time_share']==1
    assert sum(g['completed_count'] for g in groups.values())==data['totals']['completed_count']
    assert sum(g['known_actual_minutes'] for g in groups.values())==data['totals']['known_actual_minutes']


def test_estimation_uses_lifetime_partial_effort_original_estimate_and_minimum_samples(client):
    a=task(client,duration_minutes=90)
    feedback(client,a['id'],at='2026-11-01T10:00:00+08:00',outcome='partial',actual_minutes=40,remaining_minutes=30)
    client.patch(f"/api/tasks/{a['id']}",json={'duration_minutes':20})
    feedback(client,a['id'],actual_minutes=70,family='writing')
    data=get(client)
    assert data['totals']['actual_minutes']==70  # Range excludes the early effort.
    paired=data['estimation']['tasks'][0]
    assert (paired['estimated_minutes'],paired['actual_minutes'],paired['difference_minutes'])==(90,110,20)
    for _ in range(2):feedback(client,task(client,duration_minutes=90)['id'],actual_minutes=110,family='writing')
    data=get(client)
    assert data['estimation']['status']=='available' and data['estimation']['sample_count']==3
    assert data['estimation']['categories'][0]['observation'] is not None
    assert data['estimation']['deviation_ratio']==pytest.approx(60/270)


def test_missing_earlier_effort_and_incomparable_estimate_excluded(client,test_engine):
    a=task(client);b=task(client)
    feedback(client,a['id'],at='2026-11-01T10:00:00+08:00',outcome='partial',actual_minutes=None,remaining_minutes=30)
    feedback(client,a['id'])
    feedback(client,b['id'],outcome='partial',actual_minutes=20,remaining_minutes=30)
    final=feedback(client,b['id'])
    with Session(test_engine) as db:
        db.get(TaskFeedback,final['id']).initial_estimate_minutes=90;db.commit()
    data=get(client)['estimation']
    assert data['sample_count']==0 and data['excluded_unknown_time']==1 and data['excluded_incomparable_estimate']==1


@pytest.mark.parametrize('kind',['time','count','deliverable'])
def test_goal_types_reuse_shared_semantics_and_do_not_change_status(client,kind):
    goal=client.post('/api/goals',json={'title':'目标','metric_kind':kind,'weekly_target':100 if kind=='time' else 3}).json()
    a=task(client);b=task(client)
    for item in (a,b):client.put(f"/api/tasks/{item['id']}/growth-context",json={'family':'reading','goal_id':goal['id']})
    feedback(client,a['id'],actual_minutes=40)
    feedback(client,b['id'],outcome='partial',actual_minutes=None,remaining_minutes=20)
    data=get(client)['goals'][0]
    if kind=='time':assert data['actual'] is None and data['known_actual']==40 and data['unknown_actual_count']==1
    else:assert data['actual']==1 and data['remaining']==2
    assert client.get('/api/goals').json()['goals'][0]['status']=='active'


@pytest.mark.parametrize('invalid',[-1,1441])
def test_invalid_legacy_effort_excluded(client,test_engine,invalid):
    a=task(client)
    row_id=legacy_feedback(test_engine,a['id'])
    with Session(test_engine) as db:db.get(TaskFeedback,row_id).actual_minutes=invalid;db.commit()
    data=get(client)
    assert data['excluded_invalid_feedback_count']==1 and data['totals']['completed_count']==0


def test_api_reads_do_not_write_or_change_backup_and_query_count_is_bounded(client,test_engine):
    a=task(client);feedback(client,a['id'])
    before=client.get('/api/data/export').json()['tables']
    statements=[]
    def record(connection,cursor,statement,parameters,context,executemany):statements.append(statement.strip().upper())
    event.listen(test_engine,'before_cursor_execute',record)
    try:
        get(client)
        assert sum(s.startswith('SELECT') for s in statements)<=7
        assert not any(s.startswith(('INSERT','UPDATE','DELETE','REPLACE','CREATE','ALTER')) for s in statements)
    finally:event.remove(test_engine,'before_cursor_execute',record)
    assert client.get('/api/data/export').json()['tables']==before


def test_duplicate_legacy_completions_count_once_and_future_events_are_excluded(client,test_engine):
    a=task(client);legacy_feedback(test_engine,a['id'])
    legacy_feedback(test_engine,a['id'],completed_at=datetime.fromisoformat('2027-01-06T10:00:00+08:00'))
    b=task(client);feedback(client,b['id'],at='2027-01-07T10:00:00+08:00')
    data=get(client)
    assert data['totals']['completed_count']==1
    assert sum(w['completed_count'] for w in data['weekly'])==1


def test_only_formal_plans_and_history_fallback_are_labeled(client,test_engine):
    a=task(client)
    plan(test_engine,[(a['id'],'2027-01-05T08:00:00+08:00','2027-01-05T09:00:00+08:00')],status='candidate')
    legacy_feedback(test_engine,a['id'])
    data=get(client)
    assert data['totals']['planned_task_count']==0 and data['totals']['planned_minutes']==0
    assert data['legacy_completion_time_count']==1
    assert '缺失' in data['definitions']['completion']


def test_default_feedback_timestamp_uses_shared_fixed_clock(client,test_engine,fixed_clock):
    a=task(client)
    response=client.post(f"/api/tasks/{a['id']}/feedback",json={'client_action_id':'default-clock','outcome':'completed','actual_minutes':45})
    assert response.status_code==201
    with Session(test_engine) as db:
        row=db.get(TaskFeedback,response.json()['id'])
        assert row.occurred_at==fixed_clock[0] and row.completed_at==fixed_clock[0]
    data=get(client)
    assert data['overview']['completed_count']==1 and data['overview']['actual_minutes']==45


def test_late_corrections_of_earlier_partial_use_original_position_and_count_once(client):
    a=task(client,duration_minutes=90)
    partial=feedback(client,a['id'],at='2027-01-04T10:00:00+08:00',outcome='partial',actual_minutes=40,remaining_minutes=30)
    feedback(client,a['id'],actual_minutes=70)
    replacement=feedback(client,a['id'],at='2027-01-04T10:00:00+08:00',outcome='partial',actual_minutes=50,remaining_minutes=30,corrects_feedback_id=partial['id'])
    first=get(client)
    assert first['estimation']['tasks'][0]['actual_minutes']==120
    feedback(client,a['id'],at='2027-01-04T10:00:00+08:00',outcome='partial',actual_minutes=60,remaining_minutes=30,corrects_feedback_id=replacement['id'])
    data=get(client)
    assert data['overview']['completed_count']==1 and data['overview']['actual_minutes']==130
    assert data['estimation']['tasks'][0]['actual_minutes']==130
    assert data['estimation']['tasks'][0]['difference_minutes']==40


def test_backdated_correction_resolves_later_ancestor_without_importing_future_effort(client):
    a=task(client)
    old=feedback(client,a['id'],at='2027-01-05T10:00:00+08:00',actual_minutes=70)
    feedback(client,a['id'],at='2026-12-28T10:00:00+08:00',actual_minutes=80,corrects_feedback_id=old['id'])
    data=get(client,end_week='2026-12-28')
    assert data['totals']['completed_count']==1 and data['totals']['actual_minutes']==80
    assert data['estimation']['sample_count']==1 and data['estimation']['actual_minutes']==80
