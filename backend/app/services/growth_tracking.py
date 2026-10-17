"""Execution feedback and optional timer helpers shared by all task flows."""

from datetime import timedelta
from math import ceil

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import (
    GrowthGoal, Task, TaskFeedback, TaskGrowthContext, TaskStatus,
    TaskSchedulingProfile, TaskWorkSession, TaskCategory, utc_now,
)
from . import assistant_clock
from .taxonomy import validate_category


def ensure_task_context(db: Session, task: Task) -> TaskGrowthContext:
    context = db.get(TaskGrowthContext, task.id)
    if context is None:
        context = TaskGrowthContext(
            task_id=task.id,
            initial_estimate_minutes=task.duration_minutes,
            family="",
            family_confirmed=False,
            deadline_source="external",
        )
        db.add(context)
        db.flush()
    return context


def _active_actual_minutes(db: Session, task_id: int) -> int:
    value = db.scalar(
        select(func.coalesce(func.sum(TaskFeedback.actual_minutes), 0)).where(
            TaskFeedback.task_id == task_id,
            TaskFeedback.retracted_at.is_(None),
            TaskFeedback.actual_minutes.is_not(None),
        )
    )
    return int(value or 0)


def goal_progress_from_feedback(goals, effort_rows, completed_rows):
    """Shared existing goal semantics: minutes, or distinct completed task IDs.

    Callers retain their own missing-time coverage; a known subtotal is not an
    assertion that unrecorded effort was zero. This never updates a Goal.
    """
    progress = []
    for goal in goals:
        related = [row for row in effort_rows if row.goal_id_snapshot == goal.id]
        actual = (sum(row.actual_minutes or 0 for row in related) if goal.metric_kind == "time" else
                  len({row.task_id for row in completed_rows if row.goal_id_snapshot == goal.id}))
        progress.append({"goal_id": goal.id, "goal_title": goal.title, "metric_kind": goal.metric_kind,
                         "target": goal.weekly_target, "unit_label": goal.unit_label, "actual": actual,
                         "remaining": max(0, goal.weekly_target-actual), "status": goal.status})
    return progress


def valid_execution_feedback(row):
    """Effective, well-formed execution facts, including legitimate legacy zero."""
    return (row.retracted_at is None and row.outcome in ("completed", "partial", "postponed") and
            (row.actual_minutes is None or (type(row.actual_minutes) is int and 0 <= row.actual_minutes <= 1440)) and
            (row.outcome != "partial" or (type(row.remaining_minutes) is int and row.remaining_minutes > 0 and row.remaining_minutes % 5 == 0)))


def feedback_completion_time(row):
    return row.completed_at or row.occurred_at


def unique_completed_feedback(rows, as_of):
    """Latest effective completed fact per stable task ID, never current status."""
    latest = {}
    for row in sorted(rows, key=lambda item: (feedback_completion_time(item), item.id)):
        if row.outcome == "completed" and feedback_completion_time(row) <= as_of:
            latest[row.task_id] = row
    return list(latest.values())


def _learning_eligible(outcome: str, actual: int | None, context: TaskGrowthContext) -> bool:
    return outcome == "completed" and actual is not None and actual > 0 and context.family_confirmed and bool(context.family.strip())


def feedback_payload(db: Session, task: Task, feedback: TaskFeedback, context=None, total=None) -> dict:
    context = context if context is not None else ensure_task_context(db, task)
    total = _active_actual_minutes(db, task.id) if total is None else total
    return {
        "id": feedback.id,
        "task_id": task.id,
        "outcome": feedback.outcome,
        "actual_minutes": feedback.actual_minutes,
        "cumulative_actual_minutes": total,
        "remaining_minutes": task.duration_minutes if feedback.outcome == "partial" else None,
        "initial_estimate_minutes": feedback.initial_estimate_minutes,
        "task_status": task.status.value,
        "eligible_for_learning": _learning_eligible(feedback.outcome, total, context),
        "family": feedback.family_snapshot,
        "category_name": feedback.category_name_snapshot,
        "created_at": feedback.created_at,
    }


