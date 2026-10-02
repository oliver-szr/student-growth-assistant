"""Request and response shapes for Task, TimeRule, and Plan APIs."""

from datetime import date as DateValue, time
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import PlanItemKind, PlanStatus, Recurrence, TaskPriority, TaskStatus, TimeRuleKind


Duration = Annotated[int, Field(strict=True, gt=0)]
Weekday = Annotated[int, Field(strict=True, ge=1, le=7)]


def required_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise ValueError("title must not be blank")
    return title


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    duration_minutes: Duration
    deadline: AwareDatetime
    priority: TaskPriority = TaskPriority.normal

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return required_title(value)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    duration_minutes: Duration | None = None
    deadline: AwareDatetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("title cannot be null")
        return required_title(value)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("duration_minutes cannot be null")
        return value

    @field_validator("deadline", "priority", "status")
    @classmethod
    def required_fields_cannot_be_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("this field cannot be null")
        return value


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    duration_minutes: int
    deadline: AwareDatetime
    priority: TaskPriority
    status: TaskStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime


class TimeRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TimeRuleKind
    title: str
    recurrence: Recurrence
    weekday: Weekday | None = None
    date: DateValue | None = None
    start_time: time
    end_time: time
    active: bool = True

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return required_title(value)

    @model_validator(mode="after")
    def validate_combination(self) -> "TimeRuleCreate":
        if self.recurrence == Recurrence.weekly:
            if self.weekday is None or self.date is not None:
                raise ValueError("weekly requires weekday and no date")
        elif self.date is None or self.weekday is not None:
            raise ValueError("once requires date and no weekday")

        if self.kind == TimeRuleKind.course and self.recurrence != Recurrence.weekly:
            raise ValueError("course must be weekly")
        if self.start_time.tzinfo is not None or self.end_time.tzinfo is not None:
            raise ValueError("start_time and end_time must be local times without offsets")
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time; overnight rules are not supported")
        return self


class TimeRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: TimeRuleKind | None = None
    title: str | None = None
    recurrence: Recurrence | None = None
    weekday: Weekday | None = None
    date: DateValue | None = None
    start_time: time | None = None
    end_time: time | None = None
    active: bool | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("title cannot be null")
        return required_title(value)


class TimeRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: TimeRuleKind
    title: str
    recurrence: Recurrence
    weekday: int | None
    date: DateValue | None
    start_time: time
    end_time: time
    active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


def monday_date(value: DateValue) -> DateValue:
    if value.isoweekday() != 1:
        raise ValueError("week_start must be a Monday")
    return value


class CandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: DateValue
    task_ids: Annotated[list[Annotated[int, Field(strict=True, gt=0)]], Field(min_length=1)]

    @field_validator("week_start")
    @classmethod
    def validate_week_start(cls, value: DateValue) -> DateValue:
        return monday_date(value)

    @field_validator("task_ids")
    @classmethod
    def validate_unique_ids(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("task_ids must be unique")
        return value


class PlanItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    kind: PlanItemKind
    task_id: int | None
    time_rule_id: int | None
    title_snapshot: str
    start_at: AwareDatetime
    end_at: AwareDatetime


class PlanResponse(BaseModel):
    id: int
    week_start: DateValue
    status: PlanStatus
    based_on_plan_id: int | None
    source_revision: int
    task_ids: list[int]
    created_at: AwareDatetime
    confirmed_at: AwareDatetime | None
    items: list[PlanItemResponse]


class UnscheduledTaskResponse(BaseModel):
    task_id: int
    reason_code: str
    message: str


class CandidateResponse(BaseModel):
    status: Literal["feasible"] = "feasible"
    candidate: PlanResponse
    unscheduled_tasks: list[UnscheduledTaskResponse] = Field(default_factory=list)
