from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib
from typing import Any

from core.provider_owner_bridge import provider_owner_bridge_socket_path


CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"
CODEX_EXTERNAL_EVENT_HOOK_NAMES = ("SessionStart", "UserPromptSubmit", "Stop")
CODEX_HOOK_RELAY_TIMEOUT_SECONDS = 2.0
ONLINEWORKER_CODEX_HOOK_MARKER = "--codex-hook-bridge"
ONLINEWORKER_CODEX_NOTIFY_MARKER = "--codex-notify-bridge"
CODEX_NOTIFY_FORWARD_FILENAME = "codex_notify_forward.json"


def _codex_hook_command(data_dir: str) -> str:
    if getattr(sys, "frozen", False):
        argv = [
            sys.executable,
            "--codex-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    else:
        main_py = str(Path(__file__).resolve().parents[5] / "main.py")
        argv = [
            sys.executable,
            main_py,
            "--codex-hook-bridge",
            "--data-dir",
            data_dir,
        ]
    return " ".join(shlex.quote(str(item)) for item in argv)


def _codex_notify_argv(data_dir: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [
            sys.executable,
            "--codex-notify-bridge",
            "--data-dir",
            data_dir,
        ]
    main_py = str(Path(__file__).resolve().parents[5] / "main.py")
    return [
        sys.executable,
        main_py,
        "--codex-notify-bridge",
        "--data-dir",
        data_dir,
    ]


def _default_codex_config_path(config_path: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(config_path or "~/.codex/config.toml"))


def _default_codex_notify_forward_path(
    data_dir: str,
    forward_path: str | None = None,
) -> str:
    return os.path.abspath(
        os.path.expanduser(
            forward_path or os.path.join(data_dir, CODEX_NOTIFY_FORWARD_FILENAME)
        )
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.onlineworker.tmp")
    temporary_path.write_text(content, encoding="utf-8")
    os.replace(temporary_path, path)


def _render_toml_string_array(values: list[str]) -> str:
    rendered = ", ".join(json.dumps(value, ensure_ascii=False) for value in values)
    return f"[{rendered}]"


def _replace_top_level_notify(config_text: str, argv: list[str]) -> str:
    lines = config_text.splitlines(keepends=True)
    replacement = f"notify = {_render_toml_string_array(argv)}\n"
    first_table = next(
        (index for index, line in enumerate(lines) if line.startswith("[")),
        len(lines),
    )
    for start, line in enumerate(lines[:first_table]):
        if not line.startswith("notify") or line.split("=", 1)[0].strip() != "notify":
            continue
        for end in range(start, len(lines)):
            candidate = "".join(lines[start : end + 1])
            try:
                parsed = tomllib.loads(candidate)
            except tomllib.TOMLDecodeError:
                continue
            if "notify" in parsed:
                lines[start : end + 1] = [replacement]
                return "".join(lines)
        raise ValueError("Codex config.toml 的顶层 notify 配置不完整")

    insert_at = first_table
    prefix = []
    if insert_at > 0 and not lines[insert_at - 1].endswith("\n"):
        prefix.append("\n")
    lines[insert_at:insert_at] = [*prefix, replacement, "\n"]
    return "".join(lines)


def _is_onlineworker_notify_argv(argv: list[str]) -> bool:
    return any(ONLINEWORKER_CODEX_NOTIFY_MARKER in item for item in argv)


def _save_notify_forward_argv(path: Path, argv: list[str]) -> bool:
    payload = {"argv": argv}
    desired = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == desired:
        return False
    _atomic_write_text(path, desired)
    return True


def remove_onlineworker_codex_event_hooks(
    *,
    hooks_path: str | None = None,
) -> dict[str, Any]:
    resolved_path = _default_codex_hooks_path(hooks_path)
    path = Path(resolved_path)
    if not path.exists():
        return {
            "state": "removed",
            "hooksPath": resolved_path,
            "removedEvents": [],
            "changed": False,
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    if not isinstance(hooks, dict):
        raise ValueError("Codex hooks 配置 hooks 不是对象")

    removed_events: list[str] = []
    changed = False
    for event_name in CODEX_EXTERNAL_EVENT_HOOK_NAMES:
        entries = hooks.get(event_name)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise ValueError(f"Codex hooks.{event_name} 不是数组")
        preserved = [
            entry for entry in entries if not _is_onlineworker_codex_hook_entry(entry)
        ]
        if preserved != entries:
            hooks[event_name] = preserved
            removed_events.append(event_name)
            changed = True
    if changed:
        _atomic_write_text(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )
    return {
        "state": "removed",
        "hooksPath": resolved_path,
        "removedEvents": removed_events,
        "changed": changed,
    }


def install_onlineworker_codex_notify(
    data_dir: str,
    *,
    config_path: str | None = None,
    hooks_path: str | None = None,
    forward_path: str | None = None,
) -> dict[str, Any]:
    resolved_config_path = _default_codex_config_path(config_path)
    resolved_forward_path = _default_codex_notify_forward_path(
        data_dir,
        forward_path,
    )
    config_file = Path(resolved_config_path)
    forward_file = Path(resolved_forward_path)
    try:
        config_text = (
            config_file.read_text(encoding="utf-8") if config_file.exists() else ""
        )
        parsed = tomllib.loads(config_text) if config_text.strip() else {}
        existing = parsed.get("notify", [])
        if not isinstance(existing, list) or not all(
            isinstance(item, str) for item in existing
        ):
            raise ValueError("Codex config.toml 的顶层 notify 不是字符串数组")

        desired = _codex_notify_argv(data_dir)
        forward_changed = False
        if existing and not _is_onlineworker_notify_argv(existing):
            forward_changed = _save_notify_forward_argv(forward_file, existing)
        desired_text = _replace_top_level_notify(config_text, desired)
        config_changed = desired_text != config_text
        if config_changed:
            _atomic_write_text(config_file, desired_text)
        hooks_result = remove_onlineworker_codex_event_hooks(hooks_path=hooks_path)
    except Exception as exc:
        return {
            "state": "install_failed",
            "configPath": resolved_config_path,
            "forwardPath": resolved_forward_path,
            "detail": f"安装 Codex notify 入口失败：{exc}",
            "changed": False,
        }

    return {
        "state": "installed",
        "configPath": resolved_config_path,
        "forwardPath": resolved_forward_path,
        "hooksPath": str(hooks_result.get("hooksPath") or ""),
        "removedEvents": list(hooks_result.get("removedEvents") or []),
        "detail": "",
        "changed": bool(
            config_changed or forward_changed or hooks_result.get("changed")
        ),
    }


def _default_codex_hooks_path(hooks_path: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(hooks_path or "~/.codex/hooks.json"))


def _onlineworker_codex_hook_entry(handler: dict[str, Any]) -> dict[str, Any]:
    return {
        "hooks": [dict(handler)],
    }


def _is_onlineworker_codex_hook_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    handlers = value.get("hooks")
    if not isinstance(handlers, list):
        return False
    return any(
        isinstance(handler, dict)
        and ONLINEWORKER_CODEX_HOOK_MARKER
        in str(handler.get("command") or "")
        for handler in handlers
    )


def _existing_onlineworker_codex_hook_handler(
    hooks: dict[str, Any],
) -> dict[str, Any] | None:
    for entries in hooks.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            handlers = entry.get("hooks")
            if not isinstance(handlers, list):
                continue
            for handler in handlers:
                if (
                    isinstance(handler, dict)
                    and ONLINEWORKER_CODEX_HOOK_MARKER
                    in str(handler.get("command") or "")
                ):
                    return dict(handler)
    return None


def install_onlineworker_codex_hooks(
    data_dir: str,
    *,
    hooks_path: str | None = None,
) -> dict[str, Any]:
    resolved_path = _default_codex_hooks_path(hooks_path)
    path = Path(resolved_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception as exc:
        return {
            "state": "install_failed",
            "hooksPath": resolved_path,
            "detail": f"读取 Codex hooks 配置失败：{exc}",
            "installedEvents": [],
            "changed": False,
        }

    if not isinstance(payload, dict):
        return {
            "state": "install_failed",
            "hooksPath": resolved_path,
            "detail": "Codex hooks 配置根节点不是对象",
            "installedEvents": [],
            "changed": False,
        }
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return {
            "state": "install_failed",
            "hooksPath": resolved_path,
            "detail": "Codex hooks 配置 hooks 不是对象",
            "installedEvents": [],
            "changed": False,
        }

    desired_handler = _existing_onlineworker_codex_hook_handler(hooks) or {
        "type": "command",
        "command": _codex_hook_command(data_dir),
        "timeout": 5,
    }
    desired_entry = _onlineworker_codex_hook_entry(desired_handler)
    installed_events: list[str] = []
    changed = False
    for event_name in CODEX_EXTERNAL_EVENT_HOOK_NAMES:
        current_entries = hooks.get(event_name, [])
        if not isinstance(current_entries, list):
            return {
                "state": "install_failed",
                "hooksPath": resolved_path,
                "detail": f"Codex hooks.{event_name} 不是数组",
                "installedEvents": installed_events,
                "changed": changed,
            }
        preserved = [
            entry
            for entry in current_entries
            if not _is_onlineworker_codex_hook_entry(entry)
        ]
        merged = [*preserved, desired_entry]
        if merged != current_entries:
            hooks[event_name] = merged
            changed = True
        installed_events.append(event_name)

    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_name(f".{path.name}.onlineworker.tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, path)
        except Exception as exc:
            return {
                "state": "install_failed",
                "hooksPath": resolved_path,
                "detail": f"写入 Codex hooks 配置失败：{exc}",
                "installedEvents": installed_events,
                "changed": False,
            }

    return {
        "state": "installed",
        "hooksPath": resolved_path,
        "detail": "",
        "installedEvents": installed_events,
        "changed": changed,
    }


async def relay_codex_hook_payload(
    data_dir: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    socket_path = provider_owner_bridge_socket_path(data_dir)
    if not socket_path:
        return {}
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(socket_path),
            timeout=CODEX_HOOK_RELAY_TIMEOUT_SECONDS,
        )
    except Exception:
        return {}

    try:
        request = {
            "type": "provider_hook_event",
            "provider_id": "codex",
            "payload": payload,
        }
        writer.write((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
        await asyncio.wait_for(
            writer.drain(),
            timeout=CODEX_HOOK_RELAY_TIMEOUT_SECONDS,
        )
        raw = await asyncio.wait_for(
            reader.readline(),
            timeout=CODEX_HOOK_RELAY_TIMEOUT_SECONDS,
        )
    except Exception:
        return {}
    finally:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
        except Exception:
            pass

    if not raw:
        return {}
    try:
        response = json.loads(raw.decode("utf-8"))
    except Exception:
        return {}
    return response if isinstance(response, dict) else {}


def normalize_codex_notify_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("type") or "").strip() != "agent-turn-complete":
        return {}
    session_id = str(
        payload.get("thread-id")
        or payload.get("thread_id")
        or payload.get("threadId")
        or ""
    ).strip()
    if not session_id:
        return {}
    turn_id = str(
        payload.get("turn-id")
        or payload.get("turn_id")
        or payload.get("turnId")
        or ""
    ).strip()
    input_messages = payload.get("input-messages")
    if input_messages is None:
        input_messages = payload.get("input_messages")
    if isinstance(input_messages, str):
        normalized_inputs = [input_messages]
    elif isinstance(input_messages, list):
        normalized_inputs = [
            str(item).strip()
            for item in input_messages
            if str(item).strip()
        ]
    else:
        normalized_inputs = []
    return {
        "hook_event_name": "AgentTurnComplete",
        "session_id": session_id,
        "turn_id": turn_id,
        "cwd": str(payload.get("cwd") or "").strip(),
        "input_messages": normalized_inputs,
        "last_assistant_message": str(
            payload.get("last-assistant-message")
            or payload.get("last_assistant_message")
            or payload.get("lastAssistantMessage")
            or ""
        ).strip(),
        "source": "codex_notify",
    }


def forward_codex_notify_payload(data_dir: str, raw_payload: str) -> bool:
    path = Path(_default_codex_notify_forward_path(data_dir))
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        argv = payload.get("argv") if isinstance(payload, dict) else None
        if not isinstance(argv, list) or not all(
            isinstance(item, str) and item for item in argv
        ):
            return False
        if _is_onlineworker_notify_argv(argv):
            return False
        subprocess.Popen(
            [*argv, raw_payload],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return False
    return True


def run_codex_notify_bridge_once(data_dir: str, raw_payload: str) -> int:
    try:
        payload = json.loads(raw_payload or "{}")
    except Exception:
        payload = {}
    try:
        normalized = (
            normalize_codex_notify_payload(payload)
            if isinstance(payload, dict)
            else {}
        )
        if normalized:
            asyncio.run(relay_codex_hook_payload(data_dir, normalized))
    finally:
        forward_codex_notify_payload(data_dir, raw_payload)
    return 0


def default_codex_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {}


def mirror_codex_permission_request(data_dir: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    del data_dir, payload
    return {}


def _codex_permission_hook_output(decision_response: dict[str, Any]) -> dict[str, Any]:
    decision = str(decision_response.get("decision") or "").strip().lower()
    if decision in {"allow", "allow_always"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": CODEX_PERMISSION_HOOK_NAME,
                "decision": {"behavior": "allow"},
            }
        }
    if decision == "deny":
        decision_payload = {"behavior": "deny"}
        message = str(decision_response.get("message") or "").strip()
        if message:
            decision_payload["message"] = message
        return {
            "hookSpecificOutput": {
                "hookEventName": CODEX_PERMISSION_HOOK_NAME,
                "decision": decision_payload,
            }
        }
    return {}


def run_codex_hook_bridge_once(data_dir: str | None) -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except Exception:
        payload = {}
    event_name = str(payload.get("hook_event_name") or "").strip() if isinstance(payload, dict) else ""
    if event_name == CODEX_PERMISSION_HOOK_NAME:
        bridge_response = mirror_codex_permission_request(data_dir, payload)
    elif event_name in CODEX_EXTERNAL_EVENT_HOOK_NAMES:
        bridge_response = asyncio.run(relay_codex_hook_payload(data_dir, payload))
    else:
        bridge_response = {}
    response = _codex_permission_hook_output(bridge_response)
    if not response:
        response = default_codex_hook_response(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return 0
