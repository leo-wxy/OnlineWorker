from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import yaml


def _write_feature(
    root: Path,
    plugin_id: str,
    *,
    feature_id: str | None = None,
    enabled: object = True,
    frontend_entry: str = "frontend/account-entry.tsx",
    backend_entry: str = "python/account_feature.py",
    extra: dict[str, object] | None = None,
) -> Path:
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    for relative in (frontend_entry, backend_entry):
        path = plugin_dir / relative
        if ".." not in Path(relative).parts and not Path(relative).is_absolute():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture", encoding="utf-8")
    account = {
        "enabled": enabled,
        "feature_id": feature_id or f"{plugin_id}-accounts",
        "label": f"{plugin_id} Accounts",
        "frontend_entry": frontend_entry,
        "backend_entry": backend_entry,
        **(extra or {}),
    }
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump({"id": plugin_id, "kind": "provider", "features": {"account": account}}),
        encoding="utf-8",
    )
    return plugin_dir


def test_discovers_only_enabled_builtin_metadata_without_secret_fields(tmp_path):
    from core.account_features import account_feature_load_failures, list_account_features

    builtin = tmp_path / "builtin"
    _write_feature(builtin, "valid", extra={"credential": "credential-fixture", "payload": {"session": "hidden"}})
    _write_feature(builtin, "disabled", enabled=False)
    _write_feature(builtin, "string-disabled", enabled="true")

    features = list_account_features(builtin_root=builtin, overlay_spec="")

    assert [asdict(feature) for feature in features] == [
        {
            "feature_id": "valid-accounts",
            "label": "valid Accounts",
            "frontend_entry": "frontend/account-entry.tsx",
            "backend_entry": "python/account_feature.py",
        }
    ]
    serialized = json.dumps([asdict(feature) for feature in features] + account_feature_load_failures())
    assert "credential-fixture" not in serialized
    assert "credential" not in serialized
    assert "session" not in serialized


def test_frontend_entry_is_resolved_by_the_compiled_host_registry(tmp_path):
    from core.account_features import list_account_features

    builtin = tmp_path / "builtin"
    plugin = _write_feature(builtin, "compiled")
    (plugin / "frontend" / "account-entry.tsx").unlink()

    features = list_account_features(builtin_root=builtin, overlay_spec="")

    assert [feature.frontend_entry for feature in features] == ["frontend/account-entry.tsx"]


def test_isolates_duplicate_malformed_missing_and_overlay_features(tmp_path):
    from core.account_features import account_feature_load_failures, list_account_features

    builtin = tmp_path / "builtin"
    _write_feature(builtin, "first", feature_id="shared")
    _write_feature(builtin, "second", feature_id="shared")
    missing = _write_feature(builtin, "missing", backend_entry="python/missing.py")
    (missing / "python" / "missing.py").unlink()
    (builtin / "broken").mkdir(parents=True)
    (builtin / "broken" / "plugin.yaml").write_text("features: [", encoding="utf-8")

    overlay = tmp_path / "overlay"
    _write_feature(overlay, "external")

    features = list_account_features(builtin_root=builtin, overlay_spec=str(overlay))
    failures = account_feature_load_failures()

    assert [feature.feature_id for feature in features] == ["shared"]
    assert {failure["code"] for failure in failures} == {
        "duplicate_feature_id",
        "invalid_manifest",
        "missing_entry",
        "unsupported_frontend_source",
    }
    assert all(set(failure) == {"featureId", "code"} for failure in failures)


def test_rejects_unsafe_ids_and_entry_paths_without_hiding_valid_feature(tmp_path):
    from core.account_features import account_feature_load_failures, list_account_features

    builtin = tmp_path / "builtin"
    _write_feature(builtin, "valid")
    for index, feature_id in enumerate(("../bad", "bad/id", "bad\\id", "/absolute")):
        _write_feature(builtin, f"bad-id-{index}", feature_id=feature_id)
    _write_feature(builtin, "parent", frontend_entry="../outside.tsx")
    _write_feature(builtin, "absolute", backend_entry="/tmp/outside.py")

    escaped = _write_feature(builtin, "symlink")
    outside = tmp_path / "outside.py"
    outside.write_text("fixture", encoding="utf-8")
    symlink = escaped / "python" / "account_feature.py"
    symlink.unlink()
    symlink.symlink_to(outside)

    features = list_account_features(builtin_root=builtin, overlay_spec="")
    failures = account_feature_load_failures()

    assert [feature.feature_id for feature in features] == ["valid-accounts"]
    assert {failure["code"] for failure in failures} == {"invalid_feature_id", "unsafe_entry_path"}


