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
CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS = 5
CLAUDE_PRETOOL_APPROVAL_MATCHER = "Bash|Edit|Write|AskUserQuestion|ExitPlanMode"
ONLINEWORKER_CLAUDE_HOOK_MARKER = "onlineworker_claude_external_ingress_v1"


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


def default_claude_settings_path(settings_path: str | None = None) -> str:
    target = settings_path or "~/.claude/settings.json"
    return os.path.abspath(os.path.expanduser(target))


def _onlineworker_hook_specs(*, include_lifecycle: bool) -> list[dict[str, Any]]:
    specs = [
        {
            "event": "PreToolUse",
            "matcher": CLAUDE_PRETOOL_APPROVAL_MATCHER,
            "timeout": CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS,
        },
        {
            "event": "PermissionRequest",
            "matcher": "",
            "timeout": CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS,
        },
        {
            "event": "Notification",
            "matcher": "",
            "timeout": CLAUDE_BLOCKING_HOOK_TIMEOUT_SECONDS,
        },
    ]
    if include_lifecycle:
        specs.extend(
            [
                {
                    "event": "PostToolUse",
                    "matcher": "",
                    "timeout": CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS,
                },
                {
                    "event": "SessionStart",
                    "matcher": "",
                    "timeout": CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS,
                },
                {
                    "event": "Stop",
                    "matcher": "",
                    "timeout": CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS,
                },
                {
                    "event": "SessionEnd",
                    "matcher": "",
                    "timeout": CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS,
                },
                {
                    "event": "UserPromptSubmit",
                    "matcher": "",
                    "timeout": CLAUDE_NON_BLOCKING_HOOK_TIMEOUT_SECONDS,
                },
            ]
        )
    return specs


def _build_onlineworker_hook_entry(
    command: str,
    *,
    matcher: str,
    timeout: int,
    include_marker: bool,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "matcher": matcher,
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": timeout,
            }
        ],
    }
    if include_marker:
        entry["onlineworkerMarker"] = ONLINEWORKER_CLAUDE_HOOK_MARKER
    return entry


def build_onlineworker_claude_hook_settings(
    command: str,
    *,
    include_lifecycle: bool,
    include_marker: bool,
) -> dict[str, Any]:
    hooks: dict[str, list[dict[str, Any]]] = {}
    for spec in _onlineworker_hook_specs(include_lifecycle=include_lifecycle):
        hooks[spec["event"]] = [
            _build_onlineworker_hook_entry(
                command,
                matcher=str(spec.get("matcher") or ""),
                timeout=int(spec.get("timeout") or 0),
                include_marker=include_marker,
            )
        ]
    return {"hooks": hooks}


def _is_onlineworker_marker_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    return str(entry.get("onlineworkerMarker") or "").strip() == ONLINEWORKER_CLAUDE_HOOK_MARKER


def _load_claude_settings_payload(settings_path: str) -> tuple[dict[str, Any] | None, str]:
    if not os.path.exists(settings_path):
        return {}, ""
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError as exc:
        return None, f"Claude settings JSON 无法解析：{exc}"
    except Exception as exc:
        return None, f"读取 Claude settings 失败：{exc}"
    if not isinstance(payload, dict):
        return None, "Claude settings 根对象不是 JSON object"
    return payload, ""


