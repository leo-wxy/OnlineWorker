# OnlineWorker

<p align="center">
  <img src="./launcher.png" alt="OnlineWorker launcher artwork" width="360" />
</p>

OnlineWorker is a macOS AI coding workspace for local CLI agents. The Mac app is the main control surface for setup, sessions, commands, logs, and service lifecycle. Telegram is a lightweight remote entry point for starting work, adding context, handling approvals, checking status, and receiving the final response.

The default workflow is **App / Sessions as the primary control surface + Telegram for the final reply**.

中文说明见 [README.zh.md](README.zh.md).

See also:

- [Documentation Notes](docs/README.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Support](SUPPORT.md)

## Screenshots

These screenshots are generated from the real app UI with sanitized demo data.
They do not contain live tokens, user IDs, filesystem paths, session content, or
private extension configuration.

<p align="center">
  <img src="./docs/screenshots/dashboard.png" alt="OnlineWorker dashboard" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/sessions-overview.png" alt="OnlineWorker sessions" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/usage.png" alt="OnlineWorker usage" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/ai-services.png" alt="OnlineWorker AI services" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/ai-scenarios.png" alt="OnlineWorker AI scenarios" width="88%" />
</p>

<p align="center">
  <img src="./docs/screenshots/setup.png" alt="OnlineWorker setup" width="88%" />
</p>

## Overview

- macOS desktop workspace for running and supervising local AI coding CLIs.
- Built around an installed app, not a browser-hosted service.
- App for setup and ongoing control, Telegram for remote input and final delivery.
- Builtin providers in this repository: `codex` and `claude`.
- Builtin notification channel in this repository: `telegram`, with external notification channels mountable through plugins.
- A first-class `Usage` page for recent provider consumption, with `Codex / Claude` switching inside the app.
- A first-class `AI` page for shared AI service configuration and scenario-specific prompts.

## Features

- Mac app control for setup, dashboard, sessions, commands, and logs.
- Telegram entry point for remote task submission and final updates.
- Telegram mirrors provider approvals and questions. For Codex, approval
  requests can be handled either from the local Codex TUI host or from the
  Telegram buttons when the current thread is bound to the host.
- Plugin-based notification channels, configurable from the first-class `Notifications` page.
- Provider-driven configuration for supported CLI backends.
- Session browsing and message sending from the app.
- Session rows can be archived from the Sessions page. Archive actions call the provider's real archive operation first; local archived state is updated only after that operation succeeds.
- Session Browser supports text plus image/file attachment sends from the desktop app, with one user message shown per send.
- A dedicated `Usage` page for recent provider usage, with a default 7-day window, date filtering, summary cards, and daily charts.
- Usage aggregation stays behind provider/plugin adapters instead of pushing provider-specific parsing into shared React surfaces.
- `/token_usage` is a local bot command for agent topics. It reports provider usage where supported and rejects concrete conversation topics instead of forwarding into an agent session.
- Shared AI services can be configured once and reused by scenarios. Notification completion summary is the first built-in scenario and falls back to deterministic local summary rules when AI is disabled or unavailable.
- Markdown rendering for final replies.
- Installer-friendly macOS packaging through Tauri and PyInstaller.

## Provider Scope

This repository ships builtin support for:

- `codex`
- `claude`

The app also supports external provider packages through the public plugin
contracts, but this repository only bundles the builtin providers listed above.

## Notification Channels

This repository ships builtin notification support for:

- `telegram`

Additional notification packages can be mounted through the public notification plugin contract. The shared notification router sends concise task status events to enabled channels; each plugin owns the actual app-specific send logic.

## Requirements

- macOS
- Node.js 20
- Python 3.13
- Rust toolchain for the Tauri backend
- `codex` CLI for Codex-backed workflows
- `claude` CLI for Claude-backed workflows

## Quick Start

1. Build the DMG locally or download a packaged DMG.
2. Open the DMG and drag `OnlineWorker.app` into `/Applications`.
3. If macOS blocks the app on first launch, remove the quarantine attribute:

```bash
xattr -cr /Applications/OnlineWorker.app
```

