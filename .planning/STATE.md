# Project State

**Updated:** 2026-06-02
**Current milestone:** General AI Capability and Session Operations
**Current phase:** 12. Codex Managed App-Server Approval Host
**Last archived milestone:** v1.2.1

## Current Status

- v1.2.1 is archived.
- Phase 6, Notification Channel Abstraction, is complete.
- Phase 7, OnlineWorker User Message Gateway, is closed.
- Phase 8, General AI Capability Layer, is complete and packaged-app verified.
- Phase 9, Session Archive Actions, is complete and packaged-app verified.
- Active requirements `NOTIFY-01` and `NOTIFY-02` are implemented.
- Phase 6 notification mechanism, Telegram builtin channel, plugin guide assets, and UI channel configuration have been implemented and installed-app verified.
- Phase 7 adds an OnlineWorker-level provider-bound user message gateway and Codex remote app-server proxy boundary. Civility rewrite is currently paused, user text is sent unchanged, and related App entry points are hidden; installed-app verification has passed.
- Phase 8 adds a top-level AI sidebar tab and a shared AI capability layer. OpenAI and Claude are fixed built-in service choices; scenarios select exactly one configured service; service API settings and prompt/scenario settings are intentionally separate; notification summary is the first implemented consumer and local summary rules remain the fallback.
- Phase 9 adds Session tab archive actions and adjacent provider usage operations. Archive executes against the real provider source first, then persists local archived state; failures are visible, do not mark sessions archived locally, and post-success overlays keep archived rows visible when provider sources omit them. Provider usage is exposed through provider metadata/hooks, and `/token_usage` runs only in agent topics.
- Phase 10 has completed the full static codebase structure audit, staged refactor planning pass, 10-02 Tauri config/dashboard helper extraction, 10-03 Python workspace helper extraction, and 10-04 frontend Dashboard state/presentation extraction.
- Phase 11 has been added to migrate Telegram topic storage to a single SQLite table so topic bindings are independent durable records rather than JSON runtime fields.
- Phase 12 now carries the Codex app-server approval sync work that was local-only Phase 10 before the main merge. It follows the reference host/client pattern seen in Paseo, Happy, and the Codex IDE extension. OnlineWorker-managed Codex sessions own the app-server request/response channel, render Telegram as the remote approval UI, and relay Telegram decisions back to the same app-server request id. Existing Codex Desktop, VS Code, and ordinary CLI sessions keep native approval behavior; OnlineWorker mirrors them only unless it owns a controlled request/response channel. 12-01 implementation remains limited to `plugins/providers/builtin/codex/`; 12-02 explicitly expands scope to `config.py`, Codex Unix transport plumbing, and the developer-facing Codex external CLI alias/docs needed for fixed proxy testing. Unix shared transport now has local automated coverage, real app-server smoke coverage, and installed-app proxy validation: Codex default `unix://` starts under the app-server control socket, OnlineWorker `CodexAdapter.connect("unix://")` initializes and runs `model/list`, `AppServerProcess(protocol="unix")` starts and connects quickly after socket-readiness polling, and the installed app exposes `unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock` as the fixed visible-CLI proxy. The visible CLI must connect to the OnlineWorker proxy socket, not bare `--remote unix://`, because bare `unix://` goes directly to Codex's default app-server control socket and bypasses OnlineWorker approval mirroring. The remote proxy now keeps the Codex CLI native approval prompt visible, mirrors mapped approval requests to TG, dedupes duplicate raw app-server approval events, forwards `serverRequest/resolved` to the CLI while clearing TG mirror state, and consumes expected relay close/reset exceptions. Arbitrary external custom socket paths can still fail with local Codex CLI `Operation not permitted (os error 1)`, so explicit custom app-server paths should stay under the Codex app-server control directory until the path limit is better understood. Final fixed-session authorization convergence over the installed proxy is still a manual validation item.

## Archived Milestone

| Milestone | Status | Archive |
|-----------|--------|---------|
| v1.2.1 | Completed and archived | [ROADMAP](milestones/v1.2.1-ROADMAP.md), [REQUIREMENTS](milestones/v1.2.1-REQUIREMENTS.md), [phases](milestones/v1.2.1-phases/) |

## Active Phase

