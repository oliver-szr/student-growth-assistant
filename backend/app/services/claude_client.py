"""Anthropic Messages and OpenAI Chat Completions-compatible client.

The existing Claude symbols/env names are retained for configuration compatibility.
No database or planning access.
"""

import asyncio
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


async def request_claude(text: str, system: str, config: ClaudeConfig, max_tokens: int = 600) -> str:
    timeout_seconds=_request_timeout()
    # Accept a gateway origin or its /v1 API base without duplicating the version.
    base_url = config.base_url.rstrip("/").removesuffix("/v1")
    try:
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
