import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.messages.bus import MessageEventBus
from core.messages.events import create_message_event
from core.provider_owner_bridge import ProviderOwnerBridge, _stream_queue, OWNER_BRIDGE_STREAM_QUEUE_SIZE
from core.state import AppState
from core.storage import AppStorage
from core.storage import WorkspaceInfo, ThreadInfo
from bot.events import make_event_handler, make_server_request_handler, stop_event_delivery, _delivery_consumer, IM_EVENT_QUEUE_SIZE
from core.state import PendingApproval
from plugins.providers.builtin.codex.python import runtime as codex_runtime


@pytest.mark.asyncio
async def test_legacy_workspace_id_publishes_to_detail_stream_with_real_workspace_path(tmp_path):
    from core.messages.publishing import publish_session_message_event
    from core.providers.session_events import normalize_session_event

    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="overlay-tool", daemon_workspace_id="overlay-tool:sample")
    workspace.threads["sample-session"] = ThreadInfo(thread_id="sample-session")
    state = AppState(storage=AppStorage(workspaces={"sample": workspace}))
    publish(state.message_bus, "session.history.loaded", turns=[], historyWindow=50)
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    writer, reader = Writer(), asyncio.StreamReader()
    task = asyncio.create_task(bridge._handle_session_event_stream(reader, writer, {
        "provider_id": "overlay-tool", "session_id": "sample-session", "workspace_dir": workspace.path,
    }))
    try:
        await asyncio.wait_for(writer.entered.wait(), 1)
        event = normalize_session_event("app-server-event", {"workspace_id": "overlay-tool:sample", "message": {
            "method": "item/agentMessage/delta", "params": {"threadId": "sample-session", "turnId": "sample-turn", "delta": "sample update"},
        }})
        assert publish_session_message_event(state, event)
        await asyncio.sleep(0)
        assert writer.rows[-1]["snapshot"][-1]["content"] == "sample update"
        assert state.message_bus.recent_events()[-1]["workspace_path"] == workspace.path
    finally:
        reader.feed_eof()
        await asyncio.wait_for(task, 1)


def publish(bus, kind, **payload):
    return bus.publish(create_message_event(
        kind, provider_id="overlay-tool", session_id="sample-session", turn_id="sample-turn",
        workspace_path="/tmp/sample-workspace", payload=payload,
    ))


def test_conversation_window_preserves_full_text_and_message_identity():
    bus = MessageEventBus()
    history = [{"role": "user", "content": f"sample {index}"} for index in range(51)]
    publish(bus, "session.history.loaded", turns=history, historyWindow=50)
    publish(bus, "message.assistant.delta", delta="first ", itemId="sample-item")
    publish(bus, "message.assistant.delta", delta="second", itemId="sample-item")
    assert bus.session_conversation("overlay-tool", "sample-session")[-1]["content"] == "first second"
    final = "sample body " * 1000
    publish(bus, "message.assistant.final", text=final, itemId="sample-item")
    conversation = bus.session_conversation("overlay-tool", "sample-session")
    assert len(conversation) == 50
    assert conversation[-1]["content"] == final
    assert conversation[-1]["pending"] is False
    assert not bus.publish(create_message_event(
        "message.assistant.delta", provider_id="overlay-tool", session_id="sample-session", turn_id="sample-turn",
        workspace_path="/tmp/other-workspace", payload={"delta": "stale workspace text"},
    ))
    assert bus.session_conversation("overlay-tool", "sample-session")[-1]["content"] == final
    assert len(bus.session_activity("overlay-tool", "sample-session")["conversationTurns"]) == 6
    assert "conversation_payload" not in bus.recent_events()[-1]
    assert len(bus.recent_events()[-1]["payload"]["text"]) < len(final)


class Writer:
    def __init__(self, *, blocked=False):
        self.rows = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False
        if not blocked:
            self.release.set()

    def write(self, data):
        self.rows.append(json.loads(data))

    async def drain(self):
        self.entered.set()
        await self.release.wait()

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_stream_queue_disconnects_at_capacity_without_creating_event_tasks():
    writer = Writer(blocked=True)
    queue, closed, enqueue = _stream_queue(writer)
    before = len(asyncio.all_tasks())
    for index in range(1000):
        enqueue({"index": index})
    assert queue.qsize() == OWNER_BRIDGE_STREAM_QUEUE_SIZE
    assert len(asyncio.all_tasks()) == before
    assert closed.is_set() and writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", ["activity", "conversation"])
