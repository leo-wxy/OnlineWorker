# Roadmap: OnlineWorker

## Completed Milestones

- [v1.2.1](milestones/v1.2.1-ROADMAP.md): UI foundation, provider usage explorer, file/image support, Claude safe resume, and provider session error visibility.

## Current Milestone

**Theme:** General AI Capability and Session Operations

This milestone adds a shared AI capability layer and strengthens user-visible session operations. AI service connection settings stay separate from per-scenario prompt settings, so notification summary can be the first consumer while future scenarios reuse the same capability boundary. Session archive actions must execute against the real provider source and only update local state after the provider archive succeeds.

## Phases

- [x] **Phase 6: Notification Channel Abstraction** - Introduce a provider-neutral notification mechanism so OnlineWorker can emit concise notifications through enabled notification plugins. Core plugin/router/config UI is implemented; existing Telegram task/approval/final-reply paths remain unchanged.
- [x] **Phase 7: OnlineWorker User Message Gateway** - Route provider-bound user text through an OnlineWorker-level gateway before provider-specific send hooks. Gateway/proxy boundaries are complete; civility rewrite is paused, related App entry points are hidden, and packaged-app verification is complete.
- [x] **Phase 8: General AI Capability Layer** - Add a top-level AI sidebar tab plus a provider-neutral AI capability layer. Service API settings and scenario prompt settings are separate; notification summary is the first scenario, current local summary rules remain the fallback, and packaged-app verification is complete.
- [x] **Phase 9: Session Archive Actions** - Add Session tab archive actions and adjacent provider usage operations. Archive executes the provider's real source operation, archived rows remain visible through post-success local overlay, `/token_usage` is scoped to agent topics, and packaged-app verification is complete.
- [ ] **Phase 10: Codebase Structure Refinement** - Audit and restructure oversized classes/modules and misplaced responsibilities without changing product behavior. Focus on clearer ownership boundaries, smaller cohesive units, and safer extension points for provider, notification, AI, session, and UI runtime code.

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
**Plans:** 2 plans

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

### Phase 8: General AI Capability Layer

**Goal:** Add shared AI configuration and runtime support that can power multiple OnlineWorker scenarios through prompt-driven configuration, starting with notification completion summary.
**Requirements**: TBD
**Depends on:** Phase 6
**Plans:** 2 plans

Plans:
- [x] 08-01: Add general AI capability layer and first-class AI configuration tab
  - [x] Add `core/ai/` service/scenario contracts, config parsing, direct runtime adapters, prompt rendering, and fallback signaling.
  - [x] Add sidebar top-level `AI` tab with separate `Services` and `Scenarios` configuration surfaces.
  - [x] Wire notification summary through the `notification_summary` scenario while preserving local summary rules as fallback.
  - [x] Add service connection testing and store service API settings through the normal AI config flow, without requiring users to manage environment variable names.
  - [x] Keep notification preview title limiting in the scenario/fallback boundary while avoiding legacy body truncation for AI summaries.

Success Criteria (what must be TRUE):
  1. `AI` is a first-class sidebar tab, not a nested `Setup` or notification-only control.
  2. OpenAI and Claude are fixed built-in service choices in the AI tab; users do not type protocol, service id, or environment variable names.
  3. API key, endpoint/Base URL, model list, selected/default model, timeout, and enablement are service connection settings.
  4. Prompt template, selected service, output schema, limits, enablement, and fallback policy are scenario settings.
  5. A scenario selects exactly one configured service. Multiple enabled services are not called in priority order.
  6. Scenario model selection follows the selected service's configured model; the scenario page does not require manual model entry.
  7. The AI settings UI follows the Notifications settings layout, including an enable switch in the detail header top-right area.
  8. Notification completion summary is implemented as the first scenario/function and can be disabled independently.
  9. Existing deterministic local summary rules still run when AI is unavailable, disabled, or invalid.
  10. AI calls do not create provider sessions, Codex sessions, Claude sessions, or Telegram topics.

Fast verification path:
- Use source/dev verification for UI iteration: `cd mac-app && ./node_modules/.bin/tsc --noEmit && npm run tauri dev`.
- Use focused Python/Node/Rust tests for behavior regressions.
- Run packaged-app verification only after explicit approval or release validation.