def _persist_claude_settings_payload(settings_path: str, payload: dict[str, Any]) -> None:
    parent = os.path.dirname(settings_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def install_onlineworker_claude_hooks(
    data_dir: str,
    *,
    settings_path: str | None = None,
) -> dict[str, Any]:
    resolved_settings_path = default_claude_settings_path(settings_path)
    existed_before = os.path.exists(resolved_settings_path)
    payload, error = _load_claude_settings_payload(resolved_settings_path)
    if payload is None:
        return {
            "state": "install_failed",
            "settingsPath": resolved_settings_path,
            "detail": error,
            "installedEvents": [],
            "changed": False,
        }

    hooks = payload.get("hooks")
    if hooks is None:
        hooks = {}
        payload["hooks"] = hooks
    if not isinstance(hooks, dict):
        return {
            "state": "install_failed",
            "settingsPath": resolved_settings_path,
            "detail": "Claude settings 的 hooks 字段不是 object",
            "installedEvents": [],
            "changed": False,
        }

    command = build_claude_hook_command(data_dir)
    desired_payload = build_onlineworker_claude_hook_settings(
        command,
        include_lifecycle=True,
        include_marker=True,
    )
    desired_hooks = desired_payload["hooks"]
    changed = False
    installed_events: list[str] = []
    for event_name, desired_entries in desired_hooks.items():
        current_entries = hooks.get(event_name)
        if current_entries is None:
            current_entries = []
        if not isinstance(current_entries, list):
            return {
                "state": "install_failed",
                "settingsPath": resolved_settings_path,
                "detail": f"Claude settings hooks.{event_name} 不是数组",
                "installedEvents": installed_events,
                "changed": changed,
            }
        filtered_entries = [
            entry for entry in current_entries if not _is_onlineworker_marker_entry(entry)
        ]
        merged_entries = [*filtered_entries, *desired_entries]
        if current_entries != merged_entries:
            hooks[event_name] = merged_entries
            changed = True
        installed_events.append(event_name)

    if changed or not existed_before:
        _persist_claude_settings_payload(resolved_settings_path, payload)
    return {
        "state": "installed",
        "settingsPath": resolved_settings_path,
        "detail": "",
        "installedEvents": installed_events,
        "changed": changed or not existed_before,
    }


def uninstall_onlineworker_claude_hooks(
    *,
    settings_path: str | None = None,
) -> dict[str, Any]:
    resolved_settings_path = default_claude_settings_path(settings_path)
    payload, error = _load_claude_settings_payload(resolved_settings_path)
    if payload is None:
        return {
            "state": "install_failed",
            "settingsPath": resolved_settings_path,
            "detail": error,
            "removedEvents": [],
            "changed": False,
        }
    if not payload:
        return {
            "state": "disabled",
            "settingsPath": resolved_settings_path,
            "detail": "",
            "removedEvents": [],
            "changed": False,
        }

    hooks = payload.get("hooks")
    if hooks is None:
        return {
            "state": "disabled",
            "settingsPath": resolved_settings_path,
            "detail": "",
            "removedEvents": [],
            "changed": False,
        }
    if not isinstance(hooks, dict):
        return {
            "state": "install_failed",
            "settingsPath": resolved_settings_path,
            "detail": "Claude settings 的 hooks 字段不是 object",
            "removedEvents": [],
            "changed": False,
        }

    changed = False
    removed_events: list[str] = []
    for event_name, current_entries in list(hooks.items()):
        if not isinstance(current_entries, list):
            return {
                "state": "install_failed",
                "settingsPath": resolved_settings_path,
                "detail": f"Claude settings hooks.{event_name} 不是数组",
                "removedEvents": removed_events,
                "changed": changed,
            }
        filtered_entries = [
            entry for entry in current_entries if not _is_onlineworker_marker_entry(entry)
        ]
        if len(filtered_entries) != len(current_entries):
            removed_events.append(event_name)
            changed = True
            if filtered_entries:
                hooks[event_name] = filtered_entries
            else:
                hooks.pop(event_name, None)

    if changed:
        if not hooks:
            payload.pop("hooks", None)
        _persist_claude_settings_payload(resolved_settings_path, payload)
    return {
        "state": "disabled",
        "settingsPath": resolved_settings_path,
        "detail": "",
        "removedEvents": removed_events,
        "changed": changed,
    }


def write_claude_hook_settings(data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    settings_path = claude_hook_settings_path(data_dir)
    if settings_path is None:
        raise RuntimeError("缺少 data_dir，无法写入 Claude hook settings")

    command = build_claude_hook_command(data_dir)
    payload = build_onlineworker_claude_hook_settings(
        command,
        include_lifecycle=False,
        include_marker=False,
    )
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return settings_path


def default_claude_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    event_name = str(payload.get("hook_event_name") or "").strip()
    tool_name = str(payload.get("tool_name") or "").strip()

    if event_name == "PreToolUse" and tool_name == "AskUserQuestion":
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
