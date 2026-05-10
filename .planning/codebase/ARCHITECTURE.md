# Architecture

**Analysis Date:** 2026-05-10

## Pattern Overview

**Overall:** Desktop workbench with a Python runtime core, Rust/Tauri host shell, React control surface, and plugin-style provider runtime boundary.

**Key Characteristics:**
- Installed macOS app is the primary product surface, not a web app
- Python sidecar owns Telegram orchestration, provider lifecycle, and persistent app state
- Rust/Tauri acts as local process host and native bridge for the frontend
- Provider-specific behavior is intentionally pushed behind shared registry/contract layers
- Remote interaction is event-driven through Telegram topics, approvals, questions, and session replay

## Layers

**Desktop Shell Layer:**
- Purpose: Package, launch, supervise, and expose native commands to the UI
- Contains: Tauri commands, menubar integration, service lifecycle control
- Depends on: Rust/Tauri runtime, local files, packaged sidecar binaries
- Used by: React frontend and installed-app runtime
- Key files:
  - `mac-app/src-tauri/src/lib.rs`
  - `mac-app/src-tauri/src/commands/service.rs`
  - `mac-app/src-tauri/src/commands/telegram.rs`

**Frontend Control Layer:**
- Purpose: Human-facing control plane for setup, sessions, commands, logs, and provider configuration
- Contains: React pages, config editors, session browser, setup wizard, i18n, event listeners
- Depends on: Tauri `invoke` commands and local event streams
- Used by: Desktop end user
- Key files:
  - `mac-app/src/App.tsx`
  - `mac-app/src/pages/`
  - `mac-app/src/components/`

**Python Application Layer:**
- Purpose: Telegram bot bootstrap, handler registration, single-instance protection, runtime assembly
- Contains: `main.py`, config loading, app state, storage, lifecycle manager
- Depends on: Telegram API, provider registry, local storage/config
- Used by: Tauri sidecar host and source-mode development runs
- Key files:
  - `main.py`
  - `config.py`
  - `core/state.py`
  - `core/lifecycle.py`
  - `core/storage.py`

**Interaction / Routing Layer:**
- Purpose: Route Telegram commands, callback queries, workspace/thread actions, and streaming turn updates
- Contains: `bot/handlers/*`, slash router, event replay/formatting, keyboard/filter utilities
- Depends on: `AppState`, provider hooks, Telegram transport
- Used by: Python application layer during update handling
- Key files:
  - `bot/handlers/common.py`
  - `bot/handlers/workspace.py`
  - `bot/handlers/thread.py`
  - `bot/handlers/message.py`
  - `bot/events.py`

**Provider Abstraction Layer:**
- Purpose: Keep shared app surfaces provider-neutral while allowing builtin and overlay providers to expose runtime hooks
- Contains: provider contracts, registry, classification, overlay loading, facts/runtime/session event hook boundaries
- Depends on: provider manifests, Python module entrypoints, runtime-specific implementations
- Used by: Python lifecycle/message handling and Tauri provider-session surfaces
- Key files:
  - `core/providers/contracts.py`
  - `core/providers/registry.py`
  - `core/providers/overlay.py`
  - `plugins/providers/catalog.py`

**Provider Runtime Implementation Layer:**
- Purpose: Concrete codex/claude behavior for sessions, approvals, questions, workspaces, owner bridges, TUI/app-server flows
- Contains: builtin provider plugin manifests and runtime modules
- Depends on: specific external CLI tools and their session/thread semantics
- Used by: Provider abstraction layer
- Key files:
  - `plugins/providers/builtin/codex/`
  - `plugins/providers/builtin/claude/`

## Data Flow

**Installed App Startup:**
1. User launches `OnlineWorker.app`
2. Tauri initializes plugins, window state, invoke handlers, and service guard loop in `mac-app/src-tauri/src/lib.rs`
3. Service command layer starts or supervises the Python sidecar binary
4. Python `main.py` resolves `--data-dir`, loads config/env/storage, builds `AppState`, and registers Telegram handlers
5. `LifecycleManager.post_init()` creates/validates Telegram topics and autostarts enabled providers

**Telegram Task Flow:**
1. User sends Telegram command/message into the configured forum/group
2. Telegram update enters handler chain in `main.py`
3. Slash router or message handler resolves workspace/thread/provider context
4. Provider hooks prepare/send work to the external CLI/runtime
5. Streaming/provider events flow back through `bot/events.py`
6. Final state, approvals, and session metadata are persisted and surfaced back to Telegram and the app

**Desktop Session Flow:**
1. React UI calls a Tauri command via `invoke`
2. Rust command reads provider session/thread data or service state
3. Rust either answers directly from local state/files or bridges to provider-specific readers
4. Session snapshots/streams render in the React session browser

**State Management:**
- In-memory runtime state: `AppState` in `core/state.py`
- Persistent Python metadata: `AppStorage` via `core/storage.py`
- Installed-app config/env lives in Application Support
- Frontend state is local React state, refreshed by Tauri commands/events

## Key Abstractions

**ProviderDescriptor:**
- Purpose: Single provider contract describing facts, message hooks, lifecycle hooks, workspace/thread hooks, runtime hooks, and metadata
- Examples: builtin codex and claude descriptors loaded through plugin entrypoints
- Pattern: plugin registry + descriptor factory

**LifecycleManager:**
- Purpose: Centralizes startup, reconnect, cleanup, and provider runtime hook dispatch
- Examples: topic initialization, provider startup, archived-thread cleanup
- Pattern: application orchestrator/service manager

**AppState / AppStorage:**
- Purpose: Split runtime-only state from persistent state
- Examples:
  - pending approvals/questions/wrappers and active adapters in `AppState`
  - workspaces/threads/global topics in `AppStorage`
- Pattern: in-memory state + JSON persistence boundary

## Entry Points

**Python Sidecar Entry:**
- Location: `main.py`
- Triggers: source-mode `python main.py`, packaged sidecar launch, hook-bridge one-shot modes
- Responsibilities: parse args, load config, set logging, assemble app, run Telegram application

**Desktop App Entry:**
- Location: `mac-app/src-tauri/src/main.rs` -> `mac-app/src-tauri/src/lib.rs`
- Triggers: launching `OnlineWorker.app`
- Responsibilities: build Tauri app, register invoke commands, manage native lifecycle

**Frontend Entry:**
- Location: `mac-app/src/App.tsx`
- Triggers: Tauri webview load
- Responsibilities: render app tabs, first-run flow, setup/session/dashboard surfaces

## Error Handling

**Strategy:** Fail local operations loudly at boundaries, keep multi-provider startup tolerant, and prefer partial availability over total process abort during runtime orchestration.

**Patterns:**
- Python startup wraps provider startup tasks independently so one provider failing does not abort others (`core/lifecycle.py`)
- Telegram raw update and PTB application errors are logged centrally in `main.py`
- Tauri command failures are surfaced per command instead of collapsing the whole app
- Build/packaging scripts use `set -euo pipefail` for fail-fast behavior

## Cross-Cutting Concerns

**Logging:**
- Python rotating file + stdout logging in `main.py`
- Rust command/service logs for local process supervision

**Validation:**
- Config normalization in `config.py`
- Provider classification and visibility/managed gating in `core/providers/registry.py`
- Connectivity and CLI checks in Tauri commands

**Packaging Discipline:**
- Repo rules explicitly prioritize installed-app validation over source-only confidence
- Python sidecar rebuild is part of packaging expectations when bot-side changes land

---

*Architecture analysis: 2026-05-10*
*Update when major patterns change*
