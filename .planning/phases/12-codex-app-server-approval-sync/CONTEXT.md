# Phase 12 Context: Codex Managed App-Server Approval Host

## User Intent

The user wants to stop pursuing Codex Remote Connection for this problem and focus on Codex app-server approval instead.

In follow-up discussion, the user clarified a second requirement for the local shared app-server test case: when OnlineWorker/TG and a visible Codex CLI both attach to the same local app-server, prefer Codex's `unix://` transport over `ws://127.0.0.1:<port>` because it avoids port conflicts and better matches local-only sharing.

After the 2026-06-02 debugging round, the concrete visible CLI entry point is the fixed OnlineWorker proxy socket:

```bash
alias codexR='/opt/homebrew/bin/codex --remote "unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock" --cd "$(pwd)"'
```

Bare `--remote unix://` is not the OnlineWorker validation path. It connects directly to Codex's default app-server control socket and bypasses OnlineWorker's remote proxy, so it cannot validate Telegram approval mirroring/control.

The updated framing is reference-driven. The useful models are:

- `getpaseo/paseo`: Paseo owns the Codex app-server client connection, registers approval request handlers, stores pending permissions, and replies through the same app-server request id.
- `slopus/happy`: `happy codex` wraps Codex by starting `codex app-server --listen stdio://`, routing approval requests to its own app/mobile UI, and responding to app-server.
- Codex IDE extension: official host/client analogy. The extension uses Codex CLI and shared `~/.codex/config.toml`; it is useful as evidence that a host renders approval UI from Codex data, not as proof that third parties can attach to an already running Desktop/IDE session.

The core requirement is to make OnlineWorker capable of being a Codex host/client for OnlineWorker-managed sessions:

- OnlineWorker-managed Codex sessions own the app-server request/response channel.
- Telegram is the remote approval UI for those managed sessions.
- Telegram can receive the same approval request and participate in the decision only when OnlineWorker owns the app-server request id.
- Existing Codex Desktop, VS Code, and ordinary CLI sessions keep native approval behavior. OnlineWorker mirrors those sessions only, unless a future controlled proxy path explicitly makes OnlineWorker the host.

The target is not to make OnlineWorker a general authorization engine. The target is to let Codex app-server own the Codex approval lifecycle, while OnlineWorker acts as the host/client for managed sessions and relays Telegram decisions back to the same app-server request.

## Decision

Codex app-server approval lifecycle is the source of truth for this phase.

OnlineWorker can be the visible host/control surface for OnlineWorker-managed Codex sessions, analogous to Paseo, Happy, or the Codex IDE extension. Telegram is OnlineWorker's remote approval UI for those sessions.

Existing Codex Desktop, VS Code, and ordinary CLI clients remain their own hosts. OnlineWorker must not intercept or replace their native approval UI.

Remote Connection is out of scope for this phase because it is a Codex App host / ChatGPT workspace remote-control product path, not the generic multi-IM approval backend OnlineWorker needs.

For local shared app-server transport, Phase 12 now prefers `unix://` over `ws://127.0.0.1:<port>` as the target design. 12-02 implemented OnlineWorker Unix transport support:

- local Codex CLI help shows `codex app-server --listen` supports `stdio://`, `unix://`, `unix://PATH`, `ws://IP:PORT`, and `off`;
- OnlineWorker config normalization accepts `unix` and `shared_unix`, including inference from `unix://` app-server URLs;
- OnlineWorker app-server process startup can emit `--listen unix://` and connect after socket-readiness polling;
- OnlineWorker adapter connects through WebSocket-over-Unix with `compression=None`;
- OnlineWorker exposes `codex_remote_proxy.sock` for visible CLI clients, with cwd-scoped `thread/list` rewriting for `/resume` filtering and approval mirror behavior that keeps the CLI native approval prompt visible.

`ws://127.0.0.1:<port>` remains the fallback shared transport. `stdio://` remains valid for OnlineWorker-owned headless app-server approval, but it is not shareable by an external CLI process.

