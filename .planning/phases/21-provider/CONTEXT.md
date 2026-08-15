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

## Implementation Record — 2026-08-10

Implemented the third Phase 21 slice for bounded Codex Desktop ingress resources.

Verified root cause:

- The installed main bot held `255` numeric FDs against the macOS soft limit of `256` while `~/.codex/sessions` contained `531` rollout files.
- The kqueue implementation recursively opened every historical directory and rollout and retained each FD for the lifetime of the process.
- Once exhausted, socket accept, SQLite opens, Codex ingress, and Telegram polling all failed with `Errno 24`.

Implemented behavior:

- The provider now uses one recursive macOS FSEvents watcher through `watchfiles`.
- Startup still seeds historical offsets without replaying old completions, but every rollout handle is closed immediately after reading.
- Added and modified rollout files are read through short-lived handles and continue through the same adapter and EventBus path.
- No file polling, session replay, EventBus change, Telegram-specific bypass, or higher FD limit was added.

Feedback loop and verification:

- The red regression created `80` historical rollouts and reproduced FD growth from `16` to `101`, a net increase of `85`.
- After the repair, the same regression passed with constant FD usage; the full ingress suite passed `6` tests.
- Broader Codex adapter, startup, EventBus, owner-bridge, notification, and streaming regression passed: `276 passed`.
- `bash verify-packaged-fast.sh` built and installed `OnlineWorker_1.8.2_aarch64.dmg` in `86s`, including the native `watchfiles/_rust_notify` module.
- With all `531` real rollouts tracked, the installed main bot held `29` FDs, held no rollout files open, emitted no new FD/SQLite/socket resource errors, and logged repeated Telegram `getUpdates 200 OK` responses.

Remaining validation:

- Real Telegram workspace `/list`/overview title visual UAT from `21-02` remains open; the Telegram transport itself is healthy after this repair.

## Implementation Record — 2026-08-11

Implemented the fourth Phase 21 slice for Codex Desktop event-source priority.

Verified root cause:

