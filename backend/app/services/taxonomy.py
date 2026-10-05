"""Stable task-category identities and the single preference-rule compiler."""

from datetime import datetime, time, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AssistantPreference, GrowthMigration, PreferenceRule, TaskCategory,
    TaskFeedback, TaskGrowthContext, TaskSchedulingProfile, TaskWorkSession,
    WorkspaceMetadata, utc_now,
)

DEFAULT_CATEGORIES = (
    ("writing", "写作"), ("reading", "阅读"), ("practice", "练习"), ("other", "其他"),
)
_KINDS = {"prefer_time", "avoid_time", "deadline_buffer", "adjustment_mode", "ai_note"}


def _default_name(key: str) -> str:
    return dict(DEFAULT_CATEGORIES).get(key, key)


def migrate_taxonomy(db: Session) -> None:
    """Backfill category labels/rules once, preserving existing stable task keys."""
    for key, name in DEFAULT_CATEGORIES:
        if db.get(TaskCategory, key) is None:
            db.add(TaskCategory(key=key, name=name, active=True, is_default=True))
    keys = set(db.scalars(select(TaskGrowthContext.family)).all())
    for profile in db.scalars(select(TaskSchedulingProfile)).all():
        value = (profile.settings or {}).get("task_type")
        if value:
            keys.add(value)
    for key in sorted(value.strip() for value in keys if isinstance(value, str) and value.strip()):
        if db.get(TaskCategory, key) is None:
            name = _default_name(key)
            if db.scalar(select(TaskCategory.key).where(TaskCategory.name == name)) is None:
                db.add(TaskCategory(key=key, name=name, active=True, is_default=False))
    db.flush()

    for table, column, snapshot_column in (
        (TaskFeedback, "family_snapshot", "category_name_snapshot"),
        (TaskWorkSession, "family_snapshot", "category_name_snapshot"),
    ):
        rows = db.scalars(select(table)).all()
        for row in rows:
            if not getattr(row, snapshot_column, ""):
                key = getattr(row, column, "")
                category = db.get(TaskCategory, key) if key else None
                setattr(row, snapshot_column, category.name if category else (key or "未分类"))

    if db.get(GrowthMigration, "growth_v4_taxonomy") is None:
        if not db.scalars(select(PreferenceRule.id)).first():
            old = db.get(AssistantPreference, 1)
            values = old.settings if old else {
                # Keep the first-run experience useful when upgrading a fresh
                # database: these are the same clearly-marked example defaults
                # previously shown by the preferences form.
                "task_windows": {
                    "writing": [{"start": "08:00", "end": "12:00"}],
                    "reading": [{"start": "19:00", "end": "22:00"}],
                },
                "avoid_windows": [],
                "deadline_buffer_hours": 24,
                "adjustment_mode": "balanced",
            }
            source = "sample" if old is None or old.is_sample else "user"
            for key, windows in (values.get("task_windows") or {}).items():
                category = db.get(TaskCategory, key)
                for index, window in enumerate(windows):
                    db.add(PreferenceRule(
                        name=f"{category.name if category else key}适合时段" + (f" {index + 1}" if index else ""),
                        description="尽量把这类任务安排在合适时段。", kind="prefer_time",
                        category_key=key, parameters=dict(window), source=source,
                    ))
            for index, window in enumerate(values.get("avoid_windows") or []):
                db.add(PreferenceRule(name="尽量避开" + (f" {index + 1}" if index else ""),
                    description="尽量避开这段时间。", kind="avoid_time", parameters=dict(window), source=source))
            buffer_hours = int(values.get("deadline_buffer_hours", 0) or 0)
            if buffer_hours:
                db.add(PreferenceRule(name="重要任务截止缓冲", description="重要任务尽量提前完成。",
                    kind="deadline_buffer", parameters={"hours": buffer_hours}, source=source))
            mode = values.get("adjustment_mode", "balanced")
            db.add(PreferenceRule(name="调整时的取舍", description="安排任务时采用的总体取舍。",
                kind="adjustment_mode", parameters={"mode": mode}, source=source))
        db.add(GrowthMigration(name="growth_v4_taxonomy", applied_at=utc_now()))
    if db.get(WorkspaceMetadata, 1) is None:
        db.add(WorkspaceMetadata(id=1, workspace_id=str(uuid4())))


def category_rows(db: Session, active: bool | None = None) -> list[TaskCategory]:
    query = select(TaskCategory).order_by(TaskCategory.is_default.desc(), TaskCategory.name.collate("NOCASE"))
    if active is not None:
        query = query.where(TaskCategory.active == active)
    return list(db.scalars(query).all())


def categories_payload(db: Session, active: bool | None = None) -> list[dict]:
    return [dict(key=row.key, name=row.name, active=row.active, is_default=row.is_default,
                 created_at=row.created_at.isoformat(), updated_at=row.updated_at.isoformat())
            for row in category_rows(db, active)]


