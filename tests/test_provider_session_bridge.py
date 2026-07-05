from types import SimpleNamespace

from core import provider_session_bridge as bridge


def _overlay_descriptor(*, facts=None, thread_hooks=None, message_hooks=None, usage_hooks=None):
    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        metadata = type(
            "Metadata",
            (),
            {
                "bin": "overlay-tool",
                "transport": type(
                    "Transport",
                    (),
                    {
                        "app_server_port": 0,
                        "type": "http",
                    },
                )(),
                "owner_transport": "http",
                "live_transport": "http",
            },
        )()
        runtime_hooks = RuntimeHooks

    Descriptor.facts = facts
    Descriptor.thread_hooks = thread_hooks
    Descriptor.message_hooks = message_hooks
    Descriptor.usage_hooks = usage_hooks
    return Descriptor()


def test_load_provider_descriptor_prefers_registry_for_bundled_provider(monkeypatch):
    descriptor = object()

    monkeypatch.setattr(bridge, "get_provider", lambda provider_id: descriptor if provider_id == "codex" else None)
    monkeypatch.setattr(bridge, "_iter_manifest_paths", lambda: [])

    assert bridge._load_provider_descriptor("codex") is descriptor


def test_load_provider_descriptor_falls_back_to_manifest_scan(monkeypatch, tmp_path):
    overlay_dir = tmp_path / "provider-plugins" / "overlay-tool"
    overlay_dir.mkdir(parents=True)
    module_name = "bridge_overlay_manifest_entry"
    (overlay_dir / "plugin.yaml").write_text(
        """
schema_version: 1
id: overlay-tool
kind: provider
label: Overlay Tool
entrypoints:
  python_descriptor: {module_name}:create_provider_descriptor
""".format(module_name=module_name).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "provider-plugins" / f"{module_name}.py").write_text(
        """
def create_provider_descriptor():
    return {"name": "overlay-tool"}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(bridge, "get_provider", lambda provider_id: None)
    monkeypatch.setattr(bridge, "_iter_manifest_paths", lambda: [overlay_dir / "plugin.yaml"])

    assert bridge._load_provider_descriptor("overlay-tool") == {"name": "overlay-tool"}


def test_list_provider_session_rows_merges_workspaces_and_sorts(monkeypatch):
    class Facts:
        @staticmethod
        def scan_workspaces():
            return [{"path": "/tmp/beta"}, {"path": "/tmp/alpha"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"tid-2"} if workspace_path == "/tmp/beta" else {"tid-1"}

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return (
                [{"id": "tid-2", "preview": "Beta", "updatedAt": 20}]
                if workspace_path == "/tmp/beta"
                else [{"id": "tid-1", "preview": "Alpha", "updatedAt": 10}]
            )

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.list_provider_session_rows("overlay-tool", limit_per_workspace=100)

    assert result == [
        {
            "id": "tid-2",
            "title": "Beta",
            "preview": "Beta",
            "workspace": "/tmp/beta",
            "archived": False,
            "providerActive": True,
            "updatedAt": 20,
            "createdAt": 20,
        },
        {
            "id": "tid-1",
            "title": "Alpha",
            "preview": "Alpha",
            "workspace": "/tmp/alpha",
            "archived": False,
            "providerActive": True,
            "updatedAt": 10,
            "createdAt": 10,
        },
    ]


def test_list_provider_session_rows_marks_inactive_threads_archived(monkeypatch):
    class Facts:
        @staticmethod
        def scan_workspaces():
            return [{"path": "/tmp/proj"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"active-1"}

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return [
                {"id": "active-1", "preview": "Active"},
                {"id": "stale-1", "preview": "Stale"},
            ]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.list_provider_session_rows("overlay-tool")

    assert result[0]["archived"] is False
    assert result[0]["providerActive"] is True
    assert result[1]["archived"] is True
    assert result[1]["providerActive"] is False


def test_list_provider_session_rows_prefers_provider_level_list_sessions(monkeypatch):
    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            return [
                {
                    "id": "tid-2",
                    "title": "Beta",
                    "preview": "Beta preview",
                    "workspace": "/tmp/beta",
                    "archived": False,
                    "providerActive": True,
                    "updatedAt": 20,
                    "createdAt": 19,
                },
                {
                    "id": "tid-1",
                    "title": "Alpha",
                    "preview": "Alpha preview",
                    "workspace": "/tmp/alpha",
                    "archived": True,
                    "providerActive": False,
                    "updatedAt": 10,
                    "createdAt": 9,
                },
            ]

        @staticmethod
        def scan_workspaces():
            raise AssertionError("provider-level list_sessions should bypass workspace scans")

        @staticmethod
        def query_active_thread_ids(workspace_path):
            raise AssertionError("provider-level list_sessions should bypass active id queries")

        @staticmethod
        def list_threads(workspace_path, limit=100):
            raise AssertionError("provider-level list_sessions should bypass thread listing")

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.list_provider_session_rows("overlay-tool")

    assert result == [
        {
            "id": "tid-2",
            "title": "Beta",
            "preview": "Beta preview",
            "workspace": "/tmp/beta",
            "archived": False,
            "providerActive": True,
            "updatedAt": 20,
            "createdAt": 19,
        },
        {
            "id": "tid-1",
            "title": "Alpha",
            "preview": "Alpha preview",
            "workspace": "/tmp/alpha",
            "archived": True,
            "providerActive": False,
            "updatedAt": 10,
            "createdAt": 9,
        },
    ]


def test_list_provider_session_rows_keeps_preview_separate_from_title(monkeypatch):
    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            return [
                {
                    "id": "tid-2",
                    "title": "继续phase17 的实现",
                    "preview": "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。",
                    "workspace": "/tmp/beta",
                    "archived": False,
                    "providerActive": True,
                    "updatedAt": 20,
                    "createdAt": 19,
                }
            ]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.list_provider_session_rows("overlay-tool")

    assert result == [
        {
            "id": "tid-2",
            "title": "继续phase17 的实现",
            "preview": "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。",
            "workspace": "/tmp/beta",
            "archived": False,
            "providerActive": True,
            "updatedAt": 20,
            "createdAt": 19,
        }
    ]


def test_read_provider_session_rows_normalizes_content_shape(monkeypatch):
    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            return [
                {"role": "system", "text": "skip"},
                {"role": "user", "text": "hello"},
                {"role": "assistant", "content": "world"},
                {"role": "assistant", "text": "  "},
            ]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.read_provider_session_rows("overlay-tool", "session-1", limit=50)

    assert result == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_read_provider_session_rows_does_not_treat_workspace_dir_as_sessions_dir(monkeypatch):
    observed = {}

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            observed["session_id"] = session_id
            observed["limit"] = limit
            observed["sessions_dir"] = sessions_dir
            return [{"role": "assistant", "text": "history"}]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.read_provider_session_rows(
        "codex",
        "session-1",
        limit=50,
        workspace_dir="/tmp/project",
    )

    assert observed == {
        "session_id": "session-1",
        "limit": 50,
        "sessions_dir": None,
    }
    assert result == [{"role": "assistant", "content": "history"}]


def test_read_provider_session_rows_preserves_visible_error_metadata(monkeypatch):
    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            return [
                {
                    "role": "assistant",
                    "text": "provider quota exhausted",
                    "displayMode": "plain",
                    "kind": "error",
                },
                {
                    "role": "assistant",
                    "text": "",
                    "kind": "error",
                    "error": "provider auth failed",
                },
                {
                    "role": "assistant",
                    "text": "",
                    "kind": "empty-placeholder",
                },
            ]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.read_provider_session_rows("overlay-tool", "session-1", limit=50)

    assert result == [
        {
            "role": "assistant",
            "content": "provider quota exhausted",
            "displayMode": "plain",
            "kind": "error",
        },
        {
            "role": "assistant",
            "content": "provider auth failed",
            "displayMode": "plain",
            "kind": "error",
        },
    ]


def test_read_provider_session_rows_defaults_to_latest_twenty_turns(monkeypatch):
    observed = {}

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=20, sessions_dir=None):
            observed["limit"] = limit
            return [
                {"role": "assistant", "content": f"turn-{index}"}
                for index in range(limit)
            ]

    monkeypatch.setattr(bridge, "_provider_facts", lambda provider_id: Facts)

    result = bridge.read_provider_session_rows("overlay-tool", "session-1")

    assert observed["limit"] == 20
    assert len(result) == 20
    assert result[0] == {"role": "assistant", "content": "turn-0"}
    assert result[-1] == {"role": "assistant", "content": "turn-19"}


def test_provider_usage_summary_invokes_descriptor_usage_hook(monkeypatch):
    called = {}

    class UsageHooks:
        @staticmethod
        def get_summary(start_date, end_date):
            called["range"] = (start_date, end_date)
            return {
                "days": [
                    {
                        "date": "2026-05-21",
                        "inputTokens": 12,
                        "outputTokens": 3,
                        "cacheCreationTokens": 4,
                        "cacheReadTokens": 5,
                        "totalTokens": 24,
                        "totalCostUsd": 0.42,
                    }
                ]
            }

    class Descriptor:
        usage_hooks = UsageHooks

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary(
        "overlay-tool",
        "2026-05-20",
        "2026-05-21",
    )

    assert called["range"] == ("2026-05-20", "2026-05-21")
    assert result == {
        "providerId": "overlay-tool",
        "days": [
            {
                "date": "2026-05-21",
                "inputTokens": 12,
                "outputTokens": 3,
                "cacheCreationTokens": 4,
                "cacheReadTokens": 5,
                "totalTokens": 24,
                "totalCostUsd": 0.42,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }


def test_provider_usage_summary_rejects_provider_without_usage_hook(monkeypatch):
    class Descriptor:
        usage_hooks = None

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())

    try:
        bridge.get_provider_usage_summary(
            "overlay-tool",
            "2026-05-20",
            "2026-05-21",
        )
    except ValueError as exc:
        assert str(exc) == "Provider 'overlay-tool' does not expose usage hooks"
    else:
        raise AssertionError("expected missing usage hook error")


def test_codex_provider_usage_summary_reads_session_token_counts(monkeypatch, tmp_path):
    from plugins.providers.builtin.codex.python import storage_runtime

    sessions_dir = tmp_path / "codex-sessions"
    day_dir = sessions_dir / "2026" / "05" / "11"
    day_dir.mkdir(parents=True)
    (day_dir / "rollout.jsonl").write_text(
        "\n".join(
            [
                '{"type":"session_meta","payload":{"id":"t1"}}',
                '{"timestamp":"2026-05-11T01:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"last_token_usage":{"input_tokens":100,"cached_input_tokens":10,"output_tokens":50,"total_tokens":150},"total_token_usage":{"input_tokens":100,"cached_input_tokens":10,"output_tokens":50,"total_tokens":150}}}}',
                '{"timestamp":"2026-05-11T03:00:00.000Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"input_tokens":160,"cached_input_tokens":20,"output_tokens":70,"total_tokens":230}}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(storage_runtime, "CODEX_SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary("codex", "2026-05-11", "2026-05-11")

    assert result == {
        "providerId": "codex",
        "days": [
            {
                "date": "2026-05-11",
                "inputTokens": 160,
                "outputTokens": 70,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 20,
                "totalTokens": 230,
                "totalCostUsd": None,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }


def test_claude_provider_usage_summary_reads_project_usage(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python import storage_runtime

    projects_dir = tmp_path / "claude-projects"
    project_dir = projects_dir / "project-a"
    project_dir.mkdir(parents=True)
    (project_dir / "session.jsonl").write_text(
        "\n".join(
            [
                '{"timestamp":"2026-05-11T10:00:00.000Z","requestId":"req-1","message":{"id":"msg-1","usage":{"input_tokens":100,"output_tokens":50,"cache_creation_input_tokens":20,"cache_read_input_tokens":10}},"costUSD":0.12}',
                '{"timestamp":"2026-05-11T10:00:01.000Z","requestId":"req-1","message":{"id":"msg-1","usage":{"input_tokens":100,"output_tokens":50,"cache_creation_input_tokens":20,"cache_read_input_tokens":10}},"costUSD":0.12}',
                '{"timestamp":"2026-05-11T11:00:00.000Z","requestId":"req-2","message":{"id":"msg-2","usage":{"input_tokens":40,"output_tokens":10}},"costUSD":0.08}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(storage_runtime, "CLAUDE_PROJECTS_DIR", str(projects_dir))
    monkeypatch.setattr(bridge, "_unix_time_seconds", lambda: 1770000000)

    result = bridge.get_provider_usage_summary("claude", "2026-05-11", "2026-05-11")

    assert result == {
        "providerId": "claude",
        "days": [
            {
                "date": "2026-05-11",
                "inputTokens": 140,
                "outputTokens": 60,
                "cacheCreationTokens": 20,
                "cacheReadTokens": 10,
                "totalTokens": 230,
                "totalCostUsd": 0.2,
            }
        ],
        "updatedAtEpoch": 1770000000,
        "unsupportedReason": None,
    }


def test_send_provider_session_message_uses_generic_runtime_start_hook(monkeypatch):
    called = {}

    class Facts:
        @staticmethod
        def scan_workspaces():
            return [{"path": "/tmp/proj"}]

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return [{"id": "tid-1", "preview": "Thread 1"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"tid-1"}

        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            return []

    class MessageHooks:
        @staticmethod
        async def send(state, adapter, ws_info, thread_info, **kwargs):
            called["adapter"] = adapter
            called["workspace_path"] = ws_info["path"]
            called["workspace_id"] = ws_info["daemon_workspace_id"]
            called["thread_id"] = thread_info["thread_id"]
            called["text"] = kwargs["text"]

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            called["tool_cfg"] = {
                "name": tool_cfg.name,
                "bin": tool_cfg.bin,
                "port": tool_cfg.app_server_port,
                "protocol": tool_cfg.protocol,
            }
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        facts = Facts
        message_hooks = MessageHooks
        metadata = type(
            "Metadata",
            (),
            {
                "bin": "overlay-tool",
                "transport": type(
                    "Transport",
                    (),
                    {
                        "app_server_port": 0,
                        "type": "http",
                    },
                )(),
                "owner_transport": "http",
                "live_transport": "http",
            },
        )()
        runtime_hooks = RuntimeHooks

    async def fake_send():
        await bridge.send_provider_session_message(
            "overlay-tool",
            "tid-1",
            "hello bridge",
            workspace_dir="/tmp/proj",
        )

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())

    import asyncio

    asyncio.run(fake_send())

    assert called == {
        "adapter": {"provider_id": "overlay-tool"},
        "workspace_path": "/tmp/proj",
        "workspace_id": "overlay-tool:/tmp/proj",
        "thread_id": "tid-1",
        "text": "hello bridge",
        "tool_cfg": {
            "name": "overlay-tool",
            "bin": "overlay-tool",
            "port": 0,
            "protocol": "http",
        },
    }


def test_provider_session_adapter_uses_configured_runtime_context(monkeypatch, tmp_path):
    import asyncio

    captured = {}
    config = SimpleNamespace(
        data_dir=str(tmp_path),
        get_tool=lambda provider_id: SimpleNamespace(
            name=provider_id,
            bin="configured-launcher",
            auth={"auth_token": "token-123"},
            external_cli={
                "auth_token": "token-123",
                "upstream_base_url": "https://upstream.example.test",
                "model": "model-1",
            },
            launch_methods=[{"id": "primary", "bin": "configured-launcher"}],
            app_server_port=4567,
            app_server_url="unix:///tmp/configured.sock",
            protocol="unix",
            owner_transport="unix",
            live_transport="shared_unix",
            control_mode="hybrid",
        ),
    )

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            task = object()
            manager.set_tui_sync_task("overlay-tool", task)
            captured["config_data_dir"] = manager.state.config.data_dir
            captured["tool_cfg"] = {
                "name": tool_cfg.name,
                "bin": tool_cfg.bin,
                "auth": tool_cfg.auth,
                "external_cli": tool_cfg.external_cli,
                "launch_methods": tool_cfg.launch_methods,
                "app_server_port": tool_cfg.app_server_port,
                "app_server_url": tool_cfg.app_server_url,
                "protocol": tool_cfg.protocol,
                "owner_transport": tool_cfg.owner_transport,
                "live_transport": tool_cfg.live_transport,
                "control_mode": tool_cfg.control_mode,
            }
            captured["task_accessor"] = manager.get_tui_sync_task("overlay-tool") is task
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        metadata = SimpleNamespace(
            bin="metadata-bin",
            transport=SimpleNamespace(app_server_port=0, type="http"),
            owner_transport="http",
            live_transport="http",
        )
        runtime_hooks = RuntimeHooks

    monkeypatch.setattr(bridge, "get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(bridge, "load_provider_runtime_config", lambda *args, **kwargs: config)

    adapter = asyncio.run(bridge._provider_session_adapter(Descriptor(), "overlay-tool"))

    assert adapter == {"provider_id": "overlay-tool"}
    assert captured == {
        "config_data_dir": str(tmp_path),
        "tool_cfg": {
            "name": "overlay-tool",
            "bin": "configured-launcher",
            "auth": {"auth_token": "token-123"},
            "external_cli": {
                "auth_token": "token-123",
                "upstream_base_url": "https://upstream.example.test",
                "model": "model-1",
            },
            "launch_methods": [{"id": "primary", "bin": "configured-launcher"}],
            "app_server_port": 4567,
            "app_server_url": "unix:///tmp/configured.sock",
            "protocol": "unix",
            "owner_transport": "unix",
            "live_transport": "shared_unix",
            "control_mode": "hybrid",
        },
        "task_accessor": True,
    }


def test_provider_session_adapter_uses_provider_config_without_telegram_env(monkeypatch, tmp_path):
    import asyncio

    captured = {}
    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
providers:
  claude:
    managed: true
    autostart: false
    bin: "configured-claude"
    auth:
      auth_token: "token-123"
    external_cli:
      auth_token: "token-123"
      upstream_base_url: "https://upstream.example.test"
      model: "model-1"
    launch_methods:
      - id: primary
        bin: configured-claude
    transport:
      type: stdio
logging:
  level: "INFO"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    for key in ("TELEGRAM_TOKEN", "ALLOWED_USER_ID", "GROUP_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            captured["config_data_dir"] = manager.state.config.data_dir
            captured["tool_cfg"] = {
                "name": tool_cfg.name,
                "bin": tool_cfg.bin,
                "auth": tool_cfg.auth,
                "external_cli": tool_cfg.external_cli,
                "launch_methods": tool_cfg.launch_methods,
                "protocol": tool_cfg.protocol,
            }
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        metadata = SimpleNamespace(
            bin="metadata-claude",
            transport=SimpleNamespace(app_server_port=0, type="stdio"),
            owner_transport="stdio",
            live_transport="stdio",
        )
        runtime_hooks = RuntimeHooks

    monkeypatch.setattr(bridge, "get_data_dir", lambda: str(tmp_path))

    adapter = asyncio.run(bridge._provider_session_adapter(Descriptor(), "claude"))

    assert adapter == {"provider_id": "claude"}
    assert captured == {
        "config_data_dir": str(tmp_path),
        "tool_cfg": {
            "name": "claude",
            "bin": "configured-claude",
            "auth": {
                "auth_token": "token-123",
                "base_url": "https://upstream.example.test",
                "model": "model-1",
            },
            "external_cli": {
                "auth_token": "token-123",
                "upstream_base_url": "https://upstream.example.test",
                "model": "model-1",
            },
            "launch_methods": [{"id": "primary", "label": "primary", "bin": "configured-claude"}],
            "protocol": "stdio",
        },
    }


def test_provider_session_adapter_reads_overlay_from_cwd_env(monkeypatch, tmp_path):
    import asyncio
    import config as config_module

    captured = {}
    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
logging:
  level: "INFO"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    overlay_path = tmp_path / "provider-overlay.yaml"
    overlay_path.write_text(
        """
providers:
  overlay-tool:
    managed: true
    bin: "overlay-launcher"
    auth:
      auth_token: "overlay-token"
    external_cli:
      upstream_base_url: "https://overlay.example.test"
      model: "overlay-model"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"ONLINEWORKER_PROVIDER_OVERLAY={overlay_path}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ONLINEWORKER_PROVIDER_OVERLAY", raising=False)
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("ALLOWED_USER_ID", raising=False)
    monkeypatch.delenv("GROUP_CHAT_ID", raising=False)
    monkeypatch.setattr(config_module, "_dotenv_loaded", False)

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            captured["config_data_dir"] = manager.state.config.data_dir
            captured["tool_cfg"] = {
                "name": tool_cfg.name,
                "bin": tool_cfg.bin,
                "auth": tool_cfg.auth,
                "external_cli": tool_cfg.external_cli,
            }
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        metadata = SimpleNamespace(
            bin="metadata-launcher",
            transport=SimpleNamespace(app_server_port=0, type="stdio"),
            owner_transport="stdio",
            live_transport="stdio",
        )
        runtime_hooks = RuntimeHooks

    monkeypatch.setattr(bridge, "get_data_dir", lambda: None)

    adapter = asyncio.run(bridge._provider_session_adapter(Descriptor(), "overlay-tool"))

    assert adapter == {"provider_id": "overlay-tool"}
    assert captured == {
        "config_data_dir": None,
        "tool_cfg": {
            "name": "overlay-tool",
            "bin": "overlay-launcher",
            "auth": {
                "auth_token": "overlay-token",
                "base_url": "https://overlay.example.test",
                "model": "overlay-model",
            },
            "external_cli": {
                "upstream_base_url": "https://overlay.example.test",
                "model": "overlay-model",
            },
        },
    }


