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


class RecordingNotificationRouter:
    def __init__(self):
        self.events = []

    async def notify(self, event):
        self.events.append(event)
        return SimpleNamespace(sent=True, channels=("recording",), reason="")


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
async def test_turn_completed_sends_task_notification():
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
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="完成内容",
    )
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
        task_summary="接入 Codex、Claude 和扩展 provider 的用量读取，并修复 /token_usage agent 命令",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

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

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.status == "completed"
    assert event.agent_name == "Codex"
    assert event.agent_id == "codex"
    assert event.task_name == "修复用量统计"
    assert event.task_summary == "接入 Codex、Claude 和扩展 provider 的用量读取，并修复 /token_usage agent 命令"
    assert event.task_id == "turn-123"
    assert event.message == "任务已完成"


@pytest.mark.asyncio
async def test_turn_failed_sends_failed_task_notification():
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
        preview="Phase 6 通知机制",
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-123",
                    "turn": {
                        "id": "turn-123",
                        "status": "failed",
                        "error": "boom",
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.status == "failed"
    assert event.message == "任务失败：boom"
    assert event.dedupe_key == "turn-123:codex:failed"


@pytest.mark.asyncio
async def test_event_handler_builds_notification_router_from_state_config():
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
        preview="Phase 6 通知机制",
        archived=False,
        streaming_msg_id=5001,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.config = SimpleNamespace(enabled_notification_channels=[])
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=5001,
        topic_id=3794,
        turn_id="turn-123",
        buffer="完成内容",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    with patch("bot.events.build_notification_router", return_value=notifications) as build_router:
        handler = make_event_handler(state, bot, GROUP_CHAT_ID)

    build_router.assert_called_once_with(state.config)

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

    assert len(notifications.events) == 1


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
async def test_turn_started_does_not_materialize_missing_topic_for_claude_app_session():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="claude",
        topic_id=3794,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-claude-123"] = ThreadInfo(
        thread_id="ses-claude-123",
        topic_id=None,
        preview="App-created Claude session",
        archived=False,
        is_active=True,
    )
    storage = AppStorage(workspaces={"claude:onlineWorker": ws})
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
                "workspace_id": "claude:onlineWorker",
                "message": {
                    "method": "turn/started",
                    "params": {
                        "threadId": "ses-claude-123",
                        "turn": {"id": "turn-claude-1"},
                    },
                },
            },
        )

    bot.create_forum_topic.assert_not_awaited()
    replay_mock.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    assert ws.threads["ses-claude-123"].topic_id is None
    assert "ses-claude-123" not in state.streaming_turns
    save_storage_mock.assert_not_called()


@pytest.mark.asyncio
async def test_turn_started_does_not_materialize_missing_topic_for_external_app_session():
    ws = WorkspaceInfo(
        name="/",
        path="/",
        tool="external",
        topic_id=None,
        daemon_workspace_id="external:/",
    )
    ws.threads["ses-external-123"] = ThreadInfo(
        thread_id="ses-external-123",
        topic_id=None,
        preview="图里什么内容？",
        archived=False,
        is_active=True,
    )
    storage = AppStorage(workspaces={"external:/": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=6201))
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5001))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID)
    replay_mock = AsyncMock(return_value="cursor-1")

    def provider_for_test(name, *args, **kwargs):
        if name != "external":
            return None
        return SimpleNamespace(
            session_event_hooks=SimpleNamespace(
                should_materialize_unbound_thread_topic=lambda state, ws_info, thread_info: False
            )
        )

    with patch("core.providers.topic_policy.get_provider", side_effect=provider_for_test), patch(
        "bot.events._replay_thread_history", new=replay_mock
    ), patch("bot.events.save_storage") as save_storage_mock:
        await handler(
            "app-server-event",
            {
                "workspace_id": "external:/",
                "message": {
                    "method": "turn/started",
                    "params": {
                        "threadId": "ses-external-123",
                        "turn": {"id": "turn-external-1"},
                    },
                },
            },
        )

    bot.create_forum_topic.assert_not_awaited()
    replay_mock.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    assert ws.threads["ses-external-123"].topic_id is None
    assert "ses-external-123" not in state.streaming_turns
    save_storage_mock.assert_not_called()


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
async def test_final_answer_item_completed_sends_task_notification_and_dedupes_later_turn_completed():
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
        preview="POPO 通知验收",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
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
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

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

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.status == "completed"
    assert event.agent_name == "Codex"
    assert event.agent_id == "codex"
    assert event.task_name == "POPO 通知验收"
    assert event.task_summary == "POPO 通知验收"
    assert event.task_id == "turn-new"
    assert event.message == "完成摘要：最终回复已经发到 TG"

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-new",
                    "turn": {"id": "turn-new", "status": "completed"},
                },
            },
        },
    )

    assert len(notifications.events) == 1


