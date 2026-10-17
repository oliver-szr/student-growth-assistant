"""Bounded structured suggestions and optimistic draft editing contracts."""
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from .schemas import TaskResponse, required_title

MAX_CHILDREN = 20
Minutes = Annotated[int, Field(strict=True, ge=5, le=10080)]


class BreakdownParent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    deadline: AwareDatetime

    _title = field_validator("title")(required_title)


class BreakdownChild(BreakdownParent):
    duration_minutes: Minutes
    sort_order: Annotated[int, Field(strict=True, ge=0, lt=MAX_CHILDREN)]

    @field_validator("duration_minutes")
    @classmethod
    def grid(cls, value):
        if value % 5:
            raise ValueError("子任务时长必须为5分钟的整数倍")
        return value


class BreakdownContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent: BreakdownParent
    children: list[BreakdownChild] = Field(max_length=MAX_CHILDREN)

    @model_validator(mode="after")
    def validate_tree(self):
        orders = [child.sort_order for child in self.children]
        if len(set(orders)) != len(orders):
            raise ValueError("建议顺序不能重复")
        if any(child.deadline > self.parent.deadline for child in self.children):
            raise ValueError("子任务截止时间不能晚于父任务")
        return self


class GeneratedBreakdown(BreakdownContent):
    children: list[BreakdownChild] = Field(min_length=1, max_length=MAX_CHILDREN)


class BreakdownCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: str = Field(min_length=1, max_length=100)
    source: Literal["ai", "manual"] = "ai"
    text: str = Field(min_length=1, max_length=4000)
    title: str = Field(max_length=200)
    deadline: AwareDatetime
    expected_duration_minutes: Minutes
    goal_id: Annotated[int, Field(strict=True, gt=0)] | None = None

    _titles = field_validator("title", "text", "client_request_id")(required_title)
    _grid = field_validator("expected_duration_minutes")(BreakdownChild.grid.__func__)


class BreakdownEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(strict=True, ge=1)]
    content: BreakdownContent


class BreakdownVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Annotated[int, Field(strict=True, ge=1)]


class BreakdownResponse(BaseModel):
    id: int
    status: Literal["ready", "applied", "discarded", "stale"]
    source: Literal["ai", "manual"]
    source_revision: int
    version: int
    input: BreakdownCreate
    content: BreakdownContent
    total_minutes: int
    difference_minutes: int
    created_task_ids: list[int] = Field(default_factory=list)
    tasks: list[TaskResponse] = Field(default_factory=list)
