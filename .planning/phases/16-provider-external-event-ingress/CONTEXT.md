# Phase 16 Context: Provider External Event Ingress

## Trigger

Phase 16 was created on 2026-06-06 after Phase 14 UAT showed that the
TaskBoard/message bus chain still missed externally launched provider sessions.

Observed product behavior:

- Codex sessions entered the Phase 14 message bus.
- Claude sessions could be actively running while TaskBoard showed only a title
  or stale content.
- Codemaker sessions could be actively running while no corresponding running
  card appeared until late or after completion.
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
- Codemaker/OpenCode plugin lifecycle control.
- Provider-private hook payload parsing.
- Provider-private session file, SQLite, JSONL, SSE, or config discovery.
- `if provider == "claude"` or `if provider == "codemaker"` recovery logic.

TaskBoard also stays provider-neutral. It consumes the message bus projection and
must not inspect provider-private files, sockets, databases, hook payloads, or
Codemaker/OpenCode config.

## Reference Code

### CodeIsland For Claude Hook Shape

CodeIsland is the local reference for Claude external session listening.

Local evidence:

- `~/.codeisland/codeisland-hook.sh` forwards Claude hook stdin to a native
  bridge or Unix socket fallback.
- `~/.claude/settings.json` contains CodeIsland hooks on `SessionStart`,
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

### OpenCode As Codemaker Reference Only

OpenCode is a reference for Codemaker because Codemaker is based on OpenCode.
Phase 16 does not implement OpenCode as a provider.

Reference evidence:

- The local OpenCode plugin type definition exposes
  `event?: (input: { event }) => Promise<void>`.
- OpenCode-style plugin events are the model for how Codemaker should listen to
  external session/message/step activity.

Phase 16 uses OpenCode only to understand Codemaker-compatible hook/listener
patterns. It must not add an OpenCode provider, public OpenCode integration, or
core OpenCode compatibility layer.

### Existing Codemaker Plugin

Current Codemaker provider plugin already has event mapping:

- `codemaker/python/event_mapper.py`
- `codemaker/python/adapter.py`
- `codemaker/python/runtime.py`
- `codemaker/python/provider.py`

Current useful behavior:

- `event_mapper.emit_envelope()` emits existing `app-server-event` envelopes.
- `message.part.updated` already maps text parts to delta/final-like events.
- `step-start` already maps to `turn/started`.
- `session.created` and `session.updated` already map session creation/title
  updates.

Current limitation:

- `/global/event` follows the serve instance OnlineWorker is connected to. It is
  useful for OnlineWorker-owned Codemaker runtime, but it can miss user-started
  external Codemaker sessions.
- Phase 16 should add Codemaker plugin-owned external listening by referencing
  OpenCode-compatible hook/listener behavior, not by adding core scans.

## Modification Scope

### Allowed Product Code Scope

Claude implementation scope:

```text
OnlineWorker/plugins/providers/builtin/claude/
```

Codemaker implementation scope:

```text
codemaker/
```

New implementation files, if needed, must stay inside those plugin directories.
Suggested names should avoid implying a new OpenCode provider. Prefer names such
as:

- `external_ingress.py`
- `global_hook_settings.py`
- `hook_event_mapper.py`
- `codemaker_event_listener.py`
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
- `tests/test_codemaker_provider_defaults.py`
- `tests/test_codemaker_external_ingress.py`
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

Codemaker:

```text
Codemaker external listener
  -> Codemaker provider plugin event ingress
  -> existing Codemaker event mapper or plugin-local equivalent
  -> existing app-server-event
  -> Phase 14 message bus
  -> TaskBoard projection
```

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
externally launched Claude and Codemaker sessions enter the existing message bus.

The design should remain:

```text
plugin listens
plugin translates
bus receives
TaskBoard projects
```
