from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.claude.python import runtime as claude_runtime


@pytest.mark.asyncio
async def test_prepare_send_resumes_imported_thread_without_remapping():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
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
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
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
    adapter.start_thread.assert_not_awaited()
    adapter.inspect_thread_activity.assert_awaited_once_with("ses-imported")
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-imported")

    assert set(ws.threads) == {"ses-imported"}
    assert ws.threads["ses-imported"] is thread_info
    assert thread_info.thread_id == "ses-imported"
    assert thread_info.topic_id == 6968
    assert thread_info.source == "imported"
    assert thread_info.history_sync_cursor == "cursor-imported"
    assert thread_info.streaming_msg_id is None


@pytest.mark.asyncio
async def test_prepare_send_resumes_app_owned_thread_without_remapping():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
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
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
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
    adapter.inspect_thread_activity.assert_awaited_once_with("ses-app")
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-app")
    assert ws.threads["ses-app"] is thread_info
    assert thread_info.source == "app"


@pytest.mark.asyncio
async def test_prepare_send_keeps_thread_inferred_as_imported(monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
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
    adapter.inspect_thread_activity = AsyncMock(return_value={"busy": False})
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

    adapter.start_thread.assert_not_awaited()
    adapter.inspect_thread_activity.assert_awaited_once_with("ses-unknown")
    adapter.resume_thread.assert_awaited_once_with("claude:onlineWorker", "ses-unknown")
    assert set(ws.threads) == {"ses-unknown"}
    assert ws.threads["ses-unknown"] is thread_info
    assert ws.threads["ses-unknown"].source == "imported"
    assert ws.threads["ses-unknown"].topic_id == 6968
    assert thread_info.thread_id == "ses-unknown"


@pytest.mark.asyncio
async def test_prepare_send_rejects_external_busy_claude_thread():
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="claude",
        daemon_workspace_id="claude:onlineWorker",
    )
    thread_info = ThreadInfo(
        thread_id="ses-busy",
        topic_id=6968,
        preview="正在终端执行",
        is_active=True,
        source="imported",
    )
    ws.threads["ses-busy"] = thread_info
    state = AppState(storage=AppStorage())

    adapter = MagicMock()
    adapter.start_thread = AsyncMock(return_value={"id": "ses-new"})
    adapter.inspect_thread_activity = AsyncMock(
        return_value={
            "busy": True,
            "message": "当前 Claude session 正在本地终端执行，请等待结束或显式 fork。",
        }
    )
    adapter.resume_thread = AsyncMock(return_value={})

    with pytest.raises(RuntimeError, match="正在本地终端执行"):
        await claude_runtime.prepare_send(
            state,
            adapter,
            ws,
            thread_info,
            update=SimpleNamespace(),
            context=SimpleNamespace(),
            group_chat_id=1,
            src_topic_id=6968,
            text="不要抢终端",
            has_photo=False,
        )

    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_not_awaited()
