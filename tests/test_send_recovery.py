import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.provider_owner_bridge import ProviderOwnerBridge
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo, load_storage, save_storage
from core.user_messages.recovery import checkpoint_send_recovery, restore_send_recoveries


def setup_send(monkeypatch, tmp_path, *, prepare=True, failure=None):
    path = tmp_path / "state.json"
    monkeypatch.setattr("core.user_messages.recovery.save_storage", lambda storage: save_storage(storage, str(path)))
    adapter = SimpleNamespace(connected=True)
    provider = SimpleNamespace(message_hooks=SimpleNamespace(
        ensure_connected=AsyncMock(return_value=adapter), prepare_send=AsyncMock(return_value=prepare),
        send=AsyncMock(side_effect=failure, return_value={}),
    ))
    monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *_: provider)
    thread = ThreadInfo(thread_id="sample-session", source="provider")
    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/sample-workspace", threads={thread.thread_id: thread})
    state = AppState(storage=AppStorage(workspaces={workspace.daemon_workspace_id: workspace}))
    state.set_adapter("overlay-tool", adapter)
    request = {"provider_id": "overlay-tool", "thread_id": thread.thread_id, "workspace_dir": workspace.path,
               "text": "sample input", "attachments": [], "source": "session_tab", "request_id": "sample-request"}
    return state, workspace, thread, provider, ProviderOwnerBridge(state, data_dir=str(tmp_path)), request, path


@pytest.mark.asyncio
async def test_explicit_pre_send_failure_preserves_full_input_and_allows_new_attempt(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path, prepare=False)
    request["text"] = ("sample original input " * 300).strip()
    request["attachments"] = [{"id": "sample-file", "kind": "file", "name": "sample.txt", "path": str(tmp_path / "sample.txt")}]
    result = await bridge._handle_send_message(request)
    assert result["accepted"] is False
    assert thread.send_recovery["status"] == "failed"
    provider.message_hooks.send.assert_not_awaited()
    loaded = load_storage(str(path)).workspaces[workspace.daemon_workspace_id].threads[thread.thread_id]
    assert loaded.send_recovery["text"] == request["text"]
    assert loaded.send_recovery["attachments"] == request["attachments"]
    private = state.message_bus.session_send_recovery("overlay-tool", thread.thread_id)
    assert private["text"] == request["text"]
    public = [event for event in state.message_bus.recent_events() if event["kind"] == "session.recovery.updated"]
    assert str(tmp_path / "sample.txt") not in json.dumps(public)
    assert "text" not in public[-1]["payload"]["sendRecovery"]
    provider.message_hooks.prepare_send.return_value = True
    result = await bridge._handle_send_message({**request, "request_id": "sample-retry", "attachments": []})
    assert result["accepted"] is True
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert thread.send_recovery["status"] == "sent"


@pytest.mark.asyncio
async def test_response_loss_is_unknown_and_duplicate_request_never_resends(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path, failure=TimeoutError("response lost"))
    assert (await bridge._handle_send_message(request))["accepted"]
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert thread.send_recovery["status"] == "unknown"
    assert not (await bridge._handle_send_message(request))["accepted"]
    assert not (await bridge._handle_send_message({**request, "request_id": "sample-other"}))["ok"]
    assert not (await bridge._handle_send_message({**request, "request_id": ""}))["ok"]
    assert not bridge._handle_prepare_app_update()["ok"]
    provider.message_hooks.send.assert_awaited_once()
    restarted = AppState(storage=load_storage(str(path)))
    restore_send_recoveries(restarted)
    assert restarted.message_bus.session_send_recovery("overlay-tool", thread.thread_id)["status"] == "unknown"


