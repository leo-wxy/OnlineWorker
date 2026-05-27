from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


@pytest.mark.asyncio
async def test_provider_owner_bridge_uses_registry_message_hooks(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}

    class _FakeAdapter:
        def __init__(self):
            self.connected = True
            self.registered = []

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.registered.append((workspace_id, cwd))

    adapter = _FakeAdapter()
    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", adapter)

    async def ensure_connected(state_obj, current_adapter, ws_info, **kwargs):
        called["ensure_connected"] = (state_obj, current_adapter, ws_info.tool, ws_info.path)
        return current_adapter

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["prepare_send"] = (
            state_obj,
            current_adapter,
            ws_info.daemon_workspace_id,
            thread_info.thread_id,
            kwargs["text"],
        )
        return True

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["send"] = (
            state_obj,
            current_adapter,
            ws_info.daemon_workspace_id,
            thread_info.thread_id,
            kwargs["text"],
            kwargs.get("attachments"),
        )

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=ensure_connected,
                prepare_send=prepare_send,
                send=send,
            )
        )
        if name == "overlay-tool"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "overlay-tool",
            "thread_id": "tid-1",
            "text": "hello owner bridge",
            "workspace_dir": "/tmp/project-a",
            "attachments": [
                {
                    "kind": "image",
                    "path": "/tmp/project-a/image.png",
                    "name": "image.png",
                }
            ],
        }
    )

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["workspace_id"] == "overlay-tool:/tmp/project-a"
    assert adapter.registered == [("overlay-tool:/tmp/project-a", "/tmp/project-a")]
    assert called["prepare_send"][2:] == (
        "overlay-tool:/tmp/project-a",
        "tid-1",
        "hello owner bridge",
    )
    assert called["send"][2:] == (
        "overlay-tool:/tmp/project-a",
        "tid-1",
        "hello owner bridge",
        [
            {
                "kind": "image",
                "path": "/tmp/project-a/image.png",
                "name": "image.png",
            }
        ],
    )
    assert state.get_provider_runtime("overlay-tool").thread_pending_send_started_at["tid-1"] > 0


@pytest.mark.asyncio
async def test_provider_owner_bridge_keeps_text_before_registry_message_hooks_while_rewrite_is_sealed(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            pass

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["prepare_text"] = kwargs["text"]
        return True

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["send_text"] = kwargs["text"]

    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", _FakeAdapter())
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=prepare_send,
                send=send,
            )
        )
        if name == "overlay-tool"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "overlay-tool",
            "thread_id": "tid-1",
            "text": "这什么傻逼问题",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response["ok"] is True
    assert called["prepare_text"] == "这什么傻逼问题"
    assert called["send_text"] == "这什么傻逼问题"


