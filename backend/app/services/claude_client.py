"""Anthropic Messages and OpenAI Chat Completions-compatible client.

The existing Claude symbols/env names are retained for configuration compatibility.
No database or planning access.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv


TIMEOUT_SECONDS = 120.0


class AIServiceError(Exception):
    """Only these fixed public messages may reach the API response."""

    def __init__(self, code: str):
        self.code = code
        self.status_code, self.message = {
            "AI_NOT_CONFIGURED": (503, "AI parsing is not configured."),
            "AI_UNAVAILABLE": (503, "The AI parsing service is temporarily unavailable."),
            "AI_RESPONSE_INVALID": (502, "The AI parsing service returned an invalid response."),
        }[code]
        super().__init__(self.message)


def _request_timeout():
    value=os.getenv('AI_TIMEOUT_SECONDS','').strip()
    if not value:return TIMEOUT_SECONDS
    try:seconds=float(value)
    except ValueError:raise AIServiceError('AI_NOT_CONFIGURED') from None
    if not 1<=seconds<=120:raise AIServiceError('AI_NOT_CONFIGURED')
    return seconds


@dataclass(frozen=True)
class ClaudeConfig:
    api_key: str = field(repr=False)
    model: str
    base_url: str = "https://newapi.iomgaa.online"
    api_version: str = "2023-06-01"
    api_format: str = "anthropic"
    thinking_effort: str | None = None


def get_claude_config() -> ClaudeConfig:
    # Optional and lazy: missing AI settings never prevent FastAPI startup.
    # Process environment takes precedence over the backend-local .env file.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    api_format = os.getenv("AI_API_FORMAT", "anthropic").strip().lower()
    if api_format not in ("anthropic", "openai"):
        raise AIServiceError("AI_NOT_CONFIGURED")
    prefix = "OPENAI" if api_format == "openai" else "CLAUDE"
    key = os.getenv(f"{prefix}_API_KEY", "").strip()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    if not key or not model:
        raise AIServiceError("AI_NOT_CONFIGURED")
    default_base = "https://api.openai.com/v1" if api_format == "openai" else "https://newapi.iomgaa.online"
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip() or default_base
    try:
        official_deepseek = urlsplit(base_url).hostname == "api.deepseek.com"
    except ValueError:
        raise AIServiceError("AI_NOT_CONFIGURED") from None
    effort = os.getenv("AI_THINKING_EFFORT", "").strip().lower() or None
    if effort is None and api_format == "openai" and official_deepseek:
        effort = "low"
    if effort not in (None, "none", "low", "high", "max"):
        raise AIServiceError("AI_NOT_CONFIGURED")
    return ClaudeConfig(
        api_key=key,
        model=model,
        base_url=base_url,
        api_version=os.getenv("CLAUDE_API_VERSION", "").strip() or "2023-06-01",
        api_format=api_format,
        thinking_effort=effort,
    )


def extract_text(body: object) -> str:
    if not isinstance(body, dict) or not isinstance(body.get("content"), list):
        raise AIServiceError("AI_RESPONSE_INVALID")
    parts = []
    for block in body["content"]:
        if not isinstance(block, dict):
            raise AIServiceError("AI_RESPONSE_INVALID")
        if block.get("type") == "text":
            if not isinstance(block.get("text"), str):
                raise AIServiceError("AI_RESPONSE_INVALID")
            parts.append(block["text"])
    text = "".join(parts).strip()
    if not text:
        raise AIServiceError("AI_RESPONSE_INVALID")
    return text


def extract_openai_text(body: object) -> str:
    if not isinstance(body, dict) or not isinstance(body.get("choices"), list) or not body["choices"]:
        raise AIServiceError("AI_RESPONSE_INVALID")
    choice = body["choices"][0]
    if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
        raise AIServiceError("AI_RESPONSE_INVALID")
    message = choice.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
        raise AIServiceError("AI_RESPONSE_INVALID")
    # Only the final answer enters parsers/UI; reasoning_content is not a task action.
    return message["content"].strip()


def _wire(text, system, config, max_tokens):
    # Accept a gateway origin or its /v1 API base without duplicating the version.
    base_url = config.base_url.rstrip("/").removesuffix("/v1")
    if config.api_format == "openai":
        endpoint = f"{base_url}/v1/chat/completions"
        headers = {"authorization": f"Bearer {config.api_key}", "content-type": "application/json"}
        payload = {"model": config.model, "max_tokens": max_tokens,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
        if urlsplit(base_url).hostname == "api.deepseek.com":
            enabled = config.thinking_effort != "none"
            payload["thinking"] = {"type": "enabled" if enabled else "disabled"}
            if enabled:
                payload["reasoning_effort"] = config.thinking_effort or "low"
                # DeepSeek's output budget also covers reasoning before the final JSON.
                payload["max_tokens"] = max(max_tokens, 8192)
        elif config.thinking_effort is not None:
            payload["reasoning_effort"] = config.thinking_effort
    else:
        endpoint = f"{base_url}/v1/messages"
        headers = {"x-api-key": config.api_key, "anthropic-version": config.api_version,
                   "content-type": "application/json"}
        payload = {"model": config.model, "max_tokens": max_tokens, "system": system,
                   "messages": [{"role": "user", "content": text}]}
    return endpoint, headers, payload


async def request_claude(text: str, system: str, config: ClaudeConfig, max_tokens: int = 600) -> str:
    timeout_seconds=_request_timeout()
    try:
        endpoint, headers, payload = _wire(text, system, config, max_tokens)
        # Both per-operation and total request deadlines are bounded.
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError):
        # Do not expose provider errors, headers, request text, or secrets.
        raise AIServiceError("AI_UNAVAILABLE") from None
    try:
        body = response.json()
    except (ValueError, RecursionError):
        raise AIServiceError("AI_RESPONSE_INVALID") from None
    if config.api_format == "openai":
        return extract_openai_text(body)
    if isinstance(body,dict) and body.get('stop_reason')=='max_tokens':
        raise AIServiceError('AI_RESPONSE_INVALID')
    return extract_text(body)


async def stream_claude(text: str, system: str, config: ClaudeConfig, max_tokens: int = 2000):
    """Only final-answer deltas leave the transport; reasoning never reaches UI.

    A rejecting gateway is retried once without stream. A broken established
    stream is never silently reissued. Callers persist actual received text.
    """
    timeout = _request_timeout()
    try:
        endpoint, headers, payload = _wire(text, system, config, max_tokens)
        payload['stream'] = True
        fallback = False
        async with asyncio.timeout(timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream('POST', endpoint, headers=headers, json=payload) as response:
                    if response.status_code in (400, 404, 405, 415, 422, 501):
                        fallback = True
                    else:
                        response.raise_for_status()
                        if 'text/event-stream' not in response.headers.get('content-type', ''):
                            raw = await response.aread()
                            if len(raw) > 1024 * 1024:
                                raise AIServiceError('AI_RESPONSE_INVALID')
                            body = json.loads(raw)
                            answer = extract_openai_text(body) if config.api_format == 'openai' else extract_text(body)
                            if config.api_format != 'openai' and body.get('stop_reason') not in ('end_turn', 'stop_sequence'):
                                raise AIServiceError('AI_RESPONSE_INVALID')
                            yield {'type': 'mode', 'value': 'full'}
                            yield {'type': 'delta', 'text': answer}
                            return
                        yield {'type': 'mode', 'value': 'streaming'}
                        data, size, ended, valid_finish, output = [], 0, False, False, 0
                        async for line in response.aiter_lines():
                            size += len(line)
                            if size > 1024 * 1024:
                                raise AIServiceError('AI_RESPONSE_INVALID')
                            if line.startswith('data:'):
                                data.append(line[5:].lstrip())
                            if line or not data:
                                continue
                            raw, data = '\n'.join(data), []
                            if raw == '[DONE]':
                                ended = True
                                break
                            event = json.loads(raw)
                            part = ''
                            if config.api_format == 'openai':
                                choices = event.get('choices', [])
                                if not choices:
                                    continue  # optional usage event
                                choice = choices[0]
                                if choice.get('finish_reason') is not None:
                                    valid_finish = choice['finish_reason'] == 'stop'
                                part = choice.get('delta', {}).get('content') or ''
                            else:
                                if event.get('type') == 'error':
                                    raise AIServiceError('AI_UNAVAILABLE')
                                if event.get('type') == 'content_block_delta' and event.get('delta', {}).get('type') == 'text_delta':
                                    part = event['delta'].get('text', '')
                                if event.get('type') == 'message_delta':
                                    valid_finish = event.get('delta', {}).get('stop_reason') in ('end_turn', 'stop_sequence')
                                if event.get('type') == 'message_stop':
                                    ended = True
                                    break
                            if not isinstance(part, str):
                                raise AIServiceError('AI_RESPONSE_INVALID')
                            output += len(part)
                            if output > 16000:
                                raise AIServiceError('AI_RESPONSE_INVALID')
                            if part:
                                yield {'type': 'delta', 'text': part}
                        if not ended or not valid_finish or not output:
                            raise AIServiceError('AI_RESPONSE_INVALID')
        if fallback:
            yield {'type': 'mode', 'value': 'full'}
            answer = await request_claude(text, system, config, max_tokens)
            yield {'type': 'delta', 'text': answer}
    except AIServiceError:
        raise
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError):
        raise AIServiceError('AI_UNAVAILABLE') from None
    except (ValueError, TypeError, KeyError, IndexError, RecursionError):
        raise AIServiceError('AI_RESPONSE_INVALID') from None
