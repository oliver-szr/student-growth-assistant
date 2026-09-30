"""Candidate persistence, confirmation lifecycle, and transaction failures."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier, Event

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import Plan, PlanItem, PlanItemKind, PlanningState, PlanStatus
from app.routers import plans
from app.schemas import CandidateCreate
from app.services.scheduling_types import ScheduleResult, ValidationResult, Violation
from .test_planning_state import revision
from .test_tasks import TASK
from .test_time_rules import COURSE, PROTECTED_ONCE


WEEK = "2026-10-05"


def create_task(client, **changes):
    response = client.post("/api/tasks", json={**TASK, **changes})
    assert response.status_code == 201
    return response.json()["id"]


def candidate(client, task_ids, week=WEEK):
    response = client.post("/api/plans/candidates", json={"week_start": week, "task_ids": task_ids})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "feasible" and body["unscheduled_tasks"] == []
    return body["candidate"]


def confirm(client, plan_id):
    response = client.post(f"/api/plans/{plan_id}/confirm")
    assert response.status_code == 200, response.text
    return response.json()


def counts(engine):
    with Session(engine) as session:
        return tuple(session.scalar(select(func.count()).select_from(model)) for model in (Plan, PlanItem))


def test_candidate_pipeline_persistence_and_utc_storage(client, test_engine, monkeypatch):
    task_id = create_task(client)
    original_schedule, original_validate = plans.schedule_week, plans.validate_schedule
    calls = []

    def schedule(*args):
        calls.append("scheduler")
        assert args[1][0].id == task_id
        assert args[1][0].deadline.utcoffset().total_seconds() == 0
        return original_schedule(*args)

    def validate(*args):
        calls.append("validator")
        result = original_validate(*args)
        assert result.valid
        return result

    monkeypatch.setattr(plans, "schedule_week", schedule)
    monkeypatch.setattr(plans, "validate_schedule", validate)
    saved = candidate(client, [task_id])
    assert calls == ["scheduler", "validator"]
    assert saved["status"] == "candidate" and saved["source_revision"] == 1
    assert saved["based_on_plan_id"] is None and saved["confirmed_at"] is None
    assert saved["task_ids"] == [task_id] and saved["created_at"].endswith("Z")
    assert len(saved["items"]) == 1
    item = saved["items"][0]
    assert item["kind"] == "task" and item["task_id"] == task_id and item["time_rule_id"] is None
    assert item["title_snapshot"] == "Finish report"
    assert item["start_at"] == "2026-10-05T00:00:00Z"
    assert item["end_at"] == "2026-10-05T01:30:00Z"
    assert client.get(f"/api/plans/{saved['id']}").json() == saved
    assert revision(test_engine) == 1 and counts(test_engine) == (1, 1)
    with Session(test_engine) as session:
        assert session.get(Plan, saved["id"]).task_ids == [task_id]
        stored = session.get(PlanItem, item["id"])
        assert stored.start_at == datetime(2026, 10, 5, tzinfo=timezone.utc)
    with test_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT start_at FROM plan_items").scalar_one().startswith("2026-10-05 00:00:00")


@pytest.mark.parametrize("payload", [
    {"week_start": "2026-10-06", "task_ids": [1]},
    {"week_start": WEEK, "task_ids": []},
    {"week_start": WEEK, "task_ids": [1, 1]},
    {"week_start": WEEK, "task_ids": [0]},
    {"week_start": WEEK, "task_ids": [True]},
    {"week_start": WEEK, "task_ids": ["1"]},
    {"week_start": WEEK, "task_ids": [1], "source_revision": 0},
    {"week_start": "not-a-date", "task_ids": [1]},
    {"week_start": "9999-12-27", "task_ids": [1]},
])
def test_reject_invalid_candidate_input_without_writes(client, test_engine, payload):
    create_task(client)
    assert client.post("/api/plans/candidates", json=payload).status_code == 422
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 1


@pytest.mark.parametrize("state", ["missing", "done", "cancelled"])
def test_reject_missing_or_non_todo_task_without_scheduling(client, test_engine, monkeypatch, state):
    task_id = create_task(client)
    if state == "missing":
        ids = [task_id, 999]
        expected_code = "TASK_NOT_FOUND"
    else:
        assert client.patch(f"/api/tasks/{task_id}", json={"status": state}).status_code == 200
        ids = [task_id]
        expected_code = "TASK_NOT_TODO"
    before = revision(test_engine)

    def forbidden(*args):
        pytest.fail("Scheduler must not see a missing or non-todo task")

    monkeypatch.setattr(plans, "schedule_week", forbidden)
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": ids})
    assert response.status_code == 422 and response.json()["detail"]["code"] == expected_code
    assert counts(test_engine) == (0, 0) and revision(test_engine) == before


def test_unschedulable_writes_nothing_and_preserves_official(client, test_engine):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    large = create_task(client, duration_minutes=900)
    before_revision, before_counts = revision(test_engine), counts(test_engine)
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id, large]})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "UNSCHEDULABLE" and "heuristic" in detail["message"]
    assert detail["unscheduled_tasks"][0]["task_id"] == large
    assert detail["unscheduled_tasks"][0]["reason_code"] == "NO_SLOT_FOUND"
    assert revision(test_engine) == before_revision and counts(test_engine) == before_counts
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == official


def test_invalid_time_rules_are_input_error_not_unschedulable(client, test_engine):
    task_id = create_task(client)
    for title in ("First", "Overlap"):
        assert client.post("/api/time-rules", json={**COURSE, "title": title}).status_code == 201
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id]})
    assert response.status_code == 422 and response.json()["detail"]["code"] == "INVALID_TIME_RULES"
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 3


@pytest.mark.parametrize("gate_failure", ["bad_assignments", "validator_rejects"])
def test_feasible_result_must_pass_independent_validator(client, test_engine, monkeypatch, gate_failure):
    task_id = create_task(client)
    if gate_failure == "bad_assignments":
        # A falsely claimed feasible result lacks the selected task.
        monkeypatch.setattr(plans, "schedule_week", lambda *args: ScheduleResult("feasible"))
    else:
        monkeypatch.setattr(plans, "validate_schedule", lambda *args: ValidationResult(
            False, (Violation("INJECTED", "Rejected by independent validator"),)
        ))
    response = client.post("/api/plans/candidates", json={"week_start": WEEK, "task_ids": [task_id]})
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "GENERATED_SCHEDULE_INVALID"
    assert counts(test_engine) == (0, 0) and revision(test_engine) == 1


def test_course_expansion_snapshots_and_protected_not_persisted(client, test_engine, monkeypatch):
    task_id = create_task(client)
    active_course = {**COURSE, "title": "Machine Learning", "weekday": 1, "start_time": "08:00", "end_time": "09:15"}
    rule_id = client.post("/api/time-rules", json=active_course).json()["id"]
    client.post("/api/time-rules", json={**COURSE, "active": False})
    client.post("/api/time-rules", json={**PROTECTED_ONCE, "date": WEEK, "start_time": "09:00", "end_time": "10:00"})
    client.post("/api/time-rules", json={**PROTECTED_ONCE, "date": "2026-10-12"})
    original_expand = plans.expand_time_rules
    calls = []

    def expand(*args):
        calls.append(args[0])
        return original_expand(*args)

    monkeypatch.setattr(plans, "expand_time_rules", expand)
    before = revision(test_engine)
    saved = candidate(client, [task_id])
    assert calls == [date(2026, 10, 5)]
    assert revision(test_engine) == before
    assert [item["kind"] for item in saved["items"]] == ["course", "task"]
    course_item, task_item = saved["items"]
    assert course_item["time_rule_id"] == rule_id and course_item["task_id"] is None
    assert course_item["title_snapshot"] == "Machine Learning"
    assert course_item["end_at"] == "2026-10-05T01:15:00Z"
    assert task_item["start_at"] == "2026-10-05T02:00:00Z"
    client.patch(f"/api/tasks/{task_id}", json={"title": "New task title"})
    client.patch(f"/api/time-rules/{rule_id}", json={"title": "Advanced ML"})
    assert client.get(f"/api/plans/{saved['id']}").json() == saved
    rejected = client.post(f"/api/plans/{saved['id']}/confirm")
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "STALE_CANDIDATE"


def test_multiple_candidates_do_not_change_official_or_revision(client, test_engine):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    before = revision(test_engine)
    left = candidate(client, [task_id])
    right = candidate(client, [task_id])
    assert left["id"] != right["id"]
    assert left["source_revision"] == right["source_revision"] == before
    assert left["based_on_plan_id"] == right["based_on_plan_id"] == official["id"]
    assert revision(test_engine) == before
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == official
    # Generation of right did not make left stale.
    replacement = confirm(client, left["id"])
    assert replacement["status"] == "confirmed"
    assert client.get(f"/api/plans/{official['id']}").json()["status"] == "superseded"


def test_confirmation_uses_persisted_candidate_and_bumps_once(client, test_engine, monkeypatch):
    task_id = create_task(client)
    saved = candidate(client, [task_id])

    def forbidden(*args):
        pytest.fail("Confirm must not rerun Scheduler")

    monkeypatch.setattr(plans, "schedule_week", forbidden)
    result = confirm(client, saved["id"])
    assert result["items"] == saved["items"] and result["task_ids"] == saved["task_ids"]
    assert result["status"] == "confirmed" and result["confirmed_at"].endswith("Z")
    assert result["source_revision"] == saved["source_revision"]
    assert revision(test_engine) == 2
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == result
    with Session(test_engine) as session:
        assert session.get(Plan, saved["id"]).confirmed_at.tzinfo is not None


def test_same_week_replacement_preserves_other_week(client, test_engine):
    task_id = create_task(client, deadline="2026-10-18T22:00:00+08:00")
    first = confirm(client, candidate(client, [task_id])["id"])
    other = confirm(client, candidate(client, [task_id], week="2026-10-12")["id"])
    replacement_candidate = candidate(client, [task_id])
    assert replacement_candidate["based_on_plan_id"] == first["id"]
    replacement = confirm(client, replacement_candidate["id"])
    old = client.get(f"/api/plans/{first['id']}").json()
    assert old["status"] == "superseded" and old["confirmed_at"] == first["confirmed_at"]
    assert old["items"] == first["items"]
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == replacement
    assert client.get("/api/plans/confirmed?week_start=2026-10-12").json() == other
    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(Plan).where(
            Plan.week_start == date(2026, 10, 5), Plan.status == PlanStatus.confirmed,
        )) == 1
    assert revision(test_engine) == 4


def test_repeat_and_superseded_confirm_rejected_before_stale_check(client, test_engine):
    task_id = create_task(client)
    first = confirm(client, candidate(client, [task_id])["id"])
    second = confirm(client, candidate(client, [task_id])["id"])
    before = revision(test_engine)
    for plan in (first, second):
        response = client.post(f"/api/plans/{plan['id']}/confirm")
        assert response.status_code == 409 and response.json()["detail"]["code"] == "PLAN_NOT_CANDIDATE"
    assert revision(test_engine) == before
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == second


def test_confirm_a_makes_b_stale_but_viewable(client, test_engine):
    task_id = create_task(client)
    left, right = candidate(client, [task_id]), candidate(client, [task_id])
    assert left["source_revision"] == right["source_revision"] == 1
    official = confirm(client, left["id"])
    response = client.post(f"/api/plans/{right['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert revision(test_engine) == 2
    assert client.get(f"/api/plans/{right['id']}").json() == right
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == official


@pytest.mark.parametrize("mutation", ["task_patch", "task_create", "rule_patch", "rule_create"])
def test_mutations_make_candidate_stale_with_no_confirm_side_effects(client, test_engine, mutation):
    task_id = create_task(client)
    rule_id = client.post("/api/time-rules", json=COURSE).json()["id"]
    official = confirm(client, candidate(client, [task_id])["id"])
    saved = candidate(client, [task_id])
    if mutation == "task_patch":
        client.patch(f"/api/tasks/{task_id}", json={"description": "Changed"})
    elif mutation == "task_create":
        create_task(client)
    elif mutation == "rule_patch":
        client.patch(f"/api/time-rules/{rule_id}", json={"active": False})
    else:
        client.post("/api/time-rules", json={**COURSE, "weekday": 4})
    before, before_counts = revision(test_engine), counts(test_engine)
    response = client.post(f"/api/plans/{saved['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
    assert revision(test_engine) == before and counts(test_engine) == before_counts
    assert client.get(f"/api/plans/{saved['id']}").json() == saved
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == official


def test_get_and_missing_plan_errors_do_not_bump(client, test_engine):
    task_id = create_task(client)
    saved = candidate(client, [task_id])
    for method, path in (
        (client.get, "/api/plans/999"), (client.post, "/api/plans/999/confirm"),
        (client.get, f"/api/plans/confirmed?week_start={WEEK}"),
    ):
        response = method(path)
        assert response.status_code == 404 and response.json()["detail"]["code"] == "PLAN_NOT_FOUND"
    assert client.get("/api/plans/confirmed?week_start=2026-10-06").status_code == 422
    assert client.get("/api/plans/confirmed?week_start=invalid").status_code == 422
    assert client.get("/api/plans/confirmed").status_code == 422
    assert client.get(f"/api/plans/{saved['id']}").json() == saved
    assert revision(test_engine) == 1


@pytest.mark.parametrize("failure", [SQLAlchemyError, RuntimeError])
def test_confirm_failure_rolls_back_both_statuses_timestamp_and_revision(
    client, test_engine, monkeypatch, failure,
):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    saved = candidate(client, [task_id])
    before = revision(test_engine)
    original_bump = plans.bump_revision

    def fail_after_all_writes(session):
        original_bump(session)
        session.flush()
        assert session.get(Plan, official["id"]).status == PlanStatus.superseded
        assert session.get(Plan, saved["id"]).status == PlanStatus.confirmed
        assert session.get(PlanningState, 1).revision == before + 1
        raise failure("injected after both plan updates and revision SQL writes")

    monkeypatch.setattr(plans, "bump_revision", fail_after_all_writes)
    with Session(test_engine, autoflush=False) as session:
        with pytest.raises(failure):
            plans.confirm_candidate(saved["id"], db=session)
        assert not session.in_transaction()
        assert session.get(Plan, official["id"]).status == PlanStatus.confirmed
        assert session.get(Plan, saved["id"]).status == PlanStatus.candidate
        assert session.get(Plan, saved["id"]).confirmed_at is None
        assert session.get(PlanningState, 1).revision == before
    assert client.get(f"/api/plans/{saved['id']}").json() == saved
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json() == official


def test_candidate_commit_failure_rolls_back_plan_items_and_preserves_revision(client, test_engine, monkeypatch):
    task_id = create_task(client)
    with Session(test_engine, autoflush=False) as session:
        def fail_commit():
            # Both tables have actually been flushed before the commit fails.
            assert session.scalar(select(func.count()).select_from(Plan)) == 1
            assert session.scalar(select(func.count()).select_from(PlanItem)) == 1
            raise SQLAlchemyError("injected candidate commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(SQLAlchemyError):
            plans.create_candidate(CandidateCreate(week_start=WEEK, task_ids=[task_id]), db=session)
        assert not session.in_transaction()
        assert session.scalar(select(func.count()).select_from(Plan)) == 0
        assert session.scalar(select(func.count()).select_from(PlanItem)) == 0
        assert session.get(PlanningState, 1).revision == 1


def test_partial_unique_index_blocks_direct_second_confirmed_and_session_recovers(client, test_engine):
    task_id = create_task(client)
    official = confirm(client, candidate(client, [task_id])["id"])
    saved = candidate(client, [task_id])
    with Session(test_engine) as session:
        session.get(Plan, saved["id"]).status = PlanStatus.confirmed
        with pytest.raises(IntegrityError, match="UNIQUE"):
            session.commit()
        session.rollback()
        assert session.get(Plan, saved["id"]).status == PlanStatus.candidate
        assert session.get(Plan, official["id"]).status == PlanStatus.confirmed
        assert session.get(PlanningState, 1).revision == 2
        # After rollback, the same Session can successfully write again.
        session.rollback()  # End verification reads before the next fresh write transaction.
        result = plans.confirm_candidate(saved["id"], db=session)
        assert result.status == PlanStatus.confirmed


@pytest.mark.parametrize("kind,has_task,has_rule", [
    ("task", False, False), ("task", True, True), ("course", True, True),
    ("course", False, False), ("protected", False, True),
])
def test_plan_item_database_reference_and_kind_constraints(client, test_engine, kind, has_task, has_rule):
    selected = create_task(client)
    rule = client.post("/api/time-rules", json={**COURSE, "active": False})
    assert rule.status_code == 201
    saved = candidate(client, [selected])
    with Session(test_engine) as session:
        session.add(PlanItem(
            plan_id=saved["id"], kind=kind, task_id=selected if has_task else None,
            time_rule_id=rule.json()["id"] if has_rule else None,
            title_snapshot="Invalid", start_at=datetime(2026, 10, 5, 3, tzinfo=timezone.utc),
            end_at=datetime(2026, 10, 5, 4, tzinfo=timezone.utc),
        ))
        with pytest.raises(IntegrityError, match="CHECK constraint failed"):
            session.commit()
        session.rollback()
        assert session.scalar(select(func.count()).select_from(PlanItem)) == 1


def test_get_item_sorting_by_start_kind_and_id_and_requested_ids_preserved(client, test_engine):
    later = create_task(client, title="Later", deadline="2026-10-06T18:00:00+08:00")
    earlier = create_task(client, title="Earlier")
    rule_ids = []
    for weekday in (3, 4):
        rule = client.post("/api/time-rules", json={**COURSE, "weekday": weekday, "active": False})
        assert rule.status_code == 201
        rule_ids.append(rule.json()["id"])
    saved = candidate(client, [later, earlier])
    assert saved["task_ids"] == [later, earlier]
    assert [item["task_id"] for item in saved["items"]] == [earlier, later]
    # Direct fixture inserts create ties that a valid scheduler never produces.
    with Session(test_engine) as session:
        instant = datetime(2026, 10, 5, 3, tzinfo=timezone.utc)
        for kind, task_id, rule_id, title in (
            (PlanItemKind.task, later, None, "Tie task"),
            (PlanItemKind.course, None, rule_ids[0], "Tie course first"),
            (PlanItemKind.course, None, rule_ids[1], "Tie course second"),
        ):
            session.add(PlanItem(
                plan_id=saved["id"], kind=kind, task_id=task_id, time_rule_id=rule_id,
                title_snapshot=title, start_at=instant, end_at=datetime(2026, 10, 5, 4, tzinfo=timezone.utc),
            ))
        session.commit()
    items = client.get(f"/api/plans/{saved['id']}").json()["items"]
    assert [item["title_snapshot"] for item in items[2:]] == ["Tie course first", "Tie course second", "Tie task"]
    assert items == sorted(items, key=lambda item: (item["start_at"], item["kind"], item["id"]))


def test_concurrent_confirm_serializes_revision_check(client, test_engine):
    task_id = create_task(client)
    left, right = candidate(client, [task_id]), candidate(client, [task_id])
    barrier = Barrier(2)

    def run(plan_id):
        with Session(test_engine, autoflush=False) as session:
            barrier.wait(timeout=5)
            try:
                return plans.confirm_candidate(plan_id, db=session).id
            except HTTPException as error:
                assert error.status_code == 409 and error.detail["code"] == "STALE_CANDIDATE"
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [left["id"], right["id"]]))
    assert sum(result is not None for result in results) == 1
    assert revision(test_engine) == 2
    assert client.get(f"/api/plans/confirmed?week_start={WEEK}").json()["id"] in results


def test_candidate_snapshot_blocks_concurrent_mutation_until_saved(client, test_engine, monkeypatch):
    task_id = create_task(client)
    scheduler_entered, release_scheduler, mutation_started, mutation_done = Event(), Event(), Event(), Event()
    original_schedule = plans.schedule_week

    def pause_schedule(*args):
        scheduler_entered.set()
        assert release_scheduler.wait(timeout=5)
        return original_schedule(*args)

    def mutate():
        mutation_started.set()
        response = client.patch(f"/api/tasks/{task_id}", json={"title": "Concurrent change"})
        mutation_done.set()
        assert response.status_code == 200

    monkeypatch.setattr(plans, "schedule_week", pause_schedule)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_candidate = pool.submit(candidate, client, [task_id])
        assert scheduler_entered.wait(timeout=5)
        future_mutation = pool.submit(mutate)
        try:
            assert mutation_started.wait(timeout=5)
            assert not mutation_done.wait(timeout=0.1)
        finally:
            release_scheduler.set()
        saved = future_candidate.result(timeout=5)
        future_mutation.result(timeout=5)
    assert saved["source_revision"] == 1 and saved["items"][0]["title_snapshot"] == "Finish report"
    assert revision(test_engine) == 2
    response = client.post(f"/api/plans/{saved['id']}/confirm")
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_CANDIDATE"
