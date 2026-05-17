from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.codex.python import runtime as codex_runtime


@pytest.mark.asyncio
async def test_prepare_send_detaches_imported_thread_before_tg_write(monkeypatch):
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
    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "thread-app-new")
    interrupt_mock.assert_awaited_once_with(
        state,
        adapter,
        "codex:onlineWorker",
        "thread-app-new",
        label="codex",
    )

    assert ws.threads["thread-imported"].thread_id == "thread-imported"
    assert ws.threads["thread-imported"].source == "imported"
    assert ws.threads["thread-imported"].topic_id is None
    assert ws.threads["thread-imported"].history_sync_cursor == "cursor-imported"

    assert ws.threads["thread-app-new"] is thread_info
    assert thread_info.thread_id == "thread-app-new"
    assert thread_info.topic_id == 206
    assert thread_info.source == "app"
    assert thread_info.history_sync_cursor is None
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
