"""Small immutable values shared by the scheduler and validator."""

from dataclasses import dataclass
from datetime import date as DateValue, datetime, time, timedelta, timezone
from typing import Literal


SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


class SchedulingInputError(ValueError):
    """Invalid input, distinct from a valid input with no greedy placement."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TaskInput:
    id: int
    title: str
    duration_minutes: int
    deadline: datetime
    priority: Literal["low", "normal", "high"] = "normal"
    status: Literal["todo", "done", "cancelled"] = "todo"


@dataclass(frozen=True)
class TimeRuleInput:
    id: int
    kind: Literal["course", "protected"]
    title: str
    recurrence: Literal["weekly", "once"]
    start_time: time
    end_time: time
    weekday: int | None = None
    date: DateValue | None = None
    active: bool = True


@dataclass(frozen=True)
class RuleInterval:
    time_rule_id: int
    kind: Literal["course", "protected"]
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class Assignment:
    task_id: int
    title: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class UnscheduledTask:
    task_id: int
    reason_code: str
    message: str


@dataclass(frozen=True)
class ScheduleResult:
    status: Literal["feasible", "unschedulable"]
    assignments: tuple[Assignment, ...] = ()
    unscheduled_tasks: tuple[UnscheduledTask, ...] = ()


@dataclass(frozen=True)
class Violation:
    code: str
    message: str
    task_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    violations: tuple[Violation, ...] = ()
