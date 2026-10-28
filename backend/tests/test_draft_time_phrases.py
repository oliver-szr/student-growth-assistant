"""Execution windows and hard deadlines remain independent in tagged drafts."""
from datetime import datetime
import pytest
from app.services import draft_defaults
from tests.test_ai_skills import call, send
from tests.test_draft_defaults import defaults_chat, ref_of


@pytest.mark.parametrize('period,start',[
    ('早上','09:00'),('中午','12:00'),('下午','14:00'),('晚上','19:00'),
])
def test_tagged_period_defaults_survive_a_different_deadline_day(client,defaults_chat,period,start):
    result=send(client,defaults_chat,f'我明天{period}打算写操作系统实验报告，截止后天中午 #生成草案')
    draft=ref_of(result);value=draft['content']['schedule']
    assert value['title']=='操作系统实验报告'
    assert value['day']=='2026-10-15' and value['start_time']==start
    assert value['deadline']=='2026-10-16T12:00:00+08:00'
    assert value['duration_minutes']==60
    assert draft['status']=='ready' and not draft['unresolved']
    assert draft['field_sources']['deadline']=='user_explicit'
    assert draft['items'] and draft['items'][0]['start_at']==f'2026-10-15T{start}:00+08:00'
    assert result['content']['questions']==[] and call(client,'/api/tasks')==[]


@pytest.mark.parametrize('text,start,deadline',[
    ('我明天晚上打算写操作系统实验报告，截止后天中午 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('截止后天中午，明天晚上写操作系统实验报告 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('我明天晚上写操作系统实验报告，后天中午前交 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('我明天晚上19:30写操作系统实验报告，截止后天下午三点 #生成草案','19:30','2026-10-30T15:00:00+08:00'),
    ('明天晚上写操作系统实验报告，截止次日中午 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('2026-10-29晚上写操作系统实验报告，截止2026-10-30中午 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('明天晚上写操作系统实验报告，截止2026年10月30日中午 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
    ('明天晚上写操作系统实验报告，后天中午截止 #生成草案','19:00','2026-10-30T12:00:00+08:00'),
])
def test_execution_and_deadline_phrases_are_parsed_separately(text,start,deadline):
    now=datetime.fromisoformat('2026-10-28T10:00:00+08:00')
    value,sources=draft_defaults.schedule({'message':text},now)
    assert value.title=='操作系统实验报告'
    assert value.day.isoformat()=='2026-10-29' and value.start_time==start
    assert value.deadline.isoformat()==deadline
    assert sources['deadline']=='user_explicit'


def test_deadline_only_followup_preserves_schedule_day_and_exact_start():
    now=datetime.fromisoformat('2026-10-28T10:00:00+08:00')
    initial,sources=draft_defaults.schedule({'message':'明天晚上八点写操作系统实验报告'},now)
    for text in ('截止后天中午','截止次日中午'):
        value,_=draft_defaults.schedule({'message':text},now,base=initial.model_dump(mode='json'),sources=sources)
        assert value.day==initial.day and value.start_time=='20:00' and value.start_exact
        assert value.deadline.isoformat()=='2026-10-30T12:00:00+08:00'


def test_deadline_without_a_time_is_not_invented_and_does_not_move_execution():
    now=datetime.fromisoformat('2026-10-28T10:00:00+08:00')
    value,sources=draft_defaults.schedule({'message':'明天晚上写实验报告，截止后天'},now)
    assert value.day.isoformat()=='2026-10-29' and value.start_time=='19:00'
    assert value.deadline is None and sources['deadline']=='unresolved'
