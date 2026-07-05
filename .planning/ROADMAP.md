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
- [x] **Phase 10: Codebase Structure Refinement** - Audit and restructure oversized classes/modules and misplaced responsibilities without changing product behavior. Completed staged refactor slices for Tauri config/dashboard helpers, Python workspace helpers, and frontend Dashboard state/presentation.
- [x] **Phase 11: Telegram Topic SQLite Storage Migration** - Make Telegram topics independent durable records in a single SQLite table, migrate existing JSON topic ids once, and route all topic lookups through SQLite so runtime JSON saves cannot erase topic bindings. Full regression, Dashboard Telegram polling visibility, packaged build, and installed-app verification are complete.
- [x] **Phase 12: Codex Managed App-Server Approval Host** - Follow the Paseo/Happy/Codex IDE host-client model: OnlineWorker-managed Codex sessions own the app-server request/response channel, Telegram is the remote approval UI for those sessions, and existing Desktop/VS Code/ordinary CLI sessions stay native and mirror-only. 12-02 implements `unix://` support and the installed fixed OnlineWorker Unix remote proxy; fixed-session shared CLI + TG authorization convergence has been user-accepted through `codex_remote_proxy.sock`.
- [x] **Phase 13: Claude Provider Auth Runtime Hardening** - Replace the current fragile Claude runtime/auth fallback with an explicit, durable provider readiness contract. Telegram/provider sends now fail fast with visible diagnostics when Claude auth is unavailable, Dashboard/status paths surface the same reason before user traffic, active-process environment scanning is removed from the normal readiness path, and Claude can opt into user-configured multi-launch-method readiness through a generic Settings UI shown for providers that declare `capabilities.launch_methods`. Source verification, fast packaged build/install/restart verification, installed configured launch-method readiness, owner-bridge healthy status, and user UAT are complete.
- [x] **Phase 14: Unified Message Event Bus** - Establish a single OnlineWorker message/event bus so Telegram, App sessions, TaskBoard, notifications, approvals, questions, and future surfaces consume the same normalized event stream instead of each owning separate message-handling logic. 14-01 through 14-04 are source verified; fast packaged build/install/restart verification passed after the 14-04 TaskBoard first-paint fix, and the Phase 16 external-ingress follow-up closed the remaining TaskBoard visibility gap.
- [x] **Phase 15: Bus-Driven Rendering And Approval Command Boundary** - Follow up Phase 14 by migrating heavy first-party renderers onto the bus once the event schema is stable: `15-02` App Session detail live-model migration, `15-03` Telegram edge migration, and `15-04` approval/question command-boundary tightening are source verified.
- [x] **Phase 16: Provider External Event Ingress** - Add provider-plugin-owned external event ingress for Claude and distribution-provided provider plugins so externally launched sessions can enter the Phase 14 message bus. Claude uses a marker-based global hook merge; OpenCode-compatible listener behavior is reference-only for compatible provider plugins, not a new product surface. Implementation remains scoped to provider plugin directories plus focused tests and generic bus projection fixes.
- [ ] **Phase 17: Provider Session Core Isolation** - Move provider-private session/workspace parsing and filtering fully behind provider/plugin-owned capabilities so Tauri core, Session Tab, Dashboard/TaskBoard, and Telegram consume one provider-owned source of truth. This phase specifically removes duplicated Claude project parsing/filtering from core and prevents private fields such as Claude `entrypoint` from leaking into provider-neutral surfaces.
- [ ] **Phase 18: Provider Session New Flow** - Make new-session creation provider-backed across App Sessions and Telegram session topics. App `New` creates a real provider session with the first message instead of a local draft; Telegram `/new <initial message>` in an existing session topic is source-verified to create a new provider-backed session/topic under the same workspace instead of sending to the current session. The next follow-up is code convergence into a shared provider-backed new-session core service while preserving App and Telegram transport-specific shells. Installed-app/TG UAT remains before release confidence.

## Phase Details

### Phase 17: Provider Session Core Isolation

**Goal:** Make provider session/workspace behavior fully provider-owned so core/Tauri does not parse provider-private stores, fields, hook payloads, or launch metadata.
**Requirements:** TBD
**Depends on:** Phase 16
**Plans:** 1 plan

Plans:
- [ ] 17-01: Isolate provider session logic from core
  - [ ] Inventory provider-specific Tauri/core session logic.
  - [ ] Define provider-owned session/facts boundary for App, TaskBoard/Dashboard, and Telegram.
  - [ ] Migrate Claude session/workspace reads behind provider/plugin-owned capabilities.
  - [ ] Remove duplicated Claude filtering from core.
  - [ ] Verify App/TG workspace parity for manual CLI sessions, managed sessions, smoke/login failures, and provider-private noise.

Latest verification:
- The current source cleanup follow-up keeps Phase 17 scoped to provider-owned summary surfaces while removing hotfix duplication: `config.py` now shares one loader skeleton for full app config and runtime-safe provider config; SessionBrowser and TaskBoard now share one session-derived preview sanitization helper; TaskBoard pinned/low-signal preview hydration now de-duplicates per-session last-message reads; and `provider_session_bridge.py` now uses one minimal runtime/archive stub builder. Focused checks passed: `node --test OnlineWorker/mac-app/tests/sessionBrowserState.test.mjs` -> `19 passed`, `node --test OnlineWorker/mac-app/tests/taskBoard.test.mjs` -> `29 passed`, `node --test OnlineWorker/mac-app/tests/appShell.test.mjs` -> `19 passed`, `python3 -m pytest OnlineWorker/tests/test_config.py -q` -> `48 passed`, `python3 -m pytest OnlineWorker/tests/test_provider_session_bridge.py -q` -> `24 passed`. Installed-app parity validation remains required before Phase 17 closure.

Success Criteria (what must be TRUE):
  1. Core/Tauri no longer reads Claude project jsonl files directly for workspace or session list behavior.
  2. Claude-specific fields such as `entrypoint` are interpreted only by the Claude provider/plugin layer.
  3. App Session Tab, TaskBoard/Dashboard recent activity, and Telegram workspace listing share one provider-owned session/workspace truth source.
  4. Meaningful manual Claude CLI workspaces appear consistently in both App and Telegram.
  5. Smoke, login-failed, no-assistant CLI noise, and provider-private noise are filtered consistently.
  6. Focused source tests and installed-app verification pass before closure.

