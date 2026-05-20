# Phase 03-01 Summary

**Completed:** 2026-05-20

## Outcome

- Shared attachment contract and provider capability flags are now aligned with runtime behavior for builtin providers.
- Telegram image/document handling and provider session routing are in place for the Phase 3 shared attachment path.
- Claude attachment support is now explicitly **path-access based** instead of placeholder-only:
  - provider manifests/descriptors declare `photos/files` support
  - Python `ClaudeAdapter` accepts `attachments`
  - mac-app Claude send path adds `--add-dir` for attachment parent directories
  - both Claude send paths include a structured attachment block so Claude can inspect the referenced local paths directly
- Claude auth selection is now **configuration-owned** at the provider boundary:
  - reachable `ANTHROPIC_BASE_URL` still wins as proxy mode
  - unreachable explicit `ANTHROPIC_BASE_URL` now fails fast with a clear configuration error instead of silently switching auth routes
  - proxy mode preserves `ANTHROPIC_AUTH_TOKEN` for Raven / Langbase-style gateways instead of injecting a dummy API key when a token is already present
  - `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and official `claude auth login` are only selected freely when no `ANTHROPIC_BASE_URL` is configured

## Verification

- `pytest -q tests/test_handlers.py tests/test_thread_controls.py tests/test_config.py tests/test_claude_adapter.py`
- `cargo test build_claude_send_argv_switches_between_resume_and_session_id`
- `cargo test claude_attachment`
- `claude -p 'Reply with exactly OK.'` with `ANTHROPIC_BASE_URL=https://langbase.netease.com/langbase`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_MODEL=claude-opus-4-6` returned `OK`

## Remaining Work

- Phase `03-02` still needs packaged-app rebuild/reinstall verification after the Claude attachment refinement.
