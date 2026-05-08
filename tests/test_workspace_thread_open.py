import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from bot.handlers.workspace import (
    make_thread_open_callback_handler,
    make_thread_open_callback_data,
)
from core.state import AppState
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo


GROUP_CHAT_ID = -100123456789


@pytest.mark.asyncio
async def test_workspace_overview_revives_stale_archived_active_thread(monkeypatch):
    from bot.handlers.workspace import _send_workspace_thread_overview

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(
        thread_id="tid-1",
        topic_id=4567,
        preview="继续处理phase15",
        archived=True,
        is_active=False,
    )
    state = AppState(storage=storage)
    storage.workspaces["codex:onlineWorker"] = ws

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_mock,
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: None,
    )

    await _send_workspace_thread_overview(
        state,
        MagicMock(),
        GROUP_CHAT_ID,
        ws,
        "codex",
    )

    args = send_mock.await_args.args
    kwargs = send_mock.await_args.kwargs
    text = args[2]
    assert "Active (1):" in text
    assert "继续处理phase15" in text
    reply_markup = kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["✅ 继续处理phase15"]
    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True


@pytest.mark.asyncio
async def test_workspace_overview_hides_archived_claude_thread_from_active_section(monkeypatch):
    from bot.handlers.workspace import _send_workspace_thread_overview

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=3230,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-archived"] = ThreadInfo(
        thread_id="ses-archived",
        topic_id=4567,
        preview="已归档的 claude thread",
        archived=True,
        is_active=False,
        source="app",
    )
    state = AppState(storage=storage)
    storage.workspaces["claude:onlineWorker"] = ws

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_mock,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, workspace_path, limit=100: [],
    )
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: None,
    )

    await _send_workspace_thread_overview(
        state,
        MagicMock(),
        GROUP_CHAT_ID,
        ws,
        "claude",
        active_ids={"ses-archived"},
    )

    args = send_mock.await_args.args
    kwargs = send_mock.await_args.kwargs
    text = args[2]
    assert "已归档的 claude thread" not in text
    assert "Active (" not in text
    assert kwargs["reply_markup"] is None
    assert ws.threads["ses-archived"].archived is True
    assert ws.threads["ses-archived"].is_active is True


@pytest.mark.asyncio
async def test_workspace_overview_for_claude_only_shows_provider_local_threads(monkeypatch):
    from bot.handlers.workspace import _send_workspace_thread_overview

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-state-topic"] = ThreadInfo(
        thread_id="ses-state-topic",
        topic_id=5457,
        preview="旧 state topic",
        archived=False,
        is_active=True,
        source="unknown",
    )
    ws.threads["ses-state-only"] = ThreadInfo(
        thread_id="ses-state-only",
        preview="旧 state only",
        archived=False,
        is_active=True,
        source="unknown",
    )
    ws.threads["ses-real"] = ThreadInfo(
        thread_id="ses-real",
        preview="真实本地 thread",
        archived=False,
        is_active=False,
        source="imported",
    )
    state = AppState(storage=storage)
    storage.workspaces["claude:ncmplayerengine"] = ws

    send_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_mock,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, workspace_path, limit=100: [
            {
                "id": "ses-real",
                "preview": "真实本地 thread",
                "createdAt": 100,
                "updatedAt": 100,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: None,
    )

    await _send_workspace_thread_overview(
        state,
        MagicMock(),
        GROUP_CHAT_ID,
        ws,
        "claude",
        active_ids={"ses-real"},
    )

    args = send_mock.await_args.args
    kwargs = send_mock.await_args.kwargs
    text = args[2]
    assert "真实本地 thread" in text
    assert "旧 state topic" not in text
    assert "旧 state only" not in text
    reply_markup = kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["📌 真实本地 thread"]


@pytest.mark.asyncio
async def test_open_workspace_uses_provider_workspace_hooks_for_custom_provider(monkeypatch):
    from bot.handlers.workspace import _open_workspace
    from config import ToolConfig

    storage = AppStorage()
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.connected = True
    adapter.register_workspace_cwd = MagicMock()
    adapter.list_threads = AsyncMock(
        return_value=[
            {"id": "noise-1", "preview": "noise", "updatedAt": 1, "kind": "noise"},
            {"id": "main-1", "preview": "main", "updatedAt": 2, "kind": "main"},
        ]
    )
    state.set_adapter("custom", adapter)

    normalized_calls = []
    opened_calls = []

    async def _on_workspace_opened(adapter_obj, path, workspace_id):
        opened_calls.append((adapter_obj, path, workspace_id))

    def _normalize_server_threads(server_threads, *, limit):
        normalized_calls.append((server_threads, limit))
        return [item for item in server_threads if item.get("kind") == "main"]

    monkeypatch.setattr(
        "bot.handlers.workspace.get_provider",
        lambda name: SimpleNamespace(
            workspace_hooks=SimpleNamespace(
                normalize_server_threads=_normalize_server_threads,
                on_workspace_opened=_on_workspace_opened,
            )
        ) if name == "custom" else None,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.query_provider_active_thread_ids",
        lambda tool_name, path: {"main-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_workspace_thread_overview",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage_obj: None,
    )

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=7001))

    ws_info = await _open_workspace(
        bot=bot,
        state=state,
        storage=storage,
        group_chat_id=GROUP_CHAT_ID,
        tool_cfg=ToolConfig(name="custom", enabled=True, codex_bin="custom"),
        name="customWorker",
        path="/tmp/custom",
    )

    assert normalized_calls
    assert opened_calls == [(adapter, "/tmp/custom", "custom:customWorker")]
    assert list(ws_info.threads.keys()) == ["main-1"]
    assert ws_info.threads["main-1"].is_active is True


