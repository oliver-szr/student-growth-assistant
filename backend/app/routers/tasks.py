"""Task CRUD routes."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Task, TaskGrowthContext, TaskStatus, utc_now
from ..schemas import TaskCreate, TaskResponse, TaskUpdate
from ..services.growth_tracking import ensure_task_context, record_unknown_completion, retract_latest_completion
from ..services.planning_state import bump_revision, planning_transaction


router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


@router.get("", response_model=list[TaskResponse])
def list_tasks(status: TaskStatus | None = None, db: Session = Depends(get_db)) -> list[Task]:
    query = select(Task).order_by(Task.id)
    if status is not None:
        query = query.where(Task.status == status)
    return list(db.scalars(query).all())


@router.post("", response_model=TaskResponse, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> TaskResponse:
    task = Task(**payload.model_dump())
    with planning_transaction(db):
        db.add(task)
        bump_revision(db)
        db.flush()
        db.add(TaskGrowthContext(
            task_id=task.id,
            initial_estimate_minutes=task.duration_minutes,
            family="",
            family_confirmed=False,
            deadline_source="external",
        ))
        db.refresh(task)
        response = TaskResponse.model_validate(task)
    return response


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> TaskResponse:
    with planning_transaction(db):
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        changes = payload.model_dump(exclude_unset=True)
        previous_status = task.status
        ensure_task_context(db, task)
        for field, value in changes.items():
            setattr(task, field, value)
        if previous_status != TaskStatus.done and task.status == TaskStatus.done:
            record_unknown_completion(db, task)
        elif previous_status == TaskStatus.done and task.status in (TaskStatus.todo, TaskStatus.cancelled):
            retract_latest_completion(db, task.id)
        task.updated_at = max(utc_now(), task.updated_at + timedelta(microseconds=1))
        # Every successful PATCH, including {} or unchanged values, bumps once.
        bump_revision(db)
        db.flush()
        db.refresh(task)
        response = TaskResponse.model_validate(task)
    return response
