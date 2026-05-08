# tests/test_handlers.py
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from config import Config, ToolConfig
from core.state import AppState, PendingCommandWrapper
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo

GROUP_CHAT_ID = -100123456789

@pytest.fixture
def state():
    st = AppState()
    st.storage = AppStorage()
    return st

@pytest.fixture
def mock_update():
    update = MagicMock()
    update.effective_user.id = 12345
    update.effective_message.message_id = 1
    update.effective_message.message_thread_id = None
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.text = "hello"
    update.message.message_id = 1
    update.message.message_thread_id = None
    return update

@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx

@pytest.mark.asyncio
async def test_ping_handler(mock_update, mock_context, state):
    from bot.handlers import make_ping_handler
    handler = make_ping_handler(GROUP_CHAT_ID)
    await handler(mock_update, mock_context)
    mock_context.bot.send_message.assert_called_once()
    call_kwargs = mock_context.bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == GROUP_CHAT_ID
    assert call_kwargs["text"] == "pong"


@pytest.mark.asyncio
async def test_start_handler_uses_provider_neutral_text(mock_update, mock_context):
    from bot.handlers.common import make_start_handler

    handler = make_start_handler(GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "对应 codex thread" not in text
    assert "对应 CLI thread" in text


@pytest.mark.asyncio
async def test_stop_handler_requests_graceful_shutdown(mock_update, mock_context):
    from bot.handlers.common import make_stop_handler

    mock_context.application = MagicMock()
    mock_context.application.stop_running = MagicMock()

    handler = make_stop_handler(GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    mock_context.bot.send_message.assert_called_once()
    call_kwargs = mock_context.bot.send_message.call_args[1]
    assert call_kwargs["chat_id"] == GROUP_CHAT_ID
    assert "正在停止" in call_kwargs["text"]
    mock_context.application.stop_running.assert_called_once_with()

@pytest.mark.asyncio
async def test_status_handler(mock_update, mock_context, state):
    from bot.handlers import make_status_handler
    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)
    mock_context.bot.send_message.assert_called_once()
    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "已启动" in text
    assert "app-server" in text


@pytest.mark.asyncio
async def test_status_handler_reports_codex_hybrid_mode(state, mock_update, mock_context):
    from bot.handlers import make_status_handler

    state.config = Config(
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
    state.set_adapter("codex", adapter)

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "Hybrid" in text


@pytest.mark.asyncio
async def test_status_handler_reports_codex_app_mode_without_local_owner(state, mock_update, mock_context):
    from bot.handlers import make_status_handler

    state.config = Config(
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

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "本地 owner" not in text
    assert "App" in text


@pytest.mark.asyncio
async def test_status_handler_reports_claude_auth_missing_when_connected(state, mock_update, mock_context):
    from bot.handlers import make_status_handler

    state.config = Config(
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
            )
        ],
        delete_archived_topics=True,
    )
    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.auth_ready = False
    state.set_adapter("claude", claude_adapter)

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "claude CLI" in text
    assert "未鉴权" in text


@pytest.mark.asyncio
async def test_status_handler_reports_claude_proxy_auth_when_connected(state, mock_update, mock_context):
    from bot.handlers import make_status_handler

    state.config = Config(
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
            )
        ],
        delete_archived_topics=True,
    )
    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.auth_ready = True
    claude_adapter.auth_method = "proxyEnv"
    state.set_adapter("claude", claude_adapter)

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "claude CLI" in text
    assert "API/Proxy" in text


@pytest.mark.asyncio
async def test_status_handler_uses_registry_status_builder_for_custom_provider(state, mock_update, mock_context, monkeypatch):
    from bot.handlers import make_status_handler

    state.config = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            )
        ],
        delete_archived_topics=True,
    )

    custom_adapter = MagicMock()
    custom_adapter.connected = True
    state.set_adapter("custom", custom_adapter)

    monkeypatch.setattr(
        "bot.handlers.common.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(  # type: ignore[name-defined]
            status_builder=lambda current_state: ["• custom runtime：✅ 已连接"]
        ) if name == "custom" else None,
    )

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "custom runtime" in text


@pytest.mark.asyncio
async def test_status_handler_revives_stale_archived_active_thread_in_count(state, mock_update, mock_context, monkeypatch):
    from bot.handlers import make_status_handler

    state.config = Config(
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
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=77,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=True, is_active=False)
    state.storage.workspaces["codex:onlineWorker"] = ws
    state.storage.active_workspace = "codex:onlineWorker"

    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: None,
    )

    handler = make_status_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "活跃 thread 数：1" in text
    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True