4. Launch `OnlineWorker.app`.

## Initial Setup

1. Open the app and go to `Setup`.
2. Make sure the supported CLI tools you want to use are installed and visible in `PATH`.
3. Fill in the Telegram values:
   - `TELEGRAM_TOKEN`
   - `ALLOWED_USER_ID`
   - `GROUP_CHAT_ID`
4. If you use Claude through the official login flow, run `claude auth login` first.
5. Use the in-app connectivity checks on the `Setup` page to confirm Telegram access.
6. Go back to `Dashboard` and start the service.

## Configuration

The installed app reads and writes user data under:

```text
~/Library/Application Support/OnlineWorker/config.yaml
~/Library/Application Support/OnlineWorker/.env
```

When running from source, the repo root may also use local `config.yaml`, `.env`, and `onlineworker_state.json` files.

Additional provider packages can be mounted by setting `ONLINEWORKER_PROVIDER_OVERLAY` to a file or directory path. When the path points to a directory, OnlineWorker scans any `plugin.yaml` files under that tree and loads the provider descriptors it finds there. The installed app also reads the same key from `~/Library/Application Support/OnlineWorker/.env`, with process env taking priority when both are present.

Additional notification packages can be mounted by setting `ONLINEWORKER_NOTIFICATION_OVERLAY` in the process environment to a file or directory path. Directory paths are scanned for `plugin.yaml` files with `kind: notification`. This key is not read from the app `.env`.

### `.env`

```bash
TELEGRAM_TOKEN=your_bot_token_here
ALLOWED_USER_ID=123456789
GROUP_CHAT_ID=-1001234567890
```

Claude uses the local Claude CLI's own authentication and runtime configuration.
OnlineWorker does not read or write `ANTHROPIC_*` proxy, model, or key settings.

### `config.yaml`

`config.yaml` is the app configuration file for provider, Telegram, and notification plugin settings. Use the in-app settings UI to edit it in normal workflows.

Notification channels are exposed as a first-class `Notifications` tab. Channel switches are stored under `notifications.channels.<channel>.enabled`; plugin field values are stored under `notifications.channels.<channel>.config`.

AI services and scenarios are configured from the first-class `AI` tab. Service
settings such as API key, endpoint, model list, selected model, timeout, and
enablement are separate from scenario prompt settings. Scenario settings choose
one configured service and define the prompt, output schema, limits, enablement,
and fallback behavior for a specific use case.

The current built-in AI service choices are OpenAI-compatible chat completions
and Claude-compatible messages. Users choose and test those fixed service
cards; they do not need to type protocol names or environment variable names for
this feature.

## Provider Interactions

OnlineWorker routes provider-specific approval and question prompts through a
shared interaction contract:

- `core` owns the common `ProviderApprovalRequest` and `ProviderQuestionRequest`
  structures.
- Provider plugins parse their native events, decide whether a prompt is
  actionable, and handle the provider-specific reply path.
- Telegram renders the shared interaction shape and records pending callbacks.

For Codex, the packaged app can bind the active session to a managed Codex TUI
host. When that host is online, approval prompts are mirrored to Telegram with
action buttons, and Telegram actions are written back to the same TUI host. The
local Codex TUI remains usable for the same approval flow.

## Codex Text Sending

Civility mode is temporarily disabled. App and Telegram send user input
unchanged, and the related settings entry is hidden from the app.

The managed remote-proxy wrapper code remains in the repository for a future
restore, but it is not documented as a public entry point while the feature is
paused.

## Session Operations

Sessions can be browsed, messaged, filtered by active/archived state, and
archived from the Sessions page. A row-level action menu and the context menu
both expose archive when the selected provider supports a real archive path.

Archive is provider-backed. OnlineWorker calls the provider source first, then
persists a local archived overlay only after success. If the provider reports
failure or does not support real archive, the UI shows the error and leaves the
session unchanged locally. Archived overlays are merged back into provider
session lists so the Archived filter can still show rows when a provider source
omits archived sessions.

## Usage

Usage data is exposed through provider metadata and usage hooks. The app shows
usage-capable providers dynamically on the Usage page, so new providers can
participate without hard-coded React parsing.

