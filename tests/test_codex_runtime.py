from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.codex.python import runtime as codex_runtime


@pytest.mark.asyncio
async def test_start_runtime_cleans_existing_onlineworker_permission_hook(monkeypatch, tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        '{"hooks":{"PermissionRequest":[{"matcher":"","hooks":[{"type":"command","command":"onlineworker-bot --codex-hook-bridge","timeout":86400}]}]}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        codex_runtime,
        "cleanup_onlineworker_codex_permission_hooks",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(codex_runtime, "resolve_connection_target", AsyncMock(return_value="ws://127.0.0.1:4722"))
    monkeypatch.setattr(codex_runtime, "connect_adapter_with_retry", AsyncMock())
    monkeypatch.setattr(codex_runtime, "clear_stale_host_artifacts", MagicMock(return_value=False))

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        data_dir=str(tmp_path),
    )
    manager = MagicMock()
    manager.state = AppState(config=cfg)
    manager.gid = 2
    manager.get_tui_sync_task.return_value = None
    manager.get_tui_mirror_task.return_value = None

    await codex_runtime.start_runtime(manager, MagicMock(), cfg.tools[0])

    codex_runtime.cleanup_onlineworker_codex_permission_hooks.assert_called_once_with()


@pytest.mark.asyncio
async def test_prepare_send_resumes_imported_thread_without_remapping(monkeypatch):
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
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "thread-imported")
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
async def test_prepare_send_resumes_app_owned_thread_without_remapping(monkeypatch):
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
    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "thread-app")
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-app",
        label="codex",
    )
    assert ws.threads["thread-app"] is thread_info
    assert thread_info.source == "app"
