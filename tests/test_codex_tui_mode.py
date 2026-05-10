import pytest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

from config import Config, ToolConfig
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.state import StreamingTurn
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from tests.helpers.codex_runtime import make_codex_workspace_state

GROUP_CHAT_ID = -100123456789


@pytest.mark.asyncio
async def test_message_handler_uses_tui_bridge_without_persistent_codex_adapter():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="ws",
                app_server_port=4722,
                control_mode="tui",
            )
        ],
        delete_archived_topics=True,
    )
    state = AppState(storage=storage, config=cfg)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    enqueue_mock.assert_awaited_once()
    kwargs = ctx.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == GROUP_CHAT_ID
    assert kwargs["message_thread_id"] == 100
    assert "处理中" in kwargs["text"]
    assert ws.threads["tid-1"].preview == "你好"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_uses_connected_codex_adapter():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    enqueue_mock.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")
    assert ws.threads["tid-1"].preview == "你好"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_send_default_message_marks_codex_send_started():
    from plugins.providers.builtin.codex.python.runtime import send_message

    state, ws, thread = make_codex_workspace_state()

    adapter = MagicMock()
    adapter.send_user_message = AsyncMock(return_value={})

    await send_message(
        state,
        adapter,
        ws,
        thread,
        update=MagicMock(),
        context=MagicMock(),
        group_chat_id=GROUP_CHAT_ID,
        src_topic_id=100,
        text="你好",
        has_photo=False,
    )

    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-1"] > 0


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_falls_back_when_codex_thread_not_materialized():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(
        side_effect=RuntimeError(
            "thread tid-1 is not materialized yet; includeTurns is unavailable before first user message"
        )
    )
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    enqueue_mock.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")
    assert ws.threads["tid-1"].preview == "你好"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_waits_for_reconnected_codex_adapter():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)

    disconnected_adapter = MagicMock()
    disconnected_adapter.connected = False
    disconnected_adapter.resume_thread = AsyncMock(return_value={})
    disconnected_adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", disconnected_adapter)

    reconnected_adapter = MagicMock()
    reconnected_adapter.connected = True
    reconnected_adapter.resume_thread = AsyncMock(return_value={})
    reconnected_adapter.send_user_message = AsyncMock(return_value={})

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    async def _swap_adapter() -> None:
        await asyncio.sleep(0.02)
        state.set_adapter("codex", reconnected_adapter)

    reconnect_task = asyncio.create_task(_swap_adapter())

    with patch(
        "plugins.providers.builtin.codex.python.runtime.CODEX_RECONNECT_GRACE_SECONDS",
        0.2,
        create=True,
    ), patch(
        "plugins.providers.builtin.codex.python.runtime.CODEX_RECONNECT_POLL_SECONDS",
        0.01,
        create=True,
    ), patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    await reconnect_task

    enqueue_mock.assert_not_awaited()
    disconnected_adapter.resume_thread.assert_not_awaited()
    disconnected_adapter.send_user_message.assert_not_awaited()
    reconnected_adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    reconnected_adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")
    ctx.bot.send_message.assert_not_awaited()
    assert ws.threads["tid-1"].preview == "你好"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_reports_unconnected_after_reconnect_grace_window():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)

    disconnected_adapter = MagicMock()
    disconnected_adapter.connected = False
    disconnected_adapter.resume_thread = AsyncMock(return_value={})
    disconnected_adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", disconnected_adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.runtime.CODEX_RECONNECT_GRACE_SECONDS",
        0.02,
        create=True,
    ), patch(
        "plugins.providers.builtin.codex.python.runtime.CODEX_RECONNECT_POLL_SECONDS",
        0.005,
        create=True,
    ), patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    enqueue_mock.assert_not_awaited()
    disconnected_adapter.resume_thread.assert_not_awaited()
    disconnected_adapter.send_user_message.assert_not_awaited()
    save_storage_mock.assert_not_called()
    kwargs = ctx.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == GROUP_CHAT_ID
    assert kwargs["message_thread_id"] == 100
    assert kwargs["text"] == "❌ 发送失败：codex 未连接"


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_interrupts_active_turn_before_send():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(
        return_value={
            "busy": True,
            "signals": ["assistant_tool_use"],
            "message": "当前 Claude thread 正忙，请先在本地收尾。",
        }
    )
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("codex", adapter)
    state.streaming_turns["tid-1"] = StreamingTurn(
        message_id=5001,
        topic_id=100,
        turn_id="turn-1",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ), patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    assert adapter.mock_calls[:3] == [
        call.resume_thread("codex:onlineWorker", "tid-1"),
        call.turn_interrupt("codex:onlineWorker", "tid-1", "turn-1"),
        call.send_user_message("codex:onlineWorker", "tid-1", "你好"),
    ]
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_in_app_ws_mode_continues_when_interrupt_fails():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(side_effect=RuntimeError("interrupt boom"))
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("codex", adapter)
    state.streaming_turns["tid-1"] = StreamingTurn(
        message_id=5001,
        topic_id=100,
        turn_id="turn-1",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ):
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.turn_interrupt.assert_awaited_once_with("codex:onlineWorker", "tid-1", "turn-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")


