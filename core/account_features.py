from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from core.providers.manifest import load_yaml_mapping
from core.providers.overlay import iter_overlay_manifest_paths


BUILTIN_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins" / "providers" / "builtin"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_FAILURES: list[dict[str, str]] = []
_BACKEND_ENTRIES: dict[str, Path] = {}
_BACKEND_MODULES: dict[str, str] = {}


@dataclass(frozen=True)
class AccountFeatureDescriptor:
    feature_id: str
    label: str
    frontend_entry: str
    backend_entry: str


class _FeatureError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _safe_feature_id(value: object) -> str:
    feature_id = value.strip() if isinstance(value, str) else ""
    if not _SAFE_ID.fullmatch(feature_id):
        raise _FeatureError("invalid_feature_id")
    return feature_id


def _safe_entry(plugin_dir: Path, value: object, *, require_file: bool = True) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    relative = Path(raw)
    if (
        not raw
        or relative.is_absolute()
        or "\\" in raw
        or ":" in raw
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _FeatureError("unsafe_entry_path")
    if not require_file:
        return relative.as_posix()
    try:
        resolved = (plugin_dir / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise _FeatureError("missing_entry") from exc
    if not resolved.is_file() or not resolved.is_relative_to(plugin_dir.resolve()):
        raise _FeatureError("unsafe_entry_path")
    return relative.as_posix()


def _account_declaration(manifest: dict) -> dict | None:
    features = manifest.get("features")
    if features is None:
        return None
    if not isinstance(features, dict):
        raise _FeatureError("invalid_manifest")
    account = features.get("account")
    if account is None:
        return None
    if not isinstance(account, dict):
        raise _FeatureError("invalid_manifest")
    return account


def _descriptor(manifest_path: Path, manifest: dict, account: dict) -> AccountFeatureDescriptor:
    feature_id = _safe_feature_id(account.get("feature_id"))
    plugin_dir = manifest_path.parent
    return AccountFeatureDescriptor(
        feature_id=feature_id,
        label=str(account.get("label") or manifest.get("label") or feature_id).strip() or feature_id,
        frontend_entry=_safe_entry(plugin_dir, account.get("frontend_entry"), require_file=False),
        backend_entry=_safe_entry(plugin_dir, account.get("backend_entry")),
    )


def _backend_module_name(manifest_path: Path, relative_entry: str) -> str:
    relative = Path(relative_entry)
    if relative.suffix != ".py":
        raise _FeatureError("invalid_manifest")
    module_parts = [manifest_path.parent.name, *relative.with_suffix("").parts]
    if not all(part.isidentifier() for part in module_parts):
        raise _FeatureError("invalid_manifest")
    return ".".join(("plugins", "providers", "builtin", *module_parts))


def _failure(feature_id: str, code: str) -> dict[str, str]:
    return {"featureId": feature_id if _SAFE_ID.fullmatch(feature_id) else "", "code": code}


def list_account_features(
    *,
    builtin_root: Path | None = None,
    overlay_spec: str | None = None,
) -> list[AccountFeatureDescriptor]:
    _FAILURES.clear()
    _BACKEND_ENTRIES.clear()
    _BACKEND_MODULES.clear()
    descriptors: list[AccountFeatureDescriptor] = []
    seen: set[str] = set()
    root = builtin_root or BUILTIN_PLUGIN_ROOT

    for manifest_path in sorted(root.glob("*/plugin.yaml")):
        feature_id = ""
        try:
            manifest = load_yaml_mapping(manifest_path)
            account = _account_declaration(manifest)
            if account is None or account.get("enabled") is not True:
                continue
            raw_id = account.get("feature_id")
            feature_id = raw_id.strip() if isinstance(raw_id, str) else ""
            descriptor = _descriptor(manifest_path, manifest, account)
            if descriptor.feature_id in seen:
                raise _FeatureError("duplicate_feature_id")
            backend_module = _backend_module_name(manifest_path, descriptor.backend_entry)
            seen.add(descriptor.feature_id)
            _BACKEND_ENTRIES[descriptor.feature_id] = (
                manifest_path.parent / descriptor.backend_entry
            ).resolve()
            _BACKEND_MODULES[descriptor.feature_id] = backend_module
            descriptors.append(descriptor)
        except _FeatureError as exc:
            _FAILURES.append(_failure(feature_id, exc.code))
        except Exception:
            _FAILURES.append(_failure(feature_id, "invalid_manifest"))

    overlay_paths = [] if overlay_spec == "" else iter_overlay_manifest_paths(overlay_spec)
    for manifest_path in overlay_paths:
        feature_id = ""
        try:
            account = _account_declaration(load_yaml_mapping(manifest_path))
            if account is None or account.get("enabled") is not True:
                continue
            raw_id = account.get("feature_id")
            feature_id = raw_id.strip() if isinstance(raw_id, str) else ""
            _safe_feature_id(feature_id)
            _FAILURES.append(_failure(feature_id, "unsupported_frontend_source"))
        except _FeatureError as exc:
            _FAILURES.append(_failure(feature_id, exc.code))
        except Exception:
            _FAILURES.append(_failure(feature_id, "invalid_manifest"))

    _FAILURES.sort(key=lambda item: (item["featureId"], item["code"]))
    return descriptors


def account_feature_load_failures() -> list[dict[str, str]]:
    return [dict(failure) for failure in _FAILURES]


def account_feature_backend_entry(feature_id: str) -> Path | None:
    return _BACKEND_ENTRIES.get(feature_id)


def account_feature_backend_module(feature_id: str) -> str | None:
    return _BACKEND_MODULES.get(feature_id)
