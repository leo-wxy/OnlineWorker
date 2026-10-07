import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.messages.bus import MessageEventBus
from core.messages.events import create_message_event
from core.messages.publishing import (
    publish_user_message_accepted,
    publish_user_message_failed,
    publish_user_message_submitted,
)
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from core.user_messages.contracts import UserMessageSendRequest


def message_request(text):
    return UserMessageSendRequest(
        source="session_tab", provider_id="overlay-tool",
        workspace_id="overlay-tool:/tmp/sample-workspace", thread_id="sample-thread", text=text,
    )


def test_failed_delivery_is_correlated_and_does_not_replace_newer_input_or_provider_turn():
    state = SimpleNamespace(message_bus=MessageEventBus())
    first, second = message_request("same text"), message_request("same text")
    publish_user_message_submitted(state, first, text=first.text)
    publish_user_message_accepted(state, first, text=first.text)
    publish_user_message_submitted(state, second, text=second.text)
    publish_user_message_accepted(state, second, text=second.text)
    before = state.message_bus.session_activity("overlay-tool", "sample-thread")
    assert len(before["conversationTurns"]) == 2
    publish_user_message_failed(state, first, text=first.text, error=RuntimeError("old failure"))
    assert state.message_bus.session_activity("overlay-tool", "sample-thread") == before

    state.message_bus.publish(create_message_event(
        "turn.started", provider_id="overlay-tool", session_id="sample-thread", turn_id="sample-turn",
    ))
    publish_user_message_failed(state, second, text=second.text, error=TimeoutError("response lost"))
    activity = state.message_bus.session_activity("overlay-tool", "sample-thread")
    assert activity["status"] == "running"
    assert activity["activeTurnId"] == "sample-turn"
    assert activity["deliveryStatus"] == "uncertain"
    assert len(activity["conversationTurns"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("rejected"), TimeoutError("response lost")])
async def test_new_session_message_accepts_only_after_send_and_reports_failure(failure):
    from core.provider_session_new import send_started_provider_thread_message

    state = AppState(storage=AppStorage())
    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="overlay-tool")
    thread = ThreadInfo(thread_id="sample-thread")
    workspace.threads[thread.thread_id] = thread
    entered = asyncio.Event()
    release = asyncio.Event()

    async def send(*args, **kwargs):
        entered.set()
        await release.wait()
        if failure:
            raise failure

    provider = SimpleNamespace(message_hooks=SimpleNamespace(send=send))
    task = asyncio.create_task(send_started_provider_thread_message(
        state, workspace, thread, "overlay-tool:/tmp/sample-workspace", provider_id="overlay-tool",
        text="first message", attachments=[], source="session_tab", provider=provider,
        adapter=SimpleNamespace(connected=True),
    ))
    await asyncio.wait_for(entered.wait(), 1)
    assert [event["kind"] for event in state.message_bus.recent_events()] == ["message.user.submitted"]
    release.set()
    if failure:
        with pytest.raises(type(failure)):
            await task
    else:
        await task
    events = state.message_bus.recent_events()
    assert [event["kind"] for event in events] == [
        "message.user.submitted", "message.user.send_failed" if failure else "message.user.accepted",
    ]
    assert events[0]["payload"]["messageRequestId"] == events[1]["payload"]["messageRequestId"]
    activity = state.message_bus.session_activity("overlay-tool", "sample-thread")
    assert activity["status"] == ("failed" if failure else "running")
    assert len(activity["conversationTurns"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_prepare", [False, True])
async def test_owner_bridge_reports_queued_then_background_send_failure(monkeypatch, tmp_path, reject_prepare):
    from core.provider_owner_bridge import ProviderOwnerBridge

    adapter = SimpleNamespace(connected=True)
    provider = SimpleNamespace(facts=SimpleNamespace(query_active_thread_ids=lambda _: {"sample-thread"}), message_hooks=SimpleNamespace(
        ensure_connected=AsyncMock(return_value=adapter), prepare_send=AsyncMock(return_value=not reject_prepare),
        send=AsyncMock(side_effect=RuntimeError("sample rejection")),
    ))
    monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *args: provider)
    monkeypatch.setattr("core.provider_owner_bridge.save_storage", lambda *args: None)
    state = AppState(storage=AppStorage())
    state.set_adapter("overlay-tool", adapter)
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    result = await bridge._handle_send_message({
        "provider_id": "overlay-tool", "thread_id": "sample-thread", "text": "sample input",
        "workspace_dir": "/tmp/sample-workspace",
    })
    assert result["ok"] is True
    if reject_prepare:
        assert result["accepted"] is False
        assert state.message_bus.session_activity("overlay-tool", "sample-thread")["deliveryStatus"] == "failed"
        provider.message_hooks.send.assert_not_awaited()
        assert bridge._handle_prepare_app_update()["ok"]
        return
    assert [event["kind"] for event in state.message_bus.recent_events()] == [
        "message.user.submitted", "message.user.queued",
    ]
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    events = state.message_bus.recent_events()
    assert [event["kind"] for event in events] == [
        "message.user.submitted", "message.user.queued", "message.user.send_failed",
    ]
    assert len({event["payload"]["messageRequestId"] for event in events}) == 1
    assert state.message_bus.session_activity("overlay-tool", "sample-thread")["status"] == "failed"
    assert bridge._handle_prepare_app_update()["ok"]
