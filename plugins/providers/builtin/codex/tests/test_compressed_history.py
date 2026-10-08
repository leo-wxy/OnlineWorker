from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import zstandard

from plugins.providers.builtin.codex.python import storage_runtime


SESSION_ID = "00000000-0000-4000-8000-000000000026"
WORKSPACE = "/tmp/sample-workspace"


def _write_history(directory, *, compressed, user_text="hello"):
    directory.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "session_meta", "timestamp": "2026-01-01T00:00:00Z",
         "payload": {"id": SESSION_ID, "cwd": WORKSPACE, "source": "vscode"}},
        {"type": "response_item", "timestamp": "2026-01-01T00:00:01Z",
         "payload": {"role": "user", "content": [{"type": "input_text", "text": user_text}]}},
        {"type": "event_msg", "timestamp": "2026-01-01T00:00:01Z",
         "payload": {"type": "user_message", "message": user_text}},
        {"type": "response_item", "timestamp": "2026-01-01T00:00:02Z",
         "payload": {"role": "assistant", "phase": "commentary",
                     "content": [{"type": "output_text", "text": "working"}]}},
        {"type": "response_item", "timestamp": "2026-01-01T00:00:03Z",
         "payload": {"role": "assistant", "phase": "final_answer",
                     "content": [{"type": "output_text", "text": "done"}]}},
        {"type": "event_msg", "timestamp": "2026-01-01T00:00:04Z",
         "payload": {"type": "task_complete", "turn_id": "sample-turn", "last_agent_message": "done"}},
    ]
    data = "".join(json.dumps(row) + "\n" for row in rows).encode()
    path = directory / f"rollout-2026-01-01T00-00-00-{SESSION_ID}.jsonl"
    if compressed:
        path = path.with_suffix(".jsonl.zst")
        data = zstandard.ZstdCompressor().compress(data)
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("compressed", [False, True])
def test_codex_history_metadata_and_terminal_reads_support_both_formats(tmp_path, compressed):
    path = _write_history(tmp_path, compressed=compressed)
    root = str(tmp_path)

    history = storage_runtime.read_thread_history(SESSION_ID, sessions_dir=root, limit=10)
    assert [(turn["role"], turn["text"], turn["phase"]) for turn in history] == [
        ("user", "hello", ""),
        ("assistant", "working", "commentary"),
        ("assistant", "done", "final_answer"),
    ]
    assert history[-1]["timestamp"] == "2026-01-01T00:00:03Z"
    assert storage_runtime.read_thread_history(SESSION_ID, sessions_dir=root, limit=1) == history[-1:]
    assert storage_runtime.find_session_file(SESSION_ID, root, include_compressed=True) == str(path)
    assert storage_runtime._extract_codex_thread_id_from_filename(path.name) == SESSION_ID
    metadata, running = storage_runtime._scan_codex_session_file(str(path))
    assert metadata["id"] == SESSION_ID
    assert metadata["cwd"] == WORKSPACE
    assert metadata["preview"] == "hello"
    assert metadata["updatedAt"] == 1767225604000
    assert running is False
    assert storage_runtime.read_codex_turn_terminal_message(SESSION_ID, root, "sample-turn") == "done"
    assert storage_runtime.read_codex_turn_terminal_outcome(SESSION_ID, root, "sample-turn") == {
        "status": "completed", "text": "done", "reason": "",
    }


def test_plain_history_wins_when_both_formats_exist(tmp_path):
    _write_history(tmp_path, compressed=True, user_text="old")
    plain = _write_history(tmp_path, compressed=False, user_text="current")

    assert storage_runtime.find_session_file(SESSION_ID, str(tmp_path)) == str(plain)
    assert storage_runtime.read_thread_history(SESSION_ID, str(tmp_path))[0]["text"] == "current"
    assert storage_runtime._build_codex_session_index(str(tmp_path))["workspace_counts"] == {WORKSPACE: 1}


def test_compressed_history_is_not_used_for_live_byte_offset_reads(tmp_path):
    from plugins.providers.builtin.codex.python import external_ingress, tui_realtime_mirror

    _write_history(tmp_path, compressed=True)
    assert external_ingress.find_session_file(SESSION_ID, str(tmp_path)) is None
    assert tui_realtime_mirror.find_session_file(SESSION_ID, str(tmp_path)) is None


def test_invalid_compressed_history_reports_read_failure(tmp_path):
    path = _write_history(tmp_path, compressed=True)
    path.write_bytes(b"invalid zstd data")

    with pytest.raises(RuntimeError, match="compressed Codex"):
        storage_runtime.read_thread_history(SESSION_ID, str(tmp_path))


@pytest.mark.asyncio
async def test_compressed_history_reaches_existing_bus_initial_snapshot(tmp_path, monkeypatch):
    from core import provider_owner_bridge
    from core.state import AppState
    from core.storage import AppStorage

    _write_history(tmp_path, compressed=True)
    facts = SimpleNamespace(read_thread_history=lambda session_id, *, limit:
                            storage_runtime.read_thread_history(session_id, str(tmp_path), limit))
    monkeypatch.setattr(provider_owner_bridge, "get_provider", lambda *args: SimpleNamespace(facts=facts))
    snapshots = []

    async def capture_snapshot(reader, writer, queue, closed, initial):
        snapshots.append(initial)

    monkeypatch.setattr(provider_owner_bridge, "_run_stream_writer", capture_snapshot)
    state = AppState(storage=AppStorage())
    bridge = provider_owner_bridge.ProviderOwnerBridge(state, data_dir=str(tmp_path))
    await bridge._handle_session_event_stream(asyncio.StreamReader(), MagicMock(), {
        "provider_id": "codex", "session_id": SESSION_ID, "workspace_dir": WORKSPACE,
    })

    assert snapshots[0]["kind"] == "replace_snapshot"
    assert [turn["content"] for turn in snapshots[0]["snapshot"]] == ["hello", "working", "done"]
    assert state.message_bus.session_history_loaded("codex", SESSION_ID)


@pytest.mark.asyncio
async def test_compressed_read_failure_preserves_existing_bus_history(tmp_path, monkeypatch):
    from core import provider_owner_bridge
    from core.messages.events import create_message_event
    from core.state import AppState
    from core.storage import AppStorage

    path = _write_history(tmp_path, compressed=True)
    path.write_bytes(b"invalid zstd data")
    facts = SimpleNamespace(read_thread_history=lambda session_id, *, limit:
                            storage_runtime.read_thread_history(session_id, str(tmp_path), limit))
    monkeypatch.setattr(provider_owner_bridge, "get_provider", lambda *args: SimpleNamespace(facts=facts))
    state = AppState(storage=AppStorage())
    state.message_bus.publish(create_message_event(
        "session.history.loaded", provider_id="codex", session_id=SESSION_ID,
        workspace_path=WORKSPACE, payload={"turns": [{"role": "assistant", "content": "keep"}]},
    ))
    before = state.message_bus.session_conversation("codex", SESSION_ID)
    bridge = provider_owner_bridge.ProviderOwnerBridge(state, data_dir=str(tmp_path))
    response = await bridge._handle_read_session({"provider_id": "codex", "session_id": SESSION_ID})

    assert response["ok"] is False
    assert "compressed Codex" in response["error"]
    assert state.message_bus.session_conversation("codex", SESSION_ID) == before
