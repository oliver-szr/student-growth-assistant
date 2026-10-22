"""Messages wire format and failures using mock HTTP only."""

import asyncio
import json
from datetime import date, datetime, timezone

import httpx
import pytest

from app.services import claude_client, constraint_parser
from app.services.claude_client import AIServiceError, ClaudeConfig, get_claude_config, request_claude


CONFIG = ClaudeConfig("test-only-placeholder-secret", "configured-model", "https://gateway.example/", "2023-06-01")


@pytest.mark.parametrize('api_format', ['anthropic','openai'])
def test_stream_parses_only_final_text_and_requires_a_real_terminal(monkeypatch, api_format):
    real_client=httpx.AsyncClient
    config=ClaudeConfig('placeholder','model','https://gateway.example',api_format=api_format)
    if api_format=='openai':
        events=[{'choices':[{'delta':{'reasoning_content':'private'}}]},
            {'choices':[{'delta':{'content':'甲🙂'}}]}, {'choices':[{'delta':{'content':'乙'}}]},
            {'choices':[{'delta':{},'finish_reason':'stop'}]}]
        ending='data: [DONE]\n\n'
    else:
        events=[{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'private'}},
            {'type':'content_block_delta','delta':{'type':'text_delta','text':'甲🙂'}},
            {'type':'content_block_delta','delta':{'type':'text_delta','text':'乙'}},
            {'type':'message_delta','delta':{'stop_reason':'end_turn'}}, {'type':'message_stop'}]
        ending=''
    body=''.join('data: '+json.dumps(event,ensure_ascii=False)+'\n\n' for event in events)+ending
    mock_http(monkeypatch,lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},text=body))
    async def collect():return [event async for event in claude_client.stream_claude('history','system',config)]
    output=asyncio.run(collect())
    assert output==[{'type':'mode','value':'streaming'},{'type':'delta','text':'甲🙂'},{'type':'delta','text':'乙'}]
    broken=''.join('data: '+json.dumps(event,ensure_ascii=False)+'\n\n' for event in events[:2])
    monkeypatch.setattr(claude_client.httpx,'AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/event-stream'},text=broken)),**kw))
    with pytest.raises(AIServiceError):asyncio.run(collect())


def test_stream_rejection_falls_back_honestly_and_does_not_hide_auth_failure(monkeypatch):
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body)
        if body.get('stream'):return httpx.Response(422,json={'error':'stream unsupported'})
        return httpx.Response(200,json={'content':[{'type':'text','text':'完整回复'}],'stop_reason':'end_turn'})
    mock_http(monkeypatch,handler)
    async def collect():return [event async for event in claude_client.stream_claude('text','system',CONFIG)]
    assert asyncio.run(collect())==[{'type':'mode','value':'full'},{'type':'delta','text':'完整回复'}]
    assert len(calls)==2 and calls[0]['stream'] and 'stream' not in calls[1]


def test_stream_200_json_is_full_mode_without_a_second_request(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'content':[{'type':'text','text':'整段'}],'stop_reason':'end_turn'})
    mock_http(monkeypatch,handler)
    async def collect():return [event async for event in claude_client.stream_claude('text','system',CONFIG)]
    assert asyncio.run(collect())==[{'type':'mode','value':'full'},{'type':'delta','text':'整段'}]
    assert len(calls)==1


@pytest.mark.parametrize('status',[401,429,500])
def test_stream_errors_never_expose_secrets_or_automatically_repeat(monkeypatch,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,text='private-placeholder-secret internal gateway detail')
    mock_http(monkeypatch,handler)
    async def collect():return [event async for event in claude_client.stream_claude('text','system',CONFIG)]
    with pytest.raises(AIServiceError) as captured:asyncio.run(collect())
    assert captured.value.code=='AI_UNAVAILABLE'
    assert 'private-placeholder' not in str(captured.value) and len(calls)==1


