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
