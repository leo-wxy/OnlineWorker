import asyncio
from collections import deque
from collections import OrderedDict
import glob
import json
import logging
import os
import re
import shlex
import shutil
import sys
import time
import uuid
from typing import Any, Awaitable, Callable

from plugins.providers.builtin.claude.python.hook_bridge import (
    claude_hook_settings_path,
    claude_hook_socket_path,
    write_claude_hook_settings,
)
from plugins.providers.builtin.claude.python.storage_runtime import (
    _extract_claude_row_text,
    _find_claude_project_session_file,
    _iter_claude_project_rows,
    _parse_claude_timestamp,
    list_claude_threads_by_cwd,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, Any], Awaitable[None]]
ServerRequestCallback = Callable[[str, Any, int], Awaitable[None]]
PARENT_SESSION_ENV_VARS = (
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_ENABLE_SDK_FILE_CHECKPOINTING",
)

PREFERRED_CLAUDE_BINARIES = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
)
MIN_SUPPORTED_HOOK_NODE_MAJOR = 20
_PRETOOL_PERMISSION_TOOLS = frozenset(
    {"Bash", "Edit", "Write", "AskUserQuestion", "ExitPlanMode"}
)


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        return value
    return str(value or "")


def _extract_claude_assistant_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").strip() != "text":
            continue
        text = str(block.get("text") or "")
        if text:
            parts.append(text)
    return "".join(parts).strip()


def _extract_claude_stream_delta(event: Any) -> str:
    if not isinstance(event, dict):
        return ""
    event_type = str(event.get("type") or "").strip()
    payload_key = "content_block" if event_type == "content_block_start" else "delta"
    if event_type not in {"content_block_start", "content_block_delta"}:
        return ""
    payload = event.get(payload_key)
    if not isinstance(payload, dict):
        return ""
    payload_type = str(payload.get("type") or "").strip()
    if payload_type == "text":
        return str(payload.get("text") or "")
    if payload_type == "text_delta":
        return str(payload.get("text") or "")
    return ""


def _message_has_tool_use(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").strip() == "tool_use":
            return True
    return False


def _normalize_hook_tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    tool_input = payload.get("tool_input")
    return tool_input if isinstance(tool_input, dict) else {}


def _normalize_hook_tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool_name") or "").strip()


def _hook_event_name(payload: dict[str, Any]) -> str:
    return str(payload.get("hook_event_name") or "").strip()


def _hook_session_id(payload: dict[str, Any]) -> str:
    return str(payload.get("session_id") or payload.get("sessionId") or "").strip()


def _hook_cwd(payload: dict[str, Any]) -> str:
    return str(payload.get("cwd") or "").strip()


def _hook_is_notification_question(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) == "Notification" and bool(str(payload.get("question") or "").strip())


def _hook_is_pretool_event(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) == "PreToolUse"


def _hook_is_ask_user_question(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) in {"PermissionRequest", "PreToolUse"} and _normalize_hook_tool_name(payload) == "AskUserQuestion"


def _hook_is_tool_approval_request(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) in {"PermissionRequest", "PreToolUse"} and _normalize_hook_tool_name(payload) in _PRETOOL_PERMISSION_TOOLS - {"AskUserQuestion"}


def _hook_extract_option_rows(raw_options: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(raw_options, list):
        for item in raw_options:
            if isinstance(item, dict):
                rows.append(
                    {
                        "label": str(item.get("label") or "").strip(),
                        "description": str(item.get("description") or "").strip(),
                    }
                )
                continue
            label = str(item or "").strip()
            if label:
                rows.append({"label": label, "description": ""})
    return [row for row in rows if row["label"]]


def _hook_permission_display(payload: dict[str, Any]) -> tuple[str, str]:
    tool_name = _normalize_hook_tool_name(payload)
    tool_input = _normalize_hook_tool_input(payload)

    if tool_name == "Bash":
        command = str(tool_input.get("command") or "").strip() or "Bash"
        reason = str(tool_input.get("description") or "").strip() or command
        return command, reason

    if tool_name in {"Edit", "Write"}:
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "").strip()
        command = file_path or tool_name
        reason = str(tool_input.get("description") or "").strip() or f"{tool_name} 请求"
        return command, reason

    command = str(tool_input.get("command") or "").strip()
    if not command:
        command = tool_name or "Claude 权限请求"
    reason = str(tool_input.get("description") or "").strip() or command
    return command, reason


def _build_permission_hook_response(result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if "hookSpecificOutput" in result:
        return result

    event_name = _hook_event_name(payload)
    behavior = str(result.get("behavior") or "").strip().lower() or "deny"
    if event_name == "PreToolUse":
        permission_decision = "allow" if behavior == "allow" else "deny"
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": permission_decision,
            }
        }
        reason = str(result.get("reason") or "").strip()
        if reason:
            response["hookSpecificOutput"]["permissionDecisionReason"] = reason
        return response

    if behavior != "allow":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                },
            }
        }

    decision: dict[str, Any] = {"behavior": "allow"}
    if str(result.get("scope") or "").strip().lower() == "session":
        tool_name = _normalize_hook_tool_name(payload)
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
            "hookEventName": "PermissionRequest",
            "decision": decision,
        }
    }


