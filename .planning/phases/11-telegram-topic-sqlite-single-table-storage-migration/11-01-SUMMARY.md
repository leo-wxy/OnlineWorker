# 11-01 Summary: IM Route SQLite Storage Migration

**Date:** 2026-06-03
**Status:** completed
**Mode:** source implementation and regression hardening

## Completed

- Added a generic one-table IM route store in `core/im_routes.py`.
- Stores Telegram topic bindings as external IM entries mapped to fixed
  OnlineWorker route scopes:
  - `agent`
  - `workspace`
  - `session`
  - `unknown`
- Migrates existing Telegram JSON topic mirrors from:
  - `global_topic_ids`
  - workspace `topic_id`
  - thread/session `topic_id`
- Runs JSON migration once per Telegram account/space, then treats SQLite as
  the route truth source.
- Stops serializing Telegram topic route fields back into
  `onlineworker_state.json`; legacy JSON values are migration input only.
- Wires startup migration before Telegram handlers are registered.
- Routes topic lookups through SQLite when a route store is configured:
  - global agent topic lookup
  - workspace topic lookup
  - thread/session topic lookup
  - active workspace topic lookup helpers
- Adds route writes for created agent/workspace/session topics.
- Records unknown Telegram topics without routing them to the active workspace
  when SQLite routing is configured.
- Soft-marks routes as `archived` for business archive cleanup and `invalid`
  for stale/missing/replaced Telegram topics without physically deleting route
  rows.
- Preserves legacy JSON fallback behavior only when no SQLite route store is
  configured.

## Post-Close Regression Fix

**Date:** 2026-06-04

- Closed a post-close gap where some business code still treated
  `ThreadInfo.topic_id` / `WorkspaceInfo.topic_id` as the route truth source
  after JSON topic fields stopped being serialized.
- Re-routed TG thread list icons, Claude workspace thread reconciliation, and
  Codex TUI host send metadata through `AppState.get_thread_topic_id(...)` so
  a restarted process with `topic_id=None` in `onlineworker_state.json` still
  resolves active bindings from `im_routes.sqlite3`.
- Added route-aware regressions for:
  - `/list` showing `✅` when JSON mirrors are missing but SQLite session routes
    exist.
  - Claude reconcile keeping a stale local thread with an active SQLite route
    instead of pruning it as an unbound JSON-only remnant.
  - Codex owner-bridge/TUI-host sends passing the route-store topic id after the
    in-memory JSON mirror is cleared.
  - A static guard preventing handler/provider business code from reintroducing
    direct legacy topic mirror reads.

## Files Changed

- `core/im_routes.py`
- `core/state.py`
- `main.py`
- `core/lifecycle.py`
- `bot/handlers/thread.py`
- `bot/handlers/workspace.py`
- `bot/handlers/slash.py`
- `bot/handlers/message.py`
- `bot/events.py`
- `bot/thread_controls.py`
- `bot/interaction_specs.py`
- `plugins/providers/builtin/claude/python/runtime.py`
- `plugins/providers/builtin/codex/python/runtime.py`
- `plugins/providers/builtin/codex/python/remote_proxy.py`
- `plugins/providers/builtin/codex/python/tui_bridge.py`
- `plugins/providers/builtin/codex/python/tui_realtime_mirror.py`
- `plugins/providers/builtin/codex/python/tui_host_runtime.py`
- `tests/test_im_route_store.py`
- `tests/test_storage.py`
- `tests/test_thread_helpers.py`
- `tests/test_thread_controls.py`

## Behavior

- `im_routes.sqlite3` is now the only persistent Telegram topic route store
  once configured.
- `onlineworker_state.json` no longer writes `global_topic_ids`, workspace
  `topic_id`, or thread/session `topic_id`.
- Existing JSON topic ids are imported only when no non-unknown SQLite routes
  exist for the Telegram account/space. Later startups do not let stale JSON
  values reactivate archived/invalid routes.
- Unknown, archived, or invalid Telegram topics fail closed for message routing when
  SQLite routing is configured.
- Global agent topics still resolve command context and can use the active
  workspace for commands such as `/workspace`, `/new`, and `/list`.
- Topic archive, cleanup, rollback, and stale-topic rebuild paths update route
  status instead of deleting route history.

## Verification

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q \
  tests/test_im_route_store.py \
  tests/test_storage.py \
  tests/test_thread_controls.py \
  tests/test_events.py \
  tests/test_events_streaming.py \
  tests/test_workspace_thread_open.py \
  tests/test_thread_helpers.py \
  tests/test_handlers.py \
  tests/test_slash_router.py \
  tests/test_workspace_helpers.py \
  tests/test_startup_runtime.py \
  tests/test_claude_runtime.py \
  tests/test_codex_runtime.py \
  tests/test_codex_tui_mode.py \
  tests/test_provider_owner_bridge.py
```

Result: `354 passed`.

Post-close regression verification:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q \
  tests/test_topic_route_access.py \
  tests/test_im_route_store.py \
  tests/test_thread_controls.py \
  tests/test_handlers.py \
  tests/test_codex_tui_mode.py
```

Result: `123 passed`.

```bash
git diff --check
```

Result: passed.

## Packaged-App Verification

Not run in this turn. The combined repository instructions require explicit
current-conversation permission before build, packaging, install, restart, or
packaged-app verification.

## Phase 11 Status

Phase 11 source implementation and regression coverage are complete. Installed
packaged-app verification remains available as a separate user-approved step.
