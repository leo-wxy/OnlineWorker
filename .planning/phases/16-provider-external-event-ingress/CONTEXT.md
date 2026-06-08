# Phase 16 Context: Provider External Event Ingress

## Trigger

Phase 16 was created on 2026-06-06 after Phase 14 UAT showed that the
TaskBoard/message bus chain still missed externally launched provider sessions.

Observed product behavior:

- Codex sessions entered the Phase 14 message bus.
- Claude sessions could be actively running while TaskBoard showed only a title
  or stale content.
- A distribution-provided provider plugin could have active external sessions
  while no corresponding running card appeared until late or after completion.
- Switching back to the TaskBoard tab could make running cards disappear when no
  fresh bus event was available.

The narrowed problem is external provider event ingress:

```text
provider external runtime activity
  -> missing or incomplete provider plugin listener
  -> no normalized provider event
  -> message bus has nothing to project
```

Phase 16 exists to fix that ingress boundary inside provider plugins.

## Non-Negotiable Boundary

Core/message bus is only a receiver.

Allowed in core:

- Receive already-normalized provider events.
- Map existing provider/session event shapes to message bus events.
- Update generic projections from normalized events.

Not allowed in core:

- Claude hook lifecycle control.
- Distribution-provider/OpenCode-compatible plugin lifecycle control.
- Provider-private hook payload parsing.
- Provider-private session file, SQLite, JSONL, SSE, or config discovery.
- provider-specific recovery branches for external ingress.

TaskBoard also stays provider-neutral. It consumes the message bus projection and
must not inspect provider-private files, sockets, databases, hook payloads, or
provider/OpenCode-compatible config.

### Topic And Telegram Boundary

`topic` and Telegram routing are terminal delivery concerns only.

Main-chain behavior must stay valid without any topic binding:

- provider runtime execution
- local approval/question handling
- normalized provider event publication
- message bus projection
- TaskBoard rendering

Allowed topic/TG behavior:

- Mirror already-existing state or events to Telegram when a route exists.
- Accept Telegram replies or approval decisions when a route exists.
- Fail independently with logging when the route is missing, stale, or invalid.

Not allowed:

- block CLI/provider execution because topic lookup failed
- block approval/question main-chain handling because topic lookup failed
- block normalized event publication or TaskBoard updates because topic lookup
  failed
- declare the provider/session flow failed only because Telegram mirroring
  could not happen

Missing topic may break Telegram mirroring. It must not break the main chain.

### User-Visible Message Dedupe Boundary

The same assistant output may exist in more than one transport or log shape,
for example:

- `event_msg` / `agent_message`
- `response_item` / `message`

These are alternate representations of the same underlying assistant output,
not permission to render two visible messages.

User-visible consumers must deduplicate equivalent assistant content before
rendering or replay. A second transport representation of the same content must
update or confirm the existing message, not create another visible reply.

Main-source rule:

- each provider/session/turn has exactly one user-visible main message source
- mirror, polling, hook fallback, transcript replay, and alternate raw record
  shapes are fallback/observation only
- fallback layers may confirm or recover main-chain state, but they must not
  emit a second visible message in parallel with the main chain

## Reference Code

### Claude Hook Shape Reference

Local Claude hook integrations are the reference for Claude external session
listening.

Local evidence:

- a local hook command can forward Claude hook stdin to a native bridge or Unix
  socket fallback.
- `~/.claude/settings.json` can contain third-party hooks on `SessionStart`,
  `UserPromptSubmit`, `Stop`, `SessionEnd`, `PostToolUse`, `PreToolUse`,
  `PermissionRequest`, and `Notification`.
- Multiple hook listeners coexist in the same global Claude settings file.

Phase 16 uses this only as a reference for how Claude global hooks should be
attached safely. OnlineWorker must not take ownership of the entire Claude
settings file.

### Existing Claude Plugin

Current Claude provider plugin already has a hook bridge:

- `plugins/providers/builtin/claude/python/hook_bridge.py`
- `plugins/providers/builtin/claude/python/adapter.py`
- `plugins/providers/builtin/claude/python/runtime.py`

Current limitation:

- The existing hook bridge primarily covers approval/question behavior through
  `PreToolUse`, `PermissionRequest`, and `Notification`.
- It writes an OnlineWorker-owned hook settings file under the OnlineWorker data
  directory.
- It does not yet merge OnlineWorker entries into global
  `~/.claude/settings.json`.
