import json
from unittest.mock import AsyncMock

import pytest

from core.messages.bus import MessageEventBus
from core.messages.session_bridge import message_event_from_session_event
from core.providers.session_events import normalize_session_event
from plugins.providers.builtin.codex.python.adapter import CodexAdapter
from plugins.providers.builtin.codex.python.storage_runtime import is_codex_user_visible_session, _scan_codex_session_file


@pytest.mark.asyncio
async def test_side_boundary_hides_registered_hook_session_without_ephemeral_metadata(monkeypatch):
    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids", lambda ids: set())
    adapter = CodexAdapter()
    adapter._thread_workspace_map["sample-side"] = "codex:/tmp/sample-workspace"
    callback = AsyncMock()
    adapter.on_event(callback)
    result = await adapter.ingest_external_hook_payload({
        "hook_event_name": "UserPromptSubmit", "session_id": "sample-side", "cwd": "/tmp/sample-workspace",
        "input_messages": ["Side conversation boundary.\nEverything before this boundary is inherited history."],
    })
    assert result["suppressed"] == "non_user_visible_session"
    assert "sample-side" not in adapter._thread_workspace_map
    assert callback.await_args.args[1]["message"]["method"] == "session.hidden"
    callback.reset_mock()
    await adapter.ingest_external_hook_payload({"hook_event_name": "UserPromptSubmit", "session_id": "sample-side", "prompt": "later side prompt"})
    callback.assert_not_awaited()


def test_desktop_side_input_history_is_hidden_but_durable_main_thread_remains_visible(monkeypatch, tmp_path):
    import sqlite3
    from plugins.providers.builtin.codex.python import storage_runtime

    home = tmp_path / "sample-home"
    home.mkdir()
    database = home / "state_5.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("create table threads (id text, source text, cwd text)")
        connection.execute("insert into threads values ('sample-main', 'vscode', '/tmp/sample-workspace')")
    (home / ".codex-global-state.json").write_text(json.dumps({"electron-persisted-atom-state": {
        "prompt-history": {"sample-main": ["sample normal prompt"], "sample-side": ["sample side prompt"]},
    }}))
    expanduser = storage_runtime.os.path.expanduser
    monkeypatch.setattr(storage_runtime.os.path, "expanduser", lambda path: str(home / path.removeprefix("~/.codex/")) if path.startswith("~/.codex/") else expanduser(path))
    monkeypatch.setattr(storage_runtime, "find_session_file", lambda session_id: None)
    assert storage_runtime.list_codex_subagent_thread_ids(["sample-main", "sample-side", "sample-unrelated"]) == {"sample-side"}


@pytest.mark.asyncio
async def test_commentary_item_identity_keeps_two_updates_and_dedupes_replay(monkeypatch):
    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids", lambda ids: set())
    adapter = CodexAdapter()
    adapter.register_workspace_cwd("codex:/tmp/sample-workspace", "/tmp/sample-workspace")
    bus = MessageEventBus()
    async def receive(method, params):
        event = normalize_session_event(method, params)
        bus.publish(message_event_from_session_event(event))
    adapter.on_event(receive)
    for item, text in [("item-a", "first update"), ("item-b", "second update"), ("item-b", "second update")]:
        await adapter.ingest_external_hook_payload({
            "hook_event_name": "AgentMessage", "session_id": "sample-session",
            "turn_id": "sample-turn", "cwd": "/tmp/sample-workspace",
            "source": "codex_rollout", "phase": "commentary", "item_id": item, "message": text,
        })
    activity = bus.session_activity("codex", "sample-session")
    assert activity["lastAssistantMessage"] == "second update"
    assert [event["payload"]["delta"] for event in bus.recent_events() if event["kind"] == "message.assistant.delta"] == ["first update", "second update"]


