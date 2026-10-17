"""The compatibility API cannot bypass current-time or execution protections."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Plan, PlanItem, Task, TaskSchedulingProfile
from app.services import assistant_clock
from .test_planning_state import revision
from .test_plans import WEEK, candidate, confirm, counts, create_task


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    value = [datetime.fromisoformat("2026-10-04T12:00:00+08:00")]
    monkeypatch.setattr(assistant_clock, "assistant_now", lambda: value[0])
    return value


def set_profile(engine, task_id, settings):
    with Session(engine) as db:
        db.add(TaskSchedulingProfile(task_id=task_id, settings=settings))
        db.commit()


def test_current_week_generation_uses_next_future_grid_without_editing_deadline(client, test_engine, clock):
    clock[0] = datetime.fromisoformat("2026-10-05T10:02:30+08:00")
    task_id = create_task(client)
    saved = candidate(client, [task_id])
    assert saved["items"][0]["start_at"] == "2026-10-05T02:05:00Z"
    assert confirm(client, saved["id"])["items"] == saved["items"]
    task = client.get("/api/tasks").json()[0]
    assert task["status"] == "todo" and task["deadline"] == "2026-10-05T10:00:00Z"
    with Session(test_engine) as db:
        assert db.get(Task, task_id).status.value == "todo"


def test_elapsed_week_rejected_without_writes(client, test_engine, clock):
    task_id = create_task(client)
    clock[0] = datetime.fromisoformat("2026-10-12T00:00:00+08:00")
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PAST_PLANNING_WINDOW"
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 1


@pytest.mark.parametrize("now,expected", [
    ("2026-10-05T00:00:00+08:00", "2026-10-05T00:00:00Z"),
    ("2026-10-11T21:54:59+08:00", "2026-10-11T13:55:00Z"),
    ("2026-10-11T13:54:59+00:00", "2026-10-11T13:55:00Z"),
    ("2026-10-05T10:02:30-07:00", "2026-10-06T00:00:00Z"),
])
def test_clock_boundaries_use_shanghai_grid(client, clock, now, expected):
    clock[0] = datetime.fromisoformat(now)
    task_id = create_task(client, duration_minutes=5, deadline="2026-10-11T22:00:00+08:00")
    saved = candidate(client, [task_id])
    assert saved["items"][0]["start_at"] == expected


@pytest.mark.parametrize("now,status", [
    ("2026-10-11T23:59:59+08:00", 409), ("2026-10-12T00:00:00+08:00", 422),
])
def test_week_end_midnight_never_creates_a_past_candidate(client, test_engine, clock, now, status):
    clock[0] = datetime.fromisoformat(now)
    task_id = create_task(client, duration_minutes=5, deadline="2026-10-12T22:00:00+08:00")
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id]})
    assert response.status_code == status
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 1


@pytest.mark.parametrize("now", ["2026-10-05T08:00:01+08:00", "2026-10-05T10:00:00+08:00"])
def test_time_advance_rejects_candidate_and_preserves_official(client, test_engine, clock, now):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    saved = candidate(client, [task_id])
    before = revision(test_engine), counts(test_engine)
    clock[0] = datetime.fromisoformat(now)
    response = client.post(f"/api/plans/{saved['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert (revision(test_engine), counts(test_engine)) == before
    assert client.get(f"/api/plans/{official['id']}").json() == official
    assert client.get(f"/api/plans/{saved['id']}").json() == saved


@pytest.mark.parametrize("settings", [
    {"locked": True}, {"splittable": True},
    {"fixed_start": "2026-10-05T12:00:00+08:00"},
    {"allowed_windows": [{"start_at": "2026-10-05T12:00:00+08:00", "end_at": "2026-10-05T16:00:00+08:00"}]},
])
def test_richer_profiles_cannot_be_ignored_by_legacy_generation(client, test_engine, settings):
    task_id = create_task(client)
    set_profile(test_engine, task_id, settings)
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PLAN_REQUIRES_ASSISTANT"
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 1


def test_unselected_locked_task_cannot_be_removed_from_official(client, test_engine):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    set_profile(test_engine, task_id, {"locked": True})
    other_id = create_task(client, title="Other")
    before = revision(test_engine), counts(test_engine)
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [other_id]})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "PLAN_REQUIRES_ASSISTANT"
    assert (revision(test_engine), counts(test_engine)) == before
    assert client.get(f"/api/plans/{official['id']}").json() == official


@pytest.mark.parametrize("now", [
    "2026-10-05T08:00:00+08:00", "2026-10-05T08:30:00+08:00", "2026-10-05T10:00:00+08:00",
])
def test_started_and_elapsed_official_records_cannot_be_overwritten(client, test_engine, clock, now):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    other_id = create_task(client, title="New work")
    before = revision(test_engine), counts(test_engine)
    clock[0] = datetime.fromisoformat(now)
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [other_id]})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "PLAN_REQUIRES_ASSISTANT"
    assert (revision(test_engine), counts(test_engine)) == before
    assert client.get(f"/api/plans/{official['id']}").json() == official


@pytest.mark.parametrize("violation", [
    "course", "protected", "duration", "deadline", "missing_task", "missing_course", "duplicate_task", "off_grid",
])
def test_confirmation_independently_rechecks_persisted_candidate(client, test_engine, violation):
    task_id = create_task(client)
    if violation in ("course", "protected", "missing_course"):
        kind = "protected" if violation == "protected" else "course"
        response = client.post("/api/time-rules", json={
            "kind": kind, "title": "Fixed time", "recurrence": "weekly", "weekday": 1,
            "start_time": "10:00", "end_time": "11:00",
        })
        assert response.status_code == 201
    saved = candidate(client, [task_id])
    with Session(test_engine) as db:
        item = db.scalar(select(PlanItem).where(PlanItem.plan_id == saved["id"], PlanItem.kind == "task"))
        if violation in ("course", "protected"):
            item.start_at = datetime.fromisoformat("2026-10-05T10:00:00+08:00")
            item.end_at = item.start_at + timedelta(minutes=90)
        elif violation == "duration":
            item.end_at += timedelta(minutes=5)
        elif violation == "deadline":
            item.start_at = datetime.fromisoformat("2026-10-05T17:00:00+08:00")
            item.end_at = item.start_at + timedelta(minutes=90)
        elif violation == "missing_task":
            db.delete(item)
        elif violation == "duplicate_task":
            db.add(PlanItem(
                plan_id=item.plan_id, kind="task", task_id=task_id, title_snapshot=item.title_snapshot,
                start_at=item.start_at + timedelta(hours=3), end_at=item.end_at + timedelta(hours=3),
            ))
        elif violation == "off_grid":
            item.start_at += timedelta(minutes=1)
            item.end_at += timedelta(minutes=1)
        else:
            db.execute(delete(PlanItem).where(PlanItem.plan_id == saved["id"], PlanItem.kind == "course"))
        db.commit()
    before = revision(test_engine), counts(test_engine)
    response = client.post(f"/api/plans/{saved['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert (revision(test_engine), counts(test_engine)) == before
    with Session(test_engine) as db:
        assert db.get(Plan, saved["id"]).status.value == "candidate"
        assert db.scalar(select(func.count()).select_from(Plan).where(Plan.status == "confirmed")) == 0


def test_confirmation_checks_profile_again_even_without_revision_change(client, test_engine):
    task_id = create_task(client)
    saved = candidate(client, [task_id])
    set_profile(test_engine, task_id, {"locked": True})
    response = client.post(f"/api/plans/{saved['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert revision(test_engine) == 1
