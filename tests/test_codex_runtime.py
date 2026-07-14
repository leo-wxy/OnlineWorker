from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState, PendingApproval
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.codex.python import runtime as codex_runtime


@pytest.mark.asyncio
async def test_setup_connection_does_not_start_codex_hook_bridge(tmp_path, monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        data_dir=str(tmp_path),
    )
    state = AppState(config=cfg, storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage
    manager.gid = 2

    adapter = MagicMock()
    adapter.configure_hook_bridge = MagicMock()
    adapter.start_hook_bridge = AsyncMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter._thread_workspace_map = {}

    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started",
        AsyncMock(),
    )

    await codex_runtime.setup_connection(manager, MagicMock(), adapter)

    adapter.configure_hook_bridge.assert_not_called()
    adapter.start_hook_bridge.assert_not_awaited()
    adapter.register_workspace_cwd.assert_called_once_with(
        "codex:onlineWorker",
        "/Users/example/Projects/onlineWorker",
    )


@pytest.mark.asyncio
async def test_setup_connection_backfills_live_thread_mapping(tmp_path, monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-live"] = ThreadInfo(
        thread_id="tid-live",
        preview="live preview",
        archived=False,
        is_active=True,
        source="app",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[ToolConfig(name="codex", enabled=True, bin="codex")],
        data_dir=str(tmp_path),
    )
    state = AppState(config=cfg, storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage
    manager.gid = 2

    adapter = MagicMock()
    adapter.configure_hook_bridge = MagicMock()
    adapter.start_hook_bridge = AsyncMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter.list_threads = AsyncMock(
        return_value=[
            {
                "id": "tid-live",
                "preview": "live preview",
                "source": "app",
                "updatedAt": 123,
            }
        ]
    )
    adapter._thread_workspace_map = {}

    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started",
        AsyncMock(),
    )

    await codex_runtime.setup_connection(manager, MagicMock(), adapter)

    adapter.list_threads.assert_awaited_once_with("codex:onlineWorker", limit=50)
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_codex_setup_connection_wraps_handlers_for_approval_sync(tmp_path, monkeypatch):
    storage = AppStorage()
    storage.workspaces["codex:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[ToolConfig(name="codex", enabled=True, bin="codex")],
        data_dir=str(tmp_path),
    )
    state = AppState(config=cfg, storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage
    manager.gid = 2

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter._thread_workspace_map = {}

    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started",
        AsyncMock(),
    )

    await codex_runtime.setup_connection(manager, MagicMock(), adapter)

    assert adapter.on_event.call_count == 1
    assert adapter.on_server_request.call_count == 1


@pytest.mark.asyncio
async def test_setup_connection_auto_continues_capacity_abort_once(tmp_path, monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        preview="live preview",
        archived=False,
        is_active=True,
        source="app",
    )
    storage.workspaces["codex:onlineWorker"] = ws
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[ToolConfig(name="codex", enabled=True, bin="codex")],
        data_dir=str(tmp_path),
    )
    state = AppState(config=cfg, storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage
    manager.gid = 2

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    adapter._thread_workspace_map = {}

    event_handler = AsyncMock()
    monkeypatch.setattr("bot.events.make_event_handler", lambda *_args: event_handler)
    monkeypatch.setattr("bot.events.make_server_request_handler", lambda *_args: AsyncMock())
    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started",
        AsyncMock(),
    )

    await codex_runtime.setup_connection(manager, MagicMock(), adapter)

    callback = adapter.on_event.call_args.args[0]
    capacity_event = {
        "workspace_id": "codex:onlineWorker",
        "message": {
            "method": "turn/completed",
            "params": {
                "threadId": "tid-123",
                "turn": {
                    "id": "turn-1",
                    "status": "aborted",
                    "reason": "Selected model is at capacity. Please try a different model.",
                },
            },
        },
    }

    await callback("app-server-event", capacity_event)
    await callback("app-server-event", capacity_event)

    event_handler.assert_awaited()
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-123")
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "tid-123",
        "继续",
        approvals_reviewer="user",
    )
    runtime = state.get_provider_runtime("codex")
    assert runtime.thread_capacity_auto_continue_attempts["tid-123"] == 1


