# Project State

**Updated:** 2026-06-01
**Current milestone:** General AI Capability and Session Operations
**Current phase:** 11. Telegram Topic SQLite Storage Migration
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