def _build_answer_keys(questions: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    used: set[str] = set()
    for idx, question in enumerate(questions):
        question_text = str(question.get("question") or "").strip()
        header = str(question.get("header") or "").strip()
        base_key = question_text or header or f"answer_{idx + 1}"
        key = base_key
        if key in used:
            suffix = 2
            while f"{base_key}_{suffix}" in used:
                suffix += 1
            key = f"{base_key}_{suffix}"
        used.add(key)
        keys.append(key)
    return keys


def _build_question_hook_response(
    payload: dict[str, Any],
    questions: list[dict[str, Any]],
    answer_keys: list[str],
    answers: list[list[str]],
) -> dict[str, Any]:
    if _hook_event_name(payload) == "Notification":
        first = answers[0][0] if answers and answers[0] else ""
        return {
            "hookSpecificOutput": {
                "hookEventName": "Notification",
                "answer": first,
            }
        }

    answers_dict: OrderedDict[str, Any] = OrderedDict()
    for idx, answer_key in enumerate(answer_keys):
        selected = answers[idx] if idx < len(answers) else []
        answers_dict[answer_key] = ",".join(str(item or "").strip() for item in selected if str(item or "").strip())

    updated_input = {
        "questions": questions,
        "answers": answers_dict,
    }

    if _hook_event_name(payload) == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": updated_input,
            }
        }

    return {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": "allow",
                "updatedInput": updated_input,
            },
        }
    }


