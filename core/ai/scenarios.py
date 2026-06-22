from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from config import get_data_dir, load_config

from .client import AiClient
from .contracts import AiConfig, AiScenarioConfig, AiScenarioResult
from .templates import render_prompt_template

logger = logging.getLogger(__name__)


async def run_ai_scenario(
    scenario_id: str,
    variables: dict[str, Any],
    *,
    config: AiConfig | None = None,
    client: Any | None = None,
) -> AiScenarioResult:
    active_config = config or load_config(data_dir=get_data_dir()).ai
    scenario = active_config.scenarios.get(scenario_id)
    if scenario is None:
        return AiScenarioResult(ok=False, fallback="", error="scenario_not_found")
    if not scenario.enabled:
        return _fallback(scenario, "scenario_disabled")
    service = active_config.services.get(scenario.service_id)
    if service is None:
        return _fallback(scenario, "service_not_found")
    if not service.enabled:
        return _fallback(scenario, "service_disabled")
    model = service.default_model
    if not model:
        return _fallback(scenario, "model_missing")

    prompt = render_prompt_template(scenario.prompt_template, variables)
    ai_client = client or AiClient()
    try:
        response = await ai_client.complete(
            service=service,
            model=model,
            prompt=prompt,
            timeout_seconds=service.timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "[ai] scenario failed scenario=%s %s",
            scenario.id,
            _format_client_error_context(service, model, exc),
        )
        return _fallback(scenario, "client_error")

    data = _parse_json_object(response.text)
    if not _validate_schema(scenario, data):
        return _fallback(scenario, "invalid_output")
    data = _apply_limits(scenario, data)
    return AiScenarioResult(ok=True, data=data)


def _fallback(scenario: AiScenarioConfig, error: str) -> AiScenarioResult:
    return AiScenarioResult(ok=False, fallback=scenario.fallback, error=error)


def _service_target(service: AiScenarioConfig | Any) -> str:
    protocol = str(getattr(service, "protocol", "") or "").strip()
    endpoint = str(getattr(service, "endpoint", "") or "").strip()
    base_url = str(getattr(service, "base_url", "") or "").strip().rstrip("/")
    if endpoint:
        return endpoint
    if protocol == "openai_compatible_chat":
        return f"{base_url or 'https://api.openai.com/v1'}/chat/completions"
    if protocol == "anthropic_messages":
        return "https://api.anthropic.com/v1/messages"
    return base_url


def _format_client_error_context(service: Any, model: str, exc: Exception) -> str:
    parts = [
        f"service={getattr(service, 'id', '') or 'unknown'}",
        f"model={model or 'unknown'}",
        f"timeout_s={getattr(service, 'timeout_seconds', 'unknown')}",
        f"target={_service_target(service) or 'unknown'}",
        f"error_type={type(exc).__name__}",
    ]
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        parts.append(f"status_code={exc.response.status_code}")
    request = _safe_exception_request(exc)
    if request is not None and getattr(request, "url", None):
        parts.append(f"request_url={request.url}")
    error_text = str(exc).strip()
    if error_text:
        parts.append(f"error={error_text}")
    else:
        parts.append(f"error_repr={exc!r}")
    return " ".join(parts)


def _safe_exception_request(exc: Exception) -> Any | None:
    try:
        return getattr(exc, "request", None)
    except RuntimeError:
        return None


def _parse_json_object(value: str) -> dict[str, Any]:
    import json

    text = str(value or "").strip()
    if text.startswith("```"):
        lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _validate_schema(scenario: AiScenarioConfig, data: dict[str, Any]) -> bool:
    if scenario.output_schema == "notification_summary_v1":
        preview_title = str(data.get("preview_title") or "").strip()
        summary = str(data.get("summary") or "").strip()
        return bool(preview_title and summary)
    return bool(data)


def _apply_limits(scenario: AiScenarioConfig, data: dict[str, Any]) -> dict[str, Any]:
    if scenario.output_schema != "notification_summary_v1":
        return data
    limited = dict(data)
    if scenario.limits.get("preview_title"):
        limited["preview_title"] = _limit_preview_title(
            limited.get("preview_title"),
            scenario.limits["preview_title"],
        )
    return limited


def _limit_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def _limit_preview_title(value: Any, limit: int) -> str:
    original = " ".join(str(value or "").split()).strip()
    text = _limit_text(original, limit)
    if len(original) <= limit:
        return text
    return re.sub(r"\s+[A-Za-z0-9_.-]*$", "", text).strip(" -_|:：，。；,.、和与及") or text
