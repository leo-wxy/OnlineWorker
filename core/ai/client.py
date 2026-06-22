from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from .contracts import AiServiceConfig


@dataclass(frozen=True)
class AiHttpResponse:
    text: str
    raw: dict[str, Any] = field(default_factory=dict)


class AiClient:
    async def complete(
        self,
        *,
        service: AiServiceConfig,
        model: str,
        prompt: str,
        timeout_seconds: int,
    ) -> AiHttpResponse:
        protocol = service.protocol
        if protocol == "openai_compatible_chat":
            return await self._complete_openai_chat(
                service=service,
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
        if protocol == "anthropic_messages":
            return await self._complete_anthropic_messages(
                service=service,
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
        raise ValueError(f"Unsupported AI service protocol: {protocol}")

    async def _complete_openai_chat(
        self,
        *,
        service: AiServiceConfig,
        model: str,
        prompt: str,
        timeout_seconds: int,
    ) -> AiHttpResponse:
        api_key = _api_key_for(service)
        endpoint = service.endpoint or f"{(service.base_url or 'https://api.openai.com/v1').rstrip('/')}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        text = _openai_chat_text(data)
        return AiHttpResponse(text=text, raw=data)

    async def _complete_anthropic_messages(
        self,
        *,
        service: AiServiceConfig,
        model: str,
        prompt: str,
        timeout_seconds: int,
    ) -> AiHttpResponse:
        api_key = _api_key_for(service)
        endpoint = service.endpoint or "https://api.anthropic.com/v1/messages"
        payload = {
            "model": model,
            "max_tokens": 512,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        text = _anthropic_messages_text(data)
        return AiHttpResponse(text=text, raw=data)


def _api_key_for(service: AiServiceConfig) -> str:
    key = service.api_key.strip()
    if not key and service.api_key_env:
        key = os.environ.get(service.api_key_env, "")
    if not key:
        raise ValueError(f"AI service {service.id!r} missing API key")
    return key


def _openai_chat_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    return ""


def _anthropic_messages_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )
