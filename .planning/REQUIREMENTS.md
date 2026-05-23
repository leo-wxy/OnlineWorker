# Requirements: OnlineWorker

## Current Milestone

**Theme:** Notification Extensibility

The v1.2.1 milestone requirements are archived at [milestones/v1.2.1-REQUIREMENTS.md](milestones/v1.2.1-REQUIREMENTS.md).

## Notification Channels

- [x] **NOTIFY-01**: User-facing notifications can be emitted through a plugin-based notification router rather than being limited to Telegram-specific notification channels.
- [x] **NOTIFY-02**: Telegram remains the default builtin notification plugin, and custom notification plugins such as WeChat can be inserted later without changing core notification routing.

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