def test_distinct_commentary_without_item_id_is_not_deduped_by_turn():
    bus = MessageEventBus()
    for text in ("first update", "second update"):
        event = normalize_session_event("app-server-event", {
            "workspace_id": "codex:/tmp/sample-workspace", "message": {
                "method": "item/completed", "params": {"threadId": "sample-session", "turnId": "sample-turn",
                    "item": {"type": "agentMessage", "phase": "commentary", "text": text}},
            },
        })
        assert bus.publish(message_event_from_session_event(event))
    assert bus.session_activity("codex", "sample-session")["lastAssistantMessage"] == "second update"


@pytest.mark.asyncio
async def test_ephemeral_side_chat_never_enters_discovery_or_live_events(monkeypatch):
    assert not is_codex_user_visible_session("vscode", ephemeral=True)
    assert not is_codex_user_visible_session("vscode", thread_source="side_conversation")
    assert is_codex_user_visible_session("vscode", thread_source="user", ephemeral=False)
    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids", lambda ids: set())
    adapter = CodexAdapter()
    callback = AsyncMock()
    adapter.on_event(callback)
    adapter._call = AsyncMock(return_value={"data": [
        {"id": "sample-main", "source": "vscode", "ephemeral": False, "forkedFromId": "sample-parent"},
        {"id": "sample-side", "source": "vscode", "ephemeral": True},
    ]})
    assert [row["id"] for row in await adapter.list_threads("codex:/tmp/sample-workspace")] == ["sample-main"]
    result = await adapter.ingest_external_hook_payload({"hook_event_name": "UserPromptSubmit",
        "session_id": "sample-side", "ephemeral": True, "cwd": "/tmp/sample-workspace", "prompt": "sample prompt"})
    assert result["suppressed"] == "non_user_visible_session"
    callback.assert_not_awaited()
    assert "sample-side" not in adapter._thread_workspace_map