@pytest.mark.asyncio
async def test_message_handler_interrupts_active_claude_turn_before_send():
    from bot.handlers.message import make_message_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/example/Projects/sample-project",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-1"] = ThreadInfo(thread_id="ses-1", topic_id=5457, archived=False)
    storage.workspaces["claude:ncmplayerengine"] = ws

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(
        return_value={
            "busy": True,
            "signals": ["assistant_tool_use"],
            "message": "当前 Claude thread 正忙，请先在本地收尾。",
        }
    )
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("claude", adapter)
    state.streaming_turns["ses-1"] = StreamingTurn(
        message_id=5501,
        topic_id=5457,
        turn_id="turn-claude-1",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 5457

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch("bot.handlers.message.save_storage") as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    assert adapter.mock_calls[:3] == [
        call.turn_interrupt("claude:ncmplayerengine", "ses-1", "turn-claude-1"),
        call.resume_thread("claude:ncmplayerengine", "ses-1"),
        call.send_user_message("claude:ncmplayerengine", "ses-1", "你好"),
    ]
    adapter.inspect_thread_activity.assert_not_awaited()
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_does_not_block_on_claude_thread_history_activity():
    from bot.handlers.message import make_message_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/example/Projects/sample-project",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-1"] = ThreadInfo(thread_id="ses-1", topic_id=5457, archived=False)
    storage.workspaces["claude:ncmplayerengine"] = ws

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(
        return_value={
            "busy": True,
            "signals": ["assistant_tool_use", "tool_result"],
            "message": "当前 Claude thread 正忙，请先在本地收尾。",
        }
    )
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("claude", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 5457

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch("bot.handlers.message.save_storage") as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.inspect_thread_activity.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("claude:ncmplayerengine", "ses-1")
    adapter.send_user_message.assert_awaited_once_with("claude:ncmplayerengine", "ses-1", "你好")
    ctx.bot.send_message.assert_not_awaited()
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_detaches_imported_claude_thread_before_send():
    from bot.handlers.message import make_message_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/example/Projects/sample-project",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-imported"] = ThreadInfo(
        thread_id="ses-imported",
        topic_id=5457,
        preview="历史导入 thread",
        archived=False,
        is_active=True,
        source="imported",
    )
    storage.workspaces["claude:ncmplayerengine"] = ws

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
    adapter.start_thread = AsyncMock(return_value={"id": "ses-app-new"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("claude", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 5457

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.claude.python.runtime.infer_claude_thread_source_from_logs",
        return_value="imported",
    ), patch("bot.handlers.message.save_storage") as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.inspect_thread_activity.assert_not_awaited()
    adapter.start_thread.assert_awaited_once_with("claude:ncmplayerengine")
    adapter.resume_thread.assert_awaited_once_with("claude:ncmplayerengine", "ses-app-new")
    adapter.send_user_message.assert_awaited_once_with(
        "claude:ncmplayerengine",
        "ses-app-new",
        "你好",
    )
    assert "ses-imported" in ws.threads
    assert ws.threads["ses-imported"].topic_id is None
    assert ws.threads["ses-imported"].preview == "历史导入 thread"
    assert ws.threads["ses-imported"].source == "imported"
    assert ws.threads["ses-app-new"].thread_id == "ses-app-new"
    assert ws.threads["ses-app-new"].topic_id == 5457
    assert ws.threads["ses-app-new"].preview == "你好"
    assert ws.threads["ses-app-new"].source == "app"
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_message_handler_keeps_unknown_claude_thread_when_logs_mark_app_owned():
    from bot.handlers.message import make_message_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/example/Projects/sample-project",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-app"] = ThreadInfo(
        thread_id="ses-app",
        topic_id=5457,
        preview="旧的 app thread",
        archived=False,
        is_active=True,
        source="unknown",
    )
    storage.workspaces["claude:ncmplayerengine"] = ws

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
    adapter.start_thread = AsyncMock(return_value={"id": "ses-live"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("claude", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 5457

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.claude.python.runtime.infer_claude_thread_source_from_logs",
        return_value="app",
    ), patch("bot.handlers.message.save_storage") as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.inspect_thread_activity.assert_not_awaited()
    adapter.start_thread.assert_not_called()
    adapter.resume_thread.assert_awaited_once_with("claude:ncmplayerengine", "ses-app")
    adapter.send_user_message.assert_awaited_once_with("claude:ncmplayerengine", "ses-app", "你好")
    assert ws.threads["ses-app"].source == "app"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_message_handler_rolls_back_imported_claude_remap_when_send_fails():
    from bot.handlers.message import make_message_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/example/Projects/sample-project",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-imported"] = ThreadInfo(
        thread_id="ses-imported",
        topic_id=5457,
        preview="历史导入 thread",
        archived=False,
        history_sync_cursor="cursor-imported",
        is_active=True,
        source="imported",
    )
    storage.workspaces["claude:ncmplayerengine"] = ws

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
                control_mode="app",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
    adapter.start_thread = AsyncMock(return_value={"id": "ses-app-new"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.turn_interrupt = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(side_effect=RuntimeError("boom"))
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("claude", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 5457

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch("bot.handlers.message.save_storage") as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.start_thread.assert_awaited_once_with("claude:ncmplayerengine")
    adapter.resume_thread.assert_awaited_once_with("claude:ncmplayerengine", "ses-app-new")
    adapter.send_user_message.assert_awaited_once_with(
        "claude:ncmplayerengine",
        "ses-app-new",
        "你好",
    )
    assert "ses-imported" in ws.threads
    assert "ses-app-new" not in ws.threads
    assert ws.threads["ses-imported"].thread_id == "ses-imported"
    assert ws.threads["ses-imported"].topic_id == 5457
    assert ws.threads["ses-imported"].source == "imported"
    assert ws.threads["ses-imported"].history_sync_cursor == "cursor-imported"
    save_storage_mock.assert_not_called()
    ctx.bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_message_handler_in_hybrid_mode_prefers_connected_codex_adapter():
    from bot.handlers.message import make_message_handler

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

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="ws",
                app_server_port=4722,
                control_mode="hybrid",
            )
        ],
        delete_archived_topics=True,
    )
    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state = AppState(storage=storage, config=cfg)
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "你好"
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.message.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.message.save_storage",
    ) as save_storage_mock:
        handler = make_message_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    enqueue_mock.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "你好")
    assert ws.threads["tid-1"].preview == "你好"
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_new_thread_handler_rejects_tui_mode_thread_creation():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="ws",
                app_server_port=4722,
                control_mode="tui",
            )
        ],
        delete_archived_topics=True,
    )
    state = AppState(storage=storage, config=cfg)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.thread.start_thread_via_tui_bridge",
        new=AsyncMock(return_value="tid-new"),
    ) as start_mock, patch(
        "bot.handlers.thread.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.thread.save_storage",
    ) as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    start_mock.assert_not_awaited()
    enqueue_mock.assert_not_awaited()
    save_storage_mock.assert_not_called()
    ctx.bot.create_forum_topic.assert_not_called()


