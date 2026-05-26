# Roadmap: OnlineWorker

## Completed Milestones

- [v1.2.1](milestones/v1.2.1-ROADMAP.md): UI foundation, provider usage explorer, file/image support, Claude safe resume, and provider session error visibility.

## Current Milestone

**Theme:** Notification Extensibility

This milestone decouples user notifications from Telegram-only delivery so OnlineWorker can notify through additional apps/channels while preserving Telegram as the first supported channel.

## Phases

- [x] **Phase 6: Notification Channel Abstraction** - Introduce a provider-neutral notification mechanism so OnlineWorker can emit concise notifications through enabled notification plugins. Core plugin/router/config UI is implemented; existing Telegram task/approval/final-reply paths remain unchanged.
- [x] **Phase 7: OnlineWorker User Message Gateway** - Route provider-bound user text through an OnlineWorker-level gateway before provider-specific send hooks. Gateway/proxy boundaries are complete; civility rewrite is paused, related App entry points are hidden, and packaged-app verification is complete.

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

### Phase 7: OnlineWorker User Message Gateway

**Goal:** Route all provider-bound user messages through one OnlineWorker-level gateway before provider-specific send hooks. The gateway should expose `before_user_message_send` hooks so cross-provider input policies can be implemented once, starting with conservative abusive-language normalization such as `这什么傻逼问题` -> `这是什么问题`.
**Requirements**: TBD
**Depends on:** Phase 6
**Plans:** 3 plans

Plans:
- [x] 07-01: Add OnlineWorker user message gateway and before-send hooks
  - [x] Core `core/user_messages/` contracts, gateway, hook runner, and built-in abusive-language normalization
  - [x] Telegram, owner bridge, provider session bridge, and new-thread send paths routed through the gateway
  - [x] Codex CLI `UserPromptSubmit` protocol verified; current OnlineWorker hook bridge treats it as safe pass-through because prompt replacement support was not confirmed from local protocol evidence
- [x] 07-02: Add dictionary-backed user message neutralizer
  - [x] Pure Python sensitive term matcher and neutralizer
  - [x] `drop` and `replace` actions for abuse prefixes, insults, and derogatory object phrases
  - [x] Manual test script for normalizer behavior
- [x] 07-03: Add Codex remote app-server user message proxy
  - [x] Real `codex --remote` WebSocket probe confirmed initial prompt text is sent through `turn/start.params.input`
  - [x] OnlineWorker-managed Codex TUI host routes through a local fail-closed remote proxy before app-server persistence/model submission
  - [x] Proxy reuses the shared `core/user_messages` gateway and leaves `text_elements` inputs unchanged

Latest verification:
- Focused source regression passed: `PYENV_VERSION=3.13.1 pytest -q tests/test_handlers.py tests/test_user_message_hooks.py tests/test_user_message_normalizer_script.py tests/test_config.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py tests/test_provider_session_bridge_attachments.py tests/test_codex_hook_bridge.py tests/test_codex_remote_proxy.py tests/test_codex_remote_proxy_probe.py tests/test_codex_tui_mode.py tests/test_codex_tui_host_wrapper.py tests/test_startup_runtime.py && git diff --check` -> `276 passed`.
- Civility rewrite pause regression passed: `pytest tests/test_user_message_hooks.py tests/test_codex_remote_proxy.py` -> `16 passed`.
- App shell regression passed: `node --test mac-app/tests/appShell.test.mjs` -> `9 passed`.
- Frontend production build passed: `pnpm --dir mac-app build`.
- Fast packaged-app verification passed: `bash scripts/verify-packaged-fast.sh`.
  - DMG: `mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.2.1_aarch64.dmg`
  - SHA256: `4894bdd02ec340afcb5e97a4f0dbb8267a5c77809534ec1f4916a1fda34a6be6`
  - Installed runtime: `onlineworker-app` PID `74952`, `onlineworker-bot` PIDs `75058` and `75126`
- Installed app UI was checked with Computer Use: `Settings → Agents` no longer shows the message rewrite/civility entry, only provider enable/autostart controls.

Remaining Phase 7 verification:
- None. Phase 7 is closed with the rewrite hook disabled and UI entry hidden until the feature is intentionally restored.
