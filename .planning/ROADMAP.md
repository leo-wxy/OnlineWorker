# Roadmap: OnlineWorker

## Completed Milestones

- [v1.2.1](milestones/v1.2.1-ROADMAP.md): UI foundation, provider usage explorer, file/image support, Claude safe resume, and provider session error visibility.

## Current Milestone

**Theme:** Notification Extensibility

This milestone decouples user notifications from Telegram-only delivery so OnlineWorker can notify through additional apps/channels while preserving Telegram as the first supported channel.

## Phases

- [x] **Phase 6: Notification Channel Abstraction** - Introduce a provider-neutral notification mechanism so OnlineWorker can emit concise notifications through enabled notification plugins. Core plugin/router/config UI is implemented; existing Telegram task/approval/final-reply paths remain unchanged.

## Phase Details

### Phase 6: Notification Channel Abstraction

**Goal:** Add a notification plugin mechanism that keeps Telegram available as one builtin notification plugin while establishing a stable boundary for additional app/channel integrations such as WeChat.
**Requirements:** [NOTIFY-01, NOTIFY-02]
**Depends on:** v1.2.1 archived milestone
**Success Criteria** (what must be TRUE):
  1. Notification callers can emit a `NotificationEvent` to a plugin-based notification router instead of knowing the target app/channel.
  2. Telegram remains the default builtin notification plugin with behavior preserved for current users.
  3. The architecture can register additional notification plugins without adding app-specific branches throughout shared runtime code.
  4. Notification failure handling is explicit enough that one channel failure does not silently break all user-facing delivery.
**Plans:** 1 plan

Plans:
- [x] 06-01: Add minimal notification channel abstraction
  - [x] Core notification event/router/registry
  - [x] Builtin Telegram notification plugin
  - [x] External notification plugin discovery and `Setup → Notifications` UI
  - [x] Existing Telegram business send paths left unchanged

Latest verification:
- Notification unit/config regression passed: `rtk pytest -q tests/test_notifications.py tests/test_config.py` -> `49 passed`.
- App shell notification UI regression passed: `node --test mac-app/tests/appShell.test.mjs` -> `8 passed`.
- Rust config provider regression passed: `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet` -> `22 passed`.
- Codex TG ordinary message routing regression passed after the provider interaction approval pull:
  - `rtk pytest -q tests/test_codex_tui_mode.py::test_message_handler_in_app_stdio_owner_bridge_mode_uses_app_adapter_for_tg_messages ...` -> `4 passed`.
  - `rtk pytest -q tests/test_codex_tui_mode.py tests/test_slash_router.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_codex_owner_bridge.py` -> `109 passed`.
- Installed app was rebuilt with `bash scripts/build.sh`, overwritten to `/Applications/OnlineWorker.app`, relaunched, and runtime-checked:
  - installed version `1.2.1`
  - `provider_owner_bridge.sock` and `codex_owner_bridge.sock` connectable
  - provider owner bridge runtime status reported Codex app-server healthy
  - startup log error scan returned zero matches for the verification window

Remaining Phase 6 verification:
- None for the notification plugin boundary and Telegram builtin channel. Non-Telegram notification channels remain future plugin work.
