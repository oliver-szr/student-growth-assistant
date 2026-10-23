"""User-owned long-term and stage goal management."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthGoal, GrowthGoalRevision, GrowthUserProfile, GrowthProfileRevision, PlanningState, utc_now
from ..schemas import GrowthGoalCreate, GrowthGoalPatch, GrowthGoalResponse, GrowthGoalsResponse, GrowthDirectionUpdate
from ..services.planning_state import bump_revision, planning_transaction
from ..services.growth_profile import record_profile_revision

router = APIRouter(prefix="/api/goals", tags=["Growth Goals"])


def _snapshot(goal: GrowthGoal) -> dict:
    return {
        "title": goal.title,
        "motivation": goal.motivation,
        "goal_type": goal.goal_type,
        "priority": goal.priority,
        "metric_kind": goal.metric_kind,
        "weekly_target": goal.weekly_target,
        "unit_label": goal.unit_label,
        "due_date": goal.due_date.isoformat() if goal.due_date else None,
        "status": goal.status,
    }


@router.get("", response_model=GrowthGoalsResponse)
def list_goals(db: Session = Depends(get_db)) -> GrowthGoalsResponse:
    profile = db.get(GrowthUserProfile, 1)
    state = db.get(PlanningState, 1)
    goals = list(db.scalars(select(GrowthGoal).order_by(GrowthGoal.priority, GrowthGoal.id)).all())
    return GrowthGoalsResponse(
        direction=profile.direction if profile else "",
        direction_version=profile.version if profile else 1,
        revision=state.revision if state else 0,
        goals=[GrowthGoalResponse.model_validate(goal) for goal in goals],
    )


@router.put("/direction")
def update_direction(payload: GrowthDirectionUpdate, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        profile = db.get(GrowthUserProfile, 1)
        if profile is None:
            profile = GrowthUserProfile(id=1, direction=payload.direction, version=1)
            db.add(profile)
        else:
            profile.direction = payload.direction
            profile.updated_at = max(utc_now(), profile.updated_at + timedelta(microseconds=1))
        profile, _ = record_profile_revision(db)
        revision = bump_revision(db)
        result = {"direction": profile.direction, "version": profile.version, "revision": revision}
    return result


@router.post("", response_model=GrowthGoalResponse, status_code=201)
def create_goal(payload: GrowthGoalCreate, db: Session = Depends(get_db)) -> GrowthGoalResponse:
    with planning_transaction(db):
        goal = GrowthGoal(**payload.model_dump())
        db.add(goal)
        db.flush()
        db.add(GrowthGoalRevision(goal_id=goal.id, version=goal.version, snapshot=_snapshot(goal)))
        bump_revision(db)
        response = GrowthGoalResponse.model_validate(goal)
    return response


@router.patch("/{goal_id}", response_model=GrowthGoalResponse)
def update_goal(goal_id: int, payload: GrowthGoalPatch, db: Session = Depends(get_db)) -> GrowthGoalResponse:
    with planning_transaction(db):
        goal = db.get(GrowthGoal, goal_id)
        if goal is None:
            raise HTTPException(status_code=404, detail="Goal not found")
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(goal, key, value)
        if changes:
            goal.version += 1
            goal.updated_at = max(utc_now(), goal.updated_at + timedelta(microseconds=1))
            db.add(GrowthGoalRevision(goal_id=goal.id, version=goal.version, snapshot=_snapshot(goal)))
            bump_revision(db)
        db.flush()
        response = GrowthGoalResponse.model_validate(goal)
    return response


@router.get("/{goal_id}/history")
def goal_history(goal_id: int, db: Session = Depends(get_db)) -> list[dict]:
    if db.get(GrowthGoal, goal_id) is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    rows = db.scalars(
        select(GrowthGoalRevision)
        .where(GrowthGoalRevision.goal_id == goal_id)
        .order_by(GrowthGoalRevision.version)
    ).all()
    return [
        {"version": row.version, "changed_at": row.changed_at.isoformat(), **row.snapshot}
        for row in rows
    ]