async def test_blocked_stream_has_bounded_tasks_and_unsubscribes_on_overflow(tmp_path, stream):
    state = AppState(storage=AppStorage())
    publish(state.message_bus, "session.history.loaded", turns=[], historyWindow=50)
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    writer, reader = Writer(blocked=True), asyncio.StreamReader()
    before = set(asyncio.all_tasks())
    handler = bridge._handle_session_activity_stream if stream == "activity" else bridge._handle_session_event_stream
    task = asyncio.create_task(handler(reader, writer, {
        "provider_id": "overlay-tool", "session_id": "sample-session", "workspace_dir": "/tmp/sample-workspace",
    }))
    await asyncio.wait_for(writer.entered.wait(), 1)
    for _ in range(1000):
        publish(state.message_bus, "message.assistant.delta", delta="x", itemId="sample-item")
    assert len(set(asyncio.all_tasks()) - before) <= 4
    await asyncio.wait_for(task, 1)
    assert writer.closed
    assert state.message_bus._subscribers == []
    assert state.message_bus.session_conversation("overlay-tool", "sample-session")[-1]["content"] == "x" * 1000


@pytest.mark.asyncio
async def test_conversation_reconnect_starts_with_current_snapshot_and_keeps_one_assistant(tmp_path):
    state = AppState(storage=AppStorage())
    publish(state.message_bus, "session.history.loaded", turns=[{"role": "user", "content": "sample input"}], historyWindow=50)
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    request = {"provider_id": "overlay-tool", "session_id": "sample-session", "workspace_dir": "/tmp/sample-workspace"}
    writer, reader = Writer(), asyncio.StreamReader()
    task = asyncio.create_task(bridge._handle_session_event_stream(reader, writer, request))
    await asyncio.wait_for(writer.entered.wait(), 1)
    assert writer.rows[0]["kind"] == "replace_snapshot"
    publish(state.message_bus, "message.assistant.delta", delta="first ", itemId="sample-item")
    publish(state.message_bus, "message.assistant.delta", delta="second", itemId="sample-item")
    await asyncio.sleep(0)
    reader.feed_eof()
    await task

    writer, reader = Writer(), asyncio.StreamReader()
    task = asyncio.create_task(bridge._handle_session_event_stream(reader, writer, request))
    await asyncio.wait_for(writer.entered.wait(), 1)
    assert writer.rows[0]["snapshot"][-1]["content"] == "first second"
    publish(state.message_bus, "message.assistant.final", text="first second!", itemId="sample-item")
    await asyncio.sleep(0)
    assert len(writer.rows[-1]["snapshot"]) == 2
    assert writer.rows[-1]["snapshot"][-1]["content"] == "first second!"
    reader.feed_eof()
    await task
    assert state.message_bus._subscribers == []


@pytest.mark.asyncio
async def test_slow_im_does_not_block_delta_completion_or_approval_projection():
    workspace_id, session_id = "codex:/tmp/sample-workspace", "sample-session"
    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="codex", daemon_workspace_id=workspace_id)
    workspace.threads[session_id] = ThreadInfo(thread_id=session_id, topic_id=1234567890)
    state = AppState(storage=AppStorage(workspaces={workspace_id: workspace}))
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_send(**kwargs):
        entered.set()
        await release.wait()
        return SimpleNamespace(message_id=1234567890)

    bot = SimpleNamespace(send_message=blocked_send, edit_message_reply_markup=AsyncMock(), edit_message_text=AsyncMock())
    handler = make_event_handler(state, bot, -1001234567890, provider_id="codex")
    approval = make_server_request_handler(state, bot, -1001234567890, provider_id="codex")

    async def event(method, **params):
        await asyncio.wait_for(handler("app-server-event", {"workspace_id": workspace_id, "message": {
            "method": method, "params": {"threadId": session_id, "turnId": "sample-turn", **params},
        }}), 1)

    try:
        await event("turn/started")
        await asyncio.wait_for(entered.wait(), 1)
        for delta in ("first ", "second"):
            await event("item/agentMessage/delta", delta=delta, itemId="sample-item")
        assert state.message_bus.session_conversation("codex", session_id)[-1]["content"] == "first second"
        await asyncio.wait_for(approval("item/commandExecution/requestApproval", {
            "threadId": session_id, "_workspaceId": workspace_id, "command": "pwd",
        }, "sample-request"), 1)
        assert state.message_bus.session_activity("codex", session_id)["status"] == "needs_attention"
        assert "sample-request" in state.get_provider_current_run("codex", session_id).active_interruption_ids
        await event("item/completed", item={"type": "agentMessage", "id": "sample-item", "text": "first second!"})
        await event("turn/completed", status="completed")
        assert state.get_provider_current_run("codex", session_id).status == "completed"
        assert state.message_bus.session_conversation("codex", session_id)[-1]["content"] == "first second!"
        assert state.im_event_consumers["codex"].queue.qsize() == 4
    finally:
        await stop_event_delivery(state)
    assert state.message_bus._delivery_subscribers == []
    assert state.im_event_consumers == {}
    before = len(state.message_bus.recent_events())
    await event("item/agentMessage/delta", delta="stale", itemId="sample-item")
    assert len(state.message_bus.recent_events()) == before


