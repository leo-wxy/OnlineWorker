"""Pure helpers for workspace topic, callback, and history handling."""

import hashlib
import os
from datetime import datetime
from typing import Optional


THREAD_OPEN_V2_PREFIX = "thread_open_v2"


def make_thread_topic_name(tool_name: str, ws_name: str, preview: Optional[str], thread_id: str) -> str:
    """Build a Telegram forum topic name for a workspace thread."""
    workspace_label = normalize_workspace_topic_label(ws_name)
    prefix = f"[{tool_name}/{workspace_label}] "
    if preview:
        body = " ".join(str(preview).strip().split())
    else:
        body = "New session"
    return (prefix + body)[:128]


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
