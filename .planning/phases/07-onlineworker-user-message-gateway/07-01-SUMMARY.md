# 07-01 Summary: OnlineWorker User Message Gateway

## Result

Implemented the OnlineWorker-level provider-bound user message gateway and first built-in `before_user_message_send` hook.

The gateway now owns the shared text-preparation boundary for user messages before provider-specific send hooks run. The first built-in hook, `abusive_language_normalization`, conservatively rewrites abusive phrasing such as:

```text
这什么傻逼问题
=> 这是什么问题
```

## Implemented

- Added `core/user_messages/`:
  - `contracts.py`: common request/context/result dataclasses.
  - `builtin_hooks.py`: deterministic abusive-language normalization with fenced-code preservation.
  - `hooks.py`: before-send hook runner, slash-command skip, command-dispatch skip, and config checks.
  - `gateway.py`: `prepare_user_message_text(...)` entrypoint.
- Added `message_hooks` config parsing in `config.py`:
  - default enabled.
  - built-in `abusive_language_normalization` default enabled in `conservative` mode.
  - `enabled: false` and `mode: off` disable the hook at runtime.
- Routed OnlineWorker-managed provider-bound send paths through the gateway:
  - Telegram thread messages in `bot/handlers/message.py`.
  - New-thread initial messages in `bot/handlers/thread.py`.
  - Owner bridge sends in `core/provider_owner_bridge.py`, before `try_route_owner_bridge_send`, `prepare_send`, and `send`.
  - Provider session bridge sends in `core/provider_session_bridge.py`, with current config loaded when available.
- Added Codex CLI hook boundary handling:
  - `CODEX_USER_PROMPT_SUBMIT_HOOK_NAME = "UserPromptSubmit"` is now modeled.
  - `UserPromptSubmit` returns `{}` and does not use the PermissionRequest mirror.
  - Local evidence showed the event exists in the installed Codex binary and current `~/.codex/hooks.json`, but prompt replacement response support was not confirmed, so the safe behavior is pass-through.

## Verification

Passed:

```bash
rtk pytest -q tests/test_handlers.py tests/test_user_message_hooks.py tests/test_config.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py tests/test_provider_session_bridge_attachments.py tests/test_codex_hook_bridge.py && git diff --check
```

Observed result:

```text
Pytest: 132 passed
```

`git diff --check` produced no output.

## Not Run

Packaged-app build/install/relaunch verification was not run for Phase 7. Run the full installed-app verification chain before release.
