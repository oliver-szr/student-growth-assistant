"""Task attention ranking and evidence-based duration advice endpoints."""

from datetime import date, datetime, time, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import GrowthGoal, Plan, PlanItem, PlanningState, Task, TaskFeedback, TaskGrowthContext, TaskStatus
from ..services import assistant_clock
from ..services.assistant_state import time_rules
from ..services.scheduling_types import SHANGHAI
from ..services.validator import expand_time_rules

router = APIRouter(prefix="/api/growth", tags=["Personal Growth"])

_URGENCY_ORDER = {"overdue": 0, "critical": 1, "urgent": 2, "soon": 3, "at_risk": 4, "normal": 5}
_IMPORTANCE_ORDER = {"high": 0, "normal": 1, "low": 2}


def _duration_advice(db: Session, task: Task, context: TaskGrowthContext, now: datetime) -> dict:
    if not context.family_confirmed or not context.family.strip():
        return {"task_id": task.id, "status": "needs_task_type", "suggestion": None, "evidence": {"sample_count": 0}}
    cutoff = now - timedelta(days=28)
    rows = db.scalars(
        select(TaskFeedback)
        .where(
            TaskFeedback.outcome == "completed",
            TaskFeedback.retracted_at.is_(None),
            TaskFeedback.family_confirmed_snapshot.is_(True),
            TaskFeedback.family_snapshot == context.family,
            TaskFeedback.completed_at >= cutoff,
            TaskFeedback.completed_at <= now,
            TaskFeedback.actual_minutes.is_not(None),
        )
        .order_by(TaskFeedback.id.desc())
    ).all()
    seen: set[int] = set()
    samples = []
    for row in rows:
        if row.task_id in seen:
            continue
        seen.add(row.task_id)
        baseline = row.initial_estimate_minutes
        if not baseline or not 0.75 * task.duration_minutes <= baseline <= 1.25 * task.duration_minutes:
            continue
        if not row.actual_minutes or row.actual_minutes <= 0 or not row.completed_at:
            continue
        samples.append(row)
    days = sorted({row.completed_at.date().isoformat() for row in samples})
    if len(samples) < 5 or len(days) < 3:
        return {
            "task_id": task.id,
            "status": "insufficient_data",
            "suggestion": None,
            "evidence": {"sample_count": len(samples), "active_days": len(days), "window_days": 28, "family": context.family},
        }
    ratios = sorted(row.actual_minutes / row.initial_estimate_minutes for row in samples)
    q_index = max(0, ceil(0.75 * len(ratios)) - 1)
    conservative_ratio = ratios[q_index]
    raw_minutes = task.duration_minutes * conservative_ratio
    if conservative_ratio < 1:
        raw_minutes = max(raw_minutes, task.duration_minutes * 0.75)
    suggested = ceil(raw_minutes / 30) * 30
    if suggested == task.duration_minutes:
        suggestion = None
        status = "keep_current"
    else:
        suggestion = suggested
        status = "suggested"
    return {
        "task_id": task.id,
        "status": status,
        "current_minutes": task.duration_minutes,
        "suggested_minutes": suggestion,
        "suggestion": suggestion,
        "evidence": {
            "sample_count": len(samples),
            "active_days": len(days),
            "window_days": 28,
            "family": context.family,
            "conservative_actual_estimate_ratio": round(conservative_ratio, 3),
            "sample_task_ids": [row.task_id for row in samples],
            "sample_days": days,
            "reduction_cap_percent": 25,
            "rounding_minutes": 30,
        },
    }


def _overlap(a: datetime, b: datetime, c: datetime, d: datetime) -> bool:
    return a < d and c < b


def _possible_starts(task: Task, now: datetime, week_start: date, fixed_busy: list[tuple[datetime, datetime]], assigned: dict[int, tuple[datetime, datetime]]) -> int:
    deadline = task.deadline.astimezone(SHANGHAI)
    if deadline <= now:
        return 0
    window_end = min(deadline, datetime.combine(week_start + timedelta(days=7), time.min, SHANGHAI))
    own = assigned.get(task.id)
    count = 0
    for day in range(7):
        current_date = week_start + timedelta(days=day)
        for step in range(28):
            start = datetime.combine(current_date, time(8), SHANGHAI) + timedelta(minutes=30 * step)
            end = start + timedelta(minutes=task.duration_minutes)
            if start < now or end > window_end or end.date() != start.date() or end.time() > time(22):
                continue
            if any(_overlap(start, end, a, b) for a, b in fixed_busy):
                continue
            other_assigned = [slot for task_id, slot in assigned.items() if task_id != task.id]
            if any(_overlap(start, end, a, b) for a, b in other_assigned):
                continue
            if own and own[0] == start and own[1] == end:
                count += 1
                continue
            count += 1
    return count