| Phase | Status | Next Step |
|-------|--------|-----------|
| 6. Notification Channel Abstraction | Completed | Archive or release milestone when ready |
| 7. OnlineWorker User Message Gateway | Closed | None |
| 8. General AI Capability Layer | Completed and packaged-app verified | None |
| 9. Session Archive Actions | Completed and packaged-app verified | None |
| 10. Codebase Structure Refinement | Completed | None |
| 11. Telegram Topic SQLite Storage Migration | Not started | Execute 11-01 |
| 12. Codex Managed App-Server Approval Host | Boundary aligned after Paseo/Happy/IDE reference review; unix shared transport and fixed OnlineWorker proxy installed-app verified; arbitrary external socket paths still limited by local Codex CLI `EPERM` | Run fixed-session visible CLI + TG authorization convergence test through `codex_remote_proxy.sock` |

## Key Preserved Decisions

- Builtin providers in this repository remain `codex` and `claude`.
- Provider-specific behavior should stay behind provider/plugin adapters and registry/runtime boundaries.
- Installed-app behavior remains the source of truth for packaged-app changes.
- Telegram remains the current default remote task, approval, status, and final-reply channel.
- New notification work should make notification delivery plugin-based without breaking existing Telegram behavior.
- Shared AI capability configuration belongs in a top-level AI tab, with service connection settings separate from scenario prompt settings.
- AI service choices are fixed product cards for OpenAI and Claude in Phase 8. Users should not type protocol, service id, or environment variable names.
- Scenarios choose one configured service from the UI. Multiple enabled services are not called in priority order.
- Scenario model selection follows the selected service's configured model.
- Prompt templates are configured by scenario/function. Notification summary is one scenario, and future scenarios should reuse the same AI capability layer.
- Current deterministic notification summary rules remain the fallback path when AI is disabled or unavailable.
- AI service API settings, including API keys, are configured in the AI service configuration flow; users do not need to manage environment variable names for this feature.
- Notification preview titles stay length-limited, while AI-generated notification summary bodies are not truncated by the old deterministic body limit.
- Phase 8 UI iteration should use dev verification first: `cd mac-app && ./node_modules/.bin/tsc --noEmit && npm run tauri dev`. Full packaging is reserved for explicit packaged-app validation or release readiness.
- Session archive actions must not use local-only fallback behavior. If provider source archive fails or is unsupported, the UI should show the failure and leave local session state unchanged.
- Session archive local state persistence is a post-success synchronization step after real provider archive.
- Session archive list rendering should merge post-success archived overlays back into provider session lists so Archived view can show rows even when provider sources omit archived sessions.
- Provider usage belongs behind provider metadata and usage hooks. UI and Telegram command surfaces should discover usage-capable providers from metadata instead of hard-coding a private provider list.
- `/token_usage` is a local bot command scoped to agent topics. It must reject concrete thread topics and must not forward into provider conversations.
- Explicit Claude fork UX remains future work; v1.2.1 only removed implicit fork/remap from normal sends and added the safe resume guard.
- Codex app-server approval lifecycle is the source of truth for this phase. Remote Connection is not part of this phase.
- Phase 12 implementation must stay within `plugins/providers/builtin/codex/` for 12-01; 12-02 includes config and Unix transport plumbing because transport parsing crosses the plugin boundary.
- Phase 12 is reference-driven by `getpaseo/paseo`, `slopus/happy`, and the Codex IDE extension model: a host/client owns the Codex app-server request/response channel and renders the approval UI.
- OnlineWorker may provide clickable Telegram approval controls only when it owns a real Codex decision channel: an app-server request id through the active adapter, an explicit controlled-host path, or an opt-in blocking hook.
- Existing Codex Desktop, VS Code, and ordinary CLI approval prompts must remain native and unaffected. For those non-owned sessions, OnlineWorker defaults to mirror-only notification and must not create clickable approval controls.
- For the local shared visible CLI + TG test, the installed OnlineWorker proxy socket is the preferred entry point: `unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock`. 12-02 added config parsing, process startup, adapter connection, shared-live detection, focused tests, fixed Unix proxy exposure, thread-list cwd filtering, approval mirror dedupe, `serverRequest/resolved` cleanup, and packaged-app validation. The adapter and proxy must disable WebSocket compression for Unix socket upgrades because Codex rejects the default `sec-websocket-extensions` header. `ws://127.0.0.1:<port>` remains supported as fallback transport, and bare `--remote unix://` remains valid for direct Codex default-socket access but bypasses OnlineWorker's proxy approval chain.

## Pending Todos

- Decide whether to archive the completed General AI Capability and Session Operations milestone as a released version.

## Roadmap Evolution