def test_deepseek_official_defaults_to_low_thinking_with_room_for_final_json(monkeypatch):
    monkeypatch.setenv('AI_API_FORMAT','openai')
    monkeypatch.setenv('OPENAI_API_KEY','official-test-placeholder')
    monkeypatch.setenv('OPENAI_MODEL','deepseek-v4-pro')
    monkeypatch.setenv('OPENAI_BASE_URL','https://api.deepseek.com/v1/')
    monkeypatch.delenv('AI_THINKING_EFFORT',raising=False)
    config=get_claude_config()
    def handler(request):
        assert str(request.url)=='https://api.deepseek.com/v1/chat/completions'
        assert request.headers['authorization']=='Bearer official-test-placeholder'
        assert 'x-api-key' not in request.headers
        body=json.loads(request.content)
        assert body['model']=='deepseek-v4-pro'
        assert body['thinking']=={'type':'enabled'}
        assert body['reasoning_effort']=='low'
        assert body['max_tokens']>=8192
        assert body['messages']==[{'role':'system','content':'system'},{'role':'user','content':'data'}]
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'role':'assistant','reasoning_content':'private reasoning','content':'{"actions":[],"questions":[]}'}}]})
    mock_http(monkeypatch,handler)
    assert asyncio.run(request_claude('data','system',config,1600))=='{"actions":[],"questions":[]}'


def test_deepseek_thinking_can_be_disabled_without_raising_output_budget(monkeypatch):
    monkeypatch.setenv('AI_API_FORMAT','openai')
    monkeypatch.setenv('OPENAI_API_KEY','official-test-placeholder')
    monkeypatch.setenv('OPENAI_MODEL','deepseek-v4-pro')
    monkeypatch.setenv('OPENAI_BASE_URL','https://api.deepseek.com')
    monkeypatch.setenv('AI_THINKING_EFFORT','none')
    config=get_claude_config()
    def handler(request):
        body=json.loads(request.content)
        assert body['thinking']=={'type':'disabled'}
        assert 'reasoning_effort' not in body
        assert body['max_tokens']==1600
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'OK'}}]})
    mock_http(monkeypatch,handler)
    assert asyncio.run(request_claude('data','system',config,1600))=='OK'


def test_invalid_thinking_configuration_is_rejected_before_provider_call(monkeypatch):
    monkeypatch.setenv('CLAUDE_API_KEY','test-placeholder')
    monkeypatch.setenv('CLAUDE_MODEL','deepseek-v4-pro')
    monkeypatch.setenv('AI_THINKING_EFFORT','unknown')
    with pytest.raises(AIServiceError) as captured:get_claude_config()
    assert captured.value.code=='AI_NOT_CONFIGURED'


def test_openai_mode_never_uses_legacy_gateway_key_when_official_key_is_missing(monkeypatch):
    monkeypatch.setenv('AI_API_FORMAT','openai')
    monkeypatch.setenv('CLAUDE_API_KEY','old-gateway-placeholder')
    monkeypatch.setenv('OPENAI_MODEL','deepseek-v4-pro')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(AIServiceError) as captured:get_claude_config()
    assert captured.value.code=='AI_NOT_CONFIGURED'


@pytest.mark.parametrize('suffix',['','/','/v1','/v1/'])
def test_generic_openai_gateway_uses_chat_format_without_deepseek_extensions(monkeypatch,suffix):
    config=ClaudeConfig('generic-placeholder','generic-model','https://gateway.example'+suffix,api_format='openai')
    def handler(request):
        assert str(request.url)=='https://gateway.example/v1/chat/completions'
        assert request.headers['authorization']=='Bearer generic-placeholder'
        assert 'anthropic-version' not in request.headers
        body=json.loads(request.content)
        assert body=={'model':'generic-model','max_tokens':600,'messages':[{'role':'system','content':'system'},{'role':'user','content':'data'}]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'OK'}}]})
    mock_http(monkeypatch,handler)
    assert asyncio.run(request_claude('data','system',config))=='OK'


