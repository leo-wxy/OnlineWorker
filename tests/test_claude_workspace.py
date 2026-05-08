from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo

GROUP_CHAT_ID = -100123456789


@pytest.mark.asyncio
async def test_open_workspace_syncs_claude_threads_from_adapter(monkeypatch):
    from bot.handlers.workspace import _open_workspace

    storage = AppStorage()
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.connected = True
    adapter.register_workspace_cwd = MagicMock()
    adapter.list_threads = AsyncMock(
        return_value=[
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ]
    )
    state.set_adapter("claude", adapter)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=4101))

    monkeypatch.setattr("bot.handlers.workspace.save_storage", lambda storage: None)
    monkeypatch.setattr("bot.handlers.common.save_storage", lambda storage: None)
    monkeypatch.setattr(
        "bot.handlers.workspace.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-1"},
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_workspace_thread_overview",
        AsyncMock(),
    )

    ws_info = await _open_workspace(
        bot=bot,
        state=state,
        storage=storage,
        group_chat_id=GROUP_CHAT_ID,
        tool_cfg=ToolConfig(name="claude", enabled=True, codex_bin="claude", protocol="stdio"),
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
    )

    adapter.register_workspace_cwd.assert_called_once_with(
        "claude:onlineWorker",
        "/Users/wxy/Projects/onlineWorker",
    )
    adapter.list_threads.assert_awaited_once_with("claude:onlineWorker", limit=30)
    assert ws_info.tool == "claude"
    assert "ses-1" in ws_info.threads
    assert ws_info.threads["ses-1"].preview == "继续 phase16"
    assert ws_info.threads["ses-1"].is_active is True


@pytest.mark.asyncio
async def test_list_thread_handler_uses_claude_local_threads(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[ToolConfig(name="claude", enabled=True, codex_bin="claude", protocol="stdio")],
        delete_archived_topics=True,
    )
    state.config = cfg

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.storage_runtime.list_claude_threads_by_cwd",
        lambda path, limit=20: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr("bot.handlers.thread._send_to_group", send_to_group)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 4101

    context = MagicMock()
    context.bot = MagicMock()

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, context)

    send_to_group.assert_awaited_once()
    text = send_to_group.await_args.args[2]
    assert "[claude] onlineWorker" in text
    assert "phase16" in text


@pytest.mark.asyncio
async def test_list_thread_handler_hides_archived_claude_threads(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-archived"] = ThreadInfo(
        thread_id="ses-archived",
        topic_id=4201,
        preview="已归档的 claude thread",
        archived=True,
        is_active=False,
        source="app",
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[ToolConfig(name="claude", enabled=True, codex_bin="claude", protocol="stdio")],
        delete_archived_topics=True,
    )
    state.config = cfg

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, path, limit=20: [
            {
                "id": "ses-archived",
                "preview": "已归档的 claude thread",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.common.list_provider_threads",
        lambda tool_name, path, limit=200: [
            {
                "id": "ses-archived",
                "preview": "已归档的 claude thread",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_local_threads",
        lambda tool_name, path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_subagent_thread_ids",
        lambda tool_name, thread_ids: set(),
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-archived"},
        raising=False,
    )
    monkeypatch.setattr("bot.handlers.thread.save_storage", lambda storage: None)
    monkeypatch.setattr("bot.handlers.common.save_storage", lambda storage: None)
    send_to_group = AsyncMock()
    monkeypatch.setattr("bot.handlers.thread._send_to_group", send_to_group)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 4101

    context = MagicMock()
    context.bot = MagicMock()

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, context)

    text = send_to_group.await_args.args[2]
    assert "暂无 thread" in text
    assert "已归档的 claude thread" not in text


@pytest.mark.asyncio
async def test_list_thread_handler_hides_stale_claude_state_only_threads(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-1"] = ThreadInfo(
        thread_id="ses-1",
        topic_id=None,
        preview="继续 phase16",
        archived=False,
        is_active=True,
    )
    ws.threads["stale-old"] = ThreadInfo(
        thread_id="stale-old",
        topic_id=None,
        preview="who are you",
        archived=False,
        is_active=False,
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, path, limit=20: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.common.list_provider_threads",
        lambda tool_name, path, limit=200: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.thread.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-1"},
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-1"},
        raising=False,
    )
    monkeypatch.setattr("bot.handlers.common.save_storage", lambda storage: None)
    send_to_group = AsyncMock()
    monkeypatch.setattr("bot.handlers.thread._send_to_group", send_to_group)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 4101

    context = MagicMock()
    context.bot = MagicMock()

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, context)

    send_to_group.assert_awaited_once()
    text = send_to_group.await_args.args[2]
    assert "继续 phase16" in text
    assert "who are you" not in text
    assert "stale-old" not in ws.threads


@pytest.mark.asyncio
async def test_workspace_overview_hides_stale_claude_state_only_threads(monkeypatch):
    from bot.handlers.workspace import _send_workspace_thread_overview

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-1"] = ThreadInfo(
        thread_id="ses-1",
        topic_id=None,
        preview="继续 phase16",
        archived=False,
        is_active=True,
    )
    ws.threads["stale-old"] = ThreadInfo(
        thread_id="stale-old",
        topic_id=None,
        preview="who are you",
        archived=False,
        is_active=False,
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=200: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-1"},
        raising=False,
    )
    monkeypatch.setattr("bot.handlers.common.save_storage", lambda storage: None)
    send_to_group = AsyncMock()
    monkeypatch.setattr("bot.handlers.workspace._send_to_group", send_to_group)

    await _send_workspace_thread_overview(
        state,
        MagicMock(),
        GROUP_CHAT_ID,
        ws,
        "claude",
        active_ids={"ses-1"},
    )

    send_to_group.assert_awaited_once()
    text = send_to_group.await_args.args[2]
    assert "继续 phase16" in text
    assert "who are you" not in text
    assert "stale-old" not in ws.threads


@pytest.mark.asyncio
async def test_history_handler_reads_claude_local_history(monkeypatch):
    from bot.handlers.thread import make_history_handler

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-1"] = ThreadInfo(
        thread_id="ses-1",
        topic_id=4201,
        preview="继续 phase16",
        archived=False,
        is_active=True,
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    monkeypatch.setattr(
        "bot.handlers.thread.read_provider_thread_history",
        lambda tool_name, thread_id, limit=10, sessions_dir=None: [
            {"role": "user", "text": "第一条"},
            {"role": "user", "text": "第二条"},
        ],
        raising=False,
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr("bot.handlers.thread._send_to_group", send_to_group)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 4201

    context = MagicMock()
    context.bot = MagicMock()
    context.args = []

    handler = make_history_handler(state, GROUP_CHAT_ID)
    await handler(update, context)

    texts = [call.args[2] for call in send_to_group.await_args_list]
    assert any("历史记录" in text for text in texts)
    assert any("第一条" in text for text in texts)
    assert any("第二条" in text for text in texts)
