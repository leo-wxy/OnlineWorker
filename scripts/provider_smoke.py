#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROVIDERS = ("codex", "claude")
MESSAGE_MARKER = "ONLINEWORKER_SMOKE_MESSAGE_OK"
PERMISSION_MARKER = "ONLINEWORKER_SMOKE_PERMISSION_OK"
CODEX_PERMISSION_APPROVAL_POLICY = "untrusted"
CODEX_PERMISSION_SANDBOX_POLICY = {"type": "readOnly"}
APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "execCommandApproval",
    "applyPatchApproval",
}


def extract_thread_id(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    thread_id = result.get("id")
    if not thread_id:
        thread = result.get("thread")
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    return str(thread_id or "")


def default_fixed_session_id(provider: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"onlineworker-smoke:{provider}"))


def build_permission_reply(provider: str, thread_id: str, method: str = "item/commandExecution/requestApproval") -> dict[str, Any]:
    if provider == "codex":
        if method in {"execCommandApproval", "applyPatchApproval"}:
            return {"decision": "approved"}
        return {"decision": "accept"}
    if provider == "claude":
        return {"behavior": "allow"}
    raise ValueError(f"unknown provider: {provider}")


def build_message_prompt(provider: str, marker: str = MESSAGE_MARKER) -> str:
    return (
        f"This is an OnlineWorker fixed-session smoke test for provider {provider}. "
        f"Reply with exactly this text and no extra words: {marker}"
    )


def build_permission_prompt(provider: str, target: Path, content: str) -> str:
    script = (
        "from pathlib import Path; "
        f"Path({str(target)!r}).write_text({content!r}, encoding='utf-8')"
    )
    return (
        f"This is an OnlineWorker fixed-session permission smoke test for provider {provider}. "
        "Use the Bash/shell tool exactly once to run the following command, "
        f"then reply with exactly {PERMISSION_MARKER} and no extra words:\n"
        f"python3 -c {json.dumps(script)}"
    )


def build_combined_prompt(provider: str, target: Path, content: str) -> str:
    return (
        f"This is an OnlineWorker fixed-session combined smoke test for provider {provider}. "
        "Use the Bash/shell tool exactly once to run the following command, "
        f"then reply with exactly {MESSAGE_MARKER} {PERMISSION_MARKER} and no extra words:\n"
        f"printf '%s' {json.dumps(content)} > {json.dumps(str(target))}"
    )


def _default_env_file() -> Path:
    return REPO_ROOT / ".env"


def _load_env_file(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class SmokeSessionStore:
    def __init__(self, path: Path):
        self.path = path
        self._payload = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"providers": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"providers": {}}
        if not isinstance(payload, dict):
            return {"providers": {}}
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            payload["providers"] = {}
        return payload

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get_thread_id(self, provider: str) -> str:
        provider_payload = self._payload.get("providers", {}).get(provider)
        if not isinstance(provider_payload, dict):
            return ""
        return str(provider_payload.get("thread_id") or "")

    def set_thread_id(self, provider: str, thread_id: str) -> None:
        self._payload.setdefault("providers", {})[provider] = {
            "thread_id": thread_id,
            "updated_at": int(time.time()),
        }
        self._save()

    def clear_provider(self, provider: str) -> None:
        providers = self._payload.setdefault("providers", {})
        providers.pop(provider, None)
        self._save()