### Phase 6: Notification Channel Abstraction

**Goal:** Add a notification plugin mechanism that keeps Telegram available as one builtin notification plugin while establishing a stable boundary for additional app/channel integrations such as WeChat.
**Requirements:** [NOTIFY-01, NOTIFY-02]
**Depends on:** v1.2.1 archived milestone
**Success Criteria** (what must be TRUE):
  1. Notification callers can emit a `NotificationEvent` to a plugin-based notification router instead of knowing the target app/channel.
  2. Telegram remains the default builtin notification plugin with behavior preserved for current users.
  3. The architecture can register additional notification plugins without adding app-specific branches throughout shared runtime code.
  4. Notification failure handling is explicit enough that one channel failure does not silently break all user-facing delivery.
**Plans:** 2 source-verified

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
**Plans:** 2 plans

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
- [x] 10-04: Extract frontend Dashboard state and presentation
  - [x] Split Dashboard view-model helpers into a dashboard model module.
  - [x] Split Dashboard hero, sidebar, alerts, error state, and provider status list into component-local files.
  - [x] Extend `useDashboardState` with derived provider/control/open-host state.
  - [x] Preserve Dashboard Tauri commands, visible layout, and localized text.

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
- 10-04 focused frontend verification passed:
  - `node --test mac-app/tests/appShell.test.mjs mac-app/tests/dashboardProviderStatus.test.mjs` -> passed.
  - `cd mac-app && ./node_modules/.bin/tsc --noEmit` -> passed.
  - `git diff --check` -> passed.
- Phase 10 full source verification passed:
  - `node --test mac-app/tests/*.test.mjs` -> `90 passed`.
  - `cd mac-app && npm run build` -> passed.
  - `/Users/wxy/.pyenv/shims/python3.13 -m pytest -q` -> `760 passed`.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet` -> `197 passed`.
- GSD consistency passed: `node ~/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency` -> `passed: true` with existing warnings for older phase artifacts.

Remaining Phase 10 verification:
- None for the selected Phase 10 structure refactor slices. Higher-risk event/runtime/startup splits remain future phases.

### Phase 11: Telegram Topic SQLite Storage Migration

**Goal:** Move Telegram topic identity and binding state out of `onlineworker_state.json` into one durable SQLite table. After migration, every topic is an independent record keyed by `(chat_id, topic_id)` with a type such as `global`, `workspace`, `thread`, or `unknown`.
**Requirements**: TBD
**Depends on:** Phase 10
**Plans:** 1 plan

Success Criteria (what must be TRUE):
  1. Existing JSON topic ids from `global_topic_ids`, workspace `topic_id`, and thread `topic_id` migrate into SQLite exactly once.
  2. Topic lookup and routing use SQLite as the only topic truth source after migration.
  3. JSON storage saves no longer create, delete, clear, or overwrite Telegram topic bindings.
  4. Every newly created, observed, archived, invalidated, or manually rebound topic updates SQLite without physically deleting topic history.
  5. Unknown topics are recorded as `unknown` and do not fallback to active workspace or thread routing.
  6. Tests prove migration, routing, topic creation, unknown-topic handling, and cleanup/archive paths cannot lose topic bindings.

Plans:
- [x] 11-01: Migrate Telegram topic storage to one SQLite table

Latest verification:
- Full verification passed on 2026-06-03 after explicit user approval:
  - `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest` -> `811 passed`.
  - `cargo test dashboard --lib` -> `26 passed`.
  - `/Applications/Codex.app/Contents/Resources/node node_modules/typescript/bin/tsc --noEmit` -> passed.
  - `git -C OnlineWorker diff --check` -> passed.
  - `bash build.sh` -> passed and produced `OnlineWorker_1.4.0_aarch64.dmg`.
  - `bash verify-packaged-fast.sh` -> passed, installed `/Applications/OnlineWorker.app`, and verified bundled private plugins.
  - Installed runtime after restart showed Telegram `getUpdates` returning `HTTP/1.1 200 OK`.

### Phase 12: Codex Managed App-Server Approval Host

**Goal:** Follow the host/client model used by reference projects such as Paseo, Happy, and the Codex IDE extension: OnlineWorker owns an OnlineWorker-managed Codex app-server session, receives Codex app-server approval requests, renders Telegram as the remote approval UI, and relays Telegram decisions back to the same app-server request. Existing Codex Desktop, VS Code, and ordinary CLI sessions keep their native approval behavior; OnlineWorker only mirrors them unless it owns the request/response channel. For the local shared visible CLI + TG case, 12-02 implements Codex's `unix://` app-server transport and current real validation should use shared Unix.
**Requirements**: TBD
**Depends on:** Phase 7 provider message gateway and Codex app-server integration boundaries
**Scope Fence:** 12-01 code changes are limited to `plugins/providers/builtin/codex/`. 12-02 explicitly revises scope to include `config.py` because unix transport parsing is outside the Codex plugin. Shared core approval abstractions, non-Codex providers, Mac app UI, notification plugins, and packaging scripts remain out of scope unless the phase plan is explicitly revised.
**Plans:** 4 plans

Plans:
- [x] 12-01: Build OnlineWorker-managed Codex app-server approval host
  - [x] Inventory current Codex approval entry points inside the Codex plugin
  - [x] Compare reference projects: Paseo provider-owned app-server, Happy `happy codex`, and Codex IDE extension host/client behavior
  - [x] Draft Codex plugin implementation that keeps app-server approval lifecycle as the source of truth
  - [x] Add local automated tests for stale TG state cleanup and duplicate request suppression
  - [x] Adjust implementation so hook/current-session mirror paths are notification-only by default
  - [x] Validate real OnlineWorker-managed app-server + Telegram approval flow
