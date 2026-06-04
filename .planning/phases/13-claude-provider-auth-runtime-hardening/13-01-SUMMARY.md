# 13-01 Summary: Claude Provider Auth Runtime Hardening

**Status:** completed; source-verified; fast packaged build/install/restart verified; Claude TG UAT accepted
**Completed source verification:** 2026-06-04
**Completed packaged verification:** 2026-06-04
**Completed user acceptance:** 2026-06-04

## What Changed

- Added a non-secret Claude readiness contract in
  `plugins/providers/builtin/claude/python/adapter.py`.
- Normalized `claude auth status` outcomes into explicit readiness reasons:
  `ok`, `loggedOut`, `missingCli`, `emptyAuthStatus`, `unknownAuthStatus`, and
  `authStatusFailed`.
- Preserved explicit runtime env support while rejecting stale localhost proxy
  env and removing active-process env scanning from normal send readiness.
- Forced readiness refresh before each Claude send, so a stale cached ready
  state cannot mask a later CLI logout.
- Added Claude runtime preflight before Telegram provider sends call
  `resume_thread` or `send_user_message`.
- Converted Claude provider `status:error` send results into visible Telegram
  send failures.
- Updated `/status` and provider owner bridge runtime status to show unavailable
  Claude as degraded instead of healthy.
- Added `scripts/claude_readiness_smoke.py`, a sanitized live diagnostic that
  calls the real local Claude readiness path without packaging or printing
  tokens. The script also emits `methods[]` so users can see the currently
  selected provider method and other detected candidate methods such as
  current-process runtime env, configured CLI, PATH `claude`, and the
  `ow-claude` wrapper.
- Added explicit, opt-in Claude `launch_methods` support. When configured,
  OnlineWorker tests launch commands in order, selects the first usable method,
  and sends through that selected command. If `launch_methods` is absent, the
  existing single `bin: claude` behavior remains unchanged.
- Added capability-driven Settings UI support for editing multiple launch
  commands, one per line. Provider cards expose this only when the provider
  manifest declares `capabilities.launch_methods`; Claude currently declares
  that capability. Saving writes user config only; it does not add bundled
  default launch commands or hardcode any private launcher.

## User-Visible Behavior

- When `claude auth status` reports `loggedIn:false`, Dashboard/provider status
  can show Claude as unavailable before the user sends traffic.
- Sending a Telegram message to a Claude topic while Claude is unavailable gets
  an immediate provider-unavailable failure.
- Logged-out Claude does not spawn the normal `claude -p` subprocess.
- A user can explicitly configure fallback launch commands from the provider
  card when that provider declares `capabilities.launch_methods`. The current
  machine verified `claude` as logged out and
  `/Users/wxy/.nvm/versions/node/v20.20.1/bin/raven cc` as ready when supplied
  as an explicit configured candidate.
- The surfaced message is non-secret:

```text
Claude provider unavailable: Claude CLI is not logged in.
```

## Verification

Passed:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_claude_adapter.py
# 38 passed
```

Passed:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q \
  tests/test_config.py \
  tests/test_claude_readiness_smoke.py \
  tests/test_claude_adapter.py \
  tests/test_claude_runtime.py \
  tests/test_handlers.py \
  tests/test_startup_runtime.py \
  tests/test_provider_owner_bridge.py
# 193 passed
```

Frontend/config source checks passed:

```bash
cd mac-app && ./node_modules/.bin/tsc
# passed

node --test tests/appShell.test.mjs tests/settingsProviders.test.mjs tests/configProviders.test.mjs
# 18 passed

cd mac-app/src-tauri && cargo test config_provider --lib
# 36 passed

git -C OnlineWorker diff --check
# passed
```

