from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


PROVIDER_OVERLAY_ENV = "ONLINEWORKER_PROVIDER_OVERLAY"


def _split_overlay_spec(overlay_spec: str | None) -> list[Path]:
    raw = str(overlay_spec or os.environ.get(PROVIDER_OVERLAY_ENV) or "").strip()
    if not raw:
        return []
    paths: list[Path] = []
    for token in raw.split(os.pathsep):
        token = token.strip()
        if not token:
            continue
        paths.append(Path(os.path.expanduser(token)))
    return paths


def _iter_manifest_paths_from_dir(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    manifests: list[Path] = []
    for path in sorted(root.rglob("plugin.yaml")):
        if path.is_file():
            manifests.append(path)
    return manifests


def _is_provider_manifest(path: Path) -> bool:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return isinstance(data, dict) and data.get("kind") == "provider"


def iter_overlay_manifest_paths(overlay_spec: str | None = None) -> list[Path]:
    manifests: list[Path] = []
    seen: set[Path] = set()
    for path in _split_overlay_spec(overlay_spec):
        candidates: list[Path]
        if path.is_file():
            candidates = [path] if _is_provider_manifest(path) else []
        else:
            candidates = _iter_manifest_paths_from_dir(path)
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            manifests.append(candidate)
    return manifests


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Provider plugin manifest must be a mapping: {path}")
    if data.get("kind") != "provider":
        raise ValueError(f"Provider plugin manifest has unsupported kind: {path}")
    return data


def manifest_to_provider_raw(manifest: dict[str, Any]) -> dict[str, Any]:
    provider_raw = manifest.get("provider")
    if not isinstance(provider_raw, dict):
        provider_raw = {}

    capabilities = provider_raw.get("capabilities") or manifest.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        capabilities = {}
    process = provider_raw.get("process") or manifest.get("process") or {}
    if not isinstance(process, dict):
        process = {}
    health = provider_raw.get("health") or manifest.get("health") or {}
    if not isinstance(health, dict):
        health = {}
    auth = provider_raw.get("auth") or manifest.get("auth") or {}
    if not isinstance(auth, dict):
        auth = {}

    transport = provider_raw.get("transport") or manifest.get("transport") or {}
    if not isinstance(transport, dict):
        transport = {}

    provider_id = str(manifest.get("id") or "").strip()
    bin_value = provider_raw.get("bin") or manifest.get("bin") or provider_id
    return {
        "visible": bool(provider_raw.get("visible", manifest.get("default_visible", True))),
        "runtime_id": str(provider_raw.get("runtime_id") or manifest.get("runtime_id") or provider_id),
        "label": str(provider_raw.get("label") or manifest.get("label") or provider_id),
        "description": str(provider_raw.get("description") or manifest.get("description") or ""),
        "managed": bool(provider_raw.get("managed", True)),
        "autostart": bool(provider_raw.get("autostart", True)),
        "codex_bin": str(bin_value),
        "protocol": str(
            provider_raw.get("owner_transport")
            or manifest.get("owner_transport")
            or transport.get("owner")
            or transport.get("type")
            or "ws"
        ),
        "app_server_port": int(transport.get("app_server_port") or provider_raw.get("app_server_port") or 0),
        "app_server_url": str(transport.get("app_server_url") or provider_raw.get("app_server_url") or ""),
        "control_mode": str(provider_raw.get("control_mode") or manifest.get("control_mode") or "app"),
        "capabilities": capabilities,
        "process": process,
        "health": health,
        "auth": auth,
    }


def load_overlay_provider_raws(overlay_spec: str | None = None) -> dict[str, dict[str, Any]]:
    provider_raws: dict[str, dict[str, Any]] = {}
    for manifest_path in iter_overlay_manifest_paths(overlay_spec):
        manifest = load_manifest(manifest_path)
        provider_id = str(manifest.get("id") or "").strip()
        if not provider_id:
            raise ValueError(f"Provider plugin manifest missing id: {manifest_path}")
        provider_raws[provider_id] = manifest_to_provider_raw(manifest)
    return provider_raws
