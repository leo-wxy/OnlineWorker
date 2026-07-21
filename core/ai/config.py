from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from core.providers.manifest import ai_services_from_manifest
from core.providers.overlay import iter_overlay_manifest_paths

from .contracts import AiConfig, AiScenarioConfig, AiServiceConfig


LEGACY_NOTIFICATION_SUMMARY_PROMPT = """You summarize OnlineWorker task completion notifications.
Return compact JSON with preview_title and summary.
preview_title identifies the completed task.
summary explains the completed result.

Current task:
{{task_summary}}

Final assistant message:
{{final_message}}
"""


DEFAULT_NOTIFICATION_SUMMARY_PROMPT = """You summarize OnlineWorker task completion notifications.
Return JSON only, without markdown:
{"preview_title": "...", "summary": "..."}

Rules:
- preview_title must be a complete short Chinese title, ideally 6 to 12 Chinese characters.
- Avoid English in preview_title unless it is a product or provider name.
- Do not return truncated words, ellipsis, code fences, or punctuation-only titles.
- summary must be one concise Chinese sentence describing what was completed.

Current task:
{{task_summary}}

Final assistant message:
{{final_message}}
"""

def positive_int_value(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_ai_service_id(service_id: Any) -> str:
    return str(service_id or "").strip()


def normalize_ai_protocol(protocol: Any, default: str = "openai_compatible_chat") -> str:
    return str(protocol or default).strip()


def build_ai_service_config(service_id: str, raw: dict[str, Any] | None) -> AiServiceConfig:
    raw = raw if isinstance(raw, dict) else {}
    normalized_service_id = normalize_ai_service_id(service_id)
    raw_models = raw.get("models") if isinstance(raw.get("models"), list) else []
    models = tuple(str(model or "").strip() for model in raw_models if str(model or "").strip())
    protocol = normalize_ai_protocol(raw.get("protocol"))
    return AiServiceConfig(
        id=normalized_service_id,
        name=str(raw.get("name") or normalized_service_id),
        protocol=protocol,
        base_url=str(raw.get("base_url") or raw.get("baseUrl") or ""),
        endpoint=str(raw.get("endpoint") or ""),
        api_key=str(raw.get("api_key") or raw.get("apiKey") or ""),
        api_key_env=str(raw.get("api_key_env") or raw.get("apiKeyEnv") or ""),
        models=models,
        default_model=str(raw.get("default_model") or raw.get("defaultModel") or ""),
        timeout_seconds=positive_int_value(raw.get("timeout_seconds", raw.get("timeoutSeconds")), 20),
        enabled=bool(raw.get("enabled", True)),
    )


@lru_cache(maxsize=1)
def _builtin_ai_service_snapshot() -> tuple[dict[str, Any], ...]:
    plugin_root = Path(__file__).resolve().parents[2] / "plugins" / "providers" / "builtin"
    services: list[dict[str, Any]] = []
    manifest_paths = sorted(plugin_root.glob("*/plugin.yaml")) if plugin_root.exists() else []
    manifest_paths.extend(iter_overlay_manifest_paths())
    if not manifest_paths:
        return ()
    for manifest_path in manifest_paths:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(manifest, dict) or manifest.get("kind") != "provider":
            continue
        services.extend(ai_services_from_manifest(manifest))
    return tuple(services)


def builtin_ai_service_raws() -> list[dict[str, Any]]:
    return deepcopy(list(_builtin_ai_service_snapshot()))


def clear_ai_manifest_cache() -> None:
    _builtin_ai_service_snapshot.cache_clear()


def build_ai_scenario_config(
    scenario_id: str,
    raw: dict[str, Any] | None,
) -> AiScenarioConfig:
    raw = raw if isinstance(raw, dict) else {}
    limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    default_limits = (
        {"preview_title": 16}
        if scenario_id == "notification_summary"
        else {}
    )
    default_prompt = (
        DEFAULT_NOTIFICATION_SUMMARY_PROMPT
        if scenario_id == "notification_summary"
        else ""
    )
    default_fallback = (
        "local_notification_summary_rules"
        if scenario_id == "notification_summary"
        else ""
    )
    default_schema = (
        "notification_summary_v1"
        if scenario_id == "notification_summary"
        else "text"
    )
    prompt_template = str(raw.get("prompt_template") or raw.get("promptTemplate") or default_prompt)
    if scenario_id == "notification_summary" and prompt_template == LEGACY_NOTIFICATION_SUMMARY_PROMPT:
        prompt_template = DEFAULT_NOTIFICATION_SUMMARY_PROMPT
    return AiScenarioConfig(
        id=scenario_id,
        enabled=bool(raw.get("enabled", False)),
        service_id=str(raw.get("service_id") or raw.get("serviceId") or ""),
        model=str(raw.get("model") or ""),
        output_schema=str(raw.get("output_schema") or raw.get("outputSchema") or default_schema),
        fallback=str(raw.get("fallback") or default_fallback),
        limits={
            str(key): positive_int_value(value, 0)
            for key, value in {**default_limits, **limits}.items()
            if str(key or "").strip()
        },
        prompt_template=prompt_template,
    )


def iter_ai_service_raws(raw_services: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw_services, dict):
        entries: list[tuple[str, dict[str, Any]]] = []
        for service_id, service_raw in raw_services.items():
            normalized_id = normalize_ai_service_id(service_id)
            if normalized_id:
                entries.append(
                    (normalized_id, service_raw if isinstance(service_raw, dict) else {})
                )
        return entries
    if isinstance(raw_services, list):
        entries: list[tuple[str, dict[str, Any]]] = []
        for item in raw_services:
            if not isinstance(item, dict):
                continue
            service_id = normalize_ai_service_id(item.get("id"))
            if service_id:
                entries.append((service_id, item))
        return entries
    return []


def iter_ai_scenario_raws(raw_scenarios: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw_scenarios, dict):
        return [
            (str(scenario_id or "").strip(), scenario_raw if isinstance(scenario_raw, dict) else {})
            for scenario_id, scenario_raw in raw_scenarios.items()
            if str(scenario_id or "").strip()
        ]
    if isinstance(raw_scenarios, list):
        entries: list[tuple[str, dict[str, Any]]] = []
        for item in raw_scenarios:
            if not isinstance(item, dict):
                continue
            scenario_id = str(item.get("id") or "").strip()
            if scenario_id:
                entries.append((scenario_id, item))
        return entries
    return []


def load_ai_config(data: dict[str, Any]) -> AiConfig:
    raw = data.get("ai") if isinstance(data, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    services: dict[str, AiServiceConfig] = {
        service_id: build_ai_service_config(service_id, service_raw)
        for service_id, service_raw in iter_ai_service_raws(raw.get("services"))
    }
    builtin_services = builtin_ai_service_raws()
    for builtin in builtin_services:
        builtin_service_id = normalize_ai_service_id(builtin.get("id"))
        if builtin_service_id and builtin_service_id not in services:
            services[builtin_service_id] = build_ai_service_config(
                builtin_service_id,
                builtin,
            )
    scenarios = {
        scenario_id: build_ai_scenario_config(scenario_id, scenario_raw)
        for scenario_id, scenario_raw in iter_ai_scenario_raws(raw.get("scenarios"))
    }
    if "notification_summary" not in scenarios:
        scenarios["notification_summary"] = build_ai_scenario_config("notification_summary", None)
    fallback_service_id = next(
        (
            normalize_ai_service_id(service.get("id"))
            for service in builtin_services
            if bool(service.get("default_for_scenarios"))
            and normalize_ai_service_id(service.get("id")) in services
        ),
        next(iter(services), ""),
    )
    if fallback_service_id:
        scenarios = {
            scenario_id: (
                scenario
                if scenario.service_id in services
                else AiScenarioConfig(
                    id=scenario.id,
                    enabled=scenario.enabled,
                    service_id=fallback_service_id,
                    model=scenario.model,
                    output_schema=scenario.output_schema,
                    fallback=scenario.fallback,
                    limits=scenario.limits,
                    prompt_template=scenario.prompt_template,
                )
            )
            for scenario_id, scenario in scenarios.items()
        }
    return AiConfig(services=services, scenarios=scenarios)
