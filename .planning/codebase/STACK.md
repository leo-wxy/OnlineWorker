# Technology Stack

**Analysis Date:** 2026-05-10

## Languages

**Primary:**
- Python 3.13 - Telegram bot runtime, provider orchestration, state/storage, packaging entrypoint in `main.py`
- TypeScript 5.6 - React/Tauri frontend in `mac-app/src/`
- Rust 2021 - Tauri host, local service control, session bridging, packaging backend in `mac-app/src-tauri/`

**Secondary:**
- JavaScript (ES modules) - Node-native frontend tests in `mac-app/tests/*.test.mjs`
- Shell - packaging/bootstrap scripts in `scripts/*.sh`
- YAML / JSON - runtime config, provider manifests, Tauri config, workflow config

## Runtime

**Environment:**
- macOS is the target product runtime for the installed app
- Python 3.13 for the packaged bot sidecar and source-mode bot execution
- Node.js 20 for frontend build/test tooling and CI packaging flow
- Rust stable toolchain (project minimum `rust-version = "1.77.2"`) for the Tauri backend

**Package Manager:**
- pnpm for `mac-app/` frontend and Tauri CLI usage
- pip for Python dependencies from `requirements.txt`
- Cargo for `mac-app/src-tauri/`
- Lockfiles/manifests present:
  - `mac-app/src-tauri/Cargo.lock`
  - `mac-app/package.json`
  - `requirements.txt`

## Frameworks

**Core:**
- python-telegram-bot 22.7 - Telegram bot runtime and update handling, configured in `main.py`
- Tauri 2.x - macOS desktop host in `mac-app/src-tauri/`
- React 18 - Mac app UI in `mac-app/src/`
- Vite 5 - frontend dev/build pipeline in `mac-app/`

**Testing:**
- pytest 8.3 + pytest-asyncio - Python behavior/regression tests in `tests/`
- Rust built-in test framework via `cargo test` - Tauri/backend tests
- Node built-in `node --test` - frontend model/view tests in `mac-app/tests/`

**Build/Dev:**
- PyInstaller - packages `main.py` into the `onlineworker-bot` sidecar
- TypeScript compiler (`tsc`) - frontend type checking
- Tailwind CSS + PostCSS - frontend styling pipeline
- GitHub Actions - tag-driven Apple Silicon DMG packaging via `.github/workflows/release-dmg.yml`

## Key Dependencies

**Critical:**
- `python-telegram-bot==22.7` - Telegram update loop, handlers, callbacks
- `websockets==16.0` and `httpx>=0.28.0` - provider transport and HTTP client behavior
- `tauri = "2"` - desktop shell, command bridge, bundle generation
- `react` / `react-dom` 18.3 - desktop UI rendering
- `serde`, `serde_json`, `serde_yaml` - Rust-side config/session serialization

**Infrastructure:**
- `ureq` with `proxy-from-env` and `socks-proxy` - Rust-side Telegram connectivity checks and HTTP integrations
- `rusqlite` with `bundled` - local SQLite-backed command/session data on the Rust side
- `js-yaml` - frontend config parsing/editing
- `react-markdown` + `remark-gfm` - reply/session Markdown rendering

## Configuration

**Environment:**
- Installed app data:
  - `~/Library/Application Support/OnlineWorker/config.yaml`
  - `~/Library/Application Support/OnlineWorker/.env`
- Source mode may also use repo-local:
  - `config.yaml`
  - `.env`
  - `onlineworker_state.json`
- Key runtime variables include:
  - `TELEGRAM_TOKEN`
  - `ALLOWED_USER_ID`
  - `GROUP_CHAT_ID`
  - `ONLINEWORKER_PROVIDER_OVERLAY`
  - `ONLINEWORKER_PLUGIN_SOURCE_DIRS`

**Build:**
- Frontend: `mac-app/package.json`, `mac-app/tsconfig*.json`, `mac-app/vite.config.ts`
- Tauri: `mac-app/src-tauri/tauri.conf.json`, `mac-app/src-tauri/Cargo.toml`
- Python packaging: `onlineworker.spec`, `onlineworker-x86_64.spec`
- Shared packaging path: `scripts/build.sh`
- CI packaging path: `.github/workflows/release-dmg.yml`

## Platform Requirements

**Development:**
- macOS is the primary supported development platform for realistic packaging/runtime verification
- Node.js 20, Python 3.13, Rust stable, pnpm
- Local `codex` and/or `claude` CLI installed for full provider flows

**Production:**
- Distributed as a macOS `.app` / `.dmg`
- Primary packaging target today is Apple Silicon (`aarch64`)
- Intel packaging remains supported manually via `onlineworker-x86_64.spec` and targeted Tauri build

---

*Stack analysis: 2026-05-10*
*Update after major dependency changes*
