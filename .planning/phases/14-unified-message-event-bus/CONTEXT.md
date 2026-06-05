# Phase 14 Context: Unified Message Event Bus

## User Intent

The user identified that the current message architecture is drifting into
separate per-surface logic:

- TaskBoard cards are not intuitive because they are assembled from partial
  session/dashboard fields instead of a stable activity model.
- App session sending and Telegram sending are hard to explain as one message
  lifecycle.
- Previous notification work also grew its own completion/summary logic.
- Approval, question, final reply, status, and notification paths have different
  routing and dedupe behavior depending on where they enter the system.

The user decision is:

```text
All messages should go through one bus for distribution and processing.
```

This phase should become the architecture reference for future work on
TaskBoard, Telegram, App sessions, notifications, approvals, questions, and new
IM/plugin surfaces.

Phase 14 itself is scoped to the internal OnlineWorker bus and first consumers.
It does not expose a public third-party plugin event API, does not persist every
canonical event as an audit/replay log, and does not migrate heavy App Session
or Telegram renderers. Those deferred renderer and command-boundary migrations
are tracked in Phase 15.

## Decision

OnlineWorker should have a single normalized message/event bus.

Different entry points remain valid:

- Telegram messages
- App session composer sends
- Provider owner bridge sends
- Provider session bridge sends
- Codex app-server/proxy events
- Claude provider runtime events
- Approval callbacks
- Question answers
- Notification requests

But once a message or lifecycle update enters OnlineWorker, it should publish a
canonical event before surface-specific rendering or storage logic runs.

Consumers should then subscribe to the event stream or read projections derived
from it:

- TaskBoard/session activity cards
- Notification router and summary generator
- Dashboard/status activity
- Bounded in-memory debug reads
- Future App/TG/IM/plugin consumers after separate migration plans

## Why This Is Needed

The current system already has several partial abstractions:

- Phase 6 added notification channels.
- Phase 7 added the user message gateway.
- Phase 8 added AI notification summaries.
- Phase 11 made Telegram topic routing durable.
- Phase 12 clarified Codex approval ownership.
- Phase 13 made provider readiness visible before send.

Those phases solved important boundaries, but they do not yet make the message
lifecycle itself a shared product primitive. As a result, feature work can still
add new per-surface logic that re-derives state from logs, session files,
runtime maps, or Telegram callbacks.

Phase 14 should establish the message/event stream as the shared primitive.

## Required Architecture Shape

```text
input surface / provider runtime
  -> normalize to OnlineWorker event
  -> publish to message event bus
  -> update projections
  -> notify consumers
  -> surface-specific rendering at the edge
```

The bus should carry public OnlineWorker concepts, not provider-private wire
formats as the stable contract.

Canonical event groups:

- `message.user.submitted`
- `message.user.accepted`
- `message.assistant.delta`
- `message.assistant.final`
- `turn.started`
- `turn.completed`
- `turn.failed`
- `approval.requested`
- `approval.answered`
- `question.requested`
- `question.answered`
- `notification.requested`
- `notification.emitted`

Every event should carry:

- event id
- created time
- provider id
- workspace id or workspace path when known
- session/thread id when known
- turn id when known
- source surface
- normalized kind
- dedupe key
- redacted public payload

Provider-private raw payloads can remain available for local adapter handling,
but they should not become the public bus contract.

## Consumer Rules

### Telegram

Telegram should eventually render from bus events or a bus-derived adapter
layer. That heavy renderer migration is not part of Phase 14 and is tracked in
Phase 15.

Telegram-specific details such as chat id, topic id, message id, parse mode,
reply markup, and edit/send decisions belong at the Telegram consumer edge.

Telegram routing must continue to use Phase 11 route storage. Missing thread or
topic mappings must not fall back to global agent topics for approvals.

### App Sessions

App session views should eventually read session history plus live bus
events/projections. Full App Session detail live-rendering migration is not part
of Phase 14 and is tracked in Phase 15.

