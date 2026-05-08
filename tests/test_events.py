# tests/test_events.py
"""
测试 bot/events.py 中的纯逻辑函数：
- _is_network_error：网络错误判断
- _resolve_topic_id：topic_id 解析逻辑
- _extract_thread_id：thread_id 提取逻辑
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from config import Config, ToolConfig
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo
from bot.events import (
    _extract_thread_id,
    _is_network_error,
    _resolve_topic_id,
    make_event_handler,
    make_server_request_handler,
)
from bot.handlers.common import (
    tg_approval_request_text,
    tg_empty_turn_completed_text,
    tg_processing_ack_text,
    tg_send_failed_text,
)


# ── _is_network_error ─────────────────────────────────────────────────────────

class TestIsNetworkError:
    def test_connection_error_is_network(self):
        assert _is_network_error(ConnectionError("refused")) is True

    def test_timeout_error_is_network(self):
        assert _is_network_error(TimeoutError("timed out")) is True

    def test_os_error_is_network(self):
        assert _is_network_error(OSError("errno 111")) is True

    def test_generic_runtime_error_not_network(self):
        assert _is_network_error(RuntimeError("something went wrong")) is False

    def test_value_error_not_network(self):
        assert _is_network_error(ValueError("bad value")) is False

    def test_string_connecterror_is_network(self):
        assert _is_network_error(Exception("ConnectError: connection refused")) is True

    def test_string_timeout_is_network(self):
        assert _is_network_error(Exception("request timeout")) is True

    def test_string_eof_is_network(self):
        assert _is_network_error(Exception("unexpected eof")) is True

    def test_string_reset_is_network(self):
        assert _is_network_error(Exception("connection reset by peer")) is True

    def test_string_broken_is_network(self):
        assert _is_network_error(Exception("broken pipe")) is True


class TestTelegramMessageContract:
    def test_processing_ack_text(self):
        assert tg_processing_ack_text() == "✅ 已收到，处理中。完成后会把最终回复同步到这里。"

    def test_send_failed_text(self):
        assert tg_send_failed_text("boom") == "❌ 发送失败：boom"

    def test_empty_turn_completed_text(self):
        assert tg_empty_turn_completed_text() == "✅ 已完成"

    def test_approval_request_text_for_customprovider_contains_remote_hint(self):
        text = tg_approval_request_text(
            command="mkdir /tmp/demo",
            reason="need *permission*",
            tool_type="customprovider",
        )
        assert "沙盒权限请求" in text
        assert "mkdir /tmp/demo" in text
        assert "need \\*permission\\*" in text
        assert "可直接在 TG 中处理授权" not in text

    def test_approval_request_text_for_codex_omits_customprovider_hint(self):
        text = tg_approval_request_text(
            command="mkdir /tmp/demo",
            reason="need permission",
            tool_type="codex",
        )
        assert "沙盒权限请求" in text
        assert "可直接在 TG 中处理授权" not in text


# ── _extract_thread_id ────────────────────────────────────────────────────────

class TestExtractThreadId:
    def test_threadId_key(self):
        assert _extract_thread_id({"threadId": "tid-001"}) == "tid-001"

    def test_thread_id_key(self):
        assert _extract_thread_id({"thread_id": "tid-002"}) == "tid-002"

    def test_thread_object(self):
        assert _extract_thread_id({"thread": {"id": "tid-003"}}) == "tid-003"

    def test_item_threadId(self):
        assert _extract_thread_id({"item": {"threadId": "tid-004"}}) == "tid-004"

    def test_empty_dict_returns_none(self):
        assert _extract_thread_id({}) is None

    def test_threadId_takes_priority(self):
        # threadId > thread_id
        result = _extract_thread_id({"threadId": "first", "thread_id": "second"})
        assert result == "first"


# ── _resolve_topic_id ─────────────────────────────────────────────────────────

def make_state_with_workspace(
    ws_name: str = "proj",
    ws_topic_id: int = 100,
    daemon_ws_id: str = "daemon-001",
    threads: dict | None = None,
    active: bool = True,
) -> tuple[AppState, WorkspaceInfo]:
    """构建带有一个 workspace 的 AppState。"""
    ws = WorkspaceInfo(
        name=ws_name,
        path=f"/{ws_name}",
        topic_id=ws_topic_id,
        daemon_workspace_id=daemon_ws_id,
    )
    if threads:
        ws.threads.update(threads)
    storage = AppStorage(
        workspaces={ws_name: ws},
        active_workspace=ws_name if active else "",
    )
    return AppState(storage=storage), ws


class TestResolveTopicId:
    def test_thread_topic_returned_when_exists(self):
        thread = ThreadInfo(thread_id="tid-001", topic_id=999, archived=False)
        state, ws = make_state_with_workspace(threads={"tid-001": thread})
        result = _resolve_topic_id(state, "daemon-001", "tid-001", {})
        assert result == 999

    def test_archived_thread_falls_back_to_workspace_topic(self):
        thread = ThreadInfo(thread_id="tid-001", topic_id=999, archived=True)
        state, ws = make_state_with_workspace(threads={"tid-001": thread})
        result = _resolve_topic_id(state, "daemon-001", "tid-001", {})
        assert result == 100  # ws.topic_id

    def test_archived_active_thread_still_routes_to_thread_topic(self, monkeypatch):
        thread = ThreadInfo(thread_id="tid-001", topic_id=999, archived=True, is_active=False)
        state, ws = make_state_with_workspace(threads={"tid-001": thread})
        monkeypatch.setattr(
            "bot.handlers.common.query_provider_active_thread_ids",
            lambda tool_name, workspace_path: {"tid-001"},
        )

        result = _resolve_topic_id(state, "daemon-001", "tid-001", {})

        assert result == 999
        assert state.storage.workspaces["proj"].threads["tid-001"].archived is False
        assert state.storage.workspaces["proj"].threads["tid-001"].is_active is True

    def test_no_thread_returns_workspace_topic(self):
        state, ws = make_state_with_workspace()
        result = _resolve_topic_id(state, "daemon-001", None, {})
        assert result == 100

    def test_unknown_workspace_returns_none(self):
        """未知 workspace 时不再 fallback，返回 None"""
        state, ws = make_state_with_workspace()
        # daemon_ws_id 不匹配任何 workspace
        result = _resolve_topic_id(state, "unknown-daemon-id", None, {})
        # 不再 fallback 到 active workspace，应返回 None
        assert result is None

    def test_no_storage_returns_none(self):
        state = AppState(storage=None)
        result = _resolve_topic_id(state, "daemon-001", "tid-001", {})
        assert result is None

    def test_nonexistent_thread_falls_back_to_workspace_topic(self):
        state, ws = make_state_with_workspace()
        result = _resolve_topic_id(state, "daemon-001", "nonexistent-thread", {})
        assert result == 100

    def test_thread_without_topic_does_not_fall_back_to_workspace_topic(self):
        thread = ThreadInfo(thread_id="tid-001", topic_id=None, archived=False)
        state, ws = make_state_with_workspace(threads={"tid-001": thread})
        result = _resolve_topic_id(state, "daemon-001", "tid-001", {})
        assert result is None


def make_state_with_owner(
    threads: dict | None = None,
    ws_topic_id: int = 100,
) -> AppState:
    state, _ = make_state_with_workspace(threads=threads, ws_topic_id=ws_topic_id)
    state.config = Config(
        telegram_token="token",
        allowed_user_id=12345,
        group_chat_id=-100123456789,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="ws",
                app_server_port=4722,
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    return state


@pytest.mark.asyncio
async def test_server_request_approval_unknown_thread_notifies_owner_dm():
    state = make_state_with_owner()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()

    handler = make_server_request_handler(state, bot, -100123456789)
    await handler(
        "item/commandExecution/requestApproval",
        {
            "threadId": "missing-thread",
            "command": "ls",
            "reason": "need permission",
        },
        42,
    )

    bot.send_message.assert_called_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 12345
    assert "missing-thread" in call_kwargs["text"]
    assert "无法路由" in call_kwargs["text"]
    bot.edit_message_reply_markup.assert_not_called()


@pytest.mark.asyncio
async def test_server_request_approval_revives_stale_archived_thread_when_source_active(monkeypatch):
    state = make_state_with_owner(
        threads={"tid-001": ThreadInfo(thread_id="tid-001", topic_id=999, archived=True, is_active=False)}
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()

    approval_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.events.send_approval_to_telegram",
        approval_mock,
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-001"},
    )

    handler = make_server_request_handler(state, bot, -100123456789)
    await handler(
        "item/commandExecution/requestApproval",
        {
            "threadId": "tid-001",
            "command": "ls",
            "reason": "need permission",
        },
        42,
    )

    approval_mock.assert_awaited_once()
    bot.send_message.assert_not_called()
    thread = state.storage.workspaces["proj"].threads["tid-001"]
    assert thread.archived is False
    assert thread.is_active is True


@pytest.mark.asyncio
async def test_event_approval_missing_topic_notifies_owner_dm():
    state = make_state_with_owner(
        threads={"tid-001": ThreadInfo(thread_id="tid-001", topic_id=None, archived=False)}
    )
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()

    handler = make_event_handler(state, bot, -100123456789)
    await handler(
        "app-server-event",
        {
            "workspace_id": "daemon-001",
            "message": {
                "method": "item/commandExecution/requestApproval",
                "id": "req-001",
                "params": {
                    "threadId": "tid-001",
                    "command": "mkdir /tmp/demo",
                    "reason": "need elevated write",
                },
            },
        },
    )

    bot.send_message.assert_called_once()
    call_kwargs = bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == 12345
    assert "tid-001" in call_kwargs["text"]
    assert "无法路由" in call_kwargs["text"]
    bot.edit_message_reply_markup.assert_not_called()


@pytest.mark.asyncio
async def test_event_approval_uses_provider_from_payload_for_claude(monkeypatch):
    state = make_state_with_owner(
        threads={"tid-001": ThreadInfo(thread_id="tid-001", topic_id=999, archived=False)}
    )
    state.storage.workspaces["proj"].tool = "claude"

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()

    approval_mock = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", approval_mock)

    handler = make_event_handler(state, bot, -100123456789)
    await handler(
        "app-server-event",
        {
            "workspace_id": "daemon-001",
            "message": {
                "method": "item/commandExecution/requestApproval",
                "id": "req-claude-1",
                "params": {
                    "threadId": "tid-001",
                    "command": "pwd",
                    "reason": "检查目录",
                    "_provider": "claude",
                },
            },
        },
    )

    approval_mock.assert_awaited_once()
    approval_info = approval_mock.await_args.args[5]
    assert approval_info.tool_type == "claude"
    assert approval_info.request_id == "req-claude-1"


@pytest.mark.asyncio
async def test_event_approval_records_codex_interruption_on_current_run(monkeypatch):
    state = make_state_with_owner(
        threads={"tid-001": ThreadInfo(thread_id="tid-001", topic_id=999, archived=False)}
    )
    codex_state.start_run(state,
        workspace_id="daemon-001",
        thread_id="tid-001",
        turn_id="turn-001",
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()

    approval_mock = AsyncMock()
    monkeypatch.setattr("bot.events.send_approval_to_telegram", approval_mock)

    handler = make_event_handler(state, bot, -100123456789)
    await handler(
        "app-server-event",
        {
            "workspace_id": "daemon-001",
            "message": {
                "method": "item/commandExecution/requestApproval",
                "id": "req-001",
                "params": {
                    "threadId": "tid-001",
                    "command": "mkdir /tmp/demo",
                    "reason": "need elevated write",
                },
            },
        },
    )

    approval_mock.assert_awaited_once()
    run = codex_state.get_current_run(state, "tid-001")
    assert run is not None
    assert "req-001" in run.active_interruption_ids
    assert codex_state.get_runtime(state).interruptions["req-001"].run_id == "turn-001"
