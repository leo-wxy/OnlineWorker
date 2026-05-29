from __future__ import annotations

import logging
import re
from typing import Any

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
            "[ai] scenario failed scenario=%s service=%s error=%s",
            scenario.id,
            service.id,
            exc,
        )
        return _fallback(scenario, "client_error")

    data = _parse_json_object(response.text)
    if not _validate_schema(scenario, data):
        return _fallback(scenario, "invalid_output")
    data = _apply_limits(scenario, data)
    return AiScenarioResult(ok=True, data=data)


def _fallback(scenario: AiScenarioConfig, error: str) -> AiScenarioResult:
    return AiScenarioResult(ok=False, fallback=scenario.fallback, error=error)


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