def test_reconcile_workspace_threads_with_source_prunes_stale_imported_claude_threads(monkeypatch):
    from bot.handlers.common import reconcile_workspace_threads_with_source

    state = AppState()
    state.storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=77,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["tid-imported-stale"] = ThreadInfo(
        thread_id="tid-imported-stale",
        preview="Reply with exactly OK",
        archived=False,
        is_active=True,
        source="imported",
    )
    ws.threads["tid-imported-keep"] = ThreadInfo(
        thread_id="tid-imported-keep",
        preview="继续修 claude",
        archived=False,
        is_active=False,
        source="imported",
    )
    ws.threads["tid-app-stale"] = ThreadInfo(
        thread_id="tid-app-stale",
        preview="真实 app thread",
        archived=False,
        is_active=True,
        source="app",
    )
    state.storage.workspaces["claude:onlineWorker"] = ws

    save_calls: list[bool] = []
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: save_calls.append(True),
    )

    active_ids, changed = reconcile_workspace_threads_with_source(
        state,
        ws,
        active_ids={"tid-imported-keep"},
    )

    assert active_ids == {"tid-imported-keep"}
    assert changed is True
    assert "tid-imported-stale" not in ws.threads
    assert ws.threads["tid-imported-keep"].is_active is True
    assert ws.threads["tid-app-stale"].is_active is False
    assert save_calls == [True]


def test_reconcile_workspace_threads_with_source_prunes_stale_unknown_claude_threads_without_topic(monkeypatch):
    from bot.handlers.common import reconcile_workspace_threads_with_source

    state = AppState()
    state.storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["tid-unknown-stale"] = ThreadInfo(
        thread_id="tid-unknown-stale",
        preview="旧 unknown stale",
        archived=False,
        is_active=True,
        source="unknown",
    )
    ws.threads["tid-unknown-topic"] = ThreadInfo(
        thread_id="tid-unknown-topic",
        topic_id=5457,
        preview="旧 topic 映射",
        archived=False,
        is_active=True,
        source="unknown",
    )
    ws.threads["tid-live"] = ThreadInfo(
        thread_id="tid-live",
        preview="真实本地 thread",
        archived=False,
        is_active=False,
        source="imported",
    )
    state.storage.workspaces["claude:ncmplayerengine"] = ws

    save_calls: list[bool] = []
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: save_calls.append(True),
    )

    active_ids, changed = reconcile_workspace_threads_with_source(
        state,
        ws,
        active_ids={"tid-live"},
    )

    assert active_ids == {"tid-live"}
    assert changed is True
    assert "tid-unknown-stale" not in ws.threads
    assert ws.threads["tid-unknown-topic"].is_active is False
    assert ws.threads["tid-live"].is_active is True
    assert save_calls == [True]


def test_reconcile_workspace_threads_with_source_keeps_archived_claude_thread_archived(monkeypatch):
    from bot.handlers.common import reconcile_workspace_threads_with_source

    state = AppState()
    state.storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=77,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-archived"] = ThreadInfo(
        thread_id="ses-archived",
        preview="已归档 thread",
        archived=True,
        is_active=False,
        source="app",
    )
    state.storage.workspaces["claude:onlineWorker"] = ws

    save_calls: list[bool] = []
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: save_calls.append(True),
    )

    active_ids, changed = reconcile_workspace_threads_with_source(
        state,
        ws,
        active_ids={"ses-archived"},
    )

    assert active_ids == {"ses-archived"}
    assert changed is True
    assert ws.threads["ses-archived"].archived is True
    assert ws.threads["ses-archived"].is_active is True
    assert save_calls == [True]


@pytest.mark.asyncio
async def test_list_handler_for_claude_ignores_state_only_threads(monkeypatch, state, mock_update, mock_context):
    from bot.handlers.thread import make_list_thread_handler

    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-state-only"] = ThreadInfo(
        thread_id="ses-state-only",
        preview="旧 state only",
        archived=False,
        is_active=True,
        source="unknown",
    )
    state.storage.workspaces["claude:ncmplayerengine"] = ws
    mock_update.effective_message.message_thread_id = 5454

    sent: list[dict] = []

    async def fake_send(bot, group_chat_id, text, **kwargs):
        sent.append({"text": text, **kwargs})

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool, path, limit=20: [
            {
                "id": "ses-real",
                "preview": "真实本地 thread",
                "createdAt": 100,
                "updatedAt": 100,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_local_threads",
        lambda tool, path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.thread.query_provider_active_thread_ids",
        lambda tool, path: {"ses-real"},
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_subagent_thread_ids",
        lambda tool, tids: set(),
    )
    monkeypatch.setattr("bot.handlers.thread._send_to_group", fake_send)
    monkeypatch.setattr("bot.handlers.thread.save_storage", lambda storage_obj: None)

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    assert len(sent) == 1
    assert "真实本地 thread" in sent[0]["text"]
    assert "旧 state only" not in sent[0]["text"]


@pytest.mark.asyncio
async def test_help_handler_workspace_topic_mentions_current_provider(state, mock_update, mock_context):
    from bot.handlers.common import make_help_handler
    from core.storage import WorkspaceInfo

    ws = WorkspaceInfo(
        name="demo",
        path="/tmp/demo",
        tool="customprovider",
        topic_id=77,
        daemon_workspace_id="customprovider:demo",
    )
    state.storage.workspaces["customprovider:demo"] = ws
    mock_update.effective_message.message_thread_id = 77

    handler = make_help_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)

    text = mock_context.bot.send_message.call_args[1]["text"]
    assert "customprovider" in text
    assert "与 codex 对话" not in text


