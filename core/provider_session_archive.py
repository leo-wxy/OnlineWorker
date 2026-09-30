from core.messages.publishing import publish_session_archived
from core.storage import save_storage


def commit_session_archive(state, workspace, thread, *, source, archive_mode="provider"):
    previous = (thread.archived, thread.is_active, thread.archive_mode)
    thread.archived, thread.is_active, thread.archive_mode = True, False, archive_mode
    try:
        if state.storage is not None:
            save_storage(state.storage)
    except Exception:
        thread.archived, thread.is_active, thread.archive_mode = previous
        raise
    publish_session_archived(
        state, provider_id=workspace.tool,
        workspace_id=workspace.daemon_workspace_id or f"{workspace.tool}:{workspace.path}",
        workspace_path=workspace.path, session_id=thread.thread_id, source=source,
    )