@pytest.mark.asyncio
async def test_codex_delayed_final_events_skip_when_reply_already_synced(monkeypatch):
    async def fail_if_notification_summary_runs(**kwargs):
        raise AssertionError("duplicate final item should not generate notification summary")

    monkeypatch.setattr(
        "bot.events._notification_result_task_override_with_ai",
        fail_if_notification_summary_runs,
    )

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
        preview="重复 final 去重验证",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    run = codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-new",
    )
    codex_state.mark_run(
        state,
        thread_id="tid-123",
        final_reply_synced_to_tg=True,
        status="completed",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

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
                        "text": "这个 delayed final 不应该再发送",
                    },
                },
            },
        },
    )

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turnId": "turn-new",
                    "turn": {"id": "turn-new", "status": "completed"},
                },
            },
        },
    )

    bot.send_message.assert_not_awaited()
    bot.edit_message_text.assert_not_awaited()
    assert len(notifications.events) == 0
    assert run.final_reply_synced_to_tg is True
    assert run.status == "completed"


@pytest.mark.asyncio
async def test_tui_mirror_completed_with_final_buffer_uses_summary_notification(monkeypatch):
    async def fake_run_ai_scenario(scenario_id, variables):
        return SimpleNamespace(ok=False, data={})

    monkeypatch.setattr("bot.events.run_ai_scenario", fake_run_ai_scenario)
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-mirror"] = ThreadInfo(
        thread_id="tid-mirror",
        topic_id=3794,
        preview="继续会话",
        archived=False,
        streaming_msg_id=5004,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-mirror",
        turn_id="turn-mirror",
    )
    state.streaming_turns["tid-mirror"] = StreamingTurn(
        message_id=5004,
        topic_id=3794,
        turn_id="turn-mirror",
        buffer="已确认日志根因，tui-mirror 的空 completed 不再发送兜底通知。",
        completed=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-mirror",
                    "turnId": "turn-mirror",
                    "turn": {"id": "turn-mirror", "status": "completed", "source": "tui-mirror"},
                },
            },
        },
    )

    assert "tid-mirror" not in state.streaming_turns
    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.status == "completed"
    assert event.task_name == "继续会话"
    assert event.message == "完成摘要：已确认日志根因，tui-mirror 的空 completed 不再发送兜底通知。"


@pytest.mark.asyncio
async def test_tui_mirror_final_item_sends_summary_and_turn_completed_dedupes(monkeypatch):
    async def fake_run_ai_scenario(scenario_id, variables):
        return SimpleNamespace(ok=False, data={})

    monkeypatch.setattr("bot.events.run_ai_scenario", fake_run_ai_scenario)
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-real-mirror"] = ThreadInfo(
        thread_id="tid-real-mirror",
        topic_id=3794,
        preview="走完整打包流程",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=5010))
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/started",
                "params": {
                    "threadId": "tid-real-mirror",
                    "turn": {"source": "tui-mirror"},
                },
            },
        },
    )
    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-real-mirror",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-real-mirror",
                        "phase": "final_answer",
                        "text": "已跑完整打包流程，确认 DMG 安装态可以启动并通过 smoke。",
                    },
                },
            },
        },
    )
    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-real-mirror",
                    "turn": {"status": "completed", "source": "tui-mirror"},
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.status == "completed"
    assert event.task_name == "走完整打包流程"
    assert event.message == "完成摘要：已跑完整打包流程，确认 DMG 安装态可以启动并通过 smoke。"


