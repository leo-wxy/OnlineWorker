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
    ONLINEWORKER_MANAGED_HOOK_PAYLOAD_KEY,
    claude_hook_settings_path,
    claude_hook_socket_path,
    install_onlineworker_claude_hooks,
    uninstall_onlineworker_claude_hooks,
    write_claude_hook_settings,
)
from plugins.providers.builtin.claude.python.storage_runtime import (
    _extract_claude_row_text,
    _find_claude_project_session_file,
    _iter_claude_project_rows,
    _parse_claude_timestamp,
    _read_claude_project_turns,
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
CLAUDE_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
)
STALE_CLAUDE_BASE_URLS = {
    "http://localhost:3031",
    "http://127.0.0.1:3031",
}
MIN_SUPPORTED_HOOK_NODE_MAJOR = 20
CLAUDE_STREAM_BUFFER_LIMIT = 10 * 1024 * 1024
_PRETOOL_APPROVAL_TOOLS = frozenset({"Bash", "Edit", "MultiEdit", "Write", "Read", "ExitPlanMode"})
_PERMISSION_REQUEST_TOOLS = frozenset({"Bash", "Edit", "MultiEdit", "Write", "Read", "ExitPlanMode"})
CLAUDE_REASON_DETAILS = {
    "ok": "Claude provider is ready.",
    "loggedOut": "Claude CLI is not logged in.",
    "missingCli": "Claude CLI executable was not found.",
    "missingRuntime": "Claude runtime environment is not configured.",
    "staleEnv": "Claude runtime environment points to a stale local proxy.",
    "emptyAuthStatus": "Claude auth status returned no output.",
    "unknownAuthStatus": "Claude auth status returned unrecognized output.",
    "authStatusFailed": "Claude auth status failed.",
}


class ClaudeProviderUnavailable(RuntimeError):
    def __init__(self, readiness: dict[str, Any]):
        self.readiness = dict(readiness)
        super().__init__(format_claude_unavailable_message(self.readiness))


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


def _hook_transcript_path(payload: dict[str, Any]) -> str:
    return str(payload.get("transcript_path") or payload.get("transcriptPath") or "").strip()


def _hook_user_prompt(payload: dict[str, Any]) -> str:
    return str(
        payload.get("user_prompt")
        or payload.get("userPrompt")
        or payload.get("prompt")
        or ""
    ).strip()


def _hook_reason(payload: dict[str, Any]) -> str:
    return str(payload.get("reason") or "").strip()


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
    event_name = _hook_event_name(payload)
    tool_name = _normalize_hook_tool_name(payload)
    if event_name == "PreToolUse":
        return tool_name in _PRETOOL_APPROVAL_TOOLS
    if event_name == "PermissionRequest":
        return tool_name in _PERMISSION_REQUEST_TOOLS
    return False


def _hook_is_interactive_request(payload: dict[str, Any]) -> bool:
    return (
        _hook_is_ask_user_question(payload)
        or _hook_is_tool_approval_request(payload)
        or _hook_is_notification_question(payload)
    )


def _hook_is_lifecycle_event(payload: dict[str, Any]) -> bool:
    return _hook_event_name(payload) in {
        "PostToolUse",
        "SessionStart",
        "SessionEnd",
        "Stop",
        "UserPromptSubmit",
    }


def _hook_failure_text(payload: dict[str, Any]) -> str:
    for key in ("error", "error_message", "failure", "failure_reason"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    status = str(payload.get("status") or "").strip().lower()
    if status in {"error", "failed"}:
        return str(payload.get("message") or payload.get("reason") or status).strip()
    return ""


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

    if tool_name == "Read":
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "").strip()
        offset = tool_input.get("offset")
        limit = tool_input.get("limit")
        line_suffix = ""
        try:
            start = int(offset) if offset is not None else None
            count = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            start = None
            count = None
        if start is not None and count is not None and count > 0:
            line_suffix = f" · lines {start}-{start + count - 1}"
        command = f"Read({file_path}{line_suffix})" if file_path else "Read"
        reason = str(tool_input.get("description") or "").strip() or command
        return command, reason

    if tool_name in {"Edit", "MultiEdit", "Write"}:
        file_path = str(tool_input.get("file_path") or tool_input.get("path") or "").strip()
        command = file_path or tool_name
        reason = str(tool_input.get("description") or "").strip() or f"{tool_name} 请求"
        return command, reason

    command = str(tool_input.get("command") or "").strip()
    if not command:
        command = tool_name or "Claude 权限请求"
    reason = str(tool_input.get("description") or "").strip() or command
    return command, reason


def _hook_tool_activity_display(payload: dict[str, Any]) -> str:
    tool_name = _normalize_hook_tool_name(payload)
    tool_input = _normalize_hook_tool_input(payload)
    if tool_name in {"Bash", "Edit", "MultiEdit", "Write", "Read"}:
        command, _reason = _hook_permission_display(payload)
        if tool_name == "Bash":
            return f"$ {command}"
        return command

    for key in ("command", "pattern", "url", "query", "file_path", "path", "description"):
        value = str(tool_input.get(key) or "").strip()
        if value:
            return f"{tool_name}: {value}" if tool_name else value
    return tool_name or "Claude tool"


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

    # 裸命令交给运行时 PATH 解析，保持 TG provider 与 App Session Tab 行为一致。
    return expanded


