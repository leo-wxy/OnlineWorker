# Project State

## Project Reference

See: `.planning/PROJECT.md` (updated 2026-05-10)

**Core value:** Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.
**Current focus:** Phase 5 — Provider Session Error Visibility

## Current Position

Phase: 5 of 5 (Provider Session Error Visibility)
Plan: 1 of 1 in current phase
Status: Completed
Last activity: 2026-05-22 — Completed Phase 5 follow-up by routing legacy thread topic materialization through provider policy

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: Tracked per phase
- Total execution time: Tracked per phase

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. UI Foundation | 2 | 1.6h | 48.5 min |
| 2. Provider Usage Explorer | 2 | Completed | - |
| 3. File and Image Support | 2 | Completed | - |
| 4. Claude Session Ownership and Safe Resume | 1 | Completed | - |
| 5. Provider Session Error Visibility | 1 | Completed | - |

**Recent Trend:**
- Last 5 completed plans: 02-02, 03-01, 03-02, 04-01, 05-01
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
- [Phase 5] Generic provider asynchronous failures must become visible Session Browser state rather than relying on provider-specific React branches

### Pending Todos

- None for the current roadmap.

### Blockers/Concerns

- Provider-neutral boundaries in shared surfaces should remain intact while attachment work lands
- `Usage` 页当前已稳定在按日窗口与 provider 级聚合，不要在后续阶段里把 provider-specific 统计细节拉回共享 React 层
- Attachment support uses existing provider/plugin routing; source/build/install verification and live user-facing smokes are complete.
- Settings `Maintenance` cache cleanup passed installed-app smoke on 2026-05-21: cache directories were emptied and preserved, while config/env/state/log files remained present.
- Adjacent Claude adapter auth/env tests still have known failures unrelated to the TG attachment stream-limit fix; do not treat those as Phase 3 attachment regressions without new evidence.
- Explicit Claude fork UX remains future work; Phase 4 only removes implicit fork/remap from normal sends and adds the safe resume guard.

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
- Phase 5 added: Provider Session Error Visibility
- Phase 5 scope captured on 2026-05-22:
  - External overlay provider async errors should surface in Session Browser.
  - Generic provider history/read normalization should preserve user-visible error records.
  - Shared Session Browser behavior should not require provider-specific React branches.
- Phase 5 implementation completed on 2026-05-22:
  - External overlay provider assistant `data.error` records are converted into visible assistant error turns.
  - Provider owner bridge and fallback provider session bridge preserve visible provider error metadata.
  - Session Browser can stop waiting once the async error appears in read results.
- Phase 5 provider-session isolation follow-up completed on 2026-05-22:
  - Shared unbound thread topic materialization policy was moved into `core/providers/topic_policy.py`.
  - Both streaming `turn/started` and `LifecycleManager._ensure_thread_topics()` use the same provider policy.
  - External overlay provider and Claude app sessions with no TG topic stay isolated from automatic topic creation; codex keeps the default behavior.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Platform | Non-macOS desktop targets | Deferred | 2026-05-10 |
| Product | New builtin providers beyond `codex` / `claude` | Deferred | 2026-05-10 |

## Session Continuity

Last session: 2026-05-12 14:36
Stopped at: Phase 2 closed after packaged-app rebuild/reinstall, Usage page installed-app verification, and Telegram HTML final-reply fix
Resume file: `.planning/ROADMAP.md`
