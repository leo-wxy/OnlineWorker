# Codebase Structure

**Analysis Date:** 2026-05-10

## Directory Layout

```text
onlineWorker/
├── bot/                     # Telegram handlers, routing, formatting, keyboards, filters
├── core/                    # Shared runtime state, storage, lifecycle, provider contracts/registry
├── deploy/                  # Packaging and deployment notes/scripts
├── docs/                    # Public documentation notes and screenshots
├── mac-app/                 # React frontend + Tauri host project
│   ├── src/                 # Frontend UI
│   ├── src-tauri/           # Rust/Tauri backend and bundle config
│   └── tests/               # Node-native frontend behavior tests
├── plugins/                 # Builtin provider descriptors and runtime implementations
├── scripts/                 # Build/bootstrap/maintenance scripts
├── tests/                   # Python regression and runtime tests
├── .github/workflows/       # GitHub Actions packaging workflow
├── main.py                  # Python bot/sidecar entry point
├── config.py                # Config schema + normalization
├── requirements.txt         # Python dependencies
└── README.md                # Public project overview
```

## Directory Purposes

**`bot/`:**
- Purpose: Telegram interaction layer
- Contains: handler factories, slash routing, event rendering, keyboards, filters, utilities
- Key files:
  - `bot/handlers/common.py`
  - `bot/handlers/workspace.py`
  - `bot/handlers/thread.py`
  - `bot/handlers/message.py`
  - `bot/events.py`
- Subdirectories: `handlers/`

**`core/`:**
- Purpose: shared runtime and provider-neutral backend code
- Contains: lifecycle management, runtime state, persistent storage, provider contracts/overlay/registry
- Key files:
  - `core/lifecycle.py`
  - `core/state.py`
  - `core/storage.py`
  - `core/providers/contracts.py`
  - `core/providers/registry.py`

**`mac-app/`:**
- Purpose: desktop app project
- Contains:
  - `src/` frontend React UI
  - `src-tauri/` native Tauri/Rust host
  - `tests/` frontend tests
- Key files:
  - `mac-app/package.json`
  - `mac-app/src/App.tsx`
  - `mac-app/src-tauri/src/lib.rs`
  - `mac-app/src-tauri/tauri.conf.json`

**`plugins/`:**
- Purpose: provider plugin catalog and builtin provider implementations
- Contains: builtin `codex` and `claude` manifests/runtime code
- Key files:
  - `plugins/providers/catalog.py`
  - `plugins/providers/builtin/codex/plugin.yaml`
  - `plugins/providers/builtin/claude/plugin.yaml`

**`scripts/`:**
- Purpose: packaging/bootstrap/maintenance helpers
- Contains: build script, sidecar bootstrap, smoke cleanup, diagnostics
- Key files:
  - `scripts/build.sh`
  - `scripts/bootstrap-sidecar.sh`
  - `scripts/cleanup_smoke_sessions.py`
  - `scripts/README.md`

**`tests/`:**
- Purpose: Python tests
- Contains: runtime/provider/config/storage/handler tests plus fixtures/helpers
- Key files:
  - `tests/test_config.py`
  - `tests/test_provider_facts.py`
  - `tests/test_state.py`
  - `tests/helpers/codex_runtime.py`

## Key File Locations

**Entry Points:**
- `main.py` - Python sidecar / Telegram bot entry point
- `mac-app/src-tauri/src/main.rs` - Tauri binary entry
- `mac-app/src/App.tsx` - frontend application root

**Configuration:**
- `config.py` - Python config model and defaults
- `mac-app/src-tauri/tauri.conf.json` - Tauri app metadata/bundle config
- `mac-app/package.json` - frontend scripts/dependencies
- `.github/workflows/release-dmg.yml` - tag-driven DMG packaging workflow
- `requirements.txt` - Python dependency manifest

**Core Logic:**
- `core/` - runtime, provider contracts, lifecycle, storage
- `bot/` - Telegram orchestration logic
- `plugins/providers/builtin/` - provider-specific implementations
- `mac-app/src-tauri/src/commands/` - native command surface for the frontend

**Testing:**
- `tests/` - Python tests
- `mac-app/tests/` - frontend Node tests
- `mac-app/src-tauri` - Rust tests via `cargo test`

**Documentation:**
- `README.md`, `README.zh.md`
- `deploy/BUILD.md`
- `docs/README.md`
- `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`

## Naming Conventions

**Files:**
- Python modules: snake_case, e.g. `test_provider_facts.py`, `thread.py`, `storage.py`
- Frontend tests: `*.test.mjs` in `mac-app/tests/`
- React pages/components: PascalCase for main component files, e.g. `SessionBrowser.tsx`, `SetupWizard.tsx`
- Rust command modules: snake_case files under `mac-app/src-tauri/src/commands/`

**Directories:**
- Feature/domain grouping by top-level concern: `bot/`, `core/`, `plugins/`, `mac-app/`, `deploy/`, `scripts/`, `tests/`
- Provider grouping under `plugins/providers/builtin/<provider>/`

**Special Patterns:**
- `plugin.yaml` for provider manifests
- `onlineworker*.spec` for PyInstaller targets
- `.planning/` reserved for GSD planning artifacts

## Where to Add New Code

**New Telegram behavior:**
- Primary code: `bot/handlers/` or `bot/events.py`
- Shared runtime/state support: `core/`
- Tests: `tests/test_*.py`

**New provider integration:**
- Manifest/runtime: `plugins/providers/builtin/<provider>/` or overlay package
- Shared contract changes only if the provider-neutral abstraction truly requires it: `core/providers/`
- Tests: `tests/` plus optional `mac-app/tests/` / Rust command coverage if surfaced in app UI

**New desktop UI feature:**
- UI implementation: `mac-app/src/pages/` or `mac-app/src/components/`
- Native bridge: `mac-app/src-tauri/src/commands/`
- Frontend tests: `mac-app/tests/`

**New packaging/runtime helper:**
- Script: `scripts/`
- Packaging docs: `deploy/BUILD.md`
- CI automation: `.github/workflows/`

## Special Directories

**`mac-app/dist/`:**
- Purpose: frontend build output
- Source: `pnpm build`
- Committed: No

**`mac-app/src-tauri/target/`:**
- Purpose: Rust/Tauri build output and app bundles
- Source: Cargo/Tauri build
- Committed: No

**`dist/` / `build/`:**
- Purpose: PyInstaller outputs
- Source: `scripts/build.sh` / `pyinstaller`
- Committed: No

**`.planning/`:**
- Purpose: planning artifacts for GSD workflows
- Source: project planning workflows such as `gsd-new-project` and `gsd-map-codebase`
- Committed: depends on project preference; currently absent before initialization

---

*Structure analysis: 2026-05-10*
*Update when directory structure changes*
