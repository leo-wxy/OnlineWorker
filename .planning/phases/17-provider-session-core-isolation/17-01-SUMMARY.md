---
phase: 17-provider-session-core-isolation
plan: 01
subsystem: provider-session
tags: [provider-boundary, session-facts, tauri, taskboard, packaged-app]
provides:
  - Provider-private session parsing isolated behind provider/plugin boundaries
  - Generic owner-bridge session facts for App, Dashboard, TaskBoard, and Telegram callers
  - Provider-neutral preview caching, freshness arbitration, and path sanitization
affects: [provider-sessions, session-browser, task-board, dashboard, telegram-workspaces]
tech-stack:
  added: []
  patterns: [provider-owned-facts, generic-owner-bridge, summary-cache]
key-files:
  created: []
  modified:
    - mac-app/src-tauri/src/commands/provider_sessions.rs
    - mac-app/src-tauri/src/commands/dashboard/recent_activity.rs
    - core/provider_session_bridge.py
    - mac-app/src/utils/sessionBrowserState.js
key-decisions:
  - "Provider-private stores and fields stay inside provider/plugin code; shared Tauri and frontend surfaces consume normalized facts."
  - "Real Telegram visual parity was explicitly waived for this closure; source behavior, installed provider facts, and packaged runtime remain the accepted evidence."
duration: multi-slice
completed: 2026-07-11
status: complete
---

# Phase 17 Plan 17-01 Summary: Provider Session Core Isolation

**Provider session/workspace truth is now owned by provider boundaries, while shared App surfaces consume normalized owner-bridge facts instead of Claude-private storage.**

## Accomplishments

- Removed shared Tauri dependence on Claude project JSONL parsing and private fields such as `entrypoint`.
- Routed Session Browser, Dashboard recent activity, and TaskBoard session facts through generic provider-session/owner-bridge contracts.
- Preserved manual and managed provider sessions while filtering low-signal/provider-private noise inside the owning provider.
- Converged Session Browser and TaskBoard preview rules around richer provider summaries, timestamp freshness, bounded hydration, cache preservation, and absolute-path sanitization.
- Rebuilt and installed version `1.7.4`; the installed owner bridge returned real Claude and Codex workspace/session facts through the packaged provider boundary.

## Verification

- `rtk pytest -q` -> `996 passed`.
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet` -> `206 passed`.
- `node --test mac-app/tests/*.test.mjs` -> `159 passed`.
- `pnpm --dir mac-app build` -> passed; existing large-chunk warning only.
- `bash scripts/build.sh` -> passed and produced `OnlineWorker_1.7.4_aarch64.dmg`.
- Installed artifact version and binary hashes matched the mounted DMG.
- Installed runtime started new `onlineworker-app` and `onlineworker-bot` processes from `/Applications/OnlineWorker.app` and exposed the expected owner/proxy IPC sockets.
- Installed generic owner-bridge queries returned Claude `15 sessions / 4 workspaces` before the Phase 18 smoke and Codex `31 sessions / 12 workspaces` before the Phase 18 smoke.
- Real Telegram `/workspace` visual comparison was not run because the user explicitly instructed that Telegram does not need testing.

## Decisions And Deviations

- Phase closure accepts the product owner's explicit Telegram UAT waiver. This is not recorded as a Telegram pass and does not claim live Telegram visual evidence.
- The phase remains bounded to provider-session ownership and summary parity; it does not add a new provider, rewrite the message bus, or change approval authority.

## Next Phase Readiness

- Phase 18 can close on the same installed provider boundary.
- Stalled/failed provider turns observed during installed App new-session smoke feed Phase 19 Session interrupt/resume work; they do not reopen the Phase 17 facts boundary.
