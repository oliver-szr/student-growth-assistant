import json
import asyncio
import pytest


def test_model_contract_rejects_invented_fields_and_multiple_adds(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import AIServiceError, ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(*args): return json.dumps({'actions':[{'op':'add','fields':{'title':'报告','invented':True}}],'questions':[]})
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    with pytest.raises(AIServiceError): asyncio.run(assistant_ai.parse_message('报告',dict(now='2026-10-07T18:00:00+08:00',tasks=[])))


def test_model_context_and_missing_deadline_are_not_fabricated(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(text,system,config,max_tokens):
        assert max_tokens==1600
        assert 'task:42' in text and '2026-10-08T12:00:00+08:00' in text
        return json.dumps({'actions':[{'op':'add','fields':{'title':'报告'}}],'questions':['截止到几点？']})
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    parsed=asyncio.run(assistant_ai.parse_message('新增报告',dict(now='2026-10-07T18:00:00+08:00',tasks=[dict(ref='task:42',deadline='2026-10-08T12:00:00+08:00')])))
    assert parsed.actions[0].fields.deadline is None
    assert parsed.questions


def test_fenced_json_is_validated_and_duplicate_fields_rejected(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig,AIServiceError
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def fenced(*args): return '```json\n{"actions":[],"questions":["几点截止？"]}\n```'
    monkeypatch.setattr(assistant_ai,'request_claude',fenced)
    assert asyncio.run(assistant_ai.parse_message('报告',{})).questions==['几点截止？']
    async def duplicate(*args): return '{"actions":[],"questions":[],"questions":["重复字段"]}'
    monkeypatch.setattr(assistant_ai,'request_claude',duplicate)
    with pytest.raises(AIServiceError):asyncio.run(assistant_ai.parse_message('报告',{}))


def test_null_window_placeholders_do_not_erase_existing_preferences(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def raw(*args):return json.dumps({'actions':[{'op':'update','target':'draft:abc','fields':{'profile':{'fixed_start':'2026-10-08T14:00:00+08:00','preferred_windows':None,'allowed_windows':None}}}],'questions':[]})
    monkeypatch.setattr(assistant_ai,'request_claude',raw)
    parsed=asyncio.run(assistant_ai.parse_message('改到14点',{}))
    fields=parsed.actions[0].model_dump(mode='json',exclude_unset=True)['fields']['profile']
    assert 'preferred_windows' not in fields and 'allowed_windows' not in fields
    assert fields['fixed_start'].startswith('2026-10-08T14:00')


def test_model_context_keeps_all_task_constraints_without_database_metadata(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    tasks=[dict(ref=f'task:{i}',title=f'任务{i}',deadline='2026-10-08T12:00:00+08:00',duration_minutes=60,priority='high',status='todo',profile={'locked':True},created_at='private-metadata') for i in range(12)]
    async def response(text,*args):
        context=json.loads(text)['context']
        assert len(context['tasks'])==12
        assert all(t['profile']['locked'] and t['duration_minutes']==60 for t in context['tasks'])
        assert 'private-metadata' not in text
        assert context['history']==['最新一轮']*6
        return '{"actions":[],"questions":["几点截止？"]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    asyncio.run(assistant_ai.parse_message('新增任务',dict(tasks=tasks,history=['旧消息']*4+['最新一轮']*6)))