@pytest.mark.asyncio
async def test_tui_mirror_commentary_idle_completed_does_not_send_fallback_notification():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-commentary-mirror"] = ThreadInfo(
        thread_id="tid-commentary-mirror",
        topic_id=3794,
        preview="继续会话",
        archived=False,
        streaming_msg_id=5011,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    state.streaming_turns["tid-commentary-mirror"] = StreamingTurn(
        message_id=5011,
        topic_id=3794,
        buffer="💭 已收到，处理中。",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-commentary-mirror",
                    "turn": {"status": "completed", "source": "tui-mirror"},
                },
            },
        },
    )

    assert "tid-commentary-mirror" not in state.streaming_turns
    assert notifications.events == []


@pytest.mark.asyncio
async def test_tui_mirror_empty_completed_does_not_send_fallback_notification():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-empty-mirror"] = ThreadInfo(
        thread_id="tid-empty-mirror",
        topic_id=3794,
        preview="继续会话",
        archived=False,
        streaming_msg_id=5005,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-empty-mirror",
        turn_id="turn-empty-mirror",
    )
    state.streaming_turns["tid-empty-mirror"] = StreamingTurn(
        message_id=5005,
        topic_id=3794,
        turn_id="turn-empty-mirror",
        buffer="⏳ 思考中...",
        completed=True,
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-empty-mirror",
                    "turnId": "turn-empty-mirror",
                    "turn": {"id": "turn-empty-mirror", "status": "completed", "source": "tui-mirror"},
                },
            },
        },
    )

    assert "tid-empty-mirror" not in state.streaming_turns
    assert notifications.events == []


