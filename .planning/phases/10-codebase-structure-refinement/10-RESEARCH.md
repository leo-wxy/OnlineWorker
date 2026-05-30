# Phase 10 Research: Codebase Structure Refinement

## Research Question

What structural debt should Phase 10 address first, and how can OnlineWorker refactor oversized modules without changing product behavior?

## Current Architecture Context

OnlineWorker is a packaged macOS desktop app with four active implementation layers:

- React frontend under `mac-app/src/`
- Rust/Tauri host commands under `mac-app/src-tauri/src/commands/`
- Python sidecar and Telegram runtime under `main.py`, `bot/`, and `core/`
- Builtin provider implementations under `plugins/providers/builtin/`

The project already has useful boundaries: provider descriptors, provider hooks, notification router, AI scenarios, session bridge commands, and package-level plugin manifests. The structural issue is that several entrypoint files now combine these boundaries with orchestration, parsing, persistence, UI state, and provider-specific behavior in the same file.

## Size Evidence

Largest Rust/Tauri command files:

```text
2800 mac-app/src-tauri/src/commands/config_provider.rs
2621 mac-app/src-tauri/src/commands/codex.rs
2593 mac-app/src-tauri/src/commands/claude.rs
2136 mac-app/src-tauri/src/commands/dashboard.rs
1423 mac-app/src-tauri/src/commands/command_registry.rs
1411 mac-app/src-tauri/src/commands/provider_sessions.rs
1221 mac-app/src-tauri/src/commands/service.rs
```

Largest Python runtime files:

```text
1785 bot/events.py
1584 plugins/providers/builtin/codex/python/runtime.py
1294 plugins/providers/builtin/claude/python/adapter.py
1240 bot/handlers/workspace.py
1113 bot/handlers/message.py
1048 bot/handlers/thread.py
 958 core/provider_owner_bridge.py
 873 config.py
```

Largest frontend files:

```text
696 mac-app/src/pages/Dashboard.tsx
549 mac-app/src/pages/CommandRegistry.tsx
539 mac-app/src/components/NotificationSettingsPanel.tsx
512 mac-app/src/pages/SetupWizard.tsx
457 mac-app/src/components/ConfigEditor.tsx
426 mac-app/src/components/session-browser/shared.tsx
385 mac-app/src/components/ProviderSettingsPanel.tsx
354 mac-app/src/pages/UsageBrowser.tsx
348 mac-app/src/pages/SessionBrowser.tsx
345 mac-app/src/App.tsx
```

## Structural Findings

### Tauri Command Modules

`mac-app/src-tauri/src/commands/config_provider.rs` mixes provider metadata, notification plugin metadata, AI config document handling, embedded manifest/icon/guide assets, config read/write behavior, and config normalization. It already has one submodule, `config_provider/ai_config_store.rs`, which is a good local precedent for extracting focused helpers.

`mac-app/src-tauri/src/commands/dashboard.rs` mixes provider config snapshot parsing, provider runtime health over Unix sockets, config readiness, CLI discovery, Codex/Claude recent activity readers, dashboard state aggregation, and tests. It imports provider metadata, service state, sqlite, Unix sockets, local overlays, and Claude history helpers in one module.

`mac-app/src-tauri/src/commands/codex.rs` and `claude.rs` each mix local session discovery, history parsing, stream/read models, provider-specific send bridges, and tests. They are provider-specific, but still have multiple internal responsibilities that can be split without changing public Tauri commands.

### Python Bot and Runtime

`bot/events.py` combines streamed event normalization, Telegram message editing, approval/question UI, thread topic materialization, archived-thread repair, notification routing, AI summary invocation, and provider-specific Codex final-reply sync. This file is central and behavior-heavy; it should be split only behind characterization tests.

`bot/handlers/workspace.py` combines workspace listing, provider local/server thread normalization, callback token identity, topic naming, existing-history replay, thread opening, workspace opening, and CLI command callback handling. There are obvious extraction seams for topic naming/callback identity and history replay.

`plugins/providers/builtin/codex/python/runtime.py` combines approval reply mapping, final reply editing, config/default model parsing, app-server runtime control, task interruption, and provider runtime helpers. It is provider-specific, so extraction should prefer internal modules under the same provider package rather than shared `core/` movement.

### Frontend

`Dashboard.tsx`, `CommandRegistry.tsx`, `NotificationSettingsPanel.tsx`, and `SetupWizard.tsx` combine data fetching, derived state, presentation, and command callbacks. The existing `hooks/` and smaller `components/session-browser/` modules show the preferred direction: move data loading and derived state into hooks/utilities while keeping page components focused on layout and interactions.

Session Browser is already partially decomposed (`api.ts`, `archive.tsx`, `presentation.tsx`, `sessionData.ts`, provider chat components). That area should be used as a pattern rather than rewritten first.

## Recommended Phase Shape

Phase 10 should proceed as staged behavior-preserving refactors:

1. Inventory and baseline tests before moving code.
2. Tauri command extraction, starting with modules that already have tests and clear helper seams.
3. Python bot/runtime extraction, starting with pure helpers before async Telegram flows.
4. Frontend page extraction, starting with hooks and derived-state helpers.
5. Provider boundary cleanup only after the above makes repeated patterns visible.

The first implementation plan should not rewrite behavior. It should create a concrete structure-debt inventory, lock the verification matrix, and pick the first safe code extraction slice.

## Verification Anchors

Baseline checks should include:

- `git diff --check`
- `pytest -q tests/test_notifications.py tests/test_events_streaming.py tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py`
- `node --test mac-app/tests/appShell.test.mjs mac-app/tests/sessionArchiveContextMenu.test.mjs mac-app/tests/usageProviders.test.mjs`
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard config_provider provider_sessions --quiet`
- `cd mac-app && ./node_modules/.bin/tsc --noEmit`

Packaged-app verification should be reserved for refactors touching:

- Python sidecar startup
- Tauri service startup/supervision
- owner bridge IPC
- packaged provider/plugin asset loading
- installed app config paths

## Non-Goals

- No broad formatting-only rewrite.
- No public provider contract expansion unless a concrete extraction requires it.
- No behavioral changes to session send/archive, notification delivery, AI summaries, or startup.
- No movement of provider-specific runtime logic into shared `core/` just to reduce file size.
- No deleting legacy compatibility paths without targeted tests and explicit product approval.
