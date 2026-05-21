# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-10)

**Core value:** Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.
**Current focus:** Phase 4 — Claude Session Ownership and Safe Resume

## Current Position

Phase: 4 of 4 (Claude Session Ownership and Safe Resume)
Plan: 1 of 1 in current phase
Status: Completed
Last activity: 2026-05-21 — Completed Phase 4 by removing silent Claude auto-fork/remap, adding external-busy rejection and per-session serialization, and routing desktop Claude sends through the provider owner bridge

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 6
- Average duration: Tracked per phase
- Total execution time: Tracked per phase

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. UI Foundation | 2 | 1.6h | 48.5 min |
| 2. Provider Usage Explorer | 2 | Completed | - |
| 3. File and Image Support | 2 | Completed | - |
| 4. Claude Session Ownership and Safe Resume | 1 | Completed | - |

**Recent Trend:**
- Last 5 plans: 02-01, 02-02, 03-01, 03-02, 04-01
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
- [Phase 4] Existing Claude sessions are writable from TG/App; fork is explicit, not a normal-send fallback
- [Phase 4] OnlineWorker must not steal an externally active terminal Claude session; busy sessions should be rejected or queued only when OnlineWorker owns the live turn

### Pending Todos

- None for active phase.

### Blockers/Concerns

- Provider-neutral boundaries in shared surfaces should remain intact while attachment work lands
- `Usage` 页当前已稳定在按日窗口与 provider 级聚合，不要在后续阶段里把 provider-specific 统计细节拉回共享 React 层
- Attachment support uses existing provider/plugin routing; source/build/install verification and live user-facing smokes are complete.
- Settings `Maintenance` cache cleanup passed installed-app smoke on 2026-05-21: cache directories were emptied and preserved, while config/env/state/log files remained present.
- Adjacent Claude adapter auth/env tests still have known failures unrelated to the TG attachment stream-limit fix; do not treat those as Phase 3 attachment regressions without new evidence.
- The current worktree still contains Phase 3 closeout changes plus an earlier incorrect Claude auto-fork attempt; Phase 4 should revise only the Claude ownership boundary without undoing unrelated Phase 3 files.

### Roadmap Evolution

- Phase 3 replaced: removed placeholder Phases 3/4/5 and promoted file/image support into the next active phase
- Phase 3 implementation summaries added on 2026-05-21:
  - `.planning/phases/03-file-image-support/03-01-SUMMARY.md`
  - `.planning/phases/03-file-image-support/03-02-SUMMARY.md`
- Phase 4 added: Claude Session Ownership and Safe Resume
- Phase 4 implementation completed on 2026-05-21:
  - Removed silent Claude imported-session remap/fork on normal sends.
  - Added external-busy rejection before resuming non-OnlineWorker-owned live sessions.
  - Serialized Claude adapter sends per session id.
  - Routed desktop Claude sends through the provider owner bridge.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Platform | Non-macOS desktop targets | Deferred | 2026-05-10 |
| Product | New builtin providers beyond `codex` / `claude` | Deferred | 2026-05-10 |

## Session Continuity

Last session: 2026-05-12 14:36
Stopped at: Phase 2 closed after packaged-app rebuild/reinstall, Usage page installed-app verification, and Telegram HTML final-reply fix
Resume file: `.planning/ROADMAP.md`
