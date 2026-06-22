from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.providers.contracts import ProviderDocumentNormalizationResult


def _migrate_legacy_ai_aliases(data: dict[str, Any]) -> bool:
    ai = data.get("ai")
    if not isinstance(ai, dict):
        return False

    changed = False
    services = ai.get("services")
    if isinstance(services, list):
        for item in services:
            if not isinstance(item, dict):
                continue
            service_id = str(item.get("id") or "").strip()
            if service_id == "claude_default":
                item["id"] = "anthropic_default"
                changed = True
            protocol = str(item.get("protocol") or "").strip()
            if protocol == "claude_messages":
                item["protocol"] = "anthropic_messages"
                changed = True
    elif isinstance(services, dict):
        if "claude_default" in services and "anthropic_default" not in services:
            services["anthropic_default"] = services.pop("claude_default")
            changed = True
        elif "claude_default" in services:
            services.pop("claude_default")
            changed = True
        service = services.get("anthropic_default")
        if isinstance(service, dict):
            protocol = str(service.get("protocol") or "").strip()
            if protocol == "claude_messages":
                service["protocol"] = "anthropic_messages"
                changed = True

    scenarios = ai.get("scenarios")
    if isinstance(scenarios, dict):
        for scenario in scenarios.values():
            if not isinstance(scenario, dict):
                continue
            service_id = str(scenario.get("service_id") or scenario.get("serviceId") or "").strip()
            if service_id == "claude_default":
                if "service_id" in scenario:
                    scenario["service_id"] = "anthropic_default"
                else:
                    scenario["serviceId"] = "anthropic_default"
                changed = True
    elif isinstance(scenarios, list):
        for scenario in scenarios:
            if not isinstance(scenario, dict):
                continue
            service_id = str(scenario.get("service_id") or scenario.get("serviceId") or "").strip()
            if service_id == "claude_default":
                if "service_id" in scenario:
                    scenario["service_id"] = "anthropic_default"
                else:
                    scenario["serviceId"] = "anthropic_default"
                changed = True

    return changed


def normalize_config_document(raw: dict[str, Any] | None) -> ProviderDocumentNormalizationResult:
    original = raw if isinstance(raw, dict) else {}
    normalized = deepcopy(original)
    changed = _migrate_legacy_ai_aliases(normalized)
    return ProviderDocumentNormalizationResult(document=normalized, persist=changed)
