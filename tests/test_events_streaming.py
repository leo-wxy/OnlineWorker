import json
from pathlib import Path
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from telegram.error import BadRequest

from bot.events import make_event_handler
from core.providers.session_events import SessionEvent
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.state import StreamingTurn
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo


GROUP_CHAT_ID = -100123456789
SEMANTIC_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "codex_semantic_sequences.json"


def _load_semantic_sequences() -> dict:
    return json.loads(SEMANTIC_FIXTURE_PATH.read_text(encoding="utf-8"))


def _build_semantic_session_event(entry: dict, *, thread_id: str, turn_id: str) -> SessionEvent:
    kind = str(entry.get("kind") or "").strip()
    semantic_kind = str(entry.get("semanticKind") or "").strip()
    payload: dict = {
        "threadId": thread_id,
        "turnId": turn_id,
    }

    if kind == "turn_started":
        payload["turn"] = {"id": turn_id}
    elif kind == "assistant_completed":
        payload["item"] = {
            "type": "agentMessage",
            "threadId": thread_id,
        }
    elif kind == "turn_completed":
        payload["turn"] = {"id": turn_id}

    semantic_payload = {
        "kind": semantic_kind,
        "thread_id": thread_id,
        "turn_id": turn_id,
    }
    if "turn" in entry:
        semantic_payload["text"] = entry["turn"]["content"]
    if "phase" in entry:
        semantic_payload["phase"] = entry["phase"]
    if "reason" in entry:
        semantic_payload["reason"] = entry["reason"]

    return SessionEvent(
        provider="codex",
        workspace_id="codex:onlineWorker",
        thread_id=thread_id,
        turn_id=turn_id,
        kind=kind,
        payload=payload,
        raw_method=kind,
        semantic_kind=semantic_kind,
        semantic_payload=semantic_payload,
    )


@pytest.mark.asyncio
async def test_first_delta_persists_new_streaming_message_id():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(
        side_effect=[
            SimpleNamespace(message_id=5001),
            SimpleNamespace(message_id=5002),
        ]
    )
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    with patch("bot.events.save_storage") as save_storage_mock:
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "turn/started",
                    "params": {"threadId": "tid-123", "turn": {"id": "turn-123"}},
                },
            },
        )

        assert ws.threads["tid-123"].streaming_msg_id == 5001

        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "item/agentMessage/delta",
                    "params": {"threadId": "tid-123", "turnId": "turn-123", "delta": "hello"},
                },
            },
        )

        assert ws.threads["tid-123"].streaming_msg_id == 5002
        run = codex_state.get_current_run(state, "tid-123")
        assert run is not None
        assert run.first_progress_at > 0
        bot.delete_message.assert_awaited_once()
        assert save_storage_mock.call_count >= 2


@pytest.mark.asyncio
async def test_turn_completed_failed_edits_failure_instead_of_completed():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        buffer="",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {"threadId": "tid-123", "turn": {"status": "failed"}},
            },
        },
    )

    bot.edit_message_text.assert_awaited_once()
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert text != "✅ 已完成"
    assert "失败" in text or "错误" in text


@pytest.mark.asyncio
async def test_turn_completed_aborted_edits_interrupted_instead_of_completed():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        buffer="这是半截回复",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {
                        "status": "aborted",
                        "reason": "interrupted",
                    },
                },
            },
        },
    )

    bot.edit_message_text.assert_awaited_once()
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert "已中断" in text
    assert "不完整" in text


@pytest.mark.asyncio
async def test_turn_started_and_completed_update_codex_tui_turn_gate():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/started",
                "params": {"threadId": "tid-123", "turn": {"id": "turn-123"}},
            },
        },
    )

    assert "tid-123" in codex_state.get_runtime(state).active_threads
    assert not codex_state.get_tui_thread_idle_event(state, "tid-123").is_set()
    assert state.streaming_turns["tid-123"].turn_id == "turn-123"
    run = codex_state.get_current_run(state, "tid-123")
    assert run is not None
    assert run.run_id == "turn-123"
    assert run.status == "started"

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {"threadId": "tid-123", "turn": {"status": "completed"}},
            },
        },
    )

    assert "tid-123" not in codex_state.get_runtime(state).active_threads
    assert codex_state.get_tui_thread_idle_event(state, "tid-123").is_set()
    assert "tid-123" not in state.streaming_turns
    assert codex_state.get_current_run(state, "tid-123") is run
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_turn_completed_marks_streamed_reply_as_synced_for_background_dedup():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="这是已经通过 streaming 发到 TG 的最终回复",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {"id": "turn-123", "status": "completed"},
                },
            },
        },
    )

    assert (
        codex_state.get_runtime(state).last_synced_assistant["tid-123"]
        == "__text__\n这是已经通过 streaming 发到 TG 的最终回复"
    )
    assert run.final_reply_synced_to_tg is True
    assert "tid-123" not in state.streaming_turns


