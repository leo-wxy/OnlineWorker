# Phase 18 Context: Provider Session New Flow

## Trigger

Phase 18 was created on 2026-07-05 after the App Session tab `New` flow was
fixed and validated against the installed app.

The immediate follow-up is Telegram session-topic `/new`:

```text
existing Telegram session topic
  -> user sends /new <initial message>
  -> OnlineWorker must create a new provider-backed session under the same workspace
  -> OnlineWorker must create or bind a new Telegram topic for that new session
  -> initial message goes to the new session, not the current session
```

Before this phase, the product had two closely related gaps:

- App Session `New` could create local-only/draft-like state or return the
  message to the input when the provider was slow.
- Telegram session-topic `/new` was not locked down as a real new-session
  operation with the same product semantics as App `New`.

The App side has now been fixed in the v1.7.2 line. Phase 18 keeps that work in
the plan history and finishes the Telegram side.

## Product Rule

`New` means a new real provider session.

It must not mean:

- a visible local-only `app:*` draft row
- a fake session placeholder
- sending `/new` or the initial message into the current session
- waiting for the user to manually create a provider session elsewhere

The App and Telegram surfaces may present the flow differently, but the backend
truth is the same: provider `start_thread` or an equivalent provider-owned
session creation path must materialize the session.

## Convergence Status

Phase 18 has already aligned the product behavior across App `New` and
Telegram `/new`: both now mean "create a real provider-backed session, then
send the first user message into that new session."

The code paths are not fully converged yet:

- App still enters through provider owner bridge `start_session_message`.
- Telegram still enters through the local `/new` handler and its topic-binding
  flow.

The next convergence step should therefore extract a shared provider-backed
new-session core service, not force App and Telegram to share one complete
handler.

That shared core should own:

- provider/session validation
- adapter resolution
- `start_thread`
- real `ThreadInfo` materialization
- first-message send into the new real session
- post-send persistence/result shaping

The outer shells must remain surface-specific:

- App keeps the owner-bridge `pending` response model for slow provider
  startup.
- Telegram keeps forum-topic creation, route binding, route-aware rollback,
  and source-topic handoff messaging.

## Completed App Behavior

The App Session tab now follows this behavior:

- `New` opens an in-memory first-message composer.
- Sending the first message calls `start_session_message` through the provider
  owner bridge.
- The bridge asks the provider to create a real thread/session, then sends the
  first user message into that real thread.
- Slow provider creation can return a pending result to the UI without restoring
  the text into the composer.
- The UI keeps the optimistic user message visible and selects the real provider
  session when matching activity arrives.
- Visible session lists do not show local `app:*` draft ids.

Real installed-app Codex validation evidence from 2026-07-04:

```text
provider: codex
workspace: /Users/wxy/Projects/FrciblyK12
session: 019f2dda-bb82-79d3-86af-cbf29e730df9
message: 这个工程的主要作用是什么？
status: completed
lastEventKind: turn.completed
mirroredOnly: false
```

Relevant log evidence:

```text
thread/start RPC 超时，但 notification 已返回 thread=019f2dda-bb8 workspace=codex:/Users/wxy/Projects/FrciblyK12
start_session_message 跳过 prepare_send provider=codex thread=019f2dda-bb8
```

This proves the App flow created and used a real provider session, even when
Codex `thread/start` was slow enough to cross the request timeout boundary.

## Remaining Telegram Behavior

When a user sends this in an existing Telegram session topic:

```text
/new Explain this project
```

OnlineWorker should:

1. Resolve the current topic as a concrete session topic.
2. Use that session's workspace as the target workspace.
3. Create a new provider-backed session under that workspace.
4. Create or bind a new Telegram topic for the new session.
5. Send `Explain this project` as the first message to the new provider session.
6. Reply in the original topic with a short handoff message.
7. Send the normal thread control panel in the new topic.

The current existing session must not receive:

- `/new Explain this project`
- `Explain this project`
- provider `resume_thread` or `send_user_message` calls for this command

## Boundaries

### Provider Boundary

Provider-specific creation rules stay behind provider hooks:

- Codex can require an initial message for materialization.
- Claude/custom providers may support empty sessions if their hooks allow it.
- Provider-specific start-thread delays must be handled in the provider adapter
  or owner bridge, not by creating visible fake sessions.

### Telegram Route Boundary

Telegram topic routing remains terminal delivery state.

Allowed:

- Use the current session topic to find the owning workspace.
- Bind the new Telegram topic to the newly created provider session.
- Mark failed topic creation/rollback clearly.

Not allowed:

- Fall back to an unrelated workspace when a route store knows the topic is
  unknown or invalid.
- Send the new conversation content into the old topic after a new session has
  been created.
- Let Telegram topic creation success mask provider session creation failure.

### Message Boundary

All provider-bound user text still goes through the OnlineWorker user message
gateway before provider send.

The initial message for `/new <initial message>` is provider-bound user text,
so it must use the same gateway path as existing Telegram new-thread sends.

### Approval Boundary

This phase must not change Codex approval ownership, app-server request/reply
authority, mirrored-only approval behavior, or Telegram approval callback rules.

## Existing Code Anchors

Telegram slash routing:

- `bot/handlers/slash.py`
- `bot/command_rules.py`
- `tests/test_slash_router.py`

Telegram new thread/session creation:

- `bot/handlers/thread.py`
- `bot/handlers/workspace.py`
- `bot/handlers/workspace_helpers.py`
- `tests/test_workspace_thread_open.py`

Provider thread hooks:

- `core/providers/contracts.py`
- `core/providers/thread_runtime.py`
- `plugins/providers/builtin/codex/python/runtime.py`
- `plugins/providers/builtin/claude/python/provider.py`

App new-session flow already implemented:

- `core/provider_owner_bridge.py`
- `plugins/providers/builtin/codex/python/adapter.py`
- `mac-app/src/pages/SessionBrowser.tsx`
- `mac-app/src/components/session-browser/GenericProviderChat.tsx`
- `mac-app/src/components/session-browser/api.ts`
- `mac-app/tests/sessionNewComposer.test.mjs`

## Known Implementation Shape

The existing Telegram `/new` handler already resolves workspace context in this
order:

1. workspace topic -> that workspace
2. session topic -> that session's workspace
3. global/legacy fallback -> active workspace

That shape is close to the target product behavior. Phase 18 should first prove
the session-topic `/new` behavior with failing tests. Only then should it patch
routing or handler logic if the tests reveal a real gap.

After that behavior lock, the next slice should converge the duplicated
provider-backed new-session core between owner bridge and Telegram while
preserving each surface's transport-specific shell.

## Verification Standard

Source verification must cover:

- slash-router behavior for `/new <initial message>` in a session topic
- no passthrough to the current provider session
- new provider session creation and Telegram topic binding
- workspace-topic `/new` regression
- Codex empty `/new` rejection
- generic provider or Claude behavior where provider hooks allow empty sessions

Release or tag confidence requires installed-app verification, because this
feature touches packaged bot runtime behavior and real Telegram topic/session
routing.
