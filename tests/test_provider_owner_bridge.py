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
    )
    assert state.get_provider_runtime("overlay-tool").thread_pending_send_started_at["tid-1"] > 0


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
        "sessions_dir": "/tmp/project-a",
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
