from __future__ import annotations

import threading
import time
from typing import Any

from core.usage.contracts import UsageSummaryRequest
from core.usage.registry import resolve_usage_plugin


_CACHE_TTL_SECONDS = 30
_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_usage_cache() -> None:
    with _lock:
        _cache.clear()


def get_usage_source_summary(
    plugin_id: str,
    source_id: str,
    start_date: str,
    end_date: str,
    *,
    timezone: str = "local",
    force_refresh: bool = False,
) -> dict[str, Any]:
    descriptor = resolve_usage_plugin(plugin_id, source_id)
    identity = descriptor.runtime_identity()
    key = (plugin_id, source_id, start_date, end_date, timezone, identity)
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if not force_refresh and cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return dict(cached[1])

    summary = descriptor.get_summary(UsageSummaryRequest(
        plugin_id=plugin_id,
        source_id=source_id,
        start_date=str(start_date or "").strip(),
        end_date=str(end_date or "").strip(),
        timezone=str(timezone or "local").strip() or "local",
    ))
    if not isinstance(summary, dict):
        raise TypeError(f"Usage plugin '{plugin_id}' returned an invalid summary")
    normalized = {
        "pluginId": plugin_id,
        "sourceId": source_id,
        "days": list(summary.get("days") or []),
        "updatedAtEpoch": int(summary.get("updatedAtEpoch") or time.time()),
        "unsupportedReason": summary.get("unsupportedReason"),
    }
    if not normalized["unsupportedReason"]:
        with _lock:
            _cache[key] = (now, dict(normalized))
    return normalized
