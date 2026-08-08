# Phase 21 Context: Provider Child-Session Visibility

## Trigger

On 2026-08-04, internal Codex child sessions appeared as ordinary top-level rows in the Desktop Session Browser. The same polluted runtime state can also reach Telegram workspace/thread presentation, so this is a shared session-model problem rather than a surface-only rendering bug.

## Verified Evidence

- The affected Codex rollouts declare `session_meta.payload.source.subagent.thread_spawn` and a `parent_thread_id`; they are genuine child sessions.
- `plugins/providers/builtin/codex/python/storage_runtime.py#_is_codex_subagent_source` already recognizes this source shape.
- Codex provider storage paths already exclude these rows in `_scan_codex_session_file` and the SQLite thread scan.
- `plugins/providers/builtin/codex/python/external_ingress.py#_update_rollout_state` currently retains the session id and cwd from `session_meta` but discards `source`, `thread_source`, and parent metadata.
- `external_ingress.py#_should_publish_session` therefore cannot reject a new child rollout before `UserPromptSubmit` or completion ingestion.
- The resulting `session.created` event is registered by `bot/events.py#_handle_session_created` as a normal `ThreadInfo` whose default source is `unknown`.
- Telegram `/list` has a separate provider hook call for child ids, while workspace overview and Desktop session projection follow other paths. This duplicate filtering boundary permits the visible sets to diverge.

## Root Cause

Provider-private child-session classification is applied in some storage/listing paths but is lost at external event ingress. Once a child rollout enters the shared EventBus as an ordinary session, downstream consumers no longer have authoritative metadata with which to distinguish it.

## Related Changes Already Landed

Commit `ea6ba8f` introduced the current login-state summary and Desktop notification/session ingress chain. Phase 21 treats that commit as its implementation baseline instead of rebuilding the chain.

Session-related behavior already present:

- `external_ingress.py` watches appended Codex Desktop rollout data through macOS file events and maps new turns/completions into provider events.
- `adapter.py` normalizes external hook/rollout payloads and publishes them through the existing provider event path.
- `runtime.py` owns installation, startup, and shutdown of the Desktop ingress inside the Codex provider boundary.
- `bot/events.py` projects normalized session lifecycle events into OnlineWorker workspace/thread state.
- Provider facts already filter Codex child sessions when listing stored sessions and active ids.
- Telegram `/list` currently performs an additional child-id lookup, proving that presentation parity depends on a second filtering path today.

Carry-over work assigned to Phase 21:

- Preserve provider source, parent, and child classification while parsing external rollout metadata.
- Prevent a child rollout from creating a top-level EventBus session lifecycle, Task Board activity, notification, or workspace thread.
- Make Desktop Session Browser, Telegram `/list`, and Telegram workspace overview consume the same visible-session result.
- Reconcile stale child rows already registered with `source=unknown` in OnlineWorker state and discard any corresponding in-memory Desktop projection.
- Add regression coverage around the existing ingress lifecycle rather than replacing the working file-event listener.

Explicitly outside Phase 21:

- Reworking login-state AI completion or API fallback selection.
- Replacing the notification summary prompt/output contract.
- Deleting or rewriting provider rollout/transcript history.
- Replacing the existing EventBus or introducing a surface-specific session registry.

## Decision

Define one provider-owned user-visible-session decision and apply it at the common ingress/facts boundary.

- Provider plugins interpret private source metadata.
- External ingress preserves enough metadata to call the provider decision before publishing.
- Provider facts, active-id queries, state reconciliation, Desktop lists, Telegram `/list`, workspace overview, Task Board, and notifications consume the same canonical visibility result.
- Shared core and UI code do not parse Codex- or Claude-specific child-session payloads.
- Providers without child-session semantics default to visible.

## Required Repair

1. Consolidate Codex child-session detection behind the provider facts/capability contract.
2. Make external rollout ingress classify the session before emitting any user-visible lifecycle event.
3. Reconcile already-persisted child projections from OnlineWorker runtime state and refresh in-memory Desktop snapshots without deleting provider history.
4. Remove redundant surface-specific filtering once all consumers use the canonical result.
5. Keep parent-session events authoritative and preserve exactly one user-visible source per session/turn.