def test_importing_discovery_does_not_initialize_provider_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    command = (
        "import json,sys; import core.account_features; "
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name == 'core.providers.registry' or name.startswith('plugins.providers.builtin.codex.python.runtime') "
        "or 'telegram' in name.lower())))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == []


def test_backend_entry_is_internal_and_canonically_confined(tmp_path):
    from core.account_features import (
        account_feature_backend_entry,
        account_feature_backend_module,
        list_account_features,
    )

    builtin = tmp_path / "builtin"
    plugin_dir = _write_feature(builtin, "valid")

    list_account_features(builtin_root=builtin, overlay_spec="")

    assert account_feature_backend_entry("valid-accounts") == (
        plugin_dir / "python" / "account_feature.py"
    ).resolve()
    assert account_feature_backend_module("valid-accounts") == (
        "plugins.providers.builtin.valid.python.account_feature"
    )
    assert account_feature_backend_entry("missing") is None


def test_main_account_feature_list_exits_before_live_runtime_imports(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    wrapper = """
import json, runpy, sys
sys.argv = ['main.py', '--account-feature-list']
try:
    runpy.run_path('main.py', run_name='__main__')
except SystemExit as exc:
    code = exc.code
blocked = sorted(name for name in sys.modules if (
    name == 'telegram'
    or name.startswith('telegram.')
    or name.startswith('bot.')
    or name in {'core.state', 'core.lifecycle', 'core.providers.registry'}
))
print(json.dumps({'exit': code, 'blocked': blocked}), file=sys.stderr)
"""

    completed = subprocess.run(
        [sys.executable, "-c", wrapper],
        cwd=repo_root,
        env={
            "HOME": str(tmp_path),
            "PATH": __import__("os").environ.get("PATH", ""),
            "LANG": "C.UTF-8",
        },
        check=True,
        capture_output=True,
        text=True,
    )

    envelope = json.loads(completed.stdout)
    marker = json.loads(completed.stderr)
    assert envelope["ok"] is True
    assert set(envelope["data"]) == {"features", "failures"}
    assert marker == {"exit": 0, "blocked": []}
    assert list(tmp_path.iterdir()) == []


def test_main_account_feature_action_round_trips_opaque_payload_without_live_imports(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    builtin = tmp_path / "builtin"
    plugin_dir = _write_feature(builtin, "fixture")
    (plugin_dir / "python" / "account_feature.py").write_text(
        """
def handle_account_feature(*, action, payload, context):
    return {
        "action": action,
        "payload": payload,
        "contextKeys": sorted(context),
    }
""".strip(),
        encoding="utf-8",
    )
    data_root = tmp_path / "plugin-data"
    wrapper = """
import json, runpy, sys
from pathlib import Path
import core.account_features as account_features
account_features.BUILTIN_PLUGIN_ROOT = Path(sys.argv[1])
sys.argv = [
    'main.py',
    '--account-feature-action',
    '--account-feature-id', 'fixture-accounts',
    '--account-feature-action-name', 'fixture.roundtrip',
]
try:
    runpy.run_path('main.py', run_name='__main__')
except SystemExit as exc:
    code = exc.code
blocked = sorted(name for name in sys.modules if (
    name == 'telegram'
    or name.startswith('telegram.')
    or name.startswith('bot.')
    or name in {'core.state', 'core.lifecycle', 'core.providers.registry'}
))
print(json.dumps({'exit': code, 'blocked': blocked}), file=sys.stderr)
"""
    request = {
        "payload": {"opaqueValue": {"nested": True}},
        "trusted_context": {"data_root": str(data_root), "native_paths": []},
    }

    completed = subprocess.run(
        [sys.executable, "-c", wrapper, str(builtin)],
        cwd=repo_root,
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": __import__("os").environ.get("PATH", ""),
            "LANG": "C.UTF-8",
        },
        input=json.dumps(request),
        check=True,
        capture_output=True,
        text=True,
    )

    envelope = json.loads(completed.stdout)
    marker = json.loads(completed.stderr)
    assert envelope == {
        "ok": True,
        "data": {
            "action": "fixture.roundtrip",
            "payload": {"opaqueValue": {"nested": True}},
            "contextKeys": ["data_root", "native_paths"],
        },
        "error": None,
    }
    assert marker == {"exit": 0, "blocked": []}