class SmokeRecorder:
    def __init__(self, provider: str, adapter: Any, workspace_id: str):
        self.provider = provider
        self.adapter = adapter
        self.workspace_id = workspace_id
        self.permissions: list[dict[str, Any]] = []
        self.final_texts: list[str] = []
        self.completed_turns: list[dict[str, Any]] = []
        self.errors: list[str] = []
        self._final_event = asyncio.Event()
        self._permission_event = asyncio.Event()
        self._completed_event = asyncio.Event()

    async def on_server_request(self, method: str, params: dict[str, Any], request_id: Any) -> None:
        if method not in APPROVAL_METHODS:
            return
        await self._handle_permission(method, params, request_id)

    async def on_event(self, method: str, params: dict[str, Any]) -> None:
        if method != "app-server-event":
            return
        message = params.get("message") or {}
        event_method = str(message.get("method") or "")
        event_params = message.get("params") or {}
        if event_method in APPROVAL_METHODS:
            await self._handle_permission(event_method, event_params, message.get("id") or event_params.get("request_id"))
            return
        if event_method == "item/completed":
            item = event_params.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = str(item.get("text") or "").strip()
                if text:
                    self.final_texts.append(text)
                    self._final_event.set()
            return
        if event_method == "turn/completed":
            self.completed_turns.append(event_params)
            self._completed_event.set()

    async def _handle_permission(self, method: str, params: dict[str, Any], request_id: Any) -> None:
        thread_id = str(
            params.get("threadId")
            or params.get("thread_id")
            or params.get("conversationId")
            or ""
        )
        self.permissions.append({"method": method, "request_id": request_id, "thread_id": thread_id, "params": params})
        _sync_thread_workspace_map(self.adapter, thread_id, self.workspace_id)
        self._permission_event.set()
        try:
            await self.adapter.reply_server_request(
                self.workspace_id,
                request_id,
                build_permission_reply(self.provider, thread_id, method),
            )
        except Exception as exc:
            self.errors.append(f"permission reply failed: {exc}")
            raise

    async def wait_for_final_text(self, marker: str, timeout: float) -> str:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            for text in self.final_texts:
                if marker in text:
                    return text
            remaining = max(0.1, deadline - asyncio.get_event_loop().time())
            try:
                await asyncio.wait_for(self._final_event.wait(), timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
                pass
            self._final_event.clear()
        raise TimeoutError(f"{self.provider} 未在 {timeout:.0f}s 内收到包含 {marker} 的最终回复")

    async def wait_for_permission(self, timeout: float) -> dict[str, Any]:
        if not self.permissions:
            await asyncio.wait_for(self._permission_event.wait(), timeout=timeout)
        return self.permissions[0]


def _workspace_id(provider: str) -> str:
    return f"{provider}:onlineworker-smoke"


def _is_local_codex_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"ws", "wss"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _parse_codex_port(url: str, default: int = 4722) -> int:
    parsed = urlparse(url)
    return parsed.port or default


def _permission_send_kwargs(provider: str) -> dict[str, Any]:
    if provider == "codex":
        return {
            "approval_policy": CODEX_PERMISSION_APPROVAL_POLICY,
            "approvals_reviewer": "user",
            "sandbox_policy": CODEX_PERMISSION_SANDBOX_POLICY,
        }
    return {}


def _sync_thread_workspace_map(adapter: Any, thread_id: str, workspace_id: str) -> None:
    thread_workspace_map = getattr(adapter, "_thread_workspace_map", None)
    if isinstance(thread_workspace_map, dict) and thread_id and workspace_id:
        thread_workspace_map[thread_id] = workspace_id


async def _connect_adapter(provider: str, args: argparse.Namespace):
    if provider == "codex":
        from plugins.providers.builtin.codex.python.adapter import CodexAdapter
        from plugins.providers.builtin.codex.python.process import AppServerProcess

        adapter = CodexAdapter()
        try:
            await adapter.connect(args.codex_url)
            return adapter, None
        except (ConnectionRefusedError, OSError):
            if not _is_local_codex_url(args.codex_url):
                raise

        app_server = AppServerProcess(
            codex_bin=args.codex_bin,
            port=_parse_codex_port(args.codex_url),
            protocol="ws",
        )
        try:
            ws_url = await app_server.start()
            await adapter.connect(ws_url)
        except Exception:
            with suppress(Exception):
                await app_server.stop()
            raise
        return adapter, app_server

    if provider == "claude":
        from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter, resolve_claude_bin

        adapter = ClaudeAdapter(claude_bin=resolve_claude_bin(args.claude_bin))
        await adapter.connect()
        await adapter.start_hook_bridge(str(args.smoke_dir / "claude-hook"))
        return adapter, None

    raise ValueError(f"unknown provider: {provider}")


async def _archive_provider(provider: str, args: argparse.Namespace, thread_id: str) -> dict[str, Any]:
    if not thread_id:
        return {"provider": provider, "archived": False, "reason": "missing_thread_id"}

    adapter, codex_process = await _connect_adapter(provider, args)
    workspace_id = _workspace_id(provider)
    adapter.register_workspace_cwd(workspace_id, str(Path(args.workspace).resolve()))
    thread_workspace_map = getattr(adapter, "_thread_workspace_map", None)
    if isinstance(thread_workspace_map, dict):
        thread_workspace_map[thread_id] = workspace_id

    try:
        archived = await adapter.archive_thread(workspace_id, thread_id)
        return {
            "provider": provider,
            "archived": True,
            "thread_id": thread_id,
            "result": archived,
        }
    finally:
        try:
            await adapter.disconnect()
        except Exception:
            pass
        if codex_process is not None:
            with suppress(Exception):
                await codex_process.stop()


async def _ensure_thread_id(
    provider: str,
    adapter: Any,
    workspace_id: str,
    store: SmokeSessionStore,
    *,
    reset_session: bool,
) -> str:
    if reset_session:
        store.clear_provider(provider)

    stored = store.get_thread_id(provider)
    if provider == "claude":
        thread_id = stored or default_fixed_session_id(provider)
        store.set_thread_id(provider, thread_id)
        await adapter.resume_thread(workspace_id, thread_id)
        return thread_id

    if stored:
        try:
            await adapter.resume_thread(workspace_id, stored)
            return stored
        except Exception:
            store.clear_provider(provider)

    started = await adapter.start_thread(workspace_id)
    thread_id = extract_thread_id(started)
    if not thread_id:
        raise RuntimeError(f"{provider} start_thread 返回无 thread id: {started}")
    store.set_thread_id(provider, thread_id)
    return thread_id


async def _run_provider(provider: str, args: argparse.Namespace, store: SmokeSessionStore) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    workspace_id = _workspace_id(provider)
    adapter, codex_process = await _connect_adapter(provider, args)
    recorder = SmokeRecorder(provider, adapter, workspace_id)
    adapter.register_workspace_cwd(workspace_id, str(workspace))
    adapter.on_event(recorder.on_event)
    adapter.on_server_request(recorder.on_server_request)

    try:
        thread_id = await _ensure_thread_id(
            provider,
            adapter,
            workspace_id,
            store,
            reset_session=bool(args.reset_session),
        )
        _sync_thread_workspace_map(adapter, thread_id, workspace_id)
        result: dict[str, Any] = {
            "provider": provider,
            "workspace": str(workspace),
            "workspace_id": workspace_id,
            "thread_id": thread_id,
            "message": None,
            "permission": None,
        }

        if args.mode in {"message", "both"}:
            started_at = time.monotonic()
            send_result = await adapter.send_user_message(
                workspace_id,
                thread_id,
                build_message_prompt(provider),
            )
            final_text = str(send_result.get("text") or "")
            if MESSAGE_MARKER not in final_text:
                final_text = await recorder.wait_for_final_text(MESSAGE_MARKER, args.timeout)
            result["message"] = {
                "ok": MESSAGE_MARKER in final_text,
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "final_text": final_text,
            }

        if args.mode == "both":
            args.permission_dir.mkdir(parents=True, exist_ok=True)
            target = args.permission_dir / f"{provider}-permission.txt"
            content = f"onlineworker smoke permission {provider}"
            target.unlink(missing_ok=True)

            started_at = time.monotonic()
            send_result = await adapter.send_user_message(
                workspace_id,
                thread_id,
                build_permission_prompt(provider, target, content),
                **_permission_send_kwargs(provider),
            )
            final_text = str(send_result.get("text") or "")
            if recorder.permissions:
                permission = recorder.permissions[0]
            else:
                permission = await recorder.wait_for_permission(args.timeout)

            deadline = time.monotonic() + args.timeout
            while not target.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
            if not target.exists():
                raise TimeoutError(f"{provider} 权限测试文件未生成：{target}")
            actual_content = target.read_text(encoding="utf-8", errors="ignore")
            if actual_content != content:
                raise RuntimeError(
                    f"{provider} 权限测试文件内容不匹配: expected={content!r} actual={actual_content!r}"
                )
            if PERMISSION_MARKER not in final_text:
                final_text = await recorder.wait_for_final_text(PERMISSION_MARKER, args.timeout)
            if not args.keep_artifacts:
                target.unlink(missing_ok=True)
            elapsed = round(time.monotonic() - started_at, 3)
            result["message"] = {
                "ok": MESSAGE_MARKER in result["message"]["final_text"] if result["message"] else False,
                "elapsed_seconds": elapsed,
                "final_text": result["message"]["final_text"] if result["message"] else "",
            }
            result["permission"] = {
                "ok": PERMISSION_MARKER in final_text,
                "elapsed_seconds": elapsed,
                "request_id": permission.get("request_id"),
                "target": str(target),
                "final_text": final_text,
            }

        if args.mode == "permission":
            args.permission_dir.mkdir(parents=True, exist_ok=True)
            target = args.permission_dir / f"{provider}-permission.txt"
            content = f"onlineworker smoke permission {provider}"
            target.unlink(missing_ok=True)

            started_at = time.monotonic()
            send_result = await adapter.send_user_message(
                workspace_id,
                thread_id,
                build_permission_prompt(provider, target, content),
                **_permission_send_kwargs(provider),
            )
            final_text = str(send_result.get("text") or "")
            if recorder.permissions:
                permission = recorder.permissions[0]
            else:
                permission = await recorder.wait_for_permission(args.timeout)

            deadline = time.monotonic() + args.timeout
            while not target.exists() and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
            if not target.exists():
                raise TimeoutError(f"{provider} 权限测试文件未生成：{target}")
            actual_content = target.read_text(encoding="utf-8", errors="ignore")
            if actual_content != content:
                raise RuntimeError(
                    f"{provider} 权限测试文件内容不匹配: expected={content!r} actual={actual_content!r}"
                )
            if not args.keep_artifacts:
                target.unlink(missing_ok=True)
            result["permission"] = {
                "ok": True,
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "request_id": permission.get("request_id"),
                "target": str(target),
                "final_text": final_text,
            }

        return result
    finally:
        try:
            await adapter.disconnect()
        except Exception:
            pass
        if codex_process is not None:
            with suppress(Exception):
                await codex_process.stop()


async def _main_async(args: argparse.Namespace) -> int:
    _load_env_file(args.env_file)
    args.smoke_dir.mkdir(parents=True, exist_ok=True)
    store = SmokeSessionStore(args.state_file)
    providers = PROVIDERS if args.provider == "all" else (args.provider,)
    results = []

    if args.action == "archive":
        for provider in providers:
            thread_id = store.get_thread_id(provider)
            try:
                result = await _archive_provider(provider, args, thread_id)
                results.append(result)
                store.clear_provider(provider)
            except Exception as exc:
                results.append(
                    {
                        "provider": provider,
                        "ok": False,
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    }
                )
                if not args.keep_going:
                    break
        ok = all(item.get("archived", False) or item.get("reason") == "missing_thread_id" for item in results)
        print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2), flush=True)
        return 0 if ok else 1

    for provider in providers:
        try:
            result = await _run_provider(provider, args, store)
            results.append(result)
        except Exception as exc:
            results.append(
                {
                    "provider": provider,
                    "ok": False,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            )
            if not args.keep_going:
                break

    ok = all(item.get("error") is None and item.get("ok", True) is not False for item in results)
    print(json.dumps({"ok": ok, "results": results}, ensure_ascii=False, indent=2), flush=True)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run fixed-session provider smoke tests from the repository root.",
    )
    parser.add_argument("--action", choices=["smoke", "archive"], default="smoke")
    parser.add_argument("--provider", choices=[*PROVIDERS, "all"], default="all")
    parser.add_argument("--mode", choices=["message", "permission", "both"], default="both")
    parser.add_argument("--workspace", default=str(REPO_ROOT), help="Workspace cwd used by all providers")
    parser.add_argument("--codex-url", default="ws://127.0.0.1:4722")
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--reset-session", action="store_true", help="Drop stored smoke thread ids and create/resume fresh fixed sessions")
    parser.add_argument("--keep-going", action="store_true", help="Run remaining providers after a provider fails")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep generated permission files")
    parser.add_argument(
        "--smoke-dir",
        type=Path,
        default=REPO_ROOT / ".onlineworker-smoke",
        help="Local smoke state/log directory",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=REPO_ROOT / ".onlineworker-smoke" / "session-state.json",
        help="Fixed provider session state file",
    )
    parser.add_argument(
        "--permission-dir",
        type=Path,
        default=REPO_ROOT / ".onlineworker-smoke" / "artifacts",
        help="Fixed temporary directory used by permission write tests",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=_default_env_file(),
        help="Optional .env loaded before running provider CLIs",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
