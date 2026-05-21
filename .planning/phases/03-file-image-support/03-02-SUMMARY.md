# Phase 3 Plan 03-02 Summary: Desktop Attachment Send and Packaged App Verification

**Updated:** 2026-05-21
**Status:** Completed; build/install/startup, cache maintenance, and live desktop attachment smoke verified

## Scope Closed

Plan 03-02 added desktop attachment send support through the existing Session Browser and Tauri/provider bridge:

- `mac-app/src/pages/SessionBrowser.tsx`
  - Added composer attachment state for the supported session surfaces.
  - Sends selected attachments with the message payload.
  - Surfaces unsupported attachment errors through existing session error handling.
- `mac-app/src/components/session-browser/shared.tsx`
  - Added attachment controls, selected attachment rows, removal behavior, and disabled/send states.
- `mac-app/src/components/session-browser/api.ts`
  - Added attachment arguments to Codex and Claude session send APIs.
  - Added `stageComposerAttachments(...)`.
- `mac-app/src-tauri/src/commands/provider_sessions.rs`
  - Added composer attachment staging under the OnlineWorker data directory.
  - Infers image/file kind from name and mime type.
  - Sends attachments through provider session command payloads instead of exposing provider-specific details to React.
- `mac-app/src-tauri/src/commands/attachment_cache.rs`
  - Added provider-neutral cache stats and cleanup commands for the OnlineWorker data directory.
  - Covers Telegram-downloaded attachments in `attachments/`.
  - Covers desktop composer staged attachments in `composer-attachments/`.
  - Deletes cache contents while keeping/recreating cache root directories.
- `mac-app/src/components/MaintenanceSettingsPanel.tsx`
  - Added a dedicated Settings `Maintenance` sub tab for post-setup maintenance controls.
  - Added attachment cache size, refresh, and clear controls under the Storage section.
  - This intentionally stays in the desktop Settings UI; no Telegram command was added.
- `mac-app/src/pages/SetupWizard.tsx`
  - Keeps first-run and OnlineWorker configuration focused on setup/startup concerns.
  - Attachment cache maintenance was kept out of the setup wizard.
- Provider-specific Tauri command paths for Codex and Claude now carry attachment payloads into their existing provider send flows.

## Packaged App Verification From 2026-05-21

Real build and install flow completed from `/Users/wxy/Projects/onlineworker-combined`:

```text
bash build.sh
```

Generated DMG:

```text
/Users/wxy/Projects/onlineworker-combined/OnlineWorker/mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.1.0_aarch64.dmg
mtime: 2026-05-21 14:38:28 +0800
sha256: 94fbb7abce3f694178f1d91c1ebad9f574df91d172372ef9e405afb7fd24a403
```

Installed app verification:

```text
/Applications/OnlineWorker.app
mtime: 2026-05-21 14:38:00 +0800
version: 1.1.0
```

Runtime verification:

- OnlineWorker app and bot processes restarted from `/Applications/OnlineWorker.app/Contents/MacOS/...`.
- `provider-plugins/codemaker` exists inside the installed app resources.
- Startup log shows:
  - `2026-05-21 14:40:03` OnlineWorker startup.
  - Claude hook bridge started.
  - Claude workspace cwd registrations completed.
  - codemaker health check passed.
  - Provider owner bridge and Codex owner bridge sockets were recreated from the installed app runtime.

## Verification

Desktop/source verification:

```text
node --test mac-app/tests/appShell.test.mjs

5 passed
```

Attachment cache command verification:

```text
cd mac-app/src-tauri && cargo test attachment_cache --lib

2 passed
```

Frontend production build:

```text
cd mac-app && npm run build

tsc && vite build completed
```

Packaged app build/install/startup:

```text
bash build.sh
```

Completed successfully and installed to `/Applications/OnlineWorker.app`.

Installed app Settings `Maintenance` cache smoke:

```text
UI before clear: current attachment cache showed 2.2 MB across 6 files.
UI after clear: current attachment cache showed 0 B across 0 files.
Filesystem after clear:
  ~/Library/Application Support/OnlineWorker/attachments -> 0 files, 0B
  ~/Library/Application Support/OnlineWorker/composer-attachments -> 0 files, 0B
Preserved files confirmed:
  config.yaml
  .env
  onlineworker_state.json
  onlineworker.log
```

Installed app live attachment smoke:

- On 2026-05-21, the user confirmed a fresh Telegram attachment send works after the installed-app update.
- On 2026-05-21, the user confirmed a desktop Session Browser attachment send works from the installed app through the provider path.

## Known Remaining Verification

- None for Phase 3.
