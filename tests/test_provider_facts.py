import importlib
from types import SimpleNamespace
from pathlib import Path

import yaml

from core.providers.facts import (
    list_provider_threads,
    query_provider_active_thread_ids,
    read_provider_thread_history,
    scan_provider_workspaces,
)
from core.providers.registry import (
    _load_bundled_provider_descriptors,
    classify_provider,
    get_provider,
    list_providers,
    provider_not_enabled_message,
)


def _config_with_providers(**providers):
    return SimpleNamespace(providers=providers)


def _provider_config(*, enabled=True, managed=None, visible=True):
    runtime_enabled = enabled if managed is None else managed
    return SimpleNamespace(enabled=enabled, managed=runtime_enabled, visible=visible)


def test_scan_provider_workspaces_routes_to_overlay_provider(monkeypatch):
    called = {}

    def fake_scan_workspaces(*, sessions_dir=None):
        called["sessions_dir"] = sessions_dir
        return [{"name": "proj", "path": "/tmp/proj", "thread_count": 3}]

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            scan_workspaces=fake_scan_workspaces,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "overlay-tool" else None,
    )

    result = scan_provider_workspaces("overlay-tool")

    assert result == [{"name": "proj", "path": "/tmp/proj", "thread_count": 3}]
    assert called["sessions_dir"] is None


def test_scan_provider_workspaces_passes_sessions_dir_to_custom_provider(monkeypatch):
    called = {}

    def fake_scan_workspaces(*, sessions_dir=None):
        called["sessions_dir"] = sessions_dir
        return [{"name": "proj", "path": "/tmp/proj", "thread_count": 1}]

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            scan_workspaces=fake_scan_workspaces,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "custom" else None,
    )

    result = scan_provider_workspaces("custom", sessions_dir="/tmp/custom-sessions")

    assert result == [{"name": "proj", "path": "/tmp/proj", "thread_count": 1}]
    assert called == {"sessions_dir": "/tmp/custom-sessions"}


def test_read_provider_thread_history_routes_to_claude(monkeypatch):
    called = {}

    def fake_read_claude_thread_history(thread_id, *, limit=10, sessions_dir=None):
        called["thread_id"] = thread_id
        called["limit"] = limit
        called["sessions_dir"] = sessions_dir
        return [{"role": "assistant", "text": "hi"}]

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            read_thread_history=fake_read_claude_thread_history,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "claude" else None,
    )

    result = read_provider_thread_history("claude", "claude-session-1", limit=5)

    assert result == [{"role": "assistant", "text": "hi"}]
    assert called == {"thread_id": "claude-session-1", "limit": 5, "sessions_dir": None}


def test_read_provider_thread_history_passes_sessions_dir_to_custom_provider(monkeypatch):
    called = {}

    def fake_read_thread_history(thread_id, *, limit=10, sessions_dir=None):
        called["thread_id"] = thread_id
        called["limit"] = limit
        called["sessions_dir"] = sessions_dir
        return [{"role": "assistant", "text": "custom"}]

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            read_thread_history=fake_read_thread_history,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "custom" else None,
    )

    result = read_provider_thread_history(
        "custom",
        "custom-thread-1",
        limit=4,
        sessions_dir="/tmp/custom-sessions",
    )

    assert result == [{"role": "assistant", "text": "custom"}]
    assert called == {
        "thread_id": "custom-thread-1",
        "limit": 4,
        "sessions_dir": "/tmp/custom-sessions",
    }


def test_query_provider_active_thread_ids_routes_to_codex(monkeypatch):
    called = {}

    def fake_query_codex_active_thread_ids(workspace_path):
        called["workspace_path"] = workspace_path
        return {"tid-1", "tid-2"}

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            query_active_thread_ids=fake_query_codex_active_thread_ids,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "codex" else None,
    )

    result = query_provider_active_thread_ids("codex", "/tmp/proj")

    assert result == {"tid-1", "tid-2"}
    assert called == {"workspace_path": "/tmp/proj"}


