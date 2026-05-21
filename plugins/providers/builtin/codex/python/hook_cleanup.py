from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any


CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"

logger = logging.getLogger(__name__)


def codex_hooks_settings_path() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "hooks.json"
    return Path.home() / ".codex" / "hooks.json"


def _is_onlineworker_permission_hook(hook: Any) -> bool:
    if not isinstance(hook, dict):
        return False
    command = str(hook.get("command") or "")
    command_lower = command.lower()
    return "onlineworker" in command_lower and "--codex-hook-bridge" in command


def _write_codex_hooks_settings(path: Path, settings: dict[str, Any]) -> None:
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
            json.dump(settings, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
        os.replace(tmp_path, path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def cleanup_onlineworker_codex_permission_hooks(path: Path | None = None) -> bool:
    hooks_path = path or codex_hooks_settings_path()
    try:
        raw = hooks_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("[codex] 读取 hooks.json 失败，跳过 OnlineWorker PermissionRequest 清理：%s", exc)
        return False

    try:
        settings = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        logger.warning("[codex] hooks.json 不是有效 JSON，跳过 OnlineWorker PermissionRequest 清理：%s", exc)
        return False

    if not isinstance(settings, dict):
        return False
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    permission_entries = hooks.get(CODEX_PERMISSION_HOOK_NAME)
    if not isinstance(permission_entries, list):
        return False

    changed = False
    cleaned_entries: list[Any] = []
    for entry in permission_entries:
        if not isinstance(entry, dict):
            cleaned_entries.append(entry)
            continue

        entry_hooks = entry.get("hooks")
        if not isinstance(entry_hooks, list):
            cleaned_entries.append(entry)
            continue

        cleaned_hooks = [hook for hook in entry_hooks if not _is_onlineworker_permission_hook(hook)]
        if len(cleaned_hooks) == len(entry_hooks):
            cleaned_entries.append(entry)
            continue

        changed = True
        if cleaned_hooks:
            cleaned_entry = dict(entry)
            cleaned_entry["hooks"] = cleaned_hooks
            cleaned_entries.append(cleaned_entry)

    if not changed:
        return False

    if cleaned_entries:
        hooks[CODEX_PERMISSION_HOOK_NAME] = cleaned_entries
    else:
        hooks.pop(CODEX_PERMISSION_HOOK_NAME, None)

    try:
        _write_codex_hooks_settings(hooks_path, settings)
    except OSError as exc:
        logger.warning("[codex] 写回 hooks.json 失败，OnlineWorker PermissionRequest 清理未完成：%s", exc)
        return False
    return True