def _validate_name(db: Session, name: str, own_key: str | None = None) -> str:
    clean = name.strip()
    if not clean or len(clean) > 80:
        raise HTTPException(422, "类别名称不能为空，且不能超过80个字。")
    for row in category_rows(db):
        if row.key != own_key and row.name.casefold() == clean.casefold():
            raise HTTPException(409, "已有同名类别，请使用不同名称。")
    return clean


def create_category(db: Session, name: str) -> TaskCategory:
    clean = _validate_name(db, name)
    row = TaskCategory(key=f"custom-{uuid4()}", name=clean, active=True, is_default=False)
    db.add(row)
    db.flush()
    return row


def update_category(db: Session, key: str, *, name: str | None = None, active: bool | None = None) -> TaskCategory:
    row = db.get(TaskCategory, key)
    if row is None:
        raise HTTPException(404, "任务类别不存在。")
    if name is not None:
        row.name = _validate_name(db, name, key)
    if active is not None:
        if row.key == "other" and not active:
            raise HTTPException(422, "“其他”是默认类别，不能停用。")
        row.active = active
    row.updated_at = max(utc_now(), row.updated_at + timedelta(microseconds=1))
    db.flush()
    return row


def validate_category(db: Session, key: str, *, allow_inactive: bool = False) -> TaskCategory:
    row = db.get(TaskCategory, key)
    if row is None or (not row.active and not allow_inactive):
        raise HTTPException(422, "请选择一个正在使用的任务类别。")
    return row


def resolve_user_category(db: Session, value: str) -> tuple[TaskCategory, bool]:
    """Resolve older clients' confirmed display labels to stable category keys.

    Legacy feedback/context endpoints accepted free-form labels. Preserve that
    behavior by reusing a matching display name or registering the explicitly
    supplied label as a custom category; planning/AI APIs still require a key.
    """
    clean = value.strip()
    if not clean:
        raise HTTPException(422, "任务类别不能为空。")
    row = db.get(TaskCategory, clean)
    if row is not None:
        if not row.active:
            raise HTTPException(422, "这个任务类别已停用，请先选择其他类别。")
        return row, False
    for category in category_rows(db):
        if category.name.casefold() == clean.casefold():
            if not category.active:
                raise HTTPException(422, "这个任务类别已停用，请先选择其他类别。")
            return category, False
    return create_category(db, clean), True


def _clock(value: str) -> bool:
    try:
        return len(value) == 5 and time.fromisoformat(value).strftime("%H:%M") == value
    except (TypeError, ValueError):
        return False


def validate_rule(db: Session, data: dict, own_id: int | None = None) -> dict:
    name = str(data.get("name", "")).strip()
    if not name or len(name) > 120:
        raise HTTPException(422, "偏好名称不能为空，且不能超过120个字。")
    kind = data.get("kind")
    if kind not in _KINDS:
        raise HTTPException(422, "不支持这种偏好类型。")
    category_key = data.get("category_key")
    if category_key is not None:
        validate_category(db, category_key, allow_inactive=True)
        if kind not in {"prefer_time", "avoid_time", "deadline_buffer"}:
            raise HTTPException(422, "只有时间和截止缓冲规则可以指定任务类别。")
    weekdays = data.get("weekdays")
    if weekdays is not None and (not isinstance(weekdays, list) or not weekdays or any(type(x) is not int or x < 1 or x > 7 for x in weekdays)):
        raise HTTPException(422, "适用星期请从周一至周日中选择。")
    params = data.get("parameters") or {}
    if not isinstance(params, dict):
        raise HTTPException(422, "偏好规则参数格式不正确。")
    if kind in {"prefer_time", "avoid_time"}:
        if set(params) != {"start", "end"} or not _clock(params.get("start")) or not _clock(params.get("end")) or params["start"] >= params["end"]:
            raise HTTPException(422, "时间偏好需要填写有效的开始和结束时间。")
    elif kind == "deadline_buffer":
        hours = params.get("hours")
        if type(hours) is not int or not 0 <= hours <= 72:
            raise HTTPException(422, "提前时间需在0到72小时之间。")
        params = {"hours": hours}
    elif kind == "adjustment_mode":
        if params.get("mode") not in {"balanced", "preference", "stable"} or set(params) != {"mode"}:
            raise HTTPException(422, "请选择兼顾、习惯优先或稳定优先。")
        duplicate = db.scalars(select(PreferenceRule).where(PreferenceRule.enabled.is_(True), PreferenceRule.kind == kind)).all()
        for item in duplicate:
            if item.id != own_id:
                item.enabled = False
    else:
        note = params.get("text")
        if not isinstance(note, str) or not note.strip() or len(note) > 1200:
            raise HTTPException(422, "AI参考说明需要填写，且不超过1200字。")
        params = {"text": note.strip()}
    return {"name": name, "description": str(data.get("description", ""))[:1000],
            "kind": kind, "category_key": category_key, "weekdays": weekdays,
            "parameters": params, "source": data.get("source", "user")}


