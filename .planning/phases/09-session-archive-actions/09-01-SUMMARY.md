# Phase 9 Plan 09-01 Summary: Provider-Backed Session Archive Action

**Updated:** 2026-05-29
**Status:** Completed and packaged-app verified

## Scope Closed

Plan 09-01 added a real archive action for concrete sessions in the Session tab:

- Desktop UI
  - Session rows now expose a right-click context menu with Archive.
  - Session rows also expose a visible action menu for the same Archive command.
  - The action menu is rendered through a document-level portal so it is not clipped by scroll containers or stacking contexts.
  - The archive action shows an in-panel success or failure notice.
  - The active row is disabled while archive is running.
  - Successful archive clears the selected session and refreshes the current provider list.
- Tauri command boundary
  - Added `archive_provider_session`.
  - The command calls a provider real archive path first.
  - Sidecar archive is used only when the owner bridge transport is unavailable; provider-reported archive failures return to the UI directly.
  - Local `onlineworker_state.json` archived state is written only after real archive succeeds.
  - The current session title is persisted with local archived state when available, so archived-only rows can retain a useful display title.
- Provider bridges
  - Provider owner bridge handles `archive_session`.
  - Provider session sidecar bridge supports `archive`.
  - Providers without real archive support fail clearly.
  - Archive hook failures keep local session state unchanged.
- Session list overlay
  - Generic provider session listing merges locally persisted archived overlays into the returned session list.
  - Archived-only overlay rows can appear in the Archived tab even if the provider source no longer returns them in the active session list.
- Provider usage operation
  - Provider metadata now carries usage capability so the Usage tab discovers eligible visible/managed providers dynamically.
  - Built-in providers parse local usage sources directly, while extension providers can provide usage through provider hooks.
  - `/token_usage` is a local bot command scoped to agent topics; thread-topic use is rejected clearly and is not forwarded into provider conversations.
  - Unsupported usage providers return explicit unsupported messages instead of synthetic data.
- Claude boundary
  - Claude archive now reports unsupported real archive instead of pretending to archive locally.

## Behavior Now Expected

- Right-clicking a Session tab row shows Archive.
- Clicking the row action menu shows Archive.
- Archive calls provider-backed real archive logic with `provider_id`, `session_id`, and `workspace_dir`.
- A failed archive remains visible as a UI error and does not move the row to Archived.
- A successful archive persists local archived state and refreshes the list.
- Archived sessions remain visible in the Archived filter through the local post-success overlay when the provider source hides archived rows from active listings.
- Session tab archive does not archive or delete Telegram topics.
- Usage tab provider choices follow provider metadata and usage capability.
- `/token_usage` returns the current agent's recent usage only from an agent topic.

## Verification

```text
PYENV_VERSION=3.13.1 python -m pytest -q OnlineWorker/tests/test_provider_session_bridge.py OnlineWorker/tests/test_provider_owner_bridge.py
45 passed

cargo test --manifest-path OnlineWorker/mac-app/src-tauri/Cargo.toml provider_sessions --quiet
13 passed

node --test OnlineWorker/mac-app/tests/sessionArchiveContextMenu.test.mjs
2 passed

cd OnlineWorker/mac-app && ./node_modules/.bin/tsc --noEmit
passed

git -C OnlineWorker diff --check
passed
```

Additional focused verification after the archived overlay fix:

```text
cd OnlineWorker/mac-app/src-tauri && cargo test provider_sessions::tests --lib
14 passed

node --test OnlineWorker/mac-app/tests/sessionArchiveContextMenu.test.mjs
2 passed

cd OnlineWorker/mac-app && ./node_modules/.bin/tsc --noEmit
passed

python3 -m pytest OnlineWorker/tests/test_provider_session_bridge.py -q
passed
```

Provider usage and command verification:

```text
PYENV_VERSION=3.13.1 python -m pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py tests/test_slash_router.py tests/test_command_rules.py tests/test_notifications.py tests/test_events_streaming.py
118 passed

node --test mac-app/tests/sessionArchiveContextMenu.test.mjs mac-app/tests/usageBrowser.test.mjs mac-app/tests/usageProviders.test.mjs
5 passed

cargo test --manifest-path mac-app/src-tauri/Cargo.toml provider_sessions --quiet
14 passed

git -C OnlineWorker diff --check
passed
```

Packaged-app verification after explicit approval:

```text
bash verify-packaged-fast.sh
Combined fast packaged verification complete (103s)

DMG:
OnlineWorker/mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.3.0_aarch64.dmg

DMG SHA256:
3f0fb03b277c6926c7cd753f3fbe1dddfc92f2f664e2020528defefc4a5c04d6

Installed app:
/Applications/OnlineWorker.app

Installed binary hashes:
onlineworker-bot 7ffbf967f7ffd8fdfaa8807d4c4d671fa8fdadf915581d11ac9e4eee86d593f0
onlineworker-app 7960c3d8350299ab25c73ff286cd880698e0f07647c94a748004d31dd80df8c0
```