@pytest.mark.parametrize(("previous", "expected"), [("preparing", "failed"), ("sending", "unknown")])
def test_restart_recovers_without_sending(monkeypatch, tmp_path, previous, expected):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    thread.send_recovery = {"requestId": "sample-request", "text": "sample original", "attachments": []}
    checkpoint_send_recovery(state, workspace, thread, previous)
    restarted = AppState(storage=load_storage(str(path)))
    restore_send_recoveries(restarted)
    assert restarted.message_bus.session_send_recovery("overlay-tool", thread.thread_id)["status"] == expected
    assert ProviderOwnerBridge(restarted, data_dir=str(tmp_path))._handle_prepare_app_update()["ok"] is (expected == "failed")
    provider.message_hooks.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_attachment_fails_before_provider_and_success_receipt_is_idempotent(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    bad = {**request, "attachments": [{"path": str(tmp_path / "composer-attachments" / "missing.txt")}]}
    assert (await bridge._handle_send_message(bad))["accepted"]
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert thread.send_recovery["status"] == "failed"
    assert "附件已失效" in thread.send_recovery["error"]
    provider.message_hooks.send.assert_not_awaited()
    good = {**request, "request_id": "sample-next"}
    await bridge._handle_send_message(good)
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert (await bridge._handle_send_message(good))["accepted"]
    provider.message_hooks.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_failure_before_send_stops_submission(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    def fail(_):
        raise OSError("sample disk unavailable")
    monkeypatch.setattr("core.user_messages.recovery.save_storage", fail)
    assert not (await bridge._handle_send_message(request))["ok"]
    provider.message_hooks.send.assert_not_awaited()
    assert thread.send_recovery["status"] == "failed"


@pytest.mark.asyncio
async def test_recovery_is_available_even_when_provider_history_is_unavailable(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    thread.send_recovery = {"requestId": "sample-request", "text": "sample original", "attachments": []}
    checkpoint_send_recovery(state, workspace, thread, "failed", "sample send rejected")
    bridge._handle_read_session = AsyncMock(return_value={"ok": False, "error": "sample provider unavailable"})
    packets = []
    writer = SimpleNamespace(write=packets.append, drain=AsyncMock())
    await bridge._handle_session_event_stream(None, writer, {
        "provider_id": workspace.tool, "session_id": thread.thread_id, "workspace_dir": workspace.path,
    })
    frame = json.loads(packets[-1])
    assert frame["kind"] == "error"
    assert frame["recovery"]["text"] == "sample original"
    assert frame["recovery"]["status"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_late_codex_rpc_receipt_survives_restart_and_rechecks_without_resending(monkeypatch, tmp_path, rejected):
    from plugins.providers.builtin.codex.python.adapter import CodexAdapter
    from plugins.providers.builtin.codex.python import runtime

    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    adapter = CodexAdapter()
    adapter._connected = True
    state.set_adapter("overlay-tool", adapter)
    provider.message_hooks.ensure_connected.return_value = adapter
    provider.message_hooks.send = runtime.send_message
    monkeypatch.setattr("plugins.providers.builtin.codex.python.tui_bridge.uses_codex_shared_live_transport", lambda *_: True)
    packets = []
    adapter._send_raw = AsyncMock(side_effect=lambda raw: packets.append(json.loads(raw)))
    wait_for = asyncio.wait_for
    monkeypatch.setattr(asyncio, "wait_for", lambda future, timeout: wait_for(future, 0.001))
    await bridge._handle_send_message(request)
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert thread.send_recovery["status"] == "unknown"
    assert len(packets) == 1
    response = {"error": {"message": "sample request rejected"}} if rejected else {"result": {"turnId": "sample-turn"}}
    await adapter._dispatch(json.dumps({"id": packets[0]["id"], **response}))
    assert thread.send_recovery["status"] == "unknown"
    restarted = AppState(storage=load_storage(str(path)))
    restore_send_recoveries(restarted)
    if not rejected:
        from core.messages.events import create_message_event
        restarted.message_bus.publish(create_message_event("session.history.loaded", provider_id=workspace.tool,
            session_id=thread.thread_id, payload={"turns": [
                {"role": "user", "content": request["text"]}, {"role": "assistant", "content": "sample reply"}]}))
    recheck = ProviderOwnerBridge(restarted, data_dir=str(tmp_path))._handle_recheck_session_send({
        "provider_id": "overlay-tool", "session_id": thread.thread_id,
        "workspace_dir": workspace.path, "request_id": request["request_id"],
    })
    assert recheck["recovery"]["status"] == ("failed" if rejected else "sent")
    assert recheck["accepted"] is not rejected
    assert len(packets) == 1
    assert restarted.message_bus.session_send_recovery("overlay-tool", thread.thread_id)["status"] == recheck["recovery"]["status"]
    if not rejected:
        activity = restarted.message_bus.session_activity("overlay-tool", thread.thread_id)
        assert activity["status"] != "failed"
        assert activity["deliveryError"] == ""
        assert len(restarted.message_bus.session_conversation(workspace.tool, thread.thread_id)) == 2


def test_recheck_requires_the_exact_request_and_session_receipt(monkeypatch, tmp_path):
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    thread.send_recovery = {"requestId": request["request_id"], "text": request["text"], "attachments": [],
                            "providerReceipt": {"requestId": request["request_id"], "threadId": "different-session", "status": "sent"}}
    checkpoint_send_recovery(state, workspace, thread, "unknown", "sample uncertain response")
    recheck = {"provider_id": workspace.tool, "session_id": thread.thread_id,
               "workspace_dir": workspace.path, "request_id": request["request_id"]}
    assert bridge._handle_recheck_session_send(recheck)["recovery"]["status"] == "unknown"
    assert not bridge._handle_recheck_session_send({**recheck, "request_id": "different-request"})["ok"]
    assert not bridge._handle_recheck_session_send({**recheck, "workspace_dir": "/tmp/another-workspace"})["ok"]
    provider.message_hooks.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_creation_wait_preserves_input_across_restart_without_creating_twice(monkeypatch, tmp_path):
    from core import provider_owner_bridge, provider_session_new
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    persist = lambda storage: save_storage(storage, str(path))
    monkeypatch.setattr(provider_owner_bridge, "save_storage", persist)
    monkeypatch.setattr(provider_session_new, "save_storage", persist)
    release = asyncio.Event()

    async def create(_):
        await release.wait()
        return {"id": "sample-created-session"}

    adapter = state.get_adapter("overlay-tool")
    adapter.start_thread = AsyncMock(side_effect=create)
    request = {**request, "text": ("sample full original " * 300).strip()}
    response = await bridge._handle_start_session_message(request)
    assert response["pending"]
    restarted = AppState(storage=load_storage(str(path)))
    restarted.set_adapter("overlay-tool", adapter)
    restore_send_recoveries(restarted)
    next_bridge = ProviderOwnerBridge(restarted, data_dir=str(tmp_path))
    status = next_bridge._handle_recheck_session_send({"provider_id": workspace.tool, "workspace_dir": workspace.path})
    assert status["recovery"]["status"] == "unknown"
    assert status["recovery"]["text"] == request["text"]
    assert not (await next_bridge._handle_start_session_message(request))["accepted"]
    adapter.start_thread.assert_awaited_once()
    release.set()
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    status = bridge._handle_recheck_session_send({"provider_id": workspace.tool, "workspace_dir": workspace.path,
                                               "request_id": request["request_id"]})
    assert status["thread_id"] == "sample-created-session"
    assert status["recovery"]["status"] == "sent"
    provider.message_hooks.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_sent_first_message_with_failed_save_uses_receipt_after_restart(monkeypatch, tmp_path):
    from core import provider_session_new as new
    from core.user_messages.recovery import record_delivery_receipt
    state, workspace, thread, provider, bridge, request, path = setup_send(monkeypatch, tmp_path)
    fail_save = True

    def persist(storage):
        nonlocal fail_save
        if thread.new_session_recovery.get("send_status") == "sent" and fail_save:
            fail_save = False
            raise OSError("sample save failure")
        save_storage(storage, str(path))

    monkeypatch.setattr(new, "save_storage", persist)
    thread.new_session_recovery = {"request_id": request["request_id"], "text": request["text"], "attachments": [], "send_status": "pending"}

    async def send(*_, **__):
        record_delivery_receipt(state, workspace, thread, request["request_id"],
            {"status": "sent", "threadId": thread.thread_id, "turnId": "sample-turn"})
        return {}

    provider.message_hooks.send = AsyncMock(side_effect=send)
    monkeypatch.setattr(new, "get_provider", lambda *_: provider)
    with pytest.raises(OSError):
        await new.send_started_provider_thread_message(state, workspace, thread, workspace.daemon_workspace_id,
            provider_id=workspace.tool, text=request["text"], attachments=[], source="session_tab", adapter=state.get_adapter(workspace.tool))
    restarted = AppState(storage=load_storage(str(path)))
    restore_send_recoveries(restarted)
    recheck = ProviderOwnerBridge(restarted, data_dir=str(tmp_path))._handle_recheck_session_send({
        "provider_id": workspace.tool, "workspace_dir": workspace.path,
        "session_id": thread.thread_id, "request_id": request["request_id"],
    })
    assert recheck["accepted"]
    assert recheck["recovery"]["status"] == "sent"
    provider.message_hooks.send.assert_awaited_once()