- [x] 12-02: Add unix-socket shared Codex app-server transport
  - [x] Confirm local Codex CLI supports `--listen unix://` and `--remote unix://...`
  - [x] Identify current OnlineWorker gaps: config accepts only `stdio/ws/http`, process starts only `stdio/ws`, adapter connects only stdio/ws
  - [x] Add `unix` / `shared_unix` config normalization
  - [x] Add app-server process startup and adapter connection for WebSocket over Unix socket
  - [x] Add focused automated coverage for config, adapter, startup, and TUI shared transport behavior
  - [x] Validate installed fixed Unix remote proxy startup and CLI entry command
  - [x] Validate fixed-session visible Codex CLI + Telegram approval convergence on the same app-server request id over the OnlineWorker Unix proxy
  - [x] Keep loopback WebSocket as fallback shared transport only

Success Criteria (what must be TRUE):
  1. OnlineWorker-managed Codex sessions follow the reference host/client pattern: OnlineWorker owns the app-server request/response channel.
  2. Telegram receives an interactive approval prompt for app-server requests only when OnlineWorker owns the request id and has a reliable thread/topic mapping; non-app-server controls require an explicit controlled-host path or opt-in blocking hook.
  3. App-server Telegram decisions are written back to the same app-server JSON-RPC request id through the active Codex adapter.
  4. Codex app-server remains the approval lifecycle source of truth; OnlineWorker does not complete Codex items locally.
  5. If app-server resolves the request first, Telegram state is cleared or marked stale/resolved instead of staying active.
  6. Existing Codex Desktop, VS Code, and ordinary CLI approval behavior does not regress; OnlineWorker does not intercept or replace those clients.
  7. Hook/current-session mirror paths are notification-only by default and do not create clickable approval controls unless an explicit controlled-host path or opt-in blocking hook exists.
  8. Requests without a reliable thread/topic mapping do not fall back to a global topic with clickable approval controls.
  9. Duplicate or stale app-server approval requests do not create multiple active approval buttons for the same Codex request.
  10. 12-01 production implementation changes stay under `plugins/providers/builtin/codex/`.
  11. 12-02 supports `unix://` as the preferred local shared app-server transport while preserving `ws://127.0.0.1:<port>` as fallback and `stdio://` as private owner transport.
  12. Visible CLI tests use the OnlineWorker proxy socket, not bare `--remote unix://`, when the goal is Telegram approval mirroring and control.

Reference projects and behavior:
- `getpaseo/paseo`: Provider-owned Codex app-server client registers app-server approval request handlers, stores pending permissions, and replies through the same request id.
- `slopus/happy`: `happy codex` wraps Codex by starting `codex app-server --listen stdio://`, routing approval requests to its own UI/mobile flow, then responding to app-server.
- Codex IDE extension: Official host/client shape using Codex CLI and shared `~/.codex/config.toml`; useful as the product analogy for "OnlineWorker can be a Codex host", not as evidence for attaching to an already running Desktop session.

Fast verification path:
- Use focused Codex provider tests only:
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_codex_adapter.py tests/test_events_streaming.py tests/test_question_enhanced.py tests/test_codex_tui_mode.py tests/test_startup_runtime.py tests/test_codex_runtime.py`
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_config.py tests/test_codex_runtime.py tests/test_startup_runtime.py tests/test_codex_tui_mode.py tests/test_provider_owner_bridge.py`
  - `git -C OnlineWorker diff --check`
- Run packaging or installed-app verification only after explicit approval.

Local automated checks:
- Passed locally, not a substitute for real app-server/TG validation:
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_codex_adapter.py tests/test_events_streaming.py tests/test_question_enhanced.py tests/test_codex_tui_mode.py tests/test_startup_runtime.py tests/test_codex_runtime.py` -> `225 passed`.
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_codex_hook_bridge.py tests/test_codex_runtime.py tests/test_provider_owner_bridge.py tests/test_startup_runtime.py tests/test_codex_tui_mode.py` -> passed before the main merge; current merge verification uses the focused Codex/bridge suite listed in this handoff.
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_events.py tests/test_codex_interactions.py tests/test_session_events.py` -> `53 passed`.
  - `PYENV_VERSION=3.13.1 pytest -q tests/test_config.py tests/test_codex_adapter.py tests/test_startup_runtime.py tests/test_codex_tui_mode.py` -> `182 passed`.
  - `git -C OnlineWorker diff --check` -> passed.

Real installed-app app-server/TG approval chain:
- Verified on 2026-06-01 through the running installed app, without packaging or restart.
- Existing installed runtime was active:
  - `/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app`
  - `/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker`
  - OnlineWorker-managed `codex app-server --disable hooks --listen stdio://`
- App-server approval request reached Telegram:
  - `item/commandExecution/requestApproval` `id=1` for thread `019e832b-e486-77a2-8826-4f87b33591d6`.
  - `[approval_request] id=1 ... topic=8634`.
  - `[approval_request] 已推送 tool=codex msg_id=8673`.
- Telegram callback resolved the same app-server request id:
  - `[callback] 收到 callback data='exec_allow:8673:1780322294'`.
  - `reply_server_request sent request_id=1 workspace_id=codex:onlineworker-combined decision=accept payload={"decision": "accept"}`.
  - `[approval] request_id=1 tool=codex reply={'decision': 'accept'}`.

Real transport smoke:
- Official Codex docs and local CLI help confirm `codex app-server --listen unix://`, `--listen unix://PATH`, and `codex --remote unix://PATH` syntax.
- Real arbitrary external custom unix listener startup on this machine failed before OnlineWorker connected:
  - `/opt/homebrew/bin/codex app-server --disable hooks --listen unix:///private/tmp/ow-codex-unix-smoke.sock` -> `Error: Operation not permitted (os error 1)`.
  - Same result with temporary `CODEX_HOME=/private/tmp/ow-codex-home-smoke`.
- Real default unix listener startup with temporary `CODEX_HOME` succeeded:
  - `codex app-server --disable hooks --listen unix://` -> created `app-server-control/app-server-control.sock`.
- Real custom unix listener under `CODEX_HOME/app-server-control/` succeeded:
  - `codex app-server --disable hooks --listen unix:///private/tmp/ow-codex-home-unix-custom/app-server-control/custom.sock` -> created `custom.sock`.
