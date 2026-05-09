from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


CODEX_SEMANTIC_EVENT_KINDS = {
    "run_started",
    "assistant_progress",
    "tool_started",
    "tool_completed",
    "approval_requested",
    "approval_resolved",
    "turn_aborted",
    "turn_completed",
    "sync_failed",
}


@dataclass(frozen=True)
class CodexSemanticEvent:
    """Provider-neutral codex turn event used before presentation rendering."""

    kind: str
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    text: str = ""
    phase: str = ""
    tool_name: str = ""
    call_id: str = ""
    status: str = ""
    reason: str = ""
    raw_kind: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        for key in (
            "thread_id",
            "turn_id",
            "text",
            "phase",
            "tool_name",
            "call_id",
            "status",
            "reason",
            "raw_kind",
        ):
            value = getattr(self, key)
            if value:
                payload[key] = value
        return payload


def _extract_thread_id(payload: dict[str, Any]) -> Optional[str]:
    item = payload.get("item", {})
    turn = payload.get("turn", {})
    return (
        payload.get("threadId")
        or payload.get("thread_id")
        or (turn.get("threadId") if isinstance(turn, dict) else None)
        or (turn.get("thread_id") if isinstance(turn, dict) else None)
        or (item.get("threadId") if isinstance(item, dict) else None)
        or (item.get("thread_id") if isinstance(item, dict) else None)
    )


def _extract_turn_id(payload: dict[str, Any]) -> Optional[str]:
    item = payload.get("item", {})
    turn = payload.get("turn", {})
    return (
        payload.get("turnId")
        or payload.get("turn_id")
        or (turn.get("id") if isinstance(turn, dict) else None)
        or (turn.get("turnId") if isinstance(turn, dict) else None)
        or (item.get("turnId") if isinstance(item, dict) else None)
    )


def _string_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _extract_message_text(payload: dict[str, Any]) -> str:
    text = payload.get("text")
    if text is not None:
        return _string_value(text)

    content = payload.get("content", [])
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        part_type = _string_value(item.get("type"))
        if part_type not in {"output_text", "input_text", "text"}:
            continue
        part_text = _string_value(item.get("text"))
        if part_text:
            parts.append(part_text)
    return "\n".join(parts).strip()


