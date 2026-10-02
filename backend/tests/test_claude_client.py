"""Messages wire format and failures using mock HTTP only."""

import asyncio
import json
from datetime import date, datetime, timezone

import httpx
import pytest

from app.services import claude_client, constraint_parser
from app.services.claude_client import AIServiceError, ClaudeConfig, get_claude_config, request_claude


CONFIG = ClaudeConfig("test-only-placeholder-secret", "configured-model", "https://gateway.example/", "2023-06-01")


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
        assert kwargs["timeout"] == 20.0
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
        assert request.extensions["timeout"]["read"] == 20.0
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


@pytest.mark.parametrize("missing", ["CLAUDE_API_KEY", "CLAUDE_MODEL", "CLAUDE_BASE_URL"])
@pytest.mark.parametrize("value", [None, "  "])
def test_configuration_requires_explicit_key_model_and_base_url(monkeypatch, missing, value):
    for name, setting in {"CLAUDE_API_KEY": "mock-key", "CLAUDE_MODEL": "mock-model", "CLAUDE_BASE_URL": "https://gateway.example"}.items():
        monkeypatch.setenv(name, setting)
    if value is None:
        monkeypatch.delenv(missing)
    else:
        monkeypatch.setenv(missing, value)
    with pytest.raises(AIServiceError) as captured:
        get_claude_config()
    assert captured.value.code == "AI_NOT_CONFIGURED"
    assert captured.value.status_code == 503


def test_current_date_context_and_fixed_shanghai_midnight(monkeypatch):
    class FixedDatetime:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(constraint_parser, "datetime", FixedDatetime)
    assert constraint_parser.current_shanghai_date() == date(2026, 10, 1)
    assert "Current date in Asia/Shanghai: 2026-10-01" in constraint_parser.build_system_prompt(date(2026, 10, 1))
