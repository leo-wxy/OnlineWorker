---
status: passed
phase: 21
verified: 2026-08-15
requirements: []
automated_score: 6/6
human_score: "installed runtime passed; standalone Telegram visual comparison waived"
---

# Phase 21 Verification

## Result

Phase 21 achieved its goal: provider-owned visibility is applied before shared publication, child/internal sessions do not become top-level Desktop, Task Board, notification, persisted-state, or Telegram Topic records, and visible parent sessions use provider-native titles.

## Automated Evidence

- Login-backed AI, Codex adapter, and streaming regressions: `96 passed`.
- Hook bridge, TUI, workspace-open, and provider-boundary regressions: `102 passed`.
- Root logging and Telegram Bot URL redaction regressions: `13 passed`.
- Packaging-version synchronization regressions: `5 passed`.
- Source diff and staged privacy scans passed before the `v1.8.4` release.

## Goal Evidence

1. Codex child classification remains provider-owned and is reused by stored-session, rollout, Hook, notify, and app-server ingress paths.
2. Child/internal lifecycle events are suppressed before EventBus publication; shared consumers do not maintain separate provider-private filters.
3. Desktop and Telegram consume provider-native session titles while rollout and SQLite content remains preview text.
4. Stale child/internal state and routes reconcile to zero without deleting provider SQLite, rollout, transcript, or history data.
5. Unbound Topic creation is fail-closed unless a provider explicitly opts in; user-triggered workspace and session Topic creation remains available.
6. Codex Desktop ingress uses one recursive FSEvents watcher with transient rollout reads instead of retaining one file descriptor per historical rollout.

## Installed Runtime Evidence

- A real installed Codex child lifecycle produced no `session.created`, local thread, or external IM route.
- Post-cleanup inventory contained zero classified Codex child/internal threads and zero classified abnormal routes.
- Abnormal Topics and stale local projections were removed while genuine parent sessions and provider history were preserved.
- The installed runtime produced no new request-level `httpx` log lines, and active local logs contained zero unredacted Telegram Bot URLs.
- `OnlineWorker_1.8.4_aarch64.dmg` built and installed successfully; SHA-256: `e0f841b09f57d4151fcdce2997b5234a00aa23c6948d01b419ee3858d6bd817c`.

## Human Verification Closeout

The standalone live Telegram visual comparison was not rerun after the final cleanup. The user explicitly requested Phase 21 closeout on 2026-08-15, accepting this item as a documented waiver. The real installed child-suppression event, route/state inventory, Topic cleanup, and installed package checks remain the closure evidence; no visual pass is claimed.

The earlier Hook-trust checkpoint is superseded by the later real installed lifecycle smoke recorded above.

Phase 21 is complete with this explicit waiver.