- Real OnlineWorker `CodexAdapter` Unix smoke succeeded:
  - `CodexAdapter.connect("unix://")` -> connected after passing `compression=None` to `websockets.unix_connect`.
  - `model/list` -> returned 1 model.
- Real OnlineWorker `AppServerProcess(protocol="unix")` + `CodexAdapter` smoke succeeded:
  - started `unix://` in 0.11s using socket-readiness polling.
  - adapter connected and `model/list` returned 1 model.
- Real loopback WebSocket startup with temporary `CODEX_HOME` succeeded:
  - `/opt/homebrew/bin/codex app-server --listen ws://127.0.0.1:47999` -> `codex app-server (WebSockets), listening on ws://127.0.0.1:47999`.
- Real OnlineWorker `AppServerProcess` + `CodexAdapter` loopback WebSocket smoke with temporary `CODEX_HOME` succeeded:
  - started `ws://127.0.0.1:50076`, adapter connected, `model/list` returned 1 model.

Latest Phase 12 verification:
- Real OnlineWorker-managed app-server/TG authorization chain is verified for the installed app's current stdio-owned app-server path: TG button maps to the same app-server request id and TG decision relays to app-server.
- User UAT accepted fixed-session visible CLI + Telegram authorization convergence on 2026-06-03 using the installed OnlineWorker Unix proxy socket and a resumed Codex session.
- App-server-first resolution cleanup is covered by focused proxy/event tests and the implemented `serverRequest/resolved` cleanup path.
- Installed fixed OnlineWorker Unix remote proxy validation completed on 2026-06-02:
  - alias/command target: `unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock`.
  - bare `--remote unix://` is documented as direct Codex default-socket access and must not be used to validate OnlineWorker approval mirroring.
  - `/resume` filtering is scoped through the proxy by injecting the client cwd for `thread/list`.
  - `serverRequest/resolved` is forwarded to the CLI and also clears TG mirror pending state.
  - expected relay close/reset exceptions are consumed so normal restart/disconnect does not leave `Task exception was never retrieved`.
  - target tests passed: `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest OnlineWorker/tests/test_codex_remote_proxy.py OnlineWorker/tests/test_codex_runtime.py -q` -> `25 passed`.
  - packaged build/install/restart completed with DMG `OnlineWorker_1.4.0_aarch64.dmg`.
  - installed hashes:
    - `onlineworker-bot`: `50c8d9a63ce61f340193ab0887aae322ae4ace41ffb296366fde33013811945e`
    - `onlineworker-app`: `2a80c905228608eb268ed665ea751bb36e61d214c043b22f0c7b9cad9488cbd0`
  - installed runtime logs confirmed `codex 使用托管默认 unix app-server：unix://`, `已启动 Codex remote Unix proxy：unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock`, `app-server 第 1 次重连成功`, `workspace cwd 已注册：codex:onlineworker-combined`, and `codex-owner-bridge` startup after app restart.
- Merge-main verification completed on 2026-06-02 after rebasing this work onto upstream main commit `e333403` and renumbering the local Codex phase to Phase 12:
  - `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_config.py tests/test_codex_adapter.py tests/test_codex_runtime.py tests/test_codex_remote_proxy.py tests/test_codex_tui_mode.py tests/test_codex_tui_realtime_mirror.py tests/test_question_enhanced.py tests/test_startup_runtime.py tests/test_codex_hook_bridge.py tests/test_provider_owner_bridge.py` -> `291 passed`.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet` -> `21 passed`.
  - `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet` -> `33 passed`.
  - `node --test mac-app/tests/dashboardProviderStatus.test.mjs mac-app/tests/appShell.test.mjs` -> `13 passed`.
  - `cd mac-app && ./node_modules/.bin/tsc --noEmit` -> passed.
  - `git -C OnlineWorker diff --check` -> passed.
- Fixed-session visible CLI + Telegram convergence validation command used for real approval behavior:
  - `codexR resume 019e6c5a-dafa-7153-ab14-c17f16b890c4`
  - trigger an approval-producing command from the resumed CLI session.
  - verify CLI native approval prompt and TG mirror appear for the same request.
  - verify approving from either surface converges without duplicate active TG controls or CLI reset/hang.
- Arbitrary external Unix socket paths still need path-limit investigation; default `unix://` and custom paths under `CODEX_HOME/app-server-control/` are verified.

Remaining Phase 12 verification:
- None for the managed app-server approval host and fixed Unix proxy path. Arbitrary external Unix socket path investigation remains future transport-hardening work.

### Phase 13: Claude Provider Auth Runtime Hardening

**Goal:** Make Claude provider runtime readiness deterministic and user-visible so `Not logged in · Please run /login` cannot keep reappearing as a late provider failure after Telegram already accepted a user message. Claude auth/runtime checks must use an explicit contract, not active-process environment scraping, and every unavailable state must be visible in Dashboard and Telegram before or at send time.
**Requirements**: TBD
**Depends on:** Phase 7 provider send gateway, Phase 9 provider status/error visibility, Phase 11 route stability
**Scope Fence:** This phase is limited to Claude provider auth/runtime readiness, status surfacing, and send preflight. It must not change Codex app-server approval semantics, Telegram route storage, notification plugins, or AI service configuration. It must not log or persist auth secrets in plaintext artifacts.
**Plans:** 1 plan

Plans:
- [x] 13-01: Harden Claude provider auth/runtime readiness
  - [x] Replace process-scanning as a runtime dependency with an explicit Claude readiness probe.
  - [x] Define supported Claude readiness sources: native Claude CLI login status and explicit current-process runtime environment.
  - [x] Support explicit user-configured Claude `launch_methods`, tested in order and selected at send time, without changing bundled defaults.
  - [x] Add Settings Claude-card editing for multiple launch commands, one per line.
  - [x] Remove active Claude process env discovery from the normal readiness/send path.
  - [x] Add status and force-refreshed send-time preflight so unavailable Claude auth fails before spawning a normal provider turn.
  - [x] Surface the exact non-secret reason in Dashboard provider status and Telegram topic responses.
  - [x] Add regression coverage proving `loggedIn:false` does not become a silent or delayed no-response state.

