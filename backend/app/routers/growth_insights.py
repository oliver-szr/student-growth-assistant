"""AI habit-insight lifecycle: review, edit, accept, or ignore."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..assistant_schemas import PreferenceSettings
from ..database import get_db
from ..models import AssistantPreference, GrowthInsight, TaskCategory, utc_now
from ..schemas import GrowthInsightPatch
from ..services.assistant_state import preference_settings
from ..services.growth_insights import analyze_and_save
from ..services.growth_profile import record_profile_revision
from ..services.planning_state import bump_revision, planning_transaction
from ..services.taxonomy import rules_from_legacy

router = APIRouter(prefix="/api/growth", tags=["Personal Growth"])


def _insight_payload(row: GrowthInsight) -> dict:
    return {"id": row.id, "kind": row.kind, "status": row.status, "observation": row.observation, "suggestion": row.suggestion, "evidence": row.evidence, "proposed_rule": row.proposed_rule, "created_at": row.created_at.isoformat(), "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None}


@router.get("/insights")
def list_growth_insights(status: str | None = None, db: Session = Depends(get_db)) -> dict:
    query = select(GrowthInsight).order_by(GrowthInsight.created_at.desc(), GrowthInsight.id.desc())
    if status in ("draft", "accepted", "ignored"):
        query = query.where(GrowthInsight.status == status)
    rows = db.scalars(query.limit(50)).all()
    return {"insights": [_insight_payload(row) for row in rows]}


@router.post("/insights/analyze")
async def analyze_growth_insights(db: Session = Depends(get_db)) -> dict:
    return await analyze_and_save(db)


@router.patch("/insights/{insight_id}")
def edit_growth_insight(insight_id: int, payload: GrowthInsightPatch, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        row = db.get(GrowthInsight, insight_id)
        if row is None:
            raise HTTPException(status_code=404, detail="成长建议不存在")
        if row.status != "draft":
            raise HTTPException(status_code=409, detail="只有待确认建议可以修改")
        label, start, end = {"morning": ("上午", "08:00", "12:00"), "afternoon": ("下午", "12:00", "18:00"), "evening": ("晚上", "18:00", "22:00")}[payload.time_window]
        family = row.proposed_rule["family"]
        category = db.get(TaskCategory, family)
        family_label = category.name if category else family
        row.proposed_rule = {**row.proposed_rule, "start": start, "end": end}
        row.suggestion = f"是否把“{family_label}尽量安排在{label}（{start}–{end}）”保存为长期偏好？这来自你开始记录计时的时段，不代表该时段效率更高。"
        result = _insight_payload(row)
    return result


@router.post("/insights/{insight_id}/accept")
def accept_growth_insight(insight_id: int, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        row = db.get(GrowthInsight, insight_id)
        if row is None:
            raise HTTPException(status_code=404, detail="成长建议不存在")
        if row.status == "accepted":
            result = {"insight": _insight_payload(row), "preferences": preference_settings(db)["settings"]}
        else:
            if row.status != "draft":
                raise HTTPException(status_code=409, detail="这条建议已被忽略，不能直接采用")
            current = preference_settings(db)["settings"]
            family = row.proposed_rule["family"]
            category = db.get(TaskCategory, family)
            if category is None or not category.active:
                raise HTTPException(status_code=409, detail="建议关联的任务类别已停用；请先恢复类别或忽略这条建议。")
            current["task_windows"] = {**current.get("task_windows", {}), family: [{"start": row.proposed_rule["start"], "end": row.proposed_rule["end"]}]}
            values = current
            rules_from_legacy(db, {"task_windows": {family: current["task_windows"][family]}}, source="insight")
            saved = db.get(AssistantPreference, 1)
            if saved is None:
                saved = AssistantPreference(id=1, settings=values, is_sample=False)
                db.add(saved)
            else:
                saved.settings = values
                saved.is_sample = False
            row.status = "accepted"
            row.reviewed_at = utc_now()
            db.flush()
            record_profile_revision(db, values)
            bump_revision(db)
            result = {"insight": _insight_payload(row), "preferences": values}
    return result


@router.post("/insights/{insight_id}/ignore")
def ignore_growth_insight(insight_id: int, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        row = db.get(GrowthInsight, insight_id)
        if row is None:
            raise HTTPException(status_code=404, detail="成长建议不存在")
        if row.status != "draft":
            raise HTTPException(status_code=409, detail="只有待确认建议可以忽略")
        row.status = "ignored"
        row.reviewed_at = utc_now()
        result = _insight_payload(row)
    return result
