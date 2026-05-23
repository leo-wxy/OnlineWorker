# Phase 4 Plan 04-01 Summary: Claude Existing-Session Resume Ownership

**Updated:** 2026-05-21
**Status:** Completed; Claude resume ownership, external-busy guard, per-session serialization, and desktop provider-owner routing verified

## Scope Closed

Plan 04-01 aligned Claude session sending across Telegram, provider runtime ownership, and the desktop Session Browser:

- `plugins/providers/builtin/claude/python/runtime.py`
  - Removed the normal-send imported-thread auto-remap path.
  - Resumes imported/history Claude sessions in place by using the original session id.
  - Rejects externally busy Claude sessions before sending so OnlineWorker does not steal terminal-owned work.
- `plugins/providers/builtin/claude/python/adapter.py`
  - Added per-session async send locks around turn startup and Claude CLI process execution.
  - Prevents Telegram and desktop sends from launching competing `claude --resume` processes for the same session id.
- `mac-app/src/components/session-browser/api.ts`
  - Routes Claude Session Browser composer sends through `sendProviderSessionMessage("claude", ...)`.
  - Keeps desktop sends behind the generic provider owner bridge instead of using an independent direct Claude path.
- `mac-app/src-tauri/src/commands/claude.rs`
  - Removed the default existing-session branch plan from the legacy direct command.
  - Keeps branch/fork behavior limited to explicit or recovery paths, not normal message sends.
- `bot/events.py`, `bot/handlers/workspace.py`, and `core/provider_session_bridge.py`
  - Tightened topic parsing and provider-session bridge boundaries used by the follow-up runtime fix.
  - Added regression coverage for topic/session bridge behavior.

## Behavior Now Expected

- Existing Claude sessions remain writable from Telegram and the desktop app.
- Normal sends do not silently fork or remap imported/history sessions.
- OnlineWorker refuses to inject into a Claude session that appears externally busy.
- Sends to the same Claude session are serialized through the provider runtime ownership path.
- Desktop Session Browser Claude sends use the provider owner bridge path.

## Verification

Source/runtime verification recorded for the plan:

```text
pytest -q tests/test_claude_runtime.py
pytest -q tests/test_claude_adapter.py -k 'serializes_sends_for_same_session'
pytest -q tests/test_codex_tui_mode.py -k 'claude'
pytest -q tests/test_claude_runtime.py tests/test_claude_adapter.py tests/test_codex_tui_mode.py tests/test_provider_owner_bridge.py -k 'claude or provider_owner_bridge or provider_session'
node --test mac-app/tests/sessionMetadataBadges.test.mjs
cd mac-app/src-tauri && cargo test build_claude_session_send_plan --lib
cd mac-app/src-tauri && cargo test send_provider_session_message --lib
```

Additional follow-up verification for the committed bridge/topic fix:

```text
tests/test_events.py
tests/test_provider_session_bridge.py
tests/test_workspace_thread_open.py
```

Release/version validation after Phase 4 and the Session Browser attachment fix:

```text
npm --prefix mac-app run build
cargo metadata --manifest-path mac-app/src-tauri/Cargo.toml --no-deps --format-version 1
```

Both commands passed before pushing `main` and tag `1.2.0`.

## Known Remaining Verification

- None for the planned Phase 4 ownership boundary.
- Explicit fork UX remains future work. Phase 4 only removes implicit fork/remap from normal sends and adds the safe resume guard.
