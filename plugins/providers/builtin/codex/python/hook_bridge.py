from __future__ import annotations

import json
import sys
from typing import Any

from plugins.providers.builtin.codex.python.hook_cleanup import (
    CODEX_PERMISSION_HOOK_NAME,
    cleanup_onlineworker_codex_permission_hooks,
)


def default_codex_hook_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    if str(payload.get("hook_event_name") or "").strip() == CODEX_PERMISSION_HOOK_NAME:
        return {}
    return {}


def run_codex_hook_bridge_once(data_dir: str | None) -> int:
    cleanup_onlineworker_codex_permission_hooks()
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except Exception:
        payload = {}
    response = default_codex_hook_response(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return 0