@pytest.mark.asyncio
async def test_provider_owner_bridge_routes_text_via_provider_owner_bridge_hook(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.workspace_id = workspace_id
            self.cwd = cwd

    storage = AppStorage()
    storage.workspaces["overlay-tool:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.set_adapter("overlay-tool", _FakeAdapter())

    route_send = AsyncMock(return_value="owned_visible_cli")
    provider = SimpleNamespace(
        message_hooks=SimpleNamespace(
            ensure_connected=AsyncMock(),
            prepare_send=AsyncMock(),
            send=AsyncMock(),
            try_route_owner_bridge_send=route_send,
        )
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "overlay-tool",
            "thread_id": "tid-cli",
            "text": "hello visible cli",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response == {
        "ok": True,
        "accepted": True,
        "provider_id": "overlay-tool",
        "thread_id": "tid-cli",
        "requested_thread_id": "tid-cli",
        "remapped": False,
        "workspace_id": "overlay-tool:/tmp/project-a",
        "transport": "owned_visible_cli",
    }
    route_send.assert_awaited_once_with(
        state,
        storage.workspaces["overlay-tool:/tmp/project-a"],
        storage.workspaces["overlay-tool:/tmp/project-a"].threads["tid-cli"],
        text="hello visible cli",
    )
    provider.message_hooks.ensure_connected.assert_not_awaited()
    provider.message_hooks.prepare_send.assert_not_awaited()
    provider.message_hooks.send.assert_not_awaited()
    assert state.get_provider_runtime("overlay-tool").thread_pending_send_started_at["tid-cli"] > 0


@pytest.mark.asyncio
async def test_provider_owner_bridge_keeps_text_before_owner_bridge_router_while_rewrite_is_sealed(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            pass

    storage = AppStorage()
    storage.workspaces["overlay-tool:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.set_adapter("overlay-tool", _FakeAdapter())

    route_send = AsyncMock(return_value="owned_visible_cli")
    provider = SimpleNamespace(
        message_hooks=SimpleNamespace(
            ensure_connected=AsyncMock(),
            prepare_send=AsyncMock(),
            send=AsyncMock(),
            try_route_owner_bridge_send=route_send,
        )
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "overlay-tool",
            "thread_id": "tid-cli",
            "text": "这什么傻逼问题",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response["ok"] is True
    route_send.assert_awaited_once_with(
        state,
        storage.workspaces["overlay-tool:/tmp/project-a"],
        storage.workspaces["overlay-tool:/tmp/project-a"].threads["tid-cli"],
        text="这什么傻逼问题",
    )
    provider.message_hooks.prepare_send.assert_not_awaited()
    provider.message_hooks.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_persists_new_workspace_for_event_routing(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.workspace_id = workspace_id
            self.cwd = cwd

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        return {"threadId": thread_info.thread_id, "turnId": "turn-1", "status": "completed"}

    state = AppState(storage=AppStorage())
    state.set_adapter("claude", _FakeAdapter())
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=AsyncMock(return_value=True),
                send=send,
            ),
            thread_hooks=SimpleNamespace(
                new_imported_thread_source=lambda: "imported",
            ),
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "claude",
            "thread_id": "tid-new",
            "text": "hello",
            "workspace_dir": "/tmp/new-workspace",
        }
    )

    assert response["ok"] is True
    assert response["workspace_id"] == "claude:/tmp/new-workspace"
    assert state.find_workspace_by_daemon_id("claude:/tmp/new-workspace") is not None
    found = state.find_thread_by_id_global("tid-new")
    assert found is not None
    assert found[0].path == "/tmp/new-workspace"
    assert found[1].source == "imported"


@pytest.mark.asyncio
async def test_provider_owner_bridge_returns_send_error(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        return {"threadId": thread_info.thread_id, "turnId": "turn-1", "status": "error", "error": "boom"}

    state = AppState(storage=AppStorage())
    state.set_adapter("claude", _FakeAdapter())
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=AsyncMock(return_value=True),
                send=send,
            )
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "claude",
            "thread_id": "tid-new",
            "text": "hello",
            "workspace_dir": "/tmp/new-workspace",
        }
    )

    assert response == {
        "ok": False,
        "error": "boom",
        "provider_id": "claude",
        "thread_id": "tid-new",
        "workspace_id": "claude:/tmp/new-workspace",
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_rolls_back_remapped_thread_when_send_errors(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            pass

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="claude",
        daemon_workspace_id="claude:onlineWorker",
        threads={
            "ses-imported": ThreadInfo(
                thread_id="ses-imported",
                source="imported",
                preview="历史导入 thread",
            )
        },
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)
    state.set_adapter("claude", _FakeAdapter())

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        ws_info.threads.pop(thread_info.thread_id)
        thread_info.thread_id = "ses-app-new"
        thread_info.source = "app"
        ws_info.threads[thread_info.thread_id] = thread_info
        return True

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        return {"threadId": thread_info.thread_id, "turnId": "turn-1", "status": "error", "error": "boom"}

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=prepare_send,
                send=send,
            )
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "claude",
            "thread_id": "ses-imported",
            "text": "hello",
            "workspace_dir": "/Users/example/Projects/onlineWorker",
        }
    )

    assert response["ok"] is False
    assert set(ws.threads) == {"ses-imported"}
    assert ws.threads["ses-imported"].thread_id == "ses-imported"
    assert ws.threads["ses-imported"].source == "imported"
    assert ws.threads["ses-imported"].preview == "历史导入 thread"


@pytest.mark.asyncio
async def test_provider_owner_bridge_prefers_existing_workspace_thread_binding(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        def __init__(self):
            self.connected = True

        async def resume_thread(self, workspace_id: str, thread_id: str):
            return {}

        async def send_user_message(self, workspace_id: str, thread_id: str, text: str):
            return {}

    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="overlay-tool",
        daemon_workspace_id="ws-1",
        threads={"tid-1": ThreadInfo(thread_id="tid-1", archived=False)},
    )
    state = AppState(storage=AppStorage(workspaces={"overlay-tool:onlineWorker": ws}))
    state.set_adapter("overlay-tool", _FakeAdapter())

    send = AsyncMock()
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=AsyncMock(return_value=True),
                send=send,
            )
        )
        if name == "overlay-tool"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "overlay-tool",
            "thread_id": "tid-1",
            "text": "reuse existing thread",
            "workspace_dir": "/tmp/ignored-by-existing-binding",
        }
    )

    assert response["ok"] is True
    assert response["workspace_id"] == "ws-1"
    assert send.await_args.args[2] is ws
    assert send.await_args.args[3] is ws.threads["tid-1"]


