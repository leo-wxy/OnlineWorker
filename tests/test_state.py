from unittest.mock import MagicMock
from types import SimpleNamespace

from core.providers.registry import get_provider
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, WorkspaceInfo


def test_get_adapter_for_workspace_routes_claude_prefix():
    state = AppState()
    claude_adapter = MagicMock()
    state.set_adapter("claude", claude_adapter)

    assert state.get_adapter_for_workspace("claude:onlineWorker") is claude_adapter


def test_get_adapter_for_workspace_prefers_storage_workspace_tool():
    state = AppState(storage=AppStorage())
    customprovider_adapter = MagicMock()
    state.set_adapter("customprovider", customprovider_adapter)
    state.storage.workspaces["workspace-1"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        daemon_workspace_id="customprovider:onlineWorker",
    )

    assert state.get_adapter_for_workspace("workspace-1") is customprovider_adapter


def test_get_adapter_for_workspace_does_not_silently_fallback_unknown_prefix_to_codex():
    state = AppState()
    codex_adapter = MagicMock()
    state.set_adapter("codex", codex_adapter)

    assert state.get_adapter_for_workspace("unknown:onlineWorker") is None


def test_get_adapter_for_workspace_uses_provider_thread_hook_for_custom_prefix(monkeypatch):
    state = AppState(storage=AppStorage())
    custom_adapter = MagicMock()
    state.storage.workspaces["custom:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="custom",
        daemon_workspace_id="custom:onlineWorker",
    )

    monkeypatch.setattr(
        "core.state.get_provider",
        lambda name: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                resolve_adapter=lambda state, ws: custom_adapter,
            )
        ) if name == "custom" else None,
    )

    assert state.get_adapter_for_workspace("custom:onlineWorker") is custom_adapter


def test_get_adapter_for_workspace_uses_codex_thread_hook_fallback(monkeypatch):
    state = AppState()
    codex_primary = MagicMock()
    codex_primary.connected = False
    codex_fallback = MagicMock()
    codex_fallback.connected = True
    state.set_adapter("codex", codex_primary)
    state.set_adapter("codex", codex_fallback)

    monkeypatch.setattr(
        "core.state.get_provider",
        lambda name: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                resolve_adapter=lambda state, ws: codex_fallback,
            )
        ) if name == "codex" else None,
    )

    assert state.get_adapter_for_workspace("codex:onlineWorker") is codex_fallback


def test_registry_exposes_model_wrapper_capability_for_codex_only():
    codex = get_provider("codex")
    customprovider = get_provider("customprovider")

    assert codex is not None
    assert customprovider is None
    assert "model" in getattr(codex.capabilities, "command_wrappers", ())


def test_start_codex_run_creates_current_run_state():
    state = AppState()

    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    assert run.run_id == "turn-123"
    assert run.thread_id == "tid-123"
    assert run.workspace_id == "codex:onlineWorker"
    assert run.status == "started"
    assert codex_state.get_current_run(state, "tid-123") is run
    assert run.last_visible_event_seq >= 1


def test_start_codex_run_consumes_pending_send_started_at():
    state = AppState()
    send_started_at = codex_state.mark_send_started(state, "tid-123")

    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    assert run.send_started_at == send_started_at
    assert "tid-123" not in codex_state.get_runtime(state).thread_pending_send_started_at


def test_codex_run_tracks_interruptions_and_resolution():
    state = AppState()
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    interruption = codex_state.add_interruption(state,
        thread_id="tid-123",
        interruption_id="req-1",
    )

    assert interruption is not None
    assert interruption.run_id == run.run_id
    assert "req-1" in run.active_interruption_ids

    codex_state.resolve_interruption(state, "req-1", status="resolved", tg_message_id=5001)

    assert "req-1" not in run.active_interruption_ids
    assert codex_state.get_runtime(state).interruptions["req-1"].status == "resolved"
    assert codex_state.get_runtime(state).interruptions["req-1"].tg_message_id == 5001


def test_mark_codex_run_synced_updates_current_run():
    state = AppState()
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    codex_state.mark_run(state,
        thread_id="tid-123",
        status="completed",
        final_reply_synced_to_tg=True,
    )

    assert run.status == "completed"
    assert run.final_reply_synced_to_tg is True


def test_mark_codex_run_synced_without_status_records_final_reply_time():
    state = AppState()
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    codex_state.mark_run(state,
        thread_id="tid-123",
        final_reply_synced_to_tg=True,
    )

    assert run.final_reply_synced_to_tg is True
    assert run.final_reply_at >= run.created_at
    assert run.tg_synced_at >= run.final_reply_at


def test_codex_run_records_minimal_trace_timestamps():
    state = AppState()
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    assert run.bridge_accepted_at >= run.created_at

    codex_state.mark_run(state, thread_id="tid-123", first_progress_at=True)
    first_progress_at = run.first_progress_at
    first_progress_seq = run.last_visible_event_seq
    assert first_progress_at >= run.created_at

    codex_state.mark_run(state, thread_id="tid-123", first_progress_at=True)
    assert run.first_progress_at == first_progress_at
    assert run.last_visible_event_seq == first_progress_seq

    codex_state.add_interruption(state, thread_id="tid-123", interruption_id="req-1")
    assert run.approval_requested_at >= run.created_at

    codex_state.resolve_interruption(state, "req-1", status="resolved", tg_message_id=5001)
    assert run.approval_resolved_at >= run.approval_requested_at

    codex_state.mark_run(state,
        thread_id="tid-123",
        status="completed",
        final_reply_synced_to_tg=True,
    )
    assert run.final_reply_at >= run.created_at
    assert run.tg_synced_at >= run.final_reply_at


def test_codex_run_emits_structured_trace_logs(caplog):
    state = AppState()

    with caplog.at_level("INFO", logger="core.state"):
        codex_state.mark_send_started(state, "tid-123")
        codex_state.start_run(state,
            workspace_id="codex:onlineWorker",
            thread_id="tid-123",
            turn_id="turn-123",
        )
        codex_state.mark_run(state,
            thread_id="tid-123",
            status="completed",
            final_reply_synced_to_tg=True,
        )

    text = caplog.text
    assert "codex-run event=started" in text
    assert "codex-run event=updated" in text
    assert "run_id=turn-123" in text
    assert "thread_id=tid-123" in text
    assert "workspace_id=codex:onlineWorker" in text


def test_provider_runtime_state_isolated_by_tool_name():
    state = AppState()

    codex_run = state.start_provider_run(
        "codex",
        workspace_id="codex:onlineWorker",
        thread_id="tid-codex",
        turn_id="turn-codex",
    )
    claude_run = state.start_provider_run(
        "claude",
        workspace_id="claude:onlineWorker",
        thread_id="tid-claude",
        turn_id="turn-claude",
    )

    state.mark_provider_run("codex", thread_id="tid-codex", status="completed", final_reply_synced_to_tg=True)
    state.mark_provider_run("claude", thread_id="tid-claude", status="completed", final_reply_synced_to_tg=True)

    assert state.get_provider_current_run("codex", "tid-codex") is codex_run
    assert state.get_provider_current_run("claude", "tid-claude") is claude_run
    assert codex_run.final_reply_synced_to_tg is True
    assert claude_run.final_reply_synced_to_tg is True
    assert codex_run.workspace_id == "codex:onlineWorker"
    assert claude_run.workspace_id == "claude:onlineWorker"
    assert state.get_provider_current_run("codex", "tid-claude") is None
    assert state.get_provider_current_run("claude", "tid-codex") is None
