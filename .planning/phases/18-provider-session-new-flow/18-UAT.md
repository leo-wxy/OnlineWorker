---
status: complete
phase: 18-provider-session-new-flow
source: [18-01-SUMMARY.md, 18-02-SUMMARY.md]
started: 2026-07-11T08:00:00+08:00
updated: 2026-07-11T10:35:04+08:00
---

## Current Test

[testing complete]

## Tests

### 1. Shared New-Session Source Contract
expected: App and Telegram entry points reuse provider-owned validation, real-thread materialization, and started-thread first-message delivery while preserving separate transport shells.
result: pass

### 2. Installed Package And Owner Bridge
expected: Version 1.7.4 installs and the packaged provider owner bridge accepts `start_session_message` requests from the App contract.
result: pass

### 3. Installed Codex App New Session
expected: A Codex App request returns pending, later materializes a real non-placeholder session under the requested workspace, and persists the unique first user message exactly once.
result: pass

### 4. Installed Claude App New Session
expected: A Claude App request returns pending, later materializes a real non-placeholder session under the requested workspace, and persists the unique first user message.
result: pass

## Accepted Scope Waiver

- Real Telegram `/new` topic creation was intentionally not executed because the product owner explicitly said Telegram does not need testing.
- The waiver is not represented as a Telegram pass. Telegram behavior remains backed by source regressions, while packaged verification covers the shared provider core and App shell.

## Runtime Follow-Up For Phase 19

- Codex session `<session-id>` materialized correctly, then its provider turn failed with OpenAI 401 because OnlineWorker reused a global app-server started before the current ChatGPT login. The global server reported `apiKey` while `codex login status` reported ChatGPT.
- The follow-up gives OnlineWorker its own `onlineworker-app-server.sock`, starts a fresh direct child with the current Codex auth state, preserves both stored/API-key environments, and refuses to terminate an active or non-owned listener. Source regressions, an isolated real-process socket smoke, and the repackaged installed `1.7.4` runtime all pass. The installed Codex run reached `completed` without 401 while the pre-existing global daemon remained running.
- Claude session `<session-id>` materialized correctly and remained running at `turn.started` without an assistant reply at closure time.
- No destructive cleanup or external-history deletion was performed. These real states motivate pending-center visibility and Session interrupt/resume controls.

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None in the Phase 18 new-session creation contract. The Codex stale-auth runtime defect is source- and installed-app-verified; generic provider-turn recovery is deferred to Phase 19 by scope.
