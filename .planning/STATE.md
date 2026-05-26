# Project State

**Updated:** 2026-05-26
**Current milestone:** Notification Extensibility
**Current phase:** None
**Last archived milestone:** v1.2.1

## Current Status

- v1.2.1 is archived.
- Phase 6, Notification Channel Abstraction, is complete.
- Phase 7, OnlineWorker User Message Gateway, is source-verified complete for plans 07-01, 07-02, and 07-03.
- Active requirements `NOTIFY-01` and `NOTIFY-02` are implemented.
- Phase 6 notification mechanism, Telegram builtin channel, plugin guide assets, and UI channel configuration have been implemented and installed-app verified.
- Phase 7 adds an OnlineWorker-level provider-bound user message gateway, a dictionary-backed conservative abusive-language neutralizer, and a Codex remote app-server proxy for OnlineWorker-managed Codex TUI host prompt rewriting; packaged-app verification has not been run for Phase 7.

## Archived Milestone

| Milestone | Status | Archive |
|-----------|--------|---------|
| v1.2.1 | Completed and archived | [ROADMAP](milestones/v1.2.1-ROADMAP.md), [REQUIREMENTS](milestones/v1.2.1-REQUIREMENTS.md), [phases](milestones/v1.2.1-phases/) |

## Active Phase

| Phase | Status | Next Step |
|-------|--------|-----------|
| 6. Notification Channel Abstraction | Completed | Archive or release milestone when ready |
| 7. OnlineWorker User Message Gateway | Source Verified | Run packaged-app build/install/relaunch verification before release |

## Key Preserved Decisions

- Builtin providers in this repository remain `codex` and `claude`.
- Provider-specific behavior should stay behind provider/plugin adapters and registry/runtime boundaries.
- Installed-app behavior remains the source of truth for packaged-app changes.
- Telegram remains the current default remote task, approval, status, and final-reply channel.
- New notification work should make notification delivery plugin-based without breaking existing Telegram behavior.
- Explicit Claude fork UX remains future work; v1.2.1 only removed implicit fork/remap from normal sends and added the safe resume guard.

## Pending Todos

- Decide whether to archive the Notification Extensibility milestone as the next released version.

## Roadmap Evolution

- Phase 6 added: Notification Channel Abstraction.
- Phase 6 plan added: 06-01 minimal notification channel abstraction.
- Phase 6 completed: added core notification event/router/registry, builtin Telegram notification plugin, notification channel config UI, local Telegram setup guide, notification plugin development docs, and a Codex TG routing regression fix discovered during installed-app validation.
- Phase 7 added: OnlineWorker User Message Gateway, including an OnlineWorker-level `before_user_message_send` hook pipeline and a first conservative abusive-language normalization hook.
- Phase 7 plan added: 07-01 add OnlineWorker user message gateway and before-send hooks.
- Phase 7 plan completed source verification: core gateway/config/hooks added; Telegram, owner bridge, provider session bridge, and new-thread user send paths route through the gateway; Codex `UserPromptSubmit` is explicitly modeled as pass-through pending confirmed prompt replacement protocol.
- Phase 7 plan added and completed source verification: 07-02 dictionary-backed user message neutralizer with a manual normalizer test script.
- Phase 7 plan added and completed source verification: 07-03 Codex remote app-server user message proxy. Real `codex --remote` traffic was probed; OnlineWorker-managed Codex TUI host sessions can now rewrite `turn/start` and `turn/steer` text before app-server persistence/model submission.
