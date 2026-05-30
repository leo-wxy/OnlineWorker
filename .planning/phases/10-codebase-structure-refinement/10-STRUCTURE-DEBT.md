# Phase 10 Structure Debt Inventory

**Created:** 2026-05-30
**Scope:** planning-only audit for staged behavior-preserving refactors.

See also: `10-CODEBASE-AUDIT.md` for the full-repository static structure audit, including language/area totals, long function/class scans, boundary findings, and risk register.

## Summary

OnlineWorker's largest structural debt is concentrated in command/runtime files that mix multiple responsibilities behind one module boundary. Size alone is not the deciding factor; priority is based on responsibility count, boundary risk, and available characterization tests.

Recommended order:

1. Rust/Tauri command helper extraction, starting with `config_provider.rs` and `dashboard.rs`.
2. Python bot pure-helper extraction, starting with `bot/handlers/workspace.py`.
3. Frontend hook/presentation extraction, starting with `Dashboard.tsx` after backend dashboard helpers are clearer.
4. High-blast-radius runtime splits, such as `bot/events.py`, only after additional characterization tests.

## Rust/Tauri Candidates

| Order | File | Lines | Responsibilities | Existing anchors | Proposed extraction boundary | Risk |
|---:|---|---:|---|---|---|---|
| 1 | `mac-app/src-tauri/src/commands/config_provider.rs` | 2800 | Provider metadata, notification metadata, AI config documents, embedded assets, config IO, normalization | Rust `config_provider` tests, `ai_config_store.rs` precedent | Extract `config_provider/provider_assets.rs`, `notification_metadata.rs`, and provider config document helpers without changing command names | Medium |
| 2 | `mac-app/src-tauri/src/commands/dashboard.rs` | 2136 | Provider config snapshots, runtime health IPC, config readiness, CLI discovery, recent activity, state aggregation, tests | Rust `dashboard` tests | Extract provider status/health helpers and recent activity readers into sibling modules; keep Tauri command surface stable | Medium |
| 3 | `mac-app/src-tauri/src/commands/provider_sessions.rs` | 1411 | Provider session listing, archive command, local overlays, bridge behavior | Rust `provider_sessions` tests, Node session archive tests | Extract archive/local overlay helpers from command handlers | Medium |
| 4 | `mac-app/src-tauri/src/commands/command_registry.rs` | 1423 | Command discovery, registry rendering model, Telegram aliases, provider command catalog | Command registry tests and app shell tests | Extract command normalization/catalog projection helpers | Medium |
| 5 | `mac-app/src-tauri/src/commands/service.rs` | 1221 | Sidecar process control, service status, lifecycle, restart behavior | Service/startup tests are more integration-heavy | Defer until packaged-app verification window; split only after test map is explicit | High |
| 6 | `mac-app/src-tauri/src/commands/codex.rs` | 2621 | Codex session discovery, JSONL parsing, stream/read models, owner bridge send | Session/browser tests and Codex-specific Rust tests | Defer broad split; first extract pure JSONL parsing if tests are added/confirmed | High |
| 7 | `mac-app/src-tauri/src/commands/claude.rs` | 2593 | Claude project/session discovery, history parsing, provider-specific reads | Claude adapter/storage tests, Rust command tests if present | Defer broad split; extract history path/parser helpers only after characterization | High |

## Python Runtime Candidates

| Order | File | Lines | Responsibilities | Existing anchors | Proposed extraction boundary | Risk |
|---:|---|---:|---|---|---|---|
| 1 | `bot/handlers/workspace.py` | 1240 | Workspace scan/open, topic naming, callback identity, history replay, thread open, CLI callbacks | Workspace/thread tests | Extract pure topic naming, callback token, history batch, and history cursor helpers into `bot/handlers/workspace_helpers.py` | Medium |
| 2 | `bot/handlers/common.py` | 624 | Shared Telegram formatting, status, token usage command, lifecycle controls | Slash/status/notification tests | Extract token usage formatting/range helpers into focused module | Low |
| 3 | `core/provider_owner_bridge.py` | 958 | Owner bridge socket protocol, provider send/list/status/archive handling | Provider owner bridge tests | Extract request parsing/response shaping helpers; leave socket loop intact | Medium |
| 4 | `core/provider_session_bridge.py` | 581 | Sidecar session list/send/archive entrypoint | Provider session bridge tests | Extract archive/send result model helpers only if repeated by owner bridge | Medium |
| 5 | `bot/handlers/message.py` | 1113 | Telegram message dispatch, attachments, provider send, new-thread routing | Handler, attachment, message hook tests | Defer until workspace/common helpers are split; high interaction with send behavior | High |
| 6 | `bot/handlers/thread.py` | 1048 | Thread commands, new thread activation, source state sync | Thread controls tests | Defer until message/workspace extraction gives clearer shared helpers | High |
| 7 | `bot/events.py` | 1785 | Streaming event handling, Telegram edits, approval/question UI, notification routing, AI summary, topic materialization | Events streaming, notification, provider tests | Add more characterization first; later split notification/approval/topic materialization helpers | High |
| 8 | `plugins/providers/builtin/codex/python/runtime.py` | 1584 | Codex runtime controls, final reply editing, approval mapping, model defaults, app-server behavior | Codex runtime/TUI tests | Keep provider-specific; extract approval reply and model default helpers under provider package | High |

## Frontend Candidates

