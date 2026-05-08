from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import sys
import tempfile
import uuid
import logging
from typing import Any, Awaitable, Callable

from plugins.providers.builtin.codex.python import runtime_state as codex_state


CODEX_HOOK_SOCKET_FILENAME = "codex_hook_bridge.sock"
CODEX_HOOK_SETTINGS_FILENAME = "hooks.json"
CODEX_BLOCKING_HOOK_TIMEOUT_SECONDS = 86400
CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"
CODEX_HOOK_SETTINGS_RECONCILE_INTERVAL_SECONDS = 3.0

EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]
logger = logging.getLogger(__name__)


def codex_hook_socket_path(data_dir: str | None) -> str | None:
    if not data_dir:
        return None
    normalized = os.path.abspath(data_dir)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    socket_dir = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    return os.path.join(socket_dir, f"ow-codex-{digest}.sock")


def codex_hook_settings_path() -> str | None:
    home = os.path.expanduser("~")
    if not home:
        return None
    return os.path.join(home, ".codex", CODEX_HOOK_SETTINGS_FILENAME)


def build_codex_hook_command(data_dir: str) -> str:
    if getattr(sys, "frozen", False):
        argv = [
            sys.executable,
            "--codex-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    else:
        main_py = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "main.py")
        )
        argv = [
            sys.executable,
            main_py,
            "--codex-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    return " ".join(shlex.quote(str(item)) for item in argv)


def _build_codex_permission_hook_entry(command: str) -> dict[str, Any]:
    return {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": CODEX_BLOCKING_HOOK_TIMEOUT_SECONDS,
            }
        ],
    }


def merge_codex_hook_settings(existing: dict[str, Any], command: str) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    hooks_section = payload.get("hooks")
    hooks = hooks_section if isinstance(hooks_section, dict) else {}
    next_hooks = dict(hooks)
    next_hooks[CODEX_PERMISSION_HOOK_NAME] = [_build_codex_permission_hook_entry(command)]
    payload["hooks"] = next_hooks
    return payload


def write_codex_hook_settings(data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    settings_path = codex_hook_settings_path()
    if settings_path is None:
        raise RuntimeError("缺少 ~/.codex 路径，无法写入 Codex hook settings")

    command = build_codex_hook_command(data_dir)
    payload: dict[str, Any] = {}
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            payload = existing if isinstance(existing, dict) else {}
        except Exception:
            payload = {}

    merged = merge_codex_hook_settings(payload, command)
    tmp_path = f"{settings_path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, settings_path)
    return settings_path


def default_codex_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    event_name = str(payload.get("hook_event_name") or "").strip()
    if event_name == CODEX_PERMISSION_HOOK_NAME:
        return {
            "hookSpecificOutput": {
                "hookEventName": CODEX_PERMISSION_HOOK_NAME,
                "decision": {
                    "behavior": "deny",
                },
            }
        }
    return {}


def _hook_session_id(payload: dict[str, Any]) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or "").strip()


def _hook_cwd(payload: dict[str, Any]) -> str:
    return str(payload.get("cwd") or "").strip()


def _normalize_hook_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or "").strip()


def _hook_event_name(payload: dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or "").strip()


def _hook_is_permission_request(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) == CODEX_PERMISSION_HOOK_NAME


def _hook_permission_display(payload: dict[str, Any]) -> tuple[str, str]:
    tool_name = _normalize_hook_tool_name(payload)
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool_name:
        command = str(tool_input.get("command") or tool_name).strip()
        reason = str(tool_input.get("description") or tool_input.get("prompt") or command).strip()
        return command or tool_name, reason or tool_name
    command = str(tool_input.get("command") or "Codex 权限请求").strip()
    reason = str(tool_input.get("description") or command).strip()
    return command, reason


async def _read_json_from_stream(reader: asyncio.StreamReader) -> dict[str, Any]:
    raw = await reader.read()
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


