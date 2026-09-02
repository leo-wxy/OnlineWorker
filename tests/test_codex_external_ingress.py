import asyncio
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.events import make_event_handler
from core.state import AppState, StreamingTurn
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
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
async def test_large_rollout_history_does_not_consume_one_fd_per_file(
    tmp_path: Path,
):
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "10"
    day_dir.mkdir(parents=True)
    for index in range(80):
        session_id = f"00000000-0000-4000-8000-{index:012d}"
        _append_jsonl(
            day_dir / f"rollout-2026-08-10T10-00-00-{session_id}.jsonl",
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/Users/example/Projects/history-workspace",
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
    before = len(os.listdir("/dev/fd"))

    await ingress.start()
    try:
        after = len(os.listdir("/dev/fd"))
        assert len(ingress._rollouts) == 80
        assert after - before < 16
    finally:
        await ingress.close()


@pytest.mark.asyncio
async def test_start_restores_only_bound_unfinished_rollout_watch(tmp_path: Path):
    active_session_id = "11111111-2222-4333-8444-555555555557"
    completed_session_id = "11111111-2222-4333-8444-555555555558"
    turn_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee10"
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "24"
    day_dir.mkdir(parents=True)
    active_rollout = day_dir / f"rollout-2026-08-24T17-00-00-{active_session_id}.jsonl"
    completed_rollout = day_dir / f"rollout-2026-08-24T16-00-00-{completed_session_id}.jsonl"
    for path, session_id, completed in (
        (active_rollout, active_session_id, False),
        (completed_rollout, completed_session_id, True),
    ):
        rows = [
            {
                "type": "session_meta",
                "payload": {
                    "id": session_id,
                    "cwd": "/Users/example/Projects/live-workspace",
                },
            },
        ]
        if not completed:
            rows.extend(
                [
                    {"type": "event_msg", "payload": {"blob": "x" * 300_000}},
                    {"type": "turn_context", "payload": {"turn_id": turn_id}},
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": turn_id},
                    },
                    {"type": "event_msg", "payload": {"blob": "y" * 300_000}},
                    {
                        "type": "response_item",
                        "payload": {
                            "role": "assistant",
                            "phase": "commentary",
                            "content": [{"type": "output_text", "text": "仍在执行"}],
                            "internal_chat_message_metadata_passthrough": {
                                "turn_id": turn_id
                            },
                        },
                    },
                ]
            )
        else:
            rows.extend(
                [
                    {"type": "turn_context", "payload": {"turn_id": turn_id}},
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_started", "turn_id": turn_id},
                    },
                    {
                        "type": "event_msg",
                        "payload": {"type": "task_complete", "turn_id": turn_id},
                    },
                ]
            )
        _append_jsonl(path, *rows)

    workspace = WorkspaceInfo(
        name="live-workspace",
        path="/Users/example/Projects/live-workspace",
        tool="codex",
        daemon_workspace_id="codex:live-workspace",
    )
    workspace.threads[active_session_id] = ThreadInfo(
        thread_id=active_session_id,
        topic_id=14623,
        source="unknown",
    )
    workspace.threads[completed_session_id] = ThreadInfo(
        thread_id=completed_session_id,
        topic_id=14624,
        source="unknown",
    )
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(
            return_value={"accepted": True, "emitted": 1}
        ),
        has_authoritative_live_session=MagicMock(return_value=False),
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=AppState(
            storage=AppStorage(workspaces={"codex:live-workspace": workspace})
        ),
        sessions_dir=str(sessions_dir),
    )

    await ingress.start()
    try:
        assert set(ingress._active_watches) == {active_session_id}
        adapter.ingest_external_hook_payload.reset_mock()

        for index in range(2):
            _append_jsonl(
                active_rollout,
                {
                    "type": "response_item",
                    "payload": {
                        "role": "assistant",
                        "phase": "commentary",
                        "content": [
                            {
                                "type": "output_text",
                                "text": f"恢复后的过程消息 {index + 1}",
                            }
                        ],
                        "internal_chat_message_metadata_passthrough": {
                            "turn_id": turn_id
                        },
                    },
                },
            )
            await _wait_until(
                lambda: adapter.ingest_external_hook_payload.await_count == index + 1,
                timeout=1.0,
            )

        assert [
            call.args[0]["message"]
            for call in adapter.ingest_external_hook_payload.await_args_list
        ] == ["恢复后的过程消息 1", "恢复后的过程消息 2"]
    finally:
        await ingress.close()