@pytest.mark.asyncio
async def test_new_thread_handler_in_app_mode_creates_thread_and_topic():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=101))

    with patch("bot.handlers.thread.save_storage") as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker", "tid-new", "请帮我看下当前项目结构"
    )
    assert ws.threads["tid-new"].topic_id == 101
    save_storage_mock.assert_called_once()
    kwargs = ctx.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == GROUP_CHAT_ID
    assert kwargs["message_thread_id"] == 101
    assert "新 thread 已创建" in kwargs["text"]


@pytest.mark.asyncio
async def test_new_thread_handler_in_app_mode_requires_initial_text_for_codex():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=101))

    with patch("bot.handlers.thread.save_storage"):
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.create_forum_topic.assert_not_awaited()
    sent_texts = [call.kwargs.get("text", "") for call in ctx.bot.send_message.await_args_list]
    assert any("/new <初始消息>" in text for text in sent_texts)


@pytest.mark.asyncio
async def test_new_thread_handler_in_app_mode_accepts_top_level_thread_id():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "tid-new"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=101))

    with patch("bot.handlers.thread.save_storage") as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker", "tid-new", "请帮我看下当前项目结构"
    )
    assert ws.threads["tid-new"].topic_id == 101
    save_storage_mock.assert_called_once()


@pytest.mark.asyncio
async def test_new_thread_handler_rolls_back_when_topic_creation_fails():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.create_forum_topic = AsyncMock(side_effect=RuntimeError("topic boom"))
    ctx.bot.delete_forum_topic = AsyncMock()

    with patch("bot.handlers.thread.save_storage") as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    assert "tid-new" not in ws.threads
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.delete_forum_topic.assert_not_awaited()
    save_storage_mock.assert_not_called()