@pytest.mark.asyncio
async def test_final_answer_notification_uses_result_summary_instead_of_url_preview():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-usage"] = ThreadInfo(
        thread_id="tid-usage",
        topic_id=3794,
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-usage",
        turn_id="turn-usage",
        task_summary="https://github.com/ryoppippi/ccusage 扩展 provider 基于兼容运行时实现，用量信息参考实现",
    )
    state.streaming_turns["tid-usage"] = StreamingTurn(
        message_id=5003,
        topic_id=3794,
        turn_id="turn-usage",
        buffer="💭 分析中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-usage",
                    "turnId": "turn-usage",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-usage",
                        "phase": "final_answer",
                        "text": "已接入 Codex、Claude 和扩展 provider 的用量读取，并限制 /token_usage 只在 agent topic 使用。",
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "修复用量统计"
    assert event.task_summary == "扩展 provider 基于兼容运行时实现，用量信息参考实现"
    assert event.message == (
        "完成摘要：已接入 Codex、Claude 和扩展 provider 的用量读取，"
        "并限制 /token_usage 只在 agent topic 使用。"
    )


@pytest.mark.asyncio
async def test_final_answer_notification_prefers_result_topic_over_stale_task_prompt():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-notify"] = ThreadInfo(
        thread_id="tid-notify",
        topic_id=3794,
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-notify",
        turn_id="turn-notify",
        task_summary="扩展 provider 基于兼容运行时实现，用量信息应由 provider 插件提供",
    )
    state.streaming_turns["tid-notify"] = StreamingTurn(
        message_id=5004,
        topic_id=3794,
        turn_id="turn-notify",
        buffer="💭 分析中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-notify",
                    "turnId": "turn-notify",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-notify",
                        "phase": "final_answer",
                        "text": (
                            "已继续聚焦通知文案，并把最新代码打进安装态 /Applications/OnlineWorker.app 了。\n\n"
                            "核心变化：\n"
                            "- 通知标题优先从本轮结果提炼短标题，URL preview 不再作为标题污染通知。\n"
                            "- 完成通知会提取最终回复里的有效变更摘要，避开开场套话。\n\n"
                            "验证结果：\n"
                            "- 46 passed"
                        ),
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "优化任务通知"
    assert event.task_summary == "通知标题优先从本轮结果提炼短标题，URL preview 不再作为标题污染通知。"
    assert event.message == "完成摘要：完成通知会提取最终回复里的有效变更摘要，避开开场套话。"


@pytest.mark.asyncio
async def test_final_answer_notification_ignores_markdown_example_blocks():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-notify-example"] = ThreadInfo(
        thread_id="tid-notify-example",
        topic_id=3794,
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-notify-example",
        turn_id="turn-notify-example",
        task_summary="扩展 provider 基于兼容运行时实现，用量信息应由 provider 插件提供",
    )
    state.streaming_turns["tid-notify-example"] = StreamingTurn(
        message_id=5005,
        topic_id=3794,
        turn_id="turn-notify-example",
        buffer="💭 分析中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-notify-example",
                    "turnId": "turn-notify-example",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-notify-example",
                        "phase": "final_answer",
                        "text": (
                            "已修掉这条通知问题，并完成代码级验证。\n\n"
                            "本轮修复：\n"
                            "- 通知摘要提取器会跳过 Markdown 示例代码块。\n"
                            "- 完成摘要只使用真实变更点，不使用示例说明。\n\n"
                            "现在这条场景生成的通知示例是：\n\n"
                            "```text\n"
                            "完成 · Codex · 优化任务通知\n"
                            "通知标题优先从本轮结果提炼短标题，URL preview 不再作为标题污染通知。\n"
                            "完成摘要：完成通知会提取最终回复里的有效变更摘要，避开开场套话。\n"
                            "```\n\n"
                            "已验证：\n"
                            "```text\n"
                            "python3 -m pytest OnlineWorker/tests/test_events_streaming.py -q\n"
                            "48 passed\n"
                            "```"
                        ),
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "优化任务通知"
    assert event.task_summary == "通知摘要提取器会跳过 Markdown 示例代码块。"
    assert event.message == "完成摘要：完成摘要只使用真实变更点，不使用示例说明。"


@pytest.mark.asyncio
async def test_final_answer_notification_can_use_ai_summary_scenario(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-ai-summary"] = ThreadInfo(
        thread_id="tid-ai-summary",
        topic_id=3794,
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-ai-summary",
        turn_id="turn-ai-summary",
        task_summary="扩展 provider 基于兼容运行时实现，用量信息应由 provider 插件提供",
    )
    state.streaming_turns["tid-ai-summary"] = StreamingTurn(
        message_id=5007,
        topic_id=3794,
        turn_id="turn-ai-summary",
        buffer="💭 分析中",
    )

    async def fake_run_ai_scenario(scenario_id, variables):
        assert scenario_id == "notification_summary"
        assert variables["task_summary"] == "扩展 provider 基于兼容运行时实现，用量信息应由 provider 插件提供"
        assert variables["provider_id"] == "codex"
        return SimpleNamespace(
            ok=True,
            data={
                "preview_title": "用量读取接入",
                "summary": "完成 Codex、Claude 和扩展 provider 用量读取并限制命令作用域。",
            },
        )

    monkeypatch.setattr("bot.events.run_ai_scenario", fake_run_ai_scenario)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-ai-summary",
                    "turnId": "turn-ai-summary",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-ai-summary",
                        "phase": "final_answer",
                        "text": "已接入 provider 用量读取。",
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "用量读取接入"
    assert event.task_summary == ""
    assert event.message == "完成摘要：完成 Codex、Claude 和扩展 provider 用量读取并限制命令作用域。"


@pytest.mark.asyncio
async def test_final_answer_notification_does_not_relimit_ai_summary_for_display(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-ai-long-summary"] = ThreadInfo(
        thread_id="tid-ai-long-summary",
        topic_id=3794,
        preview="优化任务通知",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    long_summary = (
        "已定位 AI 摘要场景的正文在通知组装阶段被本地兜底规则再次截断，"
        "现在改为只清理空白和链接，完整保留 AI 场景已经生成好的摘要内容。"
    )

    async def fake_run_ai_scenario(scenario_id, variables):
        assert scenario_id == "notification_summary"
        return SimpleNamespace(
            ok=True,
            data={
                "preview_title": "优化任务通知",
                "summary": long_summary,
            },
        )

    monkeypatch.setattr("bot.events.run_ai_scenario", fake_run_ai_scenario)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-ai-long-summary",
                    "turnId": "turn-ai-long-summary",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-ai-long-summary",
                        "phase": "final_answer",
                        "text": "已修复通知摘要截断。",
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "优化任务通知"
    assert event.task_summary == ""
    assert event.message == f"完成摘要：{long_summary}"


@pytest.mark.asyncio
async def test_final_answer_notification_does_not_relimit_ai_preview_title(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-ai-title"] = ThreadInfo(
        thread_id="tid-ai-title",
        topic_id=3794,
        preview="Session 归档菜单",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)

    async def fake_run_ai_scenario(scenario_id, variables):
        assert scenario_id == "notification_summary"
        return SimpleNamespace(
            ok=True,
            data={
                "preview_title": "修复会话归档菜单与后台映射",
                "summary": "已修复 Session 卡片归档菜单和 workspace 映射。",
            },
        )

    monkeypatch.setattr("bot.events.run_ai_scenario", fake_run_ai_scenario)

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-ai-title",
                    "turnId": "turn-ai-title",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-ai-title",
                        "phase": "final_answer",
                        "text": "已修复会话归档菜单。",
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "修复会话归档菜单与后台映射"
    assert event.task_summary == ""
    assert event.message == "完成摘要：已修复 Session 卡片归档菜单和 workspace 映射。"


@pytest.mark.asyncio
async def test_final_answer_notification_uses_external_summary_rules(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "notification_summary_rules.yaml").write_text(
        """
limits:
  title: 12
  summary: 80
sections:
  result:
    - 本轮修复
  stop:
    - 验证结果
noise:
  prefixes: []
  contains: []
  suffixes: []
  regexes: []
title:
  rules:
    - pattern: "无明确许可不允许打包"
      title: "外置规则标题"
  strip_prefixes: []
  remove_patterns: []
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr("config.get_data_dir", lambda: str(data_dir))

    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3794,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-packaging-guard"] = ThreadInfo(
        thread_id="tid-packaging-guard",
        topic_id=3794,
        preview="https://github.com/ryoppippi/ccusage",
        archived=False,
    )
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    state = AppState(storage=storage)
    codex_state.start_run(
        state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-packaging-guard",
        turn_id="turn-packaging-guard",
        task_summary="扩展 provider 基于兼容运行时实现，用量信息应由 provider 插件提供",
    )
    state.streaming_turns["tid-packaging-guard"] = StreamingTurn(
        message_id=5006,
        topic_id=3794,
        turn_id="turn-packaging-guard",
        buffer="💭 分析中",
    )

    bot = SimpleNamespace()
    bot.send_message = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.edit_message_text = AsyncMock()
    notifications = RecordingNotificationRouter()

    handler = make_event_handler(state, bot, GROUP_CHAT_ID, notification_router=notifications)

    await handler(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "tid-packaging-guard",
                    "turnId": "turn-packaging-guard",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "tid-packaging-guard",
                        "phase": "final_answer",
                        "text": (
                            "本轮修复：\n"
                            "- 已把无明确许可不允许打包写入 AGENTS.md 和 OnlineWorker/AGENTS.md。\n"
                            "- 通知摘要提取器已跳过示例说明、代码块和泛化开场句。\n\n"
                            "验证结果：\n"
                            "- 相关回归测试通过。"
                        ),
                    },
                },
            },
        },
    )

    assert len(notifications.events) == 1
    event = notifications.events[0]
    assert event.task_name == "外置规则标题"
    assert event.task_summary == "已把无明确许可不允许打包写入 AGENTS.md 和 OnlineWorker/AGENTS.md。"
    assert event.message == "完成摘要：通知摘要提取器已跳过示例说明、代码块和泛化开场句。"


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