@pytest.mark.asyncio
async def test_primary_hook_arms_one_active_kqueue_watch_for_commentary(tmp_path: Path):
    session_id = "11111111-2222-4333-8444-555555555557"
    turn_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee10"
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "08" / "24"
    day_dir.mkdir(parents=True)
    rollout = day_dir / f"rollout-2026-08-24T17-00-00-{session_id}.jsonl"
    _append_jsonl(
        rollout,
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/Users/example/Projects/live-workspace",
            },
        },
        {"type": "turn_context", "payload": {"turn_id": turn_id}},
    )
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(
            return_value={"accepted": True, "emitted": 1}
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
        ingress.record_primary_event(session_id, turn_id, "started")
        assert set(ingress._active_watches) == {session_id}

        _append_jsonl(
            rollout,
            {
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "phase": "commentary",
                    "content": [{"type": "output_text", "text": "事件驱动已恢复"}],
                    "internal_chat_message_metadata_passthrough": {
                        "turn_id": turn_id
                    },
                },
            },
        )
        await _wait_until(
            lambda: adapter.ingest_external_hook_payload.await_count == 1,
            timeout=1.0,
        )

        adapter.ingest_external_hook_payload.assert_awaited_once_with(
            {
                "hook_event_name": "AgentMessage",
                "session_id": session_id,
                "turn_id": turn_id,
                "cwd": "/Users/example/Projects/live-workspace",
                "message": "事件驱动已恢复",
                "phase": "commentary",
                "source": "codex_rollout",
            }
        )
        ingress.record_primary_event(session_id, turn_id, "completed")
        assert session_id not in ingress._active_watches
    finally:
        await ingress.close()


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
async def test_desktop_rollout_commentary_edits_existing_telegram_placeholder(
    tmp_path: Path,
):
    session_id = "11111111-2222-4333-8444-555555555556"
    turn_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeef"
    workspace_path = "/Users/example/Projects/desktop-workspace"
    topic_id = 14623
    rollout_path = str(
        tmp_path / f"rollout-2026-08-24T16-00-00-{session_id}.jsonl"
    )
    workspace = WorkspaceInfo(
        name="desktop-workspace",
        path=workspace_path,
        tool="codex",
        topic_id=topic_id,
        daemon_workspace_id="codex:desktop-workspace",
    )
    workspace.threads[session_id] = ThreadInfo(
        thread_id=session_id,
        topic_id=topic_id,
        streaming_msg_id=14724,
        source="unknown",
    )
    state = AppState(
        storage=AppStorage(workspaces={"codex:desktop-workspace": workspace})
    )
    state.streaming_turns[session_id] = StreamingTurn(
        message_id=14724,
        topic_id=topic_id,
        turn_id=turn_id,
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(),
        delete_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    adapter = CodexAdapter()
    adapter.register_workspace_cwd("codex:desktop-workspace", workspace_path)
    adapter.on_event(make_event_handler(state, bot, GROUP_CHAT_ID))
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=state,
        sessions_dir=str(tmp_path),
        fallback_grace_seconds=0,
    )
    ingress._loop = asyncio.get_running_loop()
    ingress._closed = False

    try:
        await adapter.ingest_external_hook_payload(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "turn_id": turn_id,
                "cwd": workspace_path,
                "prompt": "验证 Desktop 过程消息",
            }
        )
        for row in (
            {
                "type": "session_meta",
                "payload": {"id": session_id, "cwd": workspace_path},
            },
            {
                "type": "turn_context",
                "payload": {"turn_id": "00000000-1111-4222-8333-444444444444"},
            },
            {
                "type": "event_msg",
                "payload": {
                    "type": "agent_message",
                    "phase": "commentary",
                    "message": "正在核对真实事件链。",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "role": "assistant",
                    "phase": "commentary",
                    "content": [
                        {"type": "output_text", "text": "正在核对真实事件链。"}
                    ],
                    "internal_chat_message_metadata_passthrough": {
                        "turn_id": turn_id
                    },
                },
            },
        ):
            await ingress._process_rollout_line(
                rollout_path,
                json.dumps(row, ensure_ascii=False).encode("utf-8"),
            )
        await _wait_until(lambda: bot.edit_message_text.await_count == 1)
        await asyncio.sleep(0.05)
    finally:
        await ingress.close()

    assert bot.edit_message_text.await_count == 1
    assert "正在核对真实事件链" in bot.edit_message_text.await_args.kwargs["text"]
    assert "思考中" not in bot.edit_message_text.await_args.kwargs["text"]
    assert state.streaming_turns[session_id].turn_id == turn_id


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


