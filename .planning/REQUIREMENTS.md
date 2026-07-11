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

## Deferred Backlog

These items were explicitly deferred from the archived v1.2.1 milestone and remain candidates for future release work:

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