@pytest.mark.asyncio
async def test_setup_connection_ignores_non_capacity_abort(tmp_path, monkeypatch):
    storage = AppStorage()
    storage.workspaces["codex:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[ToolConfig(name="codex", enabled=True, bin="codex")],
        data_dir=str(tmp_path),
    )
    state = AppState(config=cfg, storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage
    manager.gid = 2

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    adapter._thread_workspace_map = {}

    event_handler = AsyncMock()
    monkeypatch.setattr("bot.events.make_event_handler", lambda *_args: event_handler)
    monkeypatch.setattr("bot.events.make_server_request_handler", lambda *_args: AsyncMock())
    monkeypatch.setattr(codex_runtime, "prime_thread_mappings", AsyncMock())
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.owner_bridge.ensure_codex_owner_bridge_started",
        AsyncMock(),
    )

    await codex_runtime.setup_connection(manager, MagicMock(), adapter)

    callback = adapter.on_event.call_args.args[0]
    await callback(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {
                        "id": "turn-1",
                        "status": "aborted",
                        "reason": "interrupted",
                    },
                },
            },
        },
    )

    event_handler.assert_awaited_once()
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_app_server_resolved_clears_tg_pending_approval():
    state = AppState()
    state.pending_approvals[88] = PendingApproval(
        request_id="approval-1",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        cmd="touch /tmp/demo",
        justification="need permission",
        tool_type="codex",
        approval_source="item/commandExecution/requestApproval",
    )
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    cleared = await codex_runtime.handle_codex_app_server_resolution_event(
        state,
        bot,
        123,
        "app-server-event",
        {
            "message": {
                "method": "serverRequest/resolved",
                "params": {
                    "threadId": "tid-123",
                    "requestId": "approval-1",
                },
            },
        },
    )

    assert cleared == 1
    assert state.pending_approvals == {}
    bot.edit_message_text.assert_awaited_once()
    assert bot.edit_message_text.await_args.kwargs["chat_id"] == 123
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 88
    assert "已由 Codex 端处理或清理" in bot.edit_message_text.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_codex_app_server_resolved_ignores_non_codex_pending_approval():
    state = AppState()
    state.pending_approvals[88] = PendingApproval(
        request_id="approval-1",
        workspace_id="claude:proj",
        thread_id="ses-123",
        cmd="touch /tmp/demo",
        justification="need permission",
        tool_type="claude",
        approval_source="item/commandExecution/requestApproval",
    )
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    cleared = await codex_runtime.mark_codex_app_server_approval_resolved(
        state,
        bot,
        123,
        request_id="approval-1",
        thread_id="tid-123",
    )

    assert cleared == 0
    assert 88 in state.pending_approvals
    bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_server_request_handler_skips_duplicate_tg_approval():
    state = AppState()
    state.pending_approvals[88] = PendingApproval(
        request_id="approval-1",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        cmd="touch /tmp/demo",
        justification="need permission",
        tool_type="codex",
        approval_source="item/commandExecution/requestApproval",
    )
    fallback = AsyncMock()
    handler = codex_runtime.make_codex_server_request_handler(state, fallback)

    await handler(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-123", "command": "touch /tmp/demo"},
        "approval-1",
    )

    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_server_request_handler_skips_remote_proxy_duplicate_approval():
    state = AppState()
    state.pending_approvals[88] = PendingApproval(
        request_id="codex_remote_proxy:client-1:7",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        cmd="touch /tmp/demo",
        justification="need permission",
        tool_type="codex",
        approval_source="codex_remote_proxy",
    )
    fallback = AsyncMock()
    handler = codex_runtime.make_codex_server_request_handler(state, fallback)

    await handler(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-123", "command": "touch /tmp/demo"},
        7,
    )

    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_server_request_handler_allows_remote_proxy_suffix_collision():
    state = AppState()
    state.pending_approvals[88] = PendingApproval(
        request_id="codex_remote_proxy:client-1:7",
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        cmd="touch /tmp/demo",
        justification="need permission",
        tool_type="codex",
        approval_source="codex_remote_proxy",
    )
    fallback = AsyncMock()
    handler = codex_runtime.make_codex_server_request_handler(state, fallback)

    await handler(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-other", "command": "touch /tmp/demo"},
        7,
    )

    fallback.assert_awaited_once_with(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-other", "command": "touch /tmp/demo"},
        7,
    )