Live diagnostic for the default single-command path passed against the current
machine:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --claude-bin claude
# readiness.ready=false
# readiness.reason=loggedOut
# readiness.authMethod=none
# readiness.source=cliAuth
# methods.configured_cli.selected=true
# methods.configured_cli.available=false
# methods.ow_claude_wrapper.detected=true
# methods.ow_claude_wrapper.available=false
# methods.ow_claude_wrapper.selected=false
```

Live diagnostic for explicit multi-launch-method config passed against the
current machine using a temporary config file under `/tmp`:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --config /tmp/onlineworker-claude-launch-methods-smoke.yaml
# configured_launch_methods=[native, raven]
# methods.native.ready=false
# methods.native.reason=loggedOut
# methods.raven.ready=true
# methods.raven.selected=true
# readiness.ready=true
# readiness.launchMethod.id=raven
```

Production build now passes in the packaged flow:

```bash
bash build.sh
# passed
# DMG: mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.4.0_aarch64.dmg
```

Fast packaged verification passed:

```bash
bash verify-packaged-fast.sh
# Combined fast packaged verification complete (103s)
# DMG sha256: eb5520e61691f8770621a2429ea24d8ddadd532ba55a7072c29ab72ae4bab9bc
# installed /Applications/OnlineWorker.app
# installed version: 1.4.0
# installed onlineworker-bot sha256: 6a5b1eb4c4480259ab635977a98a060e0e3ba66cb81ee5fbe7b04fd0ef8f1ceb
# installed onlineworker-app sha256: 30c8498c20c51315db7f58be0df6517566f08bdb61c2ef4781f5e3d03a7ff1cd
# running: /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app
# running: /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir ~/Library/Application Support/OnlineWorker
# bundled private plugins verified:
#   /Applications/OnlineWorker.app/Contents/Resources/provider-plugins/codemaker/plugin.yaml
#   /Applications/OnlineWorker.app/Contents/Resources/notification-plugins/popo/plugin.yaml
```

Installed runtime log check:

- The first Telegram bootstrap attempt after install hit a transient
  `httpx.ConnectError`, then OnlineWorker auto-restarted after 5 seconds.
- The second bootstrap succeeded with Telegram `getMe` returning `HTTP/1.1 200 OK`.
- Startup then launched `provider_owner_bridge.sock`, Codex remote Unix proxy,
  and `codemaker serve`; codemaker health check passed.

Installed Claude readiness/status smoke passed:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --owner-bridge-status
# owner_bridge_status.ok=true
# owner_bridge_status.health=degraded
# owner_bridge_status.detail="Claude CLI is not logged in."
```

Final packaged install and user acceptance passed after explicit configured
launch methods were validated on the installed app:

```bash
bash verify-packaged-fast.sh
# Combined fast packaged verification complete (97s)
# DMG sha256: 2b28968e55530ce616ea5545ddcdb9591811cb2e25d16cb15d8f3414ddf17d2f
# installed /Applications/OnlineWorker.app
# installed version: 1.4.0
# running: /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app
# running: /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir ~/Library/Application Support/OnlineWorker
# bundled private plugins verified:
#   /Applications/OnlineWorker.app/Contents/Resources/provider-plugins/codemaker/plugin.yaml
#   /Applications/OnlineWorker.app/Contents/Resources/notification-plugins/popo/plugin.yaml
```

Installed readiness smoke after the final package confirmed the configured
Raven launch method and owner bridge status:

```bash
/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --owner-bridge-status --data-dir "$HOME/Library/Application Support/OnlineWorker" --timeout 12
# configured_bin=/Users/wxy/.nvm/versions/node/v20.20.1/bin/raven cc
# readiness.ready=true
# readiness.authMethod=oauth_token
# readiness.apiProvider=firstParty
# readiness.launchMethod.id=primary
# owner_bridge_status.ok=true
# owner_bridge_status.health=healthy
# owner_bridge_status.detail="• claude CLI：✅ 已连接"
```

User acceptance:

- User refreshed/validated the installed app after the final package and replied
  `可以了` on 2026-06-04.
- The final accepted configuration kept the user-supplied launch candidates:

```text
/Users/wxy/.nvm/versions/node/v20.20.1/bin/raven cc
claude
```

## Remaining Verification

None for Phase 13. Future regressions should use
`scripts/claude_readiness_smoke.py --owner-bridge-status` plus a real Claude
topic send check before release packaging.
