---
phase: 18-provider-session-new-flow
plan: 01
subsystem: provider-session
tags: [new-session, telegram-command, session-tab, provider-backed]
provides:
  - Real provider-backed App new-session creation from the first message
  - Telegram session-topic new-session behavior locked by regression tests
  - Provider-owned empty-session validation and source-topic feedback
affects: [session-browser, telegram-new, provider-owner-bridge]
tech-stack:
  added: []
  patterns: [first-message-materialization, real-session-only]
key-files:
  created: []
  modified:
    - bot/handlers/thread.py
    - bot/handlers/slash.py
    - core/provider_owner_bridge.py
    - mac-app/src/pages/SessionBrowser.tsx
key-decisions:
  - "A new session materializes from the first message and never appears as a visible local app draft."
  - "Telegram transport UAT is waived by the user for closure; Telegram source behavior remains covered by automated regressions."
duration: multi-slice
completed: 2026-07-11
status: complete
---

# Phase 18 Plan 18-01 Summary: App And Telegram New-Session Behavior

**App and Telegram new-session entry points now follow the same real-provider product rule: create a real session first and deliver the initial user message to that session.**

## Accomplishments

- App `New` uses a first-message composer and owner-bridge `start_session_message`; no visible `app:*` draft is created.
- App preserves pending UX while slow provider startup materializes the real session id.
- Telegram session-topic `/new <initial message>` is source-verified to create a separate provider-backed session/topic instead of sending into the current session.
- Codex empty `/new` validation remains provider-owned and responds in the source topic without creating a provider session or topic.

## Verification

- Phase-focused source checks were retained and the restored full gates passed: Python `996`, Rust `206`, frontend Node `159`, production frontend build passed.
- Packaged version `1.7.4` built, installed, relaunched, and exposed the expected owner-bridge IPC.
- Installed Codex App smoke returned `pending`, then materialized real session `<session-id>`; the unique first-message marker was present exactly once in provider history.
- Installed Claude App smoke returned `pending`, then materialized real session `<session-id>`; the unique first-message marker was present in provider history.
- Real Telegram `/new` UAT was not run by explicit user instruction.

## Runtime Observation

- The Codex smoke created and persisted the real session but its provider turn ended `failed` without an assistant message.
- The Claude smoke created and persisted the real session but remained `running` at `turn.started` without an assistant message at closure time.
- These observations do not invalidate the new-session materialization/first-message contract. They are concrete input for Phase 19 Session interrupt/resume and pending-state recovery.

## Next Phase Readiness

- The product behavior is ready for the shared-core convergence recorded in 18-02.
