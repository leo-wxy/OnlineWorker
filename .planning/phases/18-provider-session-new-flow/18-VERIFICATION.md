---
phase: 18-provider-session-new-flow
verified: 2026-07-11T10:24:31+08:00
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides:
  - truth: "Real Telegram /new topic creation acceptance"
    reason: "Explicitly waived by the product owner on 2026-07-11; no live Telegram pass is claimed."
deferred:
  - item: "User-visible interruption and recovery for failed or stalled provider turns"
    phase: 19
---

# Phase 18: Provider Session New Flow Verification Report

**Phase Goal:** Make new-session creation consistent and real-source-backed across the App Session tab and Telegram session topics, with no local-only draft sessions or current-session misrouting.
**Verified:** 2026-07-11T09:21:42+08:00
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | App and Telegram share provider-owned new-session validation, real-thread materialization, and first-message send. | ✓ VERIFIED | `core/provider_session_new.py` is wired into owner bridge and Telegram handler; full Python regression passed. |
| 2 | App preserves short-timeout pending behavior while a real session materializes. | ✓ VERIFIED | Automated slow-start coverage passes and both installed Codex/Claude requests returned `accepted=true, pending=true`. |
| 3 | App never exposes a local `app:*` placeholder as the real session. | ✓ VERIFIED | Installed smokes materialized real provider ids `019f4ebc-...` and `0afc0734-...`; source tests reject placeholder ids. |
| 4 | The initial user message is delivered to the new real Codex session exactly once. | ✓ VERIFIED | Installed Codex history contained the unique marker once in session `<session-id>`. |
| 5 | The initial user message is delivered to the new real Claude session. | ✓ VERIFIED | Installed Claude history contained the unique marker in session `<session-id>`. |
| 6 | Telegram `/new` route binding, no-current-session passthrough, and provider-specific empty validation are regression-locked. | ✓ VERIFIED | Slash/router/thread/route tests are part of the full `996 passed` source gate; live Telegram acceptance is explicitly waived and not claimed. |
| 7 | The shared new-session path is present and usable in the packaged app. | ✓ VERIFIED | Version `1.7.4` built, installed, relaunched, exposed owner-bridge IPC, and accepted real App new-session requests for both builtin providers. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `core/provider_session_new.py` | Shared two-stage provider-backed new-session core | ✓ EXISTS + SUBSTANTIVE | Owns validation, real-thread start/materialization, summary shaping, and started-thread send. |
| `core/provider_owner_bridge.py` | App pending shell over shared core | ✓ EXISTS + SUBSTANTIVE | Returns pending on slow start and completes against the real provider id. |
| `bot/handlers/thread.py` | Telegram topic-bind shell over shared core | ✓ EXISTS + SUBSTANTIVE | Inserts topic create/bind between the shared creation and send stages. |
| `tests/test_provider_session_new.py` | Shared-core contract coverage | ✓ EXISTS + SUBSTANTIVE | Covers validation and real-session behavior. |
| `mac-app/tests/sessionNewComposer.test.mjs` | App new composer behavior | ✓ EXISTS + SUBSTANTIVE | Protects first-message composer semantics. |

**Artifacts:** 5/5 verified

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Session Browser | owner bridge | `start_session_message` | ✓ WIRED | Installed calls returned pending and materialized real sessions. |
| owner bridge | shared core | start/materialize/send helpers | ✓ WIRED | Python regression and installed App smoke pass. |
| Telegram `/new` | shared core | staged creation then first-message send | ✓ WIRED | Router/thread/route tests pass. |
| shared core | provider adapters | provider hooks and `start_thread` | ✓ WIRED | Codex and Claude installed requests created real provider histories. |

**Wiring:** 4/4 connections verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| Real App session creation from first message | ✓ SATISFIED | - |
| Pending-to-real session identity | ✓ SATISFIED | - |
| Shared provider-backed core | ✓ SATISFIED | - |
| Telegram no-passthrough and topic-bind source behavior | ✓ SATISFIED | - |
| Provider-owned empty-session validation | ✓ SATISFIED | - |
| Packaged-app availability | ✓ SATISFIED | - |

**Coverage:** 6/6 requirements satisfied