def record_feedback(db: Session, task: Task, payload) -> tuple[TaskFeedback, bool]:
    """Append one idempotent feedback record. The caller owns transaction/commit."""
    from .task_hierarchy import require_executable
    require_executable(task)
    existing = db.scalar(
        select(TaskFeedback).where(
            TaskFeedback.task_id == task.id,
            TaskFeedback.client_action_id == payload.client_action_id,
        )
    )
    if existing is not None:
        return existing, False

    context = ensure_task_context(db, task)
    previous = None
    if payload.corrects_feedback_id is not None:
        previous = db.get(TaskFeedback, payload.corrects_feedback_id)
        if previous is None or previous.task_id != task.id or previous.retracted_at is not None:
            raise HTTPException(status_code=409, detail="反馈记录已变化，无法更正")
        previous.retracted_at = utc_now()
    elif task.status == TaskStatus.done:
        raise HTTPException(status_code=409, detail="已完成任务需要通过更正原完成记录来修改")

    if payload.family is not None:
        category = validate_category(db, payload.family)
        context.family = payload.family
        context.family_confirmed = bool(payload.family)
        profile = db.get(TaskSchedulingProfile, task.id)
        if profile is None:
            profile = TaskSchedulingProfile(task_id=task.id, settings={})
            db.add(profile)
        profile.settings = {**(profile.settings or {}), "task_type": payload.family}
    if payload.goal_id is not None:
        goal = db.get(GrowthGoal, payload.goal_id)
        if goal is None:
            raise HTTPException(status_code=422, detail="目标不存在")
        context.goal_id = goal.id
    context.updated_at = utc_now()

    goal = db.get(GrowthGoal, context.goal_id) if context.goal_id else None
    occurred_at = payload.occurred_at or assistant_clock.assistant_now()
    feedback = TaskFeedback(
        task_id=task.id,
        client_action_id=payload.client_action_id,
        outcome=payload.outcome,
        actual_minutes=payload.actual_minutes,
        remaining_minutes=payload.remaining_minutes,
        title_snapshot=task.title,
        deadline_snapshot=task.deadline,
        priority_snapshot=task.priority.value,
        difficulty=payload.difficulty,
        reason=payload.reason,
        family_snapshot=context.family,
        category_name_snapshot=(db.get(TaskCategory, context.family).name if context.family and db.get(TaskCategory, context.family) else context.family or "未分类"),
        family_confirmed_snapshot=context.family_confirmed,
        initial_estimate_minutes=context.initial_estimate_minutes,
        goal_id_snapshot=goal.id if goal else None,
        goal_title_snapshot=goal.title if goal else None,
        completed_at=(payload.completed_at or occurred_at) if payload.outcome == "completed" else None,
        occurred_at=occurred_at,
        supersedes_id=payload.corrects_feedback_id,
        created_at=utc_now(),
    )
    db.add(feedback)

    if payload.outcome == "completed":
        task.status = TaskStatus.done
    else:
        task.status = TaskStatus.todo
        if payload.outcome == "partial":
            task.duration_minutes = payload.remaining_minutes
    task.updated_at = max(utc_now(), task.updated_at + timedelta(microseconds=1))
    db.flush()
    return feedback, True


def record_unknown_completion(db: Session, task: Task) -> TaskFeedback:
    """Preserve status-only completion without inventing an actual duration."""
    from .task_hierarchy import require_executable
    require_executable(task)
    context = ensure_task_context(db, task)
    goal = db.get(GrowthGoal, context.goal_id) if context.goal_id else None
    category = db.get(TaskCategory, context.family) if context.family else None
    feedback = TaskFeedback(
        task_id=task.id,
        client_action_id=f"legacy-status-{task.id}-{utc_now().timestamp()}",
        outcome="completed",
        actual_minutes=None,
        title_snapshot=task.title,
        deadline_snapshot=task.deadline,
        priority_snapshot=task.priority.value,
        family_snapshot=context.family,
        category_name_snapshot=category.name if category else context.family or "未分类",
        family_confirmed_snapshot=context.family_confirmed,
        initial_estimate_minutes=context.initial_estimate_minutes,
        goal_id_snapshot=goal.id if goal else None,
        goal_title_snapshot=goal.title if goal else None,
        completed_at=utc_now(),
    )
    db.add(feedback)
    db.flush()
    return feedback


def retract_latest_completion(db: Session, task_id: int) -> None:
    latest = db.scalar(
        select(TaskFeedback)
        .where(TaskFeedback.task_id == task_id, TaskFeedback.outcome == "completed", TaskFeedback.retracted_at.is_(None))
        .order_by(TaskFeedback.id.desc())
        .limit(1)
    )
    if latest is not None:
        latest.retracted_at = utc_now()


def session_payload(session: TaskWorkSession) -> dict:
    now = utc_now()
    seconds = session.accumulated_seconds
    if session.status == "running" and session.segment_started_at is not None:
        seconds += max(0, int((now - session.segment_started_at).total_seconds()))
    return {
        "id": session.id,
        "task_id": session.task_id,
        "status": session.status,
        "family": session.family_snapshot,
        "category_name": session.category_name_snapshot,
        "family_confirmed": session.family_confirmed_snapshot,
        "elapsed_seconds": seconds,
        "accumulated_seconds": session.accumulated_seconds,
        "segment_started_at": session.segment_started_at,
        "suggested_minutes": max(1, ceil(seconds / 60)) if seconds else 0,
        "confirmed_for_learning": False,
        "started_at": session.started_at,
        "updated_at": session.updated_at,
    }


def pause_work_session(session: TaskWorkSession) -> None:
    if session.status != "running" or session.segment_started_at is None:
        raise HTTPException(status_code=409, detail="计时器当前未运行")
    now = utc_now()
    session.accumulated_seconds += max(0, int((now - session.segment_started_at).total_seconds()))
    session.segment_started_at = None
    session.status = "paused"
    session.updated_at = now


def resume_work_session(session: TaskWorkSession) -> None:
    if session.status != "paused":
        raise HTTPException(status_code=409, detail="只有已暂停的计时器可以继续")
    session.status = "running"
    session.segment_started_at = utc_now()
    session.updated_at = session.segment_started_at


def stop_work_session(session: TaskWorkSession) -> None:
    if session.status == "running":
        now = utc_now()
        if session.segment_started_at is not None:
            session.accumulated_seconds += max(0, int((now - session.segment_started_at).total_seconds()))
        session.segment_started_at = None
        session.status = "stopped"
        session.updated_at = now
    elif session.status == "paused":
        session.status = "stopped"
        session.updated_at = utc_now()
    else:
        raise HTTPException(status_code=409, detail="计时器已经结束")
