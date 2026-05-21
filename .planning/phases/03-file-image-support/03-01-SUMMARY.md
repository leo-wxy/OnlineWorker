# Phase 3 Plan 03-01 Summary: Telegram Attachment Routing

**Updated:** 2026-05-21
**Status:** Completed; source/runtime-path and live post-fix TG attachment smoke verified

## Scope Closed

Plan 03-01 upgraded the message path from text-only delivery toward an attachment-aware provider contract:

- Added `ProviderAttachment` and file capability flags in `core/providers/contracts.py`.
- Extended provider message hooks and default message runtime to pass `attachments` through the shared send path.
- Added Telegram photo and document download in `bot/handlers/message.py`, storing files under the configured OnlineWorker data directory before dispatch.
- Routed attachment messages through the existing workspace/thread/provider flow instead of bypassing provider plugins.
- Declared builtin `codex` and `claude` photo/file capability in descriptors and plugin metadata.
- Added provider-specific attachment handling behind provider boundaries:
  - `codex` forwards attachment payloads through owner/app-server bridge paths.
  - `claude` renders local attachment paths into the prompt text accepted by Claude CLI.

## Latest Fixes From 2026-05-21

The latest TG image failure was not a Telegram download failure. The real sequence observed in the installed app log was:

- Telegram photo update received on topic `7431` with caption `图片里什么内容`.
- Telegram `getFile` succeeded.
- Telegram file download succeeded.
- OnlineWorker sent the "thinking" message successfully.
- Claude turn started.
- The send failed with `Separator is not found, and chunk exceed the limit`.

The failure came from the Claude adapter reading Claude CLI stream output with the default `asyncio.StreamReader.readline()` buffer limit. Claude CLI can emit a large stream-json line, especially around attachment/tool output, and Python raises that error before OnlineWorker can parse the event.

Changes made:

- `plugins/providers/builtin/claude/python/adapter.py`
  - Added `CLAUDE_STREAM_BUFFER_LIMIT = 10 * 1024 * 1024`.
  - Passed `limit=CLAUDE_STREAM_BUFFER_LIMIT` to the Claude send subprocess.
- `bot/handlers/message.py`
  - Added `send_text = text if text and text.strip() else caption`.
  - Passed `send_text` through local-owner, prepare-send, message-hooks send, and direct adapter send paths.
  - This preserves Telegram image/file captions as the actual user text for provider delivery.
- `tests/test_claude_adapter.py`
  - Added regression coverage that the Claude send subprocess uses a larger stream limit.
- `tests/test_handlers.py`
  - Updated attachment forwarding coverage so Telegram document captions are forwarded as provider text.

## Verification

Verified in source/runtime-path tests:

```text
~/.pyenv/versions/3.13.1/bin/python3 -m pytest \
  tests/test_handlers.py \
  tests/test_thread_controls.py \
  tests/test_config.py \
  tests/test_claude_adapter.py::test_claude_adapter_uses_larger_subprocess_stream_limit_for_send \
  -q

68 passed in 4.75s
```

Additional related verification from the latest fix:

```text
~/.pyenv/versions/3.13.1/bin/python3 -m pytest \
  tests/test_handlers.py \
  tests/test_events.py \
  tests/test_events_streaming.py \
  tests/test_claude_adapter.py::test_claude_adapter_send_user_message_renders_attachment_paths \
  tests/test_claude_adapter.py::test_claude_adapter_uses_larger_subprocess_stream_limit_for_send \
  -q

80 passed in 5.37s
```

Formatting check passed:

```text
git diff --check -- \
  bot/handlers/message.py \
  plugins/providers/builtin/claude/python/adapter.py \
  tests/test_claude_adapter.py \
  tests/test_handlers.py
```

User live smoke confirmation:

- On 2026-05-21, the user sent a fresh Telegram attachment after the installed-app update and confirmed the path works.
- No new user-observed `Separator is not found` failure remains after the post-fix smoke.

## Known Remaining Verification

- None for Telegram attachment routing in Phase 3.
- Adjacent full Claude adapter auth/env tests still have 6 failures unrelated to this attachment stream-limit fix. They are auth/runtime-env expectation failures, not Telegram attachment routing failures.
