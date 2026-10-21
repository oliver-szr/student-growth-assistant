from datetime import timedelta
import pytest

from fastapi.testclient import TestClient
from app.services.assistant_clock import assistant_now


def test_export_and_import_restore_growth_data_atomically(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "项目复盘",
        "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(),
        "priority": "high",
    }).json()
    client.put("/api/goals/direction", json={"direction": "持续完成课程项目"})
    client.post("/api/goals", json={
        "title": "每周完成一次复盘", "metric_kind": "count", "weekly_target": 1, "unit_label": "次",
    })

    exported = client.get("/api/data/export")
    assert exported.status_code == 200
    snapshot = exported.json()
    assert snapshot["format_version"] == 3
    assert "growth_goals" in snapshot["tables"]

    client.patch(f"/api/tasks/{task['id']}", json={"status": "done"})
    client.put("/api/goals/direction", json={"direction": "should be rolled back"})
    restored = client.post("/api/data/import", json=snapshot)

    assert restored.status_code == 200
    assert client.get("/api/goals").json()["direction"] == "持续完成课程项目"
    assert client.get("/api/tasks").json()[0]["status"] == "todo"
    assert restored.json()["revision"] > snapshot["revision"]


def test_invalid_import_rolls_back_all_rows(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "保留任务", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    snapshot = client.get("/api/data/export").json()
    snapshot["tables"]["tasks"][0]["unknown_column"] = "invalid"

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422
    assert [row["id"] for row in client.get("/api/tasks").json()] == [task["id"]]


def test_task_growth_context_patch_preserves_goal_when_omitted(client: TestClient) -> None:
    goal = client.post("/api/goals", json={
        "title": "完成项目", "metric_kind": "deliverable", "weekly_target": 1, "unit_label": "项",
    }).json()
    task = client.post("/api/tasks", json={
        "title": "实现功能", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "writing", "goal_id": goal["id"]})

    changed = client.put(f"/api/tasks/{task['id']}/growth-context", json={"family": "reading"})

    assert changed.status_code == 200
    assert changed.json()["goal_id"] == goal["id"]


def test_import_requires_full_valid_snapshot_and_keeps_database_on_bad_reference(client: TestClient) -> None:
    task = client.post("/api/tasks", json={
        "title": "引用完整性", "duration_minutes": 60,
        "deadline": (assistant_now() + timedelta(days=2)).isoformat(), "priority": "normal",
    }).json()
    snapshot = client.get("/api/data/export").json()
    snapshot["tables"]["task_growth_contexts"][0]["goal_id"] = 999999

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422
    assert client.get("/api/tasks").json()[0]["id"] == task["id"]


def test_import_does_not_accept_wrong_schema_version(client: TestClient) -> None:
    snapshot = client.get("/api/data/export").json()
    snapshot["format_version"] = 999

    response = client.post("/api/data/import", json=snapshot)

    assert response.status_code == 422


def legacy_snapshot(version):
    import json
    from pathlib import Path
    value = json.loads((Path(__file__).parent/'fixtures/legacy_v1_snapshot.json').read_text(encoding='utf-8'))
    value['tables']['assistant_sessions'] = [dict(id=71, week_start='2026-10-12', scope='planning',
        latest_proposal_id=None, created_at='2026-10-14T10:00:00+00:00')]
    value['tables']['assistant_messages'] = [dict(id=81, session_id=71, client_message_id=None,
        role='user', text='匿名历史正文', proposal_id=None, content=None)]
    if version == 2:
        value['format_version'] = 2
        for row in value['tables']['tasks']:
            row.update(parent_task_id=None, task_kind='executable', sort_order=0)
    return value


@pytest.mark.parametrize('version', [1,2])
def test_legacy_restore_has_explicit_conversion_and_does_not_invent_message_times(client, version):
    old = legacy_snapshot(version)
    assert client.post('/api/data/import', json=old).status_code == 200
    exported = client.get('/api/data/export').json()
    assert exported['format_version'] == 3
    sessions = exported['tables']['assistant_sessions']
    messages = exported['tables']['assistant_messages']
    assert len(sessions) == len(old['tables']['assistant_sessions'])
    assert all(s['last_activity_at'] is None and s['updated_at'] is None for s in sessions)
    assert all(m['created_at'] is None for m in messages)
    assert client.post('/api/data/import', json=old).status_code == 200
    # Strict v2 columns must not silently absorb new metadata disguised as v2.
    if version == 2:
        old['tables']['assistant_sessions'][0]['title'] = '不能混入'
        assert client.post('/api/data/import', json=old).status_code == 422


@pytest.mark.parametrize('version', [1,2])
def test_old_restore_refuses_to_erase_new_conversations_including_deleted_tombstones(client, version):
    created = client.post('/api/conversations', json={'client_request_id':'retained'}).json()
    client.post(f"/api/conversations/{created['id']}/messages", json={'client_message_id':'retained','text':'升级后正文'})
    client.delete(f"/api/conversations/{created['id']}?expected_version=1")
    before = client.get('/api/data/export').json()['tables']
    response = client.post('/api/data/import', json=legacy_snapshot(version))
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'LEGACY_RESTORE_CONVERSATIONS_PRESENT'
    assert client.get('/api/data/export').json()['tables'] == before


def test_v3_restore_keeps_lifecycle_ownership_messages_and_transactional_rollback(client):
    from copy import deepcopy
    created = client.post('/api/conversations', json={'client_request_id':'restore','title':'手动名称'}).json()
    client.post(f"/api/conversations/{created['id']}/messages", json={'client_message_id':'message','text':'完整正文'})
    client.patch(f"/api/conversations/{created['id']}", json={'expected_version':1,'pinned':True,'archived':True})
    snapshot = client.get('/api/data/export').json()
    assert snapshot['format_version'] == 3
    assert client.post('/api/data/import', json=snapshot).status_code == 200
    read = client.get(f"/api/conversations/{created['id']}").json()
    assert read['title_source']=='manual' and read['pinned_at'] and read['archived_at']
    assert client.get(f"/api/conversations/{created['id']}/messages").json()['items'][0]['text'] == '完整正文'
    before = client.get('/api/data/export').json()['tables']
    for field in ('owner_id','session_id','role'):
        invalid = deepcopy(snapshot)
        invalid['tables']['assistant_messages'][0][field] = 999999 if field=='session_id' else None
        assert client.post('/api/data/import', json=invalid).status_code == 422
        assert client.get('/api/data/export').json()['tables'] == before


@pytest.mark.parametrize('exported_at', [None, 123, 'bad', '2026-10-14T12:00:00'])
def test_old_snapshot_rejects_invalid_export_time_without_writes(client, exported_at):
    old = legacy_snapshot(2)
    old['exported_at'] = exported_at
    before = client.get('/api/data/export').json()['tables']
    assert client.post('/api/data/import', json=old).status_code == 422
    assert client.get('/api/data/export').json()['tables'] == before


def test_v3_restore_interrupts_runs_stales_pending_but_keeps_terminal_receipts(client, test_engine):
    from sqlalchemy.orm import Session
    from app.models import AssistantRun, AssistantProposal, GrowthChangeDraft
    created = client.post('/api/conversations', json={'client_request_id':'pending-restore'}).json()
    with Session(test_engine) as db:
        run = AssistantRun(session_id=created['id'], client_message_id='not-live', text='匿名记录', status='running',
            phase='understanding', source_revision=0, payload={})
        pending = GrowthChangeDraft(session_id=created['id'], scope='conversation', source_revision=0, status='ready', payload={})
        terminal = AssistantProposal(session_id=created['id'], source_revision=0, status='superseded', payload={})
        db.add_all([run,pending,terminal]);db.commit()
        run_id, pending_id, terminal_id=run.id,pending.id,terminal.id
    snapshot = client.get('/api/data/export').json()
    assert client.post('/api/data/import', json=snapshot).status_code == 200
    with Session(test_engine) as db:
        assert db.get(AssistantRun,run_id).status == 'interrupted'
        assert db.get(GrowthChangeDraft,pending_id).status == 'stale'
        assert db.get(AssistantProposal,terminal_id).status == 'superseded'


@pytest.mark.parametrize('version', [1,2])
@pytest.mark.parametrize('invalid', ['workspace_id','scope'])
def test_legacy_conversion_rejects_wrong_value_types_before_deriving_metadata(client, version, invalid):
    old = legacy_snapshot(version)
    if invalid == 'workspace_id':
        old['tables']['workspace_metadata'] = [dict(id=1, workspace_id=None, created_at=old['exported_at'])]
    else:
        old['tables']['assistant_sessions'][0]['scope'] = []
    before = client.get('/api/data/export').json()['tables']
    assert client.post('/api/data/import', json=old).status_code == 422
    assert client.get('/api/data/export').json()['tables'] == before