def test_ephemeral_rollout_does_not_create_workspace_metadata(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(json.dumps({"type": "session_meta", "payload": {
        "id": "sample-side", "cwd": "/tmp/sample-workspace", "source": "vscode", "ephemeral": True,
    }}) + "\n")
    assert _scan_codex_session_file(str(path))[0] is None


@pytest.mark.asyncio
async def test_hook_without_side_metadata_reads_provider_identity(monkeypatch):
    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids", lambda ids: set())
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._call = AsyncMock(return_value={"thread": {"id": "sample-side", "source": "vscode", "ephemeral": True}})
    callback = AsyncMock()
    adapter.on_event(callback)
    result = await adapter.ingest_external_hook_payload({
        "hook_event_name": "UserPromptSubmit", "session_id": "sample-side",
        "cwd": "/tmp/sample-workspace", "prompt": "sample prompt",
    })
    assert result["suppressed"] == "non_user_visible_session"
    adapter._call.assert_awaited_once_with("thread/read", {"threadId": "sample-side", "includeTurns": False})
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_side_identity_removes_existing_activity_and_rejects_late_events():
    import asyncio
    from core.messages.events import create_message_event

    adapter = CodexAdapter()
    adapter._connected = True
    adapter._call = AsyncMock(return_value={"thread": {"id": "sample-side", "ephemeral": True}})
    adapter._thread_workspace_map["sample-side"] = "codex:/tmp/sample-workspace"
    bus = MessageEventBus()
    bus.publish(create_message_event("turn.started", provider_id="codex", session_id="sample-side"))

    async def receive(method, params):
        bus.publish(message_event_from_session_event(normalize_session_event(method, params)))

    adapter.on_event(receive)
    await adapter._dispatch(json.dumps({"method": "turn/started", "params": {
        "threadId": "sample-side", "turn": {"id": "sample-turn"},
    }}))
    await asyncio.wait_for(adapter._event_queue.join(), 1)
    assert bus.session_activity("codex", "sample-side") is None
    assert bus.recent_events()[-1]["kind"] == "session.hidden"
    assert not bus.publish(create_message_event("message.assistant.delta", provider_id="codex", session_id="sample-side", payload={"delta": "late"}))
    assert not adapter.has_authoritative_live_session("sample-side")
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_normal_fork_identity_is_checked_once_and_remains_visible(monkeypatch):
    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids", lambda ids: set())
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._call = AsyncMock(return_value={"thread": {"id": "sample-main", "source": "vscode", "ephemeral": False, "forkedFromId": "sample-parent"}})
    adapter.on_event(AsyncMock())
    for event in ("SessionStart", "UserPromptSubmit"):
        result = await adapter.ingest_external_hook_payload({
            "hook_event_name": event, "session_id": "sample-main", "turn_id": "sample-turn",
            "cwd": "/tmp/sample-workspace", "prompt": "sample prompt",
        })
        assert "suppressed" not in result
    assert adapter._call.await_count == 1
    assert "sample-main" not in adapter._hidden_live_sessions


@pytest.mark.asyncio
async def test_missing_metadata_keeps_normal_session_and_does_not_query_each_message():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._call = AsyncMock(side_effect=RuntimeError("metadata unavailable"))
    assert await adapter._check_session_visibility("sample-main")
    assert await adapter._check_session_visibility("sample-main")
    assert adapter._call.await_count == 1
    assert "sample-main" not in adapter._hidden_live_sessions


@pytest.mark.asyncio
async def test_hidden_session_reaches_activity_stream_as_remove(tmp_path):
    import asyncio
    from core.messages.events import create_message_event
    from core.provider_owner_bridge import ProviderOwnerBridge
    from core.state import AppState
    from core.storage import AppStorage

    class Writer:
        def __init__(self):
            self.payloads = asyncio.Queue()

        def write(self, payload):
            self.payloads.put_nowait(json.loads(payload))

        async def drain(self):
            pass

    state = AppState(storage=AppStorage())
    state.message_bus.publish(create_message_event("turn.started", provider_id="overlay-tool", session_id="sample-side"))
    bridge = ProviderOwnerBridge(state, data_dir=str(tmp_path))
    reader, writer = asyncio.StreamReader(), Writer()
    stream = asyncio.create_task(bridge._handle_session_activity_stream(reader, writer, {}))
    try:
        snapshot = await asyncio.wait_for(writer.payloads.get(), 1)
        assert snapshot["activities"][0]["sessionId"] == "sample-side"
        state.message_bus.publish(create_message_event("session.hidden", provider_id="overlay-tool", session_id="sample-side"))
        removal = await asyncio.wait_for(writer.payloads.get(), 1)
        assert removal == {"ok": True, "kind": "remove", "providerId": "overlay-tool", "sessionId": "sample-side"}
    finally:
        reader.feed_eof()
        await asyncio.wait_for(stream, 1)


@pytest.mark.asyncio
async def test_startup_checks_old_side_binding_without_deleting_storage(monkeypatch):
    from types import SimpleNamespace
    from core.state import AppState
    from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
    from plugins.providers.builtin.codex.python.runtime import prime_thread_mappings

    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.find_session_file", lambda *args: None)
    workspace = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="codex", daemon_workspace_id="codex:/tmp/sample-workspace")
    workspace.threads["sample-side"] = ThreadInfo(thread_id="sample-side", source="unknown")
    storage = AppStorage(workspaces={"sample": workspace})
    state = AppState(storage=storage)
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._call = AsyncMock(return_value={"thread": {"id": "sample-side", "ephemeral": True}})

    async def receive(method, params):
        state.message_bus.publish(message_event_from_session_event(normalize_session_event(method, params)))

    adapter.on_event(receive)
    await prime_thread_mappings(SimpleNamespace(storage=storage, state=state), adapter)
    assert "sample-side" in adapter._hidden_live_sessions
    assert "sample-side" in workspace.threads
    assert state.message_bus.recent_events()[-1]["kind"] == "session.hidden"
