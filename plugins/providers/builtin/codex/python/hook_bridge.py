from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from typing import Any


CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"
CODEX_USER_PROMPT_SUBMIT_HOOK_NAME = "UserPromptSubmit"
CODEX_HOOK_TIMEOUT_SECONDS = 86400


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
    del data_dir
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

    permission_entries = hooks.get(CODEX_PERMISSION_HOOK_NAME, [])
    if not isinstance(permission_entries, list):
        permission_entries = []

    cleaned_permission_entries: list[Any] = []
    found_existing = False
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

        if cleaned_hooks:
            cleaned_entry = dict(entry)
            cleaned_entry["hooks"] = cleaned_hooks
            cleaned_permission_entries.append(cleaned_entry)

    if not found_existing:
        return False

    if cleaned_permission_entries:
        hooks[CODEX_PERMISSION_HOOK_NAME] = cleaned_permission_entries
    else:
        hooks.pop(CODEX_PERMISSION_HOOK_NAME, None)
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
    else:
        bridge_response = {}
    response = _codex_permission_hook_output(bridge_response)
    if not response:
        response = default_codex_hook_response(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return 0
