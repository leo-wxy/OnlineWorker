import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.events import make_event_handler
from core.state import AppState
from core.storage import AppStorage, WorkspaceInfo
from plugins.providers.builtin.codex.python.adapter import CodexAdapter
from plugins.providers.builtin.codex.python.external_ingress import (
    CodexDesktopRolloutIngress,
)


GROUP_CHAT_ID = -100123456789
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="requires macOS kqueue")


class RecordingNotificationRouter:
    def __init__(self) -> None:
        self.events = []

    async def notify(self, event):
        self.events.append(event)
        return SimpleNamespace(sent=True, channels=("recording",), reason="")


def _append_jsonl(path: Path, *rows: dict) -> None:
    with path.open("a", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
        output.flush()


async def _wait_until(predicate, *, timeout: float = 4.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("等待 Codex Desktop rollout 事件超时")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_desktop_rollout_completion_enters_bus_without_topic(tmp_path: Path):
    session_id = "11111111-2222-4333-8444-555555555555"
    turn_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    workspace_path = "/Users/example/Projects/desktop-workspace"
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "03"
    day_dir.mkdir(parents=True)
    rollout = day_dir / f"rollout-2026-08-03T10-00-00-{session_id}.jsonl"
    _append_jsonl(
        rollout,
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": workspace_path,
            },
        },
    )

    workspace = WorkspaceInfo(
        name="desktop-workspace",
        path=workspace_path,
        tool="codex",
        topic_id=None,
        daemon_workspace_id="codex:desktop-workspace",
    )
    state = AppState(
        storage=AppStorage(workspaces={"codex:desktop-workspace": workspace})
    )
    state.message_bus.notification_summary.build_completed_notification = AsyncMock(
        return_value=SimpleNamespace(
            task_name_override="Desktop 摘要完成",
            task_summary_override="Desktop 完成事件已经进入通用事件总线。",
            message="完成摘要：Desktop 完成事件已经进入通用事件总线。",
        )
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        delete_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    notifications = RecordingNotificationRouter()
    adapter = CodexAdapter()
    adapter.register_workspace_cwd("codex:desktop-workspace", workspace_path)
    adapter.on_event(
        make_event_handler(
            state,
            bot,
            GROUP_CHAT_ID,
            notification_router=notifications,
        )
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=state,
        sessions_dir=str(sessions_dir),
    )

    await ingress.start()
    try:
        _append_jsonl(
            rollout,
            {
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": turn_id},
            },
            {
                "type": "turn_context",
                "payload": {"turn_id": turn_id},
            },
            {
                "type": "response_item",
                "payload": {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "验证 Desktop 通知摘要"}
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {"type": "output_text", "text": "Desktop 任务已经完成。"}
                    ],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": "Desktop 任务已经完成。",
                },
            },
        )

        await _wait_until(lambda: len(notifications.events) == 1)
    finally:
        await ingress.close()

    events = state.message_bus.recent_events()
    kinds = [event["kind"] for event in events]
    assert kinds == [
        "session.created",
        "message.user.submitted",
        "turn.started",
        "message.assistant.final",
        "notification.requested",
        "notification.emitted",
        "turn.completed",
    ]
    final_event = next(event for event in events if event["kind"] == "message.assistant.final")
    assert final_event["session_id"] == session_id
    assert final_event["turn_id"] == turn_id
    assert final_event["payload"]["text"] == "Desktop 任务已经完成。"
    state.message_bus.notification_summary.build_completed_notification.assert_awaited_once()
    assert notifications.events[0].task_id == turn_id
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_desktop_rollout_file_is_discovered_without_session_polling(tmp_path: Path):
    session_id = "22222222-3333-4444-8555-666666666666"
    turn_id = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "03"
    day_dir.mkdir(parents=True)
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(
            return_value={"accepted": True, "emitted": 4}
        ),
        has_authoritative_live_session=MagicMock(return_value=False),
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=AppState(storage=AppStorage()),
        sessions_dir=str(sessions_dir),
    )

    await ingress.start()
    try:
        rollout = day_dir / f"rollout-2026-08-03T10-01-00-{session_id}.jsonl"
        _append_jsonl(
            rollout,
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/Users/example/Projects/new-desktop-workspace",
                },
            },
            {
                "type": "turn_context",
                "payload": {"turn_id": turn_id},
            },
            {
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "phase": "final_answer",
                    "content": [
                        {"type": "output_text", "text": "新 Desktop Session 已完成。"}
                    ],
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "task_complete",
                    "turn_id": turn_id,
                    "last_agent_message": "新 Desktop Session 已完成。",
                },
            },
        )

        await _wait_until(
            lambda: adapter.ingest_external_hook_payload.await_count == 1,
            timeout=2.0,
        )
    finally:
        await ingress.close()

    adapter.ingest_external_hook_payload.assert_awaited_once_with(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": session_id,
            "turn_id": turn_id,
            "cwd": "/Users/example/Projects/new-desktop-workspace",
            "last_assistant_message": "新 Desktop Session 已完成。",
            "source": "codex_rollout",
        }
    )


def test_rollout_ingress_skips_onlineworker_owned_and_live_sessions(tmp_path: Path):
    session_id = "33333333-4444-4555-8666-777777777777"
    workspace = WorkspaceInfo(
        name="owned-workspace",
        path="/Users/example/Projects/owned-workspace",
        tool="codex",
        daemon_workspace_id="codex:owned-workspace",
    )
    from core.storage import ThreadInfo

    workspace.threads[session_id] = ThreadInfo(
        thread_id=session_id,
        source="app",
    )
    state = AppState(
        storage=AppStorage(workspaces={"codex:owned-workspace": workspace})
    )
    adapter = SimpleNamespace(
        has_authoritative_live_session=MagicMock(return_value=False)
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=state,
        sessions_dir=str(tmp_path),
    )

    assert ingress._should_publish_session(session_id) is False

    workspace.threads.clear()
    adapter.has_authoritative_live_session.return_value = True
    assert ingress._should_publish_session(session_id) is False


@pytest.mark.asyncio
async def test_existing_completed_rollout_is_not_replayed_on_start(tmp_path: Path):
    session_id = "44444444-5555-4666-8777-888888888888"
    turn_id = "cccccccc-dddd-4eee-8fff-000000000000"
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "03"
    day_dir.mkdir(parents=True)
    rollout = day_dir / f"rollout-2026-08-03T09-00-00-{session_id}.jsonl"
    _append_jsonl(
        rollout,
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/Users/example/Projects/history-workspace",
            },
        },
        {
            "type": "turn_context",
            "payload": {"turn_id": turn_id},
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": "这是一条历史完成消息。",
            },
        },
    )
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(),
        has_authoritative_live_session=MagicMock(return_value=False),
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=AppState(storage=AppStorage()),
        sessions_dir=str(sessions_dir),
    )

    await ingress.start()
    try:
        await asyncio.sleep(0.05)
    finally:
        await ingress.close()

    adapter.ingest_external_hook_payload.assert_not_awaited()
