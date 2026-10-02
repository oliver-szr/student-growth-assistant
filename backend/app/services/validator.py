"""Check assignments directly, independently of the placement algorithm.

The scheduler reuses only the input checks and TimeRule expansion, then asks
validate_schedule to check its completed assignments. This module never
imports or calls the scheduler.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from itertools import combinations

from .scheduling_types import (
    SHANGHAI,
    Assignment,
    RuleInterval,
    SchedulingInputError,
    TaskInput,
    TimeRuleInput,
    ValidationResult,
    Violation,
)


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    if type(week_start) is not date or week_start.isoweekday() != 1:
        raise SchedulingInputError("INVALID_WEEK", "week_start must be a Monday date.")
    try:
        next_monday = week_start + timedelta(days=7)
    except OverflowError as error:
        raise SchedulingInputError("INVALID_WEEK", "The full week must fit in the datetime range.") from error
    return (
        datetime.combine(week_start, time.min, SHANGHAI),
        datetime.combine(next_monday, time.min, SHANGHAI),
    )


def _is_aware(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _validate_selected_tasks(selected_tasks: Sequence[TaskInput]) -> None:
    seen = set()
    for task in selected_tasks:
        if not isinstance(task, TaskInput):
            raise SchedulingInputError("INVALID_TASKS", "Use TaskInput values for selected_tasks.")
        if type(task.id) is not int or task.id <= 0 or task.id in seen:
            raise SchedulingInputError("INVALID_TASKS", "Selected task IDs must be unique positive integers.")
        seen.add(task.id)
        if not isinstance(task.title, str) or not task.title.strip():
            raise SchedulingInputError("INVALID_TASKS", "Task title must not be blank.")
        if task.status != "todo":
            raise SchedulingInputError("INVALID_TASKS", f"Task {task.id} must be todo.")
        if task.priority not in ("high", "normal", "low"):
            raise SchedulingInputError("INVALID_TASKS", f"Task {task.id} has an invalid priority.")
        if type(task.duration_minutes) is not int or task.duration_minutes <= 0:
            raise SchedulingInputError("INVALID_TASKS", f"Task {task.id} duration must be a positive integer number of minutes.")
        if not _is_aware(task.deadline):
            raise SchedulingInputError("INVALID_TASKS", f"Task {task.id} deadline must be an aware datetime.")
        try:
            task.deadline.astimezone(SHANGHAI)
        except OverflowError as error:
            raise SchedulingInputError("INVALID_TASKS", f"Task {task.id} deadline is outside the local datetime range.") from error


def expand_time_rules(week_start: date, time_rules: Sequence[TimeRuleInput]) -> tuple[RuleInterval, ...]:
    """Validate raw rules and expand only active occurrences in this local week.

    Rule clock times are local wall times, not UTC. Protected intervals may
    overlap each other or courses; only course-course overlap is input conflict.
    """
    week_start_at, week_end_at = week_bounds(week_start)
    intervals = []
    seen = set()
    for rule in time_rules:
        if not isinstance(rule, TimeRuleInput):
            raise SchedulingInputError("INVALID_TIME_RULES", "Use TimeRuleInput values for time_rules.")
        if type(rule.id) is not int or rule.id <= 0 or rule.id in seen:
            raise SchedulingInputError("INVALID_TIME_RULES", "TimeRule IDs must be unique positive integers.")
        seen.add(rule.id)
        if not isinstance(rule.title, str) or not rule.title.strip():
            raise SchedulingInputError("INVALID_TIME_RULES", "TimeRule title must not be blank.")
        if rule.kind not in ("course", "protected") or rule.recurrence not in ("weekly", "once"):
            raise SchedulingInputError("INVALID_TIME_RULES", f"TimeRule {rule.id} has invalid kind or recurrence.")
        if type(rule.active) is not bool:
            raise SchedulingInputError("INVALID_TIME_RULES", f"TimeRule {rule.id} active must be boolean.")
        if not isinstance(rule.start_time, time) or not isinstance(rule.end_time, time):
            raise SchedulingInputError("INVALID_TIME_RULES", f"TimeRule {rule.id} requires local time values.")
        if rule.start_time.tzinfo is not None or rule.end_time.tzinfo is not None:
            raise SchedulingInputError("INVALID_TIME_RULES", f"TimeRule {rule.id} clock times must have no offset.")
        if rule.start_time >= rule.end_time:
            raise SchedulingInputError("INVALID_TIME_RULES", f"TimeRule {rule.id} must not cross midnight or have nonpositive duration.")
        if rule.kind == "course" and rule.recurrence != "weekly":
            raise SchedulingInputError("INVALID_TIME_RULES", f"Course {rule.id} must be weekly.")
        if rule.recurrence == "weekly":
            if type(rule.weekday) is not int or not 1 <= rule.weekday <= 7 or rule.date is not None:
                raise SchedulingInputError("INVALID_TIME_RULES", f"Weekly rule {rule.id} requires weekday 1-7 and no date.")
            occurrence = week_start + timedelta(days=rule.weekday - 1)
        else:
            if type(rule.date) is not date or rule.weekday is not None:
                raise SchedulingInputError("INVALID_TIME_RULES", f"Once rule {rule.id} requires a date and no weekday.")
            occurrence = rule.date
        if not rule.active or not week_start_at.date() <= occurrence < week_end_at.date():
            continue
        intervals.append(RuleInterval(
            time_rule_id=rule.id,
            kind=rule.kind,
            start_at=datetime.combine(occurrence, rule.start_time, SHANGHAI),
            end_at=datetime.combine(occurrence, rule.end_time, SHANGHAI),
        ))

    intervals.sort(key=lambda interval: (interval.start_at, interval.end_at, interval.time_rule_id))
    courses = [interval for interval in intervals if interval.kind == "course"]
    for left, right in combinations(courses, 2):
        if left.start_at < right.end_at and right.start_at < left.end_at:
            raise SchedulingInputError(
                "INVALID_TIME_RULES",
                f"Active courses {left.time_rule_id} and {right.time_rule_id} overlap.",
            )
    return tuple(intervals)


def validate_inputs(
    week_start: date,
    selected_tasks: Sequence[TaskInput],
    time_rules: Sequence[TimeRuleInput],
) -> tuple[RuleInterval, ...]:
    week_bounds(week_start)
    _validate_selected_tasks(selected_tasks)
    return expand_time_rules(week_start, time_rules)


def validate_schedule(
    week_start: date,
    selected_tasks: Sequence[TaskInput],
    time_rules: Sequence[TimeRuleInput],
    assignments: Sequence[Assignment],
) -> ValidationResult:
    """Validate a claimed complete schedule; malformed inputs are violations too."""
    try:
        rules = validate_inputs(week_start, selected_tasks, time_rules)
        week_start_at, week_end_at = week_bounds(week_start)
    except SchedulingInputError as error:
        return ValidationResult(False, (Violation(error.code, str(error)),))

    tasks_by_id = {task.id: task for task in selected_tasks}
    violations = []
    counts = Counter()
    normalized = []

    for assignment in assignments:
        if not isinstance(assignment, Assignment) or type(assignment.task_id) is not int or assignment.task_id <= 0:
            violations.append(Violation("INVALID_ASSIGNMENT", "Assignments require a positive integer task_id."))
            continue
        task_id = assignment.task_id
        counts[task_id] += 1
        task = tasks_by_id.get(task_id)
        if task is None:
            violations.append(Violation("UNSELECTED_TASK", "An assignment references an unselected task.", (task_id,)))
        if not _is_aware(assignment.start_at) or not _is_aware(assignment.end_at):
            violations.append(Violation("INVALID_DATETIME", "Assignment start/end must be aware datetimes.", (task_id,)))
            continue
        try:
            start = assignment.start_at.astimezone(SHANGHAI)
            end = assignment.end_at.astimezone(SHANGHAI)
        except OverflowError:
            violations.append(Violation("INVALID_DATETIME", "Assignment is outside the local datetime range.", (task_id,)))
            continue
        if end <= start:
            violations.append(Violation("INVALID_INTERVAL", "Assignment end must be after start.", (task_id,)))
            continue
        normalized.append((task_id, start, end))
        if task is not None:
            if (end - start).total_seconds() != task.duration_minutes * 60:
                violations.append(Violation("WRONG_DURATION", "Assignment duration differs from the selected task.", (task_id,)))
            if end > task.deadline.astimezone(SHANGHAI):
                violations.append(Violation("DEADLINE_VIOLATION", "Assignment ends after the task deadline.", (task_id,)))
        if start < week_start_at or start >= week_end_at or end > week_end_at:
            violations.append(Violation("OUTSIDE_WEEK", "Assignment must be inside the selected Shanghai week.", (task_id,)))
        if start.date() != end.date() or start.time() < time(8) or end.time() > time(22):
            violations.append(Violation("OUTSIDE_WORKING_HOURS", "Assignment must fit on one day within 08:00-22:00.", (task_id,)))
        if start.second or start.microsecond:
            violations.append(Violation("OFF_GRID", "Task start must be on the local 1-minute grid.", (task_id,)))
        for rule in rules:
            if start < rule.end_at and rule.start_at < end:
                code = "TASK_COURSE_OVERLAP" if rule.kind == "course" else "TASK_PROTECTED_OVERLAP"
                violations.append(Violation(code, f"Task overlaps active TimeRule {rule.time_rule_id}.", (task_id,)))

    for task_id in tasks_by_id:
        if counts[task_id] == 0:
            violations.append(Violation("MISSING_TASK", "Selected task has no assignment.", (task_id,)))
        elif counts[task_id] > 1:
            violations.append(Violation("DUPLICATE_TASK", "Selected task must appear exactly once.", (task_id,)))
    for left, right in combinations(normalized, 2):
        left_id, left_start, left_end = left
        right_id, right_start, right_end = right
        if left_start < right_end and right_start < left_end:
            violations.append(Violation("TASK_OVERLAP", "Task assignments overlap.", (left_id, right_id)))

    return ValidationResult(not violations, tuple(violations))