@pytest.mark.parametrize('body',[
    {'choices':[{'finish_reason':'length','message':{'content':'{"actions":[],"questions":[]}'}}]},
    {'choices':[{'finish_reason':'stop','message':{'content':None,'reasoning_content':'not a final answer'}}]},
    {'choices':[]}, {'choices':[None]}, {'choices':[{'message':{'content':5}}]},
])
def test_openai_truncated_or_missing_final_answer_is_rejected(monkeypatch,body):
    mock_http(monkeypatch,lambda request:httpx.Response(200,json=body))
    config=ClaudeConfig('placeholder','generic-model','https://gateway.example',api_format='openai')
    with pytest.raises(AIServiceError) as captured:asyncio.run(request_claude('data','system',config))
    assert captured.value.code=='AI_RESPONSE_INVALID'


def test_unknown_api_format_is_configuration_error(monkeypatch):
    monkeypatch.setenv('CLAUDE_API_KEY','placeholder')
    monkeypatch.setenv('CLAUDE_MODEL','model')
    monkeypatch.setenv('AI_API_FORMAT','unknown')
    with pytest.raises(AIServiceError) as captured:get_claude_config()
    assert captured.value.code=='AI_NOT_CONFIGURED'


def test_assistant_can_request_larger_output_without_extending_deadline(monkeypatch):
    def handler(request):
        assert json.loads(request.content)['max_tokens']==1600
        assert request.extensions['timeout']['read']==120.0
        return httpx.Response(200,json={'content':[{'type':'text','text':'OK'}]})
    mock_http(monkeypatch,handler)
    assert asyncio.run(request_claude('data','system',CONFIG,max_tokens=1600))=='OK'


def test_provider_timeout_can_be_configured_up_to_the_two_minute_limit(monkeypatch):
    monkeypatch.setenv('AI_TIMEOUT_SECONDS','45')
    def handler(request):
        assert request.extensions['timeout']['read']==45.0
        return httpx.Response(200,json={'content':[{'type':'text','text':'OK'}]})
    original=httpx.AsyncClient; transport=httpx.MockTransport(handler)
    monkeypatch.setattr(claude_client.httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    assert asyncio.run(request_claude('data','system',CONFIG))=='OK'


def test_budget_exhausted_response_is_never_accepted_as_complete(monkeypatch):
    mock_http(monkeypatch,lambda request:httpx.Response(200,json={'stop_reason':'max_tokens','content':[{'type':'text','text':'{"actions":[],"questions":[]}'}]}))
    with pytest.raises(AIServiceError) as captured:call()
    assert captured.value.code=='AI_RESPONSE_INVALID'


@pytest.mark.parametrize("suffix", ["", "/", "/v1", "/v1/"])
def test_gateway_base_url_never_duplicates_api_version(monkeypatch, suffix):
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/messages"
        return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}]})
    mock_http(monkeypatch, handler)
    config = ClaudeConfig("mock-key", "configured-model", "https://gateway.example" + suffix)
    assert asyncio.run(request_claude("data", "system", config)) == "OK"


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    def factory(**kwargs):
        assert kwargs["timeout"] == 120.0
        return original(transport=transport, **kwargs)
    monkeypatch.setattr(claude_client.httpx, "AsyncClient", factory)


def call():
    return asyncio.run(request_claude("Every Wednesday is lab time", "Parser system", CONFIG))