@pytest.mark.asyncio
async def test_provider_owner_bridge_reads_latest_session_turns_via_provider_facts(
    monkeypatch, tmp_path
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    observed = {}
    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=20, sessions_dir=None):
            observed["session_id"] = session_id
            observed["limit"] = limit
            observed["sessions_dir"] = sessions_dir
            return [
                {"role": "system", "text": "skip me"},
                {"role": "user", "text": "hello"},
                {"role": "assistant", "content": "world"},
                {"role": "assistant", "text": "   "},
            ]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_read_session(
        {
            "provider_id": "overlay-tool",
            "session_id": "tid-77",
            "workspace_dir": "/tmp/project-a",
            "limit": 12,
        }
    )

    assert response == {
        "ok": True,
        "session": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "world"},
        ],
    }
    assert observed == {
        "session_id": "tid-77",
        "limit": 12,
        "sessions_dir": None,
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_preserves_visible_error_metadata(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=20, sessions_dir=None):
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

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_read_session(
        {
            "provider_id": "overlay-tool",
            "session_id": "tid-error",
            "limit": 20,
        }
    )

    assert response == {
        "ok": True,
        "session": [
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
        ],
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_does_not_treat_workspace_dir_as_sessions_dir(
    monkeypatch, tmp_path
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    observed = {}
    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=20, sessions_dir=None):
            observed["session_id"] = session_id
            observed["limit"] = limit
            observed["sessions_dir"] = sessions_dir
            return [
                {"role": "user", "text": "图片主色调是什么？"},
                {"role": "assistant", "text": "偏青绿色"},
            ]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "codex" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_read_session(
        {
            "provider_id": "codex",
            "session_id": "tid-codex",
            "workspace_dir": "/Users/example/project/subdir",
            "limit": 8,
        }
    )

    assert response == {
        "ok": True,
        "session": [
            {"role": "user", "content": "图片主色调是什么？"},
            {"role": "assistant", "content": "偏青绿色"},
        ],
    }
    assert observed == {
        "session_id": "tid-codex",
        "limit": 8,
        "sessions_dir": None,
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_lists_sessions_via_provider_facts(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    observed = {"list_limits": [], "active_calls": []}
    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def scan_workspaces(sessions_dir=None):
            return [
                {"path": "/tmp/beta"},
                {"path": "/tmp/alpha"},
            ]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            observed["active_calls"].append(workspace_path)
            return {"tid-2"} if workspace_path == "/tmp/beta" else {"tid-1"}

        @staticmethod
        def list_threads(workspace_path, limit=100):
            observed["list_limits"].append((workspace_path, limit))
            if workspace_path == "/tmp/beta":
                return [{"id": "tid-2", "preview": "Beta", "updatedAt": 20}]
            return [{"id": "tid-1", "preview": "Alpha", "updatedAt": 10}]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 77,
        }
    )

    assert response == {
        "ok": True,
        "sessions": [
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
        ],
    }
    assert observed["list_limits"] == [
        ("/tmp/beta", 77),
        ("/tmp/alpha", 77),
    ]


@pytest.mark.asyncio
async def test_provider_owner_bridge_reports_runtime_status_via_status_builder(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", _FakeAdapter())

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            status_builder=lambda current_state: ["• overlay-tool：✅ 已连接"]
        )
        if name == "overlay-tool"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_runtime_status(
        {
            "provider_id": "overlay-tool",
        }
    )

    assert response == {
        "ok": True,
        "health": "healthy",
        "detail": "• overlay-tool：✅ 已连接",
        "lines": ["• overlay-tool：✅ 已连接"],
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_mirrors_cli_approval_with_tg_buttons_without_waiting(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，请在 CLI 中完成审批。",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "tool_input": {"command": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "shell",
            },
        }
    )

    assert response == {"ok": True}
    sent.assert_awaited_once()
    args = sent.await_args.args
    kwargs = sent.await_args.kwargs
    assert args[:5] == (state, state.telegram_bot, state.group_chat_id, 7653, "codex:/tmp/project-a")
    info = args[5]
    assert info.request_id == "provider-cli-hook"
    assert info.thread_id == "tid-cli"
    assert info.command == "/bin/zsh -lc 'ps -axo pid,command'"
    assert info.reason == "源 CLI 正在请求本地权限审批。"
    assert info.tool_name == "shell"
    assert info.tool_type == "codex"
    assert info.approval_source == "codex_cli_hook"
    assert kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_reads_cli_hook_command_from_tool_input_cmd(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "tool_input": {"cmd": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "exec_command",
            },
        }
    )

    assert response == {"ok": True}
    info = sent.await_args.args[5]
    assert info.command == "/bin/zsh -lc 'ps -axo pid,command'"


