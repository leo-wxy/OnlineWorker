---
phase: 18-provider-session-new-flow
plan: 02
subsystem: provider-session
tags: [new-session, shared-core, provider-hooks, telegram-routing]
provides:
  - Shared provider-backed new-session core under core/provider_session_new.py
  - Two-stage start/materialize and first-message delivery contract
  - Separate App pending and Telegram topic-bind shells
affects: [provider-owner-bridge, telegram-thread-handler, provider-session-new]
tech-stack:
  added: []
  patterns: [two-stage-session-start, transport-shell-separation]
key-files:
  created:
    - core/provider_session_new.py
    - tests/test_provider_session_new.py
  modified:
    - core/provider_owner_bridge.py
    - bot/handlers/thread.py
key-decisions:
  - "Share provider validation, real-thread materialization, and started-thread send; keep App and Telegram transport shells separate."
duration: multi-slice
completed: 2026-07-11
status: complete
---

# Phase 18 Plan 18-02 Summary: Shared Provider-Backed New-Session Core

**Owner bridge and Telegram now reuse one provider-backed new-session contract without coupling App pending UX to Telegram topic routing.**

## Accomplishments

- Added `core/provider_session_new.py` for provider-owned validation, real `start_thread` materialization, session summary shaping, and first-message delivery.
- Refactored owner bridge `start_session_message` to preserve short-timeout pending behavior while completing the shared flow asynchronously.
- Refactored Telegram `/new` to bind the new topic between shared Stage A and Stage B, preserving route-aware rollback and source-topic handoff behavior.
- Kept provider-specific empty-session rules behind provider hooks and rejected local placeholder ids as real sessions.

## Verification

- Original convergence suite: `111 passed` plus Session New frontend regression `1 passed`.
- Current full regression: Python `996 passed`, Rust `206 passed`, Node `159 passed`, frontend production build passed.
- Installed App smoke exercised the packaged shared owner-bridge entry for both builtin providers and materialized two real sessions with their initial messages.
- Telegram transport UAT was explicitly waived; no Telegram operation was performed in this closure pass.

## Decisions And Deviations

- Provider model completion is not folded into session creation. The observed failed/stalled turns are handed to Phase 19 rather than adding provider-specific retry logic to Phase 18.

## Next Phase Readiness

- Phase 19 can build pending-state handling and interrupt/resume commands on top of real provider session ids and the existing message/activity projection.
