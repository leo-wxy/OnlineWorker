# Phase 4: Claude Session Ownership and Safe Resume

This phase corrects the Claude session ownership model after Phase 3 exposed TG/App/terminal contention.

Goal:
- Existing Claude sessions remain writable from TG and the desktop app.
- Normal sends do not silently fork or remap imported/history sessions.
- OnlineWorker does not inject into an externally busy terminal Claude task.
- TG/App sends to the same Claude session are serialized through provider runtime ownership.

Plan:
- `04-01`: Align Claude existing-session resume ownership across TG, provider owner bridge, and Session Browser.

Outcome:
- Claude provider preparation now resumes imported/history sessions in place and rejects externally busy sessions before sending.
- Claude adapter sends are serialized per session id, so TG/App cannot launch concurrent `claude --resume` processes for one session.
- Desktop Claude Session Browser sends now use the generic provider owner bridge path instead of the direct Claude command path.
- The old direct Tauri Claude command no longer auto-branches existing sessions on normal sends; only the prompt-too-long recovery fallback creates a new session.

Verification:
- `pytest -q tests/test_claude_runtime.py`
- `pytest -q tests/test_claude_adapter.py -k 'serializes_sends_for_same_session'`
- `pytest -q tests/test_codex_tui_mode.py -k 'claude'`
- `pytest -q tests/test_claude_runtime.py tests/test_claude_adapter.py tests/test_codex_tui_mode.py tests/test_provider_owner_bridge.py -k 'claude or provider_owner_bridge or provider_session'`
- `node --test mac-app/tests/sessionMetadataBadges.test.mjs`
- `cd mac-app/src-tauri && cargo test build_claude_session_send_plan --lib`
- `cd mac-app/src-tauri && cargo test send_provider_session_message --lib`

Reference:
- Lucarne uses resumable history sessions, topic-bound live sessions, per-workspace turn queueing, and explicit fork commands. Phase 4 adopts that ownership boundary without importing Lucarne's full architecture.