Telegram also supports `/token_usage` as a local command in agent topics. The
command is handled by OnlineWorker and is not forwarded into the active
conversation. Concrete session topics reject it with guidance because usage is
meaningful at the agent/provider topic level.

## AI Scenarios

The AI layer is a shared app capability, not a provider session. AI scenario
calls are direct API requests and do not create Codex sessions, Claude sessions,
provider conversations, or Telegram topics.

Notification completion summary uses the `notification_summary` scenario when
enabled and correctly configured. If the scenario is disabled, invalid, or the
service call fails, OnlineWorker falls back to local summary rules. Preview
titles remain length-limited, while AI-generated summary bodies are kept intact
apart from lightweight cleanup.

## Development

### Run the bot from source

```bash
cd /path/to/onlineWorker
/path/to/python3 main.py
```

By default, source-mode runs now use the same stable app data directory as the packaged app.
Use `--data-dir /custom/path` only when you intentionally want an isolated runtime state.

### Run the Mac app in development mode

```bash
cd /path/to/onlineWorker/mac-app
pnpm dev
```

### Run tests

```bash
/path/to/python3 -m pytest -q tests/test_config.py tests/test_provider_facts.py tests/test_state.py tests/test_session_events.py

bash scripts/bootstrap-sidecar.sh
cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet

cd mac-app
node --test tests/*.test.mjs
pnpm build
```

`pnpm build` may emit a pre-existing Vite chunk-size warning. As long as the command exits with status 0, the build is successful.

`scripts/bootstrap-sidecar.sh` creates an ignored local placeholder sidecar required by Tauri's build metadata checks. It is only for source-tree tests; `scripts/build.sh` replaces it with the real PyInstaller sidecar before packaging.

## Build

### Apple Silicon DMG

```bash
cd /path/to/onlineWorker
bash scripts/build.sh
```

This build path packages the base app from this repository. Additional provider packages can be mounted at runtime through `ONLINEWORKER_PROVIDER_OVERLAY`, notification packages can be mounted through `ONLINEWORKER_NOTIFICATION_OVERLAY`, and provider packages can be staged at build time through `ONLINEWORKER_PLUGIN_SOURCE_DIRS` before calling the same `scripts/build.sh`.

Pushing a version tag such as `1.2.1` also builds this same Apple Silicon DMG automatically through `.github/workflows/release-dmg.yml`. The workflow uploads the DMG as a workflow artifact, creates the matching GitHub Release if needed, and then attaches the DMG to that Release asset list.

After a local DMG is already built, this helper installs it into
`/Applications`, restarts the packaged app, and verifies that both app and bot
processes are running:

```bash
bash scripts/install-current-dmg.sh mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.2.1_aarch64.dmg
```

To restart the currently installed app without reinstalling a DMG:

```bash
bash scripts/restart-installed-app.sh
```

### Intel DMG

```bash
cd /path/to/onlineWorker
arch -x86_64 /usr/local/bin/python3.13 -m PyInstaller onlineworker-x86_64.spec --clean --noconfirm --distpath dist-x86_64
cp dist-x86_64/onlineworker-bot mac-app/src-tauri/binaries/onlineworker-bot-x86_64-apple-darwin

cd mac-app
pnpm tauri build --target x86_64-apple-darwin
```

## Repository Layout

```text
onlineWorker/
├── main.py                  # Bot entry point
├── bot/                     # Telegram bot handlers and utilities
├── core/                    # Shared runtime, state, storage, and provider contracts
├── mac-app/                 # Tauri + React Mac app
├── plugins/                 # Provider and notification plugin descriptors/runtime implementations
├── scripts/                 # Build and maintenance scripts
├── tests/                   # Python tests
├── deploy/                  # Packaging and deployment notes
└── README.md
```

## Notes

- Source mode is for development and troubleshooting.
- App installation and verification should always be done against the packaged app.
- Local generated files such as `__pycache__`, `.pytest_cache`, build outputs, and `onlineworker_state.json` should remain untracked.

## License

MIT. See [LICENSE](LICENSE).