@pytest.mark.asyncio
async def test_provider_owner_bridge_makes_cli_hook_approval_interactive_for_owned_codex_tui_host(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                mirror_approval_policy=AsyncMock(
                    return_value={
                        "interactive": True,
                        "request_id": "codex-tui-host:tid-cli",
                        "approval_source": "codex_tui_host",
                        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
                    }
                )
            )
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "owned_tui_host": True,
            "source": "codex_cli_hook",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "tool_input": {"command": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "shell",
            },
        }
    )

    assert response == {"ok": True}
    sent.assert_awaited_once()
    kwargs = sent.await_args.kwargs
    assert kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
    }
    info = sent.await_args.args[5]
    assert info.request_id == "codex-tui-host:tid-cli"
    assert info.approval_source == "codex_tui_host"


@pytest.mark.asyncio
async def test_provider_owner_bridge_uses_policy_notice_suffix_for_interactive_cli_mirror(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                mirror_approval_policy=AsyncMock(
                    return_value={
                        "interactive": True,
                        "request_id": "codex-tui-host:tid-cli",
                        "approval_source": "codex_tui_host",
                        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
                    }
                )
            )
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，请在 CLI 中完成审批。",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "tool_input": {"command": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "shell",
            },
        }
    )

    assert response == {"ok": True}
    assert sent.await_args.kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
    }
    info = sent.await_args.args[5]
    assert info.request_id == "codex-tui-host:tid-cli"
    assert info.approval_source == "codex_tui_host"


@pytest.mark.asyncio
async def test_provider_owner_bridge_uses_provider_neutral_notice_suffix_fallback(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["custom:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="custom",
        daemon_workspace_id="custom:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                mirror_approval_policy=AsyncMock(
                    return_value={
                        "interactive": True,
                        "approval_source": "custom_cli_hook",
                    }
                )
            )
        )
        if name == "custom"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "custom",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "custom_cli_hook",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "tool_input": {"command": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "shell",
            },
        }
    )

    assert response == {"ok": True}
    assert sent.await_args.kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在源工具中弹出，可在源工具或 TG 中处理。",
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_makes_external_cli_hook_mirror_interactive(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "payload": {
                "hook_event_name": "PermissionRequest",
                "request_id": "codex-cli-hook:tid-cli:abc",
                "tool_input": {"command": "/bin/zsh -lc 'ps -axo pid,command'"},
                "tool_name": "shell",
            },
        }
    )

    assert response == {"ok": True}
    assert sent.await_args.kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
    }
    info = sent.await_args.args[5]
    assert info.request_id == "codex-cli-hook:tid-cli:abc"
    assert info.approval_source == "codex_cli_hook"


