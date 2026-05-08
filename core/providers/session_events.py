from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass(frozen=True)
class SessionEvent:
    provider: str
    workspace_id: str
    thread_id: Optional[str]
    turn_id: Optional[str]
    kind: str
    payload: dict[str, Any]
    raw_method: str = ""
    semantic_kind: str = ""
    semantic_payload: dict[str, Any] = field(default_factory=dict)


def _extract_provider(workspace_id: str) -> str:
    if not workspace_id:
        return ""
    return workspace_id.split(":", 1)[0]


def _extract_thread_id(event_params: dict[str, Any]) -> Optional[str]:
    item = event_params.get("item", {})
    thread = event_params.get("thread", {})
    return (
        event_params.get("threadId")
        or event_params.get("thread_id")
        or (thread.get("id") if isinstance(thread, dict) else None)
        or (thread.get("threadId") if isinstance(thread, dict) else None)
        or (item.get("threadId") if isinstance(item, dict) else None)
    )


def _extract_turn_id(event_params: dict[str, Any]) -> Optional[str]:
    item = event_params.get("item", {})
    turn = event_params.get("turn", {})
    item_turn = item.get("turn", {}) if isinstance(item, dict) else {}
    return (
        event_params.get("turnId")
        or event_params.get("turn_id")
        or (turn.get("id") if isinstance(turn, dict) else None)
        or (turn.get("turnId") if isinstance(turn, dict) else None)
        or (item.get("turnId") if isinstance(item, dict) else None)
        or (item_turn.get("id") if isinstance(item_turn, dict) else None)
    )


def _normalize_kind(raw_method: str, payload: dict[str, Any]) -> str:
    if raw_method == "turn/started":
        return "turn_started"
    if raw_method == "item/started":
        return "item_started"
    if raw_method == "item/agentMessage/delta":
        return "assistant_delta"
    if raw_method == "item/commandExecution/requestApproval":
        return "approval_requested"
    if raw_method == "question/asked":
        return "question_requested"
    if raw_method == "session.created":
        return "session_created"
    if raw_method == "session.title_updated":
        return "session_title_updated"
    if raw_method == "turn/completed":
        status = str(payload.get("status") or "").strip().lower()
        if status == "aborted":
            return "turn_aborted"
        return "turn_completed"
    if raw_method == "item/completed":
        item = payload.get("item", {})
        item_type = str(item.get("type") or "").strip()
        if item_type == "agentMessage":
            return "assistant_completed"
        if item_type == "shellCommand":
            return "shell_command_completed"
        return "item_completed"
    return raw_method


def normalize_session_event(method: str, params: dict[str, Any]) -> SessionEvent | None:
    if method != "app-server-event" or not isinstance(params, dict):
        return None

    message = params.get("message", {})
    if not isinstance(message, dict):
        return None

    raw_method = str(message.get("method") or "").strip()
    raw_params = message.get("params", {})
    if not raw_method or not isinstance(raw_params, dict):
        return None

    workspace_id = str(params.get("workspace_id") or "").strip()
    provider = _extract_provider(workspace_id)
    payload: dict[str, Any] = dict(raw_params)
    thread_id = _extract_thread_id(payload)
    turn_id = _extract_turn_id(payload)

    item = payload.get("item", {})
    if isinstance(item, dict):
        item_type = str(item.get("type") or "").strip()
        if item_type:
            payload.setdefault("item_type", item_type)
        text = item.get("text")
        if text is not None and "text" not in payload:
            payload["text"] = text
        phase = item.get("phase")
        if phase is not None and "phase" not in payload:
            payload["phase"] = phase
        command = item.get("command")
        if command is not None and "command" not in payload:
            payload["command"] = command

    turn = payload.get("turn", {})
    if isinstance(turn, dict):
        status = turn.get("status")
        if status is not None and "status" not in payload:
            payload["status"] = status
        reason = turn.get("reason")
        if reason is not None and "reason" not in payload:
            payload["reason"] = reason

    message_id = message.get("id")
    if message_id is not None and "request_id" not in payload:
        payload["request_id"] = message_id

    semantic_kind = ""
    semantic_payload: dict[str, Any] = {}
    semantic_event_parser = _resolve_semantic_event_parser(provider)
    if callable(semantic_event_parser):
        semantic_event = semantic_event_parser(raw_method, payload)
        if semantic_event is not None:
            semantic_kind = semantic_event.kind
            semantic_payload = semantic_event.to_payload()

    return SessionEvent(
        provider=provider,
        workspace_id=workspace_id,
        thread_id=thread_id,
        turn_id=turn_id,
        kind=_normalize_kind(raw_method, payload),
        payload=payload,
        raw_method=raw_method,
        semantic_kind=semantic_kind,
        semantic_payload=semantic_payload,
    )


def _resolve_semantic_event_parser(provider: str):
    from core.providers.registry import get_provider

    descriptor = get_provider(provider)
    hooks = descriptor.session_event_hooks if descriptor is not None else None
    return getattr(hooks, "parse_semantic_event", None) if hooks is not None else None
