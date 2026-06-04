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
        self.registered = []
        self.fail_send_for = {}
        self.start_thread_result = {"id": "tid-new"}

    async def resume_thread(self, workspace_id: str, thread_id: str):
        self.calls.append(("resume", workspace_id, thread_id))
        return {}

    async def start_thread(self, workspace_id: str):
        self.calls.append(("start", workspace_id))
        return self.start_thread_result

    async def send_user_message(
        self,
        workspace_id: str,
        thread_id: str,
        text: str,
        attachments=None,
        **kwargs,
    ):
        maybe_error = self.fail_send_for.get(thread_id)
        if maybe_error is not None:
            raise maybe_error
        self.calls.append(("send", workspace_id, thread_id, text, attachments, kwargs))
        return {}

    def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
        self.registered.append((workspace_id, cwd))

    async def _call(self, method: str, params: dict):
        self.calls.append(("call", method, params))
        return {}


@pytest.mark.asyncio
async def test_codex_owner_bridge_uses_workspace_mapping_when_cwd_matches(tmp_path):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
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
        "cwd": "/Users/example/Projects/onlineWorker",
    })

    assert response["ok"] is True
    assert state.get_adapter("codex").calls == [
        ("resume", "ws-1", "tid-1"),
        ("send", "ws-1", "tid-1", "hello", [], {}),
    ]
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-1"] > 0
    assert [event["kind"] for event in state.message_bus.recent_events()] == [
        "message.user.submitted",
        "message.user.accepted",
    ]
    activity = state.message_bus.session_activity("codex", "tid-1")
    assert activity["workspaceId"] == "ws-1"
    assert activity["lastUserMessage"] == "hello"
    assert activity["status"] == "running"


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
                "approvalsReviewer": "user",
            },
        ),
    ]
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-2"] > 0


@pytest.mark.asyncio
async def test_codex_owner_bridge_forwards_approval_and_sandbox_overrides(tmp_path):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
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
        "cwd": "/Users/example/Projects/onlineWorker",
        "approval_policy": "on-request",
        "sandbox_policy": {"type": "workspace-write", "network_access": False},
    })

    assert response["ok"] is True
    assert state.get_adapter("codex").calls == [
        ("resume", "ws-1", "tid-1"),
        (
            "send",
            "ws-1",
            "tid-1",
            "hello",
            [],
            {
                "approval_policy": "on-request",
                "sandbox_policy": {"type": "workspace-write", "network_access": False},
            },
        ),
    ]


@pytest.mark.asyncio
async def test_codex_owner_bridge_forwards_attachments_to_adapter(tmp_path):
    state = AppState()
    state.set_adapter("codex", _FakeAdapter())
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-3",
        "text": "look",
        "cwd": "/tmp/project-a",
        "attachments": [
            {
                "kind": "image",
                "path": "/tmp/project-a/image.png",
                "name": "image.png",
            }
        ],
    })

    assert response["ok"] is True
    assert response["workspace_id"] == "codex:/tmp/project-a"
    assert state.get_adapter("codex").registered == [
        ("codex:/tmp/project-a", "/tmp/project-a"),
    ]
    assert state.get_adapter("codex").calls == [
        ("resume", "codex:/tmp/project-a", "tid-3"),
        (
            "send",
            "codex:/tmp/project-a",
            "tid-3",
            "look",
            [
                {
                    "kind": "image",
                    "path": "/tmp/project-a/image.png",
                    "name": "image.png",
                }
            ],
            {},
        ),
    ]