@pytest.mark.asyncio
async def test_new_thread_handler_rolls_back_when_initial_message_send_fails():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(side_effect=RuntimeError("send boom"))
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=101))
    ctx.bot.delete_forum_topic = AsyncMock()
    ctx.bot.close_forum_topic = AsyncMock()

    with patch("bot.handlers.thread.save_storage") as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    assert "tid-new" not in ws.threads
    ctx.bot.delete_forum_topic.assert_awaited_once_with(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=101,
    )
    save_storage_mock.assert_not_called()


@pytest.mark.asyncio
async def test_archive_thread_handler_uses_codex_bridge_without_persistent_adapter():
    from bot.handlers.thread import make_archive_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=101, archived=False)
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="ws",
                app_server_port=4722,
                control_mode="tui",
            )
        ],
        delete_archived_topics=True,
    )
    state = AppState(storage=storage, config=cfg)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 101

    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.delete_forum_topic = AsyncMock()

    with patch(
        "bot.handlers.thread.archive_codex_thread_via_tui_bridge",
        new=AsyncMock(return_value={"id": "tid-1"}),
    ) as archive_mock, patch(
        "bot.handlers.thread.save_storage",
    ) as save_storage_mock:
        handler = make_archive_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    archive_mock.assert_awaited_once_with(state, ws, "tid-1")
    assert ws.threads["tid-1"].archived is True
    assert ws.threads["tid-1"].topic_id is None
    ctx.bot.delete_forum_topic.assert_awaited_once_with(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=101,
    )
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_codex_new_then_archive_keeps_same_thread_id_across_full_flow():
    from bot.handlers.thread import make_archive_thread_handler, make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)
    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "tid-new"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    adapter.archive_thread = AsyncMock(return_value={"id": "tid-new"})
    state.set_adapter("codex", adapter)

    new_update = MagicMock()
    new_update.effective_message = MagicMock()
    new_update.effective_message.message_thread_id = 50

    new_ctx = MagicMock()
    new_ctx.args = ["请创建 codex 线程"]
    new_ctx.bot = MagicMock()
    new_ctx.bot.send_message = AsyncMock()
    new_ctx.bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=101))
    new_ctx.bot.delete_forum_topic = AsyncMock()
    new_ctx.bot.close_forum_topic = AsyncMock()

    archive_update = MagicMock()
    archive_update.effective_message = MagicMock()
    archive_update.effective_message.message_thread_id = 101

    archive_ctx = MagicMock()
    archive_ctx.args = []
    archive_ctx.bot = MagicMock()
    archive_ctx.bot.send_message = AsyncMock()
    archive_ctx.bot.delete_forum_topic = AsyncMock()
    archive_ctx.bot.close_forum_topic = AsyncMock()

    with patch("bot.handlers.thread.save_storage") as save_storage_mock:
        new_handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await new_handler(new_update, new_ctx)

        assert "tid-new" in ws.threads
        assert ws.threads["tid-new"].topic_id == 101
        assert ws.threads["tid-new"].archived is False

        archive_handler = make_archive_thread_handler(state, GROUP_CHAT_ID)
        await archive_handler(archive_update, archive_ctx)

    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "tid-new",
        "请创建 codex 线程",
    )
    adapter.archive_thread.assert_awaited_once_with("codex:onlineWorker", "tid-new")
    assert ws.threads["tid-new"].archived is True
    assert ws.threads["tid-new"].topic_id is None
    archive_ctx.bot.delete_forum_topic.assert_awaited_once_with(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=101,
    )
    assert save_storage_mock.call_count == 2


