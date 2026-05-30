# Phase 10 Complete Codebase Structure Audit

**Date:** 2026-05-30
**Scope:** full-repository static structure audit for refactor planning.
**Mode:** no production code changes.

## Audit Boundary

This is a structural audit, not a line-by-line functional bug review. It covers the full repository source surface by static evidence:

- file count and line count by language/area
- largest source and test files
- largest Python classes/functions
- largest Rust functions/items
- largest React/TypeScript components/functions
- cross-layer imports and command boundaries
- provider-specific branching and hardcoded app assumptions
- available test anchors for refactor slices

It does not claim that every implementation branch was manually reviewed for behavioral bugs. Follow-up code-review passes should be scoped to changed files during each refactor slice.

## Repository Size Snapshot

Source files:

| Group | Files | Lines |
|---|---:|---:|
| Python source | 108 | 27,333 |
| Rust source | 24 | 18,491 |
| TypeScript/TSX source | 64 | 10,840 |
| JavaScript/MJS source | 19 | 1,649 |
| Python tests | 62 | 29,293 |
| Node tests | 22 | 1,988 |

Area lines:

| Area | Files | Lines |
|---|---:|---:|
| `tests/` | 62 | 29,293 |
| `plugins/` | 40 | 11,082 |
| `mac-app/src/` | 79 | 11,909 |
| `mac-app/src-tauri/` | 24 | 18,491 |
| `bot/` | 16 | 7,413 |
| `core/` | 42 | 6,040 |
| `scripts/` | 9 | 2,026 |

The repository has meaningful test volume, but the largest production modules are concentrated around runtime orchestration, provider/session handling, and Tauri command surfaces.

## Largest Source Files

| Rank | File | Lines | Assessment |
|---:|---|---:|---|
| 1 | `mac-app/src-tauri/src/commands/config_provider.rs` | 2800 | P1. Too many config/metadata/asset responsibilities in one command module. |
| 2 | `mac-app/src-tauri/src/commands/codex.rs` | 2621 | P2. Provider-specific and large; split later because behavior is protocol-sensitive. |
| 3 | `mac-app/src-tauri/src/commands/claude.rs` | 2593 | P2. Provider-specific and large; split later with storage/history tests. |
| 4 | `mac-app/src-tauri/src/commands/dashboard.rs` | 2136 | P1. Dashboard status, provider config, IPC health, activity readers, and tests are mixed. |
| 5 | `bot/events.py` | 1785 | P1. High-blast-radius event hub; needs characterization before movement. |
| 6 | `plugins/providers/builtin/codex/python/runtime.py` | 1584 | P2. Provider-specific runtime hub; keep inside provider package when splitting. |
| 7 | `mac-app/src-tauri/src/commands/command_registry.rs` | 1423 | P2. Registry/catalog projection can be split after config/dashboard. |
| 8 | `mac-app/src-tauri/src/commands/provider_sessions.rs` | 1411 | P2. Session/archive bridge behavior is important but has tests. |
| 9 | `plugins/providers/builtin/claude/python/adapter.py` | 1294 | P2. Provider-specific adapter complexity. |
| 10 | `bot/handlers/workspace.py` | 1240 | P1. Good candidate for pure-helper extraction. |
| 11 | `mac-app/src-tauri/src/commands/service.rs` | 1221 | P1/P0 if touched. Startup/process supervision requires packaged-app validation. |
| 12 | `bot/handlers/message.py` | 1113 | P2. Message send path is high behavior risk. |
| 13 | `bot/handlers/thread.py` | 1048 | P2. Thread/new-session behavior is coupled with workspace state. |
| 14 | `core/provider_owner_bridge.py` | 958 | P1. Owner bridge protocol is central; split only behind bridge tests. |
| 15 | `config.py` | 873 | P1. Config parsing/backfill/overlay/default provider behavior is dense. |

## Longest Python Units

| Unit | Lines | Risk | Notes |
|---|---:|---|---|
| `bot/events.py::make_event_handler` | 1069 | P1 | Combines event dispatch, streaming, notifications, AI summary, topic materialization, and provider-specific sync. |
| `plugins/providers/builtin/codex/python/adapter.py::CodexAdapter` | 768 | P2 | Provider implementation; split internally, not into shared core. |
| `plugins/providers/builtin/claude/python/adapter.py::ClaudeAdapter` | 749 | P2 | Provider implementation with high external CLI coupling. |
| `core/provider_owner_bridge.py::ProviderOwnerBridge` | 661 | P1 | Protocol/request handlers should be separated from socket loop. |
| `core/lifecycle.py::LifecycleManager` | 497 | P1 | Startup/reconnect/topic/provider lifecycle is high blast radius. |
| `core/state.py::AppState` | 473 | P1 | Runtime state object mixes adapter registry, topic lookup, run ledger, and pending interactions. |
| `bot/handlers/message.py::make_callback_handler` | 471 | P2 | Telegram callback routing is broad and behavior-sensitive. |
| `bot/handlers/workspace.py::make_thread_open_callback_handler` | 286 | P1 | Thread-open callback has pure helper seams. |
| `main.py::main` | 237 | P1 | Entrypoint mixes one-shot modes and bot startup; touch only with tests. |

