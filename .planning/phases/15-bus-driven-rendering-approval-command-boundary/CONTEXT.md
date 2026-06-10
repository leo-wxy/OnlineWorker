# Phase 15 Context: Bus-Driven Rendering And Approval Command Boundary

## Trigger

Phase 15 was created on 2026-06-05 during the Phase 14 design review.

Phase 14 intentionally keeps the first message bus slice scoped to the internal
in-process bus, first projections, TaskBoard, notification summary, and
source-level hardening. The user explicitly deferred heavier rendering and
command-boundary work so Phase 14 can close without turning into a broad UI and
Telegram rewrite.

Phase 16 later closed the remaining external-provider ingress gap. External
Claude sessions and distribution-provided provider sessions can now enter the
same bus through provider-plugin-owned ingress, and TaskBoard already reflects
that activity through the existing session activity projection.

Deferred work captured here:

- App Session detail live rendering should eventually consume bus-derived live
  events instead of maintaining a separate provider/session stream model.
- Telegram send/edit/topic rendering should eventually become a bus-derived edge
  consumer while preserving Telegram routing guardrails from Phase 11.
- Approval/question events currently remain observational lifecycle events. A
  later phase should decide whether a separate command boundary is needed.

## Current Post-Phase-16 Reality

Phase 15 should start from the current implementation shape, not only the
original 2026-06-05 design intent:

- External provider ingress is no longer a Phase 15 blocker. Phase 16 already
  proved that external Claude sessions and distribution-provided provider
  sessions can publish canonical lifecycle events into the Phase 14 bus.
- Claude external hooks now use a lightweight non-blocking relay for
  non-owned/native CLI interaction paths. Managed OnlineWorker Claude sessions
  keep the explicit managed hook path.
- TaskBoard already consumes the bus-derived session activity projection and now
  distinguishes mirrored-only approval/question attention from owned actionable
  requests.
- The remaining migration debt is concentrated in heavy consumers and command
  authority, not in provider ingress.

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
- Phase 16 mirrored-only approval/question activity must remain observational.
  A bus event that exists only to mirror native external CLI interaction must
  not gain command authority in Phase 15.

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

## Follow-Up Discovered During Installed-App Investigation

Installed-app investigation on 2026-06-09 exposed a separate distribution/config
model problem that should be recorded here but not reclassified as Phase 15
scope:

- Bundled provider and notification behavior currently depends on multiple
  implicit layers at once: packaged manifests, `default-config.yaml`,
  `~/Library/Application Support/OnlineWorker/config.yaml`, app-support `.env`,
  packaged `Info.plist` environment entries, and current process environment.
- Rust/Tauri settings discovery and Python runtime config loading do not share a
  single effective-config model. Fresh install visibility for bundled
  extensions can therefore differ from machines that already carry local user
  config or overlay environment state.
- Real installed-app evidence showed that bundled resources can exist in
  `/Applications/OnlineWorker.app/Contents/Resources/...` while user-visible
  provider availability still differs by machine because bundled/private
  defaults, local config overrides, and overlay environment rules are merged
  differently.
- Provider settings UI also does not currently render provider icons even when
  metadata contains a resolved icon URL, which makes bundled-extension
  discovery problems harder to diagnose in the App.

This problem is not a failure of the Phase 15 bus-rendering or approval-boundary
work. It should be handled as a dedicated follow-up that:

- separates bundled distribution extensions from external/private overlay
  mechanisms
- unifies Rust/Tauri and Python runtime effective-config rules
- narrows `config.yaml` to user overrides instead of a second hidden default
  source
- surfaces source/default/current state clearly in the Settings UI

## App Session Rendering Principle

App Session detail views should be able to render live state from bus-derived
events without losing existing behavior:

- history merge remains stable
- assistant delta/final ordering remains stable
- duplicate final/delta messages are deduped
- scroll behavior remains ergonomic
- loading/error states remain visible
- provider-specific raw payload details remain behind adapters

Current implementation anchor:

- App Session detail still reads sessions and turns through provider-specific
  desktop commands such as `list_provider_sessions`, `read_provider_session`,
  `send_provider_session_message`, and provider-specific stream access such as
  `start_provider_session_stream`.
- Provider history reads remain acceptable as initial/historical data, but the
  live-rendering model should stop depending on provider-specific stream
  semantics for ongoing UI state.

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

Current implementation anchor:

- Telegram still owns substantial direct edge behavior such as
  `send_message`, `edit_message_text`, and `edit_message_reply_markup`.
- Phase 15 should not delete the Telegram edge. It should make the Telegram edge
  consume canonical bus events as its rendering input while keeping Telegram-
  specific ids and formatting decisions local to that edge.

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
- mirrored-only approval/question activity from external CLI sessions remains
  non-actionable. It can drive TaskBoard/consumer attention state, but it must
  not be upgraded into an owned command path without a separate authority check
  and an explicit ownership contract.

## Verification Expectations

Phase 15 must include source tests for:

- App Session live rendering from bus-derived events.
- Telegram streaming/final send/edit behavior from bus-derived events.
- Telegram route fail-closed behavior with Phase 11 route storage.
- Approval/question event-vs-command authority.
- Mirrored-only approval/question events stay observational and cannot execute
  commands.
- Dedupe between provider runtime events, final messages, and rendered surfaces.
- Compatibility with existing notification and TaskBoard bus consumers.

Packaged verification remains gated on explicit current-conversation approval.
