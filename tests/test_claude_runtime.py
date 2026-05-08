from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.claude.python import runtime as claude_runtime


@pytest.mark.asyncio
async def test_prepare_send_detaches_imported_thread_before_tg_write():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        daemon_workspace_id="claude:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="ses-imported",
        topic_id=6968,
        preview="历史导入会话",
        archived=False,
        history_sync_cursor="cursor-imported",
        is_active=True,
        source="imported",
    )
    ws.threads["ses-imported"] = thread_info
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "ses-app-new"})
    adapter.resume_thread = AsyncMock(return_value={})

    should_continue = await claude_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=6968,
        text="你好",
        has_photo=False,
    )

    assert should_continue is True
    adapter.start_thread.assert_awaited_once_with("claude:onlineWorker")
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-app-new")

    assert ws.threads["ses-imported"].thread_id == "ses-imported"
    assert ws.threads["ses-imported"].source == "imported"
    assert ws.threads["ses-imported"].topic_id is None
    assert ws.threads["ses-imported"].history_sync_cursor == "cursor-imported"

    assert ws.threads["ses-app-new"] is thread_info
    assert thread_info.thread_id == "ses-app-new"
    assert thread_info.topic_id == 6968
    assert thread_info.source == "app"
    assert thread_info.history_sync_cursor is None
    assert thread_info.streaming_msg_id is None


@pytest.mark.asyncio
async def test_prepare_send_resumes_app_owned_thread_without_remapping():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        daemon_workspace_id="claude:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="ses-app",
        topic_id=6968,
        preview="App 会话",
        is_active=True,
        source="app",
    )
    ws.threads["ses-app"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "ses-new"})
    adapter.resume_thread = AsyncMock(return_value={})

    should_continue = await claude_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=6968,
        text="继续",
        has_photo=False,
    )

    assert should_continue is True
    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-app")
    assert ws.threads["ses-app"] is thread_info
    assert thread_info.source == "app"


@pytest.mark.asyncio
async def test_prepare_send_detaches_thread_inferred_as_imported(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        daemon_workspace_id="claude:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="ses-unknown",
        topic_id=6968,
        preview="历史会话",
        is_active=True,
        source="unknown",
    )
    ws.threads["ses-unknown"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"thread": {"id": "ses-app-new"}})
    adapter.resume_thread = AsyncMock(return_value={})

    monkeypatch.setattr(
        claude_runtime,
        "infer_claude_thread_source_from_logs",
        lambda thread_id, topic_id: "imported",
    )

    await claude_runtime.prepare_send(
        state,
        adapter,
        ws,
        thread_info,
        update=SimpleNamespace(),
        context=SimpleNamespace(),
        group_chat_id=1,
        src_topic_id=6968,
        text="你好",
        has_photo=False,
    )

    adapter.start_thread.assert_awaited_once_with("claude:onlineWorker")
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-app-new")
    assert ws.threads["ses-unknown"].source == "imported"
    assert ws.threads["ses-unknown"].topic_id is None
    assert ws.threads["ses-app-new"] is thread_info
    assert thread_info.source == "app"
