import pytest

from plugins.providers.builtin.codex.python.owner_bridge import CodexOwnerBridge, ensure_codex_owner_bridge_started
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


class _FakeAdapter:
    def __init__(self):
        self.connected = True
        self.calls = []
        self._thread_workspace_map = {}

    async def resume_thread(self, workspace_id: str, thread_id: str):
        self.calls.append(("resume", workspace_id, thread_id))
        return {}

    async def send_user_message(self, workspace_id: str, thread_id: str, text: str):
        self.calls.append(("send", workspace_id, thread_id, text))
        return {}

    async def _call(self, method: str, params: dict):
        self.calls.append(("call", method, params))
        return {}


@pytest.mark.asyncio
async def test_codex_owner_bridge_uses_workspace_mapping_when_cwd_matches(tmp_path):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="ws-1",
        threads={"tid-1": ThreadInfo(thread_id="tid-1")},
    )
    state = AppState(storage=AppStorage(workspaces={"codex:onlineWorker": ws}))
    state.set_adapter("codex", _FakeAdapter())
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-1",
        "text": "hello",
        "cwd": "/Users/wxy/Projects/onlineWorker",
    })

    assert response["ok"] is True
    assert state.get_adapter("codex").calls == [
        ("resume", "ws-1", "tid-1"),
        ("send", "ws-1", "tid-1", "hello"),
    ]
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-1"] > 0


@pytest.mark.asyncio
async def test_codex_owner_bridge_falls_back_to_owner_rpc_without_workspace(tmp_path):
    state = AppState()
    state.set_adapter("codex", _FakeAdapter())
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-2",
        "text": "hello fallback",
    })

    assert response["ok"] is True
    assert state.get_adapter("codex").calls == [
        ("call", "thread/resume", {"threadId": "tid-2"}),
        (
            "call",
            "turn/start",
            {
                "threadId": "tid-2",
                "input": [{"type": "text", "text": "hello fallback"}],
            },
        ),
    ]
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-2"] > 0


@pytest.mark.asyncio
async def test_ensure_codex_owner_bridge_started_skips_when_data_dir_is_missing():
    state = AppState()
    state.set_adapter("codex", _FakeAdapter())

    bridge = await ensure_codex_owner_bridge_started(state)

    assert bridge is None
    assert codex_state.get_owner_bridge(state) is None
