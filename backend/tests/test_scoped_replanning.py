"""Scoped replanning uses formal identities, explicit consent, and full validation."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models import AssistantProposal, Plan, PlanItem, TaskSchedulingProfile
from app.services.assistant_scheduler import dt
from app.services import assistant_clock
from .test_planning_state import revision


WEEK = date(2026, 10, 5)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    value = [datetime.fromisoformat("2026-10-05T07:50:00+08:00")]
    monkeypatch.setattr(assistant_clock, "assistant_now", lambda: value[0])
    return value


def seed(client, engine, rows=None):
    rows = rows or [("报告", 9, 14), ("练习", 10, 14), ("阅读", 12, 14)]
    tasks = []
    for title, hour, deadline_hour in rows:
        response = client.post("/api/tasks", json={
            "title": title, "duration_minutes": 60,
            "deadline": f"2026-10-05T{deadline_hour:02}:00:00+08:00",
        })
        assert response.status_code == 201
        tasks.append(response.json())
    with Session(engine) as db:
        plan = Plan(week_start=WEEK, status="confirmed", source_revision=revision(engine), task_ids=[t["id"] for t in tasks])
        db.add(plan)
        db.flush()
        for task, (_, hour, _) in zip(tasks, rows):
            start = datetime(2026, 10, 5, hour, tzinfo=assistant_clock.SHANGHAI)
            db.add(PlanItem(plan_id=plan.id, kind="task", task_id=task["id"], title_snapshot=task["title"],
                            start_at=start, end_at=start + timedelta(hours=1)))
        db.commit()
    sid = client.post("/api/assistant/sessions", json={}).json()["id"]
    return sid, tasks


def rule(client, start="09:00", end="10:00", kind="course"):
    response = client.post("/api/time-rules", json={
        "title": "临时安排", "kind": kind, "recurrence": "once", "date": WEEK.isoformat(),
        "start_time": start, "end_time": end,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def request(client, sid, **fields):
    response = client.post(f"/api/assistant/sessions/{sid}/messages", json={
        "client_message_id": uuid4().hex, "text": "局部重规划", "replan": True, **fields,
    })
    assert response.status_code == 200, response.text
    return response.json()


def official(client, sid):
    return client.get(f"/api/assistant/sessions/{sid}").json()["confirmed_items"]


def by_ref(items, ref):
    return sorted((item["start_at"], item["end_at"]) for item in items if item["ref"] == ref)


def test_new_course_moves_only_affected_task_and_explains_real_rule(client, test_engine):
    sid, tasks = seed(client, test_engine)
    before = official(client, sid)
    rule_id = rule(client)
    before_revision = revision(test_engine)
    proposal = request(client, sid)
    assert proposal["status"] == "ready", proposal
    assert proposal["replanning"]["mode"] == "local"
    assert proposal["replanning"]["affected_refs"] == [f"task:{tasks[0]['id']}"]
    for task in tasks[1:]:
        assert by_ref(proposal["items"], f"task:{task['id']}") == by_ref(before, f"task:{task['id']}")
    fact = next(d for d in proposal["diagnostics"] if d.get("time_rule_id") == rule_id)
    assert fact["constraint"] == "course" and fact["ref"] == f"task:{tasks[0]['id']}"
    assert fact["original_interval"]["start_at"].startswith("2026-10-05T09:00")
    assert fact["conflict_interval"]["start_at"].startswith("2026-10-05T09:00")
    assert proposal["change_groups"]["counts"] == {"preserved": 2, "moved": 1, "added": 0, "pending": 0}
    assert official(client, sid) == before and revision(test_engine) == before_revision
    adopted = client.post(f"/api/assistant/proposals/{proposal['id']}/confirm")
    assert adopted.status_code == 200, adopted.text
    assert len(official(client, sid)) == 3


def test_local_failure_requires_explicit_expansion_and_then_recalculates(client, test_engine):
    sid, tasks = seed(client, test_engine, [("紧急报告", 8, 10), ("可调整练习", 9, 11)])
    before = official(client, sid)
    rule(client, "08:00", "09:00", "protected")
    proposal = request(client, sid)
    assert proposal["status"] == "no_plan" and proposal["replanning"]["requires_expansion"]
    assert proposal["formal_plan_needs_review"] is True
    assert proposal["items"] == [] and proposal["changes"] == []
    assert official(client, sid) == before
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code == 409
    response = client.post(f"/api/assistant/proposals/{proposal['id']}/preview", json={
        "client_message_id": "explicit-expand", "expand_scope": True,
    })
    assert response.status_code == 200, response.text
    expanded = response.json()
    assert expanded["status"] == "ready", expanded
    assert expanded["replanning"]["mode"] == "expanded"
    assert by_ref(expanded["items"], f"task:{tasks[1]['id']}") != by_ref(before, f"task:{tasks[1]['id']}")
    assert official(client, sid) == before
    assert client.post(f"/api/assistant/proposals/{expanded['id']}/confirm").status_code == 200


def test_declining_expansion_keeps_formal_plan_and_version(client, test_engine):
    sid, _ = seed(client, test_engine, [("紧急报告", 8, 10), ("可调整练习", 9, 11)])
    rule(client, "08:00", "09:00", "protected")
    before, before_revision = official(client, sid), revision(test_engine)
    proposal = request(client, sid)
    assert proposal["replanning"]["requires_expansion"]
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/discard").status_code == 200
    assert official(client, sid) == before and revision(test_engine) == before_revision


@pytest.mark.parametrize("change", ["kept_time", "formal_snapshot", "scope_metadata"])
def test_confirmation_rejects_changed_scope_or_baseline(client, test_engine, change):
    sid, tasks = seed(client, test_engine)
    rule(client)
    proposal = request(client, sid)
    with Session(test_engine) as db:
        if change == "formal_snapshot":
            item = db.scalar(select(PlanItem).join(Plan).where(Plan.status == "confirmed", PlanItem.task_id == tasks[1]["id"]))
            item.start_at += timedelta(minutes=5)
            item.end_at += timedelta(minutes=5)
        else:
            row = db.get(AssistantProposal, proposal["id"])
            payload = deepcopy(row.payload)
            if change == "scope_metadata":
                payload["replanning"]["mode"] = "expanded"
            else:
                item = next(x for x in payload["items"] if x["ref"] == f"task:{tasks[1]['id']}")
                item["start_at"] = "2026-10-05T11:00:00+08:00"
                item["end_at"] = "2026-10-05T12:00:00+08:00"
            row.payload = payload
        db.commit()
    before, before_revision = official(client, sid), revision(test_engine)
    response = client.post(f"/api/assistant/proposals/{proposal['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert official(client, sid) == before and revision(test_engine) == before_revision


def test_multiple_tasks_and_deadline_edit_use_formal_diff(client, test_engine):
    sid,tasks=seed(client,test_engine)
    rule(client,'09:00','11:00')
    p=request(client,sid,actions=[dict(op='update',target=f"task:{tasks[2]['id']}",fields={'deadline':'2026-10-05T12:00:00+08:00'})])
    assert p['status']=='ready',p
    assert len(p['replanning']['affected_refs'])==3
    assert p['change_groups']['counts']['moved']==3
    assert any(d['code']=='DEADLINE_VIOLATION' and d['ref']==f"task:{tasks[2]['id']}" for d in p['diagnostics'])
    assert not any(d['code']=='TIME_RULE_CONFLICT' and d['ref']==f"task:{tasks[2]['id']}" for d in p['diagnostics'])
    assert next(t for t in client.get('/api/tasks').json() if t['id']==tasks[2]['id'])['deadline'].startswith('2026-10-05T06:00')
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200


def test_new_task_preserves_others_without_ai_and_option_diff_stays_consistent(client,test_engine,monkeypatch):
    from app.services import assistant_ai
    async def forbidden(*args,**kwargs):
        raise AssertionError('manual replanning must not call AI')
    monkeypatch.setattr(assistant_ai,'parse_message',forbidden)
    sid,_=seed(client,test_engine)
    p=request(client,sid,actions=[dict(op='add',fields=dict(title='新增任务',duration_minutes=35,deadline='2026-10-05T15:00:00+08:00'))])
    assert p['status']=='ready' and p['change_groups']['counts']==dict(preserved=3,moved=0,added=1,pending=0)
    assert len(client.get('/api/tasks').json())==3
    for option in p['candidate_options']:
        switched=client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'candidate_id':option['candidate_id']}).json()
        assert switched['items']==option['items'] and switched['change_groups']==option['change_groups']
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    assert len(client.get('/api/tasks').json())==4


@pytest.mark.parametrize('protection',['locked','started'])
def test_protected_conflict_never_offers_unauthorized_movement(client,test_engine,clock,protection):
    sid,tasks=seed(client,test_engine)
    if protection=='locked':
        with Session(test_engine) as db:
            db.add(TaskSchedulingProfile(task_id=tasks[0]['id'],settings={'locked':True}));db.commit()
    else:
        clock[0]=dt('2026-10-05T09:05:00+08:00')
    rule(client)
    before=official(client,sid)
    p=request(client,sid)
    assert p['status']!='ready'
    assert f"task:{tasks[0]['id']}" in p['replanning']['protected_refs']
    assert any(d['code']=='LOCKED_SEGMENT' for d in p['diagnostics'])
    assert not p['replanning']['requires_expansion']
    r=client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'expand_scope':True})
    assert r.status_code==422
    assert official(client,sid)==before


@pytest.mark.parametrize('change',['clock','revision','lock','metadata_removed'])
def test_confirmation_rechecks_scope_full_constraints_and_version(client,test_engine,clock,change):
    sid,tasks=seed(client,test_engine)
    rule(client)
    p=request(client,sid)
    if change=='clock':
        clock[0]=dt('2026-10-05T14:05:00+08:00')
    elif change=='revision':
        rule(client,'13:00','14:00','protected')
    else:
        with Session(test_engine) as db:
            if change=='lock':
                db.add(TaskSchedulingProfile(task_id=tasks[0]['id'],settings={'locked':True}))
            else:
                row=db.get(AssistantProposal,p['id']);row.payload={k:v for k,v in row.payload.items() if k!='replanning'}
            db.commit()
    before,rev=official(client,sid),revision(test_engine)
    response=client.post(f"/api/assistant/proposals/{p['id']}/confirm")
    assert response.status_code==409 and response.json()['detail']['code']=='STALE_CANDIDATE'
    assert official(client,sid)==before and revision(test_engine)==rev


def test_two_week_write_failure_rolls_back_everything(client,test_engine):
    sid,_=seed(client,test_engine)
    rule(client)
    p=request(client,sid)
    before,rev=official(client,sid),revision(test_engine)
    def fail_second_week(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO plans') and '2026-10-12' in parameters:
            raise RuntimeError('injected second-week save failure')
    event.listen(test_engine,'before_cursor_execute',fail_second_week)
    try:
        with pytest.raises(RuntimeError,match='second-week'):
            client.post(f"/api/assistant/proposals/{p['id']}/confirm")
    finally:
        event.remove(test_engine,'before_cursor_execute',fail_second_week)
    assert official(client,sid)==before and revision(test_engine)==rev
    assert client.get(f'/api/assistant/sessions/{sid}').json()['proposal']['status']=='ready'


def test_split_task_total_and_formal_identity_survive_replanning(client,test_engine):
    sid,tasks=seed(client,test_engine)
    rule(client)
    windows=[{'start_at':f'2026-10-05T{a}:00+08:00','end_at':f'2026-10-05T{b}:00+08:00'} for a,b in [('08:00','08:30'),('11:00','11:30')]]
    p=request(client,sid,actions=[dict(op='update',target=f"task:{tasks[0]['id']}",fields={'profile':{'splittable':True,'min_block_minutes':30,'max_segments':2,'allowed_windows':windows}})])
    segments=[x for x in p['items'] if x['ref']==f"task:{tasks[0]['id']}"]
    assert p['status']=='ready' and len(segments)==2
    assert sum((dt(x['end_at'])-dt(x['start_at'])).total_seconds()/60 for x in segments)==60
    assert p['change_groups']['counts']==dict(preserved=2,moved=1,added=0,pending=0)
    moved=p['change_groups']['moved'][0]
    assert len(moved['before_segments'])==1 and len(moved['after_segments'])==2
    assert len({(x['ref'],x['start_at'],x['end_at']) for x in p['items']})==len(p['items'])
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200


def test_missed_work_requires_remaining_confirmation_and_keeps_history(client,test_engine,clock):
    sid,tasks=seed(client,test_engine)
    clock[0]=dt('2026-10-05T11:05:00+08:00')
    ref=f"task:{tasks[0]['id']}"
    missing=request(client,sid,actions=[dict(op='update',target=ref,fields={})])
    assert missing['status']=='needs_input' and any('预计剩余' in q for q in missing['questions'])
    assert next(x for x in missing['change_groups']['pending'] if x['ref']==ref)['remaining_minutes'] is None
    p=request(client,sid,actions=[dict(op='update',target=ref,fields={'duration_minutes':30})])
    assert p['status']=='ready',p
    assert len([x for x in p['retained'] if x['ref']==ref])==1
    assert sum((dt(x['end_at'])-dt(x['start_at'])).total_seconds()/60 for x in p['items'] if x['ref']==ref)==30
    assert any(d['code']=='CURRENT_TIME_ADVANCED' for d in p['diagnostics'])
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    assert next(t for t in client.get('/api/tasks').json() if t['id']==tasks[0]['id'])['status']=='todo'


def test_search_budget_diagnostic_never_claims_infeasibility_or_silent_expansion(client,test_engine,monkeypatch):
    from app.services import assistant_state
    sid,_=seed(client,test_engine)
    rule(client)
    monkeypatch.setattr(assistant_state,'arrange',lambda *a,**k:dict(status='no_plan',items=[],alternatives=[],diagnostics=[dict(code='SEARCH_LIMIT',message='搜索达到预算，未找到完整方案；不等于数学上无解。')]))
    p=request(client,sid)
    assert p['status']=='no_plan' and not p['replanning']['requires_expansion']
    assert any(d['code']=='SEARCH_LIMIT' for d in p['diagnostics'])
    assert not any(d['code']=='LOCAL_SCOPE_LIMIT' for d in p['diagnostics'])


def test_expansion_consent_expires_after_discard(client,test_engine):
    sid,_=seed(client,test_engine,[("紧急报告",8,10),("可调整练习",9,11)])
    rule(client,'08:00','09:00','protected')
    p=request(client,sid)
    expanded=client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'expand_scope':True}).json()
    assert expanded['status']=='ready'
    # Follow-up uses the same confirmed expansion source.
    follow=request(client,sid)
    assert follow['replanning']['expansion_from']==p['id']
    assert client.post(f"/api/assistant/proposals/{follow['id']}/discard").status_code==200
    again=request(client,sid)
    assert again['status']=='no_plan' and again['replanning']['mode']=='local'


def test_weekend_replanning_keeps_next_week_and_completed_history(client,test_engine,clock,monkeypatch):
    monkeypatch.setenv('TZ','America/Los_Angeles')
    sid,tasks=seed(client,test_engine)
    for task in tasks[:2]:
        assert client.patch(f"/api/tasks/{task['id']}",json={'deadline':'2026-10-13T06:00:00Z'}).status_code==200
    assert client.patch(f"/api/tasks/{tasks[2]['id']}",json={'status':'done'}).status_code==200
    with Session(test_engine) as db:
        next_plan=Plan(week_start=WEEK+timedelta(days=7),status='confirmed',source_revision=revision(test_engine),task_ids=[tasks[1]['id']])
        db.add(next_plan);db.flush()
        for index,day,hour in [(0,11,21),(1,12,8)]:
            item=db.scalar(select(PlanItem).where(PlanItem.task_id==tasks[index]['id']))
            item.start_at=datetime(2026,10,day,hour,tzinfo=assistant_clock.SHANGHAI)
            item.end_at=item.start_at+timedelta(hours=1)
            if index==1:item.plan_id=next_plan.id
        db.commit()
    clock[0]=dt('2026-10-11T20:55:00+08:00')
    assert client.post('/api/time-rules',json=dict(title='周日晚临时保护',kind='protected',recurrence='once',date='2026-10-11',start_time='21:00',end_time='22:00')).status_code==201
    before=official(client,sid)
    p=request(client,sid)
    assert p['status']=='ready',p
    assert by_ref(p['items'],f"task:{tasks[1]['id']}")==by_ref(before,f"task:{tasks[1]['id']}")
    assert len(p['retained'])==1 and p['retained'][0]['ref']==f"task:{tasks[2]['id']}"
    assert all(dt(x['start_at']).date()==date(2026,10,12) for x in p['items'])
    assert len(p['items'])==2
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==200
    assert len(official(client,sid))==3


def test_async_ai_draft_uses_same_scope_and_guard(client,test_engine):
    from app.models import AssistantRun
    from app.routers.assistant import _create_run_proposal
    sid,_=seed(client,test_engine)
    rule(client)
    with Session(test_engine) as db:
        run=AssistantRun(session_id=sid,client_message_id='mock-run',text='重新安排',status='running',phase='arranging',source_revision=revision(test_engine),payload={'latest_id':None,'latest_status':None,'base_actions':[],'preferences':{}})
        db.add(run);db.commit();run_id=run.id
    pid=_create_run_proposal(test_engine,run_id,[],[],{},None,None,'balanced')
    p=client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    assert p['id']==pid and p['change_groups']['counts']==dict(preserved=2,moved=1,added=0,pending=0)
    assert client.post(f'/api/assistant/proposals/{pid}/confirm').status_code==200


def test_small_local_replanning_benchmark_is_reproducible(client,test_engine):
    from time import perf_counter
    from app.services.assistant_state import build_proposal
    sid,_=seed(client,test_engine,[(f'任务{i}',8+i,20) for i in range(10)])
    rule(client,'08:00','09:00')
    timings=[];outputs=[]
    with Session(test_engine) as db:
        for _ in range(3):
            start=perf_counter();p=build_proposal(db,WEEK,[],allow_replan=True);timings.append(perf_counter()-start)
            assert p['status']=='ready' and p['change_groups']['counts']==dict(preserved=9,moved=1,added=0,pending=0)
            outputs.append(p['items'])
    assert outputs[0]==outputs[1]==outputs[2]
    # A generous regression ceiling, not a production latency claim.
    assert max(timings)<15
    print('stage1_local_10_tasks_seconds='+','.join(f'{t:.4f}' for t in timings))


def test_backup_roundtrip_keeps_scope_and_invalidates_pending_candidate(client,test_engine):
    sid,_=seed(client,test_engine)
    rule(client)
    p=request(client,sid)
    snapshot=client.get('/api/data/export').json()
    stored=next(x for x in snapshot['tables']['assistant_proposals'] if x['id']==p['id'])
    assert stored['payload']['replanning']==p['replanning']
    assert any((x['content'] or {}).get('replanning_guard') for x in snapshot['tables']['assistant_messages'] if x['proposal_id']==p['id'])
    result=client.post('/api/data/import',json=snapshot)
    assert result.status_code==200,result.text
    assert client.post(f"/api/assistant/proposals/{p['id']}/confirm").status_code==409
    assert client.get('/api/data/export').json()['tables']['assistant_proposals'][0]['payload']['replanning']==p['replanning']


def test_local_failure_does_not_lose_temporary_constraints(client,test_engine):
    from app.models import AssistantRun
    from app.routers.assistant import _create_run_proposal
    sid,_=seed(client,test_engine,[("紧急报告",8,10),("可调整练习",9,11)])
    with Session(test_engine) as db:
        run=AssistantRun(session_id=sid,client_message_id='mock-blocked',text='临时有事',status='running',phase='arranging',source_revision=revision(test_engine),payload={'latest_id':None,'latest_status':None,'base_actions':[],'preferences':{}})
        db.add(run);db.commit();run_id=run.id
    blocked={'blocked_windows':[dict(start_at='2026-10-05T08:00:00+08:00',end_at='2026-10-05T09:00:00+08:00')]}
    pid=_create_run_proposal(test_engine,run_id,[],[],{},None,blocked,None)
    p=client.get(f'/api/assistant/sessions/{sid}').json()['proposal']
    assert p['id']==pid and p['status']=='no_plan' and p['replanning']['requires_expansion']
    assert p['temporary_preferences']==blocked
    assert p['replanning']['mode']=='local'
    fact=next(d for d in p['diagnostics'] if d['code']=='TIME_RULE_CONFLICT')
    assert fact['rule_source']=='in_memory_constraint' and 'time_rule_id' not in fact
    expanded=client.post(f'/api/assistant/proposals/{pid}/preview',json={'expand_scope':True}).json()
    assert expanded['status']=='ready' and expanded['temporary_preferences']==blocked
    assert all(dt(x['start_at'])>=dt('2026-10-05T09:00:00+08:00') for x in expanded['items'])


def test_expansion_not_offered_when_all_preserved_tasks_are_protected(client,test_engine):
    sid,tasks=seed(client,test_engine,[("紧急报告",8,10),("锁定练习",9,11)])
    with Session(test_engine) as db:
        db.add(TaskSchedulingProfile(task_id=tasks[1]['id'],settings={'locked':True}));db.commit()
    rule(client,'08:00','09:00','protected')
    p=request(client,sid)
    assert p['status']=='no_plan' and not p['replanning']['requires_expansion']
    assert p['replanning']['preserved_refs']==p['replanning']['protected_refs']
    assert any(d['code']=='LOCKED_SEGMENT' for d in p['diagnostics'])
    assert client.post(f"/api/assistant/proposals/{p['id']}/preview",json={'expand_scope':True}).status_code==422