@pytest.mark.asyncio
async def test_provider_owner_bridge_discards_current_session_approval_without_bound_topic(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.global_topic_ids = {"codex": 5339}
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-current": ThreadInfo(
                thread_id="tid-current",
                topic_id=None,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-current",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_current_session_log",
            "notice_suffix": "此请求已在当前 Codex 会话中弹出，请在 Codex CLI/Desktop 中完成审批。",
            "payload": {
                "hook_event_name": "ExecApprovalRequest",
                "request_id": "codex-current-session:abc",
                "command": "/bin/zsh -lc 'printf approval'",
                "reason": "approval needed",
            },
        }
    )

    assert response == {
        "ok": True,
        "discarded": True,
        "reason": "会话未绑定 TG topic，已跳过 TG 审批镜像",
    }
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_makes_current_session_approval_interactive_for_owned_tui_host(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-current": ThreadInfo(
                thread_id="tid-current",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.runtime.can_route_cli_approval_to_tui_host",
        lambda state_obj, thread_id: thread_id == "tid-current",
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-current",
            "workspace_dir": "/tmp/project-a",
            "owned_tui_host": True,
            "source": "codex_current_session_log",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
            "payload": {
                "hook_event_name": "ExecApprovalRequest",
                "request_id": "codex-current-session:abc",
                "command": "/bin/zsh -lc 'printf approval'",
                "reason": "approval needed",
            },
        }
    )

    assert response == {"ok": True}
    sent.assert_awaited_once()
    info = sent.await_args.args[5]
    assert info.request_id == "codex-current-session:abc"
    assert info.approval_source == "codex_tui_host"
    assert sent.await_args.kwargs == {
        "interactive": True,
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_dedupes_duplicate_approval_mirrors(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-current": ThreadInfo(
                thread_id="tid-current",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                mirror_approval_policy=AsyncMock(
                    return_value={
                        "interactive": True,
                        "request_id": "codex-tui-host:tid-current",
                        "approval_source": "codex_tui_host",
                    }
                )
            )
        )
        if name == "codex"
        else None,
    )
    request = {
        "type": "mirror_approval",
        "provider_id": "codex",
        "thread_id": "tid-current",
        "workspace_dir": "/tmp/project-a",
        "owned_tui_host": True,
        "payload": {
            "hook_event_name": "ExecApprovalRequest",
            "request_id": "codex-current-session:abc",
            "command": "/bin/zsh -lc 'printf approval'",
            "reason": "approval needed",
        },
    }

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    first = await bridge._handle_mirror_approval(request)
    second = await bridge._handle_mirror_approval(request)

    assert first == {"ok": True}
    assert second == {"ok": True, "deduped": True}
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_owner_bridge_dedupes_duplicate_interactive_mirror(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-current": ThreadInfo(
                thread_id="tid-current",
                topic_id=7653,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                mirror_approval_policy=AsyncMock(
                    return_value={
                        "interactive": True,
                        "request_id": "codex-tui-host:tid-current",
                        "approval_source": "codex_tui_host",
                    }
                )
            )
        )
        if name == "codex"
        else None,
    )
    request = {
        "type": "mirror_approval",
        "provider_id": "codex",
        "thread_id": "tid-current",
        "workspace_dir": "/tmp/project-a",
        "payload": {
            "hook_event_name": "ExecApprovalRequest",
            "request_id": "codex-current-session:abc",
            "command": "/bin/zsh -lc 'printf approval'",
            "reason": "approval needed",
        },
    }

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    first = await bridge._handle_mirror_approval(request)
    second = await bridge._handle_mirror_approval(request)

    assert first == {"ok": True}
    assert second == {"ok": True, "deduped": True}
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_owner_bridge_mirror_approval_does_not_persist_missing_workspace(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.global_topic_ids = {"codex": 5339}
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    def fail_save_storage(_storage):
        raise AssertionError("mirror approval must not persist fallback workspace/thread")

    monkeypatch.setattr("core.provider_owner_bridge.save_storage", fail_save_storage)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-untracked",
            "workspace_dir": "/tmp/untracked-project",
            "source": "codex_current_session_log",
            "payload": {
                "hook_event_name": "ExecApprovalRequest",
                "request_id": "codex-current-session:def",
                "command": "/bin/zsh -lc 'printf approval'",
            },
        }
    )

    assert storage.workspaces == {}
    assert state.find_thread_by_id_global("tid-untracked") is None
    assert response == {
        "ok": True,
        "discarded": True,
        "reason": "会话未绑定 TG topic，已跳过 TG 审批镜像",
    }
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_skips_blocking_cli_hook_without_bound_topic(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.global_topic_ids = {"codex": 5339}
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        topic_id=None,
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=None,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    sent = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", sent)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "blocking": True,
            "payload": {
                "hook_event_name": "PermissionRequest",
                "request_id": "codex-cli-hook:tid-cli:abc",
                "command": "/bin/zsh -lc 'printf approval'",
            },
        }
    )

    assert response == {
        "ok": True,
        "discarded": True,
        "reason": "会话未绑定 TG topic，已跳过 TG 审批镜像",
    }
    sent.assert_not_awaited()
    assert state.get_provider_runtime("codex").pending_approval_decisions == {}


@pytest.mark.asyncio
async def test_provider_owner_bridge_waits_for_blocking_cli_hook_approval(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                topic_id=7653,
                source="imported",
            )
        },
    )
    state = AppState(storage=storage)
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

    async def fake_send_approval_to_telegram(*args, **kwargs):
        state.resolve_pending_approval_decision("codex", "codex-cli-hook:tid-cli:abc", "allow")

    monkeypatch.setattr("bot.events.send_approval_to_telegram", fake_send_approval_to_telegram)

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_mirror_approval(
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-cli",
            "workspace_dir": "/tmp/project-a",
            "source": "codex_cli_hook",
            "blocking": True,
            "payload": {
                "hook_event_name": "PermissionRequest",
                "request_id": "codex-cli-hook:tid-cli:abc",
                "command": "/bin/zsh -lc 'ps -axo pid,command'",
                "reason": "inspect processes",
            },
        }
    )

    assert response == {"ok": True, "decision": "allow"}