def resolve_claude_command_prefix(claude_command: str) -> list[str]:
    raw = str(claude_command or "claude").strip() or "claude"
    try:
        parts = shlex.split(raw)
    except ValueError:
        parts = [raw]
    if not parts:
        parts = ["claude"]

    command = os.path.expanduser(parts[0])
    if len(parts) == 1:
        command = resolve_claude_bin(command)
    parts[0] = command
    return parts


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


def _is_stale_claude_base_url(value: str) -> bool:
    return str(value or "").strip().rstrip("/").lower() in STALE_CLAUDE_BASE_URLS


def _claude_runtime_env_is_usable(env: dict[str, str]) -> bool:
    base_url = str(env.get("ANTHROPIC_BASE_URL") or "").strip()
    if _is_stale_claude_base_url(base_url):
        return False
    return any(
        str(env.get(key) or "").strip()
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
    )


def _collect_claude_runtime_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    source = base_env or os.environ
    return {
        key: str(source.get(key) or "").strip()
        for key in CLAUDE_ENV_VARS
        if str(source.get(key) or "").strip()
    }


def _detect_claude_runtime_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    current = _collect_claude_runtime_env(base_env)
    if _claude_runtime_env_is_usable(current):
        return current
    return {}


def _runtime_auth_method(runtime_env: dict[str, str]) -> str:
    if runtime_env.get("ANTHROPIC_BASE_URL"):
        return "proxyEnv"
    if runtime_env.get("ANTHROPIC_API_KEY"):
        return "apiKeyEnv"
    if runtime_env.get("ANTHROPIC_AUTH_TOKEN"):
        return "authTokenEnv"
    return ""


