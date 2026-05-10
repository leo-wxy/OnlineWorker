import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import Config, ToolConfig
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.state import StreamingTurn
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


GROUP_CHAT_ID = -100123456789


def _append_response_item(path: Path, *, role: str, phase: str, text: str, timestamp: str) -> None:
    record = {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "role": role,
            "phase": phase,
            "content": [{"type": "output_text", "text": text}],
        },
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_raw_response_item(path: Path, payload: dict, *, timestamp: str) -> None:
    record = {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": payload,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _make_state(tmp_path: Path):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "04" / "06"
    day_dir.mkdir(parents=True)
    session_file = day_dir / "rollout-2026-04-06T10-00-00-tid-1.jsonl"

    return state, ws, session_file, sessions_dir


def _make_app_mode_config() -> Config:
    return Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="stdio",
                control_mode="app",
                live_transport="owner_bridge",
            )
        ],
        delete_archived_topics=True,
    )


@pytest.mark.asyncio
async def test_watch_codex_thread_initializes_watch_state(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import watch_codex_thread

    state, ws, session_file, _sessions_dir = _make_state(tmp_path)
    session_file.touch()

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)

    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    assert watch.workspace_id == "codex:onlineWorker"
    assert watch.topic_id == 100
    assert watch.last_offset == 0
    assert watch.turn_started_sent is False
    assert watch.active_until > 0
    assert watch.poll_interval_seconds == 0.5
    assert watch.next_poll_at > 0


@pytest.mark.asyncio
async def test_sync_watched_thread_once_backs_off_when_no_new_content(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    session_file.touch()

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)
    watch.last_offset = session_file.stat().st_size

    handler = AsyncMock()

    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )
    assert watch.idle_polls == 1
    assert watch.poll_interval_seconds == 0.5

    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )
    assert watch.idle_polls == 2
    assert watch.poll_interval_seconds == 1.5

    for _ in range(4):
        await sync_watched_thread_once(
            state,
            handler,
            "tid-1",
            watch,
            sessions_dir=str(sessions_dir),
        )

    assert watch.idle_polls == 6
    assert watch.poll_interval_seconds == 5.0
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_watched_thread_once_emits_commentary_and_final_events(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[
                SimpleNamespace(message_id=5001),
                SimpleNamespace(message_id=5002),
            ]
        ),
        delete_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="处理中",
        timestamp="2026-04-06T10:00:01Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="最终回复",
        timestamp="2026-04-06T10:00:10Z",
    )

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)

    from bot.events import make_event_handler

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in state.streaming_turns
    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-06T10:00:10Z\n最终回复"
    assert bot.send_message.await_count >= 2
    sent_texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert "⏳ 思考中..." in sent_texts
    assert any("处理中" in text for text in sent_texts)
    assert bot.edit_message_text.await_count >= 1
    assert watch.idle_polls == 0
    assert watch.poll_interval_seconds == 0.5


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_in_app_mode_auto_watches_bound_thread_without_replaying_old_commentary(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, _ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_app_mode_config()
    handler = AsyncMock()

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程",
        timestamp="2026-04-06T10:00:01Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()

    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    assert watch.last_offset == session_file.stat().st_size

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="新过程",
        timestamp="2026-04-06T10:00:02Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    methods = [call.args[1]["message"]["method"] for call in handler.await_args_list]
    assert methods == ["turn/started", "item/agentMessage/delta"]


@pytest.mark.asyncio
async def test_sync_watched_thread_once_skips_commentary_when_live_streaming_turn_already_exists(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_watched_thread_once, watch_codex_thread

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    handler = AsyncMock()

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="live 过程",
        timestamp="2026-04-06T10:00:01Z",
    )

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)
    state.streaming_turns["tid-1"] = StreamingTurn(
        message_id=5001,
        topic_id=100,
        turn_id="turn-live",
        buffer="已有实时链",
    )

    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )

    handler.assert_not_awaited()
    assert watch.last_commentary_text == "live 过程"


@pytest.mark.asyncio
async def test_sync_watched_thread_once_skips_final_already_synced_to_tg(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_watched_thread_once, watch_codex_thread

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    handler = AsyncMock()
    codex_state.get_runtime(state).last_synced_assistant["tid-1"] = "__text__\n最终回复"

    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="最终回复",
        timestamp="2026-04-06T10:00:10Z",
    )

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)

    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )

    handler.assert_not_awaited()
    assert watch.last_final_text == "最终回复"


@pytest.mark.asyncio
async def test_sync_watched_thread_once_ignores_reasoning_items_with_null_content(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    handler = AsyncMock()

    _append_raw_response_item(
        session_file,
        {
            "type": "reasoning",
            "summary": [],
            "content": None,
        },
        timestamp="2026-04-06T10:00:01Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="继续处理中",
        timestamp="2026-04-06T10:00:02Z",
    )

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)

    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )

    handler.assert_awaited()
    assert watch.last_commentary_text == "继续处理中"


def test_write_codex_tui_diagnostics_snapshot(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import write_codex_tui_diagnostics_snapshot
    from core.state import StreamingTurn

    state, ws, session_file, _sessions_dir = _make_state(tmp_path)
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import watch_codex_thread

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)
    watch.last_offset = 123
    watch.turn_started_sent = True
    watch.idle_polls = 2
    watch.last_commentary_text = "处理中"
    watch.next_poll_at = watch.last_poll_at + 1.5

    state.streaming_turns["tid-1"] = StreamingTurn(message_id=5001, topic_id=100)
    codex_state.get_runtime(state).mirror_task = MagicMock()
    codex_state.get_runtime(state).mirror_task.done.return_value = False

    with patch("plugins.providers.builtin.codex.python.tui_realtime_mirror.get_data_dir", return_value=str(tmp_path)):
        write_codex_tui_diagnostics_snapshot(state)
        snapshot_path = tmp_path / "codex_tui_mirror_status.json"
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert payload["tool"] == "codex"
    assert payload["mode"] == "tui"
    assert payload["mirror_task_running"] is True
    assert payload["streaming_turn_count"] == 1
    assert payload["watched_thread_count"] == 1
    watched = payload["watched_threads"][0]
    assert watched["thread_id"] == "tid-1"
    assert watched["workspace_id"] == "codex:onlineWorker"
    assert watched["topic_id"] == 100
    assert watched["last_offset"] == 123
    assert watched["idle_polls"] == 2
    assert watched["has_commentary"] is True
    assert watched["has_final"] is False
