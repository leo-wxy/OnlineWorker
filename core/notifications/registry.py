from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


NOTIFICATION_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "notifications"
NOTIFICATION_PLUGIN_GROUPS = ("builtin",)
NOTIFICATION_OVERLAY_ENV = "ONLINEWORKER_NOTIFICATION_OVERLAY"


@dataclass(frozen=True)
class NotificationPluginDescriptor:
    name: str
    label: str = ""
    default_enabled: bool = True
    channel_factory: Callable[..., Any] | None = None
    settings_fields: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        name = str(self.name or "").strip()
        if not name:
            raise ValueError("Notification plugin descriptor name is required")
        object.__setattr__(self, "name", name)
        if not self.label:
            object.__setattr__(self, "label", name)
        object.__setattr__(self, "settings_fields", tuple(self.settings_fields or ()))


def iter_builtin_notification_manifest_paths() -> list[Path]:
    manifests: list[Path] = []
    for group in NOTIFICATION_PLUGIN_GROUPS:
        group_dir = NOTIFICATION_PLUGIN_ROOT / group
        if not group_dir.exists():
            continue
        manifests.extend(sorted(group_dir.glob("*/plugin.yaml")))
    return manifests


def iter_notification_manifest_paths(root_dirs: Iterable[str | Path]) -> list[Path]:
    manifests: list[Path] = []
    seen: set[Path] = set()
    for root in root_dirs:
        root_path = Path(root).expanduser()
        candidates = [root_path] if root_path.is_file() else sorted(root_path.rglob("plugin.yaml"))
        for candidate in candidates:
            if not candidate.is_file() or not _is_notification_manifest(candidate):
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            manifests.append(candidate)
    return manifests


def iter_overlay_notification_manifest_paths(overlay_spec: str | None = None) -> list[Path]:
    raw = str(overlay_spec or os.environ.get(NOTIFICATION_OVERLAY_ENV) or "").strip()
    if not raw:
        return []
    roots = [token for token in raw.split(os.pathsep) if token.strip()]
    return iter_notification_manifest_paths(roots)


def _load_notification_plugins(
    root_dirs: Iterable[str | Path] | None = None,
) -> dict[str, NotificationPluginDescriptor]:
    descriptors = _load_bundled_notification_descriptors()
    manifest_paths = list(iter_builtin_notification_manifest_paths())
    manifest_paths.extend(
        iter_notification_manifest_paths(root_dirs)
        if root_dirs is not None
        else iter_overlay_notification_manifest_paths()
    )

    for manifest_path in manifest_paths:
        manifest = load_notification_manifest(manifest_path)
        descriptor = _load_descriptor_from_manifest(manifest, manifest_path=manifest_path)
        manifest_id = str(manifest.get("id") or "").strip()
        if not manifest_id:
            raise ValueError(f"Notification plugin manifest missing id: {manifest_path}")
        if descriptor.name != manifest_id:
            raise ValueError(
                f"Notification plugin descriptor name mismatch for {manifest_path}: "
                f"{descriptor.name!r} != {manifest_id!r}"
            )
        descriptor = _merge_manifest_settings(descriptor, manifest)
        descriptors[descriptor.name] = descriptor
    return descriptors


@lru_cache(maxsize=1)
def _notification_plugin_snapshot() -> dict[str, NotificationPluginDescriptor]:
    return _load_notification_plugins()


def load_notification_plugins(
    root_dirs: Iterable[str | Path] | None = None,
) -> dict[str, NotificationPluginDescriptor]:
    if root_dirs is not None:
        return _load_notification_plugins(root_dirs)
    return deepcopy(_notification_plugin_snapshot())


def clear_notification_registry_cache() -> None:
    _notification_plugin_snapshot.cache_clear()


def _load_bundled_notification_descriptors() -> dict[str, NotificationPluginDescriptor]:
    from plugins.notifications.catalog import iter_bundled_notification_factories

    descriptors: dict[str, NotificationPluginDescriptor] = {}
    for factory in iter_bundled_notification_factories():
        descriptor = factory()
        if descriptor.name in descriptors:
            raise ValueError(f"Duplicate bundled notification descriptor: {descriptor.name}")
        descriptors[descriptor.name] = descriptor
    return descriptors


def load_notification_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Notification plugin manifest must be a mapping: {path}")
    if data.get("kind") != "notification":
        raise ValueError(f"Notification plugin manifest has unsupported kind: {path}")
    return data


def _is_notification_manifest(path: Path) -> bool:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return isinstance(data, dict) and data.get("kind") == "notification"


def _load_descriptor_from_manifest(
    manifest: dict[str, Any],
    *,
    manifest_path: Path,
) -> NotificationPluginDescriptor:
    entrypoint = (manifest.get("entrypoints") or {}).get("python_descriptor")
    module_name, separator, factory_name = str(entrypoint or "").partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError(f"Notification plugin entrypoint must use module:function syntax: {entrypoint}")

    _ensure_manifest_import_path(manifest_path)
    module = importlib.import_module(module_name)
    factory = getattr(module, factory_name)
    descriptor = factory()
    if not isinstance(descriptor, NotificationPluginDescriptor):
        raise TypeError(f"Notification plugin entrypoint did not return NotificationPluginDescriptor: {entrypoint}")
    return descriptor


def _merge_manifest_settings(
    descriptor: NotificationPluginDescriptor,
    manifest: dict[str, Any],
) -> NotificationPluginDescriptor:
    settings = manifest.get("settings") if isinstance(manifest.get("settings"), dict) else {}
    fields = settings.get("fields") if isinstance(settings, dict) else []
    if not isinstance(fields, list):
        fields = []
    normalized_fields = tuple(
        field for field in (_normalize_settings_field(item) for item in fields)
        if field is not None
    )
    if not normalized_fields:
        return descriptor
    return NotificationPluginDescriptor(
        name=descriptor.name,
        label=descriptor.label,
        default_enabled=descriptor.default_enabled,
        channel_factory=descriptor.channel_factory,
        settings_fields=normalized_fields,
    )


def _normalize_settings_field(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    if not key:
        return None
    field_type = str(raw.get("type") or "string").strip()
    if field_type not in {"string", "number", "boolean", "select", "secret"}:
        field_type = "string"
    options = raw.get("options") if isinstance(raw.get("options"), list) else []
    return {
        "key": key,
        "label": str(raw.get("label") or key).strip(),
        "type": field_type,
        "required": bool(raw.get("required", False)),
        "default": raw.get("default"),
        "description": str(raw.get("description") or "").strip(),
        "options": [
            {
                "value": str(option.get("value") or "").strip(),
                "label": str(option.get("label") or option.get("value") or "").strip(),
            }
            for option in options
            if isinstance(option, dict) and str(option.get("value") or "").strip()
        ],
    }


def _ensure_manifest_import_path(manifest_path: Path) -> None:
    import_root = manifest_path.parent.parent
    import_root_str = str(import_root)
    if import_root_str not in sys.path:
        sys.path.insert(0, import_root_str)
