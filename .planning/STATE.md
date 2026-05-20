# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-10)

**Core value:** Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.
**Current focus:** Phase 3 — File and Image Support

## Current Position

Phase: 3 of 3 (File and Image Support)
Plan: 2 of 2 in current phase
Status: In progress
Last activity: 2026-05-20 — Refined Claude attachment support to use local file paths plus `--add-dir` access, tightened explicit `ANTHROPIC_BASE_URL` routing, and added `ANTHROPIC_AUTH_TOKEN` support for Raven / Langbase-style Claude gateways

Progress: [████████░░] 83%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 48.5 min
- Total execution time: 1.6 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. UI Foundation | 2 | 1.6h | 48.5 min |

**Recent Trend:**
- Last 5 plans: 01-01, 01-02
- Trend: Stable

## Accumulated Context

### Decisions

Decisions are logged in `PROJECT.md`.
Recent decisions affecting current work:

- [Initialization] Treat the repo as a brownfield product and derive baseline context from README + codebase map
- [Initialization] Focus the active roadmap on UI refinement rather than provider/runtime replacement
- [Phase 1] Keep sidebar collapse as shell-local UI state in `App.tsx`
- [Phase 1] Preserve Tauri drag behavior while removing explicit drag-strip decoration
- [Phase 2] Keep provider usage aggregation behind provider/plugin adapters instead of hardcoding `codex` or `claude` parsing in shared Usage UI
- [Phase 2] Expose usage as a first-class `Usage` page instead of a sidebar summary

### Pending Todos

- Finish Phase 3 plan 03-02: rerun packaged-app rebuild/reinstall and attachment smoke verification after the Claude path-access refinement and explicit-base-url auth routing update

### Blockers/Concerns

- Provider-neutral boundaries in shared surfaces should remain intact while attachment work lands
- `Usage` 页当前已稳定在按日窗口与 provider 级聚合，不要在后续阶段里把 provider-specific 统计细节拉回共享 React 层
- Attachment support will need to respect existing provider/plugin routing and not bypass current Telegram delivery flows
- Claude attachment support should stay path-access based by default; do not overbuild custom document parsing before a concrete gap is observed

### Roadmap Evolution

- Phase 3 replaced: removed placeholder Phases 3/4/5 and promoted file/image support into the next active phase

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Platform | Non-macOS desktop targets | Deferred | 2026-05-10 |
| Product | New builtin providers beyond `codex` / `claude` | Deferred | 2026-05-10 |

## Session Continuity

Last session: 2026-05-12 14:36
Stopped at: Phase 2 closed after packaged-app rebuild/reinstall, Usage page installed-app verification, and Telegram HTML final-reply fix
Resume file: `.planning/ROADMAP.md`
