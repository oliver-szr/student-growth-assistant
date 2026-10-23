"""Strict range, record and AI tool contracts; no arbitrary write tools."""
from datetime import date
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, model_validator
from .assistant_schemas import StrictModel, Action, ConversationMessageCreate
from .task_breakdown_schemas import BreakdownCreate, BreakdownContent, DEFAULT_WORK_MINUTES

DRAFT_DEFAULTS = {'duration_minutes':DEFAULT_WORK_MINUTES,'start_time':'09:00','title':'待命名任务',
    'priority':'normal','segments':1,'break_minutes':0,'deadline':None}


class ReviewContent(StrictModel):
    period: Literal['day','week','month'] = 'week'
    start_date: date
    end_date: date
    title: str = Field(min_length=1,max_length=160)
    summary: str = Field(default='',max_length=6000)
    conclusion: str = Field(default='',max_length=6000)
    next_steps: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def valid(self):
        from .services.workspace_views import bounds
        bounds(self.start_date,self.end_date,366)
        if not self.title.strip():raise ValueError('标题不能为空')
        return self


class RecordCreate(ReviewContent):
    client_request_id: str = Field(min_length=1,max_length=100)


class RecordEdit(ReviewContent):
    expected_version: int = Field(strict=True,ge=1)


class DraftEdit(StrictModel):
    expected_version: str = Field(min_length=1,max_length=80)
    content: dict


class DraftAction(StrictModel):
    expected_version: str = Field(min_length=1,max_length=80)


class DraftRef(StrictModel):
    kind: Literal['planning','breakdown','profile','feedback','review_record']
    id: int = Field(strict=True,ge=1)
    version: str = Field(min_length=1,max_length=80)


class ToolCall(StrictModel):
    name: Literal['tasks','goals','preferences','calendar','review','memories','planning_draft','breakdown_draft','profile_draft','feedback_draft','edit_draft','memory_suggestion','review_draft']
    arguments: dict = Field(default_factory=dict)


class ToolPlan(StrictModel):
    questions: list[str] = Field(default_factory=list,max_length=4)
    calls: list[ToolCall] = Field(default_factory=list,max_length=4)
    continue_after_read: bool = False

    @model_validator(mode='after')
    def safe_continuation(self):
        if self.continue_after_read and (not self.calls or any(c.name not in ('tasks','goals','preferences','calendar','review','memories') for c in self.calls)):
            raise ValueError('Only a read-only query batch can request another planning step')
        return self


class RangeArgs(StrictModel):
    start: date
    end: date


class ReviewToolArgs(StrictModel):
    start_date: date
    end_date: date
    period: Literal['day','week','month'] = 'week'


class PlanningArgs(StrictModel):
    actions: list[Action] = Field(default_factory=list,max_length=3)
    questions: list[str] = Field(default_factory=list,max_length=5)
    replan: bool = True


class SchedulePreview(StrictModel):
    """Editable intent; a completion window is never a formal deadline."""
    title: str = Field(default=DRAFT_DEFAULTS['title'], min_length=1, max_length=200)
    duration_minutes: int = Field(default=DRAFT_DEFAULTS['duration_minutes'], strict=True, ge=5, le=840, multiple_of=5)
    day: date
    start_time: str = Field(default=DRAFT_DEFAULTS['start_time'], pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    start_exact: bool = False
    deadline: AwareDatetime | None = None
    priority: Literal['high', 'normal', 'low'] = 'normal'
    segments: int = Field(default=1, strict=True, ge=1, le=8)
    break_minutes: int = Field(default=0, strict=True, ge=0, le=120, multiple_of=5)
    task_id: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode='after')
    def valid_segments(self):
        if not self.title.strip():raise ValueError('请填写任务名称')
        if self.duration_minutes % self.segments or (self.duration_minutes // self.segments) % 5:
            raise ValueError('每段工作时长须为5分钟整数倍')
        return self


class BusinessArgs(StrictModel):
    operations: list[dict] = Field(min_length=1,max_length=10)


class EditToolArgs(StrictModel):
    kind: Literal['planning','breakdown','profile','feedback','review_record']
    id: int = Field(strict=True,ge=1)
    version: str
    content: dict


class ReviewDraftCreate(StrictModel):
    client_request_id: str = Field(min_length=1,max_length=100)
    start_date: date
    end_date: date
    period: Literal['day','week','month'] = 'week'
    message_id: int | None = Field(default=None,ge=1)


class ConversationToolRun(ConversationMessageCreate):
    draft_versions: list[DraftRef] = Field(default_factory=list,max_length=20)
    review_range: RangeArgs | None = None