- Phase 6 added: Notification Channel Abstraction.
- Phase 6 plan added: 06-01 minimal notification channel abstraction.
- Phase 6 completed: added core notification event/router/registry, builtin Telegram notification plugin, notification channel config UI, local Telegram setup guide, notification plugin development docs, and a Codex TG routing regression fix discovered during installed-app validation.
- Phase 7 added: OnlineWorker User Message Gateway, including an OnlineWorker-level `before_user_message_send` hook pipeline and a first conservative abusive-language normalization hook.
- Phase 7 plan added: 07-01 add OnlineWorker user message gateway and before-send hooks.
- Phase 7 plan completed source verification: core gateway/config/hooks added; Telegram, owner bridge, provider session bridge, and new-thread user send paths route through the gateway; Codex `UserPromptSubmit` is explicitly modeled as pass-through pending confirmed prompt replacement protocol.
- Phase 7 plan added and completed source verification: 07-02 dictionary-backed user message neutralizer with a manual normalizer test script.
- Phase 7 plan added and completed source verification: 07-03 Codex remote app-server user message proxy. Real `codex --remote` traffic was probed; OnlineWorker-managed Codex TUI host sessions have a gateway/proxy boundary before app-server persistence/model submission.
- Phase 7 closed after product decision: civility rewrite is paused, App/Telegram/managed Codex paths send user text unchanged, the App settings entry is hidden, duplicate user message rendering for image sends was fixed, and fast packaged-app verification completed.
- Phase 8 added: General AI Capability Layer, including a first-class AI sidebar tab, separate service connection and scenario prompt configuration, direct AI runtime calls, and notification summary as the first scenario with local summary rules as fallback.
- Phase 8 plan added: 08-01 add general AI capability layer and first-class AI configuration tab.
- Phase 8 08-01 completed: `core/ai/` direct AI scenario runtime, `ai.services`/`ai.scenarios` config parsing, fixed OpenAI/Claude service cards, AI sidebar tab, notification-style AI service/scenario UI, Tauri config read/write command, service connection testing, notification summary AI-first/fallback behavior, external local summary fallback rules, and installed-app verification.
- Phase 9 added: Session Archive Actions, covering Session tab right-click Archive, provider-backed real archive execution, failure visibility, and local archived state persistence only after source archive success.
- Phase 9 plan added: 09-01 add provider-backed Session tab archive action.
- Phase 9 09-01 completed: Session tab right-click and visible action Archive UI, `archive_provider_session` Tauri command, owner bridge and sidecar real archive paths, post-success local state persistence, archived overlay list merging, provider usage capability discovery, `/token_usage` agent-topic command handling, and failure-visible no-local-fallback behavior. Sidecar archive is used only when owner bridge transport is unavailable; provider-reported archive failures return directly to the UI. Focused Python/Rust/Node/TypeScript verification and installed-app verification passed.
- Phase 10 added: Codebase Structure Refinement, covering oversized class/module audit, responsibility boundary cleanup, and staged behavior-preserving refactors across Python bot/runtime, Tauri, provider/plugin, AI/session, and frontend app shell code.
- Phase 10 plan added: 10-01 audit structure debt and establish staged refactor rails.
- Phase 10 10-01 completed: created `10-CODEBASE-AUDIT.md` and `10-STRUCTURE-DEBT.md`, updated codebase structure/concerns docs, locked the verification matrix, and selected the first follow-up implementation slices: Tauri config/dashboard helpers, Python workspace helpers, and frontend Dashboard state/presentation.
- Phase 10 plan added: 10-02 extract Tauri config and dashboard helper modules.
- Phase 10 10-02 completed: extracted config provider asset helpers, notification metadata helpers, dashboard provider status helpers, and dashboard recent activity helpers while preserving Tauri command surfaces. Focused Rust verification passed for `config_provider` and `dashboard`.
- Phase 10 plan added: 10-03 extract Python workspace pure helpers.
- Phase 10 10-03 completed: extracted workspace topic, callback token, callback identity, and history formatting/signature/batching helpers into `bot/handlers/workspace_helpers.py` while preserving Telegram callback/provider/topic behavior. Focused Python verification passed for workspace helper, thread open, and thread control tests.
- Phase 10 plan added: 10-04 extract frontend Dashboard state and presentation.
- Phase 10 10-04 completed: split Dashboard view-model helpers and presentation sections into `mac-app/src/components/dashboard/`, extended `useDashboardState` with derived provider/control/open-host state, and reduced `Dashboard.tsx` to hook/action orchestration while preserving Tauri command calls and visible UI.
- Phase 11 added: Telegram Topic SQLite Storage Migration, requiring a one-table SQLite topic registry to become the only truth source for Telegram topic routing after migrating existing JSON topic ids.
- Phase 11 plan added: 11-01 migrate Telegram topic storage to one SQLite table.
- Phase 12 added: Codex App-Server Approval Sync. The initial wording assumed Codex native approval UI and Telegram could both control the same request in all app-server cases; after merging main this work was renumbered from local Phase 10 to avoid colliding with upstream Phase 10 Codebase Structure Refinement and Phase 11 Telegram Topic SQLite Storage Migration.
- Phase 12 scope corrected after reference review: Paseo and Happy implement a provider/wrapper-owned app-server host, and the Codex IDE extension is the product analogy for a host/client. The phase is now Codex Managed App-Server Approval Host: OnlineWorker owns approval control only for OnlineWorker-managed Codex app-server sessions; Desktop, VS Code, and ordinary CLI remain native and mirror-only.
- Phase 12 12-01 implementation aligned with the corrected host/client boundary: Codex runtime keeps `approvalsReviewer="user"`, wraps app-server events to clear stale Telegram approval controls on `serverRequest/resolved`, dedupes duplicate app-server approval requests, and preserves Telegram decision relay back to app-server. Local automated checks passed with focused Codex/runtime/event tests and `git diff --check`; real managed app-server/TG validation is still pending.
- Phase 12 12-02 plan added: implement Codex `unix://` app-server transport for local shared visible CLI + TG approval testing, keep `ws://127.0.0.1:<port>` as the runnable fallback, and explicitly include `config.py` plus Codex provider transport code in scope.
- Phase 12 12-02 local implementation added: `unix` / `shared_unix` config parsing, Unix socket app-server startup, WebSocket-over-Unix adapter connection, runtime startup/reuse behavior, shared live transport recognition, TUI host remote URL handling, fixed Unix remote proxy exposure, external CLI alias/docs, cwd-scoped `/resume` filtering, approval mirror dedupe, `serverRequest/resolved` cleanup, and relay close/reset exception handling. Focused checks passed: `PYENV_VERSION=3.13.1 /Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_config.py tests/test_codex_adapter.py tests/test_startup_runtime.py tests/test_codex_tui_mode.py` -> `182 passed`; after the final remote proxy cleanup, `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest OnlineWorker/tests/test_codex_remote_proxy.py OnlineWorker/tests/test_codex_runtime.py -q` -> `25 passed`. Official docs and CLI help confirm `unix://` syntax; real smoke on 2026-06-02 confirmed default `unix://` creates the control socket, `CodexAdapter.connect("unix://")` connects after disabling WebSocket compression and `model/list` returns 1 model, custom sockets under `CODEX_HOME/app-server-control/` work, and `AppServerProcess(protocol="unix")` starts and connects in 0.11s with socket-readiness polling. Arbitrary external custom socket paths still fail with `Operation not permitted (os error 1)`. Real installed-app app-server/TG approval relay was verified on 2026-06-01: app-server `item/commandExecution/requestApproval` id `1` reached Telegram as msg `8673`, TG callback `exec_allow` called `reply_server_request` with request id `1` and decision `accept`. On 2026-06-02, packaged-app build/install/restart completed with DMG `OnlineWorker_1.4.0_aarch64.dmg`, installed hashes `onlineworker-bot=50c8d9a63ce61f340193ab0887aae322ae4ace41ffb296366fde33013811945e` and `onlineworker-app=2a80c905228608eb268ed665ea751bb36e61d214c043b22f0c7b9cad9488cbd0`; runtime logs confirmed `codex 使用托管默认 unix app-server：unix://`, `已启动 Codex remote Unix proxy：unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock`, `app-server 第 1 次重连成功`, and `workspace cwd 已注册：codex:onlineworker-combined`. Real fixed-session visible CLI + TG convergence validation should now use `codexR resume <session_id>` against the OnlineWorker proxy socket.
- Phase 12 was merged on top of main commit `e333403` after main introduced its own Phase 10 Codebase Structure Refinement and Phase 11 Telegram Topic SQLite Storage Migration. The Codex approval sync docs were renumbered to Phase 12, legacy current-session approval mirror files were left deleted per main, and merge verification passed: `/Users/wxy/.pyenv/versions/3.13.1/bin/python3 -m pytest -q tests/test_config.py tests/test_codex_adapter.py tests/test_codex_runtime.py tests/test_codex_remote_proxy.py tests/test_codex_tui_mode.py tests/test_codex_tui_realtime_mirror.py tests/test_question_enhanced.py tests/test_startup_runtime.py tests/test_codex_hook_bridge.py tests/test_provider_owner_bridge.py` -> `291 passed`; `cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet` -> `21 passed`; `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet` -> `33 passed`; `node --test mac-app/tests/dashboardProviderStatus.test.mjs mac-app/tests/appShell.test.mjs` -> `13 passed`; `cd mac-app && ./node_modules/.bin/tsc --noEmit` -> passed; `git -C OnlineWorker diff --check` -> passed.
