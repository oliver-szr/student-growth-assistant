"""Small, explicit context/summary/memory contracts; client never chooses owner."""
import re
from typing import Literal
from pydantic import Field, field_validator
from .assistant_schemas import StrictModel

Scope=Literal['general','study','planning','review','profile']


class MemoryContent(StrictModel):
    text:str=Field(min_length=1,max_length=1200)
    scope:Scope='general'

    @field_validator('text')
    @classmethod
    def safe_text(cls,value):
        value=value.strip()
        if not value:raise ValueError('记忆正文不能为空')
        if re.search(r'(?i)\bsk-[\w-]{12,}|-----BEGIN .*PRIVATE KEY|(?:api[_ -]?key|access[_ -]?token|password|密码|密钥)\s*[:=：]\s*\S+',value):
            raise ValueError('请勿保存密钥、密码或访问凭证')
        return value


class MemoryCreate(MemoryContent):
    client_request_id:str=Field(min_length=1,max_length=100)


class MemoryEdit(MemoryContent):
    expected_version:int=Field(strict=True,ge=1)


class MemoryAction(StrictModel):
    expected_version:int=Field(strict=True,ge=1)
    action:Literal['confirm','disable','enable','delete']


class SummaryRequest(StrictModel):
    client_request_id:str=Field(min_length=1,max_length=100)
    before_id:int|None=Field(default=None,strict=True,ge=1)
    retry_attempt:int|None=Field(default=None,strict=True,ge=1)


class SummaryItem(StrictModel):
    text:str=Field(min_length=1,max_length=600)
    message_ids:list[int]=Field(min_length=1,max_length=8)


class SummaryContent(StrictModel):
    themes:list[SummaryItem]=Field(min_length=1,max_length=6)
    conclusions:list[SummaryItem]=Field(default_factory=list,max_length=6)
    questions:list[SummaryItem]=Field(default_factory=list,max_length=6)
    followups:list[SummaryItem]=Field(default_factory=list,max_length=6)


class LookupArgs(StrictModel):
    id:int|None=Field(default=None,strict=True,ge=1)
    q:str=Field(default='',max_length=100)
    offset:int=Field(default=0,strict=True,ge=0,le=10000)
    limit:int=Field(default=25,strict=True,ge=1,le=50)
