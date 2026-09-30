"""Task CRUD routes."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Task, TaskStatus, utc_now
from ..schemas import TaskCreate, TaskResponse, TaskUpdate
from ..services.planning_state import begin_planning_transaction, bump_revision


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
    try:
        begin_planning_transaction(db)
        db.add(task)
        bump_revision(db)
        db.flush()
        db.refresh(task)
        response = TaskResponse.model_validate(task)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> TaskResponse:
    try:
        begin_planning_transaction(db)
        task = db.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")

        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            setattr(task, field, value)
        task.updated_at = max(utc_now(), task.updated_at + timedelta(microseconds=1))
        # Every successful PATCH, including {} or unchanged values, bumps once.
        bump_revision(db)
        db.flush()
        db.refresh(task)
        response = TaskResponse.model_validate(task)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return response
