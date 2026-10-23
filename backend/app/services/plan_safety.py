"""Safety boundary for the retained, single-week planning API.

The legacy engine has no concept of execution history or task profiles. Keep
its simple contract, block elapsed time, and reject worlds it cannot preserve.
The main assistant remains the existing entry point for those richer worlds.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Plan, PlanItem, Task, TaskSchedulingProfile, TimeRule
from .scheduling_types import Assignment, SHANGHAI, SchedulingInputError, TaskInput, TimeRuleInput
from .validator import expand_time_rules, validate_schedule, week_bounds


def validate_retained_history(previous: list[dict], retained: list[dict], now: datetime) -> None:
    """Only formal snapshots can authorize retained history, never pending drafts."""
    def key(item):
        start = datetime.fromisoformat(item["start_at"])
        end = datetime.fromisoformat(item["end_at"])
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("History timestamps must include an offset.")
        return item["ref"], item["title"], start.astimezone(SHANGHAI), end.astimezone(SHANGHAI)

    try:
        formal = Counter(key(item) for item in previous)
        actual = Counter(key(item) for item in retained)
        required = Counter({item: count for item, count in formal.items() if item[3] <= now})
    except (KeyError, TypeError, ValueError) as error:
        raise SchedulingInputError("HISTORY_CHANGED", "保留的历史记录无效，请重新生成。") from error
    if not (actual <= formal and required <= actual):
        raise SchedulingInputError("HISTORY_CHANGED", "候选未完整保留正式历史记录，请重新生成。")


def prepare_plan_rules(
    db: Session, week_start: date, task_ids: list[int], current: Plan | None, now: datetime,
) -> list[TimeRuleInput]:
    """Read current constraints without writing tasks, rules, plans, or versions."""
    now = now.astimezone(SHANGHAI)
    _, week_end = week_bounds(week_start)
    if week_end <= now:
        raise SchedulingInputError("PAST_PLANNING_WINDOW", "不能为已经结束的周生成或确认新安排。")

    previous = list(db.scalars(select(PlanItem).where(
        PlanItem.plan_id == current.id, PlanItem.kind == "task",
    )).all()) if current else []
    relevant_ids = set(task_ids) | {item.task_id for item in previous}
    profiles = db.scalars(select(TaskSchedulingProfile).where(
        TaskSchedulingProfile.task_id.in_(relevant_ids),
    )).all()
    has_hard_profile = any(
        any((profile.settings or {}).get(key) for key in
            ("locked", "splittable", "fixed_start", "allowed_windows"))
        for profile in profiles
    )
    has_segments = len({item.task_id for item in previous}) != len(previous)
    if has_hard_profile or has_segments or any(item.start_at <= now for item in previous):
        raise SchedulingInputError(
            "PLAN_REQUIRES_ASSISTANT",
            "当前安排包含分段、锁定、指定时段或已开始的记录，请在规划工作台调整，以保留原有记录。",
        )

    rules = [TimeRuleInput(
        id=rule.id, kind=rule.kind.value, title=rule.title,
        recurrence=rule.recurrence.value, start_time=rule.start_time,
        end_time=rule.end_time, weekday=rule.weekday, date=rule.date,
        active=rule.active,
    ) for rule in db.scalars(select(TimeRule).order_by(TimeRule.id)).all()]
    next_id = max((rule.id for rule in rules), default=0) + 1
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        opens = datetime.combine(day, time(8), SHANGHAI)
        end = min(now, datetime.combine(day, time(22), SHANGHAI))
        if end > opens:
            rules.append(TimeRuleInput(
                id=next_id, kind="protected", title="已过去的时间", recurrence="once",
                date=day, start_time=time(8), end_time=end.time().replace(tzinfo=None),
            ))
            next_id += 1
    return rules


def validate_saved_plan(db: Session, plan: Plan, current: Plan | None, now: datetime) -> None:
    """Revalidate saved assignments against current facts, without scheduling."""
    if (not plan.task_ids or any(type(task_id) is not int or task_id <= 0 for task_id in plan.task_ids)
            or len(set(plan.task_ids)) != len(plan.task_ids)):
        raise SchedulingInputError("INVALID_TASKS", "候选任务列表无效，请重新生成。")
    rules = prepare_plan_rules(db, plan.week_start, plan.task_ids, current, now)
    tasks = list(db.scalars(select(Task).where(Task.id.in_(plan.task_ids))).all())
    if {task.id for task in tasks} != set(plan.task_ids):
        raise SchedulingInputError("TASK_NOT_FOUND", "部分所选任务已不存在，请重新生成。")
    if any(task.task_kind == "container" for task in tasks):
        raise SchedulingInputError("CONTAINER_NOT_EXECUTABLE", "父容器不能直接排程，请选择子任务。")
    task_inputs = [TaskInput(
        id=task.id, title=task.title, duration_minutes=task.duration_minutes,
        deadline=task.deadline, priority=task.priority.value, status=task.status.value,
    ) for task in tasks]
    items = list(db.scalars(select(PlanItem).where(PlanItem.plan_id == plan.id)).all())
    assignments = tuple(Assignment(
        task_id=item.task_id, title=item.title_snapshot,
        start_at=item.start_at, end_at=item.end_at,
    ) for item in items if item.kind == "task")
    result = validate_schedule(plan.week_start, task_inputs, rules, assignments)
    if not result.valid:
        raise SchedulingInputError(result.violations[0].code, "候选已不满足当前时间或约束，请重新生成。")
    expected_courses = sorted(
        (item.time_rule_id, item.start_at, item.end_at)
        for item in expand_time_rules(plan.week_start, rules) if item.kind == "course"
    )
    saved_courses = sorted(
        (item.time_rule_id, item.start_at, item.end_at) for item in items if item.kind == "course"
    )
    if saved_courses != expected_courses:
        raise SchedulingInputError("COURSE_SNAPSHOT_CHANGED", "候选课程记录与当前课程不一致，请重新生成。")
