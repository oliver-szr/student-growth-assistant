"""Stage 2 safety contracts: isolated SQLite, mocked provider, no personal data."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import Session

from app.database import create_sqlite_engine
from app.models import GrowthChangeDraft, Plan, PlanItem, PlanningState, Task, TaskFeedback, TaskGrowthContext, TaskSchedulingProfile, TaskWorkSession
from app.services import assistant_ai, assistant_clock
from app.services.claude_client import AIServiceError, ClaudeConfig
from app.services.schema_migrations import upgrade_database

DEADLINE = "2026-10-25T20:00:00+08:00"
BASE = "/api/tasks/breakdown-drafts"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = [datetime.fromisoformat("2026-10-14T18:00:00+08:00")]
    monkeypatch.setattr(assistant_clock, "assistant_now", lambda: now[0])
    return now


def task(client, **fields):
    response = client.post("/api/tasks", json={"title": "项目", "duration_minutes": 60, "deadline": DEADLINE, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def content(count=3):
    return {"parent": {"title": "Software Engineering Project", "description": "课程项目", "deadline": DEADLINE},
            "children": [{"title": f"工作 {i}", "description": None, "duration_minutes": 60, "deadline": DEADLINE, "sort_order": i} for i in range(count)]}


def draft(client, monkeypatch=None, **fields):
    if monkeypatch:
        async def mock(*args):
            return content()
        monkeypatch.setattr(assistant_ai, "decompose_task", mock)
    response = client.post(BASE, json={"client_request_id": uuid4().hex, "source": "ai" if monkeypatch else "manual",
                           "text": "两周内完成课程项目", "title": "课程项目", "deadline": DEADLINE,
                           "expected_duration_minutes": 180, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def edited(client, data, body=None):
    response = client.patch(f"{BASE}/{data['id']}", json={"version": data["version"], "content": body or content()})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, data):
    return client.post(f"{BASE}/{data['id']}/confirm", json={"version": data["version"]})


def revision(engine):
    with Session(engine) as db:
        return db.get(PlanningState, 1).revision


def test_manual_hierarchy_goal_inheritance_and_ordinary_compatibility(client):
    old = task(client)
    assert old["task_kind"] == "executable" and old["parent_task_id"] is None
    parent = task(client, task_kind="container")
    goal = client.post('/api/goals', json={"title": "课程", "metric_kind": "count", "weekly_target": 3}).json()
    assert client.put(f"/api/tasks/{parent['id']}/growth-context", json={"family": "writing", "goal_id": goal['id']}).status_code == 200
    children = [task(client, parent_task_id=parent['id'], sort_order=i) for i in range(3)]
    assert len({c['id'] for c in children}) == 3
    assert all(client.get(f"/api/tasks/{c['id']}/growth-context").json()['goal_id'] == goal['id'] for c in children)
    parent = next(t for t in client.get('/api/tasks').json() if t['id'] == parent['id'])
    assert parent['progress']['total_children'] == 3
    assert parent['progress']['completed_children'] == 0
    assert parent['progress']['total_estimate_minutes'] == 180


def test_hierarchy_refuses_self_cycles_depth_missing_and_ddl(client):
    parent = task(client, task_kind='container')
    child = task(client, parent_task_id=parent['id'])
    for fields, code in [({'parent_task_id': child['id']}, 'INVALID_TASK_HIERARCHY'),
                         ({'parent_task_id': 99999}, 'PARENT_NOT_FOUND'),
                         ({'deadline': '2026-10-26T20:00:00+08:00'}, 'CHILD_DEADLINE_INVALID')]:
        response = client.patch(f"/api/tasks/{child['id']}", json=fields)
        assert response.status_code == 422 and response.json()['detail']['code'] == code
    assert client.patch(f"/api/tasks/{parent['id']}", json={'parent_task_id': child['id']}).status_code == 422
    assert client.patch(f"/api/tasks/{parent['id']}", json={'deadline':'2026-10-24T20:00:00+08:00'}).status_code == 422
    assert client.post('/api/tasks', json={'title':'层级3','duration_minutes':30,'deadline':DEADLINE,'parent_task_id':child['id']}).status_code == 422
    assert client.delete(f"/api/tasks/{parent['id']}").status_code == 405
    assert client.patch(f"/api/tasks/{parent['id']}", json={'status':'cancelled'}).status_code == 422
    assert len(client.get('/api/tasks').json()) == 2


@pytest.mark.parametrize('fact', ['plan', 'feedback', 'timer', 'lock'])
def test_conversion_preserves_execution_facts(client, test_engine, fact):
    ordinary = task(client)
    with Session(test_engine) as db:
        if fact == 'plan':
            plan = Plan(week_start=datetime(2026,10,12).date(),status='confirmed',source_revision=1,task_ids=[ordinary['id']])
            db.add(plan); db.flush()
            db.add(PlanItem(plan_id=plan.id,kind='task',task_id=ordinary['id'],title_snapshot='项目',start_at=datetime.fromisoformat('2026-10-14T09:00:00+08:00'),end_at=datetime.fromisoformat('2026-10-14T10:00:00+08:00')))
        elif fact == 'feedback':
            db.add(TaskFeedback(task_id=ordinary['id'],client_action_id='fact',outcome='postponed',title_snapshot='项目',deadline_snapshot=datetime.fromisoformat(DEADLINE),priority_snapshot='normal',initial_estimate_minutes=60))
        elif fact == 'timer':
            db.add(TaskWorkSession(task_id=ordinary['id'],client_action_id='fact'))
        else:
            db.add(TaskSchedulingProfile(task_id=ordinary['id'],settings={'locked':True}))
        db.commit()
    before = client.get('/api/data/export').json()['tables']
    response = client.patch(f"/api/tasks/{ordinary['id']}", json={'task_kind':'container'})
    assert response.status_code == 409 and response.json()['detail']['code'] == 'TASK_HAS_EXECUTION_FACTS'
    assert client.get('/api/data/export').json()['tables'] == before


def test_unused_task_can_convert_but_containers_cannot_execute(client):
    ordinary = task(client)
    assert client.patch(f"/api/tasks/{ordinary['id']}",json={'task_kind':'container'}).status_code == 200
    assert client.post(f"/api/tasks/{ordinary['id']}/feedback",json={'client_action_id':'x','outcome':'completed'}).status_code == 422
    assert client.post('/api/work-sessions/start',json={'task_id':ordinary['id'],'client_action_id':'x'}).status_code == 422
    assert client.post('/api/plans/candidates',json={'week_start':'2026-10-12','task_ids':[ordinary['id']]}).status_code == 422


def test_ai_draft_edit_cancel_and_refresh_create_no_formal_tasks(client, monkeypatch):
    data = draft(client, monkeypatch)
    assert not client.get('/api/tasks').json()
    changed = content(); changed['children'][0]['duration_minutes']=90
    changed['children'].pop(1)
    changed['children'].append({'title':'手动补充','duration_minutes':30,'deadline':DEADLINE,'sort_order':1})
    data = edited(client, data, changed)
    assert data['total_minutes'] == 180 and data['difference_minutes'] == 0
    assert client.get(BASE).json()[0]['content'] == data['content']
    assert client.post(f"{BASE}/{data['id']}/discard",json={'version':data['version']}).status_code == 200
    assert confirm(client,data).status_code == 409
    assert not client.get('/api/tasks').json()
    assert client.get(BASE).json() == []


@pytest.mark.parametrize('invalid', ['missing','duration','date','too_many','parent_ddl','past','blank','order'])
def test_bad_ai_never_creates_tasks_or_drafts(client,monkeypatch,invalid):
    bad=content()
    if invalid=='missing':del bad['children'][0]['title']
    if invalid=='duration':bad['children'][0]['duration_minutes']=7
    if invalid=='date':bad['children'][0]['deadline']='not-a-date'
    if invalid=='too_many':bad['children']*=8
    if invalid=='parent_ddl':bad['parent']['deadline']='2026-10-26T20:00:00+08:00'
    if invalid=='past':bad['children'][0]['deadline']='2026-10-10T20:00:00+08:00'
    if invalid=='blank':bad['children'][0]['title']='  '
    if invalid=='order':bad['children'][0]['sort_order']=1
    async def mock(*args):return bad
    monkeypatch.setattr(assistant_ai,'decompose_task',mock)
    response=client.post(BASE,json={'client_request_id':uuid4().hex,'text':'项目','title':'项目','deadline':DEADLINE,'expected_duration_minutes':180})
    assert response.status_code==502 and response.json()['detail']['code']=='AI_RESPONSE_INVALID'
    assert client.get('/api/tasks').json()==[] and client.get(BASE).json()==[]


def test_ai_missing_key_and_failure_allow_manual(client,monkeypatch):
    request={'client_request_id':uuid4().hex,'text':'项目','title':'项目','deadline':DEADLINE,'expected_duration_minutes':180}
    response=client.post(BASE,json=request)
    assert response.status_code==503 and response.json()['detail']['code']=='AI_NOT_CONFIGURED'
    async def unavailable(*args):raise AIServiceError('AI_UNAVAILABLE')
    monkeypatch.setattr(assistant_ai,'decompose_task',unavailable)
    assert client.post(BASE,json=request).json()['detail']['code']=='AI_UNAVAILABLE'
    data=draft(client)
    assert data['content']['children']==[]
    assert confirm(client,data).status_code==422


def test_existing_provider_adapter_and_json_schema(client, monkeypatch):
    calls=[]
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig(api_key='mock',model='mock'))
    async def request(text, system, config, max_tokens):
        calls.append(json.loads(text))
        return json.dumps(content())
    monkeypatch.setattr(assistant_ai,'request_claude',request)
    response=client.post(BASE,json={'client_request_id':'provider-mock','text':'项目','title':'项目','deadline':DEADLINE,'expected_duration_minutes':180})
    assert response.status_code==201 and calls[0]['request']['title']=='项目'


def test_confirm_atomic_idempotent_goal_inheritance_and_candidate_invalidation(client,monkeypatch,test_engine):
    goal=client.post('/api/goals',json={'title':'课程目标','metric_kind':'count','weekly_target':3}).json()
    session=client.post('/api/assistant/sessions',json={}).json()['id']
    candidate=client.post(f'/api/assistant/sessions/{session}/messages',json={'client_message_id':'candidate','text':'安排','replan':True}).json()
    data=draft(client,monkeypatch,goal_id=goal['id'])
    before=revision(test_engine)
    response=confirm(client,data)
    assert response.status_code==200,response.text
    ids=response.json()['created_task_ids'];assert len(ids)==4
    again=confirm(client,data)
    assert again.json()['created_task_ids']==ids and len(client.get('/api/tasks').json())==4
    assert revision(test_engine)==before+1
    assert all(client.get(f'/api/tasks/{i}/growth-context').json()['goal_id']==goal['id'] for i in ids)
    assert client.post(f"/api/assistant/proposals/{candidate['id']}/confirm").status_code==409
    parent=client.get('/api/tasks').json()[0]
    assert parent['duration_minutes']==180 and parent['progress']['total_estimate_minutes']==180


def test_third_child_failure_rolls_back_everything(client,monkeypatch,test_engine):
    data=draft(client,monkeypatch)
    before=revision(test_engine)
    def fail(mapper, connection, target):
        if target.parent_task_id is not None and target.sort_order==2:raise RuntimeError('third child injection')
    event.listen(Task,'before_insert',fail)
    try:
        with pytest.raises(RuntimeError,match='third child'):confirm(client,data)
    finally:event.remove(Task,'before_insert',fail)
    assert client.get('/api/tasks').json()==[] and revision(test_engine)==before
    with Session(test_engine) as db:
        assert db.get(GrowthChangeDraft,data['id']).status=='ready'
        assert list(db.scalars(select(TaskGrowthContext)).all())==[]
    assert confirm(client,data).status_code==200


def test_stale_state_edit_version_cancel_and_generic_route_protection(client,monkeypatch):
    data=draft(client,monkeypatch)
    newer=edited(client,data)
    assert confirm(client,data).json()['detail']['code']=='DRAFT_VERSION_CONFLICT'
    assert client.patch(f"{BASE}/{data['id']}",json={'version':data['version'],'content':content()}).status_code==409
    for operation in ('confirm','discard'):
        assert client.post(f"/api/assistant/drafts/{data['id']}/{operation}").status_code==422
    task(client)
    assert confirm(client,newer).json()['detail']['code']=='STALE_DRAFT'
    assert client.get(f"{BASE}/{data['id']}").json()['status']=='stale'
    assert client.post(f"{BASE}/{data['id']}/discard",json={'version':newer['version']}).status_code==200


def test_generation_retry_and_version_change_during_provider(client,monkeypatch):
    data=draft(client,monkeypatch)
    assert client.post(BASE,json=data['input']).json()['id']==data['id']
    conflicting={**data['input'],'title':'其他'}
    assert client.post(BASE,json=conflicting).status_code==409


def test_parent_progress_from_feedback_no_double_counting(client,monkeypatch):
    data=confirm(client,draft(client,monkeypatch)).json();parent,*children=data['created_task_ids']
    assert client.post(f'/api/tasks/{children[0]}/feedback',json={'client_action_id':'partial','outcome':'partial','remaining_minutes':30,'actual_minutes':20}).status_code==201
    assert client.post(f'/api/tasks/{children[1]}/feedback',json={'client_action_id':'done','outcome':'completed','actual_minutes':60}).status_code==201
    p=client.get('/api/tasks/dashboard').json()['tasks'][0]['progress']
    assert (p['total_children'],p['completed_children'],p['partial_children'],p['executed_children'],p['actual_minutes'])==(3,1,1,2,80)
    assert p['total_estimate_minutes']==180 and p['remaining_minutes']==90
    # Public review uses these deterministic feedback facts, never parent summaries.
    response=client.post('/api/growth/reviews',json={'week_start':'2026-10-12'})
    assert response.status_code in (200,201),response.text
    assert response.json()['facts']['completed_count']==1
    assert response.json()['facts']['confirmed_actual_minutes']==80
    assert client.get('/api/data/export').json()['tables']['task_feedback'][0]['task_id']!=parent


def test_migration_from_genuine_v1_preserves_ids_plans_history_locks(tmp_path,monkeypatch):
    monkeypatch.setenv('SGA_BACKUP_DIR',str(tmp_path/'backups'))
    fixture=json.loads((Path(__file__).parent/'fixtures/legacy_v1_snapshot.json').read_text(encoding='utf-8'))
    spec=importlib.util.spec_from_file_location('migration_baseline_test',Path(__file__).parents[1]/'alembic/baseline_models.py')
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    engine=create_sqlite_engine(f'sqlite:///{tmp_path / "legacy.db"}')
    baseline.Base.metadata.create_all(engine)
    # Populate exact frozen rows through the old column types.
    from app.services.growth_data import _decode_value
    with engine.begin() as connection:
        for table in baseline.Base.metadata.sorted_tables:
            for source in fixture['tables'][table.name]:
                row={c.name:_decode_value(c,source[c.name]) for c in table.columns}
                connection.execute(table.insert(),row)
        connection.execute(text('CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        connection.execute(text("INSERT INTO alembic_version VALUES('0001_baseline')"))
    upgrade_database(engine);upgrade_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT id,parent_task_id,task_kind,sort_order FROM tasks')).one()==(42,None,'executable',0)
        assert connection.execute(text('SELECT id,task_id FROM plan_items')).one()==(8,42)
        assert connection.execute(text('SELECT id,task_id FROM task_feedback')).one()==(5,42)
        assert json.loads(connection.execute(text('SELECT settings FROM task_scheduling_profiles')).scalar())['locked'] is True
        assert connection.execute(text('PRAGMA foreign_key_check')).all()==[]
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar()=='0004_review_records'
    assert list((tmp_path/'backups').rglob('*.sqlite'))
    engine.dispose()


def test_true_v1_restore_and_strict_conversion(client):
    old=json.loads((Path(__file__).parent/'fixtures/legacy_v1_snapshot.json').read_text(encoding='utf-8'))
    assert old['format_version']==1 and 'task_kind' not in old['tables']['tasks'][0]
    assert client.post('/api/data/import',json=old).status_code==200
    row=client.get('/api/tasks').json()[0]
    assert row['id']==42 and row['parent_task_id'] is None and row['task_kind']=='executable'
    bad=deepcopy(old);bad['tables']['tasks'][0]['task_kind']='container'
    assert client.post('/api/data/import',json=bad).status_code==422
    assert client.get('/api/tasks').json()[0]['id']==42


def test_v2_restore_relationships_and_transaction_rollback(client,monkeypatch):
    data=confirm(client,draft(client,monkeypatch)).json()
    snapshot=client.get('/api/data/export').json();assert snapshot['format_version']==4
    assert client.post('/api/data/import',json=snapshot).status_code==200
    rows=client.get('/api/tasks').json();assert all(r['parent_task_id']==rows[0]['id'] for r in rows[1:])
    before=client.get('/api/data/export').json()['tables']
    for mutation in ('dangling','cycle','depth','deadline','fk'):
        bad=deepcopy(snapshot)
        if mutation=='dangling':bad['tables']['tasks'][1]['parent_task_id']=99999
        if mutation=='cycle':bad['tables']['tasks'][0]['parent_task_id']=bad['tables']['tasks'][1]['id']
        if mutation=='depth':bad['tables']['tasks'][2]['parent_task_id']=bad['tables']['tasks'][1]['id']
        if mutation=='deadline':bad['tables']['tasks'][1]['deadline']='2026-10-26T20:00:00+08:00'
        if mutation=='fk':bad['tables']['task_growth_contexts'][0]['goal_id']=99999
        assert client.post('/api/data/import',json=bad).status_code==422
        assert client.get('/api/data/export').json()['tables']==before


def plan_request(client, sid, **fields):
    response=client.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':uuid4().hex,'text':'局部重规划','replan':True,**fields})
    assert response.status_code==200,response.text
    return response.json()


def test_children_use_two_week_split_scheduler_once_and_completed_excluded(client,monkeypatch,test_engine):
    data=confirm(client,draft(client,monkeypatch)).json();parent,*children=data['created_task_ids']
    assert client.patch(f'/api/tasks/{children[0]}',json={'duration_minutes':120}).status_code==200
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    profile={'splittable':True,'min_block_minutes':60,'max_segments':2,'allowed_windows':[
        {'start_at':'2026-10-18T20:00:00+08:00','end_at':'2026-10-18T21:00:00+08:00'},
        {'start_at':'2026-10-19T08:00:00+08:00','end_at':'2026-10-19T09:00:00+08:00'}]}
    candidate=plan_request(client,sid,actions=[{'op':'update','target':f'task:{children[0]}','fields':{'profile':profile}}])
    assert candidate['status']=='ready',candidate
    assert f'task:{parent}' not in candidate['selected_refs']
    refs=[i['ref'] for i in candidate['items']]
    assert refs.count(f'task:{children[0]}')==2 and set(refs)=={f'task:{i}' for i in children}
    assert sum(int((datetime.fromisoformat(i['end_at'])-datetime.fromisoformat(i['start_at'])).total_seconds()/60) for i in candidate['items'])==240
    assert client.post(f"/api/assistant/proposals/{candidate['id']}/confirm").status_code==200
    with Session(test_engine) as db:
        plans=db.scalars(select(Plan).where(Plan.status=='confirmed')).all()
        assert len(plans)==2 and all(parent not in p.task_ids for p in plans)
        assert all(children[0] in p.task_ids for p in plans)
    assert client.post(f'/api/tasks/{children[1]}/feedback',json={'client_action_id':'done','outcome':'completed'}).status_code==201
    next_candidate=plan_request(client,sid)
    assert next_candidate['status']=='ready'
    assert f'task:{children[1]}' not in next_candidate['selected_refs']
    assert not any(i['ref']==f'task:{children[1]}' for i in next_candidate['items'])
    assert client.post(f"/api/assistant/proposals/{next_candidate['id']}/confirm").status_code==200


def test_child_local_replan_preserves_history_and_lock(client,monkeypatch,test_engine):
    data=confirm(client,draft(client,monkeypatch)).json();parent,*children=data['created_task_ids']
    with Session(test_engine) as db:
        plan=Plan(week_start=datetime(2026,10,12).date(),status='confirmed',source_revision=revision(test_engine),task_ids=children)
        db.add(plan);db.flush()
        for child,start in zip(children,['2026-10-14T09:00:00+08:00','2026-10-15T10:00:00+08:00','2026-10-15T12:00:00+08:00']):
            start=datetime.fromisoformat(start)
            db.add(PlanItem(plan_id=plan.id,kind='task',task_id=child,title_snapshot=f'工作 {children.index(child)}',start_at=start,end_at=start+timedelta(hours=1)))
        db.add(TaskSchedulingProfile(task_id=children[1],settings={'locked':True}))
        db.commit()
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    before=client.get(f'/api/assistant/sessions/{sid}').json()['confirmed_items']
    assert client.post('/api/time-rules',json={'kind':'course','title':'临时课','recurrence':'once','date':'2026-10-15','start_time':'12:00','end_time':'13:00'}).status_code==201
    candidate=plan_request(client,sid,actions=[{'op':'update','target':f'task:{children[2]}','fields':{}}])
    assert candidate['status']=='ready',candidate
    locked=next(i for i in before if i['ref']==f'task:{children[1]}')
    history=next(i for i in before if i['ref']==f'task:{children[0]}')
    assert locked in candidate['items'] and history in candidate['retained']
    assert client.post(f"/api/assistant/proposals/{candidate['id']}/confirm").status_code==200
    after=client.get(f'/api/assistant/sessions/{sid}').json()['confirmed_items']
    assert locked in after and history in after
    summary=client.get('/api/tasks').json()[0]['progress']
    assert summary['completed_children']==0  # The elapsed historical item is not completion evidence.


def test_parent_deadline_cannot_be_bypassed_by_assistant(client,monkeypatch):
    data=confirm(client,draft(client,monkeypatch)).json();parent,child,*_=data['created_task_ids']
    sid=client.post('/api/assistant/sessions',json={}).json()['id']
    for target,fields,code in [(parent,{},'CONTAINER_NOT_EXECUTABLE'),(child,{'deadline':'2026-10-26T20:00:00+08:00'},'CHILD_DEADLINE_INVALID')]:
        response=client.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':uuid4().hex,'text':'修改','actions':[{'op':'update','target':f'task:{target}','fields':fields}]})
        assert response.status_code==422 and response.json()['detail']['code']==code


def test_concurrent_confirm_serialized_by_sqlite(client,monkeypatch,test_engine):
    from concurrent.futures import ThreadPoolExecutor
    data=draft(client,monkeypatch);before=revision(test_engine)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:confirm(client,data),range(2)))
    assert all(r.status_code==200 for r in responses)
    assert responses[0].json()['created_task_ids']==responses[1].json()['created_task_ids']
    assert len(client.get('/api/tasks').json())==4 and revision(test_engine)==before+1


def test_provider_releases_transaction_and_rejects_concurrent_state_change(client,monkeypatch,test_engine):
    from app.services.planning_state import bump_revision, planning_transaction
    async def mock(*args):
        with Session(test_engine) as db:
            with planning_transaction(db):bump_revision(db)
        return content()
    monkeypatch.setattr(assistant_ai,'decompose_task',mock)
    response=client.post(BASE,json={'client_request_id':'concurrent-generation','text':'项目','title':'项目','deadline':DEADLINE,'expected_duration_minutes':180})
    assert response.status_code==409 and response.json()['detail']['code']=='STALE_DRAFT'
    assert client.get('/api/tasks').json()==[] and client.get(BASE).json()==[]


def test_restore_invalidates_pending_breakdown_and_rejects_container_facts(client,monkeypatch):
    data=confirm(client,draft(client,monkeypatch)).json()
    pending=draft(client,monkeypatch)
    snapshot=client.get('/api/data/export').json()
    assert client.post('/api/data/import',json=snapshot).status_code==200
    assert client.get(f"{BASE}/{pending['id']}").json()['status']=='stale'
    assert confirm(client,pending).status_code==409
    bad=deepcopy(snapshot)
    bad['tables']['task_feedback'].append({
        'id':1,'task_id':data['created_task_ids'][0],'client_action_id':'invalid-container','outcome':'completed',
        'actual_minutes':None,'remaining_minutes':None,'title_snapshot':'parent','deadline_snapshot':DEADLINE,'priority_snapshot':'normal',
        'difficulty':None,'reason':None,'family_snapshot':'','category_name_snapshot':'未分类','family_confirmed_snapshot':False,
        'initial_estimate_minutes':180,'goal_id_snapshot':None,'goal_title_snapshot':None,'completed_at':None,
        'occurred_at':'2026-10-14T10:00:00+00:00','supersedes_id':None,'retracted_at':None,'created_at':'2026-10-14T10:00:00+00:00'})
    assert client.post('/api/data/import',json=bad).json()['detail']['code']=='CONTAINER_NOT_EXECUTABLE'


def test_confirm_revalidates_stored_data_and_future_ddl(client,monkeypatch,test_engine,clock):
    data=draft(client,monkeypatch)
    clock[0]=datetime.fromisoformat('2026-10-26T08:00:00+08:00')
    assert confirm(client,data).json()['detail']['code']=='BREAKDOWN_DEADLINE_INVALID'
    clock[0]=datetime.fromisoformat('2026-10-14T18:00:00+08:00')
    with Session(test_engine) as db:
        row=db.get(GrowthChangeDraft,data['id']);row.payload={**row.payload,'content':content(0)};db.commit()
    assert confirm(client,data).json()['detail']['code']=='INVALID_BREAKDOWN'
    assert client.get('/api/tasks').json()==[]


def test_hierarchy_dashboard_queries_remain_bounded(client,monkeypatch,test_engine):
    confirm(client,draft(client,monkeypatch))
    calls=[]
    def count(*args):calls.append(1)
    event.listen(test_engine,'before_cursor_execute',count)
    try:
        assert client.get('/api/tasks/dashboard').status_code==200
        assert len(calls)<=7
    finally:event.remove(test_engine,'before_cursor_execute',count)


def test_expired_child_is_stale_and_internal_session_cannot_schedule(client,monkeypatch,test_engine,clock):
    data=draft(client,monkeypatch)
    changed=content();changed['children'][0]['deadline']='2026-10-15T10:00:00+08:00'
    data=edited(client,data,changed)
    clock[0]=datetime.fromisoformat('2026-10-16T10:00:00+08:00')
    assert client.get(f"{BASE}/{data['id']}").json()['status']=='stale'
    assert confirm(client,data).status_code==422
    with Session(test_engine) as db:sid=db.get(GrowthChangeDraft,data['id']).session_id
    assert client.post(f'/api/assistant/sessions/{sid}/messages',json={'client_message_id':'internal','text':'排程','replan':True}).status_code==422
    assert client.post(f'/api/assistant/sessions/{sid}/runs',json={'client_message_id':'internal','text':'排程'}).status_code==422


@pytest.mark.parametrize('mutation',['deadline','duration','quantity'])
def test_editor_contract_rejects_invalid_trees_without_changing_saved_draft(client,monkeypatch,mutation):
    data=draft(client,monkeypatch);changed=content()
    if mutation=='deadline':changed['children'][0]['deadline']='2026-10-26T20:00:00+08:00'
    if mutation=='duration':changed['children'][0]['duration_minutes']=0
    if mutation=='quantity':changed['children']*=8
    assert client.patch(f"{BASE}/{data['id']}",json={'version':data['version'],'content':changed}).status_code==422
    assert client.get(f"{BASE}/{data['id']}").json()['content']==data['content']


def test_manual_child_limit_and_parent_type_are_enforced(client):
    parent=task(client,task_kind='container')
    children=[task(client,parent_task_id=parent['id'],sort_order=i) for i in range(20)]
    response=client.post('/api/tasks',json={'title':'too many','duration_minutes':30,'deadline':DEADLINE,'parent_task_id':parent['id']})
    assert response.status_code==422 and response.json()['detail']['code']=='TOO_MANY_CHILDREN'
    assert client.patch(f"/api/tasks/{parent['id']}",json={'task_kind':'executable'}).status_code==422
    assert client.patch(f"/api/tasks/{children[0]['id']}",json={'task_kind':'container'}).status_code==422


@pytest.mark.parametrize('case', [
    'json', 'fenced', 'http_500', 'timeout', 'malformed_json', 'missing_children',
    'missing_title', 'child_deadline', 'parent_deadline', 'duration', 'extra_text',
])
def test_breakdown_messages_transport_and_failure_isolation(client, monkeypatch, test_engine, case):
    """Exercise the real router/parser/transport together without any network access."""
    existing = task(client, title='Existing confirmed task')
    with Session(test_engine) as db:
        plan = Plan(week_start=datetime(2026, 10, 12).date(), status='confirmed',
                    source_revision=revision(test_engine), task_ids=[existing['id']])
        db.add(plan)
        db.flush()
        db.add(PlanItem(plan_id=plan.id, kind='task', task_id=existing['id'],
                        title_snapshot=existing['title'],
                        start_at=datetime.fromisoformat('2026-10-15T09:00:00+08:00'),
                        end_at=datetime.fromisoformat('2026-10-15T10:00:00+08:00')))
        db.commit()
    before = client.get('/api/data/export').json()['tables']
    request = {'client_request_id':'wire-test', 'source':'ai',
               'text':'Split Software Engineering Project into four actionable steps.',
               'title':'Software Engineering Project', 'deadline':DEADLINE,
               'expected_duration_minutes':180, 'goal_id':None}
    config = ClaudeConfig('offline-placeholder', 'qwen3.7-plus', 'https://gateway.example/v1/')
    monkeypatch.setattr(assistant_ai, 'get_claude_config', lambda: config)
    calls = []

    def handler(wire_request):
        calls.append(wire_request)
        assert wire_request.method == 'POST'
        assert str(wire_request.url) == 'https://gateway.example/v1/messages'
        assert wire_request.headers['x-api-key'] == config.api_key
        assert wire_request.headers['anthropic-version'] == '2023-06-01'
        assert wire_request.headers['content-type'] == 'application/json'
        body = json.loads(wire_request.content)
        assert set(body) == {'model', 'max_tokens', 'system', 'messages'}
        assert body['model'] == config.model and body['max_tokens'] == 4000
        assert isinstance(body['system'], str) and body['system']
        assert len(body['messages']) == 1 and body['messages'][0]['role'] == 'user'
        message = json.loads(body['messages'][0]['content'])
        assert message == {'request':request, 'context':{'now':'2026-10-14T18:00:00+08:00'}}
        if case == 'http_500':
            # Synthetic anonymous fixture; no claim about the real gateway's message.
            return httpx.Response(500, json={'error':{'type':'new_api_error', 'message':'synthetic gateway failure'}})
        if case == 'timeout':
            raise httpx.ReadTimeout('synthetic timeout', request=wire_request)
        result = content(4)
        if case == 'missing_children':
            del result['children']
        elif case == 'missing_title':
            del result['children'][0]['title']
        elif case == 'child_deadline':
            result['children'][0]['deadline'] = '2026-10-26T20:00:00+08:00'
        elif case == 'parent_deadline':
            result['parent']['deadline'] = '2026-10-26T20:00:00+08:00'
        elif case == 'duration':
            result['children'][0]['duration_minutes'] = 7
        answer = json.dumps(result)
        if case == 'fenced':
            answer = '```json\n' + answer + '\n```'
        elif case == 'malformed_json':
            answer = '{not valid JSON'
        elif case == 'extra_text':
            answer = 'Here is the suggested plan:\n' + answer
        return httpx.Response(200, json={'stop_reason':'end_turn', 'content':[{'type':'text', 'text':answer}]})

    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    response = client.post(BASE, json=request)
    assert len(calls) == 1  # A failed gateway request must never trigger an automatic retry.
    after = client.get('/api/data/export').json()['tables']
    if case in ('json', 'fenced'):
        assert response.status_code == 201, response.text
        assert response.json()['status'] == 'ready'
        assert len(response.json()['content']['children']) == 4
        assert response.json()['created_task_ids'] == []
        draft_tables = {'assistant_sessions', 'assistant_messages', 'growth_change_drafts'}
        assert {k:v for k,v in after.items() if k not in draft_tables} == {
            k:v for k,v in before.items() if k not in draft_tables}
    else:
        expected = 'AI_UNAVAILABLE' if case in ('http_500', 'timeout') else 'AI_RESPONSE_INVALID'
        assert response.status_code == (503 if expected == 'AI_UNAVAILABLE' else 502)
        assert response.json()['detail']['code'] == expected
        assert after == before  # Includes the pre-existing confirmed plan, revision and drafts.
    assert config.api_key not in response.text
