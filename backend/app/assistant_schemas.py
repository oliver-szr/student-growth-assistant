from typing import Literal
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

    @model_validator(mode='before')
    @classmethod
    def unchanged_window_placeholders(cls,values):
        if isinstance(values,dict):
            return {k:v for k,v in values.items() if not (k in ('preferred_windows','allowed_windows') and v is None)}
        return values


class Fields(StrictModel):
    title: str | None = Field(default=None,min_length=1,max_length=200)
    description: str | None = Field(default=None,max_length=2000)
    duration_minutes: int | None = Field(default=None,strict=True,gt=0)
    deadline: AwareDatetime | None = None
    priority: Literal['high','normal','low'] | None = None
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

    @model_validator(mode='after')
    def one_new_task(self):
        if sum(a.op=='add' for a in self.actions)>1:
            raise ValueError('每轮最多新增一项任务')
        return self


class MessageRequest(ParsedCommand):
    client_message_id: str = Field(min_length=1,max_length=100)
    text: str = Field(min_length=1,max_length=2000)


class PreviewRequest(ParsedCommand):
    client_message_id: str | None = Field(default=None,min_length=1,max_length=100)
    alternative_index: int | None = Field(default=None,ge=0,le=1)
