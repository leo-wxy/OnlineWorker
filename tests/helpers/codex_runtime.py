from __future__ import annotations

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo


def make_codex_workspace_state(
    *,
    workspace_id: str = "codex:onlineWorker",
    workspace_name: str = "onlineWorker",
    workspace_path: str = "/Users/wxy/Projects/onlineWorker",
    thread_id: str = "tid-1",
    topic_id: int = 100,
    workspace_topic_id: int = 50,
) -> tuple[AppState, WorkspaceInfo, ThreadInfo]:
    storage = AppStorage()
    workspace = WorkspaceInfo(
        name=workspace_name,
        path=workspace_path,
        tool="codex",
        topic_id=workspace_topic_id,
        daemon_workspace_id=workspace_id,
    )
    thread = ThreadInfo(thread_id=thread_id, topic_id=topic_id, archived=False)
    workspace.threads[thread_id] = thread
    storage.workspaces[workspace_id] = workspace
    return AppState(storage=storage), workspace, thread