Latest verification:
- Source verification passed:
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_ai_config.py tests/test_ai_scenarios.py tests/test_events_streaming.py tests/test_notifications.py` -> passed.
  - `node --test mac-app/tests/appTabs.test.mjs mac-app/tests/appShell.test.mjs` -> passed.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet` -> `30 passed`.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml ai_config --quiet` -> `3 passed`.
  - `./node_modules/.bin/tsc --noEmit` from `mac-app/` -> passed.
  - `npm run tauri dev` from `mac-app/` -> Vite/Tauri dev startup passed.
  - `git -C OnlineWorker diff --check` -> passed.
- Packaged-app verification passed after explicit approval: `bash verify-packaged-fast.sh` -> `Combined fast packaged verification complete (103s)`.
  - DMG: `OnlineWorker/mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.3.0_aarch64.dmg`
  - SHA256: `3f0fb03b277c6926c7cd753f3fbe1dddfc92f2f664e2020528defefc4a5c04d6`
  - Installed runtime: `/Applications/OnlineWorker.app`

Remaining Phase 8 verification:
- None for the general AI capability layer and notification summary scenario. Future AI scenarios remain separate phase work.

### Phase 9: Session Archive Actions

**Goal:** Let users archive concrete sessions directly from the Session tab without creating a local-only illusion. The UI action must call the provider-backed real archive operation, surface errors, and then refresh the session list after local archived state is persisted.
**Requirements**: TBD
**Depends on:** Phase 7 provider owner/session bridge boundaries
**Plans:** 1 plan

Plans:
- [x] 09-01: Add provider-backed Session tab archive action
  - [x] Add a right-click context menu and visible row action menu on Session tab session rows.
  - [x] Add a Tauri archive command that invokes a real provider archive operation through the running owner bridge or a real sidecar archive path.
  - [x] Use sidecar archive only when owner bridge transport is unavailable; provider-reported archive failures are returned to the UI directly.
  - [x] Persist local `onlineworker_state.json` archived state only after the real provider archive succeeds.
  - [x] Merge post-success archived overlays back into provider session lists so Archived view remains useful when a provider source omits archived rows.
  - [x] Show a visible UI error when the real archive fails; do not hide, mark, or move the session on failure.
  - [x] Expose provider usage through provider metadata/hooks and add `/token_usage` as an agent-topic local bot command.

Success Criteria (what must be TRUE):
  1. Right-clicking a concrete session row or opening its visible row action menu in the Session tab exposes an Archive action.
  2. Archive calls the provider's real source archive path; there is no local-only archive fallback.
  3. Providers without real archive support return a clear failure instead of silently marking the session archived.
  4. Local archived state changes only after the provider archive succeeds.
  5. The selected session and list refresh correctly after a successful archive, and archived rows remain visible in the Archived filter through post-success local overlay if the source no longer returns them.
  6. Focused Python, Rust, Node, and TypeScript checks cover the command boundary and UI entry point.
  7. Usage-capable providers appear in the Usage tab dynamically, and `/token_usage` rejects non-agent topics clearly.

Fast verification path:
- Use focused source verification for this phase:
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py`
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml provider_sessions --quiet`
  - `node --test mac-app/tests/sessionArchiveContextMenu.test.mjs`
  - `cd mac-app && ./node_modules/.bin/tsc --noEmit`
- Run packaged-app verification only after explicit approval.

Latest verification:
- Focused source verification passed:
  - `PYENV_VERSION=3.13.1 python -m pytest -q OnlineWorker/tests/test_provider_session_bridge.py OnlineWorker/tests/test_provider_owner_bridge.py` -> `45 passed`.
  - `cargo test --manifest-path OnlineWorker/mac-app/src-tauri/Cargo.toml provider_sessions --quiet` -> `13 passed`.
  - `node --test OnlineWorker/mac-app/tests/sessionArchiveContextMenu.test.mjs` -> `2 passed`.
  - `cd OnlineWorker/mac-app && ./node_modules/.bin/tsc --noEmit` -> passed.
  - `git -C OnlineWorker diff --check` -> passed.
- Additional archived overlay verification passed:
  - `cd OnlineWorker/mac-app/src-tauri && cargo test provider_sessions::tests --lib` -> `14 passed`.
  - `node --test OnlineWorker/mac-app/tests/sessionArchiveContextMenu.test.mjs` -> `2 passed`.
  - `cd OnlineWorker/mac-app && ./node_modules/.bin/tsc --noEmit` -> passed.
  - `python3 -m pytest OnlineWorker/tests/test_provider_session_bridge.py -q` -> passed.
- Provider usage and `/token_usage` verification passed:
  - `PYENV_VERSION=3.13.1 python -m pytest -q tests/test_provider_session_bridge.py tests/test_provider_owner_bridge.py tests/test_slash_router.py tests/test_command_rules.py tests/test_notifications.py tests/test_events_streaming.py` -> `118 passed`.
  - `node --test mac-app/tests/sessionArchiveContextMenu.test.mjs mac-app/tests/usageBrowser.test.mjs mac-app/tests/usageProviders.test.mjs` -> `5 passed`.
  - `git -C OnlineWorker diff --check` -> passed.
- Packaged-app verification passed after explicit approval: `bash verify-packaged-fast.sh` -> `Combined fast packaged verification complete (103s)`.
  - DMG: `OnlineWorker/mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.3.0_aarch64.dmg`
  - SHA256: `3f0fb03b277c6926c7cd753f3fbe1dddfc92f2f664e2020528defefc4a5c04d6`
  - Installed runtime: `/Applications/OnlineWorker.app`

Remaining Phase 9 verification:
- None for provider-backed session archive action. Providers without real archive support intentionally continue to fail clearly.

### Phase 10: Codebase Structure Refinement

**Goal:** Reduce structural debt across the app by splitting oversized classes/modules, moving misplaced responsibilities behind existing boundaries, and making future provider/plugin/UI changes easier to reason about without changing user-facing behavior.
**Requirements**: TBD
**Depends on:** Phase 9
**Plans:** 3 plans

Initial focus areas:
- Identify oversized or high-churn classes/modules in Python bot/runtime code, Tauri command/state code, and frontend app shell/components.
- Separate orchestration, persistence, provider-specific behavior, plugin contracts, UI state, and presentation logic where they are currently coupled.
- Preserve existing public provider/plugin boundaries and avoid reintroducing hardcoded provider wiring into shared app surfaces.
- Keep behavior stable through characterization tests before large splits, especially for session send/archive, notification delivery, AI scenario runtime, and packaged-app startup.
- Prefer staged, reviewable refactors over broad rewrites so each step can be verified independently.

Success Criteria (what must be TRUE):
  1. The largest and most coupled classes/modules are inventoried with concrete ownership problems and proposed target boundaries.
  2. Each refactor plan includes behavior-preserving verification before implementation.
  3. Shared provider, notification, AI, and session contracts remain stable or receive explicit migration notes.
  4. UI state/presentation splits reduce duplicated or cross-feature state mutations without changing visible workflows.
  5. Packaged-app validation remains available for any refactor touching startup, sidecar, provider bridge, or Tauri command boundaries.

Fast verification path:
- Start with codebase mapping and characterization tests before moving code.
- Use focused Python/Node/Rust/TypeScript checks for each structural slice.
- Run packaged-app verification only for slices touching app startup, sidecar packaging, bridge IPC, or installed-app behavior.

Plans:
- [x] 10-01: Audit structure debt and establish staged refactor rails
  - [x] Create a ranked structure-debt inventory from real code metrics.
  - [x] Add a full-repository static structure audit with language, size, boundary, long-unit, and test-map evidence.
  - [x] Lock a behavior-preserving verification matrix.
  - [x] Select the first safe implementation slices for later refactor plans.
- [x] 10-02: Extract Tauri config and dashboard helper modules
  - [x] Split config provider assets/metadata helpers behind the existing command surface.
  - [x] Split dashboard provider status helpers behind the existing command surface.
  - [x] Split dashboard recent activity helpers behind the existing command surface.
  - [x] Preserve public Tauri command names and response shapes.
- [x] 10-03: Extract Python workspace pure helpers
  - [x] Split workspace topic/callback/history pure helpers into `workspace_helpers.py`.
  - [x] Preserve existing Telegram callback data and private helper import compatibility.
  - [x] Add focused helper characterization tests.
  - [x] Preserve provider lookup, topic creation, and storage persistence behavior.

Latest verification:
- Planning/static verification passed: `git diff --check`.
- Structure audit anchors present: `rg -n "config_provider.rs|dashboard.rs|bot/events.py|Dashboard.tsx|Verification Matrix|Selected Slices" .planning/phases/10-codebase-structure-refinement/10-RESEARCH.md .planning/phases/10-codebase-structure-refinement/10-01-PLAN.md`.
- Full audit evidence captured in `10-CODEBASE-AUDIT.md`: source/test counts, longest files, Python/Rust/TS long units, dependency-boundary findings, provider-specific branch findings, and test coverage map.
- 10-02 focused Rust verification passed:
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet` -> `32 passed`.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet` -> `21 passed`.
  - `git diff --check` -> passed.
- 10-03 focused Python verification passed:
  - `/Users/wxy/.pyenv/shims/python3.13 -m pytest -q tests/test_workspace_helpers.py tests/test_workspace_thread_open.py tests/test_thread_controls.py` -> `48 passed`.
  - `git diff --check` -> passed.
- GSD consistency passed: `node ~/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency` -> `passed: true` with existing warnings for older phase artifacts.

Remaining Phase 10 verification:
- Next production-code refactor slice is pending 10-04 planning/execution.