@pytest.mark.asyncio
async def test_codex_server_request_handler_allows_new_request():
    state = AppState()
    fallback = AsyncMock()
    handler = codex_runtime.make_codex_server_request_handler(state, fallback)

    await handler(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-123", "command": "touch /tmp/demo"},
        "approval-1",
    )

    fallback.assert_awaited_once_with(
        "item/commandExecution/requestApproval",
        {"threadId": "tid-123", "command": "touch /tmp/demo"},
        "approval-1",
    )


@pytest.mark.asyncio
async def test_prepare_send_does_not_resume_imported_thread_before_send(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="thread-imported",
        topic_id=206,
        preview="历史导入会话",
        archived=False,
        history_sync_cursor="cursor-imported",
        is_active=True,
        source="imported",
    )
    ws.threads["thread-imported"] = thread_info
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "thread-app-new"})
    adapter.resume_thread = AsyncMock(return_value={})

    interrupt_mock = AsyncMock()
    monkeypatch.setattr(codex_runtime, "_interrupt_active_turn", interrupt_mock)

    should_continue = await codex_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=206,
        text="今天是几号？",
        has_photo=False,
    )

    assert should_continue is True
    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_not_awaited()
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-imported",
        label="codex",
    )

    assert set(ws.threads) == {"thread-imported"}
    assert ws.threads["thread-imported"] is thread_info
    assert thread_info.thread_id == "thread-imported"
    assert thread_info.topic_id == 206
    assert thread_info.source == "imported"
    assert thread_info.history_sync_cursor == "cursor-imported"
    assert thread_info.streaming_msg_id is None


@pytest.mark.asyncio
async def test_send_message_watches_codex_transcript_after_tg_send(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="thread-imported",
        topic_id=206,
        preview="历史导入会话",
        archived=False,
        is_active=True,
        source="imported",
    )
    ws.threads["thread-imported"] = thread_info
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.send_user_message = AsyncMock(return_value={})
    seeded = []
    watched = []

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.seed_codex_watch_baseline",
        lambda state_arg, ws_arg, thread_id_arg: seeded.append((state_arg, ws_arg, thread_id_arg)),
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.watch_codex_thread",
        lambda state_arg, ws_arg, thread_id_arg: watched.append((state_arg, ws_arg, thread_id_arg)),
    )

    await codex_runtime.send_message(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=206,
        text="今天是几号？",
        has_photo=False,
    )

    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "thread-imported",
        "今天是几号？",
    )
    assert seeded == [(state, ws, "thread-imported")]
    assert watched == [(state, ws, "thread-imported")]


@pytest.mark.asyncio
async def test_activate_new_thread_watches_codex_transcript(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="new-thread-1",
        topic_id=206,
        preview="Explain this project",
        archived=False,
        is_active=True,
        source="app",
    )
    ws.threads["new-thread-1"] = thread_info
    storage.workspaces["codex:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.send_user_message = AsyncMock(return_value={})
    seeded = []
    watched = []

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.seed_codex_watch_baseline",
        lambda state_arg, ws_arg, thread_id_arg: seeded.append((state_arg, ws_arg, thread_id_arg)),
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.watch_codex_thread",
        lambda state_arg, ws_arg, thread_id_arg: watched.append((state_arg, ws_arg, thread_id_arg)),
    )

    await codex_runtime.activate_new_thread(
        state,
        adapter,
        ws,
        "codex:onlineWorker",
        "new-thread-1",
        "Explain this project",
    )

    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "new-thread-1",
        "Explain this project",
    )
    assert seeded == [(state, ws, "new-thread-1")]
    assert watched == [(state, ws, "new-thread-1")]


