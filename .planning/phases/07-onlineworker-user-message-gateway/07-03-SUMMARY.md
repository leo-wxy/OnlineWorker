# 07-03 Summary: Codex Remote App-Server User Message Proxy

## Result

Confirmed and implemented a practical Codex CLI path for true user prompt rewriting before Codex app-server persistence and model submission.

## Protocol Probe

Observed local `codex --remote ws://127.0.0.1:<probe>` behavior:

- First client message is JSON-RPC `initialize` from `clientInfo.name="codex-tui"` and version `0.133.0`.
- Startup creates/resumes app-server state through JSON-RPC calls such as `thread/start`.
- Initial CLI prompt text is sent as `turn/start.params.input[]` with a text item:

```json
{"type":"text","text":"你妈的 只回复 PROBE_OK","text_elements":[]}
```

With the probe proxy rewrite enabled, the app-server event stream emitted the user message as:

```json
{"type":"text","text":"只回复 PROBE_OK","text_elements":[]}
```

The generated local transcript for that turn only contained `只回复 PROBE_OK` and the assistant reply `PROBE_OK`; it did not contain `你妈的`.

## Implemented

- Added `plugins/providers/builtin/codex/python/remote_proxy.py`:
  - starts a local WebSocket proxy bound to `127.0.0.1` with a dynamic port.
  - forwards traffic to the real local Codex app-server.
  - rewrites `turn/start` and `turn/steer` text input by calling `prepare_user_message_text`.
  - respects `message_hooks.enabled=false` and builtin hook `mode=off`.
  - skips text items with `text_elements` to avoid breaking Codex UI byte ranges for references.
- Updated `plugins/providers/builtin/codex/python/tui_bridge.py`:
  - OnlineWorker-managed `CodexTuiHost` now receives the proxy URL as its `--remote` target when a WebSocket app-server upstream is available.
  - proxy startup is fail-closed; if proxy creation fails, the host is not started with a direct upstream URL.
- Updated `plugins/providers/builtin/codex/python/runtime.py` and runtime state:
  - tracks the remote proxy handle in provider runtime state.
  - stops the proxy during Codex runtime shutdown.
- Added `scripts/probe_codex_remote_proxy.py`:
  - diagnostic-only probe/proxy for observing real Codex `--remote` traffic.

## Behavior Boundary

This covers Codex CLI sessions launched or owned by OnlineWorker through `CodexTuiHost` with a WebSocket app-server upstream.

Direct ad-hoc shell usage such as typing `codex` in a separate terminal still bypasses OnlineWorker unless it is launched with a wrapper or pointed at an OnlineWorker-managed remote proxy. `UserPromptSubmit` remains pass-through because verified prompt replacement support was not found for that hook.

## Verification

Passed:

```bash
PYENV_VERSION=3.13.1 pytest -q tests/test_handlers.py tests/test_user_message_hooks.py tests/test_user_message_normalizer_script.py tests/test_config.py tests/test_thread_controls.py tests/test_provider_owner_bridge.py tests/test_provider_session_bridge.py tests/test_provider_session_bridge_attachments.py tests/test_codex_hook_bridge.py tests/test_codex_remote_proxy.py tests/test_codex_remote_proxy_probe.py tests/test_codex_tui_mode.py tests/test_codex_tui_host_wrapper.py tests/test_startup_runtime.py && git diff --check
```

Observed result:

```text
276 passed
```

`git diff --check` produced no output.

## Not Run

Packaged-app build/install/relaunch verification was not run for Phase 7 after this extension.