@pytest.mark.asyncio
async def test_message_handler_ignores_unknown_topic_message(mock_update, mock_context, state):
    """未知 topic 的普通消息当前直接忽略。"""
    from bot.handlers import make_message_handler
    # 模拟 effective_message
    mock_update.effective_message = MagicMock()
    mock_update.effective_message.text = "hello"
    mock_update.effective_message.message_id = 1
    mock_update.effective_message.message_thread_id = None
    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)
    mock_context.bot.send_message.assert_not_called()

@pytest.mark.asyncio
async def test_confirm_callback(mock_update, mock_context, state):
    from bot.handlers import make_callback_handler
    state.set_pending("hello", message_id=1)
    mock_update.callback_query = MagicMock()
    mock_update.callback_query.data = "confirm:1"
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)
    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once()
    call_args = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "hello" in call_args
    assert not state.is_waiting_confirmation()

@pytest.mark.asyncio
async def test_cancel_callback(mock_update, mock_context, state):
    from bot.handlers import make_callback_handler
    state.set_pending("hello", message_id=1)
    mock_update.callback_query = MagicMock()
    mock_update.callback_query.data = "cancel:1"
    mock_update.callback_query.answer = AsyncMock()
    mock_update.callback_query.edit_message_text = AsyncMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(mock_update, mock_context)
    mock_update.callback_query.answer.assert_called_once()
    mock_update.callback_query.edit_message_text.assert_called_once()
    call_args = mock_update.callback_query.edit_message_text.call_args[0][0]
    assert "取消" in call_args
    assert not state.is_waiting_confirmation()


@pytest.mark.asyncio
async def test_message_handler_consumes_pending_review_wrapper_text_and_updates_panel():
    from bot.handlers.message import make_message_handler
    from core.storage import ThreadInfo, WorkspaceInfo

    state = AppState()
    state.storage = AppStorage()
    ws = WorkspaceInfo(
        name="demo",
        path="/tmp/demo",
        tool="customprovider",
        topic_id=50,
        daemon_workspace_id="customprovider:demo",
    )
    ws.threads["ses-1"] = ThreadInfo(thread_id="ses-1", topic_id=100, archived=False)
    state.storage.workspaces["customprovider:demo"] = ws

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("customprovider", adapter)

    state.pending_command_wrappers[700] = PendingCommandWrapper(
        command_name="review",
        workspace_id="customprovider:demo",
        thread_id="ses-1",
        topic_id=100,
        tool_name="customprovider",
        prompt_text="review panel",
        current_step="await_text",
        awaiting_text=True,
        panel_message_id=900,
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "HEAD~1"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    pending = state.pending_command_wrappers[700]
    assert pending.awaiting_text is False
    assert pending.current_step == "confirm"
    assert pending.text_value == "HEAD~1"
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_not_called()
    ctx.bot.edit_message_text.assert_awaited_once()
    edited_text = ctx.bot.edit_message_text.await_args.kwargs["text"]
    assert "/review HEAD~1" in edited_text


@pytest.mark.asyncio
async def test_message_handler_tracks_last_tg_user_message_id_per_thread():
    from bot.handlers.message import make_message_handler

    state = AppState()
    state.storage = AppStorage()
    ws = WorkspaceInfo(
        name="demo",
        path="/tmp/demo",
        tool="dummy",
        topic_id=50,
        daemon_workspace_id="dummy:demo",
    )
    ws.threads["tid-123"] = ThreadInfo(thread_id="tid-123", topic_id=100, archived=False)
    state.storage.workspaces["dummy:demo"] = ws

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("dummy", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "hello"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_id = 321
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with("dummy:demo", "tid-123")
    adapter.send_user_message.assert_awaited_once_with("dummy:demo", "tid-123", "hello")
    assert state.thread_last_tg_user_message_ids["tid-123"] == 321
    assert ws.threads["tid-123"].last_tg_user_message_id == 321