def test_native_messages_request_and_text_only_extraction(monkeypatch):
    def handler(request):
        assert str(request.url) == "https://gateway.example/v1/messages"
        assert request.method == "POST"
        assert request.headers["x-api-key"] == CONFIG.api_key
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert request.headers["content-type"] == "application/json"
        body = json.loads(request.content)
        assert body == {"model": "configured-model", "max_tokens": 600, "system": "Parser system",
                        "messages": [{"role": "user", "content": "Every Wednesday is lab time"}]}
        assert all(message["role"] != "system" for message in body["messages"])
        assert request.extensions["timeout"]["read"] == 120.0
        return httpx.Response(200, json={"content": [{"type": "thinking", "thinking": "ignore"}, {"type": "text", "text": "{\"status\":"}, {"type": "text", "text": "\"unsupported\"}"}]})
    mock_http(monkeypatch, handler)
    assert call() == '{"status":"unsupported"}'
    assert CONFIG.api_key not in repr(CONFIG)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 502, 503])
def test_provider_http_errors_never_expose_provider_secret(monkeypatch, status):
    mock_http(monkeypatch, lambda request: httpx.Response(status, text=CONFIG.api_key))
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_UNAVAILABLE"
    assert captured.value.status_code == 503
    assert CONFIG.api_key not in str(captured.value)
    assert "gateway.example" not in str(captured.value)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError])
def test_network_and_timeout_errors_are_safe(monkeypatch, error_type):
    def handler(request):
        raise error_type(CONFIG.api_key, request=request)
    mock_http(monkeypatch, handler)
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_UNAVAILABLE" and CONFIG.api_key not in str(captured.value)


def test_total_timeout(monkeypatch):
    async def handler(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}]})
    monkeypatch.setattr(claude_client, "TIMEOUT_SECONDS", 0.01)
    original = httpx.AsyncClient
    monkeypatch.setattr(claude_client.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_UNAVAILABLE"


@pytest.mark.parametrize("body", [{}, [], {"content": None}, {"content": []}, {"content": [{"type": "tool_use"}]}, {"content": [{"type": "text", "text": " "}]}, {"content": [{"type": "text", "text": 5}]}, {"content": [None]}])
def test_empty_missing_text_and_abnormal_structure(monkeypatch, body):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_RESPONSE_INVALID"


def test_non_json_provider_body(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, text="not JSON"))
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_RESPONSE_INVALID"


def test_deeply_nested_provider_body_is_a_safe_invalid_response(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, text="[" * 2000 + "0" + "]" * 2000))
    with pytest.raises(AIServiceError) as captured:
        call()
    assert captured.value.code == "AI_RESPONSE_INVALID"


def test_total_timeout_allows_manual_retry_without_automatic_retry(monkeypatch):
    calls = []

    async def handler(request):
        calls.append(request)
        if len(calls) == 1:
            await asyncio.sleep(0.1)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}]})

    monkeypatch.setattr(claude_client, "TIMEOUT_SECONDS", 0.01)
    original = httpx.AsyncClient
    monkeypatch.setattr(claude_client.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AIServiceError):
        call()
    assert len(calls) == 1
    assert call() == "{}"
    assert len(calls) == 2


def test_configuration_env_and_backend_local_dotenv(monkeypatch):
    calls = []
    monkeypatch.setattr(claude_client, "load_dotenv", lambda path, override: calls.append((path, override)))
    for name, value in {"CLAUDE_API_KEY": "test-only-placeholder", "CLAUDE_MODEL": "gateway-model", "CLAUDE_BASE_URL": "https://configured.example", "CLAUDE_API_VERSION": "custom-version"}.items():
        monkeypatch.setenv(name, value)
    config = get_claude_config()
    assert config.model == "gateway-model" and config.base_url == "https://configured.example"
    assert config.api_version == "custom-version"
    assert calls[0][0].parent.name == "backend" and calls[0][0].name == ".env"
    assert calls[0][1] is False


def test_current_date_context_and_fixed_shanghai_midnight(monkeypatch):
    class FixedDatetime:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(constraint_parser, "datetime", FixedDatetime)
    assert constraint_parser.current_shanghai_date() == date(2026, 10, 1)
    assert "Current date in Asia/Shanghai: 2026-10-01" in constraint_parser.build_system_prompt(date(2026, 10, 1))
