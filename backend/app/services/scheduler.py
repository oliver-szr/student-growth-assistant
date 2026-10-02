"""Deterministic earliest-slot heuristic on a bounded local 1-minute grid."""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

from .scheduling_types import (
    SHANGHAI,
    Assignment,
    ScheduleResult,
    TaskInput,
    TimeRuleInput,
    UnscheduledTask,
)
from .validator import validate_inputs, validate_schedule


PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}
NO_SLOT_MESSAGE = "No continuous slot was found before the task deadline under the current MVP scheduling rules."


def schedule_week(
    week_start: date,
    selected_tasks: Sequence[TaskInput],
    time_rules: Sequence[TimeRuleInput],
) -> ScheduleResult:
    """Schedule exactly the selected tasks without mutating inputs or storing data.

    Invalid input raises SchedulingInputError. Valid but incomplete placement
    returns unschedulable with no partial assignments. A feasible result must
    pass the independent validator before it can be returned.
    """
    tasks = tuple(selected_tasks)
    rules = tuple(time_rules)
    intervals = validate_inputs(week_start, tasks, rules)
    occupied = [(interval.start_at, interval.end_at) for interval in intervals]
    ordered_tasks = sorted(tasks, key=lambda task: (
        task.deadline.astimezone(SHANGHAI), PRIORITY_ORDER[task.priority], task.id,
    ))
    assignments = []
    unscheduled = []

    for task in ordered_tasks:
        chosen = None
        # Even very large valid durations cannot fit in a 14-hour day; avoid
        # constructing an overflowing timedelta or trying to split the task.
        if task.duration_minutes <= 14 * 60:
            duration = timedelta(minutes=task.duration_minutes)
            deadline = task.deadline.astimezone(SHANGHAI)
            for day_offset in range(7):
                day = week_start + timedelta(days=day_offset)
                opens = datetime.combine(day, time(8), SHANGHAI)
                closes = datetime.combine(day, time(22), SHANGHAI)
                for grid_step in range(14 * 60):
                    start = opens + timedelta(minutes=grid_step)
                    end = start + duration
                    if end > closes or end > deadline:
                        continue
                    if any(start < busy_end and busy_start < end for busy_start, busy_end in occupied):
                        continue
                    chosen = Assignment(task.id, task.title, start, end)
                    break
                if chosen is not None:
                    break
        if chosen is None:
            unscheduled.append(UnscheduledTask(task.id, "NO_SLOT_FOUND", NO_SLOT_MESSAGE))
        else:
            assignments.append(chosen)
            occupied.append((chosen.start_at, chosen.end_at))

    if unscheduled:
        return ScheduleResult("unschedulable", unscheduled_tasks=tuple(unscheduled))

    result = ScheduleResult("feasible", assignments=tuple(assignments))
    validation = validate_schedule(week_start, tasks, rules, result.assignments)
    if not validation.valid:
        codes = ", ".join(violation.code for violation in validation.violations)
        raise RuntimeError(f"Scheduler produced an invalid complete schedule: {codes}")
    return result
