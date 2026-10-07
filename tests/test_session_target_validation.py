import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.provider_owner_bridge import ProviderOwnerBridge
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


def setup_target(monkeypatch, tmp_path, *, bound=True, connected=True):
    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="overlay-tool",
                              daemon_workspace_id="overlay-tool:/tmp/sample-workspace")
    thread = ThreadInfo(thread_id="sample-session", source="provider")
    workspace.threads[thread.thread_id] = thread
    state = AppState(storage=AppStorage(workspaces={workspace.daemon_workspace_id: workspace} if bound else {}))
    adapter = SimpleNamespace(connected=True, start_thread=AsyncMock(return_value={"id": "sample-created-session"}))
    if connected:
        state.set_adapter("overlay-tool", adapter)
    hooks = SimpleNamespace(ensure_connected=AsyncMock(return_value=adapter),
                            prepare_send=AsyncMock(return_value=True), send=AsyncMock(return_value={}))
    facts = SimpleNamespace(query_active_thread_ids=lambda path: {thread.thread_id} if path == workspace.path else set())
    monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *_: SimpleNamespace(message_hooks=hooks, facts=facts))
    monkeypatch.setattr("core.provider_owner_bridge.save_storage", lambda *_: None)
    monkeypatch.setattr("core.provider_session_new.save_storage", lambda *_: None)
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    request = {"provider_id": "overlay-tool", "thread_id": thread.thread_id,
               "workspace_dir": workspace.path, "text": "sample message", "request_id": "sample-request"}
    return state, workspace, thread, hooks, bridge, request


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["archived", "workspace", "provider"])
async def test_send_rejects_wrong_or_archived_binding(monkeypatch, tmp_path, invalid):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path)
    if invalid == "archived":
        thread.archived = True
    elif invalid == "workspace":
        request["workspace_dir"] = "/tmp/other-workspace"
    else:
        workspace.tool = "another-provider"
        monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *_: SimpleNamespace(message_hooks=hooks))
    response = await bridge._handle_send_message(request)
    assert not response["ok"]
    hooks.send.assert_not_awaited()
    assert not state.message_bus.recent_events()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["archive", "replace", "remove_workspace"])
async def test_queued_send_rechecks_current_binding(monkeypatch, tmp_path, change):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path)
    assert (await bridge._handle_send_message(request))["ok"]
    if change == "archive":
        thread.archived = True
    elif change == "replace":
        workspace.threads[thread.thread_id] = ThreadInfo(thread_id=thread.thread_id)
    else:
        state.storage.workspaces.clear()
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    hooks.send.assert_not_awaited()
    assert state.message_bus.session_activity("overlay-tool", thread.thread_id)["deliveryStatus"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("exists", [False, True])
async def test_external_session_is_imported_only_after_source_confirmation(monkeypatch, tmp_path, exists):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path, bound=False)
    if not exists:
        request["thread_id"] = "missing-session"
    result = await bridge._handle_send_message(request)
    assert result["ok"] is exists
    if exists:
        await asyncio.gather(*tuple(bridge._pending_send_tasks))
        hooks.send.assert_awaited_once()
        assert state.find_thread_by_id_global(thread.thread_id)[0].path == workspace.path
    else:
        hooks.send.assert_not_awaited()
        assert not state.storage.workspaces


@pytest.mark.asyncio
@pytest.mark.parametrize("creating", [False, True])
async def test_send_and_creation_wait_for_provider_reconnection(monkeypatch, tmp_path, creating):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path, connected=False)
    handle = bridge._handle_start_session_message if creating else bridge._handle_send_message
    response = await handle(request)
    assert response["ok"]
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert hooks.ensure_connected.await_args_list[0].args[1] is None
    hooks.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_same_session_id_in_another_provider_cannot_replace_target(monkeypatch, tmp_path):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path)
    foreign = WorkspaceInfo(name="other", path="/tmp/other-workspace", tool="another-provider",
                            threads={thread.thread_id: ThreadInfo(thread_id=thread.thread_id)})
    state.storage.workspaces = {"another-provider:other": foreign, **state.storage.workspaces}
    assert (await bridge._handle_send_message(request))["ok"]
    await asyncio.gather(*tuple(bridge._pending_send_tasks))
    assert hooks.send.await_args.args[2] is workspace
    assert hooks.send.await_args.args[3] is thread


@pytest.mark.asyncio
async def test_first_message_rechecks_archive_after_connection_wait(monkeypatch, tmp_path):
    state, workspace, thread, hooks, bridge, request = setup_target(monkeypatch, tmp_path)
    adapter = state.get_adapter("overlay-tool")
    async def ensure_connected(*_args, **_kwargs):
        created = workspace.threads.get("sample-created-session")
        if created is not None:
            created.archived = True
        return adapter
    hooks.ensure_connected.side_effect = ensure_connected
    response = await bridge._handle_start_session_message(request)
    assert response["accepted"] is False
    hooks.send.assert_not_awaited()
    assert workspace.threads["sample-created-session"].new_session_recovery["send_status"] == "failed"