@pytest.mark.asyncio
async def test_turn_completed_html_not_modified_does_not_fallback_to_plain_text():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="明天是 **2026 年 5 月 13 日**。",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message is not modified"))

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {"id": "turn-123", "status": "completed"},
                },
            },
        },
    )

    assert bot.edit_message_text.await_count == 1
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert "<b>2026 年 5 月 13 日</b>" in kwargs["text"]
    assert "tid-123" not in state.streaming_turns
    assert ws.threads["tid-123"].streaming_msg_id is None


@pytest.mark.asyncio
async def test_codex_turn_completed_keeps_single_stream_message_without_extra_stable_reply():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5002,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.thread_last_tg_user_message_ids["tid-123"] = 7001
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5002,
        topic_id=3794,
        turn_id="turn-123",
        buffer="🤖 OW CODEX LIVE 1",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {"id": "turn-123", "status": "completed"},
                },
            },
        },
    )

    bot.send_message.assert_not_awaited()
    bot.delete_message.assert_not_awaited()
    bot.edit_message_text.assert_not_awaited()
    assert (
        codex_state.get_runtime(state).last_synced_assistant["tid-123"]
        == "__text__\nOW CODEX LIVE 1"
    )
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns


@pytest.mark.asyncio
async def test_codex_turn_completed_no_longer_uses_persisted_reply_anchor():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5002,
    )
    setattr(ws.threads["tid-123"], "last_tg_user_message_id", 7002)
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5002,
        topic_id=3794,
        turn_id="turn-123",
        buffer="🤖 OW CODEX LIVE PERSISTED",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {"id": "turn-123", "status": "completed"},
                },
            },
        },
    )

    bot.send_message.assert_not_awaited()
    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_customprovider_streaming_reply_does_not_emit_duplicate_or_touch_codex_dedup_state():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="customprovider",
        topic_id=3794,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    ws.threads["ses-123"] = ThreadInfo(
        thread_id="ses-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"customprovider:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(
        side_effect=[
            SimpleNamespace(message_id=5001),
            SimpleNamespace(message_id=5002),
        ]
    )
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "turn/started",
                "params": {"threadId": "ses-123", "turn": {}},
            },
        },
    )
    await handler(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "item/agentMessage/delta",
                "params": {"threadId": "ses-123", "delta": "Hello"},
            },
        },
    )
    await handler(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "ses-123",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "ses-123",
                        "text": "Hello world",
                    },
                },
            },
        },
    )
    await handler(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "ses-123",
                    "turn": {"status": "completed"},
                },
            },
        },
    )

    assert bot.send_message.await_count == 2
    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["text"] == "Hello world"
    assert kwargs["parse_mode"] == "HTML"
    assert codex_state.get_runtime(state).last_synced_assistant == {}
    assert "ses-123" not in state.streaming_turns


