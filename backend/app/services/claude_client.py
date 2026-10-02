"""Anthropic Messages-compatible gateway client; the model need not be Claude.

The existing Claude symbols/env names are retained for configuration compatibility.
No database or planning access.
"""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from dotenv import load_dotenv


TIMEOUT_SECONDS = 20.0


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


@dataclass(frozen=True)
class ClaudeConfig:
    api_key: str = field(repr=False)
    model: str
    base_url: str
    api_version: str = "2023-06-01"


def get_claude_config() -> ClaudeConfig:
    # Optional and lazy: missing AI settings never prevent FastAPI startup.
    # Process environment takes precedence over the backend-local .env file.
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    key = os.getenv("CLAUDE_API_KEY", "").strip()
    model = os.getenv("CLAUDE_MODEL", "").strip()
    base_url = os.getenv("CLAUDE_BASE_URL", "").strip()
    if not key or not model or not base_url:
        raise AIServiceError("AI_NOT_CONFIGURED")
    return ClaudeConfig(
        api_key=key,
        model=model,
        base_url=base_url,
        api_version=os.getenv("CLAUDE_API_VERSION", "").strip() or "2023-06-01",
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


async def request_claude(text: str, system: str, config: ClaudeConfig) -> str:
    # Accept a gateway origin or its /v1 API base without duplicating the version.
    base_url = config.base_url.rstrip("/").removesuffix("/v1")
    try:
        # Both per-operation and total request deadlines are bounded.
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": config.api_key,
                        "anthropic-version": config.api_version,
                        "content-type": "application/json",
                    },
                    json={
                        "model": config.model,
                        "max_tokens": 600,
                        # Omit temperature for gateway/model compatibility.
                        "system": system,
                        "messages": [{"role": "user", "content": text}],
                    },
                )
                response.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError):
        # Do not expose provider errors, headers, request text, or secrets.
        raise AIServiceError("AI_UNAVAILABLE") from None
    try:
        body = response.json()
    except (ValueError, RecursionError):
        raise AIServiceError("AI_RESPONSE_INVALID") from None
    return extract_text(body)