@pytest.mark.asyncio
async def test_prepare_send_reuses_app_thread_when_app_server_resume_succeeds(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="thread-app",
        topic_id=206,
        preview="App 会话",
        archived=False,
        is_active=True,
        source="app",
    )
    ws.threads["thread-app"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "thread-should-not-happen"})
    adapter.resume_thread = AsyncMock(return_value={})

    interrupt_mock = AsyncMock()
    monkeypatch.setattr(codex_runtime, "_interrupt_active_turn", interrupt_mock)
    monkeypatch.setattr(codex_runtime, "_codex_thread_has_source_record", lambda workspace_path, thread_id: True)

    should_continue = await codex_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=206,
        text="继续",
        has_photo=False,
    )

    assert should_continue is True
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "thread-app")
    adapter.start_thread.assert_not_awaited()
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-app",
        label="codex",
    )
    assert ws.threads["thread-app"] is thread_info
    assert thread_info.source == "app"


@pytest.mark.asyncio
async def test_prepare_send_materializes_app_thread_when_resume_reports_not_found(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="thread-app-stale",
        topic_id=206,
        preview="App 会话",
        archived=False,
        is_active=True,
        source="app",
    )
    ws.threads["thread-app-stale"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "thread-real"})
    adapter.resume_thread = AsyncMock(
        side_effect=RuntimeError("thread not found: thread-app-stale")
    )

    interrupt_mock = AsyncMock()
    monkeypatch.setattr(codex_runtime, "_interrupt_active_turn", interrupt_mock)
    monkeypatch.setattr(
        codex_runtime,
        "_codex_thread_has_source_record",
        lambda workspace_path, thread_id: True,
    )

    should_continue = await codex_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=206,
        text="继续",
        has_photo=False,
    )

    assert should_continue is True
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "thread-app-stale")
    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    assert set(ws.threads) == {"thread-real"}
    assert ws.threads["thread-real"] is thread_info
    assert thread_info.thread_id == "thread-real"
    assert thread_info.source == "app"
    assert thread_info.is_active is True
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-real",
        label="codex",
    )


@pytest.mark.asyncio
async def test_prepare_send_materializes_state_only_app_thread(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="app:codex:draft",
        topic_id=None,
        preview="新建会话",
        archived=False,
        is_active=False,
        source="app",
    )
    ws.threads["app:codex:draft"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "thread-real"})
    adapter.resume_thread = AsyncMock(
        side_effect=RuntimeError("thread not found: app:codex:draft")
    )

    interrupt_mock = AsyncMock()
    monkeypatch.setattr(codex_runtime, "_interrupt_active_turn", interrupt_mock)
    monkeypatch.setattr(
        codex_runtime,
        "_codex_thread_has_source_record",
        lambda workspace_path, thread_id: False,
    )

    should_continue = await codex_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=None,
        text="第一条消息",
        has_photo=False,
    )

    assert should_continue is True
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "app:codex:draft")
    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    assert set(ws.threads) == {"thread-real"}
    assert ws.threads["thread-real"] is thread_info
    assert thread_info.thread_id == "thread-real"
    assert thread_info.source == "app"
    assert thread_info.is_active is True
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-real",
        label="codex",
    )


@pytest.mark.asyncio
async def test_sync_existing_codex_topics_after_startup_repairs_active_threads(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineworker-workspace",
        path="/Users/example/Projects/onlineworker-workspace",
        tool="codex",
        daemon_workspace_id="codex:onlineworker-workspace",
    )
    ws.threads["tid-imported"] = ThreadInfo(
        thread_id="tid-imported",
        topic_id=206,
        preview="继续查 codex 通知",
        archived=True,
        is_active=False,
        source="imported",
    )
    storage.workspaces[ws.daemon_workspace_id] = ws
    state = AppState(storage=storage)
    manager = MagicMock()
    manager.state = state
    manager.storage = storage

    bootstrap_mock = MagicMock(return_value=True)
    saved = []

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.runtime.storage_runtime.query_codex_active_thread_ids",
        lambda workspace_path: {"tid-imported"},
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.bootstrap_bound_codex_thread_activity",
        bootstrap_mock,
    )
    monkeypatch.setattr(
        "core.storage.save_storage",
        lambda storage_obj: saved.append(storage_obj),
    )

    await codex_runtime.sync_existing_topics_after_startup(manager, MagicMock())

    assert ws.threads["tid-imported"].archived is False
    assert ws.threads["tid-imported"].is_active is True
    bootstrap_mock.assert_called_once_with(state)
    assert saved == [storage]
