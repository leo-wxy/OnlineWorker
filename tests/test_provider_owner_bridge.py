import json
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.state import AppState
from core.messages import MessageEventBus, create_message_event
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


@pytest.mark.asyncio
async def test_provider_owner_bridge_serves_provider_usage_summary(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}

    def get_summary(start_date, end_date):
        called["range"] = (start_date, end_date)
        return {
            "days": [
                {
                    "date": "2026-05-21",
                    "inputTokens": 9,
                    "outputTokens": 1,
                    "cacheCreationTokens": 2,
                    "cacheReadTokens": 3,
                    "totalTokens": 15,
                    "totalCostUsd": None,
                }
            ]
        }

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            usage_hooks=SimpleNamespace(get_summary=get_summary)
        )
        if name == "overlay-tool"
        else None,
    )
    monkeypatch.setattr("core.provider_session_bridge._unix_time_seconds", lambda: 1770000000)

    bridge = ProviderOwnerBridge(AppState(storage=AppStorage()), data_dir=str(tmp_path))
    response = await bridge._handle_usage_summary(
        {
            "provider_id": "overlay-tool",
            "start_date": "2026-05-20",
            "end_date": "2026-05-21",
        }
    )

    assert called["range"] == ("2026-05-20", "2026-05-21")
    assert response == {
        "ok": True,
        "summary": {
            "providerId": "overlay-tool",
            "days": [
                {
                    "date": "2026-05-21",
                    "inputTokens": 9,
                    "outputTokens": 1,
                    "cacheCreationTokens": 2,
                    "cacheReadTokens": 3,
                    "totalTokens": 15,
                    "totalCostUsd": None,
                }
            ],
            "updatedAtEpoch": 1770000000,
            "unsupportedReason": None,
        },
    }


@pytest.mark.asyncio
async def test_provider_owner_bridge_streams_session_activity_from_message_bus(tmp_path):
    import asyncio

    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={"text": "initial task"},
            created_at=10,
        )
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    socket_path = f"/tmp/ow-bridge-{os.getpid()}.sock"
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(bridge._handle_client, path=socket_path)
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"type":"session_activity_stream","limit":20}\n')
        await writer.drain()

        snapshot = json.loads((await reader.readline()).decode("utf-8"))
        assert snapshot["kind"] == "snapshot"
        assert snapshot["activities"][0]["lastUserMessage"] == "initial task"

        state.message_bus.publish(
            create_message_event(
                "message.assistant.delta",
                provider_id="codex",
                workspace_id="codex:/tmp/project",
                workspace_path="/tmp/project",
                session_id="thread-a",
                payload={"delta": "new assistant text"},
                created_at=20,
            )
        )

        update = json.loads((await reader.readline()).decode("utf-8"))
        assert update["kind"] == "activity"
        assert update["activity"]["lastAssistantMessage"] == "new assistant text"
        assert update["event"]["kind"] == "message.assistant.delta"

        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass


@pytest.mark.asyncio
async def test_provider_owner_bridge_activity_stream_does_not_drop_startup_event(tmp_path):
    import asyncio

    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={"text": "initial task"},
            created_at=10,
        )
    )
    original_session_activities = state.message_bus.session_activities
    startup_event_sent = False

    def session_activities_with_startup_publish():
        nonlocal startup_event_sent
        activities = original_session_activities()
        if not startup_event_sent:
            startup_event_sent = True
            state.message_bus.publish(
                create_message_event(
                    "message.assistant.delta",
                    provider_id="codex",
                    workspace_id="codex:/tmp/project",
                    workspace_path="/tmp/project",
                    session_id="thread-a",
                    payload={"delta": "startup assistant text"},
                    created_at=20,
                )
            )
        return activities

    state.message_bus.session_activities = session_activities_with_startup_publish
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    socket_path = f"/tmp/ow-bridge-startup-{os.getpid()}.sock"
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(bridge._handle_client, path=socket_path)
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"type":"session_activity_stream","limit":20}\n')
        await writer.drain()

        snapshot = json.loads((await reader.readline()).decode("utf-8"))
        assert snapshot["kind"] == "snapshot"
        assert snapshot["activities"][0]["lastUserMessage"] == "initial task"

        update = json.loads((await reader.readline()).decode("utf-8"))
        assert update["kind"] == "activity"
        assert update["activity"]["lastAssistantMessage"] == "startup assistant text"
        assert update["event"]["kind"] == "message.assistant.delta"

        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass


