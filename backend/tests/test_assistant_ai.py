import json
import asyncio
import pytest


@pytest.mark.parametrize('priority,accepted', [(2, True), ('normal', False)])
def test_profile_goal_priority_contract_is_numeric_and_strict(monkeypatch, priority, accepted):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig, AIServiceError
    monkeypatch.setattr(assistant_ai, 'get_claude_config', lambda: ClaudeConfig('test', 'test'))
    async def response(text, system, config, max_tokens):
        payload = json.loads(text)
        assert payload['goal_create_schema']['properties']['priority']['type'] == 'integer'
        return json.dumps({'reply': '目标草案待确认', 'questions': [], 'operations': [
            {'op': 'create_goal', 'title': '完成项目原型', 'metric_kind': 'deliverable', 'weekly_target': 1, 'priority': priority}
        ]})
    monkeypatch.setattr(assistant_ai, 'request_claude', response)
    if accepted:
        result = asyncio.run(assistant_ai.workspace_message('profile', '每周交付一个原型', {}))
        assert result['operations'][0]['priority'] == 2
    else:
        with pytest.raises(AIServiceError):
            asyncio.run(assistant_ai.workspace_message('profile', '每周交付一个原型', {}))


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


def test_profile_prompt_preserves_goal_name_and_maps_deliverables(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    captured = {}
    monkeypatch.setattr(assistant_ai, 'get_claude_config', lambda: ClaudeConfig('test', 'test'))
    async def response(text, system, config, max_tokens):
        captured['system'] = system
        return json.dumps({'reply': '我理解了。', 'questions': [], 'operations': []})
    monkeypatch.setattr(assistant_ai, 'request_claude', response)
    asyncio.run(assistant_ai.workspace_message('profile', '新增一个目标', {}))
    assert '目标名称必须保留用户明确说出的原名' in captured['system']
    assert 'deliverable表示可核实的成果物' in captured['system']


@pytest.mark.parametrize('message,window,expected_count', [
    ('新增编程类别，编程尽量安排在下午', {'start': '14:00', 'end': '18:00'}, 0),
    ('新增编程类别，编程尽量安排在下午13:00到17:00', {'start': '13:00', 'end': '17:00'}, 1),
])
def test_profile_chat_does_not_guess_vague_preference_windows(monkeypatch, message, window, expected_count):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai, 'get_claude_config', lambda: ClaudeConfig('test', 'test'))
    async def response(*args):
        return json.dumps({'reply': '我先整理类别。', 'questions': [], 'operations': [
            {'op': 'create_category', 'name': '编程', 'temp_ref': 'draftcat:programming'},
            {'op': 'create_preference_rule', 'name': '编程时段', 'description': '编程偏好时段', 'kind': 'prefer_time',
             'category_ref': 'draftcat:programming', 'parameters': window},
        ]})
    monkeypatch.setattr(assistant_ai, 'request_claude', response)
    result = asyncio.run(assistant_ai.workspace_message('profile', message, {'categories': [], 'preference_rules': []}))
    assert sum(item['op'] == 'create_preference_rule' for item in result['operations']) == expected_count
    if expected_count == 0:
        assert any('请告诉我希望的开始和结束时间' in question for question in result['questions'])


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


def test_recommendation_can_only_select_a_supplied_candidate(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(*args):return '{"candidate_id":"preference:0","reason_codes":["follows_task_window"]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    payload={'personal_preferences':{'task_windows':{'writing':[{'start':'08:00','end':'12:00'}]}},'candidate_options':[{'candidate_id':'preference:0','strategy':'preference','metrics':{},'changes':[]}]}
    result=asyncio.run(assistant_ai.recommend(payload))
    assert result=={'candidate_id':'preference:0','reason_codes':['follows_task_window']}


def test_recommendation_rejects_an_invented_candidate_id(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig,AIServiceError
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(*args):return '{"candidate_id":"invented:0","reason_codes":[]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    payload={'candidate_options':[{'candidate_id':'balanced:0','strategy':'balanced','metrics':{},'changes':[]}]}
    with pytest.raises(AIServiceError):asyncio.run(assistant_ai.recommend(payload))


def test_parser_prompt_shows_exact_persistent_preference_shape(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(_text,system,*args):
        assert '"preference_updates":{"task_windows":{"writing":[{"start":"08:00","end":"12:00"}]}}' in system
        return '{"actions":[],"questions":[]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    asyncio.run(assistant_ai.parse_message('以后写作上午8点到12点',{}))


def test_growth_insight_picker_receives_confirmed_preferences_and_only_returns_known_ids(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    candidates=[{'candidate_id':'practice:afternoon','sample_count':5,'active_days':5}]
    preferences={'task_windows':{'writing':[{'start':'08:00','end':'12:00'}]}}
    async def response(text,system,config,max_tokens):
        request=json.loads(text)
        assert request['supported_observations']==candidates
        assert request['confirmed_preferences']==preferences
        assert '至少来自5项不同任务' in system
        assert max_tokens==800
        return '{"candidate_ids":["practice:afternoon"]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    assert asyncio.run(assistant_ai.select_growth_insights(candidates,preferences))==['practice:afternoon']


def test_growth_insight_picker_rejects_invented_candidate(monkeypatch):
    from app.services import assistant_ai
    from app.services.claude_client import ClaudeConfig, AIServiceError
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:ClaudeConfig('test','test'))
    async def response(*args):return '{"candidate_ids":["invented:evening"]}'
    monkeypatch.setattr(assistant_ai,'request_claude',response)
    with pytest.raises(AIServiceError):
        asyncio.run(assistant_ai.select_growth_insights([{'candidate_id':'practice:afternoon'}],{}))
def test_schedule_explanation_uses_gentle_style_and_preserves_facts(monkeypatch):
    import asyncio,json
    from app.services import assistant_ai
    seen={}
    original='我把阅读留在周五晚上，给其他任务留出空间。**这份安排还待你确认**，也可以继续调整。'
    async def request(message,system,config,*args):
        seen.update(facts=json.loads(message),system=system)
        return original
    monkeypatch.setattr(assistant_ai,'request_claude',request)
    monkeypatch.setattr(assistant_ai,'get_claude_config',lambda:None)
    facts={'changes':[{'title':'文献阅读','after':'周五晚上'}],'summary':'待确认','diagnostics':[],'notices':[]}
    result=asyncio.run(assistant_ai.explain({**facts,'private_unrelated':'不得发送'}))
    assert result==original
    assert seen['facts']==facts
    for instruction in ('语气温柔但克制','不猜测','没有依据的安排理由不编造','不宣称已保存','修改仍需用户确认'):
        assert instruction in seen['system']
