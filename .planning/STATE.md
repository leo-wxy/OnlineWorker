# Project State

**Updated:** 2026-05-23
**Current milestone:** Not started
**Last archived milestone:** v1.2.1

## Current Status

- v1.2.1 is archived.
- Active roadmap has no open phases.
- Active requirements have not been defined for the next milestone.
- `.planning/phases/` is intentionally empty except for `.gitkeep`.

## Archived Milestone

| Milestone | Status | Archive |
|-----------|--------|---------|
| v1.2.1 | Completed and archived | [ROADMAP](milestones/v1.2.1-ROADMAP.md), [REQUIREMENTS](milestones/v1.2.1-REQUIREMENTS.md), [phases](milestones/v1.2.1-phases/) |

## Completed v1.2.1 Scope

- Phase 1: UI Foundation
- Phase 2: Provider Usage Explorer
- Phase 3: File and Image Support
- Phase 4: Claude Session Ownership and Safe Resume
- Phase 5: Provider Session Error Visibility

## Key Preserved Decisions

- Builtin providers in this repository remain `codex` and `claude`.
- Provider-specific behavior should stay behind provider/plugin adapters and registry/runtime boundaries.
- Installed-app behavior remains the source of truth for packaged-app changes.
- Telegram remains the remote task, approval, status, and final-reply channel.
- Explicit Claude fork UX remains future work; v1.2.1 only removed implicit fork/remap from normal sends and added the safe resume guard.

## Pending Todos

- None for the archived v1.2.1 milestone.

## Next Step

Start a new milestone before adding new phases.