@pytest.mark.asyncio
async def test_desktop_rollout_subagent_never_enters_provider_event_path(tmp_path: Path):
    parent_session_id = "11111111-2222-4333-8444-555555555555"
    child_session_id = "22222222-3333-4444-8555-666666666666"
    turn_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    rollout_path = str(
        tmp_path / f"rollout-2026-08-07T10-00-00-{child_session_id}.jsonl"
    )
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(
            return_value={"accepted": True, "emitted": 4}
        ),
        has_authoritative_live_session=MagicMock(return_value=False),
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=AppState(storage=AppStorage()),
        sessions_dir=str(tmp_path),
    )

    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": child_session_id,
                "cwd": "/Users/example/Projects/desktop-workspace",
                "source": {
                    "subagent": {
                        "thread_spawn": {
                            "parent_thread_id": parent_session_id,
                            "depth": 1,
                            "agent_path": "/root/example-child",
                            "agent_nickname": "Example",
                            "agent_role": "default",
                        }
                    }
                },
                "thread_source": "subagent",
            },
        },
        {
            "type": "turn_context",
            "payload": {"turn_id": turn_id},
        },
        {
            "type": "response_item",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": "内部子任务"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": "内部子任务已完成。",
            },
        },
    ]

    for row in rows:
        await ingress._process_rollout_line(
            rollout_path,
            json.dumps(row, ensure_ascii=False).encode("utf-8"),
        )

    adapter.ingest_external_hook_payload.assert_not_awaited()


def test_rollout_ingress_defers_live_source_arbitration_to_adapter(tmp_path: Path):
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
    assert ingress._should_publish_session(session_id) is True

    adapter.has_authoritative_live_session.return_value = False
    workspace.threads[session_id] = ThreadInfo(
        thread_id=session_id,
        source="unknown",
    )
    state.get_provider_runtime("codex").watched_threads[session_id] = SimpleNamespace()
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


@pytest.mark.asyncio
async def test_rollout_fallback_is_cancelled_when_primary_event_claims_turn(tmp_path: Path):
    session_id = "55555555-6666-4777-8888-999999999999"
    turn_id = "dddddddd-eeee-4fff-8000-111111111111"
    rollout_path = str(
        tmp_path / f"rollout-2026-08-11T10-00-00-{session_id}.jsonl"
    )
    adapter = SimpleNamespace(
        ingest_external_hook_payload=AsyncMock(
            return_value={"accepted": True, "emitted": 5}
        ),
        has_authoritative_live_session=MagicMock(return_value=False),
    )
    ingress = CodexDesktopRolloutIngress(
        adapter=adapter,
        state=AppState(storage=AppStorage()),
        sessions_dir=str(tmp_path),
        fallback_grace_seconds=0.05,
    )
    ingress._loop = asyncio.get_running_loop()
    ingress._closed = False

    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/Users/example/Projects/desktop-workspace",
            },
        },
        {"type": "turn_context", "payload": {"turn_id": turn_id}},
        {
            "type": "response_item",
            "payload": {
                "role": "user",
                "content": [{"type": "input_text", "text": "验证 Hook 主链"}],
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": turn_id,
                "last_agent_message": "Hook 主链验证完成。",
            },
        },
    ]

    try:
        for row in rows:
            await ingress._process_rollout_line(
                rollout_path,
                json.dumps(row, ensure_ascii=False).encode("utf-8"),
            )
        adapter.ingest_external_hook_payload.assert_not_awaited()

        ingress.record_primary_event(session_id, turn_id, "started")
        ingress.record_primary_event(session_id, turn_id, "completed")
        await asyncio.sleep(0.08)
    finally:
        await ingress.close()

    adapter.ingest_external_hook_payload.assert_not_awaited()
