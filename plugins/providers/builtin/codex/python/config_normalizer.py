from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.providers.contracts import ProviderConfigNormalizationResult


def _normalize_transport_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"stdio", "ws", "unix", "http"}:
        return normalized
    return ""


def _normalize_live_transport_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"owner_bridge", "shared_ws", "shared_unix", "stdio", "ws", "unix", "http"}:
        return normalized
    return ""


def _infer_transport_from_url(url: Any) -> str:
    normalized = str(url or "").strip()
    if normalized.startswith(("ws://", "wss://")):
        return "ws"
    if normalized.startswith("unix://"):
        return "unix"
    if normalized.startswith(("http://", "https://")):
        return "http"
    return ""


def _shared_live_transport(owner_transport: str, control_mode: str) -> str:
    if owner_transport == "ws" and control_mode in {"app", "hybrid"}:
        return "shared_ws"
    if owner_transport == "unix" and control_mode in {"app", "hybrid"}:
        return "shared_unix"
    if owner_transport == "stdio":
        return "owner_bridge"
    return ""


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def normalize_provider_config(
    raw: dict[str, Any] | None,
    *,
    defaults: dict[str, Any],
    legacy: bool,
) -> ProviderConfigNormalizationResult:
    original = raw if isinstance(raw, dict) else {}
    normalized = deepcopy(original)

    legacy_bin = str(normalized.pop("codex_bin", "") or "").strip()
    if legacy_bin and not str(normalized.get("bin") or "").strip():
        normalized["bin"] = legacy_bin

    transport = normalized.get("transport")
    if not isinstance(transport, dict):
        transport = {}
    else:
        transport = deepcopy(transport)
    if transport:
        normalized["transport"] = transport

    explicit_control_mode = str(normalized.get("control_mode") or "").strip()
    explicit_protocol = _normalize_transport_name(
        normalized.get("owner_transport")
        or transport.get("owner")
        or transport.get("type")
        or normalized.get("protocol")
    )
    app_server_url = str(
        transport.get("app_server_url")
        or transport.get("url")
        or normalized.get("app_server_url")
        or ""
    ).strip()
    raw_port = _int_value(
        transport.get("app_server_port", normalized.get("app_server_port"))
    )

    owner_transport = explicit_protocol or _infer_transport_from_url(app_server_url)
    if legacy and not owner_transport and raw_port > 0:
        owner_transport = "ws"
    if not owner_transport:
        owner_transport = _normalize_transport_name(defaults.get("protocol")) or "unix"

    migrated_stdio_default = False
    if legacy:
        if explicit_protocol == "ws" and raw_port == 4722 and not app_server_url and not explicit_control_mode:
            owner_transport = "unix"
            migrated_stdio_default = True
        elif owner_transport == "stdio" and not app_server_url:
            owner_transport = "unix"
            migrated_stdio_default = True
    elif owner_transport == "stdio" and not app_server_url:
        owner_transport = "unix"
        migrated_stdio_default = True

    control_mode = explicit_control_mode or ("app" if owner_transport in {"ws", "unix"} else "app")
    explicit_live_transport = _normalize_live_transport_name(
        normalized.get("live_transport") or transport.get("live")
    )
    if migrated_stdio_default and explicit_live_transport in {"stdio", "owner_bridge"}:
        explicit_live_transport = ""
    live_transport = explicit_live_transport or _shared_live_transport(owner_transport, control_mode)

    if legacy:
        normalized["protocol"] = owner_transport
        normalized["control_mode"] = control_mode
        if live_transport:
            normalized["live_transport"] = live_transport
        if owner_transport == "stdio":
            normalized["app_server_port"] = 0
            normalized["app_server_url"] = ""
        elif owner_transport == "unix":
            normalized["app_server_port"] = 0
    else:
        normalized["owner_transport"] = owner_transport
        normalized["control_mode"] = control_mode
        if live_transport:
            normalized["live_transport"] = live_transport
            transport["live"] = live_transport
        transport["type"] = owner_transport
        if owner_transport == "stdio":
            transport.pop("app_server_port", None)
            transport.pop("app_server_url", None)
            transport.pop("url", None)
        elif owner_transport == "unix":
            transport.pop("app_server_port", None)
        if transport:
            normalized["transport"] = transport

    return ProviderConfigNormalizationResult(
        raw=normalized,
        persist=not legacy and normalized != original,
    )