## Longest Rust Units

| Unit | Lines | Risk | Notes |
|---|---:|---|---|
| `codex.rs::parse_codex_stream_events` | 152 | P2 | Protocol parser; needs fixture tests before split. |
| `codex.rs::list_codex_threads_filters_subagent_rows` | 145 | P2 | Large test, indicates important behavior. |
| `claude.rs::list_claude_sessions_from_paths_keeps_meaningful_cli_sessions_and_skips_noise` | 134 | P2 | Large behavior test; preserve as anchor. |
| `command_catalog.rs::bot_commands` | 132 | P2 | Catalog projection can be isolated later. |
| `lib.rs::run` | 131 | P1 | App startup, do not refactor without packaged-app validation. |
| `dashboard.rs::resolve_builtin_provider_snapshots` | 120 | P1 | Strong candidate for provider-status helper extraction. |
| `provider_sessions.rs::persist_provider_session_archived_state` | 117 | P2 | Archive persistence is behavior-sensitive but tested. |
| `codex.rs::list_codex_threads_from_paths` | 114 | P2 | Provider parser surface. |
| `dashboard.rs::read_claude_workspace_activity` | 87 | P1 | Recent activity reader can move behind dashboard helper module. |

## Longest Frontend Units

| Unit | Lines | Risk | Notes |
|---|---:|---|---|
| `SetupWizard.tsx::SetupWizard` | 474 | P2 | Setup workflow state and presentation are mixed. |
| `CommandRegistry.tsx::CommandRegistryView` | 387 | P2 | Search/filter/projection/presentation should be split. |
| `NotificationSettingsPanel.tsx::NotificationSettingsPanel` | 355 | P2 | Config form and guide rendering are mixed. |
| `Dashboard.tsx::Dashboard` | 348 | P1 | First frontend candidate after dashboard backend helpers. |
| `ProviderSettingsPanel.tsx::ProviderSettingsPanel` | 324 | P2 | Provider flags/config/hook UI in one component. |
| `SessionBrowser.tsx::SessionBrowser` | 311 | P2 | Already partly decomposed; avoid first. |
| `UsageBrowser.tsx::UsageBrowser` | 311 | P2 | Usage query/render can be split later. |
| `CodexChat.tsx::CodexChat` | 290 | P2 | Provider chat behavior; defer until session browser plan. |

## Boundary Findings

### P1: Dashboard Command Is a Cross-Layer Accumulator

`dashboard.rs` imports Claude session helpers, config provider metadata, service status, session overlays, sqlite, Unix sockets, and dashboard types. It handles:

- provider default/config snapshots
- owner bridge runtime status IPC
- service and Telegram health aggregation
- Codex/Claude recent activity readers
- app dashboard response construction
- many internal tests

This is a good first backend refactor target because several responsibilities are pure or command-local, and the public Tauri command can remain unchanged.

### P1: Config Provider Command Owns Too Much Product Metadata

`config_provider.rs` handles:

- provider plugin manifests/icons
- notification plugin manifests/icons/guides
- AI config documents and metadata
- provider config defaults/backfills
- config display normalization
- command-facing setters

The existing `config_provider/ai_config_store.rs` proves submodules under the command are acceptable. The next split should follow that pattern.

### P1: Python Event Hub Is Too Central to Move First

`bot/events.py::make_event_handler` is over 1000 lines and touches streaming replies, final-reply formatting, notifications, AI summary, approvals/questions, topic materialization, archived-thread repair, and Codex-specific final sync. It is a real structural problem, but not the safest first refactor. It needs additional characterization around duplicate reply prevention and notification rules before moving behavior.

### P1: Core Runtime Depends Back Into Bot UI

There are intentional but risky imports from core/runtime paths back into bot presentation:

- `core/lifecycle.py` imports `bot.handlers.common`, `bot.handlers.workspace`, and `bot.utils`
- `core/provider_owner_bridge.py` imports `bot.events` for approval delivery
- Codex provider runtime imports `bot.handlers.common`, `bot.handlers.thread`, `bot.events`, and `bot.handlers.message`

This creates a partial inversion of the intended layering. It is not automatically wrong because Telegram is the current primary control plane, but future refactors should avoid adding more bot imports from `core/` or provider runtime modules.

### P1: Provider-Specific Branches Still Exist at Host Edges

Provider boundaries are improved, but host edges still branch on `codex` and `claude` in places such as:

