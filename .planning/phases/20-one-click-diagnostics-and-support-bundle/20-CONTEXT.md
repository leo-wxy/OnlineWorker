# Phase 20: One-Click Diagnostics And Support Bundle - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning
**Source:** Approved conversation scope and 20-SPEC.md

## Phase Boundary

Add one-click local diagnostics and privacy-safe support-bundle export to the existing Maintenance settings surface.

## Implementation Decisions

- Tauri owns diagnostic collection so the baseline works when the bot is stopped.
- Existing Dashboard, Service, provider validation/readiness, owner bridge, config, plugin, and log truth must be reused.
- Every check is independently timed and independently reportable.
- Support artifacts are generated from structured sanitized data; raw source files are never copied wholesale.
- Use the existing Maintenance settings panel; no new top-level navigation.
- Use macOS-native save/archive/reveal facilities without adding a dependency when practical.
- Export is local-only and user initiated.

## Canonical References

- `mac-app/src/components/MaintenanceSettingsPanel.tsx` — existing Maintenance surface.
- `mac-app/src-tauri/src/commands/dashboard.rs` — current health/status truth and bounded log reads.
- `mac-app/src-tauri/src/commands/service.rs` — managed service truth.
- `mac-app/src-tauri/src/commands/config.rs` — config validation and sensitive-key conventions.
- `mac-app/src-tauri/src/commands/logs.rs` — current installed log location.
- `.planning/phases/20-one-click-diagnostics-and-support-bundle/20-SPEC.md` — locked behavior and privacy boundary.

## Deferred Ideas

- Automatic repair, restart, upload, telemetry, and transcript inclusion are deferred and out of scope.

---

*Phase: 20-one-click-diagnostics-and-support-bundle*
