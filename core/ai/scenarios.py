from __future__ import annotations

import logging
import os
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
    candidates = _service_candidates_for_scenario(active_config, scenario)
    if not candidates:
        service = active_config.services.get(scenario.service_id)
        if service is None:
            return _fallback(scenario, "service_not_found")
        if not service.enabled:
            return _fallback(scenario, "service_disabled")
        if not service.default_model and service.protocol != "provider_login":
            return _fallback(scenario, "model_missing")
        return _fallback(scenario, "service_unavailable")

    prompt = render_prompt_template(scenario.prompt_template, variables)
    ai_client = client or AiClient()

    last_error = ""
    for service in candidates:
        model = service.default_model
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
            last_error = "client_error"
            continue

        data = _parse_json_object(response.text)
        if not _validate_schema(scenario, data):
            last_error = "invalid_output"
            continue
        data = _apply_limits(scenario, data)
        return AiScenarioResult(ok=True, data=data)

    return _fallback(scenario, last_error or "service_unavailable")


def _fallback(scenario: AiScenarioConfig, error: str) -> AiScenarioResult:
    return AiScenarioResult(ok=False, fallback=scenario.fallback, error=error)


def _service_candidates_for_scenario(
    active_config: AiConfig,
    scenario: AiScenarioConfig,
) -> list[Any]:
    selected = active_config.services.get(scenario.service_id)
    candidates: list[Any] = []
    if selected is not None and _service_is_callable(selected):
        candidates.append(selected)
    for service in active_config.services.values():
        if service.id == getattr(selected, "id", ""):
            continue
        if service.protocol != "provider_login" or not _service_is_callable(service):
            continue
        candidates.append(service)
    return candidates


def _service_is_callable(service: Any) -> bool:
    if not getattr(service, "enabled", False):
        return False
    protocol = str(getattr(service, "protocol", "") or "").strip()
    if protocol == "provider_login":
        return bool(
            str(getattr(service, "owner_provider_id", "") or "").strip()
            and str(getattr(service, "completion_entrypoint", "") or "").strip()
        )
    if not str(getattr(service, "default_model", "") or "").strip():
        return False
    api_key = str(getattr(service, "api_key", "") or "").strip()
    api_key_env = str(getattr(service, "api_key_env", "") or "").strip()
    return bool(api_key or (api_key_env and os.environ.get(api_key_env, "").strip()))


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
    if protocol == "provider_login":
        owner_provider_id = str(getattr(service, "owner_provider_id", "") or "").strip()
        return f"provider-login://{owner_provider_id or 'unknown'}"
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