## Acceptance

- A child session never appears as a top-level Desktop Session Browser row.
- The same child session never appears in Telegram workspace overview or `/list`.
- A child session does not create its own top-level Task Board activity or completion notification.
- Its parent session remains visible and completes normally.
- Restarting with previously polluted OnlineWorker state removes the stale child projection through normal reconciliation.
- No provider transcript, rollout, or external history file is deleted or rewritten.

## Validation Targets

- Focused Python tests for Codex source classification and external ingress suppression.
- Provider contract tests proving one canonical visibility decision.
- EventBus/state tests proving no `session.created` projection for child sessions.
- Telegram workspace overview and `/list` parity tests.
- Desktop owner-bridge/session projection tests, including stale-state reconciliation.
- Regression coverage for normal Codex parent sessions and a provider with no child-session classifier.

Packaged-app verification requires explicit user permission in the active conversation.

## Implementation Record — 2026-08-07

Implemented the first Phase 21 slice at the provider ingress boundary.

- `storage_runtime.py` now exposes one Codex user-visible-session decision used by stored-session scans, active-id queries, child-id lookup, and external ingress.
- `external_ingress.py` preserves `source`, `thread_source`, and `parent_thread_id` from `session_meta`.
- A rollout classified as a child returns before any adapter/EventBus publication, so it cannot create a top-level activity, Session Browser row, notification, or Telegram workspace thread.
- Telegram `/list` and startup cleanup retain their generic provider hooks but those hooks now resolve through the same Codex classification helper.

Feedback loop and verification:

- The new regression test failed before the fix because one child rollout invoked the provider event path twice.
- The same test passed after the fix: `1 passed`.
- Focused ingress, storage, Telegram list, and startup cleanup regression: `42 passed`.
- Broader Codex adapter/runtime/event/owner-bridge regression: `167 passed`.
- A captured real child `session_meta` replay resolved `thread_source=subagent`, preserved its parent id, and returned `user_visible=False`.
- Fast packaged verification built and installed `OnlineWorker_1.8.1_aarch64.dmg`; installed Desktop visual verification showed only the two parent sessions in the affected workspace and no child row.

Remaining validation:

- Real Telegram workspace overview and `/list` visual UAT has not been executed. Source tests cover the shared provider classification and existing Telegram filter/cleanup paths, but Phase 21 remains open until that live surface is accepted or explicitly waived.

## Implementation Record — 2026-08-08

Implemented the second Phase 21 slice for provider-native session titles.

Verified root cause:

- Codex app-server defines `Thread.name` as the optional user-facing thread title and `Thread.preview` as usually the first user message.
- The offline Codex index stores the same user-facing value in `~/.codex/session_index.jsonl` as `thread_name`.
- OnlineWorker provider facts previously read SQLite/rollout first-user content into `preview` and never read `thread_name`.
- Telegram `/list`, workspace overview state, and topic creation then treated the path-prefixed preview as the display title and truncated it from the front.

Implemented behavior:

- Codex storage facts now expose `thread_name` as `title` while retaining first-user content as `preview`.
- Workspace synchronization prefers live app-server `name`, then provider `title`, then `preview`, and refreshes stale cached labels.
- Telegram `/list` and topic creation use `title`/`name` before `preview`.
- No title generator, AI request, shared storage schema, or new dependency was added.

Feedback loop and verification:

- Four focused regressions failed before the repair: provider title extraction, Telegram list naming, workspace synchronization, and topic naming.
- The same four regressions passed after the repair.
- Broader storage, adapter, owner-bridge, Telegram, and workspace regression passed: `200 passed`.
- A real local two-session replay changed from duplicate path-prefix labels to two distinct Codex-native titles.
- `bash verify-packaged-fast.sh` built and installed `OnlineWorker_1.8.1_aarch64.dmg`, then relaunched `/Applications/OnlineWorker.app`; the installed App and bot processes were running.

Remaining validation:

- Real Telegram workspace `/list`/overview visual UAT has not been run in this slice.