@router.get("/attention")
def attention_items(db: Session = Depends(get_db)) -> dict:
    now = assistant_clock.assistant_now().astimezone(SHANGHAI)
    week_start = now.date() - timedelta(days=now.weekday())
    expanded = expand_time_rules(week_start, time_rules(db))
    fixed_busy = [(entry.start_at, entry.end_at) for entry in expanded]

    confirmed = db.scalar(select(Plan).where(Plan.week_start == week_start, Plan.status == "confirmed"))
    assigned: dict[int, tuple[datetime, datetime]] = {}
    if confirmed:
        for item in db.scalars(select(PlanItem).where(PlanItem.plan_id == confirmed.id, PlanItem.kind == "task")).all():
            if item.task_id:
                assigned[item.task_id] = (
                    item.start_at.astimezone(SHANGHAI), item.end_at.astimezone(SHANGHAI),
                )

    contexts = {item.task_id: item for item in db.scalars(select(TaskGrowthContext)).all()}
    goals = {item.id: item for item in db.scalars(select(GrowthGoal)).all() if item.status == "active"}
    items = []
    for task in db.scalars(select(Task).where(Task.status == TaskStatus.todo)).all():
        deadline = task.deadline.astimezone(SHANGHAI)
        hours_left = (deadline - now).total_seconds() / 3600
        slots = _possible_starts(task, now, week_start, fixed_busy, assigned)
        if deadline <= now:
            urgency = "overdue"
            reason = "已经超过你设定的截止时间；截止时间没有被自动修改。"
        elif hours_left <= 24:
            urgency = "critical"
            reason = f"距离截止约 {max(1, int(hours_left))} 小时，建议优先确认安排。"
        elif hours_left <= 72:
            urgency = "urgent"
            reason = f"三天内截止，预计还需 {task.duration_minutes} 分钟。"
        elif hours_left <= 168:
            urgency = "soon"
            reason = "7天内截止，适合尽早留出一段连续时间。"
        else:
            urgency = "normal"
            reason = "截止时间较远，可以和更紧急的任务一起规划。"
        if slots == 0 and deadline > now and deadline.date() < week_start + timedelta(days=7):
            urgency = "at_risk"
            reason = "本周当前课程、保护时间和已确认安排中，找不到足够长的空档；需要调整条件。"
        elif slots == 1 and deadline > now:
            reason += " 当前只找到一个可用连续时段。"

        context = contexts.get(task.id)
        goal = goals.get(context.goal_id) if context and context.goal_id else None
        items.append({
            "task_id": task.id,
            "title": task.title,
            "deadline": deadline.isoformat(),
            "remaining_minutes": task.duration_minutes,
            "importance": task.priority.value,
            "urgency": urgency,
            "reason": reason,
            "available_start_count": slots,
            "has_confirmed_time": task.id in assigned,
            "goal": {"id": goal.id, "title": goal.title, "priority": goal.priority} if goal else None,
        })

    items.sort(key=lambda item: (
        _URGENCY_ORDER[item["urgency"]],
        _IMPORTANCE_ORDER[item["importance"]],
        -(item["goal"]["priority"] if item["goal"] else 0),
        item["deadline"],
        item["task_id"],
    ))
    state = db.get(PlanningState, 1)
    return {
        "now": now.isoformat(),
        "week_start": week_start.isoformat(),
        "revision": state.revision if state else 0,
        "items": items[:3],
        "overdue_count": sum(item["urgency"] == "overdue" for item in items),
    }


@router.get("/tasks/{task_id}/duration-advice")
def duration_advice(task_id: int, db: Session = Depends(get_db)) -> dict:
    task = db.get(Task, task_id)
    if task is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="任务不存在")
    context = db.get(TaskGrowthContext, task_id)
    if context is None:
        context = TaskGrowthContext(task_id=task_id, initial_estimate_minutes=task.duration_minutes)
    return _duration_advice(db, task, context, assistant_clock.assistant_now().astimezone(SHANGHAI))