@pytest.mark.asyncio
async def test_provider_owner_bridge_filters_archived_session_activities(tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(
        storage=AppStorage(
            workspaces={
                "external:/tmp/project": WorkspaceInfo(
                    name="project",
                    path="/tmp/project",
                    tool="external",
                    daemon_workspace_id="external:/tmp/project",
                    threads={
                        "ses-archived": ThreadInfo(
                            thread_id="ses-archived",
                            archived=True,
                            is_active=False,
                            source="app",
                        )
                    },
                )
            }
        )
    )
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "turn.started",
            provider_id="external",
            workspace_id="external:/tmp/project",
            workspace_path="/tmp/project",
            session_id="ses-archived",
            created_at=10,
        )
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_session_activities({"limit": 20})

    assert response == {"ok": True, "activities": []}


@pytest.mark.asyncio
async def test_provider_owner_bridge_activity_stream_emits_remove_for_archived_session(tmp_path):
    import asyncio

    from core.messages.publishing import publish_session_archived
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(
        storage=AppStorage(
            workspaces={
                "external:/tmp/project": WorkspaceInfo(
                    name="project",
                    path="/tmp/project",
                    tool="external",
                    daemon_workspace_id="external:/tmp/project",
                    threads={
                        "ses-archived": ThreadInfo(
                            thread_id="ses-archived",
                            archived=False,
                            is_active=True,
                            source="app",
                        )
                    },
                )
            }
        )
    )
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "turn.started",
            provider_id="external",
            workspace_id="external:/tmp/project",
            workspace_path="/tmp/project",
            session_id="ses-archived",
            created_at=10,
        )
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    socket_path = f"/tmp/ow-bridge-archive-remove-{os.getpid()}.sock"
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(bridge._handle_client, path=socket_path)
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"type":"session_activity_stream","limit":20}\n')
        await writer.drain()

        snapshot = json.loads((await reader.readline()).decode("utf-8"))
        assert snapshot["kind"] == "snapshot"
        assert snapshot["activities"][0]["sessionId"] == "ses-archived"

        state.storage.workspaces["external:/tmp/project"].threads["ses-archived"].archived = True
        assert publish_session_archived(
            state,
            provider_id="external",
            workspace_id="external:/tmp/project",
            workspace_path="/tmp/project",
            session_id="ses-archived",
        ) is True

        update = json.loads((await reader.readline()).decode("utf-8"))
        assert update["kind"] == "remove"
        assert update["providerId"] == "external"
        assert update["sessionId"] == "ses-archived"

        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass


