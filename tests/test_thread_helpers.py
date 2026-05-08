# tests/test_thread_helpers.py
"""
测试 bot/handlers/thread.py 中的纯逻辑辅助函数：_resolve_workspace。
"""
import pytest
from core.state import AppState
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo
from bot.handlers.thread import _resolve_workspace


def make_state(
    workspaces: dict | None = None,
    active_workspace: str | None = None,
) -> AppState:
    """构建带有 storage 的 AppState fixture。"""
    storage = AppStorage(
        workspaces=workspaces or {},
        active_workspace=active_workspace or "",
    )
    state = AppState(storage=storage)
    return state


class TestResolveWorkspace:
    def test_no_storage_returns_none(self):
        state = AppState(storage=None)
        assert _resolve_workspace(state, src_topic_id=None) is None

    def test_no_topic_id_returns_active_workspace(self):
        ws = WorkspaceInfo(name="proj", path="/proj", topic_id=100)
        state = make_state({"proj": ws}, active_workspace="proj")
        result = _resolve_workspace(state, src_topic_id=None)
        assert result is ws

    def test_no_topic_id_no_active_returns_none(self):
        ws = WorkspaceInfo(name="proj", path="/proj", topic_id=100)
        state = make_state({"proj": ws}, active_workspace="")
        result = _resolve_workspace(state, src_topic_id=None)
        assert result is None

    def test_workspace_topic_returns_that_workspace(self):
        ws_a = WorkspaceInfo(name="a", path="/a", topic_id=101)
        ws_b = WorkspaceInfo(name="b", path="/b", topic_id=202)
        state = make_state({"a": ws_a, "b": ws_b}, active_workspace="b")
        # src_topic_id 匹配 ws_a 的 topic_id
        result = _resolve_workspace(state, src_topic_id=101)
        assert result is ws_a

    def test_thread_topic_returns_parent_workspace(self):
        thread = ThreadInfo(thread_id="tid-001", topic_id=999)
        ws = WorkspaceInfo(name="proj", path="/proj", topic_id=100)
        ws.threads["tid-001"] = thread
        state = make_state({"proj": ws}, active_workspace="proj")
        # src_topic_id 匹配 thread 的 topic_id
        result = _resolve_workspace(state, src_topic_id=999)
        assert result is ws

    def test_unknown_topic_falls_back_to_active_workspace(self):
        ws = WorkspaceInfo(name="proj", path="/proj", topic_id=100)
        state = make_state({"proj": ws}, active_workspace="proj")
        # topic_id=9999 没有任何匹配，回退到 active_workspace
        result = _resolve_workspace(state, src_topic_id=9999)
        assert result is ws

    def test_workspace_topic_takes_priority_over_active(self):
        ws_active = WorkspaceInfo(name="active", path="/active", topic_id=1)
        ws_target = WorkspaceInfo(name="target", path="/target", topic_id=2)
        state = make_state(
            {"active": ws_active, "target": ws_target},
            active_workspace="active",
        )
        # topic_id=2 匹配 ws_target，不应返回 active
        result = _resolve_workspace(state, src_topic_id=2)
        assert result is ws_target

    def test_thread_topic_with_multiple_workspaces(self):
        thread_a = ThreadInfo(thread_id="t-a", topic_id=501)
        thread_b = ThreadInfo(thread_id="t-b", topic_id=502)
        ws_a = WorkspaceInfo(name="a", path="/a", topic_id=100)
        ws_b = WorkspaceInfo(name="b", path="/b", topic_id=200)
        ws_a.threads["t-a"] = thread_a
        ws_b.threads["t-b"] = thread_b
        state = make_state({"a": ws_a, "b": ws_b}, active_workspace="a")
        # 匹配 ws_b 下的 thread
        result = _resolve_workspace(state, src_topic_id=502)
        assert result is ws_b
