# Phase 15 Context: Bus-Driven Rendering And Approval Command Boundary

## Trigger

Phase 15 was created on 2026-06-05 during the Phase 14 design review.

Phase 14 intentionally keeps the first message bus slice scoped to the internal
in-process bus, first projections, TaskBoard, notification summary, and
source-level hardening. The user explicitly deferred heavier rendering and
command-boundary work so Phase 14 can close without turning into a broad UI and
Telegram rewrite.

Deferred work captured here:

- App Session detail live rendering should eventually consume bus-derived live
  events instead of maintaining a separate provider/session stream model.
- Telegram send/edit/topic rendering should eventually become a bus-derived edge
  consumer while preserving Telegram routing guardrails from Phase 11.
- Approval/question events currently remain observational lifecycle events. A
  later phase should decide whether a separate command boundary is needed.

## Phase 14 Decisions Carried Forward

Phase 14 decisions that Phase 15 must preserve:

- Phase 14 bus is internal and in-process.
- Phase 14 does not expose a public third-party plugin event API.
- Phase 14 does not persist every canonical event as a structured audit/replay
  log. Existing runtime logs for warnings, failures, and diagnostics remain
  allowed.
- Phase 14 approval/question bus events are observational only. They feed
  projections and consumers but do not execute actions.
- App Session detail live rendering is not migrated in Phase 14.
- Telegram send/edit/topic rendering is not migrated in Phase 14.
- Codex app-server approval source-of-truth from Phase 12 must remain intact.
- Telegram topic routing source-of-truth from Phase 11 must remain intact.

## Goal

Make the heavy first-party rendering surfaces bus-derived once the Phase 14
event schema is stable.

Target shape:

```text
provider/app/tg runtime event
  -> canonical message bus event
  -> bus-derived renderer/projection
  -> App Session or Telegram edge presentation
```

Phase 15 should also decide whether approval/question handling needs a command
boundary distinct from immutable lifecycle events.

## Scope

In scope:

- App Session detail live rendering migration.
- Telegram rendering/editing/topic edge migration.
- Approval/question command-boundary review.
- Regression coverage for rendering, topic routing, approval/question authority,
  event dedupe, and stream lifecycle.

Out of scope unless a later plan expands scope:

- Public third-party plugin event API.
- External broker infrastructure.
- Persistent canonical event audit/replay log.
- Changing notification plugin settings UI.
- Changing Codex app-server approval source-of-truth semantics.
- Replacing provider adapter protocols.

## App Session Rendering Principle

App Session detail views should be able to render live state from bus-derived
events without losing existing behavior:

- history merge remains stable
- assistant delta/final ordering remains stable
- duplicate final/delta messages are deduped
- scroll behavior remains ergonomic
- loading/error states remain visible
- provider-specific raw payload details remain behind adapters

The App should not infer lifecycle independently when canonical events already
describe user accepted, assistant delta/final, turn started/completed/failed,
approval requested, and question requested.

## Telegram Rendering Principle

Telegram rendering should move toward a bus-derived edge consumer, but the edge
consumer still owns Telegram-specific presentation details:

- chat id
- topic id
- message id
- parse mode
- reply markup
- edit/send decisions
- callback metadata

Phase 11 route storage remains the Telegram routing authority. Missing or
invalid topic mappings must continue to fail closed rather than falling back to a
global agent topic.

## Approval And Question Principle

Phase 15 should explicitly decide whether approval/question should remain
event-only or gain a command boundary.

Current Phase 14 rule:

```text
Events describe what happened.
Commands execute through existing owner/callback/app-server paths.
```

If Phase 15 adds commands, keep the boundary explicit:

- immutable lifecycle events are not commands
- commands carry authorization intent and target ownership
- command handlers validate authority before mutating provider/app-server state
- Codex app-server remains the source of truth for OnlineWorker-managed Codex
  approval decisions
- non-owned Codex Desktop, VS Code, and ordinary CLI sessions remain native or
  mirror-only unless an explicit owned command path exists

## Verification Expectations

Phase 15 must include source tests for:

- App Session live rendering from bus-derived events.
- Telegram streaming/final send/edit behavior from bus-derived events.
- Telegram route fail-closed behavior with Phase 11 route storage.
- Approval/question event-vs-command authority.
- Dedupe between provider runtime events, final messages, and rendered surfaces.
- Compatibility with existing notification and TaskBoard bus consumers.

Packaged verification remains gated on explicit current-conversation approval.
