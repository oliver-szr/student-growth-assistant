"""TimeRule CRUD routes."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TimeRule, utc_now
from ..schemas import TimeRuleCreate, TimeRuleResponse, TimeRuleUpdate


router = APIRouter(prefix="/api/time-rules", tags=["Time Rules"])


@router.get("", response_model=list[TimeRuleResponse])
def list_time_rules(db: Session = Depends(get_db)) -> list[TimeRule]:
    return list(db.scalars(select(TimeRule).order_by(TimeRule.id)).all())


@router.post("", response_model=TimeRuleResponse, status_code=201)
def create_time_rule(payload: TimeRuleCreate, db: Session = Depends(get_db)) -> TimeRule:
    rule = TimeRule(**payload.model_dump())
    try:
        db.add(rule)
        db.commit()
        db.refresh(rule)
    except SQLAlchemyError:
        db.rollback()
        raise
    return rule


@router.patch("/{rule_id}", response_model=TimeRuleResponse)
def update_time_rule(
    rule_id: int, payload: TimeRuleUpdate, db: Session = Depends(get_db)
) -> TimeRule:
    rule = db.get(TimeRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="TimeRule not found")

    changes = payload.model_dump(exclude_unset=True)
    final_values = {field: getattr(rule, field) for field in TimeRuleCreate.model_fields}
    final_values.update(changes)
    try:
        validated = TimeRuleCreate.model_validate(final_values)
    except ValidationError as error:
        detail = [
            {"loc": ["body", *item["loc"]], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        raise HTTPException(status_code=422, detail=detail) from error

    for field in changes:
        setattr(rule, field, getattr(validated, field))
    rule.updated_at = max(utc_now(), rule.updated_at + timedelta(microseconds=1))

    try:
        db.commit()
        db.refresh(rule)
    except SQLAlchemyError:
        db.rollback()
        raise
    return rule
