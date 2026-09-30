from types import SimpleNamespace

import pytest

from config import Config, ToolConfig
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from plugins.providers.builtin.codex.python import tui_realtime_mirror as mirror


@pytest.mark.parametrize("ingress", [None, {"trustState": "review_required"},
                                      {"trustState": "verified", "rollout": {"state": "running"}}])
def test_live_ingress_bootstraps_bound_unknown_session_once_without_polling(monkeypatch, ingress):
    ws = WorkspaceInfo(name="sample", path="/tmp/sample-workspace", tool="codex",
                       daemon_workspace_id="codex:/tmp/sample-workspace")
    ws.threads["sample-session"] = ThreadInfo(thread_id="sample-session", source="unknown", is_active=True)
    config = Config(telegram_token="sample-token", allowed_user_id=1234567890,
                    group_chat_id=1234567890, log_level="INFO",
                    tools=[ToolConfig(name="codex", bin="codex", enabled=True,
                                      protocol="unix", control_mode="app", live_transport="shared_unix")])
    state = AppState(storage=AppStorage(workspaces={"sample": ws}), config=config)
    if ingress is not None:
        state.set_adapter("codex", SimpleNamespace(external_event_status=ingress))
    reads = []
    def history(*args, **kwargs):
        reads.append(args)
        return [{"role": "user", "text": "question"},
                {"role": "assistant", "text": "reply", "phase": "final_answer"}]
    monkeypatch.setattr(mirror, "read_thread_history", history)
    assert mirror._ensure_bound_codex_thread_watches(state)
    activity = state.message_bus.session_activity("codex", "sample-session")
    assert activity["status"] == "completed"
    assert [turn["content"] for turn in activity["conversationTurns"]] == ["question", "reply"]
    assert not codex_state.get_runtime(state).watched_threads
    assert not mirror._ensure_bound_codex_thread_watches(state)
    assert len(reads) == 1