def _semantic_from_agent_message(
    payload: dict[str, Any],
    *,
    raw_kind: str,
    thread_id: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> CodexSemanticEvent | None:
    text = _extract_message_text(payload)
    phase = _string_value(payload.get("phase"))
    if phase == "commentary":
        kind = "assistant_progress"
    else:
        kind = "turn_completed"

    return CodexSemanticEvent(
        kind=kind,
        thread_id=thread_id,
        turn_id=turn_id,
        text=text,
        phase=phase,
        raw_kind=raw_kind,
        raw_payload=payload,
    )


def parse_codex_app_server_semantic_event(
    raw_method: str,
    payload: dict[str, Any],
) -> CodexSemanticEvent | None:
    """Map codex app-server notifications into the normalized semantic event vocabulary."""
    if not isinstance(payload, dict):
        return None

    thread_id = _extract_thread_id(payload)
    turn_id = _extract_turn_id(payload)

    if raw_method == "turn/started":
        return CodexSemanticEvent(
            kind="run_started",
            thread_id=thread_id,
            turn_id=turn_id,
            raw_kind=raw_method,
            raw_payload=payload,
        )

    if raw_method == "item/agentMessage/delta":
        return CodexSemanticEvent(
            kind="assistant_progress",
            thread_id=thread_id,
            turn_id=turn_id,
            text=_string_value(payload.get("delta")),
            raw_kind=raw_method,
            raw_payload=payload,
        )

    if raw_method == "item/commandExecution/requestApproval":
        return CodexSemanticEvent(
            kind="approval_requested",
            thread_id=thread_id,
            turn_id=turn_id,
            tool_name=_string_value(payload.get("command")),
            reason=_string_value(payload.get("reason") or payload.get("justification")),
            raw_kind=raw_method,
            raw_payload=payload,
        )

    if raw_method in {"item/started", "item/completed"}:
        item = payload.get("item", {})
        if not isinstance(item, dict):
            return None
        item_type = _string_value(item.get("type"))
        if item_type == "agentMessage" and raw_method == "item/completed":
            return _semantic_from_agent_message(
                item,
                raw_kind=raw_method,
                thread_id=thread_id,
                turn_id=turn_id,
            )
        if item_type == "shellCommand":
            return CodexSemanticEvent(
                kind="tool_started" if raw_method == "item/started" else "tool_completed",
                thread_id=thread_id,
                turn_id=turn_id,
                tool_name=_string_value(item.get("command") or item.get("name") or item_type),
                raw_kind=raw_method,
                raw_payload=payload,
            )

    if raw_method == "turn/completed":
        turn = payload.get("turn", {})
        status = _string_value((turn.get("status") if isinstance(turn, dict) else None) or payload.get("status"))
        reason = _string_value((turn.get("reason") if isinstance(turn, dict) else None) or payload.get("reason"))
        return CodexSemanticEvent(
            kind="turn_aborted" if status == "aborted" else "turn_completed",
            thread_id=thread_id,
            turn_id=turn_id,
            status=status,
            reason=reason,
            raw_kind=raw_method,
            raw_payload=payload,
        )

    return None


def parse_codex_rollout_semantic_event(
    record: dict[str, Any] | str,
) -> CodexSemanticEvent | None:
    """Map a codex rollout JSONL record into the normalized semantic event vocabulary."""
    if isinstance(record, str):
        try:
            record = json.loads(record)
        except json.JSONDecodeError:
            return None
    if not isinstance(record, dict):
        return None

    line_type = _string_value(record.get("type"))
    payload = record.get("payload", {})
    if not isinstance(payload, dict):
        return None

    raw_kind = line_type
    turn_id = _string_value(payload.get("turn_id") or payload.get("turnId")) or None

    if line_type == "event_msg":
        payload_type = _string_value(payload.get("type"))
        if payload_type == "task_started":
            return CodexSemanticEvent(
                kind="run_started",
                turn_id=turn_id,
                raw_kind=payload_type,
                raw_payload=payload,
            )
        if payload_type == "turn_aborted":
            return CodexSemanticEvent(
                kind="turn_aborted",
                turn_id=turn_id,
                reason=_string_value(payload.get("reason")),
                raw_kind=payload_type,
                raw_payload=payload,
            )
        if payload_type == "task_complete":
            return CodexSemanticEvent(
                kind="turn_completed",
                turn_id=turn_id,
                text=_string_value(payload.get("last_agent_message")),
                raw_kind=payload_type,
                raw_payload=payload,
            )
        if payload_type == "agent_message":
            return _semantic_from_agent_message(
                {
                    "text": payload.get("message", ""),
                    "phase": payload.get("phase", ""),
                },
                raw_kind=payload_type,
                turn_id=turn_id,
            )
        return None

    if line_type != "response_item":
        return None

    payload_type = _string_value(payload.get("type"))
    if payload_type == "message":
        if _string_value(payload.get("role")) != "assistant":
            return None
        return _semantic_from_agent_message(
            payload,
            raw_kind=f"{line_type}:{payload_type}",
            turn_id=turn_id,
        )

    if payload_type == "function_call":
        return CodexSemanticEvent(
            kind="tool_started",
            turn_id=turn_id,
            tool_name=_string_value(payload.get("name")),
            call_id=_string_value(payload.get("call_id")),
            raw_kind=f"{line_type}:{payload_type}",
            raw_payload=payload,
        )

    if payload_type == "function_call_output":
        return CodexSemanticEvent(
            kind="tool_completed",
            turn_id=turn_id,
            call_id=_string_value(payload.get("call_id")),
            raw_kind=f"{line_type}:{payload_type}",
            raw_payload=payload,
        )

    return None
