import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.state import StreamingTurn
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


GROUP_CHAT_ID = -100123456789


def _append_response_item(
    path: Path,
    *,
    role: str,
    phase: str,
    text: str,
    timestamp: str,
    turn_id: str = "",
    passthrough_turn_id: str = "",
) -> None:
    content_type = "input_text" if role == "user" else "output_text"
    record = {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "role": role,
            "phase": phase,
            "content": [{"type": content_type, "text": text}],
        },
    }
    if turn_id:
        record["payload"]["turn_id"] = turn_id
    if passthrough_turn_id:
        record["payload"]["internal_chat_message_metadata_passthrough"] = {
            "turn_id": passthrough_turn_id,
        }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _append_session_meta(
    path: Path,
    *,
    thread_id: str,
    cwd: str,
    timestamp: str = "2026-04-06T10:00:00Z",
) -> None:
    record = {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "cwd": cwd,
            "timestamp": timestamp,
            "source": "cli",
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
                bin="codex",
                protocol="stdio",
                control_mode="app",
                live_transport="owner_bridge",
            )
        ],
        delete_archived_topics=True,
    )


def _make_shared_live_app_mode_config() -> Config:
    return Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                bin="codex",
                protocol="unix",
                control_mode="app",
                live_transport="shared_unix",
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
async def test_sync_watched_thread_once_completes_commentary_only_turn_after_idle(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        COMMENTARY_IDLE_COMPLETION_POLLS,
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    handler = AsyncMock()

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="处理中",
        timestamp="2026-04-06T10:00:01Z",
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

    methods = [call.args[1]["message"]["method"] for call in handler.await_args_list]
    assert methods == ["turn/started", "item/agentMessage/delta"]
    assert watch.turn_started_sent is True

    handler.reset_mock()
    for _ in range(COMMENTARY_IDLE_COMPLETION_POLLS):
        await sync_watched_thread_once(
            state,
            handler,
            "tid-1",
            watch,
            sessions_dir=str(sessions_dir),
        )

    methods = [call.args[1]["message"]["method"] for call in handler.await_args_list]
    assert methods == ["turn/completed"]
    assert watch.turn_started_sent is False


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
        turn_id="turn-live",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="最终回复",
        timestamp="2026-04-06T10:00:10Z",
        turn_id="turn-live",
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
    run = codex_state.get_current_run(state, "tid-1")
    assert run is not None
    assert run.turn_id == "turn-live"
    assert run.final_reply_synced_to_tg is True
    assert bot.send_message.await_count >= 2
    sent_texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert "⏳ 思考中..." in sent_texts
    assert any("处理中" in text for text in sent_texts)
    assert bot.edit_message_text.await_count >= 1
    assert watch.idle_polls == 0
    assert watch.poll_interval_seconds == 0.5


@pytest.mark.asyncio
async def test_sync_watched_thread_once_reads_codex_internal_turn_id(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    handler = AsyncMock()

    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="最终回复",
        timestamp="2026-04-06T10:00:10Z",
        passthrough_turn_id="turn-from-internal",
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

    methods = [call.args[1]["message"]["method"] for call in handler.await_args_list]
    assert methods == ["turn/started", "item/completed", "turn/completed"]
    for call in handler.await_args_list:
        params = call.args[1]["message"]["params"]
        assert params["turnId"] == "turn-from-internal"


@pytest.mark.asyncio
async def test_sync_watched_thread_once_marks_final_turn_to_skip_delayed_duplicate(tmp_path):
    from bot.events import make_event_handler
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        sync_watched_thread_once,
        watch_codex_thread,
    )

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=5001)),
        delete_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )

    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="最终回复",
        timestamp="2026-04-06T10:00:10Z",
        turn_id="turn-live",
    )

    watch_codex_thread(state, ws, "tid-1", ttl_seconds=120)
    watch = codex_state.get_runtime(state).watched_threads["tid-1"]
    watch.session_file = str(session_file)

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    await sync_watched_thread_once(
        state,
        handler,
        "tid-1",
        watch,
        sessions_dir=str(sessions_dir),
    )

    initial_send_count = bot.send_message.await_count
    initial_edit_count = bot.edit_message_text.await_count
    assert initial_send_count == 1
    assert initial_edit_count == 1
    run = codex_state.get_current_run(state, "tid-1")
    assert run is not None
    assert run.turn_id == "turn-live"
    assert run.final_reply_synced_to_tg is True

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-1",
                    "turnId": "turn-live",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-1",
                        "phase": "final_answer",
                        "text": "最终回复",
                        "turn": {"id": "turn-live", "threadId": "tid-1"},
                    },
                },
            },
        },
    )

    assert bot.send_message.await_count == initial_send_count
    assert bot.edit_message_text.await_count == initial_edit_count


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_in_app_mode_does_not_auto_watch_bound_thread(tmp_path):
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

    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_does_not_import_unmanaged_local_thread_in_shared_live_mode(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_shared_live_app_mode_config()
    ws.topic_id = None
    ws.threads.pop("tid-1")
    handler = AsyncMock()

    _append_session_meta(
        session_file,
        thread_id="tid-1",
        cwd=ws.path,
    )
    _append_response_item(
        session_file,
        role="user",
        phase="",
        text="继续查 codex 通知",
        timestamp="2026-04-06T10:00:00Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程不应重放",
        timestamp="2026-04-06T10:00:01Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in ws.threads
    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_does_not_watch_existing_unmanaged_thread_without_topic_in_shared_live_mode(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_shared_live_app_mode_config()
    ws.topic_id = None
    ws.threads["tid-1"].topic_id = None
    ws.threads["tid-1"].source = "unknown"
    ws.threads["tid-1"].is_active = True
    handler = AsyncMock()

    _append_session_meta(
        session_file,
        thread_id="tid-1",
        cwd=ws.path,
    )
    _append_response_item(
        session_file,
        role="user",
        phase="",
        text="继续查 codex 通知",
        timestamp="2026-04-06T10:00:00Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程不应重放",
        timestamp="2026-04-06T10:00:01Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    assert ws.threads["tid-1"].source == "unknown"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_does_not_emit_session_file_updates_for_shared_live_thread(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_shared_live_app_mode_config()
    ws.threads["tid-1"].topic_id = None
    ws.threads["tid-1"].source = "unknown"
    ws.threads["tid-1"].is_active = True
    handler = AsyncMock()

    _append_session_meta(
        session_file,
        thread_id="tid-1",
        cwd=ws.path,
    )
    _append_response_item(
        session_file,
        role="user",
        phase="",
        text="继续查 codex 通知",
        timestamp="2026-04-06T10:00:00Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程不应重放",
        timestamp="2026-04-06T10:00:01Z",
        turn_id="turn-shared",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_does_not_auto_watch_active_thread_bootstrap_commentary_in_app_mode(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_app_mode_config()
    ws.threads["tid-1"].is_active = True
    handler = AsyncMock()

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程不应重放",
        timestamp="2026-04-06T10:00:01Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="最近旧过程也不应重放",
        timestamp="2026-04-06T10:00:02Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_codex_tui_realtime_once_does_not_auto_watch_active_thread_bootstrap_final_answer_in_app_mode(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_app_mode_config()
    ws.threads["tid-1"].is_active = True
    handler = AsyncMock()
    final_text = "# 命令结果\n\n```bash\n/Users/example/Projects/sample-workspace\nWed May  6 16:42:05 CST 2026\n```"

    _append_response_item(
        session_file,
        role="assistant",
        phase="commentary",
        text="旧过程不应重放",
        timestamp="2026-05-06T08:41:55Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text=final_text,
        timestamp="2026-05-06T08:42:05Z",
    )

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    assert "tid-1" not in codex_state.get_runtime(state).watched_threads
    handler.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_shared_live_imported_thread_bootstraps_bus_activity_without_live_event(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import sync_codex_tui_realtime_once

    state, ws, session_file, sessions_dir = _make_state(tmp_path)
    state.config = _make_shared_live_app_mode_config()
    ws.path = "/Users/example/Projects/onlineworker-combined"
    ws.name = "onlineworker-combined"
    ws.daemon_workspace_id = "codex:onlineworker-combined"
    imported_thread = ws.threads.pop("tid-1")
    imported_thread.thread_id = "tid-imported"
    imported_thread.preview = "继续查 codex 通知"
    imported_thread.source = "imported"
    imported_thread.is_active = True
    ws.threads["tid-imported"] = imported_thread
    state.storage.workspaces = {ws.daemon_workspace_id: ws}

    _append_response_item(
        session_file,
        role="user",
        phase="",
        text="继续查 codex 通知",
        timestamp="2026-04-06T10:00:00Z",
    )
    _append_response_item(
        session_file,
        role="assistant",
        phase="final_answer",
        text="已经定位到 shared-live 启动后缺少 session activity 恢复。",
        timestamp="2026-04-06T10:00:05Z",
        turn_id="turn-bootstrap-1",
    )
    renamed = session_file.with_name("rollout-2026-04-06T10-00-00-tid-imported.jsonl")
    session_file.rename(renamed)

    handler = AsyncMock()

    await sync_codex_tui_realtime_once(
        state,
        handler,
        sessions_dir=str(sessions_dir),
    )

    runtime = codex_state.get_runtime(state)
    assert "tid-imported" in runtime.watched_threads
    activity = state.message_bus.session_activity("codex", "tid-imported")
    assert activity is not None
    assert activity["status"] == "completed"
    assert activity["title"] == "继续查 codex 通知"
    assert activity["lastUserMessage"] == "继续查 codex 通知"
    assert activity["lastFinalMessage"] == "已经定位到 shared-live 启动后缺少 session activity 恢复。"
    handler.assert_not_awaited()


def test_touch_codex_tui_watch_state_updates_runtime_marker(tmp_path):
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import touch_codex_tui_watch_state

    state, _ws, _session_file, _sessions_dir = _make_state(tmp_path)
    runtime = codex_state.get_runtime(state)
    assert runtime.last_watch_state_touch == 0.0

    touch_codex_tui_watch_state(state)

    assert runtime.last_watch_state_touch > 0.0
