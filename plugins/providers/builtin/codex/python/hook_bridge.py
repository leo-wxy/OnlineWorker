from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import socket
import sys
import tempfile
from typing import Any

from core.provider_owner_bridge import provider_owner_bridge_socket_path


CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"
CODEX_HOOK_TIMEOUT_SECONDS = 5


def _codex_hooks_settings_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "hooks.json"
    return Path.home() / ".codex" / "hooks.json"


def build_codex_hook_command(data_dir: str) -> str:
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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _is_onlineworker_codex_hook(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    command = str(hook.get("command") or "")
    return "onlineworker" in command.lower() and "--codex-hook-bridge" in command


def install_codex_permission_mirror_hook(
    data_dir: str,
    *,
    hooks_path: str | os.PathLike[str] | None = None,
) -> bool:
    path = _codex_hooks_settings_path(hooks_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        settings: dict[str, Any] = {}
    else:
        try:
            decoded = json.loads(raw or "{}")
        except json.JSONDecodeError:
            decoded = {}
        settings = decoded if isinstance(decoded, dict) else {}

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    permission_entries = hooks.setdefault(CODEX_PERMISSION_HOOK_NAME, [])
    if not isinstance(permission_entries, list):
        permission_entries = []
        hooks[CODEX_PERMISSION_HOOK_NAME] = permission_entries

    command = build_codex_hook_command(data_dir)
    desired_entry = {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": CODEX_HOOK_TIMEOUT_SECONDS,
            }
        ],
    }

    cleaned_permission_entries: list[Any] = []
    found_existing = False
    existing_needs_update = False
    for entry in permission_entries:
        if not isinstance(entry, dict):
            cleaned_permission_entries.append(entry)
            continue
        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            cleaned_permission_entries.append(entry)
            continue

        cleaned_hooks = []
        for hook in entry_hooks:
            if not _is_onlineworker_codex_hook(hook):
                cleaned_hooks.append(hook)
                continue
            found_existing = True
            if (
                hook.get("command") != command
                or hook.get("timeout") != CODEX_HOOK_TIMEOUT_SECONDS
                or hook.get("type") != "command"
            ):
                existing_needs_update = True

        if cleaned_hooks:
            cleaned_entry = dict(entry)
            cleaned_entry["hooks"] = cleaned_hooks
            cleaned_permission_entries.append(cleaned_entry)

    if found_existing and not existing_needs_update and permission_entries[:1] == [desired_entry]:
        return False

    hooks[CODEX_PERMISSION_HOOK_NAME] = [desired_entry, *cleaned_permission_entries]
    _write_json_atomic(path, settings)
    return True


def default_codex_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {}


def _infer_thread_id(payload: dict[str, Any]) -> str:
    for key in (
        "threadId",
        "thread_id",
        "conversationId",
        "conversation_id",
        "session_id",
        "sessionId",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("CODEX_THREAD_ID") or "").strip()


def _infer_workspace_dir(payload: dict[str, Any]) -> str:
    for key in ("cwd", "workspace_dir", "workspaceDir", "workspace", "project_dir"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return str(os.environ.get("PWD") or "").strip()


def _is_owned_tui_host_invocation(payload: dict[str, Any]) -> bool:
    value = str(payload.get("onlineworker_codex_tui_host") or "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    return str(os.environ.get("ONLINEWORKER_CODEX_TUI_HOST") or "").strip() == "1"


def mirror_codex_permission_request(data_dir: str | None, payload: dict[str, Any]) -> bool:
    if str(payload.get("hook_event_name") or "").strip() != CODEX_PERMISSION_HOOK_NAME:
        return False
    socket_path = provider_owner_bridge_socket_path(data_dir)
    if not socket_path:
        return False

    request = {
        "type": "mirror_approval",
        "provider_id": "codex",
        "thread_id": _infer_thread_id(payload),
        "workspace_dir": _infer_workspace_dir(payload),
        "owned_tui_host": _is_owned_tui_host_invocation(payload),
        "payload": payload,
        "source": "codex_cli_hook",
        "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"
        if _is_owned_tui_host_invocation(payload)
        else "此请求已在 Codex CLI 中弹出，请在 CLI 中完成审批。",
    }

    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(0.75)
            client.connect(socket_path)
            client.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            client.recv(4096)
        return True
    except OSError:
        return False


def run_codex_hook_bridge_once(data_dir: str | None) -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        mirror_codex_permission_request(data_dir, payload)
    response = default_codex_hook_response(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return 0
