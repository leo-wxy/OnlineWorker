# Phase 19 — Technical Research

**Date:** 2026-07-11
**Scope:** Existing Task Board projection, owner bridge, provider control hooks, Tauri transport, and Sessions navigation.

## Existing Truth Sources

- `core/messages/projections.py` is the canonical activity projection. It currently maps every `turn.failed` to a failure, so user-requested abort/cancel needs an explicit interrupted terminal classification.
- `core/provider_owner_bridge.py` already serves Task Board snapshots/streams and approval replies. Session lifecycle controls belong on this bridge, but read/control checks must not call helpers that materialize placeholder workspaces or threads.
- `core/providers/contracts.py` already defines provider-neutral interrupt hooks. Codex resolves a real active app-server turn id; Claude owns a managed subprocess cancellation path.
- `mac-app/src-tauri/src/commands/task_board_state.rs` is the narrow App transport boundary for Task Board commands.
- `mac-app/src/utils/taskBoard.js` is the existing projection-to-view-model boundary and should evolve instead of adding a second board state store.
- `App.tsx` → `SessionBrowser.tsx` → provider chat → `SessionComposer` is the existing route for opening a real Session. Continue only adds a one-shot focus intent.

## Implementation Shape

1. Classify authoritative user abort/cancel terminal events as `interrupted`, distinct from unexpected `failed`.
2. Decorate activity snapshots with normalized control availability derived from current provider/session ownership and active-turn facts. These fields are recomputed, not persisted.
3. Add one owner-bridge `session_control` command with `interrupt` and `recover` actions. Providers keep private turn/process details behind adapters.
4. Add one Tauri command that forwards the normalized request/result and returns explicit unsupported/ownership errors.
5. Replace the three-column card surface with a compact grouped list and a selected detail pane while preserving route, badge, stream, pin, and approval authority.
6. Implement Continue as navigation to the same Session plus composer focus; it never sends text.

## Non-Goals And Traps

- Do not infer interrupt success from a click, timeout, or inactivity.
- Do not replay the previous user message during recovery.
- Do not expose approval or lifecycle controls for mirrored-only/external Sessions.
- Do not make Task Board a second Session source of truth.
- Do not add global search, a new top-level page, a UI dependency, or provider-private parsing in shared Rust/React code.
- Do not package/install the app without explicit permission in the current conversation.

## Test Strategy

- Python unit tests prove projection classification, ownership fail-closed behavior, hook dispatch, and recovery evidence requirements.
- Rust unit tests prove request serialization and error propagation at the Tauri boundary.
- Node tests prove grouping/sorting/action availability and continue-focus intent without generated sends.
- TypeScript build proves the cross-component focus token and new Task Board view types remain coherent.