@pytest.mark.asyncio
async def test_provider_owner_bridge_session_activities_not_blocked_by_slow_list_sessions(
    monkeypatch,
    tmp_path,
):
    import asyncio

    from core.provider_owner_bridge import ProviderOwnerBridge

    class Facts:
        @staticmethod
        def scan_workspaces(sessions_dir=None):
            return [{"path": "/tmp/slow-workspace"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            return {"tid-1"}

        @staticmethod
        def list_threads(workspace_path, limit=100):
            time.sleep(0.2)
            return [{"id": "tid-1", "preview": "Slow thread", "updatedAt": 10}]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )
    monkeypatch.setattr("core.provider_owner_bridge.OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS", 1.0)

    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={"text": "initial task"},
            created_at=10,
        )
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    socket_path = f"/tmp/ow-bridge-concurrent-{os.getpid()}.sock"
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(bridge._handle_client, path=socket_path)
    try:
        list_reader, list_writer = await asyncio.open_unix_connection(socket_path)
        list_writer.write(b'{"type":"list_sessions","provider_id":"overlay-tool","limit":20}\n')
        await list_writer.drain()

        await asyncio.sleep(0.02)

        started = time.perf_counter()
        activity_reader, activity_writer = await asyncio.open_unix_connection(socket_path)
        activity_writer.write(b'{"type":"session_activities","limit":20}\n')
        await activity_writer.drain()
        activity_response = json.loads((await activity_reader.readline()).decode("utf-8"))
        elapsed = time.perf_counter() - started

        assert activity_response["ok"] is True
        assert activity_response["activities"][0]["lastUserMessage"] == "initial task"
        assert elapsed < 0.12

        list_response = json.loads((await list_reader.readline()).decode("utf-8"))
        assert list_response["ok"] is True
        assert list_response["sessions"][0]["id"] == "tid-1"

        activity_writer.close()
        list_writer.close()
        await activity_writer.wait_closed()
        await list_writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()
        try:
            os.remove(socket_path)
        except FileNotFoundError:
            pass


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
    assert [event["kind"] for event in state.message_bus.recent_events()] == [
        "message.user.submitted",
        "message.user.accepted",
    ]
    activity = state.message_bus.session_activity("overlay-tool", "tid-1")
    assert activity["workspacePath"] == "/tmp/project-a"
    assert activity["lastUserMessage"] == "hello owner bridge"
    assert activity["status"] == "running"


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
async def test_provider_owner_bridge_returns_and_persists_remapped_thread(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            pass

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
        threads={
            "synthetic-thread": ThreadInfo(
                thread_id="synthetic-thread",
                source="app",
                preview="new app thread",
            )
        },
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)
    state.set_adapter("codex", _FakeAdapter())

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        ws_info.threads.pop(thread_info.thread_id)
        thread_info.thread_id = "real-thread"
        thread_info.source = "app"
        ws_info.threads[thread_info.thread_id] = thread_info
        return True

    send = AsyncMock(return_value={"threadId": "real-thread", "turnId": "turn-1"})
    save_mock = MagicMock()
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=AsyncMock(return_value=state.get_adapter(name)),
                prepare_send=prepare_send,
                send=send,
            )
        )
        if name == "codex"
        else None,
    )
    monkeypatch.setattr("core.provider_owner_bridge.save_storage", lambda current_storage: save_mock(current_storage))

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_send_message(
        {
            "provider_id": "codex",
            "thread_id": "synthetic-thread",
            "text": "hello",
            "workspace_dir": "/Users/example/Projects/onlineWorker",
        }
    )

    assert response["ok"] is True
    assert response["thread_id"] == "real-thread"
    assert response["requested_thread_id"] == "synthetic-thread"
    assert response["remapped"] is True
    assert set(ws.threads) == {"real-thread"}
    assert ws.threads["real-thread"].preview == "new app thread"
    save_mock.assert_called_once_with(storage)
    send.assert_awaited_once()


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
async def test_provider_owner_bridge_list_sessions_times_out_slow_facts(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def scan_workspaces(sessions_dir=None):
            time.sleep(0.05)
            return [{"path": "/tmp/alpha"}]

    monkeypatch.setattr("core.provider_owner_bridge.OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )

    assert response["ok"] is False
    assert "overlay-tool.scan_workspaces timed out after 10ms" in response["error"]


@pytest.mark.asyncio
async def test_provider_owner_bridge_read_session_times_out_slow_facts(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())

    class Facts:
        @staticmethod
        def read_thread_history(session_id, limit=20):
            time.sleep(0.05)
            return [{"role": "assistant", "text": "slow"}]

    monkeypatch.setattr("core.provider_owner_bridge.OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_read_session(
        {
            "provider_id": "overlay-tool",
            "session_id": "tid-slow",
            "limit": 20,
        }
    )

    assert response["ok"] is False
    assert "overlay-tool.read_thread_history(tid-slow) timed out after 10ms" in response["error"]


@pytest.mark.asyncio
async def test_provider_owner_bridge_archives_session_via_real_thread_hook(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    archived = {}
    saved = {}
    storage = AppStorage()
    storage.workspaces["overlay-tool:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/project-a",
        threads={
            "tid-archive": ThreadInfo(
                thread_id="tid-archive",
                archived=False,
                is_active=True,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    adapter = SimpleNamespace(
        connected=True,
        register_workspace_cwd=lambda workspace_id, cwd: archived.update(
            {"registered": (workspace_id, cwd)}
        ),
    )
    state.set_adapter("overlay-tool", adapter)

    async def archive_thread(app_state, ws_info, thread_id, active_adapter):
        archived["workspace_id"] = ws_info.daemon_workspace_id
        archived["workspace_path"] = ws_info.path
        archived["thread_id"] = thread_id
        archived["adapter"] = active_adapter
        archived["state"] = app_state

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(archive_thread=archive_thread)
        )
        if name == "overlay-tool"
        else None,
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.save_storage",
        lambda storage_arg: saved.update({"storage": storage_arg}),
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_archive_session(
        {
            "provider_id": "overlay-tool",
            "session_id": "tid-archive",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response == {
        "ok": True,
        "provider_id": "overlay-tool",
        "thread_id": "tid-archive",
        "workspace_id": "overlay-tool:/tmp/project-a",
        "workspace_dir": "/tmp/project-a",
    }
    assert archived["registered"] == ("overlay-tool:/tmp/project-a", "/tmp/project-a")
    assert archived["workspace_id"] == "overlay-tool:/tmp/project-a"
    assert archived["workspace_path"] == "/tmp/project-a"
    assert archived["thread_id"] == "tid-archive"
    assert archived["adapter"] is adapter
    assert archived["state"] is state
    assert saved["storage"] is storage
    thread = storage.workspaces["overlay-tool:/tmp/project-a"].threads["tid-archive"]
    assert thread.archived is True
    assert thread.is_active is False


@pytest.mark.asyncio
async def test_provider_owner_bridge_archive_failure_keeps_local_state(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    storage.workspaces["overlay-tool:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/project-a",
        threads={
            "tid-archive": ThreadInfo(
                thread_id="tid-archive",
                archived=False,
                is_active=True,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    state.set_adapter("overlay-tool", SimpleNamespace(connected=True))

    async def archive_thread(_state, _ws_info, _thread_id, _adapter):
        raise RuntimeError("source archive failed")

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(archive_thread=archive_thread)
        )
        if name == "overlay-tool"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_archive_session(
        {
            "provider_id": "overlay-tool",
            "session_id": "tid-archive",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response == {"ok": False, "error": "source archive failed"}
    thread = storage.workspaces["overlay-tool:/tmp/project-a"].threads["tid-archive"]
    assert thread.archived is False
    assert thread.is_active is True


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
async def test_provider_owner_bridge_runtime_status_does_not_force_readiness_refresh(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        async def check_readiness(self, *, force: bool = False):
            raise AssertionError("runtime_status should not force CLI readiness checks")

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

    assert response["ok"] is True
    assert response["health"] == "healthy"


@pytest.mark.asyncio
async def test_provider_owner_bridge_reports_claude_logged_out_status_as_degraded(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

    state = AppState(storage=AppStorage())
    state.set_adapter("claude", _FakeAdapter())

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            status_builder=lambda current_state: [
                "• claude CLI：⚠️ 已连接，但不可用：Claude CLI is not logged in."
            ]
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_runtime_status(
        {
            "provider_id": "claude",
        }
    )

    assert response == {
        "ok": True,
        "health": "degraded",
        "detail": "• claude CLI：⚠️ 已连接，但不可用：Claude CLI is not logged in.",
        "lines": ["• claude CLI：⚠️ 已连接，但不可用：Claude CLI is not logged in."],
    }



@pytest.mark.asyncio
async def test_provider_owner_bridge_ignores_legacy_mirror_approval(tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    state.telegram_bot = object()
    state.group_chat_id = -100123456789

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
                "command": "/bin/zsh -lc 'ps -axo pid,command'",
            },
        }
    )

    assert response == {"ok": True, "ignored": True, "reason": "approval_via_app_server_only"}
    assert state.pending_approvals == {}


@pytest.mark.asyncio
async def test_provider_owner_bridge_replies_approval_via_pending_decision(tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：mkdir /tmp/demo",
                "requestId": "req-1",
                "approvalSource": "remote_proxy",
            },
            created_at=10,
        )
    )
    pending = state.ensure_pending_approval_decision("codex", "req-1")

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_reply_approval(
        {
            "type": "reply_approval",
            "provider_id": "codex",
            "workspace_id": "codex:/tmp/project",
            "session_id": "thread-a",
            "request_id": "req-1",
            "action": "exec_allow",
            "approval_source": "remote_proxy",
        }
    )

    assert response["ok"] is True
    assert response["mode"] == "pending-decision"
    assert pending.event.is_set() is True
    assert pending.decision == "exec_allow"
    activity = state.message_bus.session_activity("codex", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionKind"] == ""
    events = state.message_bus.recent_events()
    assert events[-1]["kind"] == "approval.answered"
    assert events[-1]["source"] == "desktop_app"


@pytest.mark.asyncio
async def test_provider_owner_bridge_replies_approval_via_connected_adapter(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    adapter = SimpleNamespace(
        connected=True,
        reply_server_request=AsyncMock(),
    )
    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.set_adapter("claude", adapter)
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：mkdir /tmp/demo",
                "requestId": "req-2",
                "approvalSource": "item/commandExecution/requestApproval",
            },
            created_at=10,
        )
    )

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                build_approval_reply=lambda approval, action: (
                    "✅ 已允许",
                    {"behavior": "allow", "source": approval.approval_source, "decision": action},
                )
            )
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_reply_approval(
        {
            "type": "reply_approval",
            "provider_id": "claude",
            "workspace_id": "claude:/tmp/project",
            "workspace_dir": "/tmp/project",
            "session_id": "thread-a",
            "request_id": "req-2",
            "action": "exec_allow",
            "approval_source": "item/commandExecution/requestApproval",
        }
    )

    assert response["ok"] is True
    assert response["mode"] == "adapter"
    adapter.reply_server_request.assert_awaited_once_with(
        "claude:/tmp/project",
        "req-2",
        {"behavior": "allow", "source": "item/commandExecution/requestApproval", "decision": "exec_allow"},
    )
    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionKind"] == ""


@pytest.mark.asyncio
async def test_provider_owner_bridge_preserves_numeric_approval_request_id(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    adapter = SimpleNamespace(
        connected=True,
        reply_server_request=AsyncMock(),
    )
    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.set_adapter("codex", adapter)
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：touch /tmp/demo",
                "requestId": "3",
                "rawRequestId": 3,
                "approvalSource": "item/commandExecution/requestApproval",
            },
            created_at=10,
        )
    )

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                build_approval_reply=lambda _approval, _action: (
                    "✅ 已允许",
                    {"decision": "accept"},
                )
            )
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_reply_approval(
        {
            "type": "reply_approval",
            "provider_id": "codex",
            "workspace_id": "codex:/tmp/project",
            "workspace_dir": "/tmp/project",
            "session_id": "thread-a",
            "request_id": "3",
            "action": "exec_allow",
            "approval_source": "item/commandExecution/requestApproval",
        }
    )

    assert response["ok"] is True
    adapter.reply_server_request.assert_awaited_once_with(
        "codex:/tmp/project",
        3,
        {"decision": "accept"},
    )


@pytest.mark.asyncio
async def test_provider_owner_bridge_replies_locally_retained_approval_via_pending_decision(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    adapter = SimpleNamespace(
        connected=True,
        reply_server_request=AsyncMock(),
    )
    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    state.set_adapter("claude", adapter)
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：echo hi",
                "requestId": "req-local-1",
                "approvalSource": "app_server",
            },
            created_at=10,
        )
    )
    pending = state.ensure_pending_approval_decision("claude", "req-local-1")
    pending.requires_adapter_reply = True

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(
                build_approval_reply=lambda approval, action: (
                    "✅ 已允许",
                    {"behavior": "allow"},
                )
            )
        )
        if name == "claude"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_reply_approval(
        {
            "type": "reply_approval",
            "provider_id": "claude",
            "workspace_id": "claude:/tmp/project",
            "workspace_dir": "/tmp/project",
            "session_id": "thread-a",
            "request_id": "req-local-1",
            "action": "exec_allow",
            "approval_source": "app_server",
        }
    )

    assert response["ok"] is True
    assert response["mode"] == "adapter"
    adapter.reply_server_request.assert_awaited_once_with(
        "claude:/tmp/project",
        "req-local-1",
        {"behavior": "allow"},
    )
    assert pending.event.is_set() is False
    assert pending.decision == ""
    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionKind"] == ""