Success Criteria (what must be TRUE):
  1. OnlineWorker no longer depends on `pgrep -x claude` / `ps eww` process scraping to make Claude provider sends work.
  2. Claude provider readiness has one explicit status object with non-secret fields such as `ready`, `source`, `reason`, `checked_at`, and `detail`.
  3. `claude auth status` returning `loggedIn:false` is detected during startup/status refresh and before each send.
  4. When Claude is not ready, Telegram responds promptly in the target topic with a clear provider-unavailable message instead of starting a normal streaming turn.
  5. Dashboard shows Claude as unavailable with the same high-level reason, without requiring the user to inspect logs.
  6. Provider send code does not spawn `claude -p` when preflight proves Claude auth is unavailable.
  7. Any env/config/token handling is redacted in logs, test output, Dashboard payloads, and planning artifacts.
  8. Focused tests cover native CLI logged-in, native CLI logged-out, explicit runtime env, missing CLI, stale env/proxy, and no-active-process cases.
  9. Installed-app verification includes a real negative check for logged-out Claude and a real positive check after a valid readiness source is present.

Known failure evidence from 2026-06-03:
- Installed app received Telegram message in Claude topic `7431`, started a Claude turn, and sent the eventual provider error back through Telegram.
- Runtime log showed `Claude 执行失败 ... error=Not logged in · Please run /login`.
- Local `claude auth status` returned `{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}`.
- Current process list had no active `claude` process, so the existing active-process env fallback had no usable runtime env to reuse.
- Current provider config uses `bin: claude`; the declared `ow-claude` wrapper capability is not a stable provider send auth contract.