- [Codex Hooks](https://developers.openai.com/codex/hooks/) officially supports `SessionStart`, `UserPromptSubmit`, `Stop`, and `SessionEnd` command hooks, but OnlineWorker installed only `notify` and removed its own lifecycle hook entries.
- The rollout listener published appended transcript rows immediately, so the fallback could win before an official hook or notify completion reached the provider adapter.
- When a hook had already published the turn start, a later notify completion published the user message and turn start a second time.

Implemented behavior:

- OnlineWorker now installs the official lifecycle hooks as the primary Desktop event source while retaining `notify` as the completion fallback and preserving third-party hook/notify handlers.
- A session already owned by the app-server live stream suppresses Hook, notify, and rollout publication, preserving the existing authoritative source.
- Hook and notify events share the existing adapter turn state, so the same session/turn produces one start and one terminal sequence.
- Completion priority is deterministic: Hook relays immediately, OnlineWorker's notify relay waits `0.5s`, and rollout-derived events wait `1s`; third-party notify handlers are forwarded before the OnlineWorker delay.
- FSEvents still uses one root watcher, and pending rollout fallbacks are cancelled when a primary event claims the turn.
- The existing provider adapter and EventBus contracts remain unchanged; no polling loop, new dependency, or user-facing source-priority configuration was added.

Feedback loop and verification:

- Five focused regressions failed before the repair, covering hook preservation, combined installation, cross-source turn dedupe, and delayed fallback cancellation.
- The focused repair suite passed `10` tests.
- Hook bridge, Codex adapter, real macOS FSEvents ingress, and EventBus/notification regression passed `98` tests.
- Runtime startup and owner-bridge routing regression passed `21` tests.
- The real FSEvents checks were run outside the test sandbox because sandboxed macOS file events were not delivered.
- Packaged verification exposed a synchronous-hook latency defect: the bundled `onlineworker-bot` needed about `7.9s` just to start, while Codex does not yet support asynchronous command hooks and `SessionEnd` allows at most `3s`.
- Lifecycle hooks now invoke a lightweight `/usr/bin/python3` forwarder that captures stdin, detaches the bundled bot relay, and returns within the hook timeout; `PermissionRequest` remains on the synchronous decision path.
- `bash build.sh` rebuilt `OnlineWorker_1.8.2_aarch64.dmg`; the final DMG SHA-256 was `4e05620705c4f195078170c5c00c783b0ac5c9399e0b349874e9dc65153c27ef`.
- The installed bot hash matched the DMG (`c68e89a0b85e1a17fb5f172e8a7dd30c93232f03adee9a2f43de282e0e641f15`), and the installed app plus persistent bot processes were running.
- Runtime installation produced one lightweight handler with `timeout=3` for each lifecycle event. The forwarder returned in `0.08s`, and its detached `SessionEnd` smoke payload reached the owner bridge with `emitted=0`.
- `verify-packaged-fast.sh` rebuilt and validated the DMG but could not stop two pre-existing bot processes cleanly; those exact stale PIDs were terminated, after which `install-current-dmg.sh` completed installation and restart successfully.

Remaining validation:

- Codex requires review and trust when a non-managed hook definition changes. A real Codex-triggered lifecycle event after that trust step has not been observed in this slice; the installed bridge itself, notify fallback, and rollout fallback are verified.

## Implementation Record — 2026-08-11 (Hook Trust Guidance)

Implemented the fifth Phase 21 slice for the user-visible Codex Hook trust workflow.

Verified root cause:

- Codex requires users to review and trust changed non-managed command Hook definitions through `/hooks`.
- The provider previously reported only the connected app-server line, so the later Hook trust warning was masked by first-line health parsing and had no actionable UI path.
- Installation state alone cannot prove that the current Hook definition was trusted; a real Hook event is the reliable local completion signal.

Implemented behavior:

- Hook installation persists the exact definition hash and marks it verified only after a real `codex_hook` event reaches the adapter.
- Runtime health exposes app-server connectivity and Hook trust as separate status lines, while owner-bridge health aggregation gives warning/error lines priority over an earlier connected line.
- Dashboard provider cards show `需操作` and expose a focused guide when Hook trust is pending.
- Added one reusable `ActionGuideDialog` for future user-action workflows. Provider-specific copy and steps remain outside the visual component.
- The guide supports command copying, backdrop/Escape dismissal, focus restoration, and a refresh-based recheck action. Fallback remains active until the real Hook event verifies the current definition.

Feedback loop and verification:

- Hook state, adapter verification, runtime status, and owner-bridge health regression passed `126` focused Python tests.
- The macOS frontend production build and Dashboard provider-status tests passed.
- Browser QA at `1179 x 1334`, device pixel ratio `1`, exercised copy, dismiss, primary recheck, backdrop, and Escape flows with no console warnings or errors.
- Side-by-side visual comparison found one footer-order mismatch; the primary and secondary actions were reordered and the second comparison passed with no remaining P0/P1/P2 findings.
- `bash build.sh` and `bash verify-packaged-fast.sh` rebuilt `OnlineWorker_1.8.2_aarch64.dmg`; the final DMG SHA-256 was `2f55a0c87608acf644ae7dd68c1411efec801bc816cd9e5bcc6870542404d82d`.
- The first install attempt exposed two stale bot processes that ignored normal termination. After terminating those exact stale processes, `install-current-dmg.sh` installed and relaunched the current DMG successfully.
- Installed bot, app, and usage-sidecar hashes matched the mounted DMG, both staged private plugin manifests were present, and the main app, main bot, and Codex app-server remained running.
- Installed-App UI verification confirmed the Codex card displays `需操作`, `查看引导` opens the reusable dialog, all expected instructions/actions are visible, and dismissal returns to Dashboard.

Remaining validation:

- End-to-end trust completion still requires the user to accept the current Hook definition in Codex and then trigger one real lifecycle event.

## Implementation Record — 2026-08-15 (Codex Hook Topic Pollution Repair)

Closed the remaining live-Hook bypass that allowed Codex child and internal sessions to pollute OnlineWorker state and Telegram Topics.

Verified root cause:

- Stored-session listing already filtered Codex `thread_source=subagent`, but official Hook and `notify` completion events entered the adapter independently of that listing path.
- `notify` marks its transport as `source=codex_notify`; the adapter previously queried Codex SQLite by session id only when `source` was absent, so a real subagent completion could still publish `session.created` and turn events.
- `turn/started` could then materialize an unbound Telegram Topic because providers without an explicit Topic policy inherited a fail-open default.
- OnlineWorker login-backed Codex AI helpers also launched `codex exec` without disabling Hooks, so Codex's internal activity-summary and short-title tasks could re-enter the same lifecycle path.

Implemented behavior:

- Every external Codex Hook/notify event now reuses the canonical SQLite-backed child-session decision by session id, regardless of transport source, before EventBus publication.
- Transcript metadata and exact internal activity/title prompt prefixes remain early suppression signals; `SessionStart` alone no longer creates a visible session.
- Login-backed Codex AI completion invokes `codex exec --disable hooks`, preventing OnlineWorker-owned helper tasks from generating lifecycle events.
- Unbound Topic materialization is now fail-closed unless the provider explicitly opts in. User-triggered `/list` and workspace-open Topic creation remain unchanged.
- Root logging suppresses `httpx` request-level INFO output and redacts Telegram Bot URL credentials at the shared file/stdout formatter boundary.

Cleanup and reconciliation:

- Deleted `71` classified abnormal Telegram Topics: `42` known Codex subagent Topics, `25` activity-summary Topics, `3` short-title Topics, and `1` final residual child Topic.
- Removed the matching routes plus `78` stale local Codex child/internal thread records without modifying Codex SQLite, rollout, transcript, or provider history.
- Preserved two genuine parent sessions and refreshed their state/route titles to `修复工程编译错误` and `接入 mediautils 鸿蒙源码依赖`.
- Cleanup backups are retained under `/tmp/onlineworker-topic-cleanup-20260815-*` and `/tmp/onlineworker-state-before-topic-cleanup-20260815-1045.json`.
- Redacted `94,084` historical Telegram Bot URL occurrences in the active and rotated local logs without copying the sensitive originals.

Verification:

- Focused login, adapter, and streaming regression passed: `96 passed`.
- Hook bridge, TUI, workspace-open, and provider-boundary regression passed: `102 passed`.
- A real post-install Codex subagent completed with `emitted=0`; it produced no `session.created`, local thread, or Telegram route.
- After restart, live inventory reported `0` Codex child threads in OnlineWorker state, `0` internal activity/title threads, and `0` classified abnormal Telegram routes.
- Logging regression passed `13` tests; the installed runtime produced `0` new `httpx` request lines and all local log generations contained `0` unredacted Telegram Bot URLs.
- `OnlineWorker_1.8.3_aarch64.dmg` was rebuilt and installed; DMG SHA-256: `f45e6ee501337b9ba33288177abd9b8d2832931938d0d807ff55eb62939629a1`.
