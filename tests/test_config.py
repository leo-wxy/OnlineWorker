import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

# 兼容旧 tools[] 结构的回归 fixture
VALID_YAML = """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    app_server_port: 0

logging:
  level: "INFO"
"""

PROVIDER_YAML = """
schema_version: 2

providers:
  codex:
    managed: true
    autostart: true
    bin: "codex"
    transport:
      type: "ws"
      app_server_port: 4722
    control_mode: "app"

  claude:
    managed: false
    autostart: false
    bin: "claude"
    transport:
      type: "stdio"
    auth:
      key: ""
      base_url: "http://localhost:3031"
      model: "claude-opus-4-6"

telegram:
  delete_archived_topics: false

logging:
  level: "DEBUG"
"""

# 敏感字段通过环境变量提供
BASE_ENV = {
    "TELEGRAM_TOKEN": "123:abc",
    "ALLOWED_USER_ID": "456789",
    "GROUP_CHAT_ID": "-100987654321",
}


@pytest.fixture(autouse=True)
def clear_provider_overlay(monkeypatch):
    monkeypatch.delenv("ONLINEWORKER_PROVIDER_OVERLAY", raising=False)

def test_load_config_from_yaml(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.delenv("CODEX_DAEMON_TOKEN", raising=False)
    from config import load_config
    cfg = load_config(str(p))
    assert cfg.telegram_token == "123:abc"
    assert cfg.allowed_user_id == 456789
    assert cfg.group_chat_id == -100987654321
    assert cfg.log_level == "INFO"
    # codex tool 配置
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.codex_bin == "codex"
    assert codex.app_server_port == 0
    assert codex.protocol == "stdio"
    assert codex.owner_transport == "stdio"
    assert codex.live_transport == "owner_bridge"
    assert codex.control_mode == "app"


def test_load_config_public_default_provider_names_are_codex_and_claude(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
logging:
  level: "INFO"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")

    from config import load_config

    cfg = load_config(str(p))
    assert list(cfg.providers.keys()) == ["codex", "claude"]
    assert "customprovider" not in cfg.providers
    assert cfg.providers["codex"].label == "Codex"
    assert cfg.providers["claude"].label == "Claude"


def test_builtin_provider_plugin_manifests_define_public_defaults():
    plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "providers" / "builtin"
    manifests = sorted(plugin_root.glob("*/plugin.yaml"))
    ids = []
    for manifest in manifests:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        ids.append(data["id"])
        assert data["kind"] == "provider"
        assert data["visibility"] == "public"
        assert data["provider"]["visible"] is True

    assert ids == ["claude", "codex"]
    assert "customprovider" not in ids


def test_config_yaml_example_uses_public_provider_schema():
    example_path = Path(__file__).resolve().parents[1] / "config.yaml.example"
    source = example_path.read_text(encoding="utf-8")
    data = yaml.safe_load(source)

    assert data["schema_version"] == 2
    assert "tools" not in data
    assert list(data["providers"].keys()) == ["codex", "claude"]
    assert "customprovider" not in source.lower()


def test_load_config_provider_overlay_enables_internal_tool(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("logging:\n  level: \"INFO\"\n", encoding="utf-8")
    overlay = tmp_path / "provider-overlay.yaml"
    overlay.write_text(
        """
providers:
  internal-tool:
    visible: false
    managed: true
    autostart: false
    runtime_id: internal-tool
    bin: internal-tool
    transport:
      type: stdio
    capabilities:
      sessions: true
      send: true
      commands: true
      approvals: true
      questions: true
      photos: false
    process:
      cleanup_matchers:
        - internal-tool
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(overlay))

    from config import load_config

    cfg = load_config(str(p))
    internal_tool = cfg.providers["internal-tool"]
    assert internal_tool.runtime_id == "internal-tool"
    assert internal_tool.managed is True
    assert internal_tool.enabled is True
    assert internal_tool.autostart is False
    assert internal_tool.codex_bin == "internal-tool"
    assert internal_tool.protocol == "stdio"
    assert internal_tool.capabilities["sessions"] is True
    assert internal_tool.capabilities["send"] is True
    assert internal_tool.capabilities["commands"] is True
    assert internal_tool.capabilities["approvals"] is True
    assert internal_tool.capabilities["questions"] is True
    assert internal_tool.capabilities["photos"] is False
    assert internal_tool.process["cleanup_matchers"] == ["internal-tool"]


def test_load_config_hidden_overlay_provider_is_runtime_enabled_but_not_public(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("logging:\n  level: \"INFO\"\n", encoding="utf-8")
    overlay = tmp_path / "provider-overlay.yaml"
    overlay.write_text(
        """
providers:
  internal-tool:
    visible: false
    managed: true
    autostart: true
    runtime_id: internal-tool
    bin: internal-tool
    transport:
      type: http
      app_server_port: 4096
    capabilities:
      sessions: true
      send: true
      approvals: true
      questions: true
      photos: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(overlay))

    from config import load_config

    cfg = load_config(str(p))
    internal_tool = cfg.get_tool("internal-tool")
    assert internal_tool is not None
    assert internal_tool.visible is False
    assert internal_tool.managed is True
    assert [provider.name for provider in cfg.enabled_tools] == ["codex"]
    assert [provider.name for provider in cfg.providers.values() if provider.visible] == ["codex", "claude"]


def test_load_config_provider_overlay_directory_enables_external_provider(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("logging:\n  level: \"INFO\"\n", encoding="utf-8")

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

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.setenv("ONLINEWORKER_PROVIDER_OVERLAY", str(overlay_root))

    from config import load_config

    cfg = load_config(str(p))
    internal_tool = cfg.get_tool("internal-tool")
    assert internal_tool is not None
    assert internal_tool.visible is False
    assert internal_tool.managed is True
    assert [provider.name for provider in cfg.enabled_tools] == ["codex"]


def test_load_config_from_provider_schema(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(PROVIDER_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.managed is True
    assert codex.autostart is True
    assert codex.codex_bin == "codex"
    assert codex.protocol == "ws"
    assert codex.owner_transport == "ws"
    assert codex.live_transport == "shared_ws"
    assert codex.app_server_port == 4722
    assert codex.control_mode == "app"

    assert cfg.get_tool("claude") is None
    claude = cfg.get_provider("claude")
    assert claude is not None
    assert claude.managed is False
    assert claude.autostart is False
    assert claude.codex_bin == "claude"
    assert claude.protocol == "stdio"
    assert claude.auth["key"] == ""
    assert claude.auth["base_url"] == "http://localhost:3031"
    assert claude.auth["model"] == "claude-opus-4-6"
    assert cfg.log_level == "DEBUG"
    assert cfg.delete_archived_topics is False


def test_load_config_migrates_legacy_tools_to_provider_flags(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
  - name: claude
    enabled: true
    codex_bin: "claude"
    protocol: "stdio"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")

    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_provider("codex")
    assert codex is not None
    assert codex.managed is True
    assert codex.autostart is True

    claude = cfg.get_provider("claude")
    assert claude is not None
    assert claude.managed is True
    assert claude.autostart is True
    assert cfg.get_tool("claude") is claude
    assert [tool.name for tool in cfg.enabled_tools] == ["codex", "claude"]


def test_load_config_backfills_disabled_claude_provider_when_missing(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")

    from config import load_config

    cfg = load_config(str(p))
    claude = cfg.get_provider("claude")
    assert claude is not None
    assert claude.managed is False
    assert claude.autostart is False
    assert claude.codex_bin == "claude"
    assert claude.protocol == "stdio"
    assert cfg.get_tool("claude") is None


def test_load_config_uses_env_fallback_for_empty_claude_auth_fields(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
schema_version: 2
providers:
  claude:
    managed: false
    autostart: false
    bin: "claude"
    transport:
      type: "stdio"
    auth:
      key: ""
      base_url: ""
      model: ""
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3031")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    from config import load_config

    cfg = load_config(str(p))
    claude = cfg.get_provider("claude")
    assert claude is not None
    assert claude.auth["key"] == "dummy"
    assert claude.auth["base_url"] == "http://localhost:3031"
    assert claude.auth["model"] == "claude-opus-4-6"

def test_load_config_ignores_legacy_unknown_fields(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    app_server_port: 4722
    app_server_url: "ws://127.0.0.1:4722"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.app_server_url == "ws://127.0.0.1:4722"
    assert codex.protocol == "ws"
    assert codex.control_mode == "app"


def test_load_config_preserves_external_codex_app_server_url(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
    app_server_url: "ws://127.0.0.1:4722"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "ws"
    assert codex.owner_transport == "ws"
    assert codex.live_transport == "shared_ws"
    assert codex.app_server_port == 4722
    assert codex.app_server_url == "ws://127.0.0.1:4722"
    assert codex.control_mode == "app"


def test_load_config_keeps_legacy_codex_stdio_default(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "stdio"
    app_server_port: 0
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "stdio"
    assert codex.owner_transport == "stdio"
    assert codex.live_transport == "owner_bridge"
    assert codex.app_server_port == 0
    assert codex.app_server_url == ""
    assert codex.control_mode == "app"


def test_load_config_migrates_legacy_codex_default_ws_without_control_mode_to_stdio(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "stdio"
    assert codex.owner_transport == "stdio"
    assert codex.live_transport == "owner_bridge"
    assert codex.app_server_port == 0
    assert codex.app_server_url == ""
    assert codex.control_mode == "app"


def test_load_config_treats_legacy_codex_fixed_port_without_protocol_as_shared_ws(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    app_server_port: 4722
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "ws"
    assert codex.owner_transport == "ws"
    assert codex.live_transport == "shared_ws"
    assert codex.app_server_port == 4722
    assert codex.app_server_url == ""
    assert codex.control_mode == "app"


def test_load_config_preserves_explicit_codex_app_control_mode(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
    control_mode: "app"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "ws"
    assert codex.owner_transport == "ws"
    assert codex.live_transport == "shared_ws"
    assert codex.control_mode == "app"


def test_load_config_preserves_explicit_codex_hybrid_control_mode(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
    control_mode: "hybrid"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "ws"
    assert codex.owner_transport == "ws"
    assert codex.live_transport == "shared_ws"
    assert codex.control_mode == "hybrid"


def test_load_config_allows_explicit_codex_owner_and_live_transport_override(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
schema_version: 2
providers:
  codex:
    managed: true
    autostart: true
    bin: "codex"
    transport:
      type: "ws"
      app_server_port: 4722
    owner_transport: "stdio"
    live_transport: "owner_bridge"
    control_mode: "app"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    codex = cfg.get_tool("codex")
    assert codex is not None
    assert codex.protocol == "stdio"
    assert codex.owner_transport == "stdio"
    assert codex.live_transport == "owner_bridge"
    assert codex.app_server_port == 0
    assert codex.control_mode == "app"


def test_load_config_defaults_claude_to_stdio_and_app_control_mode(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
tools:
  - name: claude
    enabled: true
    codex_bin: "claude"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config

    cfg = load_config(str(p))
    claude = cfg.get_tool("claude")
    assert claude is not None
    assert claude.codex_bin == "claude"
    assert claude.protocol == "stdio"
    assert claude.control_mode == "app"
    assert [tool.name for tool in cfg.enabled_tools] == ["claude"]


def test_env_overrides_telegram_token(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "override:xyz")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    from config import load_config
    cfg = load_config(str(p))
    assert cfg.telegram_token == "override:xyz"

def test_missing_telegram_token_raises(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    with pytest.raises(ValueError, match="TELEGRAM_TOKEN"):
        from config import load_config
        load_config(str(p))

def test_missing_allowed_user_id_raises(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.delenv("ALLOWED_USER_ID", raising=False)
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    with pytest.raises(ValueError, match="ALLOWED_USER_ID"):
        from config import load_config
        load_config(str(p))

def test_invalid_allowed_user_id_raises(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "not_a_number")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    with pytest.raises(ValueError, match="ALLOWED_USER_ID"):
        from config import load_config
        load_config(str(p))

def test_missing_group_chat_id_raises(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(VALID_YAML, encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.delenv("GROUP_CHAT_ID", raising=False)
    with pytest.raises(ValueError, match="GROUP_CHAT_ID"):
        from config import load_config
        load_config(str(p))

def test_invalid_yaml_raises(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("not: valid: yaml: :", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("ALLOWED_USER_ID", "456789")
    monkeypatch.setenv("GROUP_CHAT_ID", "-100987654321")
    with pytest.raises((yaml.YAMLError, ValueError)):
        from config import load_config
        load_config(str(p))
