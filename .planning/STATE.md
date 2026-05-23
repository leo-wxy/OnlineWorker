# Project State

**Updated:** 2026-05-23
**Current milestone:** Notification Extensibility
**Current phase:** 6
**Last archived milestone:** v1.2.1

## Current Status

- v1.2.1 is archived.
- Active roadmap has one open phase: Phase 6, Notification Channel Abstraction.
- Active requirements are `NOTIFY-01` and `NOTIFY-02`.
- Phase 6 notification mechanism and UI channel configuration have been implemented.
- Scope is notification delivery only; existing Telegram task, approval, topic, streaming, and final-reply business send paths remain unchanged.

## Archived Milestone

| Milestone | Status | Archive |
|-----------|--------|---------|
| v1.2.1 | Completed and archived | [ROADMAP](milestones/v1.2.1-ROADMAP.md), [REQUIREMENTS](milestones/v1.2.1-REQUIREMENTS.md), [phases](milestones/v1.2.1-phases/) |

## Active Phase

| Phase | Status | Next Step |
|-------|--------|-----------|
| 6. Notification Channel Abstraction | Implemented | Review and decide whether to archive after user validation |

## Key Preserved Decisions

- Builtin providers in this repository remain `codex` and `claude`.
- Provider-specific behavior should stay behind provider/plugin adapters and registry/runtime boundaries.
- Installed-app behavior remains the source of truth for packaged-app changes.
- Telegram remains the current default remote task, approval, status, and final-reply channel.
- New notification work should make notification delivery plugin-based without breaking existing Telegram behavior.
- Explicit Claude fork UX remains future work; v1.2.1 only removed implicit fork/remap from normal sends and added the safe resume guard.

## Pending Todos

- User validation of the notification settings UI and plugin boundary.

## Roadmap Evolution

- Phase 6 added: Notification Channel Abstraction.
- Phase 6 plan added: 06-01 minimal notification channel abstraction.
- Phase 6 implemented: added core notification event/router/registry, builtin Telegram notification plugin, notification channel config UI, and notification plugin development docs.