@pytest.mark.asyncio
async def test_new_thread_handler_in_app_mode_requires_connected_adapter():
    from bot.handlers.thread import make_new_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
    state = AppState(storage=storage, config=cfg)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请帮我看下当前项目结构"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    with patch(
        "bot.handlers.thread.start_thread_via_tui_bridge",
        new=AsyncMock(return_value="tid-new"),
    ) as start_mock, patch(
        "bot.handlers.thread.enqueue_codex_tui_message",
        new=AsyncMock(return_value=0),
    ) as enqueue_mock, patch(
        "bot.handlers.thread.save_storage",
    ) as save_storage_mock:
        handler = make_new_thread_handler(state, GROUP_CHAT_ID)
        await handler(update, ctx)

    start_mock.assert_not_awaited()
    enqueue_mock.assert_not_awaited()
    save_storage_mock.assert_not_called()
    ctx.bot.create_forum_topic.assert_not_called()
    kwargs = ctx.bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == GROUP_CHAT_ID
    assert kwargs["message_thread_id"] == 50
    assert "未连接" in kwargs["text"]


@pytest.mark.asyncio
async def test_list_thread_handler_hides_codex_unknown_state_only_residue(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-stale-unknown"] = ThreadInfo(
        thread_id="tid-stale-unknown",
        topic_id=None,
        preview="旧残留 thread",
        archived=False,
        is_active=False,
        source="unknown",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"
    state = AppState(storage=storage)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 3230

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_threads_by_cwd",
        lambda path, limit=20: [
            {
                "id": "tid-real",
                "preview": "真实 thread",
                "createdAt": 3000,
                "updatedAt": 3000,
            },
        ],
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=20: [],
        raising=False,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids",
        lambda thread_ids: set(),
        raising=False,
    )

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    kwargs = ctx.bot.send_message.call_args.kwargs
    text = kwargs["text"]
    assert "真实 thread" in text
    assert "旧残留 thread" not in text

    reply_markup = kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["📌 真实 thread"]


@pytest.mark.asyncio
async def test_list_thread_handler_skips_codex_state_only_subagent_threads(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-main"] = ThreadInfo(
        thread_id="tid-main",
        topic_id=None,
        preview="主线程标题",
        archived=False,
        is_active=True,
    )
    ws.threads["tid-subagent-1"] = ThreadInfo(
        thread_id="tid-subagent-1",
        topic_id=None,
        preview=None,
        archived=False,
        is_active=True,
    )
    ws.threads["tid-subagent-2"] = ThreadInfo(
        thread_id="tid-subagent-2",
        topic_id=None,
        preview=None,
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"
    state = AppState(storage=storage)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 3230

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_threads_by_cwd",
        lambda path, limit=20: [
            {"id": "tid-main", "preview": "主线程标题"},
        ],
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids",
        lambda thread_ids: {"tid-subagent-1", "tid-subagent-2"},
        raising=False,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=20: [],
        raising=False,
    )

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    kwargs = ctx.bot.send_message.call_args.kwargs
    text = kwargs["text"]
    assert "主线程标题" in text
    assert "tid-subagent-1" not in text
    assert "tid-subagent-2" not in text
    assert "thread-ent-1" not in text
    assert "thread-ent-2" not in text

    reply_markup = kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["📌 主线程标题"]