def _new_claude_readiness(
    *,
    ready: bool,
    source: str,
    reason: str,
    auth_method: str = "",
    detail: str | None = None,
    raw_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_detail = str(detail or CLAUDE_REASON_DETAILS.get(reason) or reason).strip()
    status = {
        "ready": bool(ready),
        "source": str(source or "unknown"),
        "reason": str(reason or "unknown"),
        "authMethod": str(auth_method or ""),
        "checked_at": time.time(),
        "detail": normalized_detail,
    }
    if isinstance(raw_status, dict):
        api_provider = str(raw_status.get("apiProvider") or "").strip()
        if api_provider:
            status["apiProvider"] = api_provider
    return status


def _readiness_from_runtime_env(runtime_env: dict[str, str]) -> dict[str, Any] | None:
    if not runtime_env:
        return None
    base_url = str(runtime_env.get("ANTHROPIC_BASE_URL") or "").strip()
    if _is_stale_claude_base_url(base_url):
        return _new_claude_readiness(
            ready=False,
            source="runtimeEnv",
            reason="staleEnv",
            auth_method=_runtime_auth_method(runtime_env),
        )
    if _claude_runtime_env_is_usable(runtime_env):
        return _new_claude_readiness(
            ready=True,
            source="runtimeEnv",
            reason="ok",
            auth_method=_runtime_auth_method(runtime_env),
        )
    return None


def format_claude_unavailable_message(readiness: dict[str, Any] | None) -> str:
    status = readiness if isinstance(readiness, dict) else {}
    reason = str(status.get("reason") or "").strip()
    detail = str(status.get("detail") or "").strip()
    if reason == "loggedOut":
        return "Claude provider unavailable: Claude CLI is not logged in."
    if reason == "missingCli":
        return f"Claude provider unavailable: {detail or CLAUDE_REASON_DETAILS['missingCli']}"
    if detail:
        return f"Claude provider unavailable: {detail}"
    return "Claude provider unavailable: readiness check failed."


def _readiness_to_legacy_auth_status(readiness: dict[str, Any]) -> dict[str, Any]:
    return {
        "loggedIn": bool(readiness.get("ready")),
        "authMethod": str(readiness.get("authMethod") or ""),
    }


def _normalize_claude_launch_methods(
    claude_bin: str,
    launch_methods: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    raw_methods = launch_methods if isinstance(launch_methods, list) else []
    if not raw_methods:
        command = str(claude_bin or "claude").strip() or "claude"
        return [
            {
                "id": "configured_cli",
                "label": "Configured Claude provider CLI",
                "bin": command,
            }
        ]

    methods: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_methods):
        if isinstance(item, str):
            command = item.strip()
            method_id = f"method_{index + 1}"
            label = command
        elif isinstance(item, dict):
            command = str(item.get("bin") or item.get("command") or "").strip()
            method_id = str(item.get("id") or item.get("name") or f"method_{index + 1}").strip()
            label = str(item.get("label") or item.get("name") or method_id or command).strip()
        else:
            continue

        if not command:
            continue
        if not method_id:
            method_id = f"method_{index + 1}"
        original_method_id = method_id
        suffix = 2
        while method_id in seen:
            method_id = f"{original_method_id}_{suffix}"
            suffix += 1
        seen.add(method_id)
        methods.append(
            {
                "id": method_id,
                "label": label or method_id,
                "bin": command,
            }
        )

    if methods:
        return methods
    return _normalize_claude_launch_methods(claude_bin, None)


def _cli_method_status(
    method: dict[str, str],
    prefix: list[str],
    readiness: dict[str, Any],
    *,
    selected: bool = False,
    available_override: bool | None = None,
    reason_override: str | None = None,
    detail_override: str | None = None,
) -> dict[str, Any]:
    reason = str(reason_override or readiness.get("reason") or "").strip()
    detected = reason != "missingCli" and str(readiness.get("source") or "") != "missingCli"
    ready = bool(readiness.get("ready"))
    available = ready if available_override is None else bool(available_override)
    return {
        "id": str(method.get("id") or ""),
        "label": str(method.get("label") or method.get("id") or ""),
        "selected": bool(selected),
        "detected": detected,
        "available": available,
        "ready": available,
        "reason": reason or ("ok" if available else "unknown"),
        "detail": str(detail_override or readiness.get("detail") or "").strip(),
        "command": " ".join(str(part or "").strip() for part in prefix if str(part or "").strip()),
        "configured": str(method.get("bin") or "").strip(),
    }


def _command_prefix_available(prefix: list[str]) -> tuple[bool, str]:
    command = prefix[0] if prefix else ""
    if not command:
        return False, "empty command"
    expanded = os.path.expanduser(command)
    if os.path.sep in command:
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return True, expanded
        if os.path.exists(expanded):
            return False, f"not executable: {expanded}"
        return False, f"not found: {expanded}"
    resolved = shutil.which(command)
    if resolved:
        return True, resolved
    return False, f"not found on PATH: {command}"


def _missing_cli_readiness(detail: str | None = None) -> dict[str, Any]:
    return _new_claude_readiness(
        ready=False,
        source="missingCli",
        reason="missingCli",
        detail=detail or CLAUDE_REASON_DETAILS["missingCli"],
    )


def _attach_launch_method_readiness(
    readiness: dict[str, Any],
    method_statuses: list[dict[str, Any]],
    selected_method: dict[str, str] | None,
) -> dict[str, Any]:
    result = dict(readiness)
    if selected_method is not None:
        result["launchMethod"] = {
            "id": str(selected_method.get("id") or ""),
            "label": str(selected_method.get("label") or selected_method.get("id") or ""),
            "command": str(selected_method.get("bin") or "").strip(),
        }
    result["methods"] = [dict(method) for method in method_statuses]
    return result


class ClaudeAdapter:
    """Claude CLI 本地 adapter。

    基线形态只保证：
    - list_threads 走本地事实源
    - send_user_message 走 `claude -p --session-id`
    - 输出归一化成现有 app-server event 结构
    """

    def __init__(
        self,
        claude_bin: str = "claude",
        auth: dict[str, str] | None = None,
        launch_methods: list[dict[str, Any]] | None = None,
    ):
        self._claude_command_prefix = resolve_claude_command_prefix(claude_bin)
        self.claude_bin = self._claude_command_prefix[0]
        self._configured_claude_bin = str(claude_bin or "claude").strip() or "claude"
        self._launch_methods = _normalize_claude_launch_methods(self._configured_claude_bin, launch_methods)
        # auth is accepted for descriptor compatibility only. Claude CLI owns
        # provider/auth configuration; OnlineWorker treats it as a black-box CLI.
        self._connected = False
        self._auth_ready: bool | None = None
        self._auth_method: str = ""
        self._readiness: dict[str, Any] | None = None
        self._event_callbacks: list[EventCallback] = []
        self._server_request_callbacks: list[ServerRequestCallback] = []
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self._workspace_cwd_map: dict[str, str] = {}
        self._thread_workspace_map: dict[str, str] = {}
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._send_locks: dict[str, asyncio.Lock] = {}
        self._cancelled_threads: set[str] = set()
        self._hook_server: asyncio.base_events.Server | None = None
        self._hook_data_dir: str | None = None
        self._hook_socket_path: str | None = None
        self._hook_settings_path: str | None = None
        self._global_hook_settings_path: str | None = None
        self._pending_hook_requests: dict[str, dict[str, Any]] = {}
        self._pending_hook_questions: dict[str, dict[str, Any]] = {}
        self._session_tool_allowlist: set[tuple[str, str]] = set()
        self._external_hook_status: dict[str, Any] = {"state": "disabled", "detail": ""}
        self._external_hook_sessions: dict[str, dict[str, Any]] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def auth_ready(self) -> bool | None:
        return self._auth_ready

    @property
    def auth_method(self) -> str:
        return self._auth_method

    @property
    def readiness(self) -> dict[str, Any] | None:
        return dict(self._readiness) if isinstance(self._readiness, dict) else None

    def set_cached_readiness_for_tests(self, readiness: dict[str, Any] | None) -> None:
        self._set_readiness(readiness)

    def _set_readiness(self, readiness: dict[str, Any] | None) -> None:
        self._readiness = dict(readiness) if isinstance(readiness, dict) else None
        if not isinstance(self._readiness, dict):
            self._auth_ready = None
            self._auth_method = ""
            return
        self._auth_ready = bool(self._readiness.get("ready"))
        self._auth_method = str(self._readiness.get("authMethod") or "")

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

    def _fallback_external_workspace_id(self, payload: dict[str, Any]) -> str:
        cwd = _hook_cwd(payload)
        if cwd:
            return f"claude:{cwd}"
        session_id = _hook_session_id(payload)
        if session_id:
            return f"claude:external:{session_id}"
        return "claude:external"

    def _send_lock_for_thread(self, thread_id: str) -> asyncio.Lock:
        lock = self._send_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._send_locks[thread_id] = lock
        return lock

    @property
    def hook_socket_path(self) -> str | None:
        return self._hook_socket_path

    @property
    def hook_settings_path(self) -> str | None:
        return self._hook_settings_path

    @property
    def external_hook_status(self) -> dict[str, Any]:
        return dict(self._external_hook_status)

    def _set_external_hook_status(self, state: str, detail: str = "", **extra: Any) -> None:
        status = {
            "state": str(state or "").strip() or "disabled",
            "detail": str(detail or "").strip(),
        }
        status.update(extra)
        self._external_hook_status = status

    def configure_hook_bridge(
        self,
        data_dir: str,
        *,
        global_settings_path: str | None = None,
    ) -> None:
        self._hook_data_dir = data_dir
        if global_settings_path is not None:
            self._global_hook_settings_path = global_settings_path

    async def install_external_hook_ingress(self) -> dict[str, Any]:
        if not self._hook_data_dir:
            self._set_external_hook_status("disabled", "缺少 data_dir，未安装 Claude external hook ingress")
            return dict(self._external_hook_status)
        result = install_onlineworker_claude_hooks(
            self._hook_data_dir,
            settings_path=self._global_hook_settings_path,
        )
        self._set_external_hook_status(
            result.get("state") or "disabled",
            str(result.get("detail") or ""),
            settingsPath=result.get("settingsPath") or "",
            installedEvents=list(result.get("installedEvents") or []),
            changed=bool(result.get("changed")),
        )
        return dict(self._external_hook_status)

    async def uninstall_external_hook_ingress(self) -> dict[str, Any]:
        result = uninstall_onlineworker_claude_hooks(
            settings_path=self._global_hook_settings_path,
        )
        self._set_external_hook_status(
            result.get("state") or "disabled",
            str(result.get("detail") or ""),
            settingsPath=result.get("settingsPath") or "",
            removedEvents=list(result.get("removedEvents") or []),
            changed=bool(result.get("changed")),
        )
        return dict(self._external_hook_status)

    async def _ensure_hook_bridge_started(self) -> None:
        if self._hook_server is not None:
            return
        if not self._hook_data_dir:
            return
        await self.start_hook_bridge(self._hook_data_dir)

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
        self._external_hook_sessions.clear()

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
            raw = await reader.read(1024 * 1024)
            response: dict[str, Any] = {}
            if raw:
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    managed_interactions = payload.pop(ONLINEWORKER_MANAGED_HOOK_PAYLOAD_KEY, False) is True
                    if managed_interactions:
                        response = await self.handle_hook_payload(
                            payload,
                            managed_interactions=True,
                        )
                    else:
                        asyncio.create_task(
                            self.handle_hook_payload(
                                payload,
                                managed_interactions=False,
                            )
                        )
            try:
                writer.write(json.dumps(response or {}, ensure_ascii=False).encode("utf-8"))
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[claude-hook-bridge] hook client disconnected before response flush")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[claude-hook-bridge] hook client disconnected during close")

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

    async def handle_hook_payload(
        self,
        payload: dict[str, Any],
        *,
        managed_interactions: bool = False,
    ) -> dict[str, Any]:
        if not managed_interactions and _hook_event_name(payload) == "PostToolUse":
            return await self._mirror_external_tool_hook_payload(payload, completed=True)
        if not managed_interactions and _hook_event_name(payload) == "PreToolUse":
            if _hook_is_interactive_request(payload):
                return await self._mirror_external_interactive_hook_payload(payload)
            return await self._mirror_external_tool_hook_payload(payload, completed=False)
        if _hook_is_lifecycle_event(payload):
            return await self._handle_lifecycle_hook_payload(payload)
        if _hook_is_interactive_request(payload) and not managed_interactions:
            return await self._mirror_external_interactive_hook_payload(payload)
        if _hook_is_ask_user_question(payload):
            return await self._handle_ask_user_question_payload(payload)
        if _hook_is_tool_approval_request(payload):
            return await self._handle_permission_request_payload(payload)
        if _hook_is_notification_question(payload):
            return await self._handle_notification_question_payload(payload)
        return {}

    def _resolve_hook_title_prompt(self, payload: dict[str, Any]) -> str:
        prompt_text = _hook_user_prompt(payload)
        if prompt_text:
            return prompt_text

        session_id = _hook_session_id(payload)
        if session_id:
            session_state = self._external_hook_sessions.get(session_id) or {}
            prompt_text = str(session_state.get("last_prompt") or "").strip()
            if prompt_text:
                return prompt_text

        transcript_file = self._resolve_hook_transcript_file(payload)
        if transcript_file:
            for turn in reversed(_read_claude_project_turns(transcript_file)):
                if str(turn.get("role") or "").strip() != "user":
                    continue
                text = str(turn.get("text") or "").strip()
                if text:
                    return text
        return ""

    async def _mirror_external_interactive_hook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._event_callbacks:
            self._set_external_hook_status("callback_unreachable", "Claude interactive hook 没有可用的事件回调")
            return {}

        workspace_id = self._resolve_hook_workspace_id(payload)
        if not workspace_id:
            detail = f"未匹配 Claude workspace：{_hook_cwd(payload) or _hook_session_id(payload)}"
            self._set_external_hook_status("degraded_fallback", detail)
            workspace_id = self._fallback_external_workspace_id(payload)

        thread_id = _hook_session_id(payload)
        if not thread_id:
            self._set_external_hook_status("degraded_fallback", "Claude interactive hook 缺少 session_id")
            return {}

        async with self._send_lock_for_thread(thread_id):
            self._thread_workspace_map[thread_id] = workspace_id
            state = self._external_hook_session_state(thread_id)
            state["workspace_id"] = workspace_id
            prompt_text = self._resolve_hook_title_prompt(payload)
            if prompt_text:
                state["last_prompt"] = prompt_text
            transcript_file = self._resolve_hook_transcript_file(payload)
            if transcript_file:
                state["transcript_path"] = transcript_file

            if not state.get("session_created_emitted"):
                await self._emit_hook_session_created(
                    workspace_id,
                    thread_id,
                    title=prompt_text[:120],
                )
                state["session_created_emitted"] = True

            if _hook_is_tool_approval_request(payload):
                command, reason = _hook_permission_display(payload)
                await self._emit_event(
                    workspace_id,
                    "item/commandExecution/requestApproval",
                    {
                        "threadId": thread_id,
                        "command": command,
                        "reason": reason,
                        "request_id": str(payload.get("request_id") or payload.get("id") or uuid.uuid4()),
                        "_provider": "claude",
                        "_claude_permission": True,
                        "_mirroredOnly": True,
                        "toolName": _normalize_hook_tool_name(payload),
                        "prompt": prompt_text,
                    },
                )
            elif _hook_is_ask_user_question(payload):
                tool_input = _normalize_hook_tool_input(payload)
                questions = tool_input.get("questions") if isinstance(tool_input.get("questions"), list) else []
                question_id = str(payload.get("question_id") or payload.get("request_id") or payload.get("id") or uuid.uuid4())
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
                            "_provider": "claude",
                            "_mirroredOnly": True,
                            "prompt": prompt_text,
                        },
                    )
            elif _hook_is_notification_question(payload):
                await self._emit_event(
                    workspace_id,
                    "question/asked",
                    {
                        "threadId": thread_id,
                        "questionId": str(payload.get("question_id") or payload.get("request_id") or payload.get("id") or uuid.uuid4()),
                        "header": "",
                        "question": str(payload.get("question") or ""),
                        "options": _hook_extract_option_rows(payload.get("options")),
                        "multiple": False,
                        "custom": True,
                        "_provider": "claude",
                        "_mirroredOnly": True,
                        "prompt": prompt_text,
                    },
                )
            self._set_external_hook_status("installed")
        return {}

    async def _mirror_external_tool_hook_payload(self, payload: dict[str, Any], *, completed: bool) -> dict[str, Any]:
        if not self._event_callbacks:
            self._set_external_hook_status("callback_unreachable", "Claude tool hook 没有可用的事件回调")
            return {}

        workspace_id = self._resolve_hook_workspace_id(payload)
        if not workspace_id:
            detail = f"未匹配 Claude workspace：{_hook_cwd(payload) or _hook_session_id(payload)}"
            self._set_external_hook_status("degraded_fallback", detail)
            workspace_id = self._fallback_external_workspace_id(payload)

        thread_id = _hook_session_id(payload)
        if not thread_id:
            self._set_external_hook_status("degraded_fallback", "Claude tool hook 缺少 session_id")
            return {}

        async with self._send_lock_for_thread(thread_id):
            self._thread_workspace_map[thread_id] = workspace_id
            state = self._external_hook_session_state(thread_id)
            state["workspace_id"] = workspace_id
            prompt_text = self._resolve_hook_title_prompt(payload)
            if prompt_text:
                state["last_prompt"] = prompt_text
            transcript_file = self._resolve_hook_transcript_file(payload)
            if transcript_file:
                state["transcript_path"] = transcript_file

            if not state.get("session_created_emitted"):
                await self._emit_hook_session_created(
                    workspace_id,
                    thread_id,
                    title=prompt_text[:120],
                )
                state["session_created_emitted"] = True

            display = _hook_tool_activity_display(payload)
            item = {
                "type": "shellCommand" if _normalize_hook_tool_name(payload) == "Bash" else "toolCall",
                "text": display,
                "command": display,
                "threadId": thread_id,
                "toolName": _normalize_hook_tool_name(payload),
            }
            await self._emit_event(
                workspace_id,
                "item/completed" if completed else "item/started",
                {
                    "threadId": thread_id,
                    "item": item,
                    "_provider": "claude",
                    "_mirroredOnly": True,
                    "prompt": prompt_text,
                },
            )
            self._set_external_hook_status("installed")
        return {}

    def _external_hook_session_state(self, session_id: str) -> dict[str, Any]:
        return self._external_hook_sessions.setdefault(session_id, {})

    def _is_managed_hook_session(self, session_id: str) -> bool:
        return session_id in self._active_processes

    def _resolve_hook_transcript_file(self, payload: dict[str, Any]) -> str:
        transcript_path = _hook_transcript_path(payload)
        if transcript_path and os.path.exists(transcript_path):
            return transcript_path
        session_id = _hook_session_id(payload)
        if not session_id:
            return ""
        session_file = _find_claude_project_session_file(session_id)
        return session_file or ""

    def _read_hook_final_assistant_text(self, payload: dict[str, Any]) -> str:
        transcript_file = self._resolve_hook_transcript_file(payload)
        if not transcript_file:
            return ""
        turns = _read_claude_project_turns(transcript_file)
        for turn in reversed(turns):
            if str(turn.get("role") or "").strip() != "assistant":
                continue
            text = str(turn.get("text") or "").strip()
            if text:
                return text
        return ""

    async def _emit_hook_session_created(
        self,
        workspace_id: str,
        session_id: str,
        *,
        title: str = "",
    ) -> None:
        params: dict[str, Any] = {"threadId": session_id}
        if title:
            params["title"] = title
        await self._emit_event(workspace_id, "session.created", params)

    async def _handle_lifecycle_hook_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_name = _hook_event_name(payload)
        if event_name == "PostToolUse":
            return {}

        session_id = _hook_session_id(payload)
        if not session_id:
            self._set_external_hook_status("degraded_fallback", "Claude lifecycle hook 缺少 session_id")
            return {}
        if self._is_managed_hook_session(session_id):
            return {}
        if not self._event_callbacks:
            self._set_external_hook_status("callback_unreachable", "Claude lifecycle hook 没有可用的事件回调")
            return {}

        workspace_id = self._resolve_hook_workspace_id(payload)
        if not workspace_id:
            detail = f"未匹配 Claude workspace：{_hook_cwd(payload) or session_id}"
            self._set_external_hook_status("degraded_fallback", detail)
            workspace_id = self._fallback_external_workspace_id(payload)
        async with self._send_lock_for_thread(session_id):
            self._thread_workspace_map[session_id] = workspace_id
            state = self._external_hook_session_state(session_id)
            state["workspace_id"] = workspace_id
            transcript_file = self._resolve_hook_transcript_file(payload)
            if transcript_file:
                state["transcript_path"] = transcript_file

            if event_name == "SessionStart":
                if not state.get("session_created_emitted"):
                    await self._emit_hook_session_created(workspace_id, session_id)
                    state["session_created_emitted"] = True
                self._set_external_hook_status("installed")
                return {}

            if event_name == "UserPromptSubmit":
                prompt_text = _hook_user_prompt(payload)
                if not state.get("session_created_emitted"):
                    await self._emit_hook_session_created(
                        workspace_id,
                        session_id,
                        title=prompt_text[:120],
                    )
                    state["session_created_emitted"] = True
                if (
                    state.get("turn_open")
                    and state.get("last_prompt") == prompt_text
                    and state.get("transcript_path") == transcript_file
                ):
                    return {}
                turn_id = str(uuid.uuid4())
                state["turn_id"] = turn_id
                state["turn_open"] = True
                state["last_prompt"] = prompt_text
                state.pop("terminal_emitted_turn_id", None)
                if prompt_text:
                    await self._emit_event(
                        workspace_id,
                        "message.user.submitted",
                        {
                            "threadId": session_id,
                            "text": prompt_text,
                        },
                    )
                await self._emit_event(
                    workspace_id,
                    "turn/started",
                    {
                        "threadId": session_id,
                        "turn": {
                            "id": turn_id,
                            "threadId": session_id,
                        },
                    },
                )
                self._set_external_hook_status("installed")
                return {}

            if event_name in {"Stop", "SessionEnd"}:
                turn_id = str(state.get("turn_id") or "").strip() or str(uuid.uuid4())
                if (
                    not state.get("turn_open")
                    and str(state.get("terminal_emitted_turn_id") or "").strip() == turn_id
                ):
                    return {}
                failure_text = _hook_failure_text(payload)
                if failure_text:
                    state["turn_open"] = False
                    state["terminal_emitted_turn_id"] = turn_id
                    await self._emit_event(
                        workspace_id,
                        "turn.failed",
                        {
                            "threadId": session_id,
                            "turnId": turn_id,
                            "error": failure_text,
                            "reason": failure_text,
                        },
                    )
                    self._set_external_hook_status("degraded_fallback", failure_text)
                    return {}

                final_text = self._read_hook_final_assistant_text(payload)
                if final_text:
                    await self._emit_event(
                        workspace_id,
                        "item/completed",
                        {
                            "threadId": session_id,
                            "turnId": turn_id,
                            "item": {
                                "type": "agentMessage",
                                "text": final_text,
                                "phase": "final_answer",
                                "threadId": session_id,
                                "turn": {"id": turn_id},
                            },
                        },
                    )
                else:
                    detail = f"{event_name} 未读取到 assistant final，已退化为仅补发 turn.completed"
                    self._set_external_hook_status("degraded_fallback", detail)
                await self._emit_event(
                    workspace_id,
                    "turn/completed",
                    {
                        "threadId": session_id,
                        "turn": {
                            "id": turn_id,
                            "threadId": session_id,
                            "status": "completed",
                        },
                    },
                )
                state["turn_id"] = turn_id
                state["turn_open"] = False
                state["terminal_emitted_turn_id"] = turn_id
                if final_text:
                    self._set_external_hook_status("installed")
                return {}

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
        prompt_text = ""
        if thread_id:
            session_state = self._external_hook_sessions.get(thread_id) or {}
            prompt_text = str(session_state.get("last_prompt") or "").strip()
        if not prompt_text:
            prompt_text = _hook_user_prompt(payload)
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
                    "prompt": prompt_text,
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

    def _build_claude_env(self) -> dict[str, str]:
        env = dict(os.environ)
        runtime_env = _detect_claude_runtime_env(env)
        for key in PARENT_SESSION_ENV_VARS:
            env.pop(key, None)
        for key in tuple(env.keys()):
            if key.startswith("CODEX_"):
                env.pop(key, None)
            elif key.upper().startswith("ANTHROPIC_"):
                env.pop(key, None)
        env.update(runtime_env)
        if (
            env.get("ANTHROPIC_BASE_URL")
            and not str(env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
            and not str(env.get("ANTHROPIC_API_KEY") or "").strip()
        ):
            env["ANTHROPIC_API_KEY"] = "dummy"

        preferred_node_bin = resolve_preferred_node_bin_dir()
        required_path_entries = [
            entry
            for entry in (
                preferred_node_bin,
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            )
            if entry
        ]
        current_path = str(env.get("PATH") or "")
        path_entries = [entry for entry in current_path.split(os.pathsep) if entry]
        merged_path_entries = []
        for entry in [*required_path_entries, *path_entries]:
            if entry not in merged_path_entries:
                merged_path_entries.append(entry)
        if merged_path_entries:
            env["PATH"] = os.pathsep.join(merged_path_entries)
        if preferred_node_bin:
            env["NVM_BIN"] = preferred_node_bin
        return env

    def _build_send_argv(self, thread_id: str, text: str) -> list[str]:
        base_args = [
            *self._claude_command_prefix,
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

    async def check_readiness(self, *, force: bool = False) -> dict[str, Any]:
        if not force and isinstance(self._readiness, dict):
            return dict(self._readiness)

        raw_runtime_env = _collect_claude_runtime_env()
        runtime_readiness = _readiness_from_runtime_env(raw_runtime_env)
        readiness = await self._check_launch_methods_readiness(runtime_readiness)
        self._set_readiness(readiness)
        return dict(readiness)

    async def refresh_auth_status(self) -> dict:
        readiness = await self.check_readiness(force=True)
        legacy = _readiness_to_legacy_auth_status(readiness)
        if "apiProvider" in readiness:
            legacy["apiProvider"] = readiness["apiProvider"]
        if not readiness.get("ready"):
            legacy["reason"] = readiness.get("reason")
            legacy["detail"] = readiness.get("detail")
        return legacy

    async def _check_cli_readiness_for_prefix(self, prefix: list[str]) -> dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *prefix,
                "auth",
                "status",
                env=self._build_claude_env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=CLAUDE_STREAM_BUFFER_LIMIT,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as e:
            return _new_claude_readiness(
                ready=False,
                source="missingCli",
                reason="missingCli",
                detail=str(e) or CLAUDE_REASON_DETAILS["missingCli"],
            )
        except Exception as e:
            logger.warning(f"读取 Claude auth 状态失败：{e}")
            return _new_claude_readiness(
                ready=False,
                source="cliAuth",
                reason="authStatusFailed",
                detail=str(e) or CLAUDE_REASON_DETAILS["authStatusFailed"],
            )

        out_text = _to_text(stdout).strip()
        err_text = _to_text(stderr).strip()
        payload = out_text or err_text
        if not payload:
            return _new_claude_readiness(
                ready=False,
                source="cliAuth",
                reason="emptyAuthStatus",
            )

        try:
            status = json.loads(payload)
        except Exception:
            payload_lower = payload.lower()
            if "not logged in" in payload_lower or "please run /login" in payload_lower:
                return _new_claude_readiness(
                    ready=False,
                    source="cliAuth",
                    reason="loggedOut",
                    auth_method="none",
                    detail=payload,
                )
            if "logged in" in payload_lower or "authenticated" in payload_lower:
                return _new_claude_readiness(
                    ready=True,
                    source="cliAuth",
                    reason="ok",
                    detail=CLAUDE_REASON_DETAILS["ok"],
                )
            return _new_claude_readiness(
                ready=False,
                source="cliAuth",
                reason="unknownAuthStatus",
            )

        if isinstance(status, dict):
            logged_in = bool(status.get("loggedIn"))
            auth_method = str(status.get("authMethod") or "")
            return _new_claude_readiness(
                ready=logged_in,
                source="cliAuth",
                reason="ok" if logged_in else "loggedOut",
                auth_method=auth_method,
                detail=CLAUDE_REASON_DETAILS["ok"] if logged_in else CLAUDE_REASON_DETAILS["loggedOut"],
                raw_status=status,
            )

        return _new_claude_readiness(
            ready=False,
            source="cliAuth",
            reason="unknownAuthStatus",
        )

    async def _check_launch_methods_readiness(
        self,
        runtime_readiness: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if runtime_readiness is not None and runtime_readiness.get("ready"):
            method_statuses: list[dict[str, Any]] = []
            first_missing: dict[str, Any] | None = None
            first_method: dict[str, str] | None = None
            for method in self._launch_methods:
                prefix = resolve_claude_command_prefix(method["bin"])
                available, detail = _command_prefix_available(prefix)
                readiness = (
                    _new_claude_readiness(
                        ready=True,
                        source="runtimeEnv",
                        reason="ok",
                        auth_method=str(runtime_readiness.get("authMethod") or ""),
                        detail=runtime_readiness.get("detail"),
                    )
                    if available
                    else _missing_cli_readiness(detail)
                )
                if first_missing is None:
                    first_missing = readiness
                    first_method = method
                if available:
                    self._claude_command_prefix = prefix
                    self.claude_bin = prefix[0]
                    method_statuses.append(
                        _cli_method_status(
                            method,
                            prefix,
                            readiness,
                            selected=True,
                            available_override=True,
                            reason_override="runtimeEnv",
                            detail_override=str(runtime_readiness.get("detail") or ""),
                        )
                    )
                    return _attach_launch_method_readiness(
                        runtime_readiness,
                        method_statuses,
                        method,
                    )
                method_statuses.append(_cli_method_status(method, prefix, readiness))

            return _attach_launch_method_readiness(
                first_missing or _missing_cli_readiness(),
                method_statuses,
                first_method,
            )

        method_statuses: list[dict[str, Any]] = []
        first_cli_readiness: dict[str, Any] | None = None
        first_cli_method: dict[str, str] | None = None

        for method in self._launch_methods:
            prefix = resolve_claude_command_prefix(method["bin"])
            readiness = await self._check_cli_readiness_for_prefix(prefix)
            if first_cli_readiness is None:
                first_cli_readiness = readiness
                first_cli_method = method

            if readiness.get("ready"):
                self._claude_command_prefix = prefix
                self.claude_bin = prefix[0]
                method_statuses.append(
                    _cli_method_status(
                        method,
                        prefix,
                        readiness,
                        selected=True,
                    )
                )
                return _attach_launch_method_readiness(
                    readiness,
                    method_statuses,
                    method,
                )

            method_statuses.append(_cli_method_status(method, prefix, readiness))

        if first_cli_method is not None:
            for method_status in method_statuses:
                if method_status.get("id") == first_cli_method.get("id"):
                    method_status["selected"] = True
                    break

        if runtime_readiness is not None:
            return _attach_launch_method_readiness(
                runtime_readiness,
                method_statuses,
                None,
            )

        fallback = first_cli_readiness or _new_claude_readiness(
            ready=False,
            source="missingCli",
            reason="missingCli",
            detail=CLAUDE_REASON_DETAILS["missingCli"],
        )
        return _attach_launch_method_readiness(fallback, method_statuses, first_cli_method)

    async def _ensure_ready_for_send(self) -> dict[str, Any]:
        readiness = await self.check_readiness(force=True)
        if not readiness.get("ready"):
            raise ClaudeProviderUnavailable(readiness)
        return readiness

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
        raise RuntimeError("Claude provider does not expose a real source archive operation yet.")

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

    def _render_text_with_attachments(
        self,
        text: str,
        attachments: list[dict[str, Any]] | None,
    ) -> str:
        normalized: list[dict[str, str]] = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            kind = str(item.get("kind") or "file").strip().lower()
            normalized.append(
                {
                    "kind": "image" if kind == "image" else "file",
                    "path": path,
                    "name": str(item.get("name") or "").strip(),
                    "mime_type": str(item.get("mime_type") or "").strip(),
                }
            )
        if not normalized:
            return text

        lines = [
            "用户附带了以下本地附件。请按需读取这些路径，并基于附件内容回答。",
            "",
        ]
        for index, item in enumerate(normalized, start=1):
            label = "图片" if item["kind"] == "image" else "文件"
            lines.append(f"{index}. {label}")
            lines.append(f"   - path: {item['path']}")
            if item["name"]:
                lines.append(f"   - name: {item['name']}")
            if item["mime_type"]:
                lines.append(f"   - mime_type: {item['mime_type']}")
            lines.append("")

        user_text = str(text or "").strip()
        lines.append("用户消息：")
        lines.append(user_text or "请根据以上附件进行处理。")
        return "\n".join(lines).strip()

    async def send_user_message(
        self,
        workspace_id: str,
        thread_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict:
        if not self._connected:
            raise RuntimeError("Claude 未连接")

        cwd = self._workspace_cwd_map.get(workspace_id)
        if not cwd:
            raise RuntimeError("Claude workspace 未注册 cwd")
        if not os.path.isdir(cwd):
            raise RuntimeError(f"Claude workspace cwd 不存在：{cwd}")

        try:
            await self._ensure_ready_for_send()
        except ClaudeProviderUnavailable as e:
            return {
                "threadId": thread_id,
                "turnId": "",
                "status": "error",
                "error": str(e),
                "readiness": e.readiness,
            }

        await self._ensure_hook_bridge_started()
        self._thread_workspace_map[thread_id] = workspace_id
        rendered_text = self._render_text_with_attachments(text, attachments)

        async with self._send_lock_for_thread(thread_id):
            turn_id = str(uuid.uuid4())

            await self._emit_event(
                workspace_id,
                "turn/started",
                {
                    "threadId": thread_id,
                    "turn": {"id": turn_id, "threadId": thread_id},
                },
            )

            return await self._send_user_message_once(
                workspace_id,
                thread_id,
                rendered_text,
                turn_id,
                cwd,
            )

    async def _send_user_message_once(
        self,
        workspace_id: str,
        thread_id: str,
        text: str,
        turn_id: str,
        cwd: str,
    ) -> dict:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self._build_send_argv(thread_id, text),
                cwd=cwd,
                env=self._build_claude_env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=CLAUDE_STREAM_BUFFER_LIMIT,
            )
        except Exception as e:
            error_text = str(e)
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
