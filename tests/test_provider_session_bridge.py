from core import provider_session_bridge as bridge


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
            "workspace": "/tmp/beta",
            "archived": False,
            "updatedAt": 20,
            "createdAt": 20,
        },
        {
            "id": "tid-1",
            "title": "Alpha",
            "workspace": "/tmp/alpha",
            "archived": False,
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
    assert result[1]["archived"] is True


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
                "bin": tool_cfg.codex_bin,
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
