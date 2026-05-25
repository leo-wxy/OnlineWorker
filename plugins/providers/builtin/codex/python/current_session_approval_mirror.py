from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import socket
from collections.abc import Awaitable, Callable
from typing import Optional

from config import get_data_dir
from core.provider_owner_bridge import provider_owner_bridge_socket_path
from plugins.providers.builtin.codex.python.tui_host_protocol import read_host_status


logger = logging.getLogger(__name__)

DEFAULT_CODEX_TUI_LOG_PATH = os.path.expanduser("~/.codex/log/codex-tui.log")
_TOOL_CALL_MARKER = "ToolCall: exec_command "
_THREAD_ID_PATTERN = re.compile(r"thread_id=([A-Za-z0-9_-]+(?:-[A-Za-z0-9_-]+)*)")
_ESCALATED_PERMISSIONS = {"require_escalated", "with_additional_permissions"}

MirrorSender = Callable[[Optional[str], dict], Awaitable[bool]]


def _extract_thread_id(line: str) -> str:
    matches = _THREAD_ID_PATTERN.findall(line)
    return matches[-1].strip() if matches else ""


def _extract_tool_call_params(line: str) -> Optional[dict]:
    marker_index = line.find(_TOOL_CALL_MARKER)
    if marker_index < 0:
        return None

    payload_start = marker_index + len(_TOOL_CALL_MARKER)
    try:
        payload, _end = json.JSONDecoder().raw_decode(line[payload_start:])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _stable_request_id(line: str) -> str:
    digest = hashlib.sha1(line.encode("utf-8")).hexdigest()[:20]
    return f"codex-current-session:{digest}"


def _is_owned_tui_host_thread(thread_id: str, data_dir: Optional[str]) -> bool:
    if not thread_id:
        return False
    try:
        status = read_host_status(data_dir)
    except Exception:
        return False
    if not isinstance(status, dict) or not status.get("online"):
        return False
    return str(status.get("active_thread_id") or "").strip() == thread_id


def build_current_session_approval_request(line: str, *, data_dir: Optional[str] = None) -> Optional[dict]:
    params = _extract_tool_call_params(line)
    if not params:
        return None

    sandbox_permissions = str(params.get("sandbox_permissions") or "").strip()
    if sandbox_permissions not in _ESCALATED_PERMISSIONS:
        return None

    thread_id = _extract_thread_id(line)
    owned_tui_host = _is_owned_tui_host_thread(thread_id, data_dir)
    command = str(params.get("cmd") or params.get("command") or "").strip()
    workspace_dir = str(params.get("workdir") or params.get("cwd") or "").strip()
    reason = str(params.get("justification") or params.get("reason") or "").strip()
    if not reason:
        reason = "当前 Codex 会话正在请求本地权限审批。"

    payload = {
        "hook_event_name": "ExecApprovalRequest",
        "request_id": _stable_request_id(line),
        "threadId": thread_id,
        "cwd": workspace_dir,
        "tool_name": "exec_command",
        "command": command,
        "reason": reason,
        "sandbox_permissions": sandbox_permissions,
    }
    if params.get("prefix_rule") is not None:
        payload["prefix_rule"] = params.get("prefix_rule")

    return {
        "type": "mirror_approval",
        "provider_id": "codex",
        "thread_id": thread_id,
        "workspace_dir": workspace_dir,
        "owned_tui_host": owned_tui_host,
        "payload": payload,
        "source": "codex_current_session_log",
        "notice_suffix": (
            "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"
            if owned_tui_host
            else "此请求已在当前 Codex 会话中弹出，请在 Codex CLI/Desktop 中完成审批。"
        ),
    }


async def send_current_session_approval_to_owner_bridge(
    data_dir: Optional[str],
    request: dict,
) -> bool:
    socket_path = provider_owner_bridge_socket_path(data_dir)
    if not socket_path:
        return False

    def _send() -> bool:
        try:
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(0.75)
                client.connect(socket_path)
                client.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
                raw = client.recv(4096)
        except OSError:
            return False
        try:
            response = json.loads(raw.decode("utf-8").strip() or "{}")
        except Exception:
            return False
        return bool(isinstance(response, dict) and response.get("ok"))

    return await asyncio.to_thread(_send)


async def sync_current_session_approval_mirror_once(
    *,
    data_dir: Optional[str],
    log_path: str = DEFAULT_CODEX_TUI_LOG_PATH,
    offset: int = 0,
    seen_request_ids: set[str],
    sender: MirrorSender = send_current_session_approval_to_owner_bridge,
) -> int:
    if not os.path.exists(log_path):
        return 0

    size = os.path.getsize(log_path)
    if offset > size:
        offset = 0

    with open(log_path, "r", encoding="utf-8", errors="ignore") as handle:
        handle.seek(offset)
        for line in handle:
            request = build_current_session_approval_request(line, data_dir=data_dir)
            if request is None:
                continue

            request_id = str(request.get("payload", {}).get("request_id") or "").strip()
            if not request_id or request_id in seen_request_ids:
                continue
            seen_request_ids.add(request_id)

            try:
                sent = await sender(data_dir, request)
            except Exception:
                sent = False
                logger.debug("[codex-current-session-approval] 发送 mirror request 异常", exc_info=True)
            if sent:
                logger.info(
                    "[codex-current-session-approval] 已镜像当前会话审批 thread=%s command=%s",
                    str(request.get("thread_id") or "")[:12] or "?",
                    str(request.get("payload", {}).get("command") or "")[:80],
                )
        return handle.tell()


def _initial_log_offset(log_path: str) -> int:
    try:
        return os.path.getsize(log_path)
    except OSError:
        return 0


def start_current_session_approval_mirror_loop(
    state,
    *,
    log_path: str = DEFAULT_CODEX_TUI_LOG_PATH,
    poll_interval_seconds: float = 0.5,
) -> asyncio.Task:
    data_dir = getattr(getattr(state, "config", None), "data_dir", None) or get_data_dir()
    seen_request_ids: set[str] = set()
    offset = _initial_log_offset(log_path)

    async def _runner() -> None:
        nonlocal offset
        logger.info(
            "[codex-current-session-approval] 当前会话审批镜像已启动 log=%s offset=%s",
            log_path,
            offset,
        )
        while True:
            offset = await sync_current_session_approval_mirror_once(
                data_dir=data_dir,
                log_path=log_path,
                offset=offset,
                seen_request_ids=seen_request_ids,
            )
            if len(seen_request_ids) > 1000:
                for request_id in list(seen_request_ids)[:500]:
                    seen_request_ids.discard(request_id)
            await asyncio.sleep(poll_interval_seconds)

    return asyncio.create_task(_runner(), name="codex-current-session-approval-mirror")
