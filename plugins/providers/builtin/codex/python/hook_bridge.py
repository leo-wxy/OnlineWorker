from __future__ import annotations

import json
import sys
from typing import Any


CODEX_PERMISSION_HOOK_NAME = "PermissionRequest"


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
    else:
        bridge_response = {}
    response = _codex_permission_hook_output(bridge_response)
    if not response:
        response = default_codex_hook_response(payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    sys.stdout.flush()
    return 0
