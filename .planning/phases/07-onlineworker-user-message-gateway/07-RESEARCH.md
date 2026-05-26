# Phase 7 Research: OnlineWorker User Message Gateway

## Research Complete

**Question:** What do we need to know to plan a single OnlineWorker-level user-message gateway with before-send hooks?

## Existing Send Surfaces

OnlineWorker already has several provider-bound user-message paths that share the same business meaning but enter through different files:

- Telegram thread messages enter `bot/handlers/message.py::_dispatch_thread_message`, which currently calculates `send_text`, validates attachment capability, optionally calls provider `handle_local_owner`, then calls provider `ensure_connected`, `prepare_send`, and `send`.
- Telegram command-wrapper dispatch also reuses `_dispatch_thread_message`, so it should inherit gateway behavior only when the command dispatch policy allows it.
- Session Tab sends through the Rust/Tauri provider sessions command, which forwards to the Python `ProviderOwnerBridge._handle_send_message`; this path currently calls provider `try_route_owner_bridge_send`, `ensure_connected`, `prepare_send`, and `send`.
- `core/provider_session_bridge.py::send_provider_session_message` starts the provider runtime and calls provider `message_hooks.send` directly.
- New-thread initial messages can bypass `_dispatch_thread_message` through `bot/handlers/thread.py::_activate_new_thread_in_source` and `core/providers/thread_runtime.py::activate_default_new_thread`.
- Codex CLI direct input is outside OnlineWorker's send path today. The repository already installs a Codex `PermissionRequest` hook bridge through `plugins/providers/builtin/codex/python/hook_bridge.py`; `UserPromptSubmit` exists in the user's Codex hook file, but OnlineWorker does not currently handle that event.

## Current Provider Boundary

Provider-specific behavior is already isolated behind provider registry contracts:

- `core/providers/contracts.py::ProviderMessageHooks` owns `ensure_connected`, `prepare_send`, `send`, optional `handle_local_owner`, optional `try_route_owner_bridge_send`, and attachment capability flags.
- Codex runtime `send_message` marks send start, task summary, handles attachments, and calls `adapter.send_user_message`.
- Provider owner bridge tests already verify text and attachments reach provider hooks unchanged. These are good regression anchors for proving gateway output is what provider hooks receive.

The gateway should sit above provider hooks and below input adapters. It should not absorb provider behaviors such as Codex active-turn interruption, thread materialization, owner-bridge routing, Claude runtime behavior, or provider adapter send details.

## Configuration Pattern

`config.py` already uses dataclasses plus YAML-backed nested sections for notifications. The message gateway should follow the same style:

```yaml
message_hooks:
  enabled: true
  builtin:
    abusive_language_normalization:
      enabled: true
      mode: conservative
```

The first implementation can default to enabled conservative behavior if config is absent, with focused tests documenting the default. A later UI phase can expose this setting if needed.

## Gateway Shape

Recommended core package:

```text
core/user_messages/
  __init__.py
  contracts.py
  builtin_hooks.py
  gateway.py
  hooks.py
```

Recommended request/result model:

```python
UserMessageSendRequest(
    source="telegram" | "owner_bridge" | "provider_session_bridge" | "new_thread" | "codex_cli_hook",
    provider_id="codex",
    workspace_id="codex:/path",
    thread_id="...",
    text="...",
    attachments=[],
    metadata={},
)
```

The gateway should run deterministic OnlineWorker-level hooks, then delegate to a provider sender callback or existing provider send sequence. To keep the first implementation small, gateway can expose reusable text-processing functions and a send helper used by Python send surfaces, while retaining provider-specific sequences at the call site until a larger consolidation is justified.

## Built-In Hook Scope

`abusive_language_normalization` should be conservative and deterministic:

- It should remove or neutralize abusive modifiers without changing task intent.
- It should preserve code blocks and slash commands by default.
- It should not inspect or mutate attachment file contents.
- It should not touch provider output, notifications, approval prompts, or final-reply sync.
- It should record whether text changed without logging full original text by default.

Canonical example:

```text
这什么傻逼问题
=> 这是什么问题
```

## Codex CLI UserPromptSubmit Risk

The user's local Codex config already contains a `UserPromptSubmit` hook entry, but the repository only handles `PermissionRequest`. The plan should include:

1. Read current Codex hook payload/return protocol from a real minimal hook test or official/local docs available in the environment.
2. Extend OnlineWorker's Codex hook bridge only if the protocol supports prompt replacement or a useful safe behavior.
3. Guard against recursion by tagging requests from `codex_cli_hook`.

If prompt replacement is unsupported, the phase can still deliver gateway coverage for OnlineWorker-managed send paths and document Codex direct CLI rewrite as blocked by upstream hook protocol.

## Validation Architecture

Validation should cover the gateway at four levels:

1. Pure hook tests for conservative normalization and skip rules.
2. Config tests for default and disabled hook behavior.
3. Send-surface tests proving Telegram, owner bridge, provider session bridge, and new-thread initial messages pass transformed text to provider hooks.
4. Codex hook bridge tests for `UserPromptSubmit` payload handling and return behavior, gated by the observed protocol.

Small source-level regressions are sufficient for the planning phase. Installed-app verification is required only after implementation changes are complete.
