"""Persist validated candidates and atomically confirm the stored plan."""

from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Plan, PlanItem, PlanItemKind, PlanStatus, Task, TaskStatus, TimeRule, utc_now
from ..schemas import CandidateCreate, CandidateResponse, PlanItemResponse, PlanResponse, monday_date
from ..services.planning_state import (
    begin_planning_transaction, bump_revision, get_or_create_planning_state,
)
from ..services.scheduler import schedule_week
from ..services.scheduling_types import SchedulingInputError, TaskInput, TimeRuleInput
from ..services.validator import expand_time_rules, validate_schedule


router = APIRouter(prefix="/api/plans", tags=["Plans"])


def plan_response(db: Session, plan: Plan) -> PlanResponse:
    """Read saved snapshots, without joining mutable Task or TimeRule titles."""
    items = db.scalars(
        select(PlanItem).where(PlanItem.plan_id == plan.id).order_by(
            PlanItem.start_at, PlanItem.kind, PlanItem.id
        )
    ).all()
    return PlanResponse(
        **{field: getattr(plan, field) for field in PlanResponse.model_fields if field != "items"},
        items=[PlanItemResponse.model_validate(item) for item in items],
    )


def confirmed_plan(db: Session, week_start: date) -> Plan | None:
    return db.scalar(select(Plan).where(
        Plan.week_start == week_start, Plan.status == PlanStatus.confirmed
    ))


def require_plan(db: Session, plan_id: int) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(404, detail={"code": "PLAN_NOT_FOUND", "message": "Plan not found."})
    return plan


@router.post("/candidates", response_model=CandidateResponse, responses={
    409: {"description": "UNSCHEDULABLE: the current heuristic did not produce a complete plan."},
    500: {"description": "GENERATED_SCHEDULE_INVALID: the generated schedule failed independent validation."},
})
def create_candidate(payload: CandidateCreate, db: Session = Depends(get_db)) -> CandidateResponse:
    try:
        begin_planning_transaction(db)
        state = get_or_create_planning_state(db)
        tasks = db.scalars(select(Task).where(Task.id.in_(payload.task_ids))).all()
        tasks_by_id = {task.id: task for task in tasks}
        missing = [task_id for task_id in payload.task_ids if task_id not in tasks_by_id]
        if missing:
            raise HTTPException(422, detail={
                "code": "TASK_NOT_FOUND", "message": "All selected tasks must exist.", "task_ids": missing,
            })
        not_todo = [task.id for task in tasks if task.status != TaskStatus.todo]
        if not_todo:
            raise HTTPException(422, detail={
                "code": "TASK_NOT_TODO", "message": "All selected tasks must be todo.", "task_ids": not_todo,
            })
        rules = db.scalars(select(TimeRule).order_by(TimeRule.id)).all()
        current = confirmed_plan(db, payload.week_start)
        task_inputs = [TaskInput(
            id=task.id, title=task.title, duration_minutes=task.duration_minutes,
            deadline=task.deadline, priority=task.priority.value, status=task.status.value,
        ) for task in (tasks_by_id[task_id] for task_id in payload.task_ids)]
        rule_inputs = [TimeRuleInput(
            id=rule.id, kind=rule.kind.value, title=rule.title, recurrence=rule.recurrence.value,
            start_time=rule.start_time, end_time=rule.end_time, weekday=rule.weekday,
            date=rule.date, active=rule.active,
        ) for rule in rules]
        result = schedule_week(payload.week_start, task_inputs, rule_inputs)
        if result.status == "unschedulable":
            raise HTTPException(409, detail={
                "code": "UNSCHEDULABLE",
                "message": "Could not generate a complete plan under the current scheduling heuristic.",
                "unscheduled_tasks": [asdict(task) for task in result.unscheduled_tasks],
            })
        validation = validate_schedule(payload.week_start, task_inputs, rule_inputs, result.assignments)
        if not validation.valid:
            raise HTTPException(500, detail={
                "code": "GENERATED_SCHEDULE_INVALID", "message": "Generated schedule failed validation.",
                "violations": [asdict(violation) for violation in validation.violations],
            })
        # Use Phase 4's expansion for courses; protected intervals are never persisted.
        intervals = expand_time_rules(payload.week_start, rule_inputs)
        plan = Plan(
            week_start=payload.week_start, status=PlanStatus.candidate,
            source_revision=state.revision, based_on_plan_id=current.id if current else None,
            task_ids=list(payload.task_ids),
        )
        db.add(plan)
        db.flush()
        db.add_all([PlanItem(
            plan_id=plan.id, kind=PlanItemKind.task, task_id=assignment.task_id,
            title_snapshot=tasks_by_id[assignment.task_id].title,
            start_at=assignment.start_at, end_at=assignment.end_at,
        ) for assignment in result.assignments])
        rules_by_id = {rule.id: rule for rule in rules}
        db.add_all([PlanItem(
            plan_id=plan.id, kind=PlanItemKind.course, time_rule_id=interval.time_rule_id,
            title_snapshot=rules_by_id[interval.time_rule_id].title,
            start_at=interval.start_at, end_at=interval.end_at,
        ) for interval in intervals if interval.kind == "course"])
        db.flush()
        response = CandidateResponse(candidate=plan_response(db, plan))
        db.commit()
        return response
    except SchedulingInputError as error:
        db.rollback()
        raise HTTPException(422, detail={"code": error.code, "message": str(error)}) from error
    except Exception:
        db.rollback()
        raise