## Automated And Installed Checks

- `rtk pytest -q` -> `996 passed`.
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet` -> `206 passed`.
- `node --test mac-app/tests/*.test.mjs` -> `159 passed`.
- `pnpm --dir mac-app build` -> passed.
- Version `1.7.4` package/install/relaunch/IPC checks passed with DMG SHA256 `f63758344625bf5bafe8505fed47f36f0e1d6485028828c1da747383eee6402b`.
- Codex installed App marker: `OW_PHASE18_APP_UAT_20260711_0914`; real session `<session-id>`.
- Claude installed App marker: `OW_PHASE18_CLAUDE_UAT_20260711_1018`; real session `<session-id>`.

## Accepted Scope Waiver

Real Telegram `/new` topic creation was not run because the user explicitly instructed that Telegram does not need testing. The report does not represent Telegram UAT as passed. Automated Telegram behavior remains part of the accepted source evidence, and the packaged shared core/App shell was exercised directly.

## Deferred Runtime Observation

The Codex provider turn failed after correct session creation. Follow-up diagnosis proved that the reused global app-server still held `apiKey` auth from its July 7 start while the current Codex auth had changed to ChatGPT on July 10. The source runtime now uses the OnlineWorker-owned endpoint `CODEX_HOME/app-server-control/onlineworker-app-server.sock`, launches it directly with `--disable hooks`, routes the existing remote proxy/TUI bridge to that endpoint, and reclaims only orphan listeners whose PID/PPID/start identity and exact argv match the owned socket. It does not restart the global Codex daemon.

Follow-up verification:

- `pytest -q tests/test_startup_runtime.py` -> `70 passed`.
- Codex adapter/runtime/proxy/TUI/startup regression -> `198 passed`.
- Full Python regression with Unix-socket permission -> `1003 passed in 30.27s`.
- Isolated real-process smoke under temporary `CODEX_HOME` -> dedicated socket accepted connections, `owned=True`, and stopped cleanly.
- `bash scripts/verify-packaged-fast.sh` -> passed in 81s; DMG SHA256 `3a86b777c80d6beb661d1962b562df8da4b9f83fb6835ed1d769102aa252049e`; installed app PID `40743`, bot PID `40843`.
- The installed runtime started owned app-server PID `41882` on `CODEX_HOME/app-server-control/onlineworker-app-server.sock`; pre-existing global app-server PID `33354` remained running and untouched.
- Installed Codex marker run remapped the requested UUID to real thread `<session-id>`, then progressed from `send_started` through `turn/started`, final reply, and `completed` in about 7 seconds with no 401. The test thread was archived through the real provider archive path.
- The legacy Claude-named smoke helper originally returned nonzero after the successful Codex run because it polled the pre-remap UUID instead of the `thread_id` returned by `send_message`. The helper now follows the returned thread for polling, result reporting, and cleanup; the remap regression and cleanup suite pass (`4 passed`).

The Claude provider turn remained running at `turn.started` without an assistant response at closure time. These observations do not break the verified Phase 18 creation and first-message contract. Generic pending visibility and Session interrupt/resume remain Phase 19 work.

## Anti-Patterns Found

No visible local draft session, duplicate App/TG provider-session core, or current-session `/new` passthrough remained in the verified source contract.

## Human Verification Required

None within the product-owner-approved closure scope. Live Telegram evidence was explicitly waived and remains unclaimed.

## Gaps Summary

**No Phase 18 creation-contract gaps found.** The Codex stale-auth defect is fixed and verified in the installed app. Generic provider-turn lifecycle recovery remains deliberately deferred to Phase 19.

## Verification Metadata

**Verification approach:** Goal-backward plus full regression and installed App owner-bridge smoke
**Must-haves source:** `18-01-PLAN.md`, `18-02-PLAN.md`, and `ROADMAP.md`
**Automated checks:** 4 primary gates passed, 0 failed
**Installed checks:** package identity, install/relaunch/IPC, Codex/Claude materialization, and the dedicated-socket Codex turn lifecycle passed
**Human checks required:** 0 in accepted scope

---
*Verified: 2026-07-11T10:35:04+08:00*
*Verifier: Codex*