@pytest.mark.asyncio
async def test_codex_owner_bridge_synthesizes_workspace_binding_from_external_cwd(tmp_path):
    state = AppState()
    adapter = _FakeAdapter()
    state.set_adapter("codex", adapter)
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-external",
        "text": "review this screenshot",
        "cwd": "/Users/example/Projects/player-lite",
        "attachments": [
            {
                "kind": "image",
                "path": "/Users/example/Projects/player-lite/tmp/screenshot.png",
                "name": "screenshot.png",
            }
        ],
    })

    assert response["ok"] is True
    assert response["workspace_id"] == "codex:/Users/example/Projects/player-lite"
    assert adapter.registered == [
        ("codex:/Users/example/Projects/player-lite", "/Users/example/Projects/player-lite"),
    ]
    assert adapter._thread_workspace_map["tid-external"] == "codex:/Users/example/Projects/player-lite"
    assert adapter.calls == [
        ("resume", "codex:/Users/example/Projects/player-lite", "tid-external"),
        (
            "send",
            "codex:/Users/example/Projects/player-lite",
            "tid-external",
            "review this screenshot",
            [
                {
                    "kind": "image",
                    "path": "/Users/example/Projects/player-lite/tmp/screenshot.png",
                    "name": "screenshot.png",
                }
            ],
            {},
        ),
    ]


@pytest.mark.asyncio
async def test_codex_owner_bridge_persists_workspace_for_successful_external_send(tmp_path):
    state = AppState()
    adapter = _FakeAdapter()
    state.set_adapter("codex", adapter)
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-cli",
        "text": "hello",
        "cwd": "/Users/wxy",
    })

    assert response["ok"] is True
    assert state.storage is not None
    ws = state.storage.workspaces.get("codex:/Users/wxy")
    assert ws is not None
    assert ws.tool == "codex"
    assert ws.path == "/Users/wxy"
    assert ws.daemon_workspace_id == "codex:/Users/wxy"


@pytest.mark.asyncio
async def test_codex_owner_bridge_remaps_external_thread_when_send_hits_unmaterialized_error(tmp_path):
    ws = WorkspaceInfo(
        name="wxy",
        path="/Users/wxy",
        tool="codex",
        daemon_workspace_id="codex:/Users/wxy",
        threads={
            "tid-cli": ThreadInfo(
                thread_id="tid-cli",
                preview="who are you",
                is_active=True,
                source="cli",
            )
        },
    )
    state = AppState(storage=AppStorage(workspaces={"codex:/Users/wxy": ws}))
    adapter = _FakeAdapter()
    adapter.fail_send_for["tid-cli"] = RuntimeError("no rollout found for thread id tid-cli")
    adapter.start_thread_result = {"id": "tid-app"}
    state.set_adapter("codex", adapter)
    bridge = CodexOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_send_message({
        "thread_id": "tid-cli",
        "text": "hello with image",
        "cwd": "/Users/wxy",
        "attachments": [
            {
                "kind": "image",
                "path": "/Users/wxy/Pictures/demo.png",
                "name": "demo.png",
            }
        ],
    })

    assert response["ok"] is True
    assert response["requested_thread_id"] == "tid-cli"
    assert response["thread_id"] == "tid-app"
    assert response["created_new_thread"] is True
    assert adapter.calls == [
        ("resume", "codex:/Users/wxy", "tid-cli"),
        ("start", "codex:/Users/wxy"),
        ("resume", "codex:/Users/wxy", "tid-app"),
        (
            "send",
            "codex:/Users/wxy",
            "tid-app",
            "hello with image",
            [
                {
                    "kind": "image",
                    "path": "/Users/wxy/Pictures/demo.png",
                    "name": "demo.png",
                }
            ],
            {},
        ),
    ]
    assert ws.threads["tid-cli"].source == "cli"
    assert ws.threads["tid-app"].source == "app"
    assert ws.threads["tid-app"].preview == "who are you"
    assert adapter._thread_workspace_map["tid-app"] == "codex:/Users/wxy"


@pytest.mark.asyncio
@pytest.mark.allow_missing_data_dir
async def test_ensure_codex_owner_bridge_started_skips_when_data_dir_is_missing():
    state = AppState()
    state.set_adapter("codex", _FakeAdapter())

    bridge = await ensure_codex_owner_bridge_started(state)

    assert bridge is None
    assert codex_state.get_owner_bridge(state) is None