@pytest.mark.asyncio
async def test_thread_open_uses_latest_codex_title_for_topic_name(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1234567890abcdef"] = ThreadInfo(
        thread_id="tid-1234567890abcdef",
        topic_id=None,
        preview="old cached preview",
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(
        return_value=MagicMock(message_thread_id=4567)
    )
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = "thread_open:codex:onlineWorker:tid-1234567890abcdef"
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": "tid-1234567890abcdef",
                "preview": "latest title from sqlite",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=100: [],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    call_kwargs = bot.create_forum_topic.await_args.kwargs
    assert call_kwargs["name"] == "[codex/onlineWorker] latest title from sqlite"
    assert ws.threads["tid-1234567890abcdef"].preview == "latest title from sqlite"


@pytest.mark.asyncio
async def test_thread_open_renames_existing_topic_when_codex_title_changed(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1234567890abcdef"] = ThreadInfo(
        thread_id="tid-1234567890abcdef",
        topic_id=3235,
        preview="old cached preview",
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock()
    bot.edit_forum_topic = AsyncMock(return_value=True)
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = "thread_open:codex:onlineWorker:tid-1234567890abcdef"
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": "tid-1234567890abcdef",
                "preview": "latest title from sqlite",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=100: [],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_to_group,
    )
    save_storage_mock = MagicMock()
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        save_storage_mock,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_not_called()
    bot.edit_forum_topic.assert_awaited_once()
    call_kwargs = bot.edit_forum_topic.await_args.kwargs
    assert call_kwargs["chat_id"] == GROUP_CHAT_ID
    assert call_kwargs["message_thread_id"] == 3235
    assert call_kwargs["name"] == "[codex/onlineWorker] latest title from sqlite"
    assert ws.threads["tid-1234567890abcdef"].preview == "latest title from sqlite"
    save_storage_mock.assert_called()
    send_to_group.assert_awaited_once()


@pytest.mark.asyncio
async def test_thread_open_existing_claude_topic_without_cursor_sends_history_snapshot(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-phase16"] = ThreadInfo(
        thread_id="ses-phase16",
        topic_id=5457,
        preview="继续 claude phase16",
        archived=False,
        is_active=True,
        source="imported",
    )
    storage.workspaces["claude:ncmplayerengine"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock()
    bot.edit_forum_topic = AsyncMock(return_value=True)

    query = MagicMock()
    query.data = "thread_open:claude:ncmplayerengine:ses-phase16"
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": "ses-phase16",
                "preview": "继续 claude phase16",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._list_provider_local_threads",
        lambda tool_name, path, limit=100: [],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.read_provider_thread_history",
        lambda tool_name, thread_id, limit=50, sessions_dir=None: [
            {"role": "user", "text": "你好么？", "timestamp": 1000},
            {"role": "assistant", "text": "目前还在排查。", "timestamp": 1001},
            {"role": "user", "text": "请只回复 OK", "timestamp": 1002},
            {"role": "assistant", "text": "Not logged in · Please run /login", "timestamp": 1003},
        ],
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_to_group,
    )
    control_panel_mock = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace.send_thread_control_panel",
        control_panel_mock,
    )
    save_storage_mock = MagicMock()
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        save_storage_mock,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_not_called()
    messages = [call.args[2] for call in send_to_group.await_args_list]
    combined = "\n".join(messages)
    assert "当前会话快照" in combined
    assert "👤 你好么？" in combined
    assert "🤖 目前还在排查。" in combined
    assert "👤 请只回复 OK" in combined
    assert "🤖 Not logged in · Please run /login" in combined
    assert ws.threads["ses-phase16"].history_sync_cursor is not None
    control_panel_mock.assert_awaited_once()
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_thread_open_existing_claude_topic_only_syncs_turns_after_cursor(monkeypatch):
    from bot.handlers.workspace import _history_turn_signature

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        topic_id=5454,
        daemon_workspace_id="claude:ncmplayerengine",
    )
    old_turns = [
        {"role": "user", "text": "旧问题", "timestamp": 1000},
        {"role": "assistant", "text": "旧回复", "timestamp": 1001},
    ]
    ws.threads["ses-phase16"] = ThreadInfo(
        thread_id="ses-phase16",
        topic_id=5457,
        preview="继续 claude phase16",
        archived=False,
        is_active=True,
        source="imported",
        history_sync_cursor=_history_turn_signature(old_turns[-1]),
    )
    storage.workspaces["claude:ncmplayerengine"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock()
    bot.edit_forum_topic = AsyncMock(return_value=True)

    query = MagicMock()
    query.data = "thread_open:claude:ncmplayerengine:ses-phase16"
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": "ses-phase16",
                "preview": "继续 claude phase16",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._list_provider_local_threads",
        lambda tool_name, path, limit=100: [],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.read_provider_thread_history",
        lambda tool_name, thread_id, limit=50, sessions_dir=None: old_turns + [
            {"role": "user", "text": "新问题", "timestamp": 1002},
            {"role": "assistant", "text": "新回复", "timestamp": 1003},
        ],
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_to_group,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.send_thread_control_panel",
        AsyncMock(),
    )
    save_storage_mock = MagicMock()
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        save_storage_mock,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_not_called()
    messages = [call.args[2] for call in send_to_group.await_args_list]
    combined = "\n".join(messages)
    assert "同步到 2 条新消息" in combined
    assert "👤 新问题" in combined
    assert "🤖 新回复" in combined
    assert "👤 旧问题" not in combined
    assert "🤖 旧回复" not in combined
    assert ws.threads["ses-phase16"].history_sync_cursor == _history_turn_signature(
        {"role": "assistant", "text": "新回复", "timestamp": 1003}
    )
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_thread_open_customprovider_status_message_avoids_markdown_parse_risk(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        topic_id=3160,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    ws.threads["ses_2ac5d4905ffeIe8iB6Ql0W0uPX"] = ThreadInfo(
        thread_id="ses_2ac5d4905ffeIe8iB6Ql0W0uPX",
        topic_id=None,
        preview="Quick check-in",
        archived=False,
        is_active=True,
    )
    storage.workspaces["customprovider:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4257))

    query = MagicMock()
    query.data = "thread_open:customprovider:onlineWorker:ses_2ac5d4905ffeIe8iB6Ql0W0uP"
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": "ses_2ac5d4905ffeIe8iB6Ql0W0uPX",
                "preview": "Quick check-in",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    send_to_group = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        send_to_group,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    send_to_group.assert_awaited()
    send_args = send_to_group.await_args_list[-1].args
    send_kwargs = send_to_group.await_args_list[-1].kwargs
    assert send_args[2] == "✅ thread Ql0W0uPX 新建 topic id=4257"
    assert "parse_mode" not in send_kwargs


@pytest.mark.asyncio
async def test_thread_open_uses_provider_local_thread_fallback_for_custom_provider(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/tmp/custom",
        tool="custom",
        topic_id=3230,
        daemon_workspace_id="custom:onlineWorker",
    )
    storage.workspaces["custom:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4568))
    bot.send_message = AsyncMock()

    target_tid = "custom-thread-1"
    query = MagicMock()
    query.data = make_thread_open_callback_data("custom:onlineWorker", target_tid)
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=50: [],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.get_provider",
        lambda name: SimpleNamespace(
            workspace_hooks=SimpleNamespace(
                list_local_threads=lambda path, limit=50: [
                    {"id": target_tid, "preview": "custom preview", "updatedAt": 1}
                ]
            )
        ) if name == "custom" else None,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.send_thread_control_panel",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage_obj: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    assert target_tid in ws.threads
    assert ws.threads[target_tid].preview == "custom preview"
    assert ws.threads[target_tid].topic_id == 4568


@pytest.mark.asyncio
async def test_thread_open_uses_unique_payload_for_state_thread_collision(monkeypatch):
    target_tid = "tid-1234567890abcdef1234567890ab-BBBB"
    other_tid = "tid-1234567890abcdef1234567890ab-AAAA"

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads[other_tid] = ThreadInfo(
        thread_id=other_tid,
        topic_id=None,
        preview="other preview",
        archived=False,
        is_active=True,
    )
    ws.threads[target_tid] = ThreadInfo(
        thread_id=target_tid,
        topic_id=None,
        preview="target preview",
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4567))
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = make_thread_open_callback_data("codex:onlineWorker", target_tid)
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {"id": other_tid, "preview": "other preview", "updatedAt": 100},
            {"id": target_tid, "preview": "target preview", "updatedAt": 101},
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.list_codex_session_meta_threads_by_cwd",
        lambda path, limit=100: [],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    assert ws.threads[target_tid].topic_id == 4567
    assert ws.threads[other_tid].topic_id is None


@pytest.mark.asyncio
async def test_thread_open_backfills_codex_jsonl_only_thread(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4567))
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = make_thread_open_callback_data("codex:onlineWorker", "tid-phase15")
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=50: [],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.get_provider",
        lambda name: SimpleNamespace(
            workspace_hooks=SimpleNamespace(
                list_local_threads=lambda path, limit=50: [
                    {
                        "id": "tid-phase15",
                        "preview": "继续处理phase15",
                        "createdAt": 3000,
                        "updatedAt": 3000,
                    },
                ]
            )
        ) if name == "codex" else None,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    call_kwargs = bot.create_forum_topic.await_args.kwargs
    assert call_kwargs["name"] == "[codex/onlineWorker] 继续处理phase15"
    assert ws.threads["tid-phase15"].preview == "继续处理phase15"


@pytest.mark.asyncio
async def test_thread_open_uses_unique_payload_for_sqlite_backfill_collision(monkeypatch):
    target_tid = "ses_2ac5d4905ffeIe8iB6Ql0W0uPX-target"
    other_tid = "ses_2ac5d4905ffeIe8iB6Ql0W0uPX-other"

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        topic_id=3160,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    storage.workspaces["customprovider:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4257))

    query = MagicMock()
    query.data = make_thread_open_callback_data("customprovider:onlineWorker", target_tid)
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {"id": other_tid, "preview": "other session", "updatedAt": 100},
            {"id": target_tid, "preview": "target session", "updatedAt": 101},
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    assert target_tid in ws.threads
    assert ws.threads[target_tid].topic_id == 4257
    assert other_tid not in ws.threads


@pytest.mark.asyncio
async def test_thread_open_backfills_claude_local_session(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=3230,
        daemon_workspace_id="claude:onlineWorker",
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4567))
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = make_thread_open_callback_data("claude:onlineWorker", "ses-phase16")
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=50: [
            {
                "id": "ses-phase16",
                "preview": "继续 claude phase16",
                "createdAt": 3000,
                "updatedAt": 3000,
            },
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    call_kwargs = bot.create_forum_topic.await_args.kwargs
    assert call_kwargs["name"] == "[claude/onlineWorker] 继续 claude phase16"
    assert ws.threads["ses-phase16"].preview == "继续 claude phase16"


@pytest.mark.asyncio
async def test_thread_open_revives_stale_locally_archived_active_thread(monkeypatch):
    target_tid = "tid-revive-1"

    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads[target_tid] = ThreadInfo(
        thread_id=target_tid,
        topic_id=None,
        preview="stale archived preview",
        archived=True,
        is_active=False,
    )
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    handler = make_thread_open_callback_handler(state, GROUP_CHAT_ID)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=4567))
    bot.send_message = AsyncMock()

    query = MagicMock()
    query.data = make_thread_open_callback_data("codex:onlineWorker", target_tid)
    query.answer = AsyncMock()
    query.get_bot.return_value = bot

    update = MagicMock(callback_query=query)
    context = MagicMock()

    monkeypatch.setattr(
        "bot.handlers.workspace.list_provider_threads",
        lambda tool_name, path, limit=100: [
            {
                "id": target_tid,
                "preview": "fresh active preview",
                "updatedAt": 123,
            }
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {target_tid},
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._replay_thread_history",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace._send_to_group",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "bot.handlers.workspace.save_storage",
        lambda storage: None,
    )
    monkeypatch.setattr(
        "bot.handlers.message.save_storage",
        lambda storage: None,
    )

    await handler.callback(update, context)

    bot.create_forum_topic.assert_awaited_once()
    assert ws.threads[target_tid].archived is False
    assert ws.threads[target_tid].is_active is True
    assert ws.threads[target_tid].preview == "fresh active preview"
