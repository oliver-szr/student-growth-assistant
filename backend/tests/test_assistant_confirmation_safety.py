"""Manual assistant confirmation preserves formal history and locked segments."""

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AssistantProposal, Plan, PlanItem, TaskSchedulingProfile
from app.services import assistant_clock
from .test_planning_state import revision
from .test_revision_workflow import send


@pytest.fixture
def formal_context(client, test_engine, monkeypatch):
    monkeypatch.setattr(assistant_clock, "assistant_now", lambda: datetime.fromisoformat("2026-10-07T12:00:00+08:00"))
    task_ids = []
    for title in ("已完成的历史", "已锁定的安排"):
        response = client.post("/api/tasks", json={
            "title": title, "duration_minutes": 60, "deadline": "2026-10-10T22:00:00+08:00",
        })
        assert response.status_code == 201
        task_ids.append(response.json()["id"])
    assert client.patch(f"/api/tasks/{task_ids[0]}", json={"status": "done"}).status_code == 200
    with Session(test_engine) as db:
        official = Plan(week_start=date(2026, 10, 5), status="confirmed", source_revision=0, task_ids=task_ids)
        db.add(official)
        db.flush()
        for task_id, title, start in zip(task_ids, ("已完成的历史", "已锁定的安排"),
                                         ("2026-10-05T08:00:00+08:00", "2026-10-08T08:00:00+08:00")):
            start_at = datetime.fromisoformat(start)
            db.add(PlanItem(plan_id=official.id, kind="task", task_id=task_id, title_snapshot=title,
                            start_at=start_at, end_at=start_at + timedelta(hours=1)))
        db.add(TaskSchedulingProfile(task_id=task_ids[1], settings={"locked": True}))
        db.commit()
    sid = client.post("/api/assistant/sessions", json={}).json()["id"]
    proposal = send(client, sid, [{"op": "add", "fields": {
        "title": "新任务", "duration_minutes": 45, "deadline": "2026-10-09T22:00:00+08:00",
        "profile": {"fixed_start": "2026-10-07T13:05:00+08:00"},
    }}])
    assert proposal["status"] == "ready", proposal
    return sid, proposal, task_ids


def formal_items(engine):
    with Session(engine) as db:
        return sorted((item.task_id, item.title_snapshot, item.start_at, item.end_at)
                      for item in db.scalars(select(PlanItem).join(Plan).where(
                          Plan.status == "confirmed", PlanItem.kind == "task")).all())


def test_manual_confirmation_preserves_history_locks_and_idempotency(client, test_engine, formal_context):
    _, proposal, task_ids = formal_context
    before = formal_items(test_engine)
    before_revision = revision(test_engine)
    response = client.post(f"/api/assistant/proposals/{proposal['id']}/confirm")
    assert response.status_code == 200, response.text
    assert all(item in formal_items(test_engine) for item in before)
    assert revision(test_engine) == before_revision + 1
    assert client.post(f"/api/assistant/proposals/{proposal['id']}/confirm").status_code == 200
    assert revision(test_engine) == before_revision + 1
    tasks = client.get("/api/tasks").json()
    assert next(task for task in tasks if task["id"] == task_ids[0])["status"] == "done"
    assert next(task for task in tasks if task["title"] == "新任务")["status"] == "todo"


@pytest.mark.parametrize("target", ["history", "locked", "locked_reasserted"])
def test_altered_preserved_segments_cannot_be_confirmed(client, test_engine, formal_context, target):
    _, proposal, task_ids = formal_context
    before = formal_items(test_engine)
    before_revision = revision(test_engine)
    with Session(test_engine) as db:
        row = db.get(AssistantProposal, proposal["id"])
        payload = deepcopy(row.payload)
        if target == "history":
            item = next(x for x in payload["retained"] if x["ref"] == f"task:{task_ids[0]}")
        else:
            item = next(x for x in payload["items"] if x["ref"] == f"task:{task_ids[1]}")
            if target == "locked_reasserted":
                payload["actions"].append({"op": "update", "target": item["ref"], "fields": {"profile": {"locked": True}}})
        item["start_at"] = (datetime.fromisoformat(item["start_at"]) + timedelta(minutes=5)).isoformat()
        item["end_at"] = (datetime.fromisoformat(item["end_at"]) + timedelta(minutes=5)).isoformat()
        row.payload = payload
        db.commit()
    response = client.post(f"/api/assistant/proposals/{proposal['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert revision(test_engine) == before_revision
    assert formal_items(test_engine) == before
