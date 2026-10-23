from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from app.services.assistant_clock import assistant_now
import pytest
from sqlalchemy.orm import Session
from app.models import Plan, PlanItem, TaskSchedulingProfile


def _task(client: TestClient, title: str, deadline: datetime, priority: str = "normal") -> int:
    response = client.post("/api/tasks", json={
        "title": title,
        "duration_minutes": 60,
        "deadline": deadline.isoformat(),
        "priority": priority,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_attention_separates_user_importance_from_dynamic_urgency(client: TestClient) -> None:
    now = assistant_now()
    later_high = _task(client, "长期项目", now + timedelta(days=4), "high")
    soon_low = _task(client, "明早汇报稿", now + timedelta(hours=10), "low")

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    tasks = response.json()["items"]
    assert tasks[0]["task_id"] == soon_low
    assert tasks[0]["urgency"] in {"critical", "urgent"}
    assert tasks[0]["importance"] == "low"
    assert tasks[1]["task_id"] == later_high
    assert tasks[1]["importance"] == "high"
    assert tasks[0]["reason"]


def test_attention_marks_overdue_tasks_without_changing_deadline(client: TestClient) -> None:
    deadline = assistant_now() - timedelta(days=1)
    task_id = _task(client, "逾期作业", deadline)

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    item = next(x for x in response.json()["items"] if x["task_id"] == task_id)
    assert item["urgency"] == "overdue"
    assert datetime.fromisoformat(item["deadline"]) == deadline.astimezone(datetime.fromisoformat(item["deadline"]).tzinfo)
    assert datetime.fromisoformat(client.get("/api/tasks").json()[0]["deadline"]) == deadline


def test_seven_day_urgency_reason_does_not_claim_calendar_week(client: TestClient) -> None:
    deadline = assistant_now() + timedelta(days=6)
    task_id = _task(client, "下周截止任务", deadline)

    response = client.get("/api/growth/attention")

    assert response.status_code == 200
    item = next(x for x in response.json()["items"] if x["task_id"] == task_id)
    assert item["urgency"] == "soon"
    assert item["reason"].startswith("7天内截止")


def test_paused_goal_no_longer_changes_current_attention_context(client: TestClient) -> None:
    goal = client.post("/api/goals", json={
        "title": "已暂停目标", "metric_kind": "count", "weekly_target": 2, "unit_label": "次", "priority": 1,
    }).json()
    task_id = _task(client, "目标关联任务", assistant_now() + timedelta(days=3))
    client.put(f"/api/tasks/{task_id}/growth-context", json={"family": "writing", "goal_id": goal["id"]})
    client.patch(f"/api/goals/{goal['id']}", json={"status": "paused"})

    item = next(row for row in client.get("/api/growth/attention").json()["items"] if row["task_id"] == task_id)

    assert item["goal"] is None


@pytest.fixture
def friday(monkeypatch):
    from app.services import assistant_clock
    now=datetime.fromisoformat('2026-10-23T13:00:00+08:00')
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:now)
    return now


def attention_task(client,friday):
    return _task(client,'匿名数据库实验',friday.replace(hour=22))


def attention_for(client,task_id):
    response=client.get('/api/growth/attention');assert response.status_code==200,response.text
    return next(row for row in response.json()['items'] if row['task_id']==task_id)


def block(client,start,end):
    r=client.post('/api/time-rules',json={'title':'匿名固定占用','kind':'protected','recurrence':'once','date':'2026-10-23','start_time':start,'end_time':end})
    assert r.status_code==201,r.text


def test_long_free_window_has_many_starts_even_with_a_category_profile(client,test_engine,friday):
    tid=attention_task(client,friday)
    with Session(test_engine) as db:
        db.add(TaskSchedulingProfile(task_id=tid,settings={'task_type':'writing'}));db.commit()
    row=attention_for(client,tid)
    assert row['free_interval_count']==1 and row['free_minutes']==540
    assert row['available_start_count']==97 and row['fitting_interval_count']==1
    assert len(row['recommendations'])==3 and row['recommendation_count']==3
    assert row['urgency']!='critical' and '只找到一个' not in row['reason']
    assert all(datetime.fromisoformat(x['start_at'])>=friday for r in row['recommendations'] for x in r['items'])


def test_multiple_free_intervals_count_duration_and_grid_starts(client,friday):
    tid=attention_task(client,friday);block(client,'14:00','15:00');block(client,'17:00','18:00')
    row=attention_for(client,tid)
    assert [i['minutes'] for i in row['free_intervals']]==[60,120,240]
    assert row['free_interval_count']==3 and row['available_start_count']==51


def test_only_one_fitting_gap_is_not_the_count_of_all_free_gaps(client,friday):
    tid=attention_task(client,friday)
    for a,b in [('13:30','14:00'),('14:30','15:00'),('16:00','22:00')]:block(client,a,b)
    row=attention_for(client,tid)
    assert row['free_interval_count']==3 and row['fitting_interval_count']==1
    assert row['available_start_count']==1 and row['recommendations'][0]['items'][0]['start_at'].startswith('2026-10-23T15:00')
    assert '只有这段' in row['reason']


@pytest.mark.parametrize('now',['2026-10-23T21:05:00+08:00','2026-10-23T22:01:00+08:00'])
def test_too_late_never_invents_an_available_start(client,monkeypatch,friday,now):
    from app.services import assistant_clock
    tid=attention_task(client,friday);monkeypatch.setattr(assistant_clock,'assistant_now',lambda:datetime.fromisoformat(now))
    row=attention_for(client,tid)
    assert row['available_start_count']==0 and row['recommendations']==[]
    assert row['availability_state'] in ('unavailable','overdue')


def test_past_minutes_are_rounded_up_and_deadline_boundary_remains_exact(client,monkeypatch,friday):
    from app.services import assistant_clock
    tid=attention_task(client,friday)
    monkeypatch.setattr(assistant_clock,'assistant_now',lambda:friday.replace(minute=7,second=9))
    row=attention_for(client,tid)
    assert row['available_start_count']==95
    assert row['recommendations'][0]['items'][0]['start_at'].startswith('2026-10-23T13:10')


def test_formal_occupancy_counts_other_tasks_but_not_self_or_candidate(client,test_engine,friday):
    tid=attention_task(client,friday);other=attention_task(client,friday)
    with Session(test_engine) as db:
        plans={}
        for status,start,taskid in [('confirmed',14,other),('candidate',16,other),('confirmed',19,tid)]:
            if status not in plans:
                plans[status]=Plan(week_start=friday.date()-timedelta(days=4),status=status,source_revision=0,task_ids=[tid,other]);db.add(plans[status]);db.flush()
            plan=plans[status]
            db.add(PlanItem(plan_id=plan.id,kind='task',task_id=taskid,title_snapshot='匿名安排',start_at=friday.replace(hour=start),end_at=friday.replace(hour=start+1)))
        db.add(TaskSchedulingProfile(task_id=tid,settings={'task_type':'writing'}));db.commit()
    row=attention_for(client,tid)
    assert row['available_start_count']==74 and row['free_minutes']==480
    assert row['has_confirmed_time'] and row['availability_state']=='scheduled'
    assert all(not (datetime.fromisoformat(i['start_at'])<friday.replace(hour=15) and datetime.fromisoformat(i['end_at'])>friday.replace(hour=14)) for r in row['recommendations'] for i in r['items'])


def test_hard_profile_is_distinct_from_general_free_time(client,test_engine,friday):
    tid=attention_task(client,friday)
    with Session(test_engine) as db:
        db.add(TaskSchedulingProfile(task_id=tid,settings={'allowed_windows':[{'start_at':'2026-10-23T14:00:00+08:00','end_at':'2026-10-23T15:00:00+08:00'}]}));db.commit()
    row=attention_for(client,tid)
    assert row['free_minutes']==540 and row['available_start_count']==1
    assert row['constraints']['allowed_windows'] and '指定' in row['reason']


def test_partial_feedback_changes_remaining_work_and_done_leaves_attention(client,friday):
    tid=attention_task(client,friday)
    r=client.post(f'/api/tasks/{tid}/feedback',json={'client_action_id':'partial','outcome':'partial','actual_minutes':40,'remaining_minutes':20});assert r.status_code<300,r.text
    assert attention_for(client,tid)['remaining_minutes']==20
    r=client.post(f'/api/tasks/{tid}/feedback',json={'client_action_id':'done','outcome':'completed','actual_minutes':20});assert r.status_code<300,r.text
    assert not any(row['task_id']==tid for row in client.get('/api/growth/attention').json()['items'])


def test_attention_suggestion_creates_real_draft_once_then_requires_original_confirm(client,friday):
    tid=attention_task(client,friday);before=client.get('/api/tasks').json()
    snapshot=client.get('/api/growth/attention').json();row=next(x for x in snapshot['items'] if x['task_id']==tid)
    body={'client_request_id':'suggestion','expected_revision':snapshot['revision'],'recommendation_key':row['recommendations'][0]['key']}
    path=f'/api/growth/tasks/{tid}/schedule-draft'
    response=client.post(path,json=body);assert response.status_code==200,response.text
    draft=response.json();assert draft['kind']=='planning' and draft['status']=='ready'
    assert client.get('/api/tasks').json()==before
    assert client.get('/api/calendar/events?start=2026-10-23&end=2026-10-24').json()['events']==[e for e in client.get('/api/calendar/events?start=2026-10-23&end=2026-10-24').json()['events'] if e['kind']!='formal_task']
    assert client.post(path,json=body).json()['id']==draft['id']
    saved=client.post(f"/api/workspace/drafts/planning/{draft['id']}/confirm",json={'expected_version':draft['version']});assert saved.status_code==200,saved.text
    assert saved.json()['status']=='applied'
    assert any(e['kind']=='formal_task' for e in client.get('/api/calendar/events?start=2026-10-23&end=2026-10-24').json()['events'])
    assert client.post(path,json=body).json()['id']==draft['id']


def test_attention_rejects_stale_suggestion_without_creating_draft(client,friday):
    tid=attention_task(client,friday);snap=client.get('/api/growth/attention').json()
    key=snap['items'][0]['recommendations'][0]['key'];block(client,'13:00','14:00')
    response=client.post(f'/api/growth/tasks/{tid}/schedule-draft',json={'client_request_id':'stale','expected_revision':snap['revision'],'recommendation_key':key})
    assert response.status_code==409 and response.json()['detail']['code']=='STALE_CANDIDATE'


def test_cross_day_utc_deadline_and_weekly_course_expand_once(client,test_engine,friday):
    tid=_task(client,'跨日UTC截止',datetime.fromisoformat('2026-10-24T02:00:00+00:00'))
    r=client.post('/api/time-rules',json={'title':'周五课程','kind':'course','recurrence':'weekly','weekday':5,'start_time':'14:00','end_time':'15:00'});assert r.status_code==201
    with Session(test_engine) as db:
        p=Plan(week_start=friday.date()-timedelta(days=4),status='confirmed',source_revision=0,task_ids=[]);db.add(p);db.flush()
        db.add(PlanItem(plan_id=p.id,kind='course',time_rule_id=r.json()['id'],title_snapshot='周五课程',start_at=friday.replace(hour=14),end_at=friday.replace(hour=15)));db.commit()
    row=attention_for(client,tid)
    assert row['free_minutes']==600 and row['available_start_count']==87
    assert row['window_end']=='2026-10-24T10:00:00+08:00'


def test_split_possible_does_not_claim_zero_schedules_or_a_unique_start(client,test_engine,friday):
    tid=attention_task(client,friday)
    for a,b in [('13:30','14:00'),('14:30','22:00')]:block(client,a,b)
    with Session(test_engine) as db:
        db.add(TaskSchedulingProfile(task_id=tid,settings={'splittable':True,'min_block_minutes':30,'max_segments':2}));db.commit()
    row=attention_for(client,tid)
    assert row['available_start_count']==0 and row['availability_state']=='split_possible'
    assert row['recommendations'] and len(row['recommendations'][0]['items'])==2
    assert '分段' in row['reason']

@pytest.mark.parametrize('locked,started',[(True,False),(False,True)])
def test_locked_or_started_formal_segments_never_offer_movement(client,test_engine,friday,locked,started):
    tid=attention_task(client,friday)
    with Session(test_engine) as db:
        p=Plan(week_start=friday.date()-timedelta(days=4),status='confirmed',source_revision=0,task_ids=[tid]);db.add(p);db.flush()
        a=friday.replace(hour=12,minute=30) if started else friday.replace(hour=14)
        db.add(PlanItem(plan_id=p.id,kind='task',task_id=tid,title_snapshot='匿名安排',start_at=a,end_at=a+timedelta(hours=1)))
        db.add(TaskSchedulingProfile(task_id=tid,settings={'locked':locked,'splittable':True,'min_block_minutes':30,'max_segments':2}));db.commit()
    row=attention_for(client,tid)
    assert row['availability_state']==('in_progress' if started else 'locked')
    assert row['recommendations']==[]

def test_lost_draft_reply_reuses_original_message_even_without_optional_metadata(client,test_engine,friday):
    from app.models import AssistantProposal
    tid=attention_task(client,friday);snap=client.get('/api/growth/attention').json()
    body={'client_request_id':'lost-reply','expected_revision':snap['revision'],'recommendation_key':snap['items'][0]['recommendations'][0]['key']}
    path=f'/api/growth/tasks/{tid}/schedule-draft'
    draft=client.post(path,json=body).json()
    with Session(test_engine) as db:
        row=db.get(AssistantProposal,draft['id']);value=dict(row.payload);value.pop('attention_request');row.payload=value;db.commit()
    assert client.post(path,json=body).json()['id']==draft['id']
    another={**body,'recommendation_key':snap['items'][0]['recommendations'][1]['key']}
    assert client.post(path,json=another).status_code==409

def test_unconfirmed_start_at_now_is_editable_not_a_started_formal_task(client,friday):
    tid=attention_task(client,friday);snap=client.get('/api/growth/attention').json()
    draft=client.post(f'/api/growth/tasks/{tid}/schedule-draft',json={'client_request_id':'edit','expected_revision':snap['revision'],'recommendation_key':snap['items'][0]['recommendations'][0]['key']}).json()
    assert '截止 10-23 22:00' in draft['summary']  # UTC storage must not display 14:00.
    content=draft['content'];content['actions'][0]['fields']['profile']['fixed_start']='2026-10-23T14:00:00+08:00'
    edited=client.patch(f"/api/workspace/drafts/planning/{draft['id']}",json={'expected_version':draft['version'],'content':content})
    assert edited.status_code==200,edited.text
    latest=edited.json();assert latest['status']=='ready'
    assert latest['items'][0]['start_at']=='2026-10-23T14:00:00+08:00'
    saved=client.post(f"/api/workspace/drafts/planning/{latest['id']}/confirm",json={'expected_version':latest['version']})
    assert saved.status_code==200,saved.text