def test_list_provider_threads_routes_to_codex(monkeypatch):
    called = {}

    def fake_list_codex_threads_by_cwd(workspace_path, limit=20):
        called["workspace_path"] = workspace_path
        called["limit"] = limit
        return [{"id": "tid-1", "preview": "hello"}]

    descriptor = SimpleNamespace(
        facts=SimpleNamespace(
            list_threads=fake_list_codex_threads_by_cwd,
        )
    )
    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: descriptor if tool_name == "codex" else None,
    )

    result = list_provider_threads("codex", "/tmp/proj", limit=7)

    assert result == [{"id": "tid-1", "preview": "hello"}]
    assert called == {"workspace_path": "/tmp/proj", "limit": 7}


def test_classify_provider_returns_unknown_for_unregistered_provider():
    cfg = _config_with_providers(codex=_provider_config())

    assert classify_provider("opencode-private", cfg) == "unknown_provider"


def test_public_provider_runtime_descriptors_are_plugin_entrypoints():
    plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "providers" / "builtin"
    public_provider_ids = []

    for manifest in sorted(plugin_root.glob("*/plugin.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        provider_id = data["id"]
        public_provider_ids.append(provider_id)

        entrypoint = data["entrypoints"]["python_descriptor"]
        assert entrypoint.startswith(f"plugins.providers.builtin.{provider_id}.python.provider:")

        descriptor = get_provider(provider_id)
        assert descriptor is not None
        assert descriptor.name == provider_id
        assert descriptor.metadata.id == provider_id
        assert descriptor.metadata.label == data["label"]

    listed_public_ids = [
        provider.name
        for provider in list_providers()
        if getattr(provider.metadata, "visible", False)
    ]
    assert listed_public_ids == public_provider_ids


def test_provider_registry_does_not_static_construct_public_provider_descriptors():
    registry_path = Path(__file__).resolve().parents[1] / "core" / "providers" / "registry.py"
    source = registry_path.read_text(encoding="utf-8")

    assert '"codex": ProviderDescriptor(' not in source
    assert '"claude": ProviderDescriptor(' not in source
    assert "core.providers.command_runtime" not in source
    assert "core.providers.lifecycle_runtime" not in source


def test_core_provider_package_is_provider_agnostic():
    provider_core = Path(__file__).resolve().parents[1] / "core" / "providers"
    combined_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(provider_core.glob("*.py"))
    )

    assert not (provider_core / "command_runtime.py").exists()
    assert not (provider_core / "status.py").exists()
    private_package = ".".join(["plugins", "providers", "private"])
    assert private_package not in combined_source
    assert "customprovider" not in combined_source.lower()


def test_bundled_provider_catalog_supports_manifestless_packaged_runtime():
    providers = _load_bundled_provider_descriptors()

    assert list(providers.keys()) == ["claude", "codex"]
    assert providers["codex"].metadata.visible is True
    assert providers["claude"].metadata.visible is True


def test_classify_provider_returns_unknown_for_overlay_provider_without_config():
    cfg = _config_with_providers(codex=_provider_config(), claude=_provider_config(enabled=False, managed=False))

    assert classify_provider("overlay-tool", cfg) == "unknown_provider"
    assert get_provider("overlay-tool", cfg) is None


def test_provider_not_enabled_message_uses_user_facing_prefix():
    assert provider_not_enabled_message("overlay-tool").startswith("Provider 'overlay-tool' is not enabled")
    assert "Provider 'overlay-tool' is not enabled" in provider_not_enabled_message(
        "overlay-tool",
        "disabled_provider",
    )


def test_disabled_overlay_provider_facts_fail_with_user_facing_message():
    cfg = _config_with_providers(codex=_provider_config(), claude=_provider_config(enabled=False, managed=False))

    try:
        scan_provider_workspaces("overlay-tool", config=cfg)
    except ValueError as exc:
        assert "Provider 'overlay-tool' is not enabled" in str(exc)
    else:
        raise AssertionError("unknown overlay provider should fail before provider hook dispatch")


def test_unknown_provider_facts_fail_with_user_facing_message():
    cfg = _config_with_providers(codex=_provider_config())

    try:
        list_provider_threads("opencode-private", "/tmp/project", config=cfg)
    except ValueError as exc:
        assert "Provider 'opencode-private' is not enabled" in str(exc)
        assert "unknown_provider" in str(exc)
    else:
        raise AssertionError("unknown provider should fail before provider hook dispatch")


def test_hidden_runtime_enabled_overlay_provider_still_dispatches_provider_hooks(monkeypatch):
    called = {}
    cfg = _config_with_providers(
        codex=_provider_config(),
        claude=_provider_config(enabled=False, managed=False),
        **{"overlay-tool": _provider_config(enabled=True, managed=True, visible=False)},
    )

    def fake_scan_overlay_session_cwds():
        called["overlay-tool"] = True
        return [{"name": "internal", "path": "/tmp/internal", "thread_count": 1}]

    monkeypatch.setattr(
        "core.providers.facts.get_provider",
        lambda tool_name: SimpleNamespace(
            facts=SimpleNamespace(scan_workspaces=fake_scan_overlay_session_cwds)
        ) if tool_name == "overlay-tool" else None,
    )

    assert classify_provider("overlay-tool", cfg) == "unknown_provider"
    assert get_provider("overlay-tool", cfg) is None
    try:
        scan_provider_workspaces("overlay-tool", config=cfg)
    except ValueError as exc:
        assert "Provider 'overlay-tool' is not enabled" in str(exc)
    else:
        raise AssertionError("hidden overlay provider should not dispatch provider hooks in the public build")


def test_provider_registry_loads_external_overlay_manifest(tmp_path, monkeypatch):
    overlay_root = tmp_path / "provider-overlay"
    provider_dir = overlay_root / "internal_tool"
    provider_pkg_dir = provider_dir / "python"
    provider_pkg_dir.mkdir(parents=True)
    (provider_dir / "__init__.py").write_text("", encoding="utf-8")
    (provider_pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (provider_pkg_dir / "provider.py").write_text(
        """
from core.providers.contracts import ProviderCapabilities, ProviderDescriptor, ProviderFactsHooks, ProviderMetadata


def create_provider_descriptor():
    return ProviderDescriptor(
        name="internal-tool",
        metadata=ProviderMetadata(
            id="internal-tool",
            label="Internal Tool",
            visible=False,
            managed=True,
            autostart=True,
            bin="internal-tool",
        ),
        facts=ProviderFactsHooks(
            scan_workspaces=lambda *, sessions_dir=None: [],
            list_threads=lambda workspace_path, limit=20: [],
            read_thread_history=lambda thread_id, *, limit=10, sessions_dir=None: [],
            query_active_thread_ids=lambda workspace_path: set(),
        ),
        capabilities=ProviderCapabilities(),
    )
""",
        encoding="utf-8",
    )
    (provider_dir / "plugin.yaml").write_text(
        """
schema_version: 1
id: internal-tool
kind: provider
visibility: private
order: 100
runtime_id: internal-tool
label: Internal Tool
description: Private overlay sessions
default_visible: false

provider:
  visible: false
  managed: true
  autostart: true
  runtime_id: internal-tool
  bin: internal-tool
  transport:
    type: http
  capabilities:
    sessions: true
    send: true
    approvals: true
    questions: true

entrypoints:
  python_descriptor: internal_tool.python.provider:create_provider_descriptor
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(overlay_root))
    registry = importlib.import_module("core.providers.registry")
    importlib.reload(registry)

    providers = registry.list_providers()
    provider_ids = [provider.name for provider in providers]
    assert provider_ids == ["claude", "codex", "internal-tool"]
    internal_tool = registry.get_provider("internal-tool")
    assert internal_tool is not None
    assert internal_tool.metadata.visible is False