@pytest.mark.asyncio
async def test_list_thread_handler_includes_codex_jsonl_only_main_thread(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    storage.active_workspace = "codex:onlineWorker"
    state = AppState(storage=storage)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 3230

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_threads_by_cwd",
        lambda path, limit=20: [
            {
                "id": "tid-db-old",
                "preview": "数据库已有线程",
                "createdAt": 1000,
                "updatedAt": 1000,
            },
        ],
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids",
        lambda thread_ids: set(),
        raising=False,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=20: [
            {
                "id": "tid-phase15",
                "preview": "继续处理phase15",
                "createdAt": 3000,
                "updatedAt": 3000,
            },
        ],
        raising=False,
    )

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    kwargs = ctx.bot.send_message.call_args.kwargs
    text = kwargs["text"]
    assert text.index("继续处理phase15") < text.index("数据库已有线程")

    reply_markup = kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == [
        "📌 继续处理phase15",
        "📌 数据库已有线程",
    ]


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_pushes_new_assistant_reply_to_topic():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "user", "text": "你好", "phase": ""},
            {"role": "assistant", "text": "这是最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["chat_id"] == GROUP_CHAT_ID
    assert kwargs["message_thread_id"] == 100
    assert kwargs["text"] == "这是最终回复"
    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-04T05:00:10Z\n这是最终回复"


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_skips_already_synced_reply():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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
    codex_state.get_runtime(state).last_synced_assistant["tid-1"] = "2026-04-04T05:00:10Z\n这是最终回复"

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "user", "text": "你好", "phase": ""},
            {"role": "assistant", "text": "这是最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_only_pushes_final_answer():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "处理中进度", "timestamp": "2026-04-04T05:00:00Z", "phase": "commentary"},
            {"role": "assistant", "text": "真正最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["text"] == "真正最终回复"


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_skips_commentary_only_history():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "处理中进度", "timestamp": "2026-04-04T05:00:00Z", "phase": "commentary"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_skips_reply_already_sent_by_schedule():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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
    codex_state.get_runtime(state).last_synced_assistant["tid-1"] = "2026-04-04T05:00:10Z\n真正最终回复"

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "真正最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_skips_reply_marked_by_live_event_text_signature():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

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
    codex_state.get_runtime(state).last_synced_assistant["tid-1"] = "__text__\n真正最终回复"

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "真正最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    bot.send_message.assert_not_called()
    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-04T05:00:10Z\n真正最终回复"


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_skips_reply_marked_by_run_state():
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

    state, _, _ = make_codex_workspace_state()
    codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-1",
        turn_id="turn-live",
    )
    codex_state.mark_run(state,
        thread_id="tid-1",
        status="completed",
        final_reply_synced_to_tg=True,
    )

    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {
                "role": "assistant",
                "text": "直播链路已经同步过的最终回复",
                "timestamp": "2026-04-04T05:00:10Z",
                "phase": "final_answer",
                "turn_id": "turn-live",
            },
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    bot.send_message.assert_not_called()
    assert (
        codex_state.get_runtime(state).last_synced_assistant["tid-1"]
        == "2026-04-04T05:00:10Z\n直播链路已经同步过的最终回复"
    )


@pytest.mark.asyncio
async def test_sync_codex_tui_final_replies_once_revives_stale_archived_active_thread(monkeypatch):
    from plugins.providers.builtin.codex.python.tui_bridge import sync_codex_tui_final_replies_once

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=True, is_active=False)
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_bridge.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-1"},
        raising=False,
    )

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "这是最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await sync_codex_tui_final_replies_once(state, bot, GROUP_CHAT_ID)

    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["message_thread_id"] == 100
    assert kwargs["text"] == "这是最终回复"
    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True


@pytest.mark.asyncio
async def test_schedule_codex_final_reply_marks_sent_reply_as_synced():
    from plugins.providers.builtin.codex.python.tui_bridge import schedule_codex_final_reply

    state = AppState(storage=AppStorage())
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        side_effect=[
            [
                {"role": "assistant", "text": "过程播报", "timestamp": "2026-04-04T05:00:01Z", "phase": "commentary"},
                {"role": "assistant", "text": "真正最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
            ],
        ],
    ):
        task = schedule_codex_final_reply(
            state,
            bot,
            GROUP_CHAT_ID,
            100,
            "tid-1",
            baseline_len=0,
            poll_interval=0.01,
            max_wait_seconds=0.1,
        )
        await task

    kwargs = bot.send_message.call_args.kwargs
    assert kwargs["text"] == "真正最终回复"
    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-04T05:00:10Z\n真正最终回复"


@pytest.mark.asyncio
async def test_send_message_via_tui_bridge_baseline_counts_only_final_answers():
    from plugins.providers.builtin.codex.python.tui_bridge import send_message_via_tui_bridge

    state = AppState(storage=AppStorage())
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "过程播报1", "timestamp": "2026-04-04T05:00:01Z", "phase": "commentary"},
            {"role": "assistant", "text": "最终回复1", "timestamp": "2026-04-04T05:00:02Z", "phase": "final_answer"},
            {"role": "assistant", "text": "过程播报2", "timestamp": "2026-04-04T05:00:03Z", "phase": "commentary"},
        ],
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_host",
        new=AsyncMock(),
    ):
        baseline = await send_message_via_tui_bridge(state, ws, "tid-1", "你好")

    assert baseline == 1


@pytest.mark.asyncio
async def test_send_message_via_tui_bridge_seeds_and_refreshes_watch_state():
    from plugins.providers.builtin.codex.python.tui_bridge import send_message_via_tui_bridge

    state = AppState(storage=AppStorage())
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.seed_codex_watch_baseline",
    ) as seed_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.watch_codex_thread",
    ) as watch_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_host",
        new=AsyncMock(),
    ):
        baseline = await send_message_via_tui_bridge(state, ws, "tid-1", "你好")

    assert baseline == 0
    seed_mock.assert_called_once_with(state, ws, "tid-1")
    watch_mock.assert_called_once_with(state, ws, "tid-1")


