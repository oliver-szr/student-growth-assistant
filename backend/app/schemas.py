"""Request and response shapes for Task, TimeRule, and Plan APIs."""

from datetime import date as DateValue, time
from typing import Annotated, Literal
from .services.grid import GRID_MINUTES

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
    parent_task_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    task_kind: Literal["executable", "container"] = "executable"
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10000)] = 0

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return required_title(value)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, value: int) -> int:
        if value % GRID_MINUTES != 0:
            raise ValueError("duration_minutes must be a multiple of 5")
        return value


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    duration_minutes: Duration | None = None
    deadline: AwareDatetime | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    parent_task_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    task_kind: Literal["executable", "container"] | None = None
    sort_order: Annotated[int, Field(strict=True, ge=0, le=10000)] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("title cannot be null")
        return required_title(value)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, value: int | None) -> int:
        if value is None or value % GRID_MINUTES != 0:
            raise ValueError("duration_minutes must be a positive multiple of 5")
        return value

    @field_validator("deadline", "priority", "status", "task_kind", "sort_order")
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
    parent_task_id: int | None = None
    task_kind: Literal["executable", "container"] = "executable"
    sort_order: int = 0
    progress: "TaskProgress | None" = None


class TaskProgress(BaseModel):
    total_children: int
    completed_children: int
    cancelled_children: int
    partial_children: int
    scheduled_children: int
    executed_children: int
    total_estimate_minutes: int
    remaining_minutes: int
    actual_minutes: int


TaskResponse.model_rebuild()


class GrowthGoalFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    motivation: str = Field(default="", max_length=2000)
    goal_type: Literal["long_term", "stage"] = "long_term"
    priority: Annotated[int, Field(strict=True, ge=1, le=3)] = 2
    metric_kind: Literal["time", "count", "deliverable"]
    weekly_target: Annotated[int, Field(strict=True, ge=1, le=100000)] = 1
    unit_label: str = Field(default="项", min_length=1, max_length=30)
    due_date: DateValue | None = None
    status: Literal["active", "paused", "completed", "archived"] = "active"

    @field_validator("title", "unit_label")
    @classmethod
    def validate_growth_text(cls, value: str) -> str:
        return required_title(value)


class GrowthGoalCreate(GrowthGoalFields):
    pass


class GrowthGoalPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    motivation: str | None = Field(default=None, max_length=2000)
    goal_type: Literal["long_term", "stage"] | None = None
    priority: Annotated[int, Field(strict=True, ge=1, le=3)] | None = None
    metric_kind: Literal["time", "count", "deliverable"] | None = None
    weekly_target: Annotated[int, Field(strict=True, ge=1, le=100000)] | None = None
    unit_label: str | None = Field(default=None, min_length=1, max_length=30)
    due_date: DateValue | None = None
    status: Literal["active", "paused", "completed", "archived"] | None = None

    @field_validator("title", "unit_label")
    @classmethod
    def validate_optional_growth_text(cls, value: str | None) -> str | None:
        return required_title(value) if value is not None else None

    @field_validator("motivation", "goal_type", "priority", "metric_kind", "weekly_target", "status")
    @classmethod
    def reject_null_for_present_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("this field cannot be null")
        return value


class GrowthGoalResponse(GrowthGoalFields):
    id: int
    version: int
    created_at: AwareDatetime
    updated_at: AwareDatetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class GrowthGoalsResponse(BaseModel):
    direction: str
    direction_version: int
    revision: int
    goals: list[GrowthGoalResponse]


class GrowthDirectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: str = Field(max_length=2000)

    @field_validator("direction")
    @classmethod
    def trim_direction(cls, value: str) -> str:
        return value.strip()


class TaskFeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=100)
    outcome: Literal["completed", "partial", "postponed"]
    actual_minutes: Annotated[int, Field(strict=True, ge=1, le=1440)] | None = None
    remaining_minutes: Annotated[int, Field(strict=True, ge=5, le=1440)] | None = None
    difficulty: Literal["easy", "expected", "hard"] | None = None
    reason: str | None = Field(default=None, max_length=500)
    family: str | None = Field(default=None, max_length=80)
    goal_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    corrects_feedback_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    completed_at: AwareDatetime | None = None
    occurred_at: AwareDatetime | None = None

    @field_validator("client_action_id")
    @classmethod
    def trim_action_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("client_action_id must not be blank")
        return value

    @field_validator("family", "reason")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("remaining_minutes")
    @classmethod
    def validate_remaining_minutes(cls, value: int | None) -> int | None:
        if value is not None and value % GRID_MINUTES != 0:
            raise ValueError("remaining_minutes must use 5-minute increments")
        return value

    @model_validator(mode="after")
    def validate_outcome_fields(self) -> "TaskFeedbackCreate":
        if self.outcome == "partial" and self.remaining_minutes is None:
            raise ValueError("partial feedback requires remaining_minutes")
        if self.outcome != "partial" and self.remaining_minutes is not None:
            raise ValueError("remaining_minutes is only valid for partial feedback")
        return self


class WorkSessionStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: Annotated[int, Field(strict=True, gt=0)]
    client_action_id: str = Field(min_length=1, max_length=100)

    @field_validator("client_action_id")
    @classmethod
    def trim_action_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("client_action_id must not be blank")
        return value


class TaskGrowthContextUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: Annotated[int, Field(strict=True, gt=0)] | None = None
    family: str = Field(min_length=1, max_length=80)
    deadline_source: Literal["external", "user_target"] = "external"

    @field_validator("family")
    @classmethod
    def trim_family(cls, value: str) -> str:
        return required_title(value)


class GrowthReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: DateValue

    @field_validator("week_start")
    @classmethod
    def validate_review_week(cls, value: DateValue) -> DateValue:
        return monday_date(value)


class GrowthInsightPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time_window: Literal["morning", "afternoon", "evening"]


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
