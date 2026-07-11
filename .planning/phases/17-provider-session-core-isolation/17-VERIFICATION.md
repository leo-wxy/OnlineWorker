---
phase: 17-provider-session-core-isolation
verified: 2026-07-11T09:30:32+08:00
status: passed
score: 7/7 must-haves verified
behavior_unverified: 0
overrides:
  - truth: "Real Telegram workspace-list visual comparison"
    reason: "Explicitly waived by the product owner on 2026-07-11; no live Telegram pass is claimed."
---

# Phase 17: Provider Session Core Isolation Verification Report

**Phase Goal:** Make provider session/workspace behavior fully provider-owned so core/Tauri does not parse provider-private stores, fields, hook payloads, or launch metadata.
**Verified:** 2026-07-11T09:30:32+08:00
**Status:** passed

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Shared Tauri code does not read Claude project JSONL files for workspace/session listing. | ✓ VERIFIED | Static architecture inspection plus the complete Rust suite (`206 passed`) cover the generic command surface. |
| 2 | Claude-private fields such as `entrypoint` are interpreted only inside the Claude provider/plugin boundary. | ✓ VERIFIED | Provider-private parsing remains under `plugins/providers/builtin/claude/`; restored Python regression is fully green (`996 passed`). |
| 3 | Session Browser, Dashboard recent activity, and TaskBoard consume generic provider session facts. | ✓ VERIFIED | Generic owner-bridge/provider-session command wiring is covered across Python, Rust, and frontend suites. |
| 4 | Telegram workspace/session behavior uses the same provider-owned facts boundary rather than a second Claude parser. | ✓ VERIFIED | Handler/provider regressions are included in the `996 passed` suite; no live Telegram visual pass is claimed. |
| 5 | Manual/managed sessions and provider-private noise follow provider-owned inclusion/filtering rules. | ✓ VERIFIED | Provider facts/session tests pass in the full Python suite; installed bridge returned real Claude and Codex inventories. |
| 6 | Provider-neutral summaries preserve richer/fresher previews and sanitize absolute paths. | ✓ VERIFIED | Full frontend regression passed (`159 passed`) and production frontend build completed. |
| 7 | The packaged app exposes the same generic facts boundary after install. | ✓ VERIFIED | Version `1.7.4` installed, app/bot hashes matched the DMG, new installed processes and IPC sockets were verified, and live owner-bridge list queries succeeded. |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `mac-app/src-tauri/src/commands/provider_sessions.rs` | Generic provider session owner-bridge command boundary | ✓ EXISTS + SUBSTANTIVE | Uses provider-neutral request types and response shaping. |
| `mac-app/src-tauri/src/commands/dashboard/recent_activity.rs` | Dashboard derives activity from provider session rows | ✓ EXISTS + SUBSTANTIVE | Provider rows can supply workspace/session identity without Claude-private storage. |
| `core/provider_session_bridge.py` | Runtime/archive bridge without duplicated provider registries | ✓ EXISTS + SUBSTANTIVE | Uses shared minimal adapter/state stubs. |
| `plugins/providers/builtin/claude/python/storage_runtime.py` | Claude-owned private storage parsing/filtering | ✓ EXISTS + SUBSTANTIVE | Private Claude storage knowledge remains in the provider package. |
| Session Browser/TaskBoard preview helpers | Shared sanitization and summary precedence | ✓ EXISTS + SUBSTANTIVE | Frontend regression covers cache preservation, freshness arbitration, and safe previews. |

**Artifacts:** 5/5 verified

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| Session Browser | Provider owner bridge | generic `list_sessions` / `read_session` requests | ✓ WIRED | Installed bridge returned real packaged provider facts. |
| Dashboard/TaskBoard | Provider session rows | provider-neutral projections and preview merge | ✓ WIRED | Rust/frontend full suites pass. |
| Telegram workspace handlers | Provider facts/runtime | provider registry hooks | ✓ WIRED | Python full suite passes; no duplicate Tauri Claude parser is involved. |
| Claude private store | Shared surfaces | normalized provider facts only | ✓ WIRED | Private parsing stays under the Claude plugin. |

**Wiring:** 4/4 connections verified

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| Core/Tauri provider-session isolation | ✓ SATISFIED | - |
| Provider-owned filtering and private-field interpretation | ✓ SATISFIED | - |
| Shared App/Dashboard/TaskBoard/Telegram facts contract | ✓ SATISFIED | - |
| Packaged-app behavior | ✓ SATISFIED | - |
| Safe provider-neutral summaries | ✓ SATISFIED | - |

**Coverage:** 5/5 requirements satisfied

## Automated And Installed Checks

- `rtk pytest -q` -> `996 passed`.
- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet` -> `206 passed`.
- `node --test mac-app/tests/*.test.mjs` -> `159 passed`.
- `pnpm --dir mac-app build` -> passed with the existing chunk-size warning.
- `git diff --check` -> passed before documentation closure.
- `bash scripts/build.sh` -> passed.
- DMG: `mac-app/src-tauri/target/release/bundle/dmg/OnlineWorker_1.7.4_aarch64.dmg`.
- DMG SHA256: `f63758344625bf5bafe8505fed47f36f0e1d6485028828c1da747383eee6402b`.
- Installed runtime: new app PID `87052`, bot PID `87156`, bot child PID `87229`, all from `/Applications/OnlineWorker.app`.
- Installed owner bridge returned Claude `15 sessions / 4 workspaces` and Codex `31 sessions / 12 workspaces` before Phase 18 smoke activity added test rows.

## Accepted Scope Waiver

The user explicitly directed that Telegram does not need testing and asked to close Phase 17/18. Therefore a real Telegram `/workspace` visual comparison was not executed. This report does not claim it passed; closure relies on the shared source contract, full automated handler/provider regressions, packaged runtime integrity, and installed generic provider facts.

## Anti-Patterns Found

No phase-blocking stubs, duplicate provider-private Tauri parsing paths, or raw-path preview regressions were found in the accepted closure scope.

## Human Verification Required

None within the product-owner-approved closure scope. Real Telegram visual evidence was explicitly waived and remains unclaimed.

## Gaps Summary

**No Phase 17 gaps found.** Provider-turn interruption/recovery is a separate Phase 19 concern and does not reopen the provider-session facts boundary.

## Verification Metadata

**Verification approach:** Goal-backward plus full regression and installed owner-bridge evidence
**Must-haves source:** `17-01-PLAN.md` and `ROADMAP.md`
**Automated checks:** 4 primary gates passed, 0 failed
**Installed checks:** build, artifact identity, install, relaunch, IPC, and provider-facts query passed
**Human checks required:** 0 in accepted scope

---
*Verified: 2026-07-11T09:30:32+08:00*
*Verifier: Codex*