@pytest.mark.asyncio
async def test_send_message_via_tui_bridge_uses_local_tui_host_client():
    from plugins.providers.builtin.codex.python.tui_bridge import send_message_via_tui_bridge

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

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.seed_codex_watch_baseline",
    ) as seed_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.watch_codex_thread",
    ) as watch_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_host",
        new=AsyncMock(),
    ) as host_mock:
        baseline = await send_message_via_tui_bridge(state, ws, "tid-1", "你好")

    assert baseline == 0
    host_mock.assert_awaited_once_with(state, ws, "tid-1", "你好")
    seed_mock.assert_called_once_with(state, ws, "tid-1")
    watch_mock.assert_called_once_with(state, ws, "tid-1")


@pytest.mark.asyncio
async def test_send_message_via_tui_host_does_not_auto_start_managed_host_for_app_mode(tmp_path):
    from plugins.providers.builtin.codex.python.tui_bridge import send_message_via_tui_host

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
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
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
        data_dir=str(tmp_path),
        delete_archived_topics=True,
    )
    state = AppState(storage=storage, config=cfg)

    host = MagicMock()
    host.start = AsyncMock()
    host.thread_id = "tid-1"
    host.cwd = ws.path
    host.is_running = False

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_host_status",
        return_value=None,
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.CodexTuiHost",
        return_value=host,
    ) as host_cls, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_to_codex_tui_host",
        new=AsyncMock(return_value={"ok": True}),
    ) as client_mock:
        result = await send_message_via_tui_host(state, ws, "tid-1", "你好")

    assert result == {"ok": True}
    host_cls.assert_not_called()
    host.start.assert_not_awaited()
    assert codex_state.get_tui_host(state) is None
    assert codex_state.get_runtime(state).thread_pending_send_started_at["tid-1"] > 0
    client_mock.assert_awaited_once_with(state, ws, "tid-1", "你好", topic_id=100)


@pytest.mark.asyncio
async def test_start_thread_via_tui_bridge_prefers_persistent_codex_adapter_when_connected():
    from plugins.providers.builtin.codex.python.tui_bridge import start_thread_via_tui_bridge

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "tid-new"})
    state.set_adapter("codex", adapter)

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.with_codex_tui_bridge",
        new=AsyncMock(),
    ) as bridge_mock:
        thread_id = await start_thread_via_tui_bridge(state, ws)

    assert thread_id == "tid-new"
    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    bridge_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_message_via_tui_bridge_propagates_local_host_error():
    from plugins.providers.builtin.codex.python.tui_bridge import send_message_via_tui_bridge

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

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.seed_codex_watch_baseline",
    ) as seed_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.watch_codex_thread",
    ) as watch_mock, patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_host",
        new=AsyncMock(side_effect=RuntimeError("host offline")),
    ) as host_mock:
        with pytest.raises(RuntimeError, match="host offline"):
            await send_message_via_tui_bridge(state, ws, "tid-1", "你好")

    host_mock.assert_awaited_once_with(state, ws, "tid-1", "你好")
    seed_mock.assert_called_once_with(state, ws, "tid-1")
    watch_mock.assert_not_called()


@pytest.mark.asyncio
async def test_start_thread_via_tui_bridge_falls_back_to_short_lived_bridge_when_persistent_adapter_unavailable():
    from plugins.providers.builtin.codex.python.tui_bridge import start_thread_via_tui_bridge

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.connected = False
    adapter.start_thread = AsyncMock(return_value={"id": "tid-ignored"})
    state.set_adapter("codex", adapter)

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.with_codex_tui_bridge",
        new=AsyncMock(return_value="tid-new"),
    ) as bridge_mock:
        thread_id = await start_thread_via_tui_bridge(state, ws)

    assert thread_id == "tid-new"
    adapter.start_thread.assert_not_awaited()
    bridge_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_codex_tui_message_serializes_same_thread_sends():
    from plugins.providers.builtin.codex.python.tui_bridge import enqueue_codex_tui_message

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
    bot = MagicMock()

    events: list[str] = []
    gate = asyncio.Event()

    async def _fake_send(_state, _ws, _thread_id, text):
        events.append(f"start:{text}")
        if text == "first":
            await gate.wait()
        events.append(f"end:{text}")
        return 0

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_bridge",
        new=AsyncMock(side_effect=_fake_send),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.get_persistent_codex_adapter",
        return_value=MagicMock(connected=True),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.schedule_codex_final_reply",
    ) as schedule_mock:
        first = asyncio.create_task(
            enqueue_codex_tui_message(state, ws, bot, GROUP_CHAT_ID, 100, "tid-1", "first")
        )
        await asyncio.sleep(0)
        second = asyncio.create_task(
            enqueue_codex_tui_message(state, ws, bot, GROUP_CHAT_ID, 100, "tid-1", "second")
        )
        await asyncio.sleep(0.01)
        assert events == ["start:first"]
        gate.set()
        await asyncio.gather(first, second)

    assert events == ["start:first", "end:first", "start:second", "end:second"]
    assert schedule_mock.call_count == 2