async def relay_codex_hook_payload(
    data_dir: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if data_dir:
        try:
            write_codex_hook_settings(data_dir)
        except Exception:
            pass

    socket_path = codex_hook_socket_path(data_dir)
    if not socket_path:
        return default_codex_hook_response(payload)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except Exception:
        return default_codex_hook_response(payload)

    try:
        writer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await writer.drain()
        writer.write_eof()
        raw = await reader.read()
    except Exception:
        return default_codex_hook_response(payload)
    finally:
        writer.close()
        await writer.wait_closed()

    if not raw:
        return {}
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def run_codex_hook_bridge_once(data_dir: str | None) -> int:
    raw = sys.stdin.buffer.read()
    if not raw:
        return 0

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        sys.stdout.write("{}")
        sys.stdout.flush()
        return 0

    if not isinstance(payload, dict):
        sys.stdout.write("{}")
        sys.stdout.flush()
        return 0

    response = asyncio.run(relay_codex_hook_payload(data_dir, payload))
    sys.stdout.write(json.dumps(response or {}, ensure_ascii=False))
    sys.stdout.flush()
    return 0


class CodexHookBridge:
    def __init__(
        self,
        state,
        *,
        data_dir: str | None,
        emit_event: EventEmitter,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.state = state
        self.data_dir = data_dir
        self.emit_event = emit_event
        self._loop = event_loop
        self.socket_path = codex_hook_socket_path(data_dir)
        self.settings_path = codex_hook_settings_path()
        self._server: asyncio.base_events.Server | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._settings_task: asyncio.Task | None = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        if self.is_running:
            return
        if not self.data_dir:
            raise RuntimeError("缺少 data_dir，无法启动 codex hook bridge")
        if not self.socket_path:
            raise RuntimeError("缺少 codex hook socket 路径")

        os.makedirs(self.data_dir, exist_ok=True)
        if self.settings_path:
            os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        write_codex_hook_settings(self.data_dir)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        self._settings_task = asyncio.create_task(
            self._reconcile_hook_settings_loop(),
            name="codex-hook-settings-reconcile",
        )
        logger.info("[codex-hook-bridge] 已启动 socket=%s", self.socket_path)

    async def stop(self) -> None:
        for request_id in list(self._pending.keys()):
            entry = self._pending.get(request_id) or {}
            future = entry.get("future")
            if future is not None and not future.done():
                future.set_result(default_codex_hook_response({"hook_event_name": CODEX_PERMISSION_HOOK_NAME}))
        self._pending.clear()
        if self._settings_task is not None and not self._settings_task.done():
            self._settings_task.cancel()
            try:
                await self._settings_task
            except asyncio.CancelledError:
                pass
        self._settings_task = None

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        if self.settings_path:
            logger.info("[codex-hook-bridge] 已停止 socket=%s settings=%s", self.socket_path, self.settings_path)

    async def _reconcile_hook_settings_loop(self) -> None:
        while True:
            await asyncio.sleep(CODEX_HOOK_SETTINGS_RECONCILE_INTERVAL_SECONDS)
            if not self.data_dir:
                continue
            try:
                write_codex_hook_settings(self.data_dir)
            except Exception as e:
                logger.warning("[codex-hook-bridge] reconcile hooks.json 失败：%s", e)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            payload = await _read_json_from_stream(reader)
            response = await self.handle_hook_payload(payload) if payload else {}
            writer.write(json.dumps(response or {}, ensure_ascii=False).encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _resolve_workspace_id(self, payload: dict[str, Any]) -> str:
        session_id = _hook_session_id(payload)
        if session_id:
            run = codex_state.get_current_run(self.state, session_id)
            if run is not None and getattr(run, "workspace_id", ""):
                return run.workspace_id

        cwd = _hook_cwd(payload)
        if cwd:
            storage = getattr(self.state, "storage", None)
            workspaces = getattr(storage, "workspaces", {}) if storage is not None else {}
            for ws_name, ws in workspaces.items():
                if getattr(ws, "tool", "") != "codex":
                    continue
                if getattr(ws, "path", "") == cwd:
                    return getattr(ws, "daemon_workspace_id", "") or ws_name
        return ""

    async def handle_hook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not _hook_is_permission_request(payload):
            return {}
        if self.data_dir:
            try:
                write_codex_hook_settings(self.data_dir)
            except Exception as e:
                logger.warning("[codex-hook-bridge] hook payload 前 reconcile hooks.json 失败：%s", e)

        request_id = str(payload.get("request_id") or payload.get("id") or uuid.uuid4())
        workspace_id = self._resolve_workspace_id(payload)
        thread_id = _hook_session_id(payload)
        command, reason = _hook_permission_display(payload)

        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = {
            "future": future,
            "payload": payload,
        }

        approval_payload = {
            "threadId": thread_id,
            "command": command,
            "reason": reason,
            "request_id": request_id,
            "_provider": "codex",
            "_codex_hook_bridge": True,
            "toolName": _normalize_hook_tool_name(payload),
        }

        try:
            await self.emit_event(workspace_id, "item/commandExecution/requestApproval", approval_payload)
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def reply_server_request(self, request_id: Any, result: Any) -> dict[str, Any]:
        request_key = str(request_id or "").strip()
        entry = self._pending.get(request_key)
        if entry is None:
            raise RuntimeError(f"Codex hook 请求不存在：{request_key}")

        result_dict = result if isinstance(result, dict) else {}
        response = self._build_permission_hook_response(result_dict, entry.get("payload") or {})
        future = entry.get("future")
        if not future.done():
            future.set_result(response)
        return response

    def _build_permission_hook_response(
        self,
        result: dict[str, Any],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        behavior = str(result.get("behavior") or "").strip().lower() or "deny"
        if behavior != "allow":
            return default_codex_hook_response({"hook_event_name": CODEX_PERMISSION_HOOK_NAME})

        decision: dict[str, Any] = {"behavior": "allow"}
        if str(result.get("scope") or "").strip().lower() == "session":
            tool_name = str(
                result.get("tool_name")
                or payload.get("tool_name")
                or ""
            ).strip()
            if tool_name:
                decision["updatedPermissions"] = [
                    {
                        "type": "addRules",
                        "rules": [{"toolName": tool_name, "ruleContent": "*"}],
                        "behavior": "allow",
                        "destination": "session",
                    }
                ]
        return {
            "hookSpecificOutput": {
                "hookEventName": CODEX_PERMISSION_HOOK_NAME,
                "decision": decision,
            }
        }


async def ensure_codex_hook_bridge_started(
    state,
    *,
    data_dir: str | None,
    event_handler,
) -> CodexHookBridge | None:
    bridge = codex_state.get_hook_bridge(state)
    if bridge is not None and bridge.is_running:
        return bridge

    async def emit_event(workspace_id: str, method: str, params: dict[str, Any]) -> None:
        await event_handler(
            "app-server-event",
            {
                "workspace_id": workspace_id,
                "message": {
                    "method": method,
                    "params": params,
                },
            },
        )

    bridge = CodexHookBridge(state, data_dir=data_dir, emit_event=emit_event)
    if not bridge.socket_path:
        logger.info("[codex-hook-bridge] 缺少 data_dir，跳过 hook bridge 启动")
        return None
    await bridge.start()
    codex_state.set_hook_bridge(state, bridge)
    return bridge


async def stop_codex_hook_bridge(state) -> None:
    bridge = codex_state.get_hook_bridge(state)
    if bridge is None:
        return
    await bridge.stop()
    codex_state.set_hook_bridge(state, None)
