from __future__ import annotations

import time
from typing import Any

from core.providers.overlay import load_manifest
from core.providers.registry import (
    _iter_provider_plugin_manifests,
    _load_descriptor_from_entrypoint,
    get_provider,
)


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(primary: Any, fallback: Any) -> Any:
    return primary if primary is not None else fallback


def _unix_time_seconds() -> int:
    return int(time.time())


def _normalize_usage_day(day: Any) -> dict[str, Any] | None:
    if not isinstance(day, dict):
        return None
    date = str(day.get("date") or "").strip()
    if not date:
        return None

    return {
        "date": date,
        "inputTokens": _int_value(
            _first_present(day.get("inputTokens"), day.get("input_tokens"))
        ),
        "outputTokens": _int_value(
            _first_present(day.get("outputTokens"), day.get("output_tokens"))
        ),
        "cacheCreationTokens": _int_value(
            _first_present(
                _first_present(day.get("cacheCreationTokens"), day.get("cache_creation_tokens")),
                _first_present(
                    day.get("cacheCreationInputTokens"),
                    day.get("cache_creation_input_tokens"),
                ),
            )
        ),
        "cacheReadTokens": _int_value(
            _first_present(
                _first_present(day.get("cacheReadTokens"), day.get("cache_read_tokens")),
                _first_present(day.get("cacheReadInputTokens"), day.get("cache_read_input_tokens")),
            )
        ),
        "totalTokens": _int_value(
            _first_present(day.get("totalTokens"), day.get("total_tokens"))
        ),
        "totalCostUsd": _float_or_none(
            _first_present(day.get("totalCostUsd"), day.get("total_cost_usd"))
        ),
    }


def _normalize_usage_summary(provider_id: str, raw_summary: Any) -> dict[str, Any]:
    raw = raw_summary if isinstance(raw_summary, dict) else {}
    days = [
        normalized
        for normalized in (
            _normalize_usage_day(day)
            for day in (raw.get("days") if isinstance(raw.get("days"), list) else [])
        )
        if normalized is not None
    ]
    days.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return {
        "providerId": str(raw.get("providerId") or raw.get("provider_id") or provider_id),
        "days": days,
        "updatedAtEpoch": _int_value(
            _first_present(raw.get("updatedAtEpoch"), raw.get("updated_at_epoch"))
            if _first_present(raw.get("updatedAtEpoch"), raw.get("updated_at_epoch")) is not None
            else _unix_time_seconds()
        ),
        "unsupportedReason": raw.get("unsupportedReason") or raw.get("unsupported_reason"),
    }


def _load_provider_descriptor(provider_id: str):
    normalized_provider_id = str(provider_id or "").strip()
    if not normalized_provider_id:
        raise ValueError("provider_id is required")

    registry_descriptor = get_provider(normalized_provider_id)
    if registry_descriptor is not None:
        return registry_descriptor

    for manifest_path in _iter_provider_plugin_manifests():
        manifest = load_manifest(manifest_path)
        manifest_id = str(manifest.get("id") or "").strip()
        if manifest_id != normalized_provider_id:
            continue
        entrypoint = str((manifest.get("entrypoints") or {}).get("python_descriptor") or "").strip()
        return _load_descriptor_from_entrypoint(entrypoint, manifest_path=manifest_path)

    raise ValueError(f"Provider '{normalized_provider_id}' manifest not found")


def get_provider_usage_summary(
    provider_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    descriptor = _load_provider_descriptor(provider_id)
    usage_hooks = getattr(descriptor, "usage_hooks", None)
    get_summary = getattr(usage_hooks, "get_summary", None)
    if not callable(get_summary):
        raise ValueError(f"Provider '{provider_id}' does not expose usage hooks")

    raw_summary = get_summary(
        str(start_date or "").strip(),
        str(end_date or "").strip(),
    )
    return _normalize_usage_summary(provider_id, raw_summary)
