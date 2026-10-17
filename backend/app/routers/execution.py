"""Task execution feedback and optional persisted work timers."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthGoal, Task, TaskFeedback, TaskGrowthContext, TaskSchedulingProfile, TaskWorkSession, TaskCategory, utc_now
from ..schemas import TaskFeedbackCreate, TaskGrowthContextUpdate, WorkSessionStart
from ..services.growth_tracking import (
    ensure_task_context, feedback_payload, pause_work_session, record_feedback, resume_work_session,
    session_payload, stop_work_session, _active_actual_minutes,
)
from ..services.growth_insights import automatic_analysis_is_due, launch_automatic_analysis
from ..services.planning_state import bump_revision, planning_transaction
from ..services.taxonomy import resolve_user_category
from ..services.growth_profile import record_profile_revision

router = APIRouter(tags=["Task Execution"])


@router.post("/api/tasks/{task_id}/feedback", status_code=201)
def save_task_feedback(task_id: int, payload: TaskFeedbackCreate, response: Response, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        existing = db.scalar(select(TaskFeedback).where(TaskFeedback.task_id == task.id, TaskFeedback.client_action_id == payload.client_action_id))
        effective_payload = payload
        if payload.family is not None and existing is None:
            category, added = resolve_user_category(db, payload.family)
            effective_payload = payload.model_copy(update={"family": category.key})
            if added:
                record_profile_revision(db)
        feedback, created = record_feedback(db, task, effective_payload)
        if not created:
            response.status_code = 200
        if created:
            bump_revision(db)
        result = feedback_payload(db, task, feedback)
    if created and result["eligible_for_learning"] and automatic_analysis_is_due(db):
        launch_automatic_analysis(db.get_bind())
    return result


@router.put("/api/tasks/{task_id}/growth-context")
def update_task_growth_context(task_id: int, payload: TaskGrowthContextUpdate, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if payload.goal_id is not None and db.get(GrowthGoal, payload.goal_id) is None:
            raise HTTPException(status_code=422, detail="目标不存在")
        category, added = resolve_user_category(db, payload.family)
        context = ensure_task_context(db, task)
        if "goal_id" in payload.model_fields_set:
            context.goal_id = payload.goal_id
        context.family = category.key
        context.family_confirmed = True
        context.deadline_source = payload.deadline_source
        context.updated_at = utc_now()
        profile = db.get(TaskSchedulingProfile, task.id)
        if profile is None:
            profile = TaskSchedulingProfile(task_id=task.id, settings={})
            db.add(profile)
        profile.settings = {**(profile.settings or {}), "task_type": category.key}
        if added:
            record_profile_revision(db)
        bump_revision(db)
        result = {
            "task_id": task.id,
            "goal_id": context.goal_id,
            "family": context.family,
            "family_confirmed": context.family_confirmed,
            "initial_estimate_minutes": context.initial_estimate_minutes,
            "deadline_source": context.deadline_source,
        }
    return result


@router.get("/api/tasks/{task_id}/growth-context")
def get_task_growth_context(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    context = db.get(TaskGrowthContext, task_id)
    category = db.get(TaskCategory, context.family) if context and context.family else None
    return {
        "task_id": task_id,
        "goal_id": context.goal_id if context else None,
        "family": context.family if context else "",
        "family_name": category.name if category else (context.family if context else "未分类"),
        "family_confirmed": context.family_confirmed if context else False,
        "initial_estimate_minutes": context.initial_estimate_minutes if context else task.duration_minutes,
        "deadline_source": context.deadline_source if context else "external",
    }


@router.get("/api/tasks/{task_id}/feedback")
def list_task_feedback(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    rows = db.scalars(
        select(TaskFeedback).where(TaskFeedback.task_id == task_id).order_by(TaskFeedback.created_at, TaskFeedback.id)
    ).all()
    context = ensure_task_context(db, task)
    total = _active_actual_minutes(db, task.id)
    return {
        "task_id": task_id,
        "entries": [
            {
                **feedback_payload(db, task, row, context, total),
                "reason": row.reason,
                "difficulty": row.difficulty,
                "family_confirmed": row.family_confirmed_snapshot,
                "superseded": row.retracted_at is not None,
                "supersedes_id": row.supersedes_id,
            }
            for row in rows
        ],
    }


@router.post("/api/work-sessions/start", status_code=201)
def start_work_session(payload: WorkSessionStart, db: Session = Depends(get_db)) -> dict:
    try:
        with planning_transaction(db):
            task = db.get(Task, payload.task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            from ..services.task_hierarchy import require_executable
            require_executable(task)
            if task.status.value != "todo":
                raise HTTPException(status_code=409, detail="只有待完成任务可以开始计时")
            existing = db.scalar(
                select(TaskWorkSession).where(
                    TaskWorkSession.task_id == payload.task_id,
                    TaskWorkSession.client_action_id == payload.client_action_id,
                )
            )
            if existing is not None:
                result = session_payload(existing)
            else:
                context = ensure_task_context(db, task)
                session = TaskWorkSession(
                    task_id=task.id,
                    client_action_id=payload.client_action_id,
                    status="running",
                    family_snapshot=context.family,
                    category_name_snapshot=(db.get(TaskCategory, context.family).name if context.family and db.get(TaskCategory, context.family) else context.family or "未分类"),
                    family_confirmed_snapshot=context.family_confirmed,
                    accumulated_seconds=0,
                    segment_started_at=utc_now(),
                )
                db.add(session)
                db.flush()
                result = session_payload(session)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="已有一个计时任务正在运行")
    return result


@router.get("/api/tasks/{task_id}/work-sessions/current")
def current_work_session(task_id: int, db: Session = Depends(get_db)) -> dict:
    if db.get(Task, task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    session = db.scalar(
        select(TaskWorkSession)
        .where(TaskWorkSession.task_id == task_id, TaskWorkSession.status.in_(["running", "paused"]))
        .order_by(TaskWorkSession.id.desc())
        .limit(1)
    )
    return {"session": session_payload(session) if session else None}


def _change_session(session_id: int, operation: str, db: Session) -> dict:
    try:
        with planning_transaction(db):
            session = db.get(TaskWorkSession, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="计时记录不存在")
            if operation == "pause":
                pause_work_session(session)
            elif operation == "resume":
                resume_work_session(session)
            else:
                stop_work_session(session)
            result = session_payload(session)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="另一个计时任务正在运行")
    return result


@router.post("/api/work-sessions/{session_id}/pause")
def pause_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    return _change_session(session_id, "pause", db)


@router.post("/api/work-sessions/{session_id}/resume")
def resume_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    return _change_session(session_id, "resume", db)


@router.post("/api/work-sessions/{session_id}/finish")
def finish_session(session_id: int, db: Session = Depends(get_db)) -> dict:
    return _change_session(session_id, "finish", db)
