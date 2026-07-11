---
phase: 19
slug: attention-center-and-session-interrupt-resume
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-11
---

# Phase 19 — Validation Strategy

## Test Infrastructure

| Layer | Framework | Quick command |
|-------|-----------|---------------|
| Python projection/control | pytest | `pytest -q tests/test_message_event_bus.py tests/test_provider_owner_bridge.py tests/test_thread_controls.py` |
| Tauri command | cargo test | `cargo test --manifest-path mac-app/src-tauri/Cargo.toml task_board_state --quiet` |
| Frontend model/shell | node:test | `node --test mac-app/tests/taskBoard.test.mjs mac-app/tests/appShell.test.mjs` |
| Type integration | TypeScript/Vite | `pnpm --dir mac-app build` |

## Sampling Rate

- Run the narrow failing test immediately after each RED addition.
- Run the matching layer command after each GREEN implementation.
- Run all four commands plus `git diff --check` before phase verification.
- Target feedback latency for a narrow RED/GREEN cycle: under 60 seconds.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Test Type | Automated command |
|---------|------|------|-------------|------------|-----------|-------------------|
| 19-01-01 | 01 | 1 | SESS-CTRL-01 | T-19-01 | unit | `pytest -q tests/test_message_event_bus.py -k interrupt` |
| 19-01-02 | 01 | 1 | SESS-CTRL-01 | T-19-01,T-19-02 | unit | `pytest -q tests/test_provider_owner_bridge.py -k session_control` |
| 19-01-03 | 01 | 1 | SESS-CTRL-01 | T-19-03 | unit | `cargo test --manifest-path mac-app/src-tauri/Cargo.toml task_board_state --quiet` |
| 19-02-01 | 02 | 2 | ATTN-01 | T-19-03 | unit | `node --test mac-app/tests/taskBoard.test.mjs` |
| 19-02-02 | 02 | 2 | ATTN-01 | T-19-03 | unit/build | `node --test mac-app/tests/appShell.test.mjs && pnpm --dir mac-app build` |

## Wave 0 Requirements

Existing test infrastructure covers every requirement; tests are added to established suites before production changes.

## Manual-Only Verification

| Behavior | Requirement | Why manual | Instructions |
|----------|-------------|------------|--------------|
| Desktop split-pane visual hierarchy and responsive list/detail transition | ATTN-01 | Visual composition and focus feel require the installed UI | After explicit package permission, inspect Task Board at desktop and narrow widths, select rows, and verify focus/aria state. |
| Real provider authoritative interrupt/recovery lifecycle | SESS-CTRL-01 | Requires a live managed Codex/Claude turn | After explicit package permission, interrupt a real active turn and confirm provider aborted/cancelled evidence before the row moves to `最近结束`. |

## Sign-Off

- All behavior-adding tasks have a RED command before implementation.
- No three consecutive tasks lack automated verification.
- No watch mode or package/install command is part of source verification.

**Approval:** approved 2026-07-11
