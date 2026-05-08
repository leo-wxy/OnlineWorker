# storage.py
import json
import os
from dataclasses import dataclass, field
from typing import Optional


STORAGE_PATH = "onlineworker_state.json"


@dataclass
class ThreadInfo:
    """单个 thread/session 的持久化元数据。"""
    thread_id: str
    topic_id: Optional[int] = None
    preview: Optional[str] = None
    archived: bool = False
    streaming_msg_id: Optional[int] = None
    last_tg_user_message_id: Optional[int] = None
    history_sync_cursor: Optional[str] = None
    is_active: bool = False
    source: str = "unknown"


@dataclass
class WorkspaceInfo:
    """单个 workspace 的信息。"""
    name: str
    path: str
    tool: str = ""
    topic_id: Optional[int] = None
    daemon_workspace_id: Optional[str] = None
    threads: dict = field(default_factory=dict)
    _legacy_active_thread_id: Optional[str] = field(default=None, repr=False)


@dataclass
class AppStorage:
    """持久化的应用状态。"""
    workspaces: dict = field(default_factory=dict)
    active_workspace: Optional[str] = None
    global_topic_ids: dict = field(default_factory=dict)


def _thread_info_from_dict(d: dict) -> ThreadInfo:
    return ThreadInfo(
        thread_id=d["thread_id"],
        topic_id=d.get("topic_id"),
        preview=d.get("preview"),
        archived=d.get("archived", False),
        streaming_msg_id=d.get("streaming_msg_id"),
        last_tg_user_message_id=d.get("last_tg_user_message_id"),
        history_sync_cursor=d.get("history_sync_cursor"),
        is_active=d.get("is_active", False),
        source=str(d.get("source") or "unknown"),
    )


def _thread_info_to_dict(t: ThreadInfo) -> dict:
    return {
        "thread_id": t.thread_id,
        "topic_id": t.topic_id,
        "preview": t.preview,
        "archived": t.archived,
        "streaming_msg_id": t.streaming_msg_id,
        "last_tg_user_message_id": t.last_tg_user_message_id,
        "history_sync_cursor": t.history_sync_cursor,
        "is_active": t.is_active,
        "source": t.source,
    }


def _infer_tool_from_storage_key(storage_key: str) -> str:
    prefix, sep, _rest = storage_key.partition(":")
    return prefix if sep and prefix else ""


def _workspace_info_from_dict(storage_key: str, d: dict) -> WorkspaceInfo:
    threads = {
        tid: _thread_info_from_dict(td)
        for tid, td in d.get("threads", {}).items()
    }
    ws = WorkspaceInfo(
        name=d["name"],
        path=d["path"],
        tool=d.get("tool") or _infer_tool_from_storage_key(storage_key),
        topic_id=d.get("topic_id"),
        daemon_workspace_id=d.get("daemon_workspace_id"),
        threads=threads,
    )
    legacy_tid = d.get("active_thread_id")
    if legacy_tid and not threads:
        ws._legacy_active_thread_id = legacy_tid
    return ws


def _workspace_info_to_dict(ws: WorkspaceInfo) -> dict:
    return {
        "name": ws.name,
        "path": ws.path,
        "tool": ws.tool,
        "topic_id": ws.topic_id,
        "daemon_workspace_id": ws.daemon_workspace_id,
        "threads": {
            tid: _thread_info_to_dict(t)
            for tid, t in ws.threads.items()
        },
    }


def load_storage(path: str = STORAGE_PATH) -> AppStorage:
    """从 JSON 文件加载持久化状态，文件不存在时返回空状态。"""
    if path == STORAGE_PATH:
        from config import get_data_dir
        dd = get_data_dir()
        if dd is not None:
            path = os.path.join(dd, STORAGE_PATH)

    if not os.path.exists(path):
        return AppStorage()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    workspaces = {
        name: _workspace_info_from_dict(name, info)
        for name, info in data.get("workspaces", {}).items()
    }
    return AppStorage(
        workspaces=workspaces,
        active_workspace=data.get("active_workspace"),
        global_topic_ids=data.get("global_topic_ids", {}),
    )


def save_storage(storage: AppStorage, path: str = STORAGE_PATH) -> None:
    """将持久化状态写入 JSON 文件（原子写入）。"""
    if path == STORAGE_PATH:
        from config import get_data_dir
        dd = get_data_dir()
        if dd is not None:
            path = os.path.join(dd, STORAGE_PATH)
    data = {
        "workspaces": {
            name: _workspace_info_to_dict(ws)
            for name, ws in storage.workspaces.items()
        },
        "active_workspace": storage.active_workspace,
        "global_topic_ids": storage.global_topic_ids,
    }
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)