## Scope Fence

For 12-01, implementation changes must stay under:

```text
plugins/providers/builtin/codex/
```

12-02 explicitly revises the scope for unix-socket transport plumbing because config parsing lives outside the Codex plugin:

```text
config.py
plugins/providers/builtin/codex/
tests/
```

Out of scope unless the phase is explicitly revised:

- `core/` shared approval abstractions
- `bot/` shared handlers outside Codex-owned callback wiring
- non-Codex providers
- Mac app UI
- notification plugins
- packaging/build scripts
- Remote Connection readiness or setup flows

## Desired Managed Flow

```text
OnlineWorker starts or owns Codex app-server
  -> OnlineWorker sends thread/start or turn/start
  -> Codex app-server sends approval server request to OnlineWorker
  -> OnlineWorker maps request id/thread/topic and renders Telegram approval UI
  -> Telegram user chooses allow/deny
  -> OnlineWorker replies to the same app-server JSON-RPC request id
  -> app-server emits serverRequest/resolved and item completion
  -> Telegram pending state converges to resolved/stale
```

OnlineWorker owns:

- thread/topic/session mapping lookup
- Telegram prompt rendering and callback relay
- duplicate/stale request suppression
- stale-state cleanup when Codex resolves before Telegram

Codex app-server owns:

- approval request creation
- available decisions
- command/file/tool item lifecycle
- final resolved/completed status

## Desired Shared Unix Flow

```text
OnlineWorker starts or connects to one Codex app-server over unix://PATH
  -> OnlineWorker exposes a fixed unix proxy socket
  -> visible Codex CLI attaches with codex --remote unix:///Users/wxy/Library/Application Support/OnlineWorker/codex_remote_proxy.sock --cd <cwd>
  -> Codex app-server emits one approval request id
  -> Telegram and the visible CLI both render that same approval state
  -> Telegram allow/deny replies to the same app-server request id
  -> Codex app-server resolves and both surfaces converge
```

This flow is the preferred replacement for the previous `ws://127.0.0.1:4722` shared local test because it avoids a fixed TCP port and keeps the shared control socket in the local filesystem permission model.

## Current Risk To Control

Current Codex approval behavior has several possible sources:

- app-server server requests
- hook mirror approvals
- TUI host approvals
- provider runtime pending approval decisions
- topic/global fallback routing

Phase 12 should preserve working Codex-native behavior while preventing Telegram mirrors, hook mirrors, or topic fallbacks from creating conflicting authorization state.

## Guardrails

- OnlineWorker may show clickable Telegram approval controls only when it owns the app-server request/response channel.
- Codex Desktop, VS Code, and ordinary CLI native authorization prompts must remain visible and usable in their own sessions.
- Visible CLI validation through `codexR` must preserve the Codex CLI native approval prompt; OnlineWorker/TG is a mirrored control surface, not a replacement prompt.
- Do not reintroduce ordinary CLI + blocking hook as the main validation path; that path can suppress or compete with Codex CLI native approval prompts and was rejected for this phase.
- Do not use bare `codex --remote unix://` to validate OnlineWorker approval behavior; use the fixed OnlineWorker proxy socket.
- Hook mirror and current-session log mirror paths are notification-only by default.
- Telegram must not become the primary authorization controller for sessions owned by another Codex client.
- Missing thread/topic mapping must not produce Telegram approval controls in a provider global topic.
- Duplicate or stale app-server approval requests must not produce multiple active buttons for the same request.
- Telegram user decisions must be relayed back to app-server; OnlineWorker must not pretend to complete Codex items locally.
- If app-server resolves first, Telegram pending controls must be cleared, disabled, or marked stale.
- Do not claim full fixed-session visible CLI + TG authorization convergence until a resumed fixed session has triggered and resolved a real approval through the installed proxy.
- Restarting OnlineWorker closes the proxy socket and disconnects current `codexR` CLI processes. This is expected; users should reopen with `codexR resume <session_id>` and keep the same session id.