def test_provider_session_adapter_exposes_lifecycle_reconnect_api(monkeypatch, tmp_path):
    import asyncio

    captured = {}
    config = SimpleNamespace(
        data_dir=str(tmp_path),
        get_tool=lambda provider_id: SimpleNamespace(
            name=provider_id,
            bin="configured-launcher",
            auth={},
            external_cli={},
            launch_methods=[],
            app_server_port=0,
            app_server_url="",
            protocol="unix",
            owner_transport="unix",
            live_transport="shared_unix",
            control_mode="app",
        ),
    )

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            captured["initial"] = manager.is_reconnect_inflight("codex")
            manager.set_reconnect_inflight("codex", True)
            captured["enabled"] = manager.is_reconnect_inflight("codex")
            manager.set_reconnect_inflight("codex", False)
            captured["disabled"] = manager.is_reconnect_inflight("codex")
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        metadata = SimpleNamespace(
            bin="metadata-codex",
            transport=SimpleNamespace(app_server_port=0, type="unix"),
            owner_transport="unix",
            live_transport="shared_unix",
        )
        runtime_hooks = RuntimeHooks

    monkeypatch.setattr(bridge, "get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(bridge, "load_provider_runtime_config", lambda *args, **kwargs: config)

    adapter = asyncio.run(bridge._provider_session_adapter(Descriptor(), "codex"))

    assert adapter == {"provider_id": "codex"}
    assert captured == {
        "initial": False,
        "enabled": True,
        "disabled": False,
    }


def test_send_provider_session_message_passes_original_text_to_provider_hook(monkeypatch):
    called = {}

    class Facts:
        @staticmethod
        def scan_workspaces():
            return [{"path": "/tmp/proj"}]

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return [{"id": "tid-1", "preview": "Thread 1"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"tid-1"}

        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            return []

    class MessageHooks:
        @staticmethod
        async def send(state, adapter, ws_info, thread_info, **kwargs):
            called["text"] = kwargs["text"]
            called["workspace_id"] = ws_info["daemon_workspace_id"]
            called["thread_id"] = thread_info["thread_id"]

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        facts = Facts
        message_hooks = MessageHooks
        metadata = type(
            "Metadata",
            (),
            {
                "bin": "overlay-tool",
                "transport": type(
                    "Transport",
                    (),
                    {
                        "app_server_port": 0,
                        "type": "http",
                    },
                )(),
                "owner_transport": "http",
                "live_transport": "http",
            },
        )()
        runtime_hooks = RuntimeHooks

    async def fake_send():
        await bridge.send_provider_session_message(
            "overlay-tool",
            "tid-1",
            "这什么傻逼问题",
            workspace_dir="/tmp/proj",
        )

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())

    import asyncio

    asyncio.run(fake_send())

    assert called == {
        "workspace_id": "overlay-tool:/tmp/proj",
        "thread_id": "tid-1",
        "text": "这什么傻逼问题",
    }


def test_send_provider_session_message_ignores_removed_global_message_hook_config(monkeypatch):
    called = {}

    class Facts:
        @staticmethod
        def scan_workspaces():
            return [{"path": "/tmp/proj"}]

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return [{"id": "tid-1", "preview": "Thread 1"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"tid-1"}

        @staticmethod
        def read_thread_history(session_id, limit=50, sessions_dir=None):
            return []

    class MessageHooks:
        @staticmethod
        async def send(state, adapter, ws_info, thread_info, **kwargs):
            called["text"] = kwargs["text"]

    class RuntimeHooks:
        @staticmethod
        async def start(manager, bot, tool_cfg):
            manager.state.set_adapter(tool_cfg.name, {"provider_id": tool_cfg.name})

    class Descriptor:
        facts = Facts
        message_hooks = MessageHooks
        metadata = type(
            "Metadata",
            (),
            {
                "bin": "overlay-tool",
                "transport": type(
                    "Transport",
                    (),
                    {
                        "app_server_port": 0,
                        "type": "http",
                    },
                )(),
                "owner_transport": "http",
                "live_transport": "http",
            },
        )()
        runtime_hooks = RuntimeHooks

    async def fake_send():
        await bridge.send_provider_session_message(
            "overlay-tool",
            "tid-1",
            "这什么傻逼问题",
            workspace_dir="/tmp/proj",
        )

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: Descriptor())
    import asyncio

    asyncio.run(fake_send())

    assert called["text"] == "这什么傻逼问题"


def test_archive_provider_session_invokes_real_thread_hook(monkeypatch):
    called = {}

    class ThreadHooks:
        @staticmethod
        async def archive_thread(state, ws_info, thread_id, adapter):
            called["adapter"] = adapter
            called["workspace_id"] = ws_info.daemon_workspace_id
            called["workspace_path"] = ws_info.path
            called["thread_id"] = thread_id
            called["state_adapter"] = state.get_adapter("overlay-tool")

    descriptor = _overlay_descriptor(thread_hooks=ThreadHooks)
    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: descriptor)

    import asyncio

    asyncio.run(
        bridge.archive_provider_session(
            "overlay-tool",
            "tid-archive",
            workspace_dir="/tmp/project-a",
        )
    )

    assert called == {
        "adapter": {"provider_id": "overlay-tool"},
        "workspace_id": "overlay-tool:/tmp/project-a",
        "workspace_path": "/tmp/project-a",
        "thread_id": "tid-archive",
        "state_adapter": {"provider_id": "overlay-tool"},
    }


