"""Pure helpers for workspace topic, callback, and history handling."""

import hashlib
import os
from datetime import datetime
from typing import Optional


THREAD_OPEN_V2_PREFIX = "thread_open_v2"


def make_thread_topic_name(
    tool_name: str,
    ws_name: str,
    preview: Optional[str],
    thread_id: str,
    workspace_path: Optional[str] = None,
) -> str:
    """Build a Telegram forum topic name for a workspace thread."""
    workspace_label = normalize_workspace_topic_label(ws_name)
    hint = workspace_path_topic_hint(workspace_path)
    if hint:
        workspace_label = _append_topic_hint(workspace_label, hint, max_len=84)
    prefix = f"[{tool_name}/{workspace_label}] "
    if preview:
        body = " ".join(str(preview).strip().split())
    else:
        body = "New session"
    return (prefix + body)[:128]


def make_workspace_storage_key(tool_name: str, path: str, name: str = "") -> str:
    """Build the canonical workspace identity used by storage, routes, and callbacks."""
    normalized_tool = str(tool_name or "").strip()
    normalized_path = str(path or "").strip()
    if normalized_path:
        return f"{normalized_tool}:{normalized_path}"
    return f"{normalized_tool}:{str(name or '').strip()}"


def workspace_path_for_topic_hint(ws) -> Optional[str]:
    """Return the path only for workspaces that already use path-based identity."""
    tool_name = str(getattr(ws, "tool", "") or "")
    path = str(getattr(ws, "path", "") or "")
    name = str(getattr(ws, "name", "") or "")
    if not path:
        return None
    if getattr(ws, "daemon_workspace_id", None) == make_workspace_storage_key(tool_name, path, name):
        return path
    return None


def make_workspace_topic_name(tool_name: str, ws_name: str, workspace_path: Optional[str] = None) -> str:
    """Build a Telegram forum topic name for a workspace."""
    base = f"[{tool_name}] {normalize_workspace_topic_label(ws_name)}"
    hint = workspace_path_topic_hint(workspace_path)
    return _append_topic_hint(base, hint)


def workspace_path_topic_hint(path: Optional[str], *, max_chars: int = 48) -> str:
    """Return a compact, stable path hint that keeps duplicate basenames distinct."""
    normalized = str(path or "").strip().rstrip("/\\")
    if not normalized:
        return ""

    parts = [part for part in normalized.split(os.sep) if part]
    suffix = ""
    if "Projects" in parts:
        project_index = parts.index("Projects")
        if project_index + 1 < len(parts) - 1:
            suffix = "/".join(parts[project_index + 1:min(len(parts) - 1, project_index + 3)])
    if not suffix:
        parent_parts = parts[:-1]
        suffix = "/".join(parent_parts[-2:]) if parent_parts else normalize_workspace_topic_label(normalized)

    if len(suffix) > max_chars:
        suffix = "..." + suffix[-max(0, max_chars - 3):]
    return suffix


def _append_topic_hint(base: str, hint: str, *, max_len: int = 128) -> str:
    normalized_base = str(base or "").strip()
    normalized_hint = str(hint or "").strip()
    if not normalized_hint:
        return normalized_base[:max_len]

    suffix = f" @ {normalized_hint}"
    max_base_len = max(1, max_len - len(suffix))
    return f"{normalized_base[:max_base_len]}{suffix}"


def normalize_workspace_topic_label(ws_name: str) -> str:
    normalized = str(ws_name or "").strip()
    if not normalized:
        return "workspace"
    if normalized == "/":
        return "root"
    if "/" in normalized or "\\" in normalized:
        basename = os.path.basename(normalized.rstrip("/\\"))
        return basename or "workspace"
    return normalized


def make_thread_open_token(value: str) -> str:
    """Generate a stable short token for thread_open callback lookup."""
    return hashlib.blake2s(value.encode("utf-8"), digest_size=8).hexdigest()


def get_workspace_callback_identity(storage_key: str, ws) -> str:
    return ws.daemon_workspace_id or storage_key or f"{ws.tool}:{ws.name}"


def history_turn_signature(turn: dict) -> str:
    role = str(turn.get("role") or "").strip()
    timestamp = normalize_history_turn_timestamp(turn.get("timestamp"))
    text = str(turn.get("text") or "").strip()
    payload = f"{role}\n{timestamp}\n{text}".encode("utf-8")
    return hashlib.blake2s(payload, digest_size=16).hexdigest()


def normalize_history_turn_timestamp(value) -> int | str:
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value or "").strip()
    if not text:
        return 0

    try:
        return int(text)
    except (TypeError, ValueError):
        pass

    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return text


def format_history_turn_message(turn: dict) -> Optional[str]:
    role = str(turn.get("role") or "").strip()
    text = str(turn.get("text") or "").strip()
    if not text:
        return None
    if role == "user":
        return f"👤 {text[:3000]}"
    if role == "assistant":
        truncated = text[:3000]
        if len(text) > 3000:
            truncated += "\n…（截断）"
        return f"🤖 {truncated}"
    return None


def build_history_sync_batches(header: str, turn_messages: list[str], *, max_chars: int = 3500) -> list[str]:
    batches: list[str] = []
    current = header.strip()

    for msg in turn_messages:
        if not msg:
            continue
        addition = f"\n\n{msg}" if current else msg
        if current and len(current) + len(addition) > max_chars:
            batches.append(current)
            current = msg
            continue
        current += addition

    if current:
        batches.append(current)
    return batches