Latest source and live diagnostic verification:
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_claude_adapter.py` -> `38 passed`.
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_config.py tests/test_claude_readiness_smoke.py tests/test_claude_adapter.py tests/test_claude_runtime.py tests/test_handlers.py tests/test_startup_runtime.py tests/test_provider_owner_bridge.py` -> `193 passed`.
- `cd mac-app && ./node_modules/.bin/tsc` -> passed.
- `node --test mac-app/tests/settingsProviders.test.mjs mac-app/tests/configProviders.test.mjs` -> `7 passed`.
- `cd mac-app/src-tauri && cargo test config_provider --lib` -> `35 passed`.
- `git -C OnlineWorker diff --check` -> passed.
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --claude-bin claude` -> sanitized live readiness reported `ready=false`, `reason=loggedOut`, `authMethod=none`, `source=cliAuth`; `configured_cli` was selected and unavailable, while `ow_claude_wrapper` was detected but not considered available for provider send.
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --config /tmp/onlineworker-claude-launch-methods-smoke.yaml` -> with explicit native and configured fallback candidates, smoke selected the configured fallback, reported `readiness.ready=true`, and kept `path_claude` logged out.
- `cd mac-app && ./node_modules/.bin/vite build` was attempted but blocked by a local Rollup native optional dependency code-signature failure for `@rollup/rollup-darwin-arm64`; this was not a TypeScript/code failure.
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet` -> `26 passed`.
- `node --test mac-app/tests/dashboardProviderStatus.test.mjs mac-app/tests/appShell.test.mjs` -> `13 passed`.
- `cd mac-app && /Applications/Codex.app/Contents/Resources/node node_modules/typescript/bin/tsc --noEmit` -> passed.
- `git -C OnlineWorker diff --check` -> passed.
- `rg` over Claude provider/runtime/status source and focused tests found no remaining `_scan_active_claude_process_env`, `pgrep`, `ps eww`, `subprocess.check_output`, or active-process-env dependency.

Packaged verification:
- `bash build.sh` -> passed, produced `OnlineWorker_1.4.0_aarch64.dmg`.
- `bash verify-packaged-fast.sh` -> passed, installed `/Applications/OnlineWorker.app`, launched app/bot processes, and verified distribution-bundled provider and notification plugins.
- Installed owner-bridge readiness smoke reported Claude degraded with `Claude CLI is not logged in`.

Final Phase 13 packaged and user verification:
- `bash verify-packaged-fast.sh` -> `Combined fast packaged verification complete (97s)`, DMG sha256 `2b28968e55530ce616ea5545ddcdb9591811cb2e25d16cb15d8f3414ddf17d2f`, installed `/Applications/OnlineWorker.app`, launched app/bot processes, and verified distribution-bundled provider and notification plugins.
- `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 scripts/claude_readiness_smoke.py --owner-bridge-status --data-dir "$HOME/Library/Application Support/OnlineWorker" --timeout 12` -> configured launch command ready, `readiness.ready=true`, `authMethod=oauth_token`, `apiProvider=firstParty`, `launchMethod.id=primary`, owner bridge `health=healthy`, detail `• claude CLI：✅ 已连接`.
- User accepted installed-app UAT on 2026-06-04.

### Phase 14: Unified Message Event Bus

**Goal:** Route all OnlineWorker message and lifecycle activity through one normalized in-process event bus, then let first-party consumers and projections use that shared stream. Message entry points can remain different, but once inside OnlineWorker they must publish a canonical event before any surface-specific handling.
**Requirements**: TBD
**Depends on:** Phase 6 notification channel abstraction, Phase 7 user message gateway, Phase 10 structure rails, Phase 11 route stability, Phase 12 Codex app-server host, Phase 13 provider readiness contract
**Scope Fence:** This phase establishes the internal message/event bus boundary and migrates the first lightweight consumers behind it. It must not rewrite provider adapter protocols, expose a stable public plugin event API, add a persistent event audit/replay log, migrate App Session detail live rendering, migrate Telegram send/edit/topic rendering, change Codex approval ownership semantics, or change notification plugin configuration unless the plan explicitly revises scope. Ordinary runtime logs remain allowed; only per-event persistent audit logging is excluded.
**Plans:** 4 plans

Plans:
- [x] 14-01: Establish unified message event bus and first projections
  - [x] Define canonical `MessageEvent` / session activity contracts and event ids.
  - [x] Add an in-process bus with deterministic publish/subscribe ordering and testable consumers.
  - [x] Publish events from App sends, Telegram sends, owner-bridge sends, provider session events, approval/question requests and answers, final replies, and notification emission.
  - [x] Add a session activity projection that TaskBoard and App-visible status can read.
  - [x] Move notification delivery activity toward the bus by publishing requested/emitted/skipped/failed events.
  - [x] Keep existing Telegram/App delivery behavior compatible while proving both surfaces derive from the same event stream.
  - [x] Fully migrate notification summary generation to consume only canonical final/turn events instead of the legacy completion helper path.
- [x] 14-02: Harden TaskBoard activity stream follow-ups
  - [x] Close the TaskBoard activity stream snapshot/subscribe race.
  - [x] Make stream stop target a concrete stream instance.
  - [x] Bound pinned idle preview hydration.
  - [x] Record verified follow-up scope in Phase 14 docs.
- [x] 14-03: Close consumer boundary cleanup
  - [x] Move completed notification summary local/AI fallback logic under the bus consumer boundary.
  - [x] Remove old completed-summary helper names and file boundary.
  - [x] Remove TaskBoard hidden/remove-from-board state, command, UI action, types, tests, and i18n.
  - [x] Record focused source verification in Phase 14 docs.
- [x] 14-04: Fix TaskBoard running activity first paint
  - [x] Include session activity projection in the initial TaskBoard refresh.
  - [x] Render activity projection before full provider session metadata hydration completes.
  - [x] Clear loading on activity stream snapshot/activity events.
  - [x] Add running-card preview fallback from user intent, activity title, or resolved title.
  - [x] Record focused source verification in Phase 14 docs.

Success Criteria (what must be TRUE):
  1. All provider-bound user sends publish one canonical user-message event after the Phase 7 user message gateway has produced the final text.
  2. Provider runtime events such as turn started, assistant delta, final reply, approval requested, question requested, turn completed, and turn failed are normalized into canonical bus events.
  3. Telegram and App session send/lifecycle activity publish to the bus while their heavy rendering surfaces remain behavior-compatible.
  4. Notification summary is not a separate hidden task-completion pipeline; it consumes the same final-reply/turn-completed events used by other surfaces and old helper boundaries are removed.
  5. TaskBoard cards show useful session/activity information, including provider, workspace, session id, status, recent user/final message summary, and attention reason from the projection.
  6. Approval and question handling keep the same source-of-truth ownership rules from Phase 12 and do not fall back to provider-global topics.
  7. Existing Telegram topic routing from Phase 11 remains the routing source for Telegram consumers.
  8. Existing provider-specific adapters remain behind the provider registry; the bus carries normalized OnlineWorker events, not private provider payloads as the public contract.
  9. The bus has deterministic tests for ordering, dedupe, projection updates, consumer failure isolation, and redaction of sensitive fields.
  10. Migration is incremental: heavy App Session and Telegram rendering migrations are explicitly deferred to Phase 15, not left as implicit Phase 14 scope.
  11. Approval/question bus events are observational lifecycle events in Phase 14; they do not execute commands or grant authorization authority.
  12. Running TaskBoard activities render from the activity projection immediately and do not disappear while slower session metadata hydration is still in progress.

Design reference for future development:
- Inputs: Telegram text/files, App session composer sends, owner-bridge sends, provider-session bridge sends, provider app-server events, CLI/proxy mirrored events, approval callbacks, question answers, and notification requests.
- Canonical event groups: `message.user.submitted`, `message.user.accepted`, `message.assistant.delta`, `message.assistant.final`, `turn.started`, `turn.completed`, `turn.failed`, `approval.requested`, `approval.answered`, `question.requested`, `question.answered`, `notification.requested`, `notification.emitted`.
- Consumers/projections: TaskBoard/session activity projection, notification router and summary consumer, status/dashboard projection, bounded in-memory debug reads, and future App/TG/IM/plugin consumers.
- Durable identity: every event should carry provider id, workspace id/path when available, session/thread id, turn id when available, source surface, event id, created time, dedupe key, and redacted public payload.
- Surface-specific payloads belong at the consumer edge. The bus should not expose Telegram message ids, parse-mode decisions, or provider-private raw payloads as its stable public contract.
- Phase 14 does not persist every event as a structured audit/replay log. Existing runtime logging remains available for warnings, failures, and key diagnostics.
- Phase 14 does not publish a stable third-party plugin event API. Future plugin/IM consumers should use a later, versioned adapter boundary after first-party consumers stabilize the schema.

Fast verification path:
- Python bus/session-event tests:
  - `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_session_events.py tests/test_events_streaming.py tests/test_notifications.py tests/test_provider_owner_bridge.py`
- Frontend TaskBoard/App projection tests:
  - `node --test mac-app/tests/taskBoard.test.mjs mac-app/tests/appTabs.test.mjs mac-app/tests/sessionStreamLifecycle.test.mjs`
  - `cd mac-app && ./node_modules/.bin/tsc --noEmit`
- General hygiene:
  - `git -C OnlineWorker diff --check`
- Packaging, install, app restart, and packaged-app verification require explicit current-conversation approval.

Planning status:
- Phase 14 was added on 2026-06-04 after the user identified the root architecture problem: notifications, Telegram sends, App session display, and TaskBoard cards should not each own separate message-handling logic. They should all consume one OnlineWorker message event bus.
- 14-01 source verification passed on 2026-06-04. The first slice adds `core/messages/`, publishes TG/session-tab/provider/approval/question/notification activity into the bus, exposes session activity projection to TaskBoard, and keeps existing delivery behavior compatible.
- 14-02 source verification passed on 2026-06-05. TaskBoard activity streaming is race-hardened, stream stop is keyed by stream id, and pinned preview hydration is bounded.
- 14-03 source verification passed on 2026-06-05. Completed notification summary fallback logic now lives under the bus consumer boundary, old completed-summary helper names were removed, and TaskBoard hidden/remove-from-board state/action were removed.
- 14-04 source verification passed on 2026-06-05. TaskBoard initial refresh now includes activity projection, stream events clear loading, and running cards use activity/user/title preview fallback so active sessions do not render as empty lanes or blank cards while metadata hydration is still in progress.
- Product decisions from the 2026-06-05 Phase 14 review: App Session detail live rendering and Telegram rendering remain follow-up work; approval/question bus events remain observational in Phase 14; persistent event audit logs and public plugin event APIs are excluded from Phase 14; TaskBoard uses pin/unpin only.
- Fast packaged build/install/restart verification passed on 2026-06-05 after the 14-04 UI follow-up. `verify-packaged-fast.sh` rebuilt `OnlineWorker_1.5.0_aarch64.dmg` with sha256 `42708ebfcea5c4b0df4d22128d90a93c6c94680ac0cbcd45ed661a535fce463c`, installed `/Applications/OnlineWorker.app`, launched app/bot processes, and verified distribution-bundled provider and notification plugins.

### Phase 15: Bus-Driven Rendering And Approval Command Boundary

**Goal:** Continue the Phase 14 migration after the internal bus and first consumers stabilize. App Session detail live updates and Telegram send/edit/topic rendering should become bus-driven first-party consumers, and approval/question lifecycle events should be evaluated for a safe command boundary without violating Phase 12 approval ownership.
**Requirements**: TBD
**Depends on:** Phase 14 Unified Message Event Bus, Phase 11 Telegram route storage, Phase 12 Codex managed app-server approval host
**Scope Fence:** This phase migrates heavy first-party rendering surfaces and designs the approval/question command boundary. It should not add a third-party plugin API, external broker, persistent event audit log, or change Codex approval source-of-truth semantics without a dedicated plan.
**Plans:** 4 planned

Plans:
- [ ] 15-01: Define heavy-consumer migration and command-boundary umbrella
  - [ ] Keep the overall Phase 15 scope, execution order, and verification contract explicit.
  - [ ] Decompose App Session, Telegram, and approval/question authority into narrower plans before implementation.
- [x] 15-02: Migrate App Session detail to a bus-derived live model
  - [x] Replace provider-specific live rendering semantics with canonical bus events while preserving history merge, streaming delta/final behavior, scroll ergonomics, and error states.
  - [x] Keep provider history reads only as initial/historical data.
- [x] 15-03: Migrate Telegram rendering to a bus-derived edge consumer
  - [x] Drive Telegram streaming/final/edit/topic rendering from canonical events while preserving Phase 11 route fail-closed behavior and Phase 12 approval ownership.
  - [x] Keep Telegram-specific ids, parse mode, reply markup, and callback metadata at the Telegram edge.
- [x] 15-04: Define approval/question command boundary
  - [ ] Decide whether approval/question remains event-only or gains an explicit command boundary.
  - [ ] If command handling is added, keep commands separate from immutable lifecycle events and preserve mirrored-only observational semantics.

Success Criteria (what must be TRUE):
  1. App Session detail view can render live user/assistant/turn state from bus-derived events without regressing existing provider session history behavior.
  2. Telegram rendering/editing/topic routing is explained as a bus-derived edge consumer while retaining all Phase 11 route storage guardrails.
  3. Approval/question handling has a clear command/event split. Events describe what happened; commands execute only through authorized owner/callback/app-server paths.
  4. Codex app-server approval source-of-truth from Phase 12 remains intact. OnlineWorker does not invent approval authority from a bus event.
  5. Source verification covers App live rendering, Telegram streaming/final replies, approval/question callbacks, and notification/event bus regressions.

Planning status:
- Phase 15 was added on 2026-06-05 during Phase 14 design review so deferred migration tasks would not be lost.
- Phase 15 explicitly carries App Session detail live rendering migration, Telegram rendering migration, and the approval/question command boundary review that Phase 14 intentionally leaves out.
- Phase 15 was decomposed on 2026-06-08 into `15-02` App Session live-model migration, `15-03` Telegram edge migration, and `15-04` approval/question command-boundary work so execution can proceed in smaller verified slices.
- `15-02` reached source-verified status on 2026-06-09: Session Browser detail now hydrates history from provider reads but consumes live updates from a dedicated owner-bridge bus event stream with focused Python/Rust/Node/TypeScript regression coverage.
- `15-03` reached source-verified status on 2026-06-09: Telegram session rendering now decides streaming/final/abort/topic-title behavior from canonical message events while preserving Telegram-specific formatting, route fail-closed behavior, and existing approval/question ownership paths at the edge.
- `15-04` reached source-verified status on 2026-06-09: approval/question lifecycle events remain observational on the bus, Telegram approval routing now fail-closes when the current thread lacks a bound topic, owner-bridge approval replies require a validated adapter/app-server authority path, and the accepted `codex_remote_proxy` controlled-host path remains intact.

### Phase 16: Provider External Event Ingress

**Goal:** Let externally launched Claude and distribution-provided provider sessions enter the existing Phase 14 message bus through provider-plugin-owned listeners, without adding provider-specific hook/listener logic to core or TaskBoard.
**Requirements**: TBD
**Depends on:** Phase 14 Unified Message Event Bus, Claude provider plugin, provider plugin packaging boundary
**Scope Fence:** Phase 16 is plugin-scoped. Claude plugin owns Claude hook lifecycle and payload mapping. Distribution-provided provider plugins own their own external listener lifecycle and payload mapping, using OpenCode-compatible hook/listener behavior only as a reference where applicable. OpenCode is not implemented as a provider. Core/message bus only receives normalized events; TaskBoard only consumes bus projection.
**Plans:** 2 planned

Plans:
- [x] 16-01: Define plugin-scoped external event ingress
  - [x] Create Phase 16 context with trigger, reference code, and strict core/plugin boundary.
  - [x] Create Phase 16 plan covering Claude plugin ingress, distribution-provider plugin ingress, source validation, and packaged validation gates.
  - [x] Commit Phase 16 planning docs on the Phase 16 branch.
  - [x] Start implementation only after the reference code and modification scope are accepted.
- [x] 16-02: Add Claude plugin external hook ingress
  - [x] Define Claude-plugin-owned global `~/.claude/settings.json` merge, marker, dedupe, and remove-only-own behavior.
  - [x] Map Claude lifecycle hooks into existing normalized provider events.
  - [x] Keep implementation scoped to `OnlineWorker/plugins/providers/builtin/claude/` plus focused tests.
  - [x] Source-verify with automated tests and user-assisted external provider sessions.

Success Criteria (what must be TRUE):
  1. Claude external session ingress is owned by `OnlineWorker/plugins/providers/builtin/claude/`.
  2. Distribution-provided provider plugin ingress is owned by the distribution package, not OnlineWorker core.
  3. OpenCode-compatible behavior is used only as a hook/listener reference mechanism; Phase 16 does not add an OpenCode provider or product surface.
  4. Core/message bus does not manage hooks/plugins, parse provider-private payloads, scan provider-private files, or add provider-specific branches.
  5. TaskBoard does not perform provider-private discovery and continues to consume bus projection only.
  6. Hook/listener install/update/uninstall is marker-based, idempotent, and remove-only-own.
  7. Installed-app validation proves Claude, Codex, and distribution-provided provider sessions enter the bus and refresh TaskBoard state through the same projection.

Planning status:
- Phase 16 was added on 2026-06-06 after Phase 14 UAT showed that external provider sessions could be active while the bus received no provider events.
- The reference decision is explicit: Claude uses marker-based global hook integration; OpenCode-compatible listener behavior is only a reference for compatible provider plugins; OpenCode itself is not an implementation target.
- The modification scope is explicit: implementation code should stay in provider plugin directories, with planning docs and focused tests as the expected non-plugin changes.
- 16-01 planning docs were committed on branch `codex/phase-16-provider-event-ingress`.
- 16-02 is complete: automated source regression passed, installed-app live validation covered Claude, Codex, and the distribution-provided provider flow, TaskBoard attention/running/completed updates, approval buttons, and final message refresh. A follow-up raw approval request id fix was added for Codex app-server approval decisions and revalidated in the installed app.

### Phase 18: Provider Session New Flow

**Goal:** Make new-session creation consistent and real-source-backed across the App Session tab and Telegram session topics, with no local-only draft sessions or current-session misrouting.
**Requirements**: TBD
**Depends on:** Phase 17
**Scope Fence:** This phase covers provider-backed session creation and first-message delivery for App Sessions and Telegram `/new`. It must not reintroduce local `app:*` sessions as visible rows, bypass provider `start_thread`, or change approval/question ownership rules.
**Plans:** 2 plans

Plans:
- [x] 18-01: Unify App and Telegram new-session creation
  - [x] App Session tab `New` opens a first-message composer instead of creating a visible local draft session.
  - [x] App first-message send calls provider-backed `start_session_message`, keeps optimistic text visible on slow provider startup, and selects the real provider session once activity arrives.
  - [x] Codex slow `thread/start` waits for app-server notification before mapping the real thread id and skips duplicate `prepare_send`.
  - [x] Telegram session topic `/new <initial message>` creates a new provider-backed session under the current session's workspace and opens/binds a new Telegram topic.
  - [x] Telegram `/new` must not send the slash command or first message to the current existing session.
  - [x] Empty `/new` behavior remains provider-specific: Codex rejects with a clear initial-message requirement; providers that support empty sessions may continue to create one.
- [x] 18-02: Converge the provider-backed new-session core
  - [x] Extract a shared `start_thread -> materialize real thread -> first-message send` core service under `core/`.
  - [x] Keep App owner-bridge `pending` behavior and Telegram topic bind/rollback as outer surface-specific shells.
  - [x] Preserve provider-owned validation hooks instead of hard-coding provider rules into either entrypoint.

Success Criteria (what must be TRUE):
  1. App `New` creates and selects a real provider session, never a visible `app:*` draft.
  2. App first-message send survives slow Codex `thread/start` by using a pending state and later real activity match.
  3. Telegram `/new <initial message>` inside a session topic creates a separate provider-backed session and a separate Telegram topic under the same workspace.
  4. The original Telegram session topic receives only a confirmation/handoff message, not the new conversation content.
  5. Codex and Claude follow the same generic thread handler boundary where possible, with provider-specific validation kept in provider hooks.
  6. Focused slash-router/thread tests cover session-topic `/new`, workspace-topic `/new`, Codex empty-message rejection, and no current-session passthrough.
  7. Packaged-app verification is run before release/tag confidence when this phase changes installed runtime behavior.

Planning status:
- Phase 18 was added on 2026-07-05 after App Session `New` was implemented and real Codex installed-app validation proved a new provider-backed session could be created with the first message.
- Telegram session-topic `/new <initial message>` is source-verified to reuse the same product semantics from App `New`: create a new real provider session under the current workspace and route subsequent conversation to the new session/topic. The fix keeps `/new` confirmation and Codex empty-message validation in the source session topic instead of replying in the workspace topic.
- Verification passed: `pytest -q tests/test_slash_router.py tests/test_workspace_thread_open.py tests/test_thread_helpers.py tests/test_im_route_store.py` -> `57 passed`; `node --test mac-app/tests/sessionNewComposer.test.mjs` -> `1 passed`; `git diff --check` -> passed.
- The next convergence step is explicit: App and Telegram should share one provider-backed new-session core service, but they should not be forced through one complete handler because App needs owner-bridge `pending` semantics and Telegram needs topic bind/rollback semantics.
- `18-02` reached source-verified status: App owner bridge and Telegram `/new` now share provider-owned validation, real-thread start/materialization, and started-thread first-message send through `core/provider_session_new.py`, while keeping App `pending` behavior and Telegram topic bind/rollback at the outer shell. Verification passed: `pytest -q tests/test_provider_session_new.py tests/test_provider_owner_bridge.py tests/test_slash_router.py tests/test_workspace_thread_open.py tests/test_thread_helpers.py tests/test_im_route_store.py` -> `111 passed`; `node --test mac-app/tests/sessionNewComposer.test.mjs` -> `1 passed`; `git diff --check` -> passed.
- Installed-app/TG UAT remains required before release/tag confidence.