def test_archive_provider_session_rejects_missing_real_archive_support(monkeypatch):
    descriptor = _overlay_descriptor(thread_hooks=None)
    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: descriptor)

    import asyncio

    try:
        asyncio.run(
            bridge.archive_provider_session(
                "overlay-tool",
                "tid-archive",
                workspace_dir="/tmp/project-a",
            )
        )
    except ValueError as exc:
        assert str(exc) == "Provider 'overlay-tool' does not expose real archive support"
    else:
        raise AssertionError("expected missing archive support error")


def test_archive_provider_session_uses_descriptor_real_archive_hook(monkeypatch):
    called = {}

    class Adapter:
        async def archive_thread(self, workspace_id, thread_id):
            called["workspace_id"] = workspace_id
            called["thread_id"] = thread_id
            return {"ok": True}

    class ThreadHooks:
        @staticmethod
        async def archive_thread(state, ws_info, thread_id, adapter):
            assert state.get_adapter("overlay-tool") is adapter
            await adapter.archive_thread(ws_info.daemon_workspace_id, thread_id)

    descriptor = _overlay_descriptor(thread_hooks=ThreadHooks)

    async def fake_provider_session_adapter(active_descriptor, provider_id):
        assert active_descriptor is descriptor
        assert provider_id == "overlay-tool"
        return Adapter()

    monkeypatch.setattr(bridge, "_load_provider_descriptor", lambda provider_id: descriptor)
    monkeypatch.setattr(bridge, "_provider_session_adapter", fake_provider_session_adapter)

    import asyncio

    asyncio.run(
        bridge.archive_provider_session(
            "overlay-tool",
            "ses_123",
            workspace_dir="/tmp/project-a",
        )
    )

    assert called == {
        "workspace_id": "overlay-tool:/tmp/project-a",
        "thread_id": "ses_123",
    }
