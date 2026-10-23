"""Bounded read-only views over the existing execution ledger and formal plans."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select, text

from ..analytics_schemas import GrowthStatistics
from ..models import GrowthGoal, Plan, PlanItem, Task, TaskCategory, TaskFeedback, TaskGrowthContext
from . import assistant_clock
from .growth_tracking import (goal_progress_from_feedback, valid_execution_feedback as valid_feedback,
                             feedback_completion_time as completion_time, unique_completed_feedback)
from .scheduling_types import SHANGHAI

DEFINITIONS = {
    "completion": "按有效completed反馈的completed_at归周，旧记录缺失时使用occurred_at并标记；每个可执行Task ID只保留最新一次有效完成，不由当前status反推历史。",
    "effort": "仅累计未撤回有效反馈的actual_minutes，按occurred_at归周，包含部分完成/暂缓；计时器不再累加。更正后旧反馈不计。",
    "plan": "当前仍为confirmed的正式快照中，可执行任务片段在范围内的分钟之和；每周任务按ID去重，区间总数再次去重，包含本周尚未到来的安排。",
    "completion_rate": "未保存不可变的周初计划任务集，无法可靠重建历史完成率；不把确认完成数除以当前可变计划数冒充历史完成率。",
    "cancellation": "没有独立取消时间日志，周取消事件数未知；仅展示查询时全库可执行任务的当前取消状态数，不按updated_at猜取消日期。",
    "category": "归属按反馈当时的family_snapshot稳定标识；存在类别时显示当前名称（含停用类别），否则显示历史名称；无快照归未分类，不从当前任务类别猜测。",
    "estimate": "按范围内确认完成任务配对：完成反馈保存的原始估时 vs 截至该完成记录的全部有效反馈耗时（含范围外早期投入）；按supersedes_id追溯原始记录顺序，晚补更正替换原投入而不重复相加。任一耗时缺失、原始估时不一致或修正链不可解释则排除。不用当前剩余时长比较。至少3项才描述类别规律。",
    "goals": "最近一周的有效反馈按历史goal_id_snapshot计算：time累计已知反馈分钟，count/deliverable按完成Task ID计数；对照当前weekly_target，不推断历史目标值或修改目标状态。关联任务状态为当前快照，父容器不贡献执行量。",
    "missing": "actual_minutes为null表示无反馈或耗时缺失；known_actual_minutes仅为已知小计，不能当完整投入；合法历史0分钟与未知区分。所有结果是截至查询时的更正后事实，不是当时数据库快照。",
}


def _time_summary(rows):
    known = sum(row.actual_minutes for row in rows if row.actual_minutes is not None)
    unknown = sum(row.actual_minutes is None for row in rows)
    return dict(feedback_count=len(rows), known_actual_minutes=known,
                actual_minutes=known if rows and unknown == 0 else None, unknown_actual_count=unknown)


def _metrics(start, end, feedback, completed, segments):
    a, b = datetime.combine(start, time.min, SHANGHAI), datetime.combine(end, time.min, SHANGHAI)
    rows = [row for row in feedback if a <= row.occurred_at < b]
    done = [row for row in completed if a <= completion_time(row) < b]
    planned_ids, minutes = set(), 0
    for task_id, begin, finish in segments:
        if begin < b and finish > a:
            planned_ids.add(task_id)
            minutes += max(0, int((min(finish, b)-max(begin, a)).total_seconds() // 60))
    values = _time_summary(rows)
    state = ("missing_time" if values["unknown_actual_count"] else "complete") if rows else ("no_feedback" if planned_ids or done else "no_records")
    return dict(start_date=start, end_date_exclusive=end, planned_task_count=len(planned_ids), planned_minutes=minutes,
                completed_count=len(done), partial_task_count=len({row.task_id for row in rows if row.outcome == "partial"}),
                **values, completion_rate=None, cancelled_event_count=None, data_state=state)


def _estimate_metrics(pairs):
    count = len(pairs)
    estimated = sum(pair["estimated_minutes"] for pair in pairs)
    actual = sum(pair["actual_minutes"] for pair in pairs)
    return dict(sample_count=count, minimum_samples=3, status="available" if count >= 3 else "insufficient_data",
                estimated_minutes=estimated if count else None, actual_minutes=actual if count else None,
                difference_minutes=actual-estimated if count else None, deviation_ratio=(actual-estimated)/estimated if count else None,
                overrun_count=sum(pair["difference_minutes"] > 0 for pair in pairs))


def _build(db, weeks, start, end, now, as_of):
    # Seven SELECTs at most, independent of task count. Only paired tasks need
    # earlier feedback outside the selected window to establish total effort.
    tasks = {row.id: row for row in db.scalars(select(Task)).all()}
    contexts = list(db.scalars(select(TaskGrowthContext)).all())
    categories = {row.key: row.name for row in db.scalars(select(TaskCategory)).all()}
    goals = list(db.scalars(select(GrowthGoal).order_by(GrowthGoal.priority, GrowthGoal.id)).all())
    lower, upper = datetime.combine(start, time.min, SHANGHAI), datetime.combine(end, time.min, SHANGHAI)
    source = list(db.scalars(select(TaskFeedback).where(TaskFeedback.retracted_at.is_(None),
        TaskFeedback.occurred_at <= as_of, or_(TaskFeedback.occurred_at >= lower, TaskFeedback.completed_at >= lower),
        TaskFeedback.occurred_at < upper).order_by(TaskFeedback.id)).all())
    feedback, invalid = [], 0
    for row in source:
        task = tasks.get(row.task_id)
        if not task or task.task_kind != "executable":
            continue
        if not valid_feedback(row):
            invalid += 1
            continue
        feedback.append(row)
    completed = [row for row in unique_completed_feedback(feedback, as_of) if lower <= completion_time(row) < upper]
    effort = [row for row in feedback if lower <= row.occurred_at < upper]
    history = list(db.scalars(select(TaskFeedback).where(TaskFeedback.task_id.in_([row.task_id for row in completed])).order_by(TaskFeedback.id)).all()) if completed else []
    histories = defaultdict(list)
    for row in history:
        histories[row.task_id].append(row)
    history_by_id = {row.id: row for row in history}

    def original_position(row):
        seen = set()
        current = row
        while current.supersedes_id is not None:
            if current.id in seen:
                return None
            seen.add(current.id)
            current = history_by_id.get(current.supersedes_id)
            if current is None or current.task_id != row.task_id:
                return None
        return current.id
    segments = list(db.execute(select(PlanItem.task_id, PlanItem.start_at, PlanItem.end_at).join(Plan).join(Task, Task.id == PlanItem.task_id).where(
        Plan.status == "confirmed", PlanItem.kind == "task", Task.task_kind == "executable",
        PlanItem.start_at < upper, PlanItem.end_at > lower)).all())

    def category(row):
        key = row.family_snapshot.strip() if row.family_snapshot else ""
        return key, categories.get(key) or (row.category_name_snapshot if key else None) or "未分类"

    grouped = {}
    for row in sorted(effort+completed, key=lambda row: row.id):
        key, name = category(row)
        grouped.setdefault(key, {"key": key, "name": name, "rows": [], "done": set()})["name"] = name
    for row in effort:
        grouped[category(row)[0]]["rows"].append(row)
    for row in completed:
        grouped[category(row)[0]]["done"].add(row.task_id)
    total_known = sum(row.actual_minutes or 0 for row in effort)
    distribution = []
    for key, item in sorted(grouped.items()):
        values = _time_summary(item["rows"])
        distribution.append(dict(key=key, name=item["name"], completed_count=len(item["done"]), **values,
                                 known_time_share=values["known_actual_minutes"]/total_known if total_known > 0 else None))

    pairs, excluded_unknown, excluded_estimate = [], 0, 0
    for row in completed:
        # Ancestors may have a later timestamp that the correction moved back;
        # retain them only to resolve identity/order, never as future effort.
        active = [item for item in histories[row.task_id] if item.retracted_at is None and item.occurred_at <= as_of]
        positions = {item.id: original_position(item) for item in active}
        if any(position is None for position in positions.values()):
            excluded_estimate += 1
            continue
        prior = [item for item in active if positions[item.id] <= positions[row.id]]
        if not prior or any(not valid_feedback(item) or item.actual_minutes is None for item in prior):
            excluded_unknown += 1
            continue
        baseline = row.initial_estimate_minutes
        if (type(baseline) is not int or baseline <= 0 or baseline % 5 or sum(item.outcome == "completed" for item in prior) != 1 or
                any(item.initial_estimate_minutes != baseline for item in prior)):
            excluded_estimate += 1
            continue
        actual = sum(item.actual_minutes for item in prior)
        key, name = category(row)
        pairs.append(dict(task_id=row.task_id, title=row.title_snapshot, category_key=key, category_name=name,
                          completed_at=completion_time(row), estimated_minutes=baseline, actual_minutes=actual,
                          difference_minutes=actual-baseline, deviation_ratio=(actual-baseline)/baseline))
    pair_groups = defaultdict(list)
    for pair in pairs:
        pair_groups[pair["category_key"]].append(pair)
    by_category = []
    for key, items in sorted(pair_groups.items()):
        metrics = _estimate_metrics(items)
        observation = None
        if metrics["status"] == "available" and metrics["overrun_count"]/len(items) >= 2/3 and metrics["deviation_ratio"] > .1:
            observation = f"这{len(items)}项可比较任务中，{metrics['overrun_count']}项超出原始估时，合计多用{metrics['difference_minutes']}分钟；只描述已有样本。"
        by_category.append(dict(key=key, name=items[-1]["category_name"], **metrics, observation=observation))

    weekly = [_metrics(start+timedelta(weeks=index), start+timedelta(weeks=index+1), effort, completed, segments) for index in range(weeks)]
    recent = weekly[-1]
    week_start = datetime.combine(recent["start_date"], time.min, SHANGHAI)
    week_end = datetime.combine(recent["end_date_exclusive"], time.min, SHANGHAI)
    recent_effort = [row for row in effort if week_start <= row.occurred_at < week_end]
    recent_done = [row for row in completed if week_start <= completion_time(row) < week_end]
    goal_data = []
    for progress in goal_progress_from_feedback(goals, recent_effort, recent_done):
        goal_id = progress["goal_id"]
        related = [row for row in recent_effort if row.goal_id_snapshot == goal_id]
        missing = sum(row.actual_minutes is None for row in related)
        known = progress["actual"]
        if progress["metric_kind"] == "time" and (not related or missing):
            progress = {**progress, "actual": None, "remaining": None}
        linked = [tasks[c.task_id] for c in contexts if c.goal_id == goal_id and c.task_id in tasks and tasks[c.task_id].task_kind == "executable"]
        goal_data.append(dict(**progress, known_actual=known, unknown_actual_count=missing,
                              linked_task_count=len(linked), linked_done_count=sum(t.status == "done" for t in linked),
                              linked_cancelled_count=sum(t.status == "cancelled" for t in linked)))
    return GrowthStatistics(weeks=weeks, start_date=start, end_date_exclusive=end, as_of=as_of,
        overview=recent, totals=_metrics(start,end,effort,completed,segments), weekly=weekly,
        categories=distribution, estimation=dict(**_estimate_metrics(pairs), completed_candidates=len(completed),
            excluded_unknown_time=excluded_unknown, excluded_incomparable_estimate=excluded_estimate,
            categories=by_category, tasks=sorted(pairs,key=lambda pair:(-pair["difference_minutes"],pair["task_id"]))[:20]),
        goals=goal_data, current_cancelled_task_count=sum(t.task_kind == "executable" and t.status == "cancelled" for t in tasks.values()),
        excluded_invalid_feedback_count=invalid, legacy_completion_time_count=sum(row.completed_at is None for row in completed),
        definitions=DEFINITIONS)


def statistics(db, weeks=4, end_week=None):
    now = assistant_clock.assistant_now().astimezone(SHANGHAI)
    current = now.date()-timedelta(days=now.weekday())
    last = end_week or current
    if weeks not in (4,8,12) or last.weekday() != 0 or last > current:
        raise HTTPException(422, detail={"code":"INVALID_STATISTICS_RANGE","message":"请选择4、8或12周，结束周须为不晚于当前周的周一。"})
    try:
        start, end = last-timedelta(weeks=weeks-1), last+timedelta(weeks=1)
    except OverflowError:
        raise HTTPException(422, detail={"code":"INVALID_STATISTICS_RANGE","message":"统计日期超出支持范围。"}) from None
    as_of = min(now,datetime.combine(end,time.min,SHANGHAI))
    # Explicit SQLite read snapshot: no ensure/create helpers, state changes,
    # persisted analytics or provider calls. Concurrent feedback cannot tear it.
    db.execute(text("BEGIN"))
    try:
        return _build(db,weeks,start,end,now,as_of)
    finally:
        db.rollback()
