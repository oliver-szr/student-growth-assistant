"""Read-only analytics contracts. Null means unavailable, never an invented zero."""
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PeriodMetrics(AnalyticsModel):
    start_date: date
    end_date_exclusive: date
    planned_task_count: int = Field(ge=0)
    planned_minutes: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    partial_task_count: int = Field(ge=0)
    feedback_count: int = Field(ge=0)
    known_actual_minutes: int = Field(ge=0)
    actual_minutes: int | None = Field(ge=0)
    unknown_actual_count: int = Field(ge=0)
    completion_rate: None = None
    cancelled_event_count: None = None
    data_state: Literal["no_records", "no_feedback", "missing_time", "complete"]


class CategoryMetrics(AnalyticsModel):
    key: str
    name: str
    completed_count: int = Field(ge=0)
    feedback_count: int = Field(ge=0)
    known_actual_minutes: int = Field(ge=0)
    actual_minutes: int | None = Field(ge=0)
    unknown_actual_count: int = Field(ge=0)
    known_time_share: float | None = Field(ge=0, le=1)


class EstimateMetrics(AnalyticsModel):
    sample_count: int = Field(ge=0)
    minimum_samples: int = 3
    status: Literal["insufficient_data", "available"]
    estimated_minutes: int | None = Field(ge=0)
    actual_minutes: int | None = Field(ge=0)
    difference_minutes: int | None
    deviation_ratio: float | None
    overrun_count: int = Field(ge=0)


class CategoryEstimate(EstimateMetrics):
    key: str
    name: str
    observation: str | None


class TaskEstimate(AnalyticsModel):
    task_id: int
    title: str
    category_key: str
    category_name: str
    completed_at: datetime
    estimated_minutes: int = Field(gt=0)
    actual_minutes: int = Field(ge=0)
    difference_minutes: int
    deviation_ratio: float


class EstimateSummary(EstimateMetrics):
    completed_candidates: int = Field(ge=0)
    excluded_unknown_time: int = Field(ge=0)
    excluded_incomparable_estimate: int = Field(ge=0)
    categories: list[CategoryEstimate]
    tasks: list[TaskEstimate]
    task_detail_limit: int = 20


class AnalyticsGoal(AnalyticsModel):
    goal_id: int
    goal_title: str
    metric_kind: Literal["time", "count", "deliverable"]
    target: int = Field(gt=0)
    unit_label: str
    actual: int | None = Field(ge=0)
    known_actual: int = Field(ge=0)
    remaining: int | None = Field(ge=0)
    status: str
    unknown_actual_count: int = Field(ge=0)
    linked_task_count: int = Field(ge=0)
    linked_done_count: int = Field(ge=0)
    linked_cancelled_count: int = Field(ge=0)


class AnalyticsDefinitions(AnalyticsModel):
    completion: str
    effort: str
    plan: str
    completion_rate: str
    cancellation: str
    category: str
    estimate: str
    goals: str
    missing: str


class GrowthStatistics(AnalyticsModel):
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    unit: Literal["minutes"] = "minutes"
    weeks: Literal[4, 8, 12]
    start_date: date
    end_date_exclusive: date
    as_of: datetime
    overview: PeriodMetrics
    totals: PeriodMetrics
    weekly: list[PeriodMetrics]
    categories: list[CategoryMetrics]
    estimation: EstimateSummary
    goals: list[AnalyticsGoal]
    current_cancelled_task_count: int = Field(ge=0)
    excluded_invalid_feedback_count: int = Field(ge=0)
    legacy_completion_time_count: int = Field(ge=0)
    definitions: AnalyticsDefinitions