def inspect_claude_thread_busy_state(
    session_file: str | None,
    now_ms: int | None = None,
    recent_window_ms: int = 5 * 60 * 1000,
    sample_limit: int = 60,
) -> dict[str, Any]:
    if not session_file:
        return {"busy": False}

    rows = deque(maxlen=max(1, sample_limit))
    for row in _iter_claude_project_rows(session_file):
        rows.append(row)
    if not rows:
        return {"busy": False}

    now_ts = int(now_ms if now_ms is not None else time.time() * 1000)
    signals: list[str] = []
    latest_ts = 0
    latest_cwd = ""
    latest_entrypoint = ""
    latest_busy_signal_ts = 0
    latest_completion_ts = 0

    for row in rows:
        if not isinstance(row, dict) or row.get("isSidechain") is True:
            continue
        ts = _parse_claude_timestamp(row.get("timestamp"))
        if ts <= 0:
            continue
        latest_ts = max(latest_ts, ts)
        if latest_ts == ts:
            latest_cwd = str(row.get("cwd") or "")
            latest_entrypoint = str(row.get("entrypoint") or "")
        if now_ts - ts > recent_window_ms:
            continue

        row_type = str(row.get("type") or "").strip()
        if row_type == "queue-operation":
            signals.append("queue")
            latest_busy_signal_ts = max(latest_busy_signal_ts, ts)
            continue
        if row_type == "system" and str(row.get("subtype") or "").strip() == "compact_boundary":
            signals.append("compact")
            latest_busy_signal_ts = max(latest_busy_signal_ts, ts)
            continue
        if row_type == "assistant":
            message = row.get("message")
            if _message_has_tool_use(message) or str((message or {}).get("stop_reason") or "").strip() == "tool_use":
                signals.append("assistant_tool_use")
                latest_busy_signal_ts = max(latest_busy_signal_ts, ts)
                continue
            if str((message or {}).get("stop_reason") or "").strip() == "end_turn":
                latest_completion_ts = max(latest_completion_ts, ts)
                continue
        if row_type == "user":
            if row.get("toolUseResult") is not None:
                signals.append("tool_result")
                continue
            text = _extract_claude_row_text(row)
            if text.startswith("[Request interrupted by user"):
                signals.append("interrupted")
                latest_busy_signal_ts = max(latest_busy_signal_ts, ts)
                continue

    if not signals:
        return {"busy": False, "latest_ts": latest_ts}

    non_terminal_signals = {
        signal for signal in signals
        if signal not in {"tool_result"}
    }
    if not non_terminal_signals:
        return {"busy": False, "latest_ts": latest_ts}

    if latest_completion_ts and latest_completion_ts >= latest_busy_signal_ts:
        return {"busy": False, "latest_ts": latest_ts}

    latest_age_sec = max(0, (now_ts - latest_ts) // 1000) if latest_ts else None
    location = latest_cwd or "当前 workspace"
    if latest_age_sec is None:
        message = (
            "当前 Claude thread 最近仍有本地任务痕迹，TG 消息继续注入只会排队，"
            "不能稳定得到独立回复。请先在本地/TUI收尾，或新开一个 Claude thread。"
        )
    else:
        message = (
            f"当前 Claude thread 仍在忙碌中，最近 {latest_age_sec} 秒内还在 `{location}` "
            f"执行本地任务（signals={','.join(sorted(set(signals)))}, entrypoint={latest_entrypoint or 'unknown'}）。"
            "TG 消息继续注入只会排队，不能稳定得到独立回复。请先在本地/TUI收尾，或新开一个 Claude thread。"
        )
    return {
        "busy": True,
        "signals": sorted(set(signals)),
        "latest_ts": latest_ts,
        "latest_cwd": latest_cwd,
        "latest_entrypoint": latest_entrypoint,
        "message": message,
    }


async def _read_stream_text(stream) -> str:
    if stream is None:
        return ""
    data = await stream.read()
    return _to_text(data)


def resolve_claude_bin(claude_bin: str) -> str:
    raw = str(claude_bin or "claude").strip() or "claude"
    expanded = os.path.expanduser(raw)

    # 显式路径 / 自定义包装脚本一律尊重，不做重写。
    if os.path.sep in raw:
        return expanded

    # 仅对裸 `claude` 命令做优先级修正，避免吃到 ~/.local/bin 中的陈旧版本。
    if raw != "claude":
        return expanded

    for candidate in PREFERRED_CLAUDE_BINARIES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    local_candidate = os.path.expanduser("~/.local/bin/claude")
    if os.path.isfile(local_candidate) and os.access(local_candidate, os.X_OK):
        return local_candidate

    which_result = shutil.which("claude")
    if which_result:
        return which_result

    return expanded


def _parse_node_semver(version_name: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(version_name or "").strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return (major, minor, patch)


def resolve_preferred_node_bin_dir() -> str | None:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for node_path in glob.glob(os.path.expanduser("~/.nvm/versions/node/v*/bin/node")):
        version_name = os.path.basename(os.path.dirname(os.path.dirname(node_path)))
        version = _parse_node_semver(version_name)
        if version is None or version[0] < MIN_SUPPORTED_HOOK_NODE_MAJOR:
            continue
        if not os.path.isfile(node_path) or not os.access(node_path, os.X_OK):
            continue
        candidates.append((version, os.path.dirname(node_path)))

    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]

    current_nvm_bin = str(os.environ.get("NVM_BIN") or "").strip()
    if current_nvm_bin:
        current_node = os.path.join(current_nvm_bin, "node")
        if os.path.isfile(current_node) and os.access(current_node, os.X_OK):
            return current_nvm_bin
    return None


class ClaudeAdapter:
    """Claude CLI 本地 adapter。

    基线形态只保证：
    - list_threads 走本地事实源
    - send_user_message 走 `claude -p --session-id`
    - 输出归一化成现有 app-server event 结构
    """

    def __init__(self, claude_bin: str = "claude"):
        self.claude_bin = claude_bin
        self._connected = False
        self._auth_ready: bool | None = None
        self._auth_method: str = ""
        self._event_callbacks: list[EventCallback] = []
        self._server_request_callbacks: list[ServerRequestCallback] = []
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self._workspace_cwd_map: dict[str, str] = {}
        self._thread_workspace_map: dict[str, str] = {}
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled_threads: set[str] = set()
        self._hook_server: asyncio.base_events.Server | None = None
        self._hook_data_dir: str | None = None
        self._hook_socket_path: str | None = None
        self._hook_settings_path: str | None = None
        self._pending_hook_requests: dict[str, dict[str, Any]] = {}
        self._pending_hook_questions: dict[str, dict[str, Any]] = {}
        self._session_tool_allowlist: set[tuple[str, str]] = set()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def auth_ready(self) -> bool | None:
        return self._auth_ready

    @property
    def auth_method(self) -> str:
        return self._auth_method

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        for thread_id, proc in list(self._active_processes.items()):
            try:
                proc.kill()
            except Exception:
                pass
            self._active_processes.pop(thread_id, None)
        await self.stop_hook_bridge()
        for cb in self._disconnect_callbacks:
            try:
                cb()
            except Exception:
                logger.debug("Claude disconnect callback failed", exc_info=True)

    def on_event(self, callback: EventCallback) -> None:
        self._event_callbacks.append(callback)

    def on_server_request(self, callback: ServerRequestCallback) -> None:
        self._server_request_callbacks.append(callback)

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        self._disconnect_callbacks.append(callback)

    def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
        self._workspace_cwd_map[workspace_id] = cwd

    @property
    def hook_socket_path(self) -> str | None:
        return self._hook_socket_path

    @property
    def hook_settings_path(self) -> str | None:
        return self._hook_settings_path

    async def start_hook_bridge(self, data_dir: str) -> None:
        if self._hook_server is not None:
            return
        os.makedirs(data_dir, exist_ok=True)
        self._hook_data_dir = data_dir
        self._hook_socket_path = claude_hook_socket_path(data_dir)
        self._hook_settings_path = write_claude_hook_settings(data_dir)
        if not self._hook_socket_path:
            raise RuntimeError("缺少 Claude hook socket 路径")
        if os.path.exists(self._hook_socket_path):
            os.remove(self._hook_socket_path)
        self._hook_server = await asyncio.start_unix_server(
            self._handle_hook_client,
            path=self._hook_socket_path,
        )
        logger.info("[claude-hook-bridge] 已启动 socket=%s", self._hook_socket_path)

    async def stop_hook_bridge(self) -> None:
        for entry in list(self._pending_hook_requests.values()):
            future = entry.get("future")
            payload = entry.get("payload") or {}
            if future is not None and not future.done():
                future.set_result(_build_permission_hook_response({"behavior": "deny"}, payload))
        self._pending_hook_requests.clear()

        for entry in list(self._pending_hook_questions.values()):
            future = entry.get("future")
            payload = entry.get("payload") or {}
            if future is not None and not future.done():
                future.set_result(_build_question_hook_response(payload, [], [], []))
        self._pending_hook_questions.clear()
        self._session_tool_allowlist.clear()

        if self._hook_server is not None:
            self._hook_server.close()
            await self._hook_server.wait_closed()
            self._hook_server = None
        if self._hook_socket_path and os.path.exists(self._hook_socket_path):
            try:
                os.remove(self._hook_socket_path)
            except OSError:
                pass
        self._hook_socket_path = None
        self._hook_settings_path = None
        self._hook_data_dir = None

    async def _handle_hook_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.read()
            response: dict[str, Any] = {}
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    response = await self.handle_hook_payload(payload)
            writer.write(json.dumps(response or {}, ensure_ascii=False).encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _resolve_hook_workspace_id(self, payload: dict[str, Any]) -> str:
        session_id = _hook_session_id(payload)
        if session_id:
            mapped = self._thread_workspace_map.get(session_id)
            if mapped:
                return mapped
        cwd = _hook_cwd(payload)
        if cwd:
            for workspace_id, workspace_cwd in self._workspace_cwd_map.items():
                if workspace_cwd == cwd:
                    if session_id:
                        self._thread_workspace_map[session_id] = workspace_id
                    return workspace_id
        return ""

    async def handle_hook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if _hook_is_ask_user_question(payload):
            return await self._handle_ask_user_question_payload(payload)
        if _hook_is_tool_approval_request(payload):
            return await self._handle_permission_request_payload(payload)
        if _hook_is_notification_question(payload):
            return await self._handle_notification_question_payload(payload)
        return {}

    def _session_tool_allow_key(self, payload: dict[str, Any]) -> tuple[str, str] | None:
        session_id = _hook_session_id(payload)
        tool_name = _normalize_hook_tool_name(payload)
        if not session_id or not tool_name:
            return None
        return session_id, tool_name

    def _is_session_tool_auto_allowed(self, payload: dict[str, Any]) -> bool:
        key = self._session_tool_allow_key(payload)
        return key in self._session_tool_allowlist if key is not None else False

    async def _handle_permission_request_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_session_tool_auto_allowed(payload):
            return _build_permission_hook_response({"behavior": "allow"}, payload)

        request_id = str(payload.get("request_id") or payload.get("id") or uuid.uuid4())
        workspace_id = self._resolve_hook_workspace_id(payload)
        thread_id = _hook_session_id(payload)
        command, reason = _hook_permission_display(payload)
        future = asyncio.get_running_loop().create_future()
        self._pending_hook_requests[request_id] = {
            "future": future,
            "payload": payload,
        }
        try:
            await self._emit_event(
                workspace_id,
                "item/commandExecution/requestApproval",
                {
                    "threadId": thread_id,
                    "command": command,
                    "reason": reason,
                    "request_id": request_id,
                    "_provider": "claude",
                    "_claude_permission": True,
                    "toolName": _normalize_hook_tool_name(payload),
                },
            )
            return await future
        finally:
            self._pending_hook_requests.pop(request_id, None)

    async def _handle_ask_user_question_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool_input = _normalize_hook_tool_input(payload)
        questions = tool_input.get("questions") if isinstance(tool_input.get("questions"), list) else []
        question_id = str(payload.get("question_id") or payload.get("request_id") or payload.get("id") or uuid.uuid4())
        answer_keys = _build_answer_keys(questions)
        workspace_id = self._resolve_hook_workspace_id(payload)
        thread_id = _hook_session_id(payload)
        future = asyncio.get_running_loop().create_future()
        self._pending_hook_questions[question_id] = {
            "future": future,
            "payload": payload,
            "questions": questions,
            "answer_keys": answer_keys,
        }
        try:
            for idx, question in enumerate(questions):
                await self._emit_event(
                    workspace_id,
                    "question/asked",
                    {
                        "threadId": thread_id,
                        "questionId": question_id,
                        "header": str(question.get("header") or ""),
                        "question": str(question.get("question") or ""),
                        "options": _hook_extract_option_rows(question.get("options")),
                        "multiple": bool(question.get("multiple") or question.get("multiSelect")),
                        "custom": bool(question.get("custom", True)),
                        "subIndex": idx,
                        "subTotal": len(questions),
                    },
                )
            return await future
        finally:
            self._pending_hook_questions.pop(question_id, None)

    async def _handle_notification_question_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        question_id = str(payload.get("question_id") or payload.get("request_id") or payload.get("id") or uuid.uuid4())
        workspace_id = self._resolve_hook_workspace_id(payload)
        thread_id = _hook_session_id(payload)
        question = {
            "header": "",
            "question": str(payload.get("question") or ""),
            "options": payload.get("options"),
            "multiple": False,
            "custom": True,
        }
        future = asyncio.get_running_loop().create_future()
        self._pending_hook_questions[question_id] = {
            "future": future,
            "payload": payload,
            "questions": [question],
            "answer_keys": ["answer"],
        }
        try:
            await self._emit_event(
                workspace_id,
                "question/asked",
                {
                    "threadId": thread_id,
                    "questionId": question_id,
                    "header": "",
                    "question": question["question"],
                    "options": _hook_extract_option_rows(question["options"]),
                    "multiple": False,
                    "custom": True,
                    "subIndex": 0,
                    "subTotal": 1,
                },
            )
            return await future
        finally:
            self._pending_hook_questions.pop(question_id, None)

    def _proxy_base_url(self) -> str:
        return (os.environ.get("ANTHROPIC_BASE_URL") or "").strip()

    def _proxy_model(self) -> str:
        return (os.environ.get("ANTHROPIC_MODEL") or "").strip()

    def _build_claude_env(self) -> dict[str, str]:
        env = dict(os.environ)
        base_url = self._proxy_base_url()
        if base_url and not (env.get("ANTHROPIC_API_KEY") or "").strip():
            # Claude CLI 在代理模式下仍要求一个非空 key 形状；本地代理链通常接受占位值。
            env["ANTHROPIC_API_KEY"] = "dummy"
        for key in PARENT_SESSION_ENV_VARS:
            env.pop(key, None)
        for key in tuple(env.keys()):
            if key.startswith("CODEX_"):
                env.pop(key, None)

        preferred_node_bin = resolve_preferred_node_bin_dir()
        if preferred_node_bin:
            current_path = str(env.get("PATH") or "")
            path_entries = [entry for entry in current_path.split(os.pathsep) if entry]
            path_entries = [entry for entry in path_entries if entry != preferred_node_bin]
            env["PATH"] = os.pathsep.join([preferred_node_bin, *path_entries]) if path_entries else preferred_node_bin
            env["NVM_BIN"] = preferred_node_bin
        return env

    def _build_send_argv(self, thread_id: str, text: str) -> list[str]:
        base_args = [
            self.claude_bin,
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
        ]
        if self._hook_settings_path:
            base_args.extend([
                "--setting-sources",
                "project,local",
                "--settings",
                self._hook_settings_path,
            ])
        if _find_claude_project_session_file(thread_id):
            return [*base_args, "--resume", thread_id, text]
        return [*base_args, "--session-id", thread_id, text]

    async def refresh_auth_status(self) -> dict:
        if os.environ.get("ANTHROPIC_API_KEY"):
            self._auth_ready = True
            self._auth_method = "apiKeyEnv"
            return {"loggedIn": True, "authMethod": self._auth_method}

        if self._proxy_base_url():
            self._auth_ready = True
            self._auth_method = "proxyEnv"
            return {"loggedIn": True, "authMethod": self._auth_method}

        try:
            proc = await asyncio.create_subprocess_exec(
                self.claude_bin,
                "auth",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except Exception as e:
            logger.warning(f"读取 Claude auth 状态失败：{e}")
            self._auth_ready = None
            self._auth_method = ""
            return {"loggedIn": None, "authMethod": "", "error": str(e)}

        out_text = _to_text(stdout).strip()
        err_text = _to_text(stderr).strip()
        payload = out_text or err_text
        if not payload:
            self._auth_ready = None
            self._auth_method = ""
            return {"loggedIn": None, "authMethod": ""}

        try:
            status = json.loads(payload)
        except Exception:
            logged_in = "not logged in" not in payload.lower()
            self._auth_ready = True if logged_in else False
            self._auth_method = "" if logged_in else "none"
            return {"loggedIn": self._auth_ready, "authMethod": self._auth_method}

        if isinstance(status, dict):
            self._auth_ready = status.get("loggedIn")
            self._auth_method = str(status.get("authMethod") or "")
            return status

        self._auth_ready = None
        self._auth_method = ""
        return {"loggedIn": None, "authMethod": ""}

    async def _ensure_auth_ready(self) -> None:
        status = await self.refresh_auth_status()
        if status.get("loggedIn") is False:
            raise RuntimeError(
                "Claude CLI 未鉴权。请先在本机终端执行 `claude auth login`，"
                "或配置 `ANTHROPIC_API_KEY`；若走代理，再补 `ANTHROPIC_BASE_URL` "
                "和 `ANTHROPIC_MODEL`。"
            )

    async def _emit_event(self, workspace_id: str, method: str, params: dict) -> None:
        envelope = {
            "message": {"method": method, "params": params},
            "workspace_id": workspace_id,
        }
        for cb in self._event_callbacks:
            await cb("app-server-event", envelope)

    async def list_workspaces(self) -> list[dict]:
        return [
            {"id": workspace_id, "name": workspace_id.split(":", 1)[-1], "path": cwd}
            for workspace_id, cwd in self._workspace_cwd_map.items()
        ]

    async def list_threads(self, workspace_id: str, limit: int = 20) -> list[dict]:
        cwd = self._workspace_cwd_map.get(workspace_id)
        if not cwd:
            return []
        return list_claude_threads_by_cwd(cwd, limit=limit)

    async def start_thread(self, workspace_id: str) -> dict:
        thread_id = str(uuid.uuid4())
        self._thread_workspace_map[thread_id] = workspace_id
        return {"id": thread_id}

    async def resume_thread(self, workspace_id: str, thread_id: str) -> dict:
        self._thread_workspace_map[thread_id] = workspace_id
        return {"id": thread_id}

    async def archive_thread(self, workspace_id: str, thread_id: str) -> dict:
        self._thread_workspace_map[thread_id] = workspace_id
        return {"id": thread_id, "status": "archived"}

    async def inspect_thread_activity(self, thread_id: str) -> dict[str, Any]:
        session_file = _find_claude_project_session_file(thread_id)
        return inspect_claude_thread_busy_state(session_file)

    async def turn_interrupt(self, workspace_id: str, thread_id: str, turn_id: str) -> dict:
        proc = self._active_processes.get(thread_id)
        if proc is None:
            raise RuntimeError("当前没有可中断的 Claude 任务。")
        self._cancelled_threads.add(thread_id)
        try:
            proc.kill()
        except Exception as e:
            raise RuntimeError(f"中断 Claude 任务失败：{e}") from e
        return {"threadId": thread_id, "turnId": turn_id, "status": "cancelled"}

    async def reply_server_request(self, *args, **kwargs) -> dict:
        if len(args) >= 3:
            request_id = args[1]
            result = args[2]
        else:
            request_id = kwargs.get("request_id")
            result = kwargs.get("result")
        request_key = str(request_id or "").strip()
        entry = self._pending_hook_requests.get(request_key)
        if entry is None:
            raise RuntimeError(f"Claude 权限请求不存在：{request_key}")
        payload = entry.get("payload") or {}
        result_dict = result if isinstance(result, dict) else {}
        if (
            str(result_dict.get("behavior") or "").strip().lower() == "allow"
            and str(result_dict.get("scope") or "").strip().lower() == "session"
        ):
            allow_key = self._session_tool_allow_key(payload)
            if allow_key is not None:
                self._session_tool_allowlist.add(allow_key)
        response = _build_permission_hook_response(
            result_dict,
            payload,
        )
        future = entry.get("future")
        if future is not None and not future.done():
            future.set_result(response)
        return response

    async def reply_question(self, question_id: str, answers: list[list[str]]) -> dict:
        question_key = str(question_id or "").strip()
        entry = self._pending_hook_questions.get(question_key)
        if entry is None:
            raise RuntimeError(f"Claude question 请求不存在：{question_key}")
        response = _build_question_hook_response(
            entry.get("payload") or {},
            entry.get("questions") or [],
            entry.get("answer_keys") or [],
            answers,
        )
        future = entry.get("future")
        if future is not None and not future.done():
            future.set_result(response)
        return response

    async def send_user_message(self, workspace_id: str, thread_id: str, text: str) -> dict:
        if not self._connected:
            raise RuntimeError("Claude 未连接")

        cwd = self._workspace_cwd_map.get(workspace_id)
        if not cwd:
            raise RuntimeError("Claude workspace 未注册 cwd")

        await self._ensure_auth_ready()

        self._thread_workspace_map[thread_id] = workspace_id
        turn_id = str(uuid.uuid4())

        await self._emit_event(
            workspace_id,
            "turn/started",
            {
                "threadId": thread_id,
                "turn": {"id": turn_id, "threadId": thread_id},
            },
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._build_send_argv(thread_id, text),
                cwd=cwd,
                env=self._build_claude_env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            await self._emit_event(
                workspace_id,
                "turn/completed",
                {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "threadId": thread_id,
                        "status": "error",
                        "error": str(e),
                    },
                },
            )
            return {"threadId": thread_id, "turnId": turn_id, "status": "error", "error": str(e)}

        self._active_processes[thread_id] = proc
        stderr_task = asyncio.create_task(_read_stream_text(proc.stderr))
        final_text = ""
        stream_error = ""
        streamed_parts: list[str] = []
        raw_lines: list[str] = []
        try:
            while True:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                line = _to_text(raw_line).strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    raw_lines.append(line)
                    continue
                if not isinstance(record, dict):
                    continue
                record_type = str(record.get("type") or "").strip()
                if record_type == "stream_event":
                    delta = _extract_claude_stream_delta(record.get("event"))
                    if not delta:
                        continue
                    streamed_parts.append(delta)
                    await self._emit_event(
                        workspace_id,
                        "item/agentMessage/delta",
                        {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "delta": delta,
                        },
                    )
                    continue
                if record_type == "assistant":
                    assistant_text = _extract_claude_assistant_text(record.get("message"))
                    if assistant_text:
                        final_text = assistant_text
                    continue
                if record_type == "result":
                    result_text = str(record.get("result") or "").strip()
                    if bool(record.get("is_error")) or str(record.get("subtype") or "").strip() == "error":
                        if result_text:
                            stream_error = result_text
                    elif result_text and not final_text:
                        final_text = result_text
            returncode = await proc.wait()
        finally:
            self._active_processes.pop(thread_id, None)
        err_text = (await stderr_task).strip()
        if not final_text and streamed_parts:
            final_text = "".join(streamed_parts).strip()
        if not final_text and raw_lines:
            final_text = "\n".join(raw_lines).strip()

        if thread_id in self._cancelled_threads:
            self._cancelled_threads.discard(thread_id)
            await self._emit_event(
                workspace_id,
                "turn/completed",
                {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "threadId": thread_id,
                        "status": "cancelled",
                        "error": err_text or "任务已取消",
                    },
                },
            )
            return {"threadId": thread_id, "turnId": turn_id, "status": "cancelled"}

        if int(returncode or 0) == 0 and not stream_error:
            if final_text:
                await self._emit_event(
                    workspace_id,
                    "item/completed",
                    {
                        "threadId": thread_id,
                        "item": {
                            "type": "agentMessage",
                            "text": final_text,
                            "phase": "final_answer",
                            "threadId": thread_id,
                            "turn": {"id": turn_id},
                        },
                    },
                )
            await self._emit_event(
                workspace_id,
                "turn/completed",
                {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "threadId": thread_id,
                        "status": "completed",
                    },
                },
            )
            return {"threadId": thread_id, "turnId": turn_id, "status": "completed", "text": final_text}

        error_text = stream_error or err_text or final_text or "Claude 执行失败"
        logger.warning(
            "Claude 执行失败 thread=%s returncode=%s error=%s",
            thread_id,
            returncode,
            error_text,
        )
        await self._emit_event(
            workspace_id,
            "turn/completed",
            {
                "threadId": thread_id,
                "turn": {
                    "id": turn_id,
                    "threadId": thread_id,
                    "status": "error",
                    "error": error_text,
                },
            },
        )
        return {"threadId": thread_id, "turnId": turn_id, "status": "error", "error": error_text}
