"""Fact-based weekly review endpoints and narrative fallbacks."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthGoal, GrowthWeeklyReview, Plan, PlanItem, Task, TaskFeedback
from ..schemas import GrowthReviewCreate
from ..services import assistant_ai, assistant_clock
from ..services.planning_state import planning_transaction
from ..services.scheduling_types import SHANGHAI
from ..services.growth_tracking import (goal_progress_from_feedback, valid_execution_feedback,
                                      feedback_completion_time, unique_completed_feedback)

router = APIRouter(prefix="/api/growth", tags=["Personal Growth"])


def _review_facts(db: Session, week_start: date) -> dict:
    week_end = week_start + timedelta(days=7)
    rows = db.scalars(
        select(TaskFeedback).join(Task, Task.id == TaskFeedback.task_id)
        .where(TaskFeedback.retracted_at.is_(None), Task.task_kind == "executable")
        .order_by(TaskFeedback.occurred_at, TaskFeedback.id)
    ).all()
    now = assistant_clock.assistant_now()
    rows = [row for row in rows if valid_execution_feedback(row) and row.occurred_at <= now]
    # Effort follows occurred_at; completion follows completed_at (legacy fallback
    # occurred_at). Shared with live statistics, even for cross-week backfills.
    in_week = [row for row in rows if row.occurred_at and week_start <= row.occurred_at.astimezone(SHANGHAI).date() < week_end]
    completed = [row for row in unique_completed_feedback(rows, now)
                 if week_start <= feedback_completion_time(row).astimezone(SHANGHAI).date() < week_end]
    goal_map = {goal.id: goal for goal in db.scalars(select(GrowthGoal)).all()}
    progress = goal_progress_from_feedback(goal_map.values(), in_week, completed)
    plan = db.scalar(select(Plan).where(Plan.week_start == week_start, Plan.status == "confirmed"))
    planned_minutes = 0
    if plan:
        for item in db.scalars(select(PlanItem).join(Task, Task.id == PlanItem.task_id).where(PlanItem.plan_id == plan.id, PlanItem.kind == "task", Task.task_kind == "executable")).all():
            planned_minutes += max(0, int((item.end_at - item.start_at).total_seconds() // 60))
    blockers = [
        {"task_title": row.title_snapshot, "reason": row.reason, "outcome": row.outcome}
        for row in in_week if row.reason
    ]
    return {
        "week_start": week_start.isoformat(),
        "week_end_exclusive": week_end.isoformat(),
        "completed_tasks": [
            {"task_id": row.task_id, "title": row.title_snapshot, "actual_minutes": row.actual_minutes,
             "initial_estimate_minutes": row.initial_estimate_minutes,
             "goal_title": row.goal_title_snapshot, "completed_at": row.completed_at.isoformat() if row.completed_at else None}
            for row in completed
        ],
        "completed_count": len({row.task_id for row in completed}),
        "confirmed_actual_minutes": sum(row.actual_minutes or 0 for row in in_week),
        "unknown_actual_count": sum(row.actual_minutes is None for row in in_week),
        "execution_feedback": [
            {"feedback_id": row.id, "task_id": row.task_id, "title": row.title_snapshot,
             "outcome": row.outcome, "actual_minutes": row.actual_minutes,
             "remaining_minutes": row.remaining_minutes, "reason": row.reason,
             "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
             "goal_title": row.goal_title_snapshot, "initial_estimate_minutes": row.initial_estimate_minutes}
            for row in in_week
        ],
        "planned_minutes": planned_minutes,
        "goal_progress": progress,
        "blockers": blockers,
        "data_quality_note": "完成按有效完成时间归周，投入按反馈发生时间归周；只统计用户确认的有效反馈，投入数为已知小计，缺失耗时不等于0；日程或计时结束不代表完成。旧复盘版本保留生成时的事实。",
    }


@router.get("/reviews")
def list_growth_reviews(week_start: date | None = None, db: Session = Depends(get_db)) -> dict:
    query = select(GrowthWeeklyReview).order_by(GrowthWeeklyReview.week_start.desc(), GrowthWeeklyReview.version.desc())
    if week_start:
        query = query.where(GrowthWeeklyReview.week_start == week_start)
    rows = db.scalars(query.limit(20)).all()
    return {"reviews": [_review_payload(row) for row in rows]}


def _review_payload(row: GrowthWeeklyReview) -> dict:
    return {"id": row.id, "week_start": row.week_start.isoformat(), "version": row.version, "facts": row.facts,
            "narrative": row.narrative, "summary_mode": (row.facts or {}).get("ai_summary_status", "facts_only"),
            "created_at": row.created_at.isoformat()}


def _review_options(facts: dict) -> tuple[list[dict], list[dict]]:
    fact_options = [{
        "id": "week-summary",
        "text": f"本周确认完成 {facts['completed_count']} 项任务，共记录已知 {facts['confirmed_actual_minutes']} 分钟投入。" + (f"另有{facts['unknown_actual_count']}条反馈耗时未知。" if facts.get('unknown_actual_count') else ""),
    }]
    suggestions = []
    for item in facts["goal_progress"]:
        fact_options.append({
            "id": f"goal-{item['goal_id']}",
            "text": f"目标“{item['goal_title']}”本周推进 {item['actual']} / {item['target']} {item['unit_label']}。",
        })
        if item["remaining"] and item["status"] == "active":
            suggestions.append({
                "id": f"goal-next-{item['goal_id']}",
                "text": f"下周可以为“{item['goal_title']}”提前安排一次行动；这是可讨论的建议，不会自动改日程。",
            })
    for index, item in enumerate(facts["blockers"]):
        fact_options.append({"id": f"blocker-{index}", "text": f"“{item['task_title']}”的记录提到：{item['reason']}。"})
        suggestions.append({
            "id": f"blocker-next-{index}",
            "text": f"下周可针对“{item['reason']}”预留缓冲，或把“{item['task_title']}”拆成更小的行动；是否尝试由你决定。",
        })
    return fact_options, suggestions


def _compose_review(selection: dict, fact_options: list[dict], suggestions: list[dict]) -> str:
    facts_by_id = {item["id"]: item["text"] for item in fact_options}
    suggestions_by_id = {item["id"]: item["text"] for item in suggestions}
    chosen = [selection["lead_fact_id"], *selection["additional_fact_ids"]]
    paragraphs = [f"**本周重点：** {facts_by_id[chosen[0]]}"]
    paragraphs.extend(f"- {facts_by_id[fact_id]}" for fact_id in chosen[1:])
    suggestion = selection.get("suggestion_id")
    if suggestion:
        paragraphs.append(f"**下周可以尝试：** {suggestions_by_id[suggestion]}")
    return "\n".join(paragraphs)


def _fallback_review(facts: dict, fact_options: list[dict], suggestions: list[dict]) -> str:
    preferred = next((item for item in fact_options if item["id"].startswith("goal-") and any(goal["goal_id"] == int(item["id"].split("-")[1]) and goal["remaining"] for goal in facts["goal_progress"])), fact_options[0])
    paragraphs = ["**本周重点：** " + preferred["text"]]
    if preferred["id"] != "week-summary":
        paragraphs.append("- " + fact_options[0]["text"])
    if suggestions:
        paragraphs.append("**可以讨论的下一步：** " + suggestions[0]["text"])
    paragraphs.append("AI 暂时无法整理说明，以上内容由已确认记录自动汇总。")
    return "\n".join(paragraphs)


@router.post("/reviews", status_code=201)
async def create_growth_review(payload: GrowthReviewCreate, db: Session = Depends(get_db)) -> dict:
    with planning_transaction(db):
        facts = _review_facts(db, payload.week_start)
        latest_version = db.scalar(select(GrowthWeeklyReview.version).where(GrowthWeeklyReview.week_start == payload.week_start).order_by(GrowthWeeklyReview.version.desc()).limit(1)) or 0
        row = GrowthWeeklyReview(week_start=payload.week_start, version=latest_version + 1, facts=facts, narrative=None)
        db.add(row)
        db.flush()
        db.refresh(row)

    fact_options, suggestions = _review_options(facts)
    from ..services.claude_client import AIServiceError
    summary_status = "ai"
    try:
        selection = await assistant_ai.select_growth_review(fact_options, suggestions)
        narrative = _compose_review(selection, fact_options, suggestions)
    except AIServiceError:
        summary_status = "facts_only"
        narrative = _fallback_review(facts, fact_options, suggestions)

    with planning_transaction(db):
        saved = db.get(GrowthWeeklyReview, row.id)
        if saved is None:
            raise HTTPException(status_code=409, detail="复盘版本已变化，请重新生成")
        saved.facts = {**saved.facts, "ai_summary_status": summary_status}
        saved.narrative = narrative
        result = _review_payload(saved)
    return result
