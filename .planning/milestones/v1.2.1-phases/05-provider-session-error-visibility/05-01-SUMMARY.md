# Phase 5 Plan 05-01 Summary: Provider Session Async Error Visibility

**Updated:** 2026-05-22
**Status:** Completed; async provider error turns now survive external overlay provider, fallback bridge, and owner bridge read normalization

## Scope Closed

Plan 05-01 fixed the silent Session Browser wait caused by asynchronous provider errors that are accepted by send but fail later during generation:

- External overlay provider storage/runtime layer
  - Reads `message.data` for provider assistant records.
  - Converts assistant records with `data.error` and no text parts into visible assistant error turns.
  - Includes provider/model context when the provider stored `providerID` and `modelID`.
- `core/provider_session_bridge.py`
  - Preserves provider-neutral `displayMode` and `kind` metadata from provider facts.
  - Uses `error` as visible content for `kind=error` turns when normal text/content is empty.
  - Keeps empty non-error assistant placeholders filtered.
- `core/provider_owner_bridge.py`
  - Applies the same normalization in the packaged App owner bridge read path.
  - Keeps the Session Browser path generic and provider-neutral.

## Behavior Now Expected

- An external overlay provider upstream quota/auth/network/runtime error appears as a visible assistant error turn in Session Browser.
- Generic provider reads can surface async failures without a provider-specific React branch.
- Session Browser polling observes a new visible assistant turn and can stop waiting.
- Empty non-error assistant placeholders remain hidden.

## Verification

```text
PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_provider_session_bridge.py::test_read_provider_session_rows_preserves_visible_error_metadata tests/test_provider_owner_bridge.py::test_provider_owner_bridge_preserves_visible_error_metadata
3 passed in 0.09s

External overlay provider storage/runtime checks passed in the source workspace.
8 passed in 0.08s

cd OnlineWorker && PYTHONDONTWRITEBYTECODE=1 pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py
18 passed in 0.09s

cd OnlineWorker/mac-app/src-tauri && cargo test owner_bridge_can_read_provider_session_payload -- --nocapture
1 passed; 166 filtered out
```

## Remaining Boundary

This plan surfaces errors through read normalization. It does not add full provider event streaming or change upstream quota/auth behavior.

## Follow-up: Provider Topic Materialization Isolation

**Updated:** 2026-05-22

The legacy active-thread topic materialization path was also brought under provider policy after the main async-error work:

- `core/providers/topic_policy.py`
  - Centralizes `session_event_hooks.should_materialize_unbound_thread_topic` evaluation.
  - Defaults to allowing materialization for providers without this hook, preserving codex/default provider behavior.
  - Falls back to the provider registry descriptor when runtime config lookup does not return a provider.
- `bot/events.py`
  - Uses the shared helper for streaming `turn/started` topic materialization.
- `core/lifecycle.py`
  - Uses the same helper before `LifecycleManager._ensure_thread_topics()` creates any TG topic for an active unbound thread.

Expected behavior:

- External overlay provider and Claude app sessions with `topic_id=None` remain isolated from automatic TG topic creation.
- codex and providers without this hook keep the existing automatic materialization path.
- Explicit user-driven TG thread open/create flows remain available.

Verification:

```text
pytest tests/test_startup_runtime.py::test_ensure_thread_topics_respects_unbound_topic_policy tests/test_startup_runtime.py::test_ensure_thread_topics_replays_history_via_provider_defaults_for_codex tests/test_startup_runtime.py::test_ensure_thread_topics_revives_stale_archived_active_thread -q
4 passed in 0.90s

pytest tests/test_startup_runtime.py tests/test_events_streaming.py tests/test_workspace_thread_open.py tests/test_provider_facts.py -q
114 passed in 6.04s
```