- It does not yet map external-session lifecycle events such as `SessionStart`,
  `UserPromptSubmit`, `Stop`, and `SessionEnd` into normalized provider events.

### OpenCode-Compatible Listener Reference Only

OpenCode-compatible listener behavior is a reference for compatible
distribution-provided provider plugins. Phase 16 does not implement OpenCode as
a provider.

Reference evidence:

- The local OpenCode plugin type definition exposes
  `event?: (input: { event }) => Promise<void>`.
- OpenCode-style plugin events are the model for how compatible provider
  plugins can listen to external session/message/step activity.

Phase 16 uses OpenCode only to understand compatible hook/listener patterns. It
must not add an OpenCode provider, public OpenCode integration, or core
OpenCode compatibility layer.

### Distribution-Provided Provider Plugin

The distribution-provided provider plugin already has event mapping in its own
package outside the upstream OnlineWorker source tree:

- provider-local event mapper
- provider-local adapter
- provider-local runtime
- provider-local descriptor

Current useful behavior:

- `event_mapper.emit_envelope()` emits existing `app-server-event` envelopes.
- `message.part.updated` already maps text parts to delta/final-like events.
- `step-start` already maps to `turn/started`.
- `session.created` and `session.updated` already map session creation/title
  updates.

Current limitation:

- `/global/event` follows the serve instance OnlineWorker is connected to. It is
  useful for OnlineWorker-owned provider runtime, but it can miss user-started
  external provider sessions.
- Phase 16 should add provider-plugin-owned external listening by referencing
  OpenCode-compatible hook/listener behavior, not by adding core scans.

## Modification Scope

### Allowed Product Code Scope

Claude implementation scope:

```text
OnlineWorker/plugins/providers/builtin/claude/
```

Distribution-provided provider implementation scope:

```text
distribution package outside OnlineWorker/
```

New implementation files, if needed, must stay inside those plugin directories.
Suggested names should avoid implying a new OpenCode provider. Prefer names such
as:

- `external_ingress.py`
- `global_hook_settings.py`
- `hook_event_mapper.py`
- `provider_event_listener.py`
- `opencode_compatible_events.py`

### Allowed Documentation Scope

Planning docs may be updated:

```text
OnlineWorker/.planning/
```

### Allowed Test Scope

Tests may cover plugin behavior and standard event delivery, but should not
force core provider-specific code.

Likely test files:

- `OnlineWorker/tests/test_claude_adapter.py`
- `OnlineWorker/tests/test_claude_external_ingress.py`
- distribution-owned provider default tests
- distribution-owned provider external ingress tests
- existing standard bus/owner-bridge tests only when asserting normalized event
  delivery

### Forbidden Product Code Scope

Phase 16 should not modify these areas for provider-specific behavior:

```text
OnlineWorker/core/
OnlineWorker/core/messages/
OnlineWorker/core/provider_owner_bridge.py
OnlineWorker/mac-app/
OnlineWorker/bot/
OnlineWorker/config.py
OnlineWorker/main.py
```

Small changes outside plugin directories require a separate explicit reason and
must not add provider-specific hook/listener behavior. The default expectation
is no non-plugin product code changes.

## Desired Event Flow

Claude:

```text
Claude global hook
  -> Claude provider plugin hook bridge
  -> Claude plugin lifecycle/event mapper
  -> existing app-server-event or provider event
  -> Phase 14 message bus
  -> TaskBoard projection
```

Distribution-provided provider:

```text
provider external listener
  -> provider plugin event ingress
  -> existing provider event mapper or plugin-local equivalent
  -> existing app-server-event
  -> Phase 14 message bus
  -> TaskBoard projection
```

Telegram/topic mirroring, when enabled, is downstream of this chain. It may
observe and mirror the result, but it must not gate or redefine the chain.

OpenCode:

```text
reference only
```

## Out Of Scope

Phase 16 does not include:

- OpenCode provider implementation.
- Public third-party event bus/plugin API.
- App Session detail live rendering migration.
- Telegram send/edit/topic rendering migration.
- Approval/question command-boundary work.
- TaskBoard provider-private discovery.
- Full transcript replay.
- Full tool-call UI replay.
- Persistent event audit/replay storage.
- Packaged validation before source-level ingress is proven.

## Success Direction

Phase 16 is successful when the provider plugins, not core, can explain how
externally launched Claude and distribution-provided provider sessions enter
the existing message bus.

The design should remain:

```text
plugin listens
plugin translates
bus receives
TaskBoard projects
```
