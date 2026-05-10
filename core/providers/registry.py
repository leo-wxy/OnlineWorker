from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Literal, Optional

from core.providers.contracts import ProviderDescriptor
from core.providers.overlay import iter_overlay_manifest_paths, load_manifest


PROVIDER_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "providers"
PROVIDER_PLUGIN_GROUPS = ("builtin",)


def _iter_provider_plugin_manifests() -> list[Path]:
    manifests: list[Path] = []
    for group in PROVIDER_PLUGIN_GROUPS:
        group_dir = PROVIDER_PLUGIN_ROOT / group
        if not group_dir.exists():
            continue
        manifests.extend(sorted(group_dir.glob("*/plugin.yaml")))
    manifests.extend(iter_overlay_manifest_paths())
    return manifests


def _ensure_manifest_import_path(manifest_path: Path) -> None:
    overlay_root = manifest_path.parent.parent
    overlay_root_str = str(overlay_root)
    if overlay_root_str not in sys.path:
        sys.path.insert(0, overlay_root_str)


def _load_descriptor_from_entrypoint(entrypoint: str, *, manifest_path: Path) -> ProviderDescriptor:
    module_name, separator, factory_name = str(entrypoint or "").partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError(f"Provider plugin entrypoint must use module:function syntax: {entrypoint}")

    _ensure_manifest_import_path(manifest_path)
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    descriptor = factory()
    if not isinstance(descriptor, ProviderDescriptor):
        raise TypeError(f"Provider plugin entrypoint did not return ProviderDescriptor: {entrypoint}")
    return descriptor


def _load_provider_descriptors() -> dict[str, ProviderDescriptor]:
    providers: dict[str, ProviderDescriptor] = _load_bundled_provider_descriptors()
    manifest_paths = _iter_provider_plugin_manifests()
    if not manifest_paths:
        return providers

    for manifest_path in manifest_paths:
        manifest = load_manifest(manifest_path)
        entrypoint = (manifest.get("entrypoints") or {}).get("python_descriptor")
        descriptor = _load_descriptor_from_entrypoint(entrypoint, manifest_path=manifest_path)
        manifest_id = str(manifest.get("id") or "").strip()
        if not manifest_id:
            raise ValueError(f"Provider plugin manifest missing id: {manifest_path}")
        if descriptor.name != manifest_id:
            raise ValueError(
                f"Provider plugin descriptor name mismatch for {manifest_path}: "
                f"{descriptor.name!r} != {manifest_id!r}"
            )
        providers[descriptor.name] = descriptor
    return providers


def _load_bundled_provider_descriptors() -> dict[str, ProviderDescriptor]:
    from plugins.providers.catalog import iter_bundled_provider_factories

    providers: dict[str, ProviderDescriptor] = {}
    for factory in iter_bundled_provider_factories():
        descriptor = factory()
        if descriptor.name in providers:
            raise ValueError(f"Duplicate bundled provider descriptor: {descriptor.name}")
        providers[descriptor.name] = descriptor
    return providers


_PROVIDERS: dict[str, ProviderDescriptor] = _load_provider_descriptors()


ProviderClassification = Literal[
    "available",
    "disabled_provider",
    "hidden_provider",
    "unknown_provider",
]


def _runtime_enabled(provider_config) -> bool:
    if provider_config is None:
        return False
    if hasattr(provider_config, "enabled"):
        return bool(getattr(provider_config, "enabled"))
    if hasattr(provider_config, "managed"):
        return bool(getattr(provider_config, "managed"))
    return False


def _runtime_visible(provider_config, descriptor: ProviderDescriptor | None) -> bool:
    if provider_config is not None and hasattr(provider_config, "visible"):
        return bool(getattr(provider_config, "visible"))
    metadata = descriptor.metadata if descriptor is not None else None
    return bool(metadata.visible) if metadata is not None else True


def classify_provider(name: str, config=None) -> ProviderClassification:
    provider_id = str(name or "").strip()
    if not provider_id:
        return "unknown_provider"

    descriptor = _PROVIDERS.get(provider_id)
    config_provider = None
    if config is not None:
        providers = getattr(config, "providers", {}) or {}
        if isinstance(providers, dict):
            config_provider = providers.get(provider_id)
        if descriptor is None:
            return "unknown_provider"
        if config_provider is None:
            return "disabled_provider"
        if not _runtime_enabled(config_provider):
            return "disabled_provider"
        if not _runtime_visible(config_provider, descriptor):
            return "hidden_provider"
        return "available"

    if descriptor is None:
        return "unknown_provider"
    metadata = descriptor.metadata
    if metadata is not None and not metadata.managed:
        return "disabled_provider"
    if metadata is not None and not metadata.visible:
        return "hidden_provider"
    return "available"


def provider_not_enabled_message(name: str, classification: ProviderClassification | str | None = None) -> str:
    provider_id = str(name or "").strip() or "unknown"
    suffix = ""
    if classification:
        suffix = f" ({classification})"
    return f"Provider '{provider_id}' is not enabled{suffix}"


def get_provider(name: str, config=None) -> Optional[ProviderDescriptor]:
    provider_id = str(name or "").strip()
    descriptor = _PROVIDERS.get(provider_id)
    if config is None:
        return descriptor
    classification = classify_provider(provider_id, config)
    if classification in {"available", "hidden_provider"}:
        return descriptor
    return None


def list_providers() -> list[ProviderDescriptor]:
    return list(_PROVIDERS.values())


def provider_supports_command_wrapper(name: str, command_name: str) -> bool:
    provider = get_provider(name)
    if provider is None:
        return False
    wrappers = getattr(provider.capabilities, "command_wrappers", ())
    normalized = str(command_name or "").strip().lower()
    return normalized in {str(item).strip().lower() for item in wrappers}


def list_providers_supporting_command_wrapper(command_name: str) -> list[str]:
    normalized = str(command_name or "").strip().lower()
    if not normalized:
        return []
    supported: list[str] = []
    for provider in list_providers():
        wrappers = getattr(provider.capabilities, "command_wrappers", ())
        if normalized in {str(item).strip().lower() for item in wrappers}:
            supported.append(provider.name)
    return supported
