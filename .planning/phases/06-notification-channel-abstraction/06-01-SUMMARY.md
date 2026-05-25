# Phase 6 Plan 06-01 Summary: Notification Channel Abstraction

**Updated:** 2026-05-25
**Status:** Completed; notification routing, builtin Telegram channel, plugin configuration UI, and plugin development docs implemented and installed-app verified

## Scope Closed

Plan 06-01 added the minimal notification plugin boundary for OnlineWorker:

- `core/notifications/`
  - Defines a compact `NotificationEvent` shape with status, agent, task, message, and stable identifiers.
  - Routes emitted notification events through enabled notification channels.
  - Deduplicates repeated `{task_id, agent_id, status}` events so noisy repeated task updates do not spam users.
- `plugins/notifications/builtin/telegram/`
  - Adds Telegram as the first builtin notification channel plugin.
  - Keeps notification delivery separate from existing Telegram task input, approval, streaming, topic, and final-reply business paths.
  - Adds a built-in Telegram setup guide through local HTML guide assets.
- Notification plugin discovery/configuration
  - Supports plugin-defined configuration fields.
  - Keeps channel-specific delivery and config shape owned by each notification plugin.
  - Documents the notification plugin directory structure, manifest keys, config fields, and setup guide assets.
- Desktop UI
  - Adds a first-class Notifications menu under the app setup/configuration surface.
  - Shows supported notification apps on the left and selected channel configuration/guide content on the right.
  - Localizes the notification configuration and guide labels.

## Behavior Now Expected

- Runtime code can emit concise task notifications through a provider-neutral notification router.
- Telegram is still the default builtin notification channel.
- Additional channels, such as a future WeChat plugin, can be added behind the notification plugin boundary without scattering app-specific branches through shared runtime code.
- Notification failure handling is scoped per channel, so one notification channel failure does not silently disable all delivery.
- Existing Telegram business message paths remain separate from notification delivery.

## Verification

Source/runtime verification:

```text
rtk pytest -q tests/test_notifications.py tests/test_config.py
Pytest: 49 passed

node --test mac-app/tests/appShell.test.mjs
pass 7/7, later pass 8/8 after upstream app shell changes

cargo fmt --manifest-path mac-app/src-tauri/Cargo.toml --check
pass

cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet
22 passed

git diff --check
pass
```

Installed-app verification:

```text
bash scripts/build.sh
DMG: mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.2.1_aarch64.dmg
```

The installed `/Applications/OnlineWorker.app` was overwritten from the generated DMG and relaunched. Runtime checks confirmed:

- Installed version: `1.2.1`
- Installed app and bot binary hashes matched the mounted DMG.
- New `onlineworker-app` and `onlineworker-bot` processes launched from `/Applications/OnlineWorker.app`.
- `provider_owner_bridge.sock` and `codex_owner_bridge.sock` were connectable.
- `provider_owner_bridge` runtime status reported Codex app-server healthy.
- Recent startup logs did not show traceback, panic, provider error, bridge error, or permission routing errors for the verification window.

## Follow-up: Codex TG Message Routing Regression

After pulling the latest provider interaction approval work, the default Codex app-mode configuration (`protocol=stdio`, `live_transport=owner_bridge`, `control_mode=app`) incorrectly routed ordinary Telegram messages into the local TUI host path. Users saw only the processing acknowledgement without the expected app-server execution path.

The regression was fixed on 2026-05-25:

- Ordinary Telegram messages no longer route to TUI host merely because `live_transport=owner_bridge`.
- External owner bridge / CLI-owned paths can still explicitly allow owner-bridge TUI host routing with `allow_owner_bridge=True`.
- A regression test covers the installed-app equivalent configuration and verifies Telegram messages use the app adapter send path.

Verification:

```text
rtk pytest -q tests/test_codex_tui_mode.py::test_message_handler_in_app_stdio_owner_bridge_mode_uses_app_adapter_for_tg_messages ...
4 passed

rtk pytest -q tests/test_codex_tui_mode.py tests/test_slash_router.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_codex_owner_bridge.py
109 passed

cargo fmt --manifest-path mac-app/src-tauri/Cargo.toml --check
pass

git diff --check
pass
```

The fixed bot was rebuilt with `bash scripts/build.sh`, installed over `/Applications/OnlineWorker.app`, and relaunched. Runtime checks after installation showed:

- Installed version: `1.2.1`
- New app and bot processes launched from `/Applications/OnlineWorker.app`.
- `provider_owner_bridge.sock` and `codex_owner_bridge.sock` were connectable.
- Runtime status reported `codex app-server` healthy.
- Startup error log scan for the verification window returned zero matches.

## Known Remaining Boundary

This phase establishes notification delivery plugins. It does not replace Telegram as an input channel and does not implement non-Telegram builtin notification apps in this repository.
