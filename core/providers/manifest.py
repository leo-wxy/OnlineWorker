from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from core.providers.contracts import (
    ProviderCapabilities,
    ProviderHealthMetadata,
    ProviderManifestCapabilities,
    ProviderMetadata,
    ProviderProcessMetadata,
    ProviderTransportMetadata,
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def _str_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _string_tuple(value: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return default


def capabilities_from_manifest(raw: dict[str, Any] | None) -> ProviderManifestCapabilities:
    data = _mapping(raw)
    return ProviderManifestCapabilities(
        sessions=_bool_value(data.get("sessions")),
        send=_bool_value(data.get("send")),
        approvals=_bool_value(data.get("approvals")),
        questions=_bool_value(data.get("questions")),
        photos=_bool_value(data.get("photos")),
        files=_bool_value(data.get("files")),
        commands=_bool_value(data.get("commands")),
        command_wrappers=_string_tuple(data.get("command_wrappers")),
        control_modes=_string_tuple(data.get("control_modes"), ("app",)),
        message_rewrite=dict(_mapping(data.get("message_rewrite"))),
    )


def runtime_capabilities_from_manifest(
    capabilities: ProviderManifestCapabilities,
) -> ProviderCapabilities:
    return ProviderCapabilities(
        command_wrappers=capabilities.command_wrappers,
        control_modes=capabilities.control_modes,
    )


def metadata_from_provider_manifest(manifest: dict[str, Any]) -> ProviderMetadata:
    provider_id = _str_value(manifest.get("id")).strip()
    if not provider_id:
        raise ValueError("Provider plugin manifest missing id")

    provider = _mapping(manifest.get("provider"))
    transport = _mapping(provider.get("transport") or manifest.get("transport"))
    capabilities = capabilities_from_manifest(
        provider.get("capabilities") or manifest.get("capabilities")
    )
    process = _mapping(provider.get("process") or manifest.get("process"))
    health = _mapping(provider.get("health") or manifest.get("health"))

    owner_transport = _str_value(
        provider.get("owner_transport")
        or manifest.get("owner_transport")
        or transport.get("owner")
        or transport.get("type"),
        "stdio",
    )
    live_transport = _str_value(
        provider.get("live_transport")
        or manifest.get("live_transport")
        or transport.get("live")
        or owner_transport,
        owner_transport,
    )
    bin_value = _str_value(provider.get("bin") or manifest.get("bin") or provider_id)

    return ProviderMetadata(
        id=provider_id,
        runtime_id=_str_value(
            provider.get("runtime_id") or manifest.get("runtime_id") or provider_id
        ),
        label=_str_value(provider.get("label") or manifest.get("label") or provider_id),
        description=_str_value(
            provider.get("description") or manifest.get("description") or ""
        ),
        visible=_bool_value(
            provider.get("visible"),
            _bool_value(manifest.get("default_visible"), True),
        ),
        managed=_bool_value(provider.get("managed"), True),
        autostart=_bool_value(provider.get("autostart"), True),
        bin=bin_value,
        transport=ProviderTransportMetadata(
            owner=owner_transport,
            live=live_transport,
            type=_str_value(transport.get("type") or owner_transport),
            app_server_port=int(transport.get("app_server_port") or provider.get("app_server_port") or 0),
            app_server_url=_str_value(
                transport.get("app_server_url") or provider.get("app_server_url") or ""
            ),
        ),
        capabilities=capabilities,
        process=ProviderProcessMetadata(
            cleanup_matchers=_string_tuple(process.get("cleanup_matchers")),
        ),
        health=ProviderHealthMetadata(
            url=_str_value(health.get("url")),
        ),
    )


def metadata_from_builtin_provider_manifest(provider_file: str) -> ProviderMetadata:
    manifest_path = Path(provider_file).resolve().parents[1] / "plugin.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(manifest, dict):
        raise ValueError(f"Provider plugin manifest must be a mapping: {manifest_path}")
    return metadata_from_provider_manifest(manifest)
