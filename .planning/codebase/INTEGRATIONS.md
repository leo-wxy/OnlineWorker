# External Integrations

**Analysis Date:** 2026-05-10

## APIs & External Services

**Telegram Bot API:**
- Telegram - primary remote control and delivery channel
  - Python integration: `python-telegram-bot` in `main.py`, `bot/handlers/`, `bot/events.py`
  - Rust integration: Telegram connectivity checks in `mac-app/src-tauri/src/commands/telegram.rs`
  - Auth/config: `TELEGRAM_TOKEN`, `ALLOWED_USER_ID`, `GROUP_CHAT_ID`

**Local AI CLI Providers:**
- OpenAI Codex CLI - builtin provider runtime
  - Provider implementation roots:
    - `plugins/providers/builtin/codex/`
    - `plugins/providers/builtin/codex/python/`
  - Used for session management, thread operations, approvals, wrappers, app-server/TUI flows
- Anthropic Claude CLI - builtin provider runtime
  - Provider implementation roots:
    - `plugins/providers/builtin/claude/`
    - `plugins/providers/builtin/claude/python/`
  - Used for session management, questions, approvals, and source/app mode workflows

**External Provider Packages:**
- Public provider extension boundary through plugin manifests and overlays
  - Manifest loading in `core/providers/registry.py`
  - Overlay discovery in `core/providers/overlay.py`
  - Build-time staging via `ONLINEWORKER_PLUGIN_SOURCE_DIRS`
  - Runtime loading via `ONLINEWORKER_PROVIDER_OVERLAY`

## Data Storage

**Local JSON state:**
- `onlineworker_state.json` - source-mode persistent state via `core/storage.py`
- Stores workspaces, active workspace, global topic IDs, thread metadata

**Installed app config/env:**
- `~/Library/Application Support/OnlineWorker/config.yaml`
- `~/Library/Application Support/OnlineWorker/.env`

**SQLite (Rust side):**
- `rusqlite` is present in `mac-app/src-tauri/Cargo.toml`
- Used by Rust-side command/session support surfaces and local persistence paths inside Tauri commands

**Log storage:**
- Python side log file rotates to `onlineworker.log` in the data dir or `/tmp/onlineworker.log`
- App-side log viewing is exposed through `mac-app/src-tauri/src/commands/logs.rs`

## Authentication & Identity

**Telegram allowlisting:**
- User access gate via `ALLOWED_USER_ID`
- Group-bound interaction via `GROUP_CHAT_ID`
- Request filter path starts in `bot/filters.py` and handler registration in `main.py`

**Provider authentication:**
- Codex CLI authentication is external to this repo and handled by the installed `codex` CLI
- Claude CLI authentication is external to this repo and typically driven by `claude auth login`
- Optional Claude API/proxy values surfaced through `.env`:
  - `ANTHROPIC_API_KEY`
  - `ANTHROPIC_BASE_URL`
  - `ANTHROPIC_MODEL`

## Monitoring & Observability

**Application logs:**
- Python root logging with rotating file handler in `main.py`
- Rust-side service/log commands exposed to the Tauri app
- Telegram-side raw update/error logging hooks registered in `main.py`

**Runtime health checks:**
- Service and CLI health commands in `mac-app/src-tauri/src/commands/service.rs`
- Telegram connectivity validation in `mac-app/src-tauri/src/commands/telegram.rs`

## CI/CD & Deployment

**Hosting / distribution:**
- No hosted SaaS deployment target
- Product is distributed as a macOS desktop app bundle and DMG

**CI Pipeline:**
- GitHub Actions workflow: `.github/workflows/release-dmg.yml`
  - Trigger: version tag push like `1.0.0`
  - Runtime: `macos-15`
  - Output: Apple Silicon DMG
  - Release handling: creates GitHub Release if missing, uploads DMG asset

**Local packaging:**
- `scripts/build.sh` is the canonical Apple Silicon packaging path
- `deploy/BUILD.md` documents both Apple Silicon and Intel flows

## Environment Configuration

**Development:**
- Source-mode config from repo-local `config.yaml` / `.env` when present
- Local CLI dependencies (`codex`, `claude`) must exist in `PATH`
- Build-time Python path can be overridden with `PYTHON_ARM64`

**Installed app:**
- Reads config/env from Application Support
- Uses bundled sidecar binary `onlineworker-bot-*` inside the Tauri app bundle

## Webhooks & Callbacks

**Incoming Telegram callbacks:**
- Inline keyboard callback queries processed by `CallbackQueryHandler` in `main.py`
- Approval/question/session callback handling routed through `bot/handlers/message.py`, `bot/handlers/workspace.py`, `bot/events.py`

**Provider event callbacks:**
- App-server / provider events normalized into semantic session/turn/approval/question events
- Hook bridges exist for provider-specific relay modes:
  - `plugins/providers/builtin/claude/python/hook_bridge.py`
  - `plugins/providers/builtin/codex/python/hook_bridge.py`

---

*Integration audit: 2026-05-10*
*Update when adding/removing external services*