The App should not need to separately poll and infer whether a message is
running, waiting, failed, or completed when the bus already knows the lifecycle.

### TaskBoard

TaskBoard should read a session activity projection instead of scraping partial
dashboard/session fields.

Cards should show:

- provider
- workspace
- session id
- title or recent user intent
- latest assistant/final summary when available
- current status
- attention reason
- updated time

Current UI constraints from implementation review:

- TaskBoard must listen to the message/event bus activity stream. It should not
  depend on a periodic auto-refresh loop to discover activity updates.
- The card title should be the real session title when known. Assistant stream
  text must not replace the card title.
- The preview area should show the latest useful content. Prefer current
  assistant/final content when present, but fall back to the last user message
  so a running card does not render a large blank area.
- Preview text must be visually clamped to exactly three lines; partial fourth
  lines are not acceptable.
- The "Pinned" lane needs a first-class entry point from Session Browser. The
  Session Browser follow/unfollow action should write the same TaskBoard pinned
  state as the TaskBoard card star button.
- Pinned idle cards should still show the latest useful session message when
  available. A followed session remains useful even when it is not currently
  running.
- TaskBoard user-visible card management should use only pin/unpin. Idle cards
  remain visible only while pinned. There should be no hidden/remove-from-board
  action or hidden state in the target Phase 14 model.
- The Running lane should render from the bus-derived activity projection as
  soon as that projection is available. Full provider session metadata and
  pinned preview hydration can enrich cards later, but they must not block the
  first visible running state.
- Activity stream snapshot/activity events should clear the loading state after
  applying projection data. A running session reported by the provider owner
  bridge must not appear as an empty Running lane.
- A running card should not show a large blank preview area when there is a
  usable last user message, activity title, or resolved card title.

### Usage

Usage date windows should be based on the local app date.

The default seven-day window should roll forward when the local day changes.
For example, on 2026-06-05 the default range should end at 2026-06-05. Refresh
should not keep using a stale 2026-06-04 end date when the user has not manually
applied a custom range.

If the user has manually applied a custom date range, Usage should preserve that
range across refreshes.

### Workflow Note

When a user identifies a new Phase 14 product requirement during implementation,
update the phase plan/context first, then modify code. This keeps the phase
state aligned with the current product target and avoids untracked behavioral
drift.

2026-06-05 source verification covered the TaskBoard pinned idle last-message
preview, the three-line preview clamp regression, and the Usage local-date
default range rollover.

## Current Implementation State

As of 2026-06-05, Phase 14 has landed the first unified message bus slice and
the first TaskBoard/notification consumers.

Completed source-level work:

- `core/messages/` provides the canonical event contract, in-process bus,
  session-event bridge, publish helpers, notification summary consumer, and
  session activity projection.
- Provider runtime events, user send paths, approval/question paths, final
  replies, turn completion, and notification delivery now publish bus events
  beside existing behavior.
- Notification delivery publishes `notification.requested`,
  `notification.emitted`, `notification.skipped`, and `notification.failed`.
- Notification summary generation now consumes `message.assistant.final` through
  the bus consumer path. Completed-summary extraction, local fallback, and AI
  fallback logic live under `core/messages/notification_summary.py`; the old
  completed-summary helper names and file boundary were removed.
- TaskBoard reads the bus-derived session activity projection and receives live
  activity over a Tauri channel stream.
- TaskBoard cards preserve real session titles, use assistant/user/final content
  as preview text, fall back to user/activity/title text while a run is still
  starting, clamp previews to three lines, and keep pinned idle sessions useful
  by hydrating the latest useful session message.
- TaskBoard first paint now includes session activity projection before slower
  provider session list and pinned preview hydration finish, so running cards do
  not disappear while metadata is still loading.
- Session Browser exposes follow/unfollow actions that write the same pinned
  TaskBoard state as the card star button. TaskBoard user-visible card
  management is pin/unpin only; hidden/remove-from-board state and action have
  been removed.