@pytest.mark.asyncio
async def test_turn_started_materializes_missing_topic_for_registered_customprovider_thread():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="customprovider",
        topic_id=3794,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    ws.threads["ses-123"] = ThreadInfo(
        thread_id="ses-123",
        topic_id=None,
        preview="工程主要功能分析",
        archived=False,
        is_active=True,
    )
    storage = AppStorage(workspaces={"customprovider:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=6201))
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    replay_mock = AsyncMock(return_value="cursor-1")

    with patch("bot.events._replay_thread_history", new=replay_mock), patch(
        "bot.events.save_storage"
    ) as save_storage_mock:
        await handler(
            "app-server-event",
            {
                "workspace_id": "",
                "message": {
                    "method": "turn/started",
                    "params": {"threadId": "ses-123", "turn": {}},
                },
            },
        )

    bot.create_forum_topic.assert_awaited_once()
    replay_mock.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 6201
    assert ws.threads["ses-123"].topic_id == 6201
    assert ws.threads["ses-123"].history_sync_cursor == "cursor-1"
    assert state.streaming_turns["ses-123"].topic_id == 6201
    assert save_storage_mock.call_count >= 2


@pytest.mark.asyncio
async def test_turn_started_with_new_turn_id_replaces_previous_streaming_turn():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-old",
        buffer="上一轮还没收口",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5002))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    with patch("bot.events.save_storage") as save_storage_mock:
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "turn/started",
                    "params": {"threadId": "tid-123", "turn": {"id": "turn-new"}},
                },
            },
        )

    st = state.streaming_turns["tid-123"]
    assert st.turn_id == "turn-new"
    assert st.message_id == 5002
    assert st.buffer == ""
    assert not st.placeholder_deleted
    assert ws.threads["tid-123"].streaming_msg_id == 5002
    bot.send_message.assert_awaited_once()
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_stale_turn_completed_does_not_clear_newer_streaming_turn():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5002,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5002,
        topic_id=3794,
        turn_id="turn-new",
        buffer="新一轮思考中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    with patch("bot.events.save_storage") as save_storage_mock:
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "tid-123",
                        "turnId": "turn-old",
                        "turn": {"id": "turn-old", "status": "completed"},
                    },
                },
            },
        )

    assert state.streaming_turns["tid-123"].turn_id == "turn-new"
    assert ws.threads["tid-123"].streaming_msg_id == 5002
    bot.edit_message_text.assert_not_awaited()
    save_storage_mock.assert_not_called()


@pytest.mark.asyncio
async def test_stale_item_completed_does_not_overwrite_newer_streaming_turn():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5002,
        topic_id=3794,
        turn_id="turn-new",
        buffer="新一轮思考中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-old",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-123",
                        "text": "旧 turn 的最终回复",
                    },
                },
            },
        },
    )

    assert state.streaming_turns["tid-123"].buffer == "新一轮思考中"
    bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_answer_item_completed_marks_reply_as_synced_for_background_dedup():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-new",
    )
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5002,
        topic_id=3794,
        turn_id="turn-new",
        buffer="💭 分析中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-new",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-123",
                        "phase": "final_answer",
                        "text": "最终回复已经发到 TG",
                    },
                },
            },
        },
    )

    assert (
        codex_state.get_runtime(state).last_synced_assistant["tid-123"]
        == "__text__\n最终回复已经发到 TG"
    )
    assert run.final_reply_synced_to_tg is True


@pytest.mark.asyncio
async def test_item_completed_can_render_codex_semantic_final_reply_without_raw_item_text():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="思考中...",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    event = SessionEvent(
        provider="codex",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
        kind="assistant_completed",
        payload={
            "threadId": "tid-123",
            "turnId": "turn-123",
            "item": {
                "type": "agentMessage",
            },
        },
        raw_method="item/completed",
        semantic_kind="turn_completed",
        semantic_payload={
            "kind": "turn_completed",
            "thread_id": "tid-123",
            "turn_id": "turn-123",
            "text": "语义层最终回复",
            "phase": "final_answer",
        },
    )

    with patch("bot.events.normalize_session_event", return_value=event):
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "item/completed",
                    "params": {
                        "threadId": "tid-123",
                        "turnId": "turn-123",
                        "item": {"type": "agentMessage"},
                    },
                },
            },
        )

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["text"] == "语义层最终回复"
    assert kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_item_completed_final_reply_falls_back_to_plain_text_when_formatted_edit_fails():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="💭 还在整理中",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock(
        side_effect=[
            BadRequest("can't parse entities"),
            None,
        ]
    )

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    event = SessionEvent(
        provider="codex",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
        kind="assistant_completed",
        payload={
            "threadId": "tid-123",
            "turnId": "turn-123",
            "item": {"type": "agentMessage"},
        },
        raw_method="item/completed",
        semantic_kind="turn_completed",
        semantic_payload={
            "kind": "turn_completed",
            "thread_id": "tid-123",
            "turn_id": "turn-123",
            "text": "## 最终结果\n\n- 第一项",
            "phase": "final_answer",
        },
    )

    with patch("bot.events.normalize_session_event", return_value=event):
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "item/completed",
                    "params": {
                        "threadId": "tid-123",
                        "turnId": "turn-123",
                        "item": {"type": "agentMessage"},
                    },
                },
            },
        )

    assert bot.edit_message_text.await_count == 2
    assert bot.edit_message_text.await_args_list[0].kwargs["parse_mode"] == "HTML"
    assert bot.edit_message_text.await_args_list[1].kwargs["text"] == "## 最终结果\n\n- 第一项"
    assert "parse_mode" not in bot.edit_message_text.await_args_list[1].kwargs
    assert run.final_reply_synced_to_tg is True