@pytest.mark.asyncio
async def test_enqueue_codex_tui_message_waits_until_thread_turn_completed():
    from plugins.providers.builtin.codex.python.tui_bridge import enqueue_codex_tui_message

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
    codex_state.mark_tui_turn_started(state, "tid-1")

    bot = MagicMock()
    gate = asyncio.Event()
    send_mock = AsyncMock(return_value=0)

    async def _release_gate():
        await asyncio.sleep(0.01)
        codex_state.mark_tui_turn_completed(state, "tid-1")
        gate.set()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.send_message_via_tui_bridge",
        new=send_mock,
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.get_persistent_codex_adapter",
        return_value=MagicMock(connected=True),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.schedule_codex_final_reply",
    ) as schedule_mock:
        release_task = asyncio.create_task(_release_gate())
        send_task = asyncio.create_task(
            enqueue_codex_tui_message(state, ws, bot, GROUP_CHAT_ID, 100, "tid-1", "later")
        )
        await asyncio.sleep(0)
        send_mock.assert_not_awaited()
        await gate.wait()
        await send_task
        await release_task

    send_mock.assert_awaited_once_with(state, ws, "tid-1", "later")
    schedule_mock.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_codex_final_reply_skips_when_realtime_mirror_already_synced_same_reply():
    from plugins.providers.builtin.codex.python.tui_bridge import schedule_codex_final_reply

    state = AppState(storage=AppStorage())
    codex_state.get_runtime(state).last_synced_assistant["tid-1"] = "2026-04-04T05:00:10Z\n真正最终回复"
    bot = MagicMock()
    bot.send_message = AsyncMock()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "真正最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        task = schedule_codex_final_reply(
            state,
            bot,
            GROUP_CHAT_ID,
            100,
            "tid-1",
            baseline_len=0,
            poll_interval=0.01,
            max_wait_seconds=0.05,
        )
        await task

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_prime_codex_tui_reply_state_records_latest_final_without_sending():
    from plugins.providers.builtin.codex.python.tui_bridge import prime_codex_tui_reply_state

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

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "过程播报", "timestamp": "2026-04-04T05:00:01Z", "phase": "commentary"},
            {"role": "assistant", "text": "最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await prime_codex_tui_reply_state(state)

    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-04T05:00:10Z\n最终回复"


@pytest.mark.asyncio
async def test_prime_codex_tui_reply_state_revives_stale_archived_active_thread(monkeypatch):
    from plugins.providers.builtin.codex.python.tui_bridge import prime_codex_tui_reply_state

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=50,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=True, is_active=False)
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_bridge.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-1"},
        raising=False,
    )

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "最终回复", "timestamp": "2026-04-04T05:00:10Z", "phase": "final_answer"},
        ],
    ):
        await prime_codex_tui_reply_state(state)

    assert codex_state.get_runtime(state).last_synced_assistant["tid-1"] == "2026-04-04T05:00:10Z\n最终回复"
    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True


@pytest.mark.asyncio
async def test_start_codex_tui_sync_loop_primes_before_polling():
    from plugins.providers.builtin.codex.python.tui_bridge import start_codex_tui_sync_loop

    state = AppState(storage=AppStorage())
    bot = MagicMock()
    calls = []

    async def _fake_prime(_state):
        calls.append("prime")

    async def _fake_sync(_state, _bot, _group_chat_id):
        calls.append("sync")
        raise asyncio.CancelledError()

    with patch(
        "plugins.providers.builtin.codex.python.tui_bridge.prime_codex_tui_reply_state",
        new=AsyncMock(side_effect=_fake_prime),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.sync_codex_tui_final_replies_once",
        new=AsyncMock(side_effect=_fake_sync),
    ):
        task = start_codex_tui_sync_loop(state, bot, GROUP_CHAT_ID, poll_interval=0.01)
        with pytest.raises(asyncio.CancelledError):
            await task

    assert calls == ["prime", "sync"]
