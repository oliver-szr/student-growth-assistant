"""User-managed task categories and independently editable preference rules."""

from typing import Literal
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PreferenceRule, TaskCategory
from ..services.growth_profile import record_profile_revision
from ..services.planning_state import bump_revision, planning_transaction
from ..services.taxonomy import (
    categories_payload, create_category, rule_payload, rules_payload,
    update_category, validate_rule,
)

categories_router = APIRouter(prefix="/api/task-categories", tags=["Task Categories"])
preferences_router = APIRouter(prefix="/api/assistant/preference-rules", tags=["Preference Rules"])
settings_router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)


class CategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None


class PreferenceRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    kind: Literal["prefer_time", "avoid_time", "deadline_buffer", "adjustment_mode", "ai_note"]
    category_key: str | None = Field(default=None, max_length=80)
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    parameters: dict


class PreferenceRulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    kind: Literal["prefer_time", "avoid_time", "deadline_buffer", "adjustment_mode", "ai_note"] | None = None
    category_key: str | None = Field(default=None, max_length=80)
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)
    parameters: dict | None = None
    enabled: bool | None = None


@categories_router.get("")
def list_categories(active: bool | None = None, db: Session = Depends(get_db)):
    return {"categories": categories_payload(db, active)}


@categories_router.post("", status_code=201)
def add_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    with planning_transaction(db):
        row = create_category(db, payload.name)
        record_profile_revision(db)
        bump_revision(db)
        result = dict(key=row.key, name=row.name, active=row.active, is_default=row.is_default)
    return result


@categories_router.patch("/{key}")
def patch_category(key: str, payload: CategoryPatch, db: Session = Depends(get_db)):
    if payload.name is None and payload.active is None:
        from fastapi import HTTPException
        raise HTTPException(422, "请至少修改类别名称或状态。")
    with planning_transaction(db):
        row = update_category(db, key, **payload.model_dump(exclude_unset=True))
        record_profile_revision(db)
        bump_revision(db)
        result = dict(key=row.key, name=row.name, active=row.active, is_default=row.is_default)
    return result


@preferences_router.get("")
def list_preference_rules(db: Session = Depends(get_db)):
    return {"rules": rules_payload(db), "categories": categories_payload(db, True)}


@preferences_router.post("", status_code=201)
def add_preference_rule(payload: PreferenceRuleCreate, db: Session = Depends(get_db)):
    with planning_transaction(db):
        values = validate_rule(db, {**payload.model_dump(), "source": "user"})
        row = PreferenceRule(**values)
        db.add(row)
        db.flush()
        record_profile_revision(db)
        bump_revision(db)
        result = rule_payload(db, row)
    return result


@preferences_router.patch("/{rule_id}")
def patch_preference_rule(rule_id: int, payload: PreferenceRulePatch, db: Session = Depends(get_db)):
    changes = payload.model_dump(exclude_unset=True)
    with planning_transaction(db):
        row = db.get(PreferenceRule, rule_id)
        if row is None:
            from fastapi import HTTPException
            raise HTTPException(404, "偏好规则不存在。")
        values = validate_rule(db, {**{
            "name": row.name, "description": row.description, "enabled": row.enabled, "kind": row.kind,
            "category_key": row.category_key, "weekdays": row.weekdays, "parameters": row.parameters,
            "source": row.source,
        }, **changes}, own_id=rule_id)
        # Once the user edits or toggles a sample rule, its provenance becomes
        # an explicit user decision instead of remaining a demo default.
        if changes:
            values["source"] = "user"
        for key, value in values.items():
            setattr(row, key, value)
        if "enabled" in changes:
            row.enabled = bool(changes["enabled"])
        if changes:
            row.updated_at = datetime.now(timezone.utc)
        db.flush()
        record_profile_revision(db)
        bump_revision(db)
        result = rule_payload(db, row)
    return result
