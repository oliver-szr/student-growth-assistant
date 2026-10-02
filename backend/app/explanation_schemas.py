"""Read-only explanation requests and deterministic diff responses."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from datetime import date


class ExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    language: Literal["en", "zh-CN"] = "en"


class DiffTask(BaseModel):
    task_id: int
    title: str
    start_at: AwareDatetime
    end_at: AwareDatetime


class MovedTask(BaseModel):
    task_id: int
    title: str
    from_start: AwareDatetime
    from_end: AwareDatetime
    to_start: AwareDatetime
    to_end: AwareDatetime


class DiffSummary(BaseModel):
    added_count: int
    removed_count: int
    moved_count: int
    unchanged_count: int


class PlanDiffResponse(BaseModel):
    confirmed_plan_id: int | None
    candidate_plan_id: int
    week_start: date
    summary: DiffSummary
    added: list[DiffTask]
    removed: list[DiffTask]
    moved: list[MovedTask]
    unchanged: list[DiffTask]


class ExplanationResponse(BaseModel):
    diff: PlanDiffResponse
    explanation: Annotated[str, Field(min_length=1, max_length=3000)] | None
    explanation_status: Literal["available", "unavailable", "deterministic"]
