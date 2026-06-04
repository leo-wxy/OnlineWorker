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

- Telegram renderer
- App session stream
- TaskBoard/session activity cards
- Notification router and summary generator
- Dashboard/status activity
- Audit/debug logs
- Future notification/IM plugins

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

Telegram should render from bus events or a bus-derived adapter layer.

Telegram-specific details such as chat id, topic id, message id, parse mode,
reply markup, and edit/send decisions belong at the Telegram consumer edge.

Telegram routing must continue to use Phase 11 route storage. Missing thread or
topic mappings must not fall back to global agent topics for approvals.

### App Sessions

App session views should read session history plus live bus events/projections.

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

### Notifications

Notification summary should be a consumer of final reply / turn completion
events, not a separate hidden completion pipeline.

Notification channels from Phase 6 remain the delivery mechanism. The event bus
should decide what happened; the notification router should decide where/how to
deliver.

### Approvals And Questions

Approval and question ownership rules from Phase 12 remain intact.

The bus can publish `approval.requested` and `approval.answered`, but it must
not invent authorization authority. Codex app-server remains the approval source
of truth for OnlineWorker-managed Codex sessions.

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
- Do not change Codex approval ownership semantics from Phase 12.
- Do not log or expose secrets in event payloads.
- Do not make TaskBoard depend on Telegram message ids.
- Do not make notifications depend on Telegram rendering state.
- Do not make App session display depend on notification summaries.

## Triggering Discussion

This phase was opened on 2026-06-04 after a TaskBoard/session-card discussion.
The user explicitly called out that the same root problem affected prior
notifications too: each feature had its own message handling logic, which made
behavior inconsistent and difficult to reason about.