@pytest.mark.asyncio
async def test_turn_completed_formats_streamed_buffer_when_no_final_item_arrives():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="## 最终结果\n\n- 第一项",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-123",
                    "turn": {"id": "turn-123", "status": "completed"},
                },
            },
        },
    )

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert "<b>最终结果</b>" in kwargs["text"]
    assert "• 第一项" in kwargs["text"]


@pytest.mark.asyncio
async def test_customprovider_item_completed_without_phase_formats_final_reply():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="customprovider",
        topic_id=3794,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    ws.threads["ses_123"] = ThreadInfo(
        thread_id="ses_123",
        topic_id=3794,
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"customprovider:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["ses_123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        buffer="还在输出",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    await handler(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "ses_123",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "ses_123",
                        "text": "## Custom Provider 最终结果\n\n- 已完成",
                    },
                },
            },
        },
    )

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["parse_mode"] == "HTML"
    assert "<b>Custom Provider 最终结果</b>" in kwargs["text"]
    assert "• 已完成" in kwargs["text"]


@pytest.mark.asyncio
async def test_turn_completed_can_use_semantic_abort_when_legacy_kind_is_not_aborted():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="这是半截回复",
        placeholder_deleted=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    event = SessionEvent(
        provider="codex",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
        kind="turn_completed",
        payload={
            "threadId": "tid-123",
            "turnId": "turn-123",
            "turn": {"id": "turn-123"},
        },
        raw_method="turn/completed",
        semantic_kind="turn_aborted",
        semantic_payload={
            "kind": "turn_aborted",
            "thread_id": "tid-123",
            "turn_id": "turn-123",
            "reason": "interrupted",
        },
    )

    with patch("bot.events.normalize_session_event", return_value=event):
        await handler(
            "app-server-event",
            {
                "workspace_id": "codex:onlineWorker",
                "message": {
                    "method": "turn/completed",
                    "params": {
                        "threadId": "tid-123",
                        "turnId": "turn-123",
                        "turn": {"id": "turn-123"},
                    },
                },
            },
        )

    bot.edit_message_text.assert_awaited_once()
    text = bot.edit_message_text.await_args.kwargs["text"]
    assert "已中断" in text
    assert "不完整" in text


@pytest.mark.asyncio
async def test_tg_codex_semantic_final_fixture_renders_single_completed_reply():
    sequences = _load_semantic_sequences()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    events = [
        _build_semantic_session_event(entry, thread_id="tid-123", turn_id="turn-123")
        for entry in sequences["final_sequence"]
    ]

    with patch("bot.events.normalize_session_event", side_effect=events):
        for entry in sequences["final_sequence"]:
            await handler(
                "app-server-event",
                {
                    "workspace_id": "codex:onlineWorker",
                    "message": {
                        "method": entry["kind"],
                        "params": {"threadId": "tid-123", "turnId": "turn-123"},
                    },
                },
            )

    bot.send_message.assert_awaited_once()
    assert bot.edit_message_text.await_args_list[0].kwargs["text"] == "💭 我先检查一下当前链路。"
    assert bot.edit_message_text.await_args_list[1].kwargs["text"] == "已经确认根因，开始修改。"
    assert bot.edit_message_text.await_args_list[1].kwargs["parse_mode"] == "HTML"
    assert "tid-123" not in state.streaming_turns


@pytest.mark.asyncio
async def test_tg_codex_semantic_abort_fixture_preserves_commentary_and_marks_incomplete():
    sequences = _load_semantic_sequences()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    events = [
        _build_semantic_session_event(entry, thread_id="tid-123", turn_id="turn-123")
        for entry in sequences["abort_sequence"]
    ]

    with patch("bot.events.normalize_session_event", side_effect=events):
        for entry in sequences["abort_sequence"]:
            await handler(
                "app-server-event",
                {
                    "workspace_id": "codex:onlineWorker",
                    "message": {
                        "method": entry["kind"],
                        "params": {"threadId": "tid-123", "turnId": "turn-123"},
                    },
                },
            )

    bot.send_message.assert_awaited_once()
    assert len(bot.edit_message_text.await_args_list) == 2
    final_text = bot.edit_message_text.await_args_list[-1].kwargs["text"]
    assert "我先检查一下当前链路。" in final_text
    assert "已中断" in final_text
    assert "不完整" in final_text
