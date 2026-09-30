from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo, load_storage, save_storage
from core.provider_owner_bridge import ProviderOwnerBridge
from core.provider_session_archive import commit_session_archive
from bot.handlers.common import clear_stale_thread_archive_if_active


def session_state():
    thread = ThreadInfo(thread_id="sample-session", source="unknown", is_active=True)
    ws = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="codex",
                       daemon_workspace_id="codex:/tmp/sample-workspace", threads={thread.thread_id: thread})
    return AppState(storage=AppStorage(workspaces={ws.daemon_workspace_id: ws})), ws, thread


@pytest.mark.asyncio
async def test_unsupported_archive_is_persisted_by_owner_and_survives_next_save(monkeypatch, tmp_path):
    state, ws, thread = session_state()
    archive = AsyncMock(side_effect=RuntimeError("Provider does not expose a real source archive operation"))
    state.set_adapter("codex", SimpleNamespace(connected=True))
    monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *args: SimpleNamespace(thread_hooks=SimpleNamespace(archive_thread=archive)))
    path = tmp_path / "state.json"
    monkeypatch.setattr("core.provider_session_archive.save_storage", lambda storage: save_storage(storage, str(path)))
    result = await ProviderOwnerBridge(state, data_dir=str(tmp_path))._handle_archive_session({
        "provider_id": "codex", "session_id": thread.thread_id,
        "workspace_dir": ws.path, "allow_local_overlay": True,
    })
    assert result["ok"] and result["archive_mode"] == "local_overlay"
    save_storage(state.storage, str(path))
    restored = load_storage(str(path)).workspaces[ws.daemon_workspace_id].threads[thread.thread_id]
    assert restored.archived and not restored.is_active
    assert restored.source == "unknown" and restored.archive_mode == "local_overlay"
    assert not clear_stale_thread_archive_if_active(state, ws, thread, active_ids={thread.thread_id})
    assert state.message_bus.recent_events()[-1]["kind"] == "session.archived"


def test_archive_save_failure_restores_exact_previous_flags(monkeypatch):
    state, ws, thread = session_state()
    thread.is_active = False
    def fail(*args):
        raise OSError("sample write failed")
    monkeypatch.setattr("core.provider_session_archive.save_storage", fail)
    with pytest.raises(OSError):
        commit_session_archive(state, ws, thread, source="sample", archive_mode="local_overlay")
    assert not thread.archived and not thread.is_active and thread.archive_mode == ""
    assert not state.message_bus.recent_events()
