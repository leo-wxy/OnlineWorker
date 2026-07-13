from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

from core.providers.overlay import iter_overlay_manifest_paths, load_manifest as load_provider_manifest
from core.usage.contracts import UsagePluginDescriptor


USAGE_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "usage"
USAGE_OVERLAY_ENV = "ONLINEWORKER_USAGE_OVERLAY"
PROVIDER_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "providers"
logger = logging.getLogger(__name__)


def _manifest_paths() -> list[Path]:
    paths = sorted((USAGE_PLUGIN_ROOT / "builtin").glob("*/plugin.yaml"))
    overlay = str(os.environ.get(USAGE_OVERLAY_ENV) or "").strip()
    for raw_root in filter(None, overlay.split(os.pathsep)):
        root = Path(raw_root).expanduser()
        candidates = [root] if root.is_file() else sorted(root.rglob("plugin.yaml"))
        paths.extend(candidate for candidate in candidates if candidate.is_file())
    return paths


def load_usage_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or data.get("kind") != "usage":
        raise ValueError(f"Usage plugin manifest has unsupported kind: {path}")
    if not str(data.get("id") or "").strip():
        raise ValueError(f"Usage plugin manifest missing id: {path}")
    return data


def _load_descriptor(manifest: dict[str, Any], manifest_path: Path) -> UsagePluginDescriptor:
    entrypoint = str((manifest.get("entrypoints") or {}).get("python_descriptor") or "")
    module_name, separator, factory_name = entrypoint.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError(f"Usage plugin entrypoint must use module:function syntax: {entrypoint}")
    import_root = str(manifest_path.parent.parent)
    if import_root not in sys.path:
        sys.path.insert(0, import_root)
    descriptor = getattr(importlib.import_module(module_name), factory_name)()
    if not isinstance(descriptor, UsagePluginDescriptor):
        raise TypeError(f"Usage plugin entrypoint returned an invalid descriptor: {entrypoint}")
    if descriptor.plugin_id != str(manifest.get("id")):
        raise ValueError(f"Usage plugin descriptor id mismatch: {descriptor.plugin_id}")
    return descriptor


def load_usage_plugins() -> dict[str, tuple[dict[str, Any], UsagePluginDescriptor]]:
    plugins: dict[str, tuple[dict[str, Any], UsagePluginDescriptor]] = {}
    for path in _manifest_paths():
        manifest = load_usage_manifest(path)
        plugin_id = str(manifest["id"])
        plugins[plugin_id] = (manifest, _load_descriptor(manifest, path))
    return plugins


def _provider_usage_sources() -> dict[str, tuple[str, str]]:
    sources: dict[str, tuple[str, str]] = {}
    manifests = sorted((PROVIDER_PLUGIN_ROOT / "builtin").glob("*/plugin.yaml"))
    manifests.extend(iter_overlay_manifest_paths())
    for provider_manifest in manifests:
        try:
            provider_raw = load_provider_manifest(provider_manifest)
            provider_id = str(provider_raw.get("id") or "").strip()
            usage = (provider_raw.get("provider") or {}).get("usage") or {}
            plugin_id = str(usage.get("plugin_id") or "").strip()
            source_id = str(usage.get("source_id") or "").strip()
            if provider_id and plugin_id and source_id:
                sources[provider_id] = (plugin_id, source_id)
            elif provider_id:
                sources.pop(provider_id, None)
        except Exception:
            logger.exception(
                "Skipping provider usage association that failed to load: manifest=%s",
                provider_manifest,
            )
    return sources


def get_usage_source_catalog() -> list[dict[str, Any]]:
    associations = {
        source: provider_id
        for provider_id, source in _provider_usage_sources().items()
    }

    catalog: list[dict[str, Any]] = []
    for plugin_id, (manifest, _) in load_usage_plugins().items():
        for source in manifest.get("sources") or []:
            if not isinstance(source, dict) or not str(source.get("id") or "").strip():
                continue
            catalog.append({
                "pluginId": plugin_id,
                "sourceId": str(source["id"]),
                "label": str(source.get("label") or source["id"]),
                "description": str(source.get("description") or ""),
                "order": int(source.get("order") or 0),
                "icon": source.get("icon") or manifest.get("icon") or {},
                "providerId": associations.get((plugin_id, str(source["id"]))),
            })
    return sorted(catalog, key=lambda item: (item["order"], item["label"].lower()))


def resolve_usage_plugin(plugin_id: str, source_id: str) -> UsagePluginDescriptor:
    plugins = load_usage_plugins()
    if plugin_id not in plugins:
        raise ValueError(f"Usage plugin '{plugin_id}' not found")
    manifest, descriptor = plugins[plugin_id]
    source_ids = {str(item.get("id") or "") for item in manifest.get("sources") or [] if isinstance(item, dict)}
    if source_id not in source_ids:
        raise ValueError(f"Usage source '{plugin_id}/{source_id}' not found")
    return descriptor


def get_provider_usage_source(provider_id: str) -> tuple[str, str] | None:
    return _provider_usage_sources().get(str(provider_id or "").strip())
