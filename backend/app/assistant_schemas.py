from typing import Literal
from datetime import time
from pydantic import BaseModel, ConfigDict, AwareDatetime, Field, model_validator


class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Window(StrictModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode='after')
    def ordered(self):
        if self.start_at>=self.end_at: raise ValueError('时段结束必须晚于开始')
        return self


class Profile(StrictModel):
    fixed_start: AwareDatetime | None = None
    preferred_windows: list[Window] = Field(default_factory=list,max_length=14)
    allowed_windows: list[Window] = Field(default_factory=list,max_length=14)
    locked: bool = False
    splittable: bool = False
    min_block_minutes: int = Field(default=30, strict=True, ge=5, le=840, multiple_of=5)
    max_segments: int = Field(default=4, strict=True, ge=1, le=8)

    @model_validator(mode='before')
    @classmethod
    def unchanged_window_placeholders(cls,values):
        if isinstance(values,dict):
            return {k:v for k,v in values.items() if not (k in ('preferred_windows','allowed_windows') and v is None)}
        return values


class ClockWindow(StrictModel):
    start: str
    end: str
    weekdays: list[int] | None = Field(default=None, min_length=1, max_length=7)

    @model_validator(mode='after')
    def valid_clock_range(self):
        try: start=time.fromisoformat(self.start); end=time.fromisoformat(self.end)
        except ValueError: raise ValueError('时间请使用 HH:MM 格式') from None
        if len(self.start)!=5 or len(self.end)!=5 or start>=end: raise ValueError('偏好时段必须是有效的 HH:MM 时间范围')
        if self.weekdays is not None and (len(set(self.weekdays)) != len(self.weekdays) or any(type(day) is not int or day < 1 or day > 7 for day in self.weekdays)):
            raise ValueError('适用星期请使用1到7，且不能重复')
        return self


class PreferenceSettings(StrictModel):
    task_windows: dict[str,list[ClockWindow]] = Field(default_factory=dict)
    avoid_windows: list[ClockWindow] = Field(default_factory=list,max_length=14)
    deadline_buffer_hours: int = Field(default=24,strict=True,ge=0,le=72)
    adjustment_mode: Literal['balanced','preference','stable'] = 'balanced'

    @model_validator(mode='after')
    def valid_categories(self):
        if any(len(windows)>14 for windows in self.task_windows.values()): raise ValueError('每类任务最多设置14个偏好时段')
        return self


class PreferencePatch(StrictModel):
    task_windows: dict[str,list[ClockWindow]] | None = None
    avoid_windows: list[ClockWindow] | None = Field(default=None,max_length=14)
    deadline_buffer_hours: int | None = Field(default=None,strict=True,ge=0,le=72)
    adjustment_mode: Literal['balanced','preference','stable'] | None = None

    @model_validator(mode='after')
    def valid_categories(self):
        if self.task_windows is not None and any(len(windows)>14 for windows in self.task_windows.values()): raise ValueError('每类任务最多设置14个偏好时段')
        return self


class DateTimeWindow(StrictModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode='after')
    def ordered(self):
        if self.start_at>=self.end_at:raise ValueError('临时时段结束必须晚于开始')
        return self


class TemporaryPreferences(StrictModel):
    blocked_windows: list[DateTimeWindow] = Field(default_factory=list,max_length=14)
    avoid_windows: list[DateTimeWindow] = Field(default_factory=list,max_length=14)


class Fields(StrictModel):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=2000)
    duration_minutes: int | None = Field(default=None,strict=True,gt=0)
    deadline: AwareDatetime | None = None
    priority: Literal['high','normal','low'] | None = None
    task_type: str | None = Field(default=None, min_length=1, max_length=80)
    goal_id: int | None = None
    status: Literal['todo','done','cancelled'] | None = None
    profile: Profile | None = None

    @model_validator(mode='before')
    @classmethod
    def required_not_null(cls,values):
        if isinstance(values,dict) and any(k in values and values[k] is None for k in ('title','duration_minutes','deadline','priority','status','profile')):
            raise ValueError('必填任务字段不能显式设为空')
        if isinstance(values,dict) and isinstance(values.get('title'),str):
            values={**values,'title':values['title'].strip()}
        return values


class Action(StrictModel):
    op: Literal['add','update']
    target: str | None = Field(default=None,pattern=r'^(task:\d+|draft:[a-zA-Z0-9-]+)$')
    fields: Fields

    @model_validator(mode='after')
    def new_identity(self):
        if self.op=='add' and self.target and not self.target.startswith('draft:'):
            raise ValueError('新增任务只能使用新的草稿引用')
        return self


class ParsedCommand(StrictModel):
    actions: list[Action] = Field(default_factory=list,max_length=3)
    questions: list[str] = Field(default_factory=list,max_length=5)
    preference_updates: PreferencePatch | None = None
    temporary_preferences: TemporaryPreferences | None = None
    clear_temporary_preferences: bool = False
    strategy: Literal['balanced','preference','stable'] | None = None

    @model_validator(mode='after')
    def one_new_task(self):
        if sum(a.op=='add' for a in self.actions)>1:
            raise ValueError('每轮最多新增一项任务')
        return self


class Recommendation(StrictModel):
    candidate_id: str
    reason_codes: list[Literal['follows_task_window','avoids_unwanted_window','reduces_task_moves','more_deadline_buffer','balanced_tradeoff']] = Field(default_factory=list,max_length=5)


class GrowthInsightSelection(StrictModel):
    candidate_ids: list[str] = Field(default_factory=list,max_length=3)


class GrowthReviewSelection(StrictModel):
    lead_fact_id: str
    additional_fact_ids: list[str] = Field(default_factory=list, max_length=2)
    suggestion_id: str | None = None


class MessageRequest(ParsedCommand):
    replan: bool = False
    client_message_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=2000)


class PreviewRequest(ParsedCommand):
    expand_scope: bool = False
    client_message_id: str | None = Field(default=None,min_length=1,max_length=100)
    alternative_index: int | None = Field(default=None,ge=0,le=1)
    candidate_id: str | None = Field(default=None,min_length=1,max_length=80)
