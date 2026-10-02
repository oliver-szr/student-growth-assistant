"""Revision semantics, write atomicity, and SQLite concurrency protection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import PlanningState, Task, TimeRule
from app.routers import tasks, time_rules
from app.schemas import TaskCreate, TaskUpdate, TimeRuleCreate, TimeRuleUpdate
from app.services.planning_state import (
    begin_planning_transaction, bump_revision, get_or_create_planning_state,
)
from .test_tasks import TASK
from .test_time_rules import COURSE


def revision(engine):
    with Session(engine) as session:
        return session.get(PlanningState, 1).revision


def test_first_access_initializes_singleton_and_helpers_do_not_commit(test_engine):
    Base.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        assert session.get(PlanningState, 1) is None
        state = get_or_create_planning_state(session)
        assert (state.id, state.revision) == (1, 0)
        assert get_or_create_planning_state(session).id == 1
        session.rollback()
        assert session.get(PlanningState, 1) is None
        get_or_create_planning_state(session)
        session.commit()
        assert bump_revision(session) == 1
        session.rollback()
        assert session.get(PlanningState, 1).revision == 0
        assert session.scalar(select(func.count()).select_from(PlanningState)) == 1


def test_startup_initializes_state_without_manual_seed(client, test_engine):
    assert revision(test_engine) == 0
    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(PlanningState)) == 1


@pytest.mark.parametrize("id_value,revision_value", [(2, 0), (1, -1)])
def test_database_rejects_invalid_singleton_state(client, test_engine, id_value, revision_value):
    with Session(test_engine) as session:
        session.delete(session.get(PlanningState, 1))
        session.flush()
        session.add(PlanningState(id=id_value, revision=revision_value))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        assert session.get(PlanningState, 1).revision == 0


@pytest.mark.parametrize("changes", [
    {"title": "Changed"}, {"description": "Changed"}, {"description": None},
    {"duration_minutes": 120}, {"deadline": "2026-10-06T18:00:00+08:00"},
    {"priority": "low"}, {"status": "done"}, {"status": "cancelled"},
    {}, {"title": "Finish report"},
])
def test_task_create_and_every_successful_patch_bump_once(client, test_engine, changes):
    created = client.post("/api/tasks", json=TASK)
    assert created.status_code == 201
    assert revision(test_engine) == 1
    changed = client.patch(f"/api/tasks/{created.json()['id']}", json=changes)
    assert changed.status_code == 200
    assert revision(test_engine) == 2


@pytest.mark.parametrize("changes", [
    {"title": "Changed"}, {"weekday": 4}, {"start_time": "09:00"},
    {"end_time": "13:00"}, {"active": False}, {}, {"title": "Software Engineering"},
    {"kind": "protected", "recurrence": "once", "weekday": None, "date": "2026-10-06"},
])
def test_rule_create_and_every_successful_patch_bump_once(client, test_engine, changes):
    created = client.post("/api/time-rules", json=COURSE)
    assert created.status_code == 201
    assert revision(test_engine) == 1
    changed = client.patch(f"/api/time-rules/{created.json()['id']}", json=changes)
    assert changed.status_code == 200
    assert revision(test_engine) == 2


def test_get_and_rejected_crud_do_not_bump(client, test_engine):
    task_id = client.post("/api/tasks", json=TASK).json()["id"]
    rule_id = client.post("/api/time-rules", json=COURSE).json()["id"]
    assert revision(test_engine) == 2
    for path in ("/api/health", "/api/tasks", "/api/tasks?status=todo", "/api/time-rules"):
        assert client.get(path).status_code == 200
    assert client.post("/api/tasks", json={**TASK, "duration_minutes": 45.5}).status_code == 422
    assert client.post("/api/time-rules", json={**COURSE, "weekday": 8}).status_code == 422
    assert client.patch(f"/api/tasks/{task_id}", json={"deadline": None}).status_code == 422
    assert client.patch(f"/api/time-rules/{rule_id}", json={"start_time": "13:00"}).status_code == 422
    assert client.patch("/api/tasks/999", json={}).status_code == 404
    assert client.patch("/api/time-rules/999", json={}).status_code == 404
    assert revision(test_engine) == 2


@pytest.mark.parametrize("resource,operation", [
    ("task", "create"), ("task", "patch"), ("rule", "create"), ("rule", "patch"),
])
@pytest.mark.parametrize("failure", [SQLAlchemyError, RuntimeError])
def test_crud_write_and_revision_roll_back_together(
    client, test_engine, monkeypatch, resource, operation, failure,
):
    module = tasks if resource == "task" else time_rules
    model = Task if resource == "task" else TimeRule
    payload = TASK if resource == "task" else COURSE
    path = "/api/tasks" if resource == "task" else "/api/time-rules"
    before = 0
    object_id = None
    if operation == "patch":
        object_id = client.post(path, json=payload).json()["id"]
        before = 1
    original_bump = module.bump_revision

    def fail_after_writes(session):
        original_bump(session)
        session.flush()  # Prove actual SQL business writes and revision both roll back.
        raise failure("injected after CRUD and revision writes")

    monkeypatch.setattr(module, "bump_revision", fail_after_writes)
    with Session(test_engine, autoflush=False) as session:
        with pytest.raises(failure):
            if resource == "task" and operation == "create":
                tasks.create_task(TaskCreate(**payload), db=session)
            elif resource == "task":
                tasks.update_task(object_id, TaskUpdate(title="Changed"), db=session)
            elif operation == "create":
                time_rules.create_time_rule(TimeRuleCreate(**payload), db=session)
            else:
                time_rules.update_time_rule(object_id, TimeRuleUpdate(title="Changed"), db=session)
        assert not session.in_transaction()
        assert session.get(PlanningState, 1).revision == before
        assert session.scalar(select(func.count()).select_from(model)) == before
        if object_id is not None:
            assert session.get(model, object_id).title == payload["title"].strip()
    assert revision(test_engine) == before


def test_concurrent_initialization_and_bumps_have_no_lost_updates(test_engine):
    Base.metadata.create_all(test_engine)
    barrier = Barrier(4)

    def mutate(_):
        with Session(test_engine) as session:
            barrier.wait(timeout=5)
            begin_planning_transaction(session)
            assert get_or_create_planning_state(session).id == 1
            bump_revision(session)
            session.commit()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(mutate, range(4)))
    assert revision(test_engine) == 4
    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(PlanningState)) == 1
