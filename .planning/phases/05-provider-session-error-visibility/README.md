# Phase 5: Provider Session Error Visibility

## Goal

Make asynchronous provider failures visible in Session Browser instead of leaving the user waiting on a silent background failure.

## Trigger Evidence

- An external overlay provider accepted a Session Browser send and returned quickly.
- The provider then failed during upstream model streaming with an auth/quota error.
- The provider published an async error and returned to idle, but OnlineWorker did not map that event to a visible Session Browser state.
- Generic provider Session Browser polling only detects assistant content changes; an empty assistant placeholder plus an unmapped error leaves the UI in a reply-watch state.

## Scope

- Add a provider-neutral error shape that can be read by Session Browser for overlay/generic providers.
- Map asynchronous provider error events into that shape.
- Preserve user-visible error records in provider session reads.
- Keep provider-specific parsing in provider/plugin layers, not in shared React UI.

## Out of Scope

- Changing upstream provider billing/auth behavior.
- Reworking the whole provider event streaming architecture.
- Adding provider-specific UI branches for a single external provider.
- Killing or cleanup of historical orphan provider processes; that is a separate lifecycle concern.

## Success Criteria

1. An external overlay provider upstream quota/auth/network/runtime failure appears in Session Browser as a visible error state or assistant error turn.
2. Generic provider sends stop waiting once an asynchronous provider error is observed.
3. Existing successful external overlay provider, Claude, and Codex session display behavior remains intact.
4. Tests cover the generic provider normalization path and async error mapping.

## Outcome

- `05-01` completed on 2026-05-22.
- External overlay provider assistant records with `data.error` and no text parts are converted into visible assistant error turns.
- Provider owner bridge and fallback provider session bridge now preserve `displayMode/kind` metadata and surface `kind=error` records that only carry an `error` field.
- Empty non-error assistant placeholders remain filtered.
- Follow-up provider-session isolation completed on 2026-05-22:
  - `core/providers/topic_policy.py` centralizes provider policy for unbound thread topic materialization.
  - Streaming `turn/started` and `LifecycleManager._ensure_thread_topics()` use the same provider hook.
  - External overlay provider and Claude app sessions with no TG topic do not auto-create TG topics; codex keeps the default materialization behavior.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_provider_session_bridge.py::test_read_provider_session_rows_preserves_visible_error_metadata tests/test_provider_owner_bridge.py::test_provider_owner_bridge_preserves_visible_error_metadata`
- External overlay provider storage/runtime checks passed in the source workspace.
- `cd OnlineWorker && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py`
- `cd OnlineWorker/mac-app/src-tauri && cargo test owner_bridge_can_read_provider_session_payload -- --nocapture`
- `pytest tests/test_startup_runtime.py::test_ensure_thread_topics_respects_unbound_topic_policy tests/test_startup_runtime.py::test_ensure_thread_topics_replays_history_via_provider_defaults_for_codex tests/test_startup_runtime.py::test_ensure_thread_topics_revives_stale_archived_active_thread -q` -> passed in source workspace.
- `pytest tests/test_startup_runtime.py tests/test_events_streaming.py tests/test_workspace_thread_open.py tests/test_provider_facts.py -q` -> passed in source workspace.