def rule_payload(db: Session, row: PreferenceRule, categories=None) -> dict:
    category = (categories.get(row.category_key) if categories is not None else db.get(TaskCategory, row.category_key)) if row.category_key else None
    return dict(id=row.id, name=row.name, description=row.description, enabled=row.enabled, kind=row.kind,
                category_key=row.category_key, category_name=category.name if category else None,
                weekdays=row.weekdays, parameters=row.parameters, source=row.source,
                updated_at=row.updated_at.isoformat())


def rules_payload(db: Session) -> list[dict]:
    categories={row.key:row for row in category_rows(db)}
    return [rule_payload(db, row, categories) for row in db.scalars(select(PreferenceRule).order_by(PreferenceRule.id)).all()]


def compile_preferences(db: Session) -> dict:
    result = {"task_windows": {}, "avoid_windows": [], "avoid_windows_by_category": {},
              "deadline_buffer_hours": 0, "deadline_buffer_by_category": {}, "adjustment_mode": "balanced", "ai_notes": []}
    for row in db.scalars(select(PreferenceRule).where(PreferenceRule.enabled.is_(True)).order_by(PreferenceRule.id)).all():
        params = row.parameters or {}
        scoped_window = {key: value for key, value in params.items() if value is not None}
        if row.weekdays is not None:
            scoped_window["weekdays"] = row.weekdays
        if row.kind == "prefer_time":
            result["task_windows"].setdefault(row.category_key or "*", []).append(scoped_window)
        elif row.kind == "avoid_time":
            key = "avoid_windows" if row.category_key is None else "avoid_windows_by_category"
            if key == "avoid_windows":
                result[key].append(scoped_window)
            else:
                result[key].setdefault(row.category_key, []).append(scoped_window)
        elif row.kind == "deadline_buffer":
            key = "deadline_buffer_hours" if row.category_key is None else "deadline_buffer_by_category"
            if key == "deadline_buffer_hours":
                result[key] = max(result[key], params["hours"])
            else:
                result[key][row.category_key] = max(result[key].get(row.category_key, 0), params["hours"])
        elif row.kind == "adjustment_mode":
            result["adjustment_mode"] = params["mode"]
        elif row.kind == "ai_note":
            result["ai_notes"].append(params["text"])
    result["is_sample"] = any(row.source == "sample" for row in db.scalars(select(PreferenceRule).where(PreferenceRule.enabled.is_(True))).all())
    return result


def rules_from_legacy(db: Session, settings: dict, source: str = "user") -> None:
    """Compatibility adapter. Only updates provided categories; custom rules survive."""
    for category_key, windows in (settings.get("task_windows") or {}).items():
        if category_key != "*":
            validate_category(db, category_key)
        rule_category = None if category_key == "*" else category_key
        existing = db.scalars(select(PreferenceRule).where(PreferenceRule.kind == "prefer_time", PreferenceRule.category_key == rule_category)).all()
        for row in existing:
            row.enabled = False
        category = db.get(TaskCategory, rule_category) if rule_category else None
        for index, window in enumerate(windows):
            row = PreferenceRule(name=f"{category.name if category else '全部任务'}适合时段" + (f" {index+1}" if index else ""),
                description="尽量把这类任务安排在合适时段。", kind="prefer_time", category_key=rule_category,
                parameters={key: value for key, value in window.items() if value is not None}, source=source)
            db.add(row)
    if "avoid_windows" in settings:
        for row in db.scalars(select(PreferenceRule).where(PreferenceRule.kind == "avoid_time", PreferenceRule.category_key.is_(None))).all(): row.enabled = False
        for index, window in enumerate(settings.get("avoid_windows") or []):
            db.add(PreferenceRule(name="尽量避开" + (f" {index+1}" if index else ""), description="尽量避开这段时间。",
                kind="avoid_time", parameters=dict(window), source=source))
    if "deadline_buffer_hours" in settings:
        for row in db.scalars(select(PreferenceRule).where(PreferenceRule.kind == "deadline_buffer", PreferenceRule.category_key.is_(None))).all(): row.enabled = False
        hours = int(settings["deadline_buffer_hours"])
        if hours:
            db.add(PreferenceRule(name="重要任务截止缓冲", description="重要任务尽量提前完成。", kind="deadline_buffer", parameters={"hours": hours}, source=source))
    if "adjustment_mode" in settings:
        existing = db.scalars(select(PreferenceRule).where(PreferenceRule.kind == "adjustment_mode")).all()
        for row in existing: row.enabled = False
        db.add(PreferenceRule(name="调整时的取舍", description="安排任务时采用的总体取舍。", kind="adjustment_mode",
            parameters={"mode": settings["adjustment_mode"]}, source=source))
    db.flush()
