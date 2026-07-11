---
phase: 19
plan: 01
subsystem: session-control
tags: [message-bus, owner-bridge, tauri, interrupt, recovery]
key-files:
  modified:
    - core/messages/events.py
    - core/messages/projections.py
    - core/provider_owner_bridge.py
    - mac-app/src-tauri/src/commands/task_board_state.rs
    - mac-app/src-tauri/src/lib.rs
metrics:
  tests: 1010-python-208-rust
  commits: 0
---

# 19-01 Summary — Provider Session Controls

- Added authoritative user-interruption classification distinct from unexpected failure.
- Projected the real active provider `turn_id`; App-managed interrupt no longer depends on Telegram streaming state.
- Added ownership-safe `session_control` handling for interrupt and recovery, with mirrored/imported Sessions failing closed.
- Recovery can reconnect through provider `ensure_connected`, resumes the same Session, and never replays content.
- Added Tauri request/result transport plus normalized control availability and recent event facts.

## Verification

- RED tests were observed before implementation for interruption classification, control availability/dispatch, disconnected recovery, and Rust transport.
- Final full Python suite: `1010 passed`.
- Final full Rust suite: `208 passed`.

## Deviations

- No task commits were created because the working tree already contained unrelated user changes; delivery remains unstaged.

## Self-Check

PASSED for source behavior. Installed-app/live-provider UAT is tracked separately.