- `config.py` default provider blueprints and transport defaults
- `dashboard.rs` provider snapshots and recent activity readers
- `provider_sessions.rs` direct imports from `codex` and `claude`
- frontend `SessionBrowser.tsx` provider-specific list loading
- frontend dashboard action `open_codex_tui_host_terminal`

Some branches are legitimate builtin-provider handling. The risk is letting new provider-specific behavior spread into shared UI/host surfaces instead of metadata/hooks.

### P2: Frontend Pages Mix Fetching, Derived State, Actions, and Presentation

Several React pages/components are now large enough that testable logic is hidden inside UI components. The project already has `hooks/`, `utils/`, and decomposed session-browser modules. Use those patterns before creating new abstractions.

## Test Coverage Map

Strong anchors already exist:

- Startup/process: `tests/test_startup_runtime.py`, `tests/test_main.py`, `tests/test_packaging_socks_support.py`
- Provider registry/boundary: `tests/test_provider_facts.py`, `tests/test_provider_runtime_boundary.py`, `tests/test_provider_owner_bridge.py`, `tests/test_provider_session_bridge.py`
- Event streaming/notifications: `tests/test_events_streaming.py`, `tests/test_notifications.py`
- Workspace/thread flows: `tests/test_workspace_thread_open.py`, `tests/test_thread_controls.py`, `tests/test_handlers.py`, `tests/test_slash_router.py`
- Codex runtime/TUI: `tests/test_codex_*`, `mac-app/tests/codexSessionStream.test.mjs`
- Claude runtime/storage: `tests/test_claude_*`, `tests/test_storage_claude.py`
- Frontend shell/session/usage: `mac-app/tests/appShell.test.mjs`, `sessionArchiveContextMenu.test.mjs`, `usageProviders.test.mjs`, `dashboardProviderStatus.test.mjs`
- Rust command modules: embedded tests in `dashboard.rs`, `config_provider.rs`, `provider_sessions.rs`, `provider_usage.rs`, `codex.rs`, `claude.rs`

Gaps:

- Structural dependency rules are not enforced automatically.
- Large frontend component decomposition is mostly protected by shell-level tests, not per-component tests.
- Packaged-app verification remains procedural and should be used when startup/IPC/asset paths move.

## Risk Register

### P0: Do Not Move Without Packaged-App Verification

- `main.py`
- `core/lifecycle.py`
- `mac-app/src-tauri/src/lib.rs`
- `mac-app/src-tauri/src/commands/service.rs`
- packaged provider/notification asset includes
- owner bridge socket protocol behavior

These areas can pass source tests but fail in installed app context.

### P1: Fix During Phase 10

- Split `config_provider.rs` into command-local helper modules.
- Split `dashboard.rs` provider status and recent activity helpers.
- Extract pure helpers from `bot/handlers/workspace.py`.
- Add characterization before splitting `bot/events.py`.
- Stop adding new bot dependencies from `core/` and provider runtime modules.

### P2: Plan After First Slices

- Split provider-specific Codex/Claude Rust session parsers.
- Split provider runtime adapter classes internally.
- Extract frontend page hooks/components for Dashboard, Command Registry, Notification Settings, and Setup Wizard.
- Consider lightweight dependency-boundary checks in CI/test suite.

## Recommended Execution Order

1. `10-02`: Extract Tauri config/dashboard helpers.
2. `10-03`: Extract Python workspace pure helpers.
3. `10-04`: Add event hub characterization and split notification/approval/topic helpers.
4. `10-05`: Extract frontend Dashboard and settings page hooks/components.
5. `10-06`: Add boundary guard tests for provider/core/bot/mac-app layering.

This order avoids touching startup, sidecar process management, and streaming event behavior before the lower-risk extraction paths are proven.

## Verification Strategy

Use focused checks for each slice:

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider dashboard --quiet
pytest -q tests/test_workspace_thread_open.py tests/test_thread_controls.py tests/test_events_streaming.py tests/test_notifications.py
node --test mac-app/tests/appShell.test.mjs mac-app/tests/dashboardProviderStatus.test.mjs
cd mac-app && ./node_modules/.bin/tsc --noEmit
git diff --check
```

Use packaged-app verification when a slice touches startup, sidecar process control, owner bridge IPC, bundled assets in a way source tests cannot prove, or installed app data paths.

## Audit Commands Used

- `find ... -name '*.py' -o -name '*.rs' -o -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.mjs'`
- `wc -l` over source and test files
- Python `ast` scan for class/function line spans
- simple JS/TS brace scan for exported functions/components
- simple Rust item span scan
- `rg` scans for provider-specific branches, cross-layer imports, Tauri commands, and frontend `invoke` calls

## Conclusion

The codebase has adequate test anchors for staged refactoring, but the largest modules are doing too much. The safest path is not a broad rewrite. Phase 10 should start with command-local helper extraction in Tauri, then pure Python helper extraction, then frontend hook/component extraction, while deferring event hub and startup refactors until characterization is stronger.
