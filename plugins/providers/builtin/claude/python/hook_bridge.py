from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from typing import Any


CLAUDE_HOOK_SOCKET_FILENAME = "claude_hook_bridge.sock"
CLAUDE_HOOK_SETTINGS_FILENAME = "claude_hook_settings.json"
CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS = 86400
CLAUDE_PRETOOL_APPROVAL_MATCHER = "Bash|Edit|Write|AskUserQuestion|ExitPlanMode"


def claude_hook_socket_path(data_dir: str | None) -> str | None:
    if not data_dir:
        return None
    normalized = os.path.abspath(data_dir)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    socket_dir = "/tmp" if os.path.isdir("/tmp") else tempfile.gettempdir()
    return os.path.join(socket_dir, f"ow-claude-{digest}.sock")


def claude_hook_settings_path(data_dir: str | None) -> str | None:
    if not data_dir:
        return None
    return os.path.join(data_dir, CLAUDE_HOOK_SETTINGS_FILENAME)


def build_claude_hook_command(data_dir: str) -> str:
    if getattr(sys, "frozen", False):
        argv = [
            sys.executable,
            "--claude-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    else:
        main_py = str(Path(__file__).resolve().parents[5] / "main.py")
        argv = [
            sys.executable,
            main_py,
            "--claude-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    return " ".join(shlex.quote(str(item)) for item in argv)


def write_claude_hook_settings(data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    settings_path = claude_hook_settings_path(data_dir)
    if settings_path is None:
        raise RuntimeError("缺少 data_dir，无法写入 Claude hook settings")

    command = build_claude_hook_command(data_dir)
    hook_entry = {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS,
            }
        ],
    }
    pretool_entry = {
        "matcher": CLAUDE_PRETOOL_APPROVAL_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS,
            }
        ],
    }
    payload = {
        "hooks": {
            "PreToolUse": [pretool_entry],
            "PermissionRequest": [hook_entry],
            "Notification": [hook_entry],
        }
    }
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return settings_path


def default_claude_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    event_name = str(payload.get("hook_event_name") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()

    if event_name == "PreToolUse" and tool_name in {
        "AskUserQuestion",
        "Bash",
        "Edit",
        "Write",
        "ExitPlanMode",
    }:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
            }
        }

    if event_name == "PermissionRequest":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                },
            }
        }

    if event_name == "Notification" and payload.get("question"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "Notification",
            }
        }

    if tool_name == "AskUserQuestion":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PermissionRequest",
                "decision": {
                    "behavior": "deny",
                },
            }
        }

    return {}


async def relay_claude_hook_payload(
    data_dir: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    socket_path = claude_hook_socket_path(data_dir)
    if not socket_path:
        return default_claude_hook_response(payload)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except Exception:
        return default_claude_hook_response(payload)

    try:
        writer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        await writer.drain()
        writer.write_eof()
        raw = await reader.read()
    except Exception:
        return default_claude_hook_response(payload)
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


def run_claude_hook_bridge_once(data_dir: str | None) -> int:
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

    response = asyncio.run(relay_claude_hook_payload(data_dir, payload))
    sys.stdout.write(json.dumps(response or {}, ensure_ascii=False))
    sys.stdout.flush()
    return 0
