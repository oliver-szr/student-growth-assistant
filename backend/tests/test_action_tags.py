"""Forced action tags and semantic routing use only isolated DBs/Mock providers."""
import asyncio
import json
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Plan, PlanItem
from app.services import ai_skills, claude_client, conversation_tools, conversation_runs
from app.services.ai_skills import resolve_skills as real_resolve
from tests.test_ai_skills import call, send
from tests.test_draft_defaults import defaults_chat, ref_of


@pytest.mark.parametrize('text,title',[
    ('我明天要写云计算ppt #生成草案','云计算ppt'),
    ('#生成草案','待命名任务'),
])
def test_explicit_draft_tag_bypasses_model_questions_and_keeps_formal_data_empty(client,defaults_chat,monkeypatch,test_engine,text,title):
    async def forbidden(*args,**kwargs):
        raise AssertionError('a forced default draft must not wait for a planner or classifier')
    monkeypatch.setattr(ai_skills,'resolve_skills',real_resolve)
    monkeypatch.setattr(conversation_tools,'plan',forbidden)
    monkeypatch.setattr(claude_client,'request_claude',forbidden)
    result=send(client,defaults_chat,text)
    draft=ref_of(result);value=draft['content']['schedule']
    assert value['title']==title and value['duration_minutes']==60 and value['deadline'] is None
    assert result['content']['questions']==[] and result['content']['business_status']=='awaiting_confirmation'
    assert call(client,'/api/tasks')==[]
    with Session(test_engine) as db:
        assert db.scalar(select(Plan)) is None and db.scalar(select(PlanItem)) is None


def test_review_tag_creates_real_editable_review_even_without_ai(client,defaults_chat,monkeypatch):
    async def unavailable(*args,**kwargs):raise claude_client.AIServiceError('AI_UNAVAILABLE')
    monkeypatch.setattr(conversation_tools,'plan',unavailable)
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    monkeypatch.setattr(claude_client,'request_claude',unavailable)
    draft=ref_of(send(client,defaults_chat,'本周 #复盘'))
    assert draft['kind']=='review_record' and draft['status']=='ready'
    assert draft['content']['summary']=='' and draft['notices']
    assert call(client,'/api/reviews/records')['items']==[] and call(client,'/api/tasks')==[]


@pytest.mark.parametrize('text,start,end',[
    ('明天 #查看日程','2026-10-15','2026-10-16'),
    ('下周 #日程','2026-10-19','2026-10-26'),
])
def test_calendar_tag_queries_the_requested_range_without_model_or_writes(client,defaults_chat,monkeypatch,text,start,end):
    async def forbidden(*args,**kwargs):raise AssertionError('tagged calendar uses an actual query and server receipt')
    monkeypatch.setattr(conversation_tools,'plan',forbidden)
    monkeypatch.setattr(conversation_runs,'reply_events',forbidden)
    result=send(client,defaults_chat,text)
    assert result['status']=='completed' and result['content']['business_status']=='queried'
    tools=result['content']['tools']
    assert len(tools)==1 and tools[0]['tool']=='calendar'
    assert tools[0]['start']==start and tools[0]['end_exclusive']==end
    assert '没有已保存的日程事项' in result['delta'] and call(client,'/api/tasks')==[]


@pytest.mark.parametrize('text',['“#生成草案”','说明 `#复盘`','```\n#查看日程\n```','解释 #生成草案 的意思'])
def test_only_active_trailing_tags_force_actions(text):
    assert ai_skills.action_tag(text) is None
    assert ai_skills.select_skills(text).expected is None


def test_untagged_agent_recognizes_semantics_outside_keyword_router(client,defaults_chat,monkeypatch):
    text='云计算ppt还没做，明天给它留个位置。'
    assert ai_skills.select_skills(text).expected is None
    requests=[]
    async def classify(prompt,*args,**kwargs):
        requests.append(json.loads(prompt))
        return json.dumps({'operation':'schedule'})
    monkeypatch.setattr(ai_skills,'resolve_skills',real_resolve)
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    monkeypatch.setattr(claude_client,'request_claude',classify)
    result=send(client,defaults_chat,text)
    draft=ref_of(result)
    assert len(requests)==1 and 'schedule' in requests[0]['allowed_operations']
    assert draft['content']['schedule']['title']=='云计算ppt'
    assert draft['content']['schedule']['day']=='2026-10-15'
    assert call(client,'/api/tasks')==[]


def test_untagged_agent_can_choose_chat_without_keyword_forcing(client,defaults_chat,monkeypatch):
    async def classify(*args,**kwargs):return json.dumps({'operation':'chat'})
    monkeypatch.setattr(ai_skills,'resolve_skills',real_resolve)
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    monkeypatch.setattr(claude_client,'request_claude',classify)
    result=send(client,defaults_chat,'我明天要写云计算ppt')
    assert result['status']=='completed' and result['content']['business_status']=='chat'
    assert result['content']['tools']==[] and call(client,'/api/tasks')==[]


def test_semantic_router_cannot_upgrade_denials_or_add_unknown_capabilities(monkeypatch):
    async def classify(*args,**kwargs):return json.dumps({'operation':'confirm_everything'})
    monkeypatch.setattr(claude_client,'get_claude_config',lambda:None)
    monkeypatch.setattr(claude_client,'request_claude',classify)
    result=asyncio.run(real_resolve({'message':'今天有点累'}))
    assert result.operation=='chat' and not result.allowed
    async def forbidden(*args,**kwargs):raise AssertionError('explicit denial does not call a classifier')
    monkeypatch.setattr(claude_client,'request_claude',forbidden)
    for text in ('先不要帮我安排','如果明天安排两小时会怎样','他说“#生成草案”是什么意思'):
        assert not asyncio.run(real_resolve({'message':text})).expected
