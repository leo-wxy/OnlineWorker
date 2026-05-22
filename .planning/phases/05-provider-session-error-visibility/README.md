# Phase 5: Provider Session Error Visibility

## Goal

Make asynchronous provider failures visible in Session Browser instead of leaving the user waiting on a silent background failure.

## Trigger Evidence

- codemaker accepted a Session Browser send and returned from `prompt_async` quickly.
- codemaker then failed during upstream model streaming with `403 insufficient_quota`.
- codemaker published `session.error` and returned to idle, but OnlineWorker did not map that event to a visible Session Browser state.
- Generic provider Session Browser polling only detects assistant content changes; an empty assistant placeholder plus an unmapped error leaves the UI in a reply-watch state.

## Scope

- Add a provider-neutral error shape that can be read by Session Browser for overlay/generic providers.
- Map codemaker asynchronous `session.error` events into that shape.
- Preserve user-visible error records in provider session reads.
- Keep provider-specific parsing in provider/plugin layers, not in shared React UI.

## Out of Scope

- Changing upstream provider billing/auth behavior.
- Reworking the whole provider event streaming architecture.
- Adding provider-specific UI branches for codemaker only.
- Killing or cleanup of historical orphan provider processes; that is a separate lifecycle concern.

## Success Criteria

1. A codemaker upstream quota/auth/network/runtime failure appears in Session Browser as a visible error state or assistant error turn.
2. Generic provider sends stop waiting once an asynchronous provider error is observed.
3. Existing successful codemaker, Claude, and Codex session display behavior remains intact.
4. Tests cover the generic provider normalization path and codemaker `session.error` mapping.

## Outcome

- `05-01` completed on 2026-05-22.
- codemaker assistant records with `data.error` and no text parts are converted into visible assistant error turns.
- Provider owner bridge and fallback provider session bridge now preserve `displayMode/kind` metadata and surface `kind=error` records that only carry an `error` field.
- Empty non-error assistant placeholders remain filtered.
- Follow-up provider-session isolation completed on 2026-05-22:
  - `core/providers/topic_policy.py` centralizes provider policy for unbound thread topic materialization.
  - Streaming `turn/started` and `LifecycleManager._ensure_thread_topics()` use the same provider hook.
  - codemaker and Claude app sessions with no TG topic do not auto-create TG topics; codex keeps the default materialization behavior.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=OnlineWorker:. pytest -q tests/test_codemaker_storage_runtime.py::test_read_codemaker_thread_history_surfaces_assistant_error OnlineWorker/tests/test_provider_session_bridge.py::test_read_provider_session_rows_preserves_visible_error_metadata OnlineWorker/tests/test_provider_owner_bridge.py::test_provider_owner_bridge_preserves_visible_error_metadata`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=OnlineWorker:. pytest -q tests/test_codemaker_storage_runtime.py tests/test_codemaker_attachments.py tests/test_codemaker_plugin_manifest.py`
- `cd OnlineWorker && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py`
- `cd OnlineWorker/mac-app/src-tauri && cargo test owner_bridge_can_read_provider_session_payload -- --nocapture`
- `PYTHONPATH=/Users/wxy/Projects/onlineworker-combined/OnlineWorker:/Users/wxy/Projects/onlineworker-combined pytest OnlineWorker/tests/test_startup_runtime.py::test_ensure_thread_topics_respects_unbound_topic_policy OnlineWorker/tests/test_startup_runtime.py::test_ensure_thread_topics_replays_history_via_provider_defaults_for_codex OnlineWorker/tests/test_startup_runtime.py::test_ensure_thread_topics_revives_stale_archived_active_thread -q` -> `4 passed in 0.90s`
- `PYTHONPATH=/Users/wxy/Projects/onlineworker-combined/OnlineWorker:/Users/wxy/Projects/onlineworker-combined pytest OnlineWorker/tests/test_startup_runtime.py OnlineWorker/tests/test_events_streaming.py OnlineWorker/tests/test_workspace_thread_open.py OnlineWorker/tests/test_provider_facts.py -q` -> `114 passed in 6.04s`
- `PYTHONPATH=/Users/wxy/Projects/onlineworker-combined/OnlineWorker:/Users/wxy/Projects/onlineworker-combined pytest tests/test_codemaker_attachments.py tests/test_codemaker_plugin_manifest.py tests/test_codemaker_storage_runtime.py -q` -> `10 passed in 0.05s`
