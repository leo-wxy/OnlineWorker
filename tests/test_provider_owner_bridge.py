import asyncio
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
async def test_provider_owner_bridge_creates_provider_session(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []
            self.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})

        def register_workspace_cwd(self, workspace_id: str, cwd: str):
            self.registered.append((workspace_id, cwd))

    state = AppState(storage=AppStorage())
    adapter = _FakeAdapter()
    state.set_adapter("overlay-tool", adapter)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(name=name) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_create_session(
        {
            "provider_id": "overlay-tool",
            "workspace_dir": "/tmp/workspace",
        }
    )

    assert response["ok"] is True
    assert response["thread_id"] == "tid-new"
    assert response["session"]["id"] == "tid-new"
    assert response["session"]["workspace"] == "/tmp/workspace"
    assert adapter.registered == [("overlay-tool:/tmp/workspace", "/tmp/workspace")]
    adapter.start_thread.assert_awaited_once_with("overlay-tool:/tmp/workspace")
    ws = state.storage.workspaces["overlay-tool:/tmp/workspace"]
    assert ws.threads["tid-new"].thread_id == "tid-new"
    assert ws.threads["tid-new"].archived is False


@pytest.mark.asyncio
async def test_provider_owner_bridge_creates_app_state_session_without_source_materialization(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []
            self.start_thread = AsyncMock(return_value={"thread": {"id": "tid-source"}})

        def register_workspace_cwd(self, workspace_id: str, cwd: str):
            self.registered.append((workspace_id, cwd))

    state = AppState(storage=AppStorage())
    adapter = _FakeAdapter()
    state.set_adapter("codex", adapter)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            name=name,
            facts=SimpleNamespace(
                include_state_only_thread=lambda thread_info: thread_info.source == "app",
            ),
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_create_session(
        {
            "provider_id": "codex",
            "workspace_dir": "/tmp/workspace",
            "create_mode": "app_state",
        }
    )

    assert response["ok"] is True
    assert response["thread_id"].startswith("app:codex:")
    assert response["session"]["id"] == response["thread_id"]
    assert response["session"]["workspace"] == "/tmp/workspace"
    assert response["session"]["source"] == "app"
    assert adapter.registered == [("codex:/tmp/workspace", "/tmp/workspace")]
    adapter.start_thread.assert_not_awaited()
    ws = state.storage.workspaces["codex:/tmp/workspace"]
    assert ws.threads[response["thread_id"]].source == "app"
    assert ws.threads[response["thread_id"]].archived is False
    assert ws.threads[response["thread_id"]].is_active is False


@pytest.mark.asyncio
async def test_provider_owner_bridge_list_sessions_excludes_state_only_app_threads(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="codex",
        daemon_workspace_id="codex:/tmp/workspace",
        threads={
            "app:codex:1": ThreadInfo(
                thread_id="app:codex:1",
                preview="新建会话",
                archived=False,
                is_active=False,
                source="app",
            )
        },
    )
    storage.workspaces["codex:/tmp/workspace"] = ws
    state = AppState(storage=storage)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            name=name,
            facts=SimpleNamespace(
                list_sessions=lambda limit=100: [
                    {
                        "id": "real-thread",
                        "workspace": "/tmp/workspace",
                        "title": "Real",
                    }
                ],
                include_state_only_thread=lambda thread_info: thread_info.source == "app",
            ),
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions(
        {
            "provider_id": "codex",
            "force_refresh": True,
        }
    )

    assert response["ok"] is True
    session_ids = {session["id"] for session in response["sessions"]}
    assert session_ids == {"real-thread"}


@pytest.mark.asyncio
async def test_provider_owner_bridge_list_sessions_excludes_legacy_draft_threads(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="codex",
        daemon_workspace_id="codex:/tmp/workspace",
        threads={
            "draft:codex:1": ThreadInfo(
                thread_id="draft:codex:1",
                preview="legacy draft",
                archived=False,
                is_active=False,
                source="app",
            ),
            "app:codex:1": ThreadInfo(
                thread_id="app:codex:1",
                preview="新建会话",
                archived=False,
                is_active=False,
                source="app",
            ),
        },
    )
    storage.workspaces["codex:/tmp/workspace"] = ws
    state = AppState(storage=storage)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            name=name,
            facts=SimpleNamespace(
                list_sessions=lambda limit=100: [],
                include_state_only_thread=lambda thread_info: thread_info.source == "app",
            ),
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions(
        {
            "provider_id": "codex",
            "force_refresh": True,
        }
    )

    assert response["ok"] is True
    assert response["sessions"] == []


@pytest.mark.asyncio
async def test_provider_owner_bridge_serves_usage_source_summary(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}

    def get_summary(plugin_id, source_id, start_date, end_date, **kwargs):
        called["request"] = (plugin_id, source_id, start_date, end_date, kwargs)
        return {
            "pluginId": plugin_id,
            "sourceId": source_id,
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
        }

    monkeypatch.setattr("core.usage.runtime.get_usage_source_summary", get_summary)

    bridge = ProviderOwnerBridge(AppState(storage=AppStorage()), data_dir=str(tmp_path))
    response = await bridge._handle_usage_source_summary(
        {
            "plugin_id": "ccusage",
            "source_id": "codex",
            "start_date": "2026-05-20",
            "end_date": "2026-05-21",
        }
    )

    assert called["request"][:4] == ("ccusage", "codex", "2026-05-20", "2026-05-21")
    assert response == {
        "ok": True,
        "summary": {
            "pluginId": "ccusage",
            "sourceId": "codex",
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
async def test_provider_owner_bridge_streams_filtered_session_events_from_message_bus(tmp_path):
    import asyncio

    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    state.message_bus = MessageEventBus()
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    socket_path = f"/tmp/ow-bridge-events-{os.getpid()}.sock"
    try:
        os.remove(socket_path)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(bridge._handle_client, path=socket_path)
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(
            b'{"type":"session_event_stream","provider_id":"claude","session_id":"thread-a","workspace_dir":"/tmp/project"}\n'
        )
        await writer.drain()
        ready = json.loads((await reader.readline()).decode("utf-8"))
        assert ready["kind"] == "stream_ready"

        state.message_bus.publish(
            create_message_event(
                "message.user.accepted",
                provider_id="claude",
                workspace_id="claude:/tmp/project",
                workspace_path="/tmp/project",
                session_id="thread-a",
                payload={
                    "text": "图片里面主要是什么内容",
                    "attachments": [{"kind": "image", "name": "Image #1"}],
                },
                created_at=10,
            )
        )
        user_update = json.loads((await reader.readline()).decode("utf-8"))
        assert user_update["kind"] == "user_message"
        assert user_update["semanticKind"] == "message.user.accepted"
        assert user_update["turn"]["role"] == "user"
        assert user_update["turn"]["content"] == "图片里面主要是什么内容\n[Attached image] Image #1"

        state.message_bus.publish(
            create_message_event(
                "message.assistant.delta",
                provider_id="claude",
                workspace_id="claude:/tmp/project",
                workspace_path="/tmp/project",
                session_id="thread-a",
                payload={"delta": "我先看一下当前链路。"},
                created_at=20,
            )
        )
        delta_update = json.loads((await reader.readline()).decode("utf-8"))
        assert delta_update["kind"] == "assistant_progress"
        assert delta_update["turn"]["pending"] is True
        assert delta_update["turn"]["content"] == "我先看一下当前链路。"

        state.message_bus.publish(
            create_message_event(
                "message.assistant.final",
                provider_id="claude",
                workspace_id="claude:/tmp/project",
                workspace_path="/tmp/project",
                session_id="thread-a",
                payload={"text": "## 最终结果"},
                created_at=30,
            )
        )
        final_update = json.loads((await reader.readline()).decode("utf-8"))
        assert final_update["kind"] == "assistant_completed"
        assert final_update["turn"]["displayMode"] == "markdown"
        assert final_update["turn"]["content"] == "## 最终结果"

        state.message_bus.publish(
            create_message_event(
                "message.assistant.delta",
                provider_id="claude",
                workspace_id="claude:/tmp/other",
                workspace_path="/tmp/other",
                session_id="thread-a",
                payload={"delta": "should not pass"},
                created_at=40,
            )
        )

        state.message_bus.publish(
            create_message_event(
                "turn.failed",
                provider_id="claude",
                workspace_id="claude:/tmp/project",
                workspace_path="/tmp/project",
                session_id="thread-a",
                payload={"reason": "interrupted"},
                created_at=50,
            )
        )
        first_following_update = json.loads((await reader.readline()).decode("utf-8"))
        assert "should not pass" not in json.dumps(first_following_update, ensure_ascii=False)
        abort_update = first_following_update
        if abort_update["kind"] != "turn_aborted":
            abort_update = json.loads((await reader.readline()).decode("utf-8"))
        assert abort_update["kind"] == "turn_aborted"
        assert abort_update["reason"] == "interrupted"
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
async def test_provider_owner_bridge_exposes_and_dispatches_owned_active_interrupt(
    monkeypatch,
    tmp_path,
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    interrupt = AsyncMock()
    provider = SimpleNamespace(
        thread_hooks=SimpleNamespace(
            interrupt_supported=lambda state, ws: True,
            interrupt_thread=interrupt,
        )
    )
    ws = WorkspaceInfo(
        name="project",
        path="/tmp/project",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project",
        threads={
            "thread-active": ThreadInfo(
                thread_id="thread-active",
                source="app",
                is_active=True,
            )
        },
    )
    state = AppState(storage=AppStorage(workspaces={"codex:/tmp/project": ws}))
    adapter = SimpleNamespace(connected=True)
    state.set_adapter("codex", adapter)
    state.message_bus.publish(
        create_message_event(
            "turn.started",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-active",
            turn_id="turn-1",
            created_at=10,
        )
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "codex" else None,
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    activities = await bridge._handle_session_activities({"limit": 20})
    assert activities["activities"][0]["canInterrupt"] is True
    assert activities["activities"][0]["canRecover"] is False
    assert activities["activities"][0]["controlReason"] == ""

    response = await bridge._handle_session_control(
        {
            "provider_id": "codex",
            "workspace_id": "codex:/tmp/project",
            "session_id": "thread-active",
            "action": "interrupt",
        }
    )

    assert response == {
        "ok": True,
        "accepted": True,
        "action": "interrupt",
        "provider_id": "codex",
        "session_id": "thread-active",
        "awaiting_provider_event": True,
    }
    interrupt.assert_awaited_once_with(state, ws, ws.threads["thread-active"], adapter, "turn-1")


@pytest.mark.asyncio
async def test_provider_owner_bridge_rejects_mirrored_session_control_without_dispatch(
    monkeypatch,
    tmp_path,
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    interrupt = AsyncMock()
    provider = SimpleNamespace(
        thread_hooks=SimpleNamespace(
            interrupt_supported=lambda state, ws: True,
            interrupt_thread=interrupt,
        )
    )
    ws = WorkspaceInfo(
        name="project",
        path="/tmp/project",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project",
        threads={
            "thread-imported": ThreadInfo(
                thread_id="thread-imported",
                source="imported",
                is_active=True,
            )
        },
    )
    state = AppState(storage=AppStorage(workspaces={"codex:/tmp/project": ws}))
    state.set_adapter("codex", SimpleNamespace(connected=True))
    state.streaming_turns["thread-imported"] = SimpleNamespace(turn_id="turn-1")
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "codex" else None,
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_session_control(
        {
            "provider_id": "codex",
            "workspace_id": "codex:/tmp/project",
            "session_id": "thread-imported",
            "action": "interrupt",
        }
    )

    assert response["ok"] is False
    assert response["code"] == "not_owned"
    assert "外部客户端" in response["error"]
    interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_recovers_owned_session_without_replaying_message(
    monkeypatch,
    tmp_path,
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    adapter = SimpleNamespace(
        connected=True,
        resume_thread=AsyncMock(return_value={"id": "thread-failed"}),
        send_user_message=AsyncMock(),
    )
    provider = SimpleNamespace(thread_hooks=SimpleNamespace())
    ws = WorkspaceInfo(
        name="project",
        path="/tmp/project",
        tool="claude",
        daemon_workspace_id="claude:/tmp/project",
        threads={
            "thread-failed": ThreadInfo(
                thread_id="thread-failed",
                source="app",
                is_active=True,
            )
        },
    )
    state = AppState(storage=AppStorage(workspaces={"claude:/tmp/project": ws}))
    state.set_adapter("claude", adapter)
    state.message_bus.publish(
        create_message_event(
            "turn.failed",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-failed",
            payload={"reason": "provider process exited"},
            created_at=10,
        )
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "claude" else None,
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_session_control(
        {
            "provider_id": "claude",
            "workspace_id": "claude:/tmp/project",
            "session_id": "thread-failed",
            "action": "recover",
        }
    )

    assert response == {
        "ok": True,
        "accepted": True,
        "action": "recover",
        "provider_id": "claude",
        "session_id": "thread-failed",
        "awaiting_provider_event": False,
    }
    adapter.resume_thread.assert_awaited_once_with("claude:/tmp/project", "thread-failed")
    adapter.send_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_reconnects_before_recovering_owned_session(
    monkeypatch,
    tmp_path,
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    disconnected = SimpleNamespace(connected=False, resume_thread=AsyncMock())
    connected = SimpleNamespace(
        connected=True,
        resume_thread=AsyncMock(return_value={"id": "thread-failed"}),
        send_user_message=AsyncMock(),
    )
    ensure_connected = AsyncMock(return_value=connected)
    provider = SimpleNamespace(
        thread_hooks=SimpleNamespace(),
        message_hooks=SimpleNamespace(ensure_connected=ensure_connected),
    )
    ws = WorkspaceInfo(
        name="project",
        path="/tmp/project",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project",
        threads={
            "thread-failed": ThreadInfo(
                thread_id="thread-failed",
                source="app",
                is_active=True,
            )
        },
    )
    state = AppState(storage=AppStorage(workspaces={"codex:/tmp/project": ws}))
    state.set_adapter("codex", disconnected)
    state.message_bus.publish(
        create_message_event(
            "turn.failed",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-failed",
            payload={"reason": "connection lost"},
            created_at=10,
        )
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "codex" else None,
    )
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))

    response = await bridge._handle_session_control(
        {
            "provider_id": "codex",
            "workspace_id": "codex:/tmp/project",
            "session_id": "thread-failed",
            "action": "recover",
        }
    )

    assert response["ok"] is True
    assert response["awaiting_provider_event"] is False
    ensure_connected.assert_awaited_once_with(
        state,
        disconnected,
        ws,
        update=None,
        context=None,
        group_chat_id=0,
        src_topic_id=None,
    )
    connected.resume_thread.assert_awaited_once_with("codex:/tmp/project", "thread-failed")
    connected.send_user_message.assert_not_awaited()


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
async def test_provider_owner_bridge_marks_provider_active_sessions(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class Facts:
        thread_list_is_authoritative = False

        @staticmethod
        def scan_workspaces(sessions_dir=None):
            return [{"path": "/tmp/project"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            assert workspace_path == "/tmp/project"
            return {"tid-active", "tid-idle"}

        @staticmethod
        def query_running_thread_ids(workspace_path):
            assert workspace_path == "/tmp/project"
            return {"tid-active"}

        @staticmethod
        def list_threads(workspace_path, limit=100):
            assert workspace_path == "/tmp/project"
            return [
                {"id": "tid-active", "preview": "Active task", "updatedAt": 2000, "createdAt": 1000},
                {"id": "tid-idle", "preview": "Idle task", "updatedAt": 1500, "createdAt": 900},
            ]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(AppState(storage=AppStorage()), data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions({"provider_id": "overlay-tool", "limit": 20})

    assert response["ok"] is True
    sessions = {item["id"]: item for item in response["sessions"]}
    assert sessions["tid-active"]["providerActive"] is True
    assert sessions["tid-active"]["archived"] is False
    assert sessions["tid-idle"]["providerActive"] is False
    assert sessions["tid-idle"]["archived"] is False


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
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
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
async def test_provider_owner_bridge_starts_real_session_with_first_message(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []
            self.start_thread = AsyncMock(return_value={"id": "real-thread"})

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
    response = await bridge._handle_start_session_message(
        {
            "provider_id": "overlay-tool",
            "workspace_dir": "/tmp/project-a",
            "text": "first message",
        }
    )

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["thread_id"] == "real-thread"
    assert response["requested_thread_id"] == "real-thread"
    assert response["created_new_thread"] is True
    assert response["remapped"] is False
    assert response["session"]["id"] == "real-thread"
    assert not response["session"]["id"].startswith("app:overlay-tool:")
    adapter.start_thread.assert_awaited_once_with("overlay-tool:/tmp/project-a")
    assert adapter.registered == [
        ("overlay-tool:/tmp/project-a", "/tmp/project-a"),
    ]
    ws = state.storage.workspaces["overlay-tool:/tmp/project-a"]
    assert set(ws.threads) == {"real-thread"}
    assert ws.threads["real-thread"].thread_id == "real-thread"
    assert ws.threads["real-thread"].preview == "first message"
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
    assert called["send"][2:] == (
        "overlay-tool:/tmp/project-a",
        "real-thread",
        "first message",
    )


@pytest.mark.asyncio
async def test_provider_owner_bridge_start_session_message_accepts_slow_real_thread(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}
    release_start = asyncio.Event()

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.registered.append((workspace_id, cwd))

        async def start_thread(self, workspace_id: str):
            called["start_thread"] = workspace_id
            await release_start.wait()
            return {"id": "real-thread"}

    adapter = _FakeAdapter()
    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", adapter)

    async def ensure_connected(state_obj, current_adapter, ws_info, **kwargs):
        return current_adapter

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        raise AssertionError("start_session_message should send directly after start_thread")

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["send"] = (
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
    task = asyncio.create_task(
        bridge._handle_start_session_message(
            {
                "provider_id": "overlay-tool",
                "workspace_dir": "/tmp/project-a",
                "text": "first message",
            }
        )
    )

    await asyncio.sleep(0)
    assert not task.done()
    release_start.set()
    response = await asyncio.wait_for(task, timeout=1.0)

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["thread_id"] == "real-thread"
    assert response["created_new_thread"] is True
    assert response["session"]["id"] == "real-thread"
    ws = state.storage.workspaces["overlay-tool:/tmp/project-a"]
    assert set(ws.threads) == {"real-thread"}
    assert ws.threads["real-thread"].preview == "first message"
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
    assert called["start_thread"] == "overlay-tool:/tmp/project-a"
    assert called["send"] == (
        "overlay-tool:/tmp/project-a",
        "real-thread",
        "first message",
    )
    activity = state.message_bus.session_activity("overlay-tool", "real-thread")
    assert activity["workspacePath"] == "/tmp/project-a"
    assert activity["lastUserMessage"] == "first message"


@pytest.mark.asyncio
async def test_provider_owner_bridge_start_session_message_returns_before_thread_start_finishes(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    called = {}
    release_start = asyncio.Event()

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.registered.append((workspace_id, cwd))

        async def start_thread(self, workspace_id: str):
            called["start_thread"] = workspace_id
            await release_start.wait()
            return {"id": "real-thread"}

    adapter = _FakeAdapter()
    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", adapter)

    async def ensure_connected(state_obj, current_adapter, ws_info, **kwargs):
        return current_adapter

    async def prepare_send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        raise AssertionError("start_session_message should send directly after start_thread")

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["send"] = thread_info.thread_id

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
    response = await asyncio.wait_for(
        bridge._handle_start_session_message(
            {
                "provider_id": "overlay-tool",
                "workspace_dir": "/tmp/project-a",
                "text": "first message",
            }
        ),
        timeout=0.05,
    )

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["pending"] is True
    assert not response.get("thread_id")
    assert called["start_thread"] == "overlay-tool:/tmp/project-a"

    release_start.set()
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)

    ws = state.storage.workspaces["overlay-tool:/tmp/project-a"]
    assert set(ws.threads) == {"real-thread"}
    assert ws.threads["real-thread"].preview == "first message"
    assert called["send"] == "real-thread"
    activity = state.message_bus.session_activity("overlay-tool", "real-thread")
    assert activity["workspacePath"] == "/tmp/project-a"
    assert activity["lastUserMessage"] == "first message"


@pytest.mark.asyncio
async def test_provider_owner_bridge_keeps_real_thread_binding_when_first_send_fails(
    monkeypatch,
    tmp_path,
):
    from core.provider_owner_bridge import ProviderOwnerBridge

    release_send = asyncio.Event()

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.start_thread = AsyncMock(return_value={"id": "real-thread-failed"})
            self.resume_thread = AsyncMock(return_value={"id": "real-thread-failed"})
            self.send_user_message = AsyncMock()

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            return None

    adapter = _FakeAdapter()
    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", adapter)

    async def ensure_connected(state_obj, current_adapter, ws_info, **kwargs):
        return current_adapter

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        await release_send.wait()
        raise RuntimeError("first send failed")

    provider = SimpleNamespace(
        thread_hooks=SimpleNamespace(),
        message_hooks=SimpleNamespace(
            ensure_connected=ensure_connected,
            send=send,
        ),
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: provider if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_start_session_message(
        {
            "provider_id": "overlay-tool",
            "workspace_dir": "/tmp/project-a",
            "text": "first message",
        }
    )

    assert response["ok"] is True
    assert response["pending"] is True
    pending_tasks = tuple(bridge._pending_send_tasks)
    release_send.set()
    await asyncio.gather(*pending_tasks, return_exceptions=True)

    ws = state.storage.workspaces["overlay-tool:/tmp/project-a"]
    assert ws.threads["real-thread-failed"].source == "provider"
    state.message_bus.publish(
        create_message_event(
            "turn.failed",
            provider_id="overlay-tool",
            workspace_id="overlay-tool:/tmp/project-a",
            workspace_path="/tmp/project-a",
            session_id="real-thread-failed",
            payload={"reason": "provider process exited"},
            created_at=10,
        )
    )

    activities = await bridge._handle_session_activities({"limit": 20})
    failed = next(
        item for item in activities["activities"]
        if item["sessionId"] == "real-thread-failed"
    )
    assert failed["controlMode"] == "owned"
    assert failed["canRecover"] is True

    recovered = await bridge._handle_session_control(
        {
            "provider_id": "overlay-tool",
            "workspace_id": "overlay-tool:/tmp/project-a",
            "session_id": "real-thread-failed",
            "action": "recover",
        }
    )
    assert recovered["ok"] is True
    adapter.resume_thread.assert_awaited_once_with(
        "overlay-tool:/tmp/project-a",
        "real-thread-failed",
    )
    adapter.send_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_start_session_message_uses_provider_thread_validation(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.start_thread = AsyncMock(return_value={"id": "real-thread"})

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            return None

    state = AppState(storage=AppStorage())
    adapter = _FakeAdapter()
    state.set_adapter("codex", adapter)

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(),
            thread_hooks=SimpleNamespace(
                validate_new_thread=lambda state_obj, ws_info, initial_text: "blocked by provider",
            ),
        )
        if name == "codex"
        else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_start_session_message(
        {
            "provider_id": "codex",
            "workspace_dir": "/tmp/project-a",
            "text": "first message",
        }
    )

    assert response == {"ok": False, "error": "blocked by provider"}
    adapter.start_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_owner_bridge_start_session_message_creates_claude_thread(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge
    from plugins.providers.builtin.claude.python.provider import create_provider_descriptor

    class _FakeAdapter:
        connected = True

        def __init__(self):
            self.registered = []
            self.start_thread = AsyncMock(return_value={"id": "claude-new-thread"})
            self.send_user_message = AsyncMock(return_value={})

        def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
            self.registered.append((workspace_id, cwd))

    adapter = _FakeAdapter()
    state = AppState(storage=AppStorage())
    state.set_adapter("claude", adapter)

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: create_provider_descriptor() if name == "claude" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_start_session_message(
        {
            "provider_id": "claude",
            "workspace_dir": "/tmp/project-a",
            "text": "first message",
        }
    )

    assert response["ok"] is True
    assert response["accepted"] is True
    assert response["thread_id"] == "claude-new-thread"
    assert response["created_new_thread"] is True
    adapter.start_thread.assert_awaited_once_with("claude:/tmp/project-a")
    adapter.send_user_message.assert_awaited_once_with(
        "claude:/tmp/project-a",
        "claude-new-thread",
        "first message",
    )
    assert adapter.registered == [("claude:/tmp/project-a", "/tmp/project-a")]

    ws = state.storage.workspaces["claude:/tmp/project-a"]
    assert ws.threads["claude-new-thread"].thread_id == "claude-new-thread"
    assert ws.threads["claude-new-thread"].preview == "first message"


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
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
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
            "source": "telegram",
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
            "source": "telegram",
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
async def test_provider_owner_bridge_session_tab_bypasses_owner_bridge_router(monkeypatch, tmp_path):
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
        threads={"tid-cli": ThreadInfo(thread_id="tid-cli", source="provider")},
    )
    state = AppState(storage=storage)
    state.set_adapter("overlay-tool", _FakeAdapter())

    route_send = AsyncMock(return_value="owned_visible_cli")
    provider = SimpleNamespace(
        message_hooks=SimpleNamespace(
            ensure_connected=AsyncMock(return_value=None),
            prepare_send=AsyncMock(return_value=True),
            send=AsyncMock(return_value={}),
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
            "text": "hello from session tab",
            "workspace_dir": "/tmp/project-a",
        }
    )
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks))

    assert response["ok"] is True
    assert response["accepted"] is True
    route_send.assert_not_awaited()
    provider.message_hooks.prepare_send.assert_awaited_once()
    provider.message_hooks.send.assert_awaited_once()


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
        "ok": True,
        "accepted": True,
        "provider_id": "claude",
        "thread_id": "tid-new",
        "requested_thread_id": "tid-new",
        "remapped": False,
        "workspace_id": "claude:/tmp/new-workspace",
    }
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)


@pytest.mark.asyncio
async def test_provider_owner_bridge_accepts_send_before_slow_send_completes(monkeypatch, tmp_path):
    import asyncio

    from core.provider_owner_bridge import ProviderOwnerBridge

    class _FakeAdapter:
        connected = True

    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        send_started.set()
        await release_send.wait()
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
    assert response["accepted"] is True
    await asyncio.wait_for(send_started.wait(), timeout=1)
    release_send.set()
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks))


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

    assert response["ok"] is True
    assert response["accepted"] is True
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
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
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
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
    if bridge._pending_send_tasks:
        await asyncio.gather(*tuple(bridge._pending_send_tasks), return_exceptions=True)
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
                "preview": "Beta",
                "workspace": "/tmp/beta",
                "archived": False,
                "providerActive": False,
                "updatedAt": 20,
                "createdAt": 20,
            },
            {
                "id": "tid-1",
                "title": "Alpha",
                "preview": "Alpha",
                "workspace": "/tmp/alpha",
                "archived": False,
                "providerActive": False,
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
async def test_provider_owner_bridge_prefers_provider_level_list_sessions(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    observed = {"limit": None}

    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            observed["limit"] = limit
            return [
                {
                    "id": "tid-2",
                    "title": "Beta",
                    "workspace": "/tmp/beta",
                    "archived": False,
                    "providerActive": True,
                    "updatedAt": 20,
                    "createdAt": 19,
                },
                {
                    "id": "tid-1",
                    "title": "Alpha",
                    "workspace": "/tmp/alpha",
                    "archived": False,
                    "providerActive": False,
                    "updatedAt": 10,
                    "createdAt": 9,
                },
            ]

        @staticmethod
        def scan_workspaces(sessions_dir=None):
            raise AssertionError("provider-level list_sessions should bypass workspace scans")

        @staticmethod
        def query_active_thread_ids(workspace_path):
            raise AssertionError("provider-level list_sessions should bypass active id queries")

        @staticmethod
        def list_threads(workspace_path, limit=100):
            raise AssertionError("provider-level list_sessions should bypass thread listing")

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 55,
        }
    )

    assert response == {
        "ok": True,
        "sessions": [
            {
                "id": "tid-2",
                "title": "Beta",
                "preview": "",
                "workspace": "/tmp/beta",
                "archived": False,
                "providerActive": True,
                "updatedAt": 20,
                "createdAt": 19,
            },
            {
                "id": "tid-1",
                "title": "Alpha",
                "preview": "",
                "workspace": "/tmp/alpha",
                "archived": False,
                "providerActive": False,
                "updatedAt": 10,
                "createdAt": 9,
            },
        ],
    }
    assert observed["limit"] == 55


@pytest.mark.asyncio
async def test_provider_owner_bridge_hydrates_missing_preview_from_history_and_caches(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    observed = {"list_calls": 0, "read_calls": 0}

    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            observed["list_calls"] += 1
            return [
                {
                    "id": "tid-2",
                    "title": "继续phase17 的实现",
                    "workspace": "/tmp/beta",
                    "archived": False,
                    "providerActive": True,
                    "updatedAt": 20,
                    "createdAt": 19,
                }
            ]

        @staticmethod
        def read_thread_history(session_id, limit=20, sessions_dir=None):
            observed["read_calls"] += 1
            assert session_id == "tid-2"
            return [
                {
                    "role": "user",
                    "text": "继续phase17 的实现。工作区在 /Users/wxy/Projects/onlineworker-combined。",
                },
                {
                    "role": "assistant",
                    "text": "我现在继续修 Session 列表预览，并检查 /Users/wxy/Projects/onlineworker-combined 里的 owner bridge 数据链。",
                },
            ]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    first = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )
    second = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )

    assert first == {
        "ok": True,
        "sessions": [
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
        ],
    }
    assert second == first
    assert observed["list_calls"] == 1
    assert observed["read_calls"] == 1


@pytest.mark.asyncio
async def test_provider_owner_bridge_list_sessions_uses_cached_snapshot_on_timeout(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    calls = {"count": 0}

    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            calls["count"] += 1
            if calls["count"] == 1:
                return [
                    {
                        "id": "tid-cached",
                        "title": "Cached",
                        "workspace": "/tmp/cached",
                        "archived": False,
                        "providerActive": True,
                        "updatedAt": 20,
                        "createdAt": 19,
                    }
                ]
            time.sleep(0.05)
            return []

    monkeypatch.setattr("core.provider_owner_bridge.OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    first = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )
    second = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
            "force_refresh": True,
        }
    )

    assert first["ok"] is True
    assert first["sessions"][0]["id"] == "tid-cached"
    assert second == first
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_provider_owner_bridge_list_sessions_returns_cached_snapshot_without_reloading(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())
    calls = {"count": 0}

    class Facts:
        @staticmethod
        def list_sessions(*, limit=100, sessions_dir=None):
            calls["count"] += 1
            return [
                {
                    "id": "tid-cached",
                    "title": "Cached",
                    "workspace": "/tmp/cached",
                    "archived": False,
                    "providerActive": True,
                    "updatedAt": 20,
                    "createdAt": 19,
                }
            ]

    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(facts=Facts) if name == "overlay-tool" else None,
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    first = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )
    second = await bridge._handle_list_sessions(
        {
            "provider_id": "overlay-tool",
            "limit": 20,
        }
    )

    assert first == second
    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_provider_owner_bridge_skips_active_query_for_authoritative_facts(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    state = AppState(storage=AppStorage())

    class Facts:
        thread_list_is_authoritative = True

        @staticmethod
        def scan_workspaces(sessions_dir=None):
            return [{"path": "/tmp/alpha"}]

        @staticmethod
        def query_active_thread_ids(workspace_path):
            raise AssertionError("authoritative thread list should not need active id query")

        @staticmethod
        def list_threads(workspace_path, limit=100):
            return [{"id": "tid-1", "preview": "Alpha", "updatedAt": 10}]

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

    assert response["ok"] is True
    assert response["sessions"][0]["id"] == "tid-1"
    assert response["sessions"][0]["archived"] is False


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
async def test_provider_owner_bridge_archives_app_state_session_locally(monkeypatch, tmp_path):
    from core.provider_owner_bridge import ProviderOwnerBridge

    saved = {}
    storage = AppStorage()
    storage.workspaces["codex:/tmp/project-a"] = WorkspaceInfo(
        name="project-a",
        path="/tmp/project-a",
        tool="codex",
        daemon_workspace_id="codex:/tmp/project-a",
        threads={
            "app:codex:empty": ThreadInfo(
                thread_id="app:codex:empty",
                archived=False,
                is_active=False,
                source="app",
            )
        },
    )
    state = AppState(storage=storage)
    adapter = SimpleNamespace(connected=True)
    state.set_adapter("codex", adapter)

    archive_thread = AsyncMock(side_effect=AssertionError("source archive should not be called"))
    monkeypatch.setattr(
        "core.provider_owner_bridge.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(archive_thread=archive_thread)
        )
        if name == "codex"
        else None,
    )
    monkeypatch.setattr(
        "core.provider_owner_bridge.save_storage",
        lambda storage_arg: saved.update({"storage": storage_arg}),
    )

    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_archive_session(
        {
            "provider_id": "codex",
            "session_id": "app:codex:empty",
            "workspace_dir": "/tmp/project-a",
        }
    )

    assert response == {
        "ok": True,
        "provider_id": "codex",
        "thread_id": "app:codex:empty",
        "workspace_id": "codex:/tmp/project-a",
        "workspace_dir": "/tmp/project-a",
        "archive_source": "local_state",
    }
    archive_thread.assert_not_awaited()
    assert saved["storage"] is storage
    thread = storage.workspaces["codex:/tmp/project-a"].threads["app:codex:empty"]
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
async def test_provider_owner_bridge_rejects_approval_without_adapter_authority(tmp_path):
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

    assert response == {"ok": False, "error": "codex adapter 未连接"}
    activity = state.message_bus.session_activity("codex", "thread-a")
    assert activity["status"] == "needs_attention"
    assert activity["attentionKind"] == "approval"
    events = state.message_bus.recent_events()
    assert events[-1]["kind"] == "approval.requested"


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
async def test_provider_owner_bridge_replies_approval_via_connected_adapter_without_pending_decision(
    monkeypatch,
    tmp_path,
):
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
    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionKind"] == ""