@pytest.mark.asyncio
async def test_im_queue_overflow_is_bounded_and_failure_keeps_local_events():
    state = AppState(storage=AppStorage())
    consumer = _delivery_consumer(state, "overlay-tool")
    entered = asyncio.Event()

    async def blocked_send(index):
        entered.set()
        await asyncio.Event().wait()

    consumer.enqueue(blocked_send, -1)
    await asyncio.wait_for(entered.wait(), 1)
    before = set(asyncio.all_tasks())
    try:
        for index in range(IM_EVENT_QUEUE_SIZE + 1):
            accepted = consumer.enqueue(blocked_send, index)
        assert accepted is False
        assert consumer.queue.qsize() == IM_EVENT_QUEUE_SIZE
        assert set(asyncio.all_tasks()) == before
        assert state.message_bus.recent_events()[-1]["payload"]["reason"] == "im_queue_full"
        publish(state.message_bus, "message.assistant.final", text="sample final")
        assert state.message_bus.session_conversation("overlay-tool", "sample-session")[-1]["content"] == "sample final"
    finally:
        await stop_event_delivery(state)
    assert consumer.task.done()
    assert consumer.queue.empty()


@pytest.mark.asyncio
async def test_codex_resolution_updates_locally_before_slow_button_edit_and_setup_replaces_consumer(monkeypatch):
    state = AppState(storage=AppStorage())
    manager = SimpleNamespace(state=state, storage=state.storage, gid=1234567890)
    adapter = MagicMock()
    entered = asyncio.Event()

    async def blocked_edit(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    bot = SimpleNamespace(edit_message_text=blocked_edit)
    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr("plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started", AsyncMock())
    await codex_runtime.setup_connection(manager, bot, adapter)
    consumer = state.im_event_consumers["codex"]
    state.pending_approvals[1234567890] = PendingApproval(
        request_id="sample-request", workspace_id="codex:/tmp/sample-workspace", thread_id="sample-session",
        cmd="pwd", justification="sample", tool_type="codex", approval_source="item/commandExecution/requestApproval",
    )
    state.message_bus.publish(create_message_event("approval.requested", provider_id="codex", session_id="sample-session",
        workspace_id="codex:/tmp/sample-workspace", payload={"requestId": "sample-request"}))
    callback = adapter.on_event.call_args.args[0]
    try:
        await asyncio.wait_for(callback("app-server-event", {"workspace_id": "codex:/tmp/sample-workspace", "message": {
            "method": "serverRequest/resolved", "params": {"threadId": "sample-session", "requestId": "sample-request"},
        }}), 1)
        await asyncio.wait_for(entered.wait(), 1)
        assert state.pending_approvals == {}
        assert state.message_bus.session_activity("codex", "sample-session")["requestId"] == ""
        await asyncio.wait_for(callback("app-server-event", {"workspace_id": "codex:/tmp/sample-workspace", "message": {
            "method": "item/agentMessage/delta", "params": {"threadId": "sample-session", "turnId": "sample-turn", "delta": "sample reply"},
        }}), 1)
        assert state.message_bus.session_conversation("codex", "sample-session")[-1]["content"] == "sample reply"
        await codex_runtime.setup_connection(manager, bot, adapter)
        assert consumer.closed and consumer.task.done()
        assert len(state.message_bus._delivery_subscribers) == 3
    finally:
        await stop_event_delivery(state)
    assert state.message_bus._delivery_subscribers == []