# Static path must be registered before /{plan_id}.
@router.get("/confirmed", response_model=PlanResponse, responses={
    404: {"description": "PLAN_NOT_FOUND: no confirmed plan exists for this week."},
})
def get_confirmed_plan(
    week_start: date = Query(...), db: Session = Depends(get_db),
) -> PlanResponse:
    try:
        monday_date(week_start)
    except ValueError as error:
        raise HTTPException(422, detail={"code": "INVALID_WEEK", "message": str(error)}) from error
    plan = confirmed_plan(db, week_start)
    if plan is None:
        raise HTTPException(404, detail={"code": "PLAN_NOT_FOUND", "message": "No confirmed plan for this week."})
    return plan_response(db, plan)


@router.get("/{plan_id}", response_model=PlanResponse, responses={
    404: {"description": "PLAN_NOT_FOUND: the requested plan does not exist."},
})
def get_plan(plan_id: int, db: Session = Depends(get_db)) -> PlanResponse:
    return plan_response(db, require_plan(db, plan_id))


@router.post("/{plan_id}/confirm", response_model=PlanResponse, responses={
    404: {"description": "PLAN_NOT_FOUND: the requested plan does not exist."},
    409: {"description": "PLAN_NOT_CANDIDATE or STALE_CANDIDATE: the stored plan cannot be confirmed."},
})
def confirm_candidate(plan_id: int, db: Session = Depends(get_db)) -> PlanResponse:
    try:
        begin_planning_transaction(db)
        state = get_or_create_planning_state(db)
        plan = require_plan(db, plan_id)
        if plan.status != PlanStatus.candidate:
            raise HTTPException(409, detail={
                "code": "PLAN_NOT_CANDIDATE", "message": "Only a candidate plan can be confirmed.",
            })
        if plan.source_revision != state.revision:
            raise HTTPException(409, detail={
                "code": "STALE_CANDIDATE",
                "message": "The candidate plan was generated from an older planning state. Generate a new candidate before confirming.",
            })
        current = confirmed_plan(db, plan.week_start)
        if current is not None:
            current.status = PlanStatus.superseded
            # Release the unique-index entry before setting the new confirmed status.
            # This flush is still inside the same transaction and can be rolled back.
            db.flush()
        plan.status = PlanStatus.confirmed
        plan.confirmed_at = utc_now()
        bump_revision(db)
        db.flush()
        response = plan_response(db, plan)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
