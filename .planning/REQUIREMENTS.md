# Requirements: OnlineWorker

## Current Milestone

**Theme:** Notification Extensibility

The v1.2.1 milestone requirements are archived at [milestones/v1.2.1-REQUIREMENTS.md](milestones/v1.2.1-REQUIREMENTS.md).

## Notification Channels

- [x] **NOTIFY-01**: User-facing notifications can be emitted through a plugin-based notification router rather than being limited to Telegram-specific notification channels.
- [x] **NOTIFY-02**: Telegram remains the default builtin notification plugin, and custom notification plugins such as WeChat can be inserted later without changing core notification routing.

## Attention Center And Session Controls

- [x] **ATTN-01**: User can use the existing Task Board Tab as a focused attention center grouped into `需要你`, `正在运行`, and `最近结束`, with a selected Session detail pane and authority-safe actions.
- [x] **SESS-CTRL-01**: User can interrupt a concrete provider-owned active turn and continue or recover the same real Session without fabricating local Session truth, replaying a prior message, or exposing controls for mirrored-only Sessions.

## Diagnostics And Support

- [x] **DIAG-01**: User can run bounded local diagnostics from Settings and receive independent pass, warning, or failure results for app version, managed service, provider readiness, owner bridge, configuration, plugins, sockets, and recent runtime errors even when some checks fail or the bot is stopped.
- [x] **SUPPORT-01**: User can export a local support ZIP containing a human-readable summary, structured diagnostic facts, sanitized configuration shape, provider/plugin inventory, and a bounded recent log excerpt, then reveal the generated file in Finder.
- [x] **PRIV-01**: Diagnostics and support bundles exclude raw credentials, tokens, environment values, complete Session conversations, prompts, provider transcript/history files, and automatic network upload.

## Runtime Stability

- [x] **STAB-01**: MessageEventBus dedupe retention is bounded while recent duplicates remain suppressed.
- [x] **STAB-02**: Runtime read failures remain errors and do not replace last-known-good state with fabricated empty data.
- [x] **STAB-03**: Stale turns, generations, stream cleanup, and delayed requests cannot overwrite a newer owner.
- [x] **STAB-04**: One provider ingress/live chain owns each user-visible session turn event category.
- [x] **STAB-05**: Critical config/state writes are atomic and recoverable, and route migrations can safely resume.
- [x] **STAB-06**: Each stability slice has focused automated regression coverage.

## Deferred Backlog

- [ ] **STAB-07**: OnlineWorker can discover the current Codex session owner, steer/queue ordinary TG input through that owner, invoke its real interrupt capability, and return commentary/final to the original TG Topic. Deferred from Phase 24 by user acceptance; not implemented/verified. Resume only when supported owner control becomes available; preserve the acceptance criteria in [24-07-PLAN.md](phases/24-runtime-authority-and-durability-hardening/24-07-PLAN.md).

These items remain candidates for future work. UX/PLT items came from v1.2.1; STAB-07 was deferred by explicit user acceptance when Phase 24 was archived on 2026-09-05.

- **UX-01**: User can customize more of the app appearance from first-class settings surfaces.
- **UX-02**: User can discover and configure external provider extensions from a richer in-app management experience.
- **PLT-01**: User can use equivalent first-class desktop packaging flows beyond macOS.
- **PLT-02**: User can use richer release automation including signing/notarization without manual release intervention.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| NOTIFY-01 | Phase 6 | Implemented |
| NOTIFY-02 | Phase 6 | Implemented |
| ATTN-01 | Phase 19 | Complete; installed desktop UAT passed, narrow visual check explicitly waived |
| SESS-CTRL-01 | Phase 19 | Implemented; installed interrupt, Continue, recovery, no-replay UAT passed |
| DIAG-01 | Phase 20 | Complete; source and installed diagnostics UAT passed |
| SUPPORT-01 | Phase 20 | Complete; installed export, cancellation, and Finder reveal passed |
| PRIV-01 | Phase 20 | Complete; strict ZIP whitelist and installed `.env` zero-match privacy scan passed |
| STAB-01 | Phase 24 | Source verified in 24-01 |
| STAB-02 | Phase 24 | Source verified in 24-02 and 24-08 |
| STAB-03 | Phase 24 | Source verified in 24-03, 24-05, and 24-08 |
| STAB-04 | Phase 24 | Source verified in 24-04 and 24-06 |
| STAB-05 | Phase 24 | Source verified in 24-06 and 24-08 |
| STAB-06 | Phase 24 | Source verified through 24-09; fast packaged verification passed; feature UAT not run and accepted as an archival limitation |
| STAB-07 | Deferred backlog (from Phase 24) | Deferred by user acceptance on 2026-09-05; original owner-control gap and acceptance criteria preserved in 24-07 |