- Usage Browser uses a local-date default range that rolls forward when the
  local day changes, while preserving manually applied custom ranges.
- The app sidecar/provider bridge launch paths set
  `PYINSTALLER_RESET_ENVIRONMENT=1` to prevent packaged-runtime environment
  leakage.
- Codex TUI realtime mirror bootstrap updates its offset after bootstrapped
  commentary so it does not replay stale text as new activity.

Follow-up work from the 2026-06-05 code review is tracked in `14-02-PLAN.md`.
The consumer-boundary cleanup from the 2026-06-05 design review is tracked in
`14-03-PLAN.md`. The user UAT first-paint fix for running TaskBoard cards is
tracked in `14-04-PLAN.md`.

Confirmed Phase 14 follow-up decisions from the 2026-06-05 design review:

- Notification summary has one lifecycle trigger path:
  `message.assistant.final` / `turn.completed` bus events ->
  `NotificationSummaryConsumer` -> notification router. Legacy completion
  summary trigger entry points, names, and file boundaries have been removed or
  moved under the bus consumer boundary.
- App Session detail live rendering is deferred to Phase 15.
- Telegram send/edit/topic rendering is deferred to Phase 15.
- Approval/question bus events are observational only in Phase 14. Command
  boundary design is deferred to Phase 15.
- Persistent canonical event audit/replay logs are excluded from Phase 14.
  Ordinary runtime logs for warnings, failures, and diagnostics remain allowed.
- Public third-party plugin event APIs are excluded from Phase 14.
- TaskBoard hidden/remove-from-board state is not part of the target UI model
  and has been removed; pin/unpin is the only user-visible TaskBoard card
  management action.

### Notifications

Notification summary should be a consumer of final reply / turn completion
events, not a separate hidden completion pipeline.

Phase 14 completed this boundary cleanup by moving the reusable local/AI
summary algorithms under the bus consumer boundary. No non-consumer code imports
or calls the old completed-summary helper names.

Notification channels from Phase 6 remain the delivery mechanism. The event bus
should decide what happened; the notification router should decide where/how to
deliver.

### Approvals And Questions

Approval and question ownership rules from Phase 12 remain intact.

The bus can publish `approval.requested` and `approval.answered`, but it must
not invent authorization authority. Codex app-server remains the approval source
of truth for OnlineWorker-managed Codex sessions.

In Phase 14 these events are observational lifecycle events only. They feed
projections and consumers but do not execute commands. Any future command
boundary is Phase 15 scope.

## Migration Principle

Do this incrementally.

The first implementation should add the bus and publish events from existing
paths while preserving current behavior. Then migrate one projection/consumer at
a time.

Recommended order:

1. Add core event contracts and in-process bus.
2. Publish from provider session event normalization and user send paths.
3. Add session activity projection.
4. Point TaskBoard at the projection.
5. Record notification requested/emitted events.
6. Move notification summary generation to consume final/turn events.
7. Gradually reduce duplicate per-surface lifecycle inference.

## Guardrails

- Do not turn this into a full external broker before the in-process contract is
  proven.
- Do not rewrite provider protocols as part of the first slice.
- Do not change Telegram polling as part of this phase unless a specific plan
  adds that scope.
- Do not migrate App Session detail live rendering in Phase 14.
- Do not migrate Telegram send/edit/topic rendering in Phase 14.
- Do not change Codex approval ownership semantics from Phase 12.
- Do not log or expose secrets in event payloads.
- Do not persist every canonical event as a structured audit/replay log in Phase
  14.
- Do not expose a stable third-party plugin event API in Phase 14.
- Do not make TaskBoard depend on Telegram message ids.
- Do not make notifications depend on Telegram rendering state.
- Do not make App session display depend on notification summaries.

## Triggering Discussion

This phase was opened on 2026-06-04 after a TaskBoard/session-card discussion.
The user explicitly called out that the same root problem affected prior
notifications too: each feature had its own message handling logic, which made
behavior inconsistent and difficult to reason about.