| Order | File | Lines | Responsibilities | Existing anchors | Proposed extraction boundary | Risk |
|---:|---|---:|---|---|---|---|
| 1 | `mac-app/src/pages/Dashboard.tsx` | 696 | Dashboard load state, derived health state, restart/open actions, presentation | `appShell.test.mjs`, dashboard hook precedent | Move data loading/derived status into `hooks/useDashboardState` extensions and smaller dashboard sections | Medium |
| 2 | `mac-app/src/components/NotificationSettingsPanel.tsx` | 539 | Notification channel list, detail editing, validation, guide display | App shell notification tests | Extract config form field rendering and guide panel helpers | Medium |
| 3 | `mac-app/src/pages/CommandRegistry.tsx` | 549 | Registry loading, search/filtering, duplicate detection, rendering | Command registry tests/hooks | Move filter/sort logic into utility functions with tests | Medium |
| 4 | `mac-app/src/pages/SetupWizard.tsx` | 512 | Setup env writes, provider metadata loading, CLI checks, step presentation | App shell/setup tests | Extract setup data hook and step sections | Medium |
| 5 | `mac-app/src/components/ConfigEditor.tsx` | 457 | Raw config editing, validation, save/reload UI | App shell/config tests if present | Defer unless settings refactor touches it | Medium |
| 6 | `mac-app/src/components/session-browser/shared.tsx` | 426 | Shared session UI helpers/components | Session browser tests | Keep stable; session browser is already partly decomposed | Low |

## Verification Matrix

### Rust/Tauri Command Refactors

Use focused tests by touched module:

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet
cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet
cargo test --manifest-path mac-app/src-tauri/Cargo.toml provider_sessions --quiet
```

If a refactor touches service startup, sidecar process control, packaged asset loading, or bridge socket behavior, add packaged-app verification with:

```bash
bash scripts/verify-packaged-fast.sh
```

### Python Runtime Refactors

Use focused behavior checks by touched boundary:

```bash
pytest -q tests/test_events_streaming.py tests/test_notifications.py
pytest -q tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py
pytest -q tests/test_thread_controls.py tests/test_workspace_thread_open.py
pytest -q tests/test_slash_router.py tests/test_command_rules.py
```

If a refactor touches `main.py`, `core/lifecycle.py`, startup hooks, or sidecar packaging, rebuild/verify the installed app.

### Frontend Refactors

Use Node tests and TypeScript checks:

```bash
node --test mac-app/tests/appShell.test.mjs
node --test mac-app/tests/sessionArchiveContextMenu.test.mjs mac-app/tests/usageProviders.test.mjs
cd mac-app && ./node_modules/.bin/tsc --noEmit
```

### Global Guard

Run after every refactor slice:

```bash
git diff --check
node ~/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency
```

## Packaged-App Verification Triggers

Run packaged-app verification when a slice changes:

- `main.py`
- `core/lifecycle.py`
- `mac-app/src-tauri/src/commands/service.rs`
- sidecar process startup/shutdown
- owner bridge socket protocols
- packaged plugin/provider/notification assets
- installed app config/data path behavior

Do not run packaged-app verification for planning-only changes or pure helper extraction with unchanged startup/IPC behavior unless a focused test fails or the user explicitly asks.

## Selected Slices

### 10-02: Extract Tauri Config/Dashboard Helpers

First code-refactor slice. It is lower risk than `bot/events.py` or provider runtime splits because the first extractions can be pure helpers under existing Rust command modules, with stable Tauri command names and existing tests.

Initial files:

- `mac-app/src-tauri/src/commands/config_provider.rs`
- `mac-app/src-tauri/src/commands/config_provider/ai_config_store.rs`
- `mac-app/src-tauri/src/commands/dashboard.rs`
- new sibling modules under `mac-app/src-tauri/src/commands/config_provider/` and `dashboard/` as needed

Required tests:

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet
cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet
git diff --check
```

### 10-03: Extract Python Workspace Pure Helpers

Second slice. Start with pure logic in `bot/handlers/workspace.py`: topic naming, callback token identity, history turn signatures, timestamp normalization, and history batch construction. Avoid Telegram API calls and async topic creation in the first pass.

Initial files:

- `bot/handlers/workspace.py`
- new `bot/handlers/workspace_helpers.py`
- focused tests in existing workspace/thread test files or a new `tests/test_workspace_helpers.py`

Required tests:

```bash
pytest -q tests/test_workspace_thread_open.py tests/test_thread_controls.py
git diff --check
```

### 10-04: Extract Frontend Dashboard State/Presentation

Third slice. Move Dashboard data loading and derived state out of `Dashboard.tsx` only after backend dashboard helper behavior is stable.

Initial files:

- `mac-app/src/pages/Dashboard.tsx`
- `mac-app/src/hooks/useDashboardState.ts`
- potential new `mac-app/src/components/dashboard/*`

Required tests:

```bash
node --test mac-app/tests/appShell.test.mjs
cd mac-app && ./node_modules/.bin/tsc --noEmit
git diff --check
```

## Deferred High-Risk Areas

- `bot/events.py`: central streaming/notification/approval behavior. Needs additional characterization before movement.
- `plugins/providers/builtin/codex/python/runtime.py`: provider-specific runtime behavior. Keep under provider package and split only by internal provider responsibility.
- `mac-app/src-tauri/src/commands/service.rs`: startup and process supervision. Requires packaged-app verification.
