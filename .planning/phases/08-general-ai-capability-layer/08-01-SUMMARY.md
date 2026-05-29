# Phase 8 Plan 08-01 Summary: General AI Capability Layer

**Updated:** 2026-05-29
**Status:** Completed and packaged-app verified

## Scope Closed

Plan 08-01 added a reusable AI capability layer and the first AI-backed product scenario:

- Core AI runtime
  - Added `core/ai/` service, scenario, prompt rendering, schema validation, and direct HTTP client boundaries.
  - Supports OpenAI-compatible chat and Claude Messages protocols through direct requests.
  - Keeps AI calls separate from provider CLI runtimes, provider sessions, agent sessions, and Telegram topics.
- Configuration model
  - Added top-level `ai.services` and `ai.scenarios`.
  - Service configuration owns API key, request URL or endpoint, supported models, selected/default model, timeout, protocol, and enablement.
  - Scenario configuration owns enablement, selected service, output schema, fallback policy, limits, and prompt template.
  - The `notification_summary` scenario selects one configured service; multiple enabled services are not called in priority order.
- Desktop UI
  - Added top-level sidebar `AI` tab.
  - Added fixed OpenAI and Claude service cards; users do not type service id, protocol, or environment variable names.
  - Matched the Notifications settings layout with left-side navigation, right-side details, and enable switches in the detail header.
  - Added service connection testing through `test_ai_service_connection`.
  - Added scenario editing where the user selects a configured service; model choice follows the selected service.
- Notification summary
  - Routes completion notification title/body extraction through the `notification_summary` AI scenario when enabled.
  - Uses `preview_title` as the notification preview title and `summary` as the notification body summary when AI output validates.
  - Preserves deterministic local summary rules as fallback when AI is disabled, unavailable, invalid, or unsupported.
  - Keeps preview title length limiting in the scenario/fallback boundary and does not apply the old body truncation to AI summary output.
  - Supports external local summary rule files for deterministic fallback updates without rebuilding the app.

## Behavior Now Expected

- A user configures OpenAI or Claude from the AI tab without managing provider sessions or environment variable names.
- A user enables a scenario separately from enabling a service.
- A scenario selects exactly one service and uses that service's configured model.
- Notification completion summaries can use AI when configured, and otherwise fall back to local deterministic rules.
- AI-backed notification summary does not create Codex, Claude, provider, or Telegram conversation history.

## Verification

```text
PYENV_VERSION=3.13.1 pytest -q tests/test_ai_config.py tests/test_ai_scenarios.py tests/test_events_streaming.py tests/test_notifications.py
59 passed

node --test mac-app/tests/appTabs.test.mjs mac-app/tests/appShell.test.mjs
13 passed

cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet
30 passed

cargo test --manifest-path mac-app/src-tauri/Cargo.toml ai_config --quiet
3 passed

cd mac-app && ./node_modules/.bin/tsc --noEmit
passed

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

## Follow-Up Boundaries

- Adding more scenarios should reuse `core/ai/` and `ai.scenarios`; it should not add prompt fields to service API settings.
- Adding more AI protocols should extend the direct AI client boundary, not provider CLI session logic.
- Local deterministic summary rules remain the fallback and can be adjusted externally when AI output is not configured or not desired.
