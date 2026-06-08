from __future__ import annotations

from typing import Any

from core.messages.events import MessageEvent, create_message_event
from core.providers.session_events import SessionEvent


def _text(value: Any) -> str:
    return str(value or "").strip()


def _event_text(event: SessionEvent) -> str:
    semantic_text = _text(event.semantic_payload.get("text"))
    if semantic_text:
        return semantic_text
    payload = event.payload or {}
    return _text(
        payload.get("text")
        or payload.get("delta")
        or payload.get("message")
        or payload.get("command")
        or payload.get("reason")
        or payload.get("error")
    )


def _workspace_path_from_id(workspace_id: str) -> str:
    if ":" not in workspace_id:
        return ""
    return workspace_id.split(":", 1)[1]


def canonical_kind_for_session_event(event: SessionEvent) -> str:
    if event.kind == "turn_started":
        return "turn.started"
    if event.kind == "assistant_delta":
        return "message.assistant.delta"
    if event.kind == "approval_requested":
        return "approval.requested"
    if event.kind == "question_requested":
        return "question.requested"
    if event.kind == "turn_aborted":
        return "turn.failed"
    if event.kind == "turn_completed":
        payload = event.payload or {}
        status = _text(payload.get("status")).lower()
        if status in {"aborted", "cancelled", "canceled", "error", "failed"}:
            return "turn.failed"
        return "turn.completed"
    if event.kind == "assistant_completed":
        payload = event.payload or {}
        phase = _text(event.semantic_payload.get("phase") or payload.get("phase"))
        if phase == "final_answer" or event.semantic_kind == "turn_completed":
            return "message.assistant.final"
        return "message.assistant.delta"
    if event.kind == "session_created":
        return "session.created"
    if event.kind == "session_title_updated":
        return "session.title_updated"
    return event.kind.replace("_", ".")


def message_event_from_session_event(event: SessionEvent) -> MessageEvent:
    payload = event.payload or {}
    semantic_payload = event.semantic_payload or {}
    kind = canonical_kind_for_session_event(event)
    request_id = _text(payload.get("request_id"))
    item_id = _text(payload.get("item_id") or payload.get("id"))
    text = _event_text(event)
    title = _text(
        payload.get("title")
        or payload.get("taskSummary")
        or payload.get("prompt")
        or payload.get("user_prompt")
        or payload.get("userPrompt")
    )
    status = _text(payload.get("status"))
    reason = _text(payload.get("reason") or semantic_payload.get("reason"))
    dedupe_parts = [
        event.provider,
        event.workspace_id,
        event.thread_id or "",
        event.turn_id or "",
        kind,
        request_id,
        item_id,
    ]
    dedupe_key = ":".join(part for part in dedupe_parts if part)
    if kind == "message.assistant.delta" and not request_id and not item_id:
        dedupe_key = ""

    public_payload: dict[str, Any] = {
        "rawMethod": event.raw_method,
        "semanticKind": event.semantic_kind,
    }
    if text:
        if kind == "message.assistant.delta":
            public_payload["delta"] = text
        else:
            public_payload["text"] = text
    if title:
        public_payload["title"] = title
    if status:
        public_payload["status"] = status
    if reason:
        public_payload["reason"] = reason
    if request_id:
        public_payload["requestId"] = request_id
    if payload.get("_mirroredOnly") is True:
        public_payload["mirroredOnly"] = True
    if kind == "approval.requested":
        command = _text(payload.get("command"))
        approval_source = _text(payload.get("approval_source") or event.raw_method)
        prompt = _text(payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt"))
        if approval_source:
            public_payload["approvalSource"] = approval_source
        if command:
            public_payload["command"] = command
        if prompt:
            public_payload["prompt"] = prompt
        if command:
            public_payload["message"] = f"需要处理授权请求：{command[:180]}"
        else:
            public_payload["message"] = "需要处理授权请求"
    if kind == "question.requested":
        question = _text(payload.get("question") or payload.get("header"))
        prompt = _text(payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt"))
        if prompt:
            public_payload["prompt"] = prompt
        public_payload["message"] = question or "需要回答问题"

    return create_message_event(
        kind,
        provider_id=event.provider,
        workspace_id=event.workspace_id,
        workspace_path=_workspace_path_from_id(event.workspace_id),
        session_id=event.thread_id or "",
        turn_id=event.turn_id or "",
        source="provider_event",
        payload=public_payload,
        dedupe_key=dedupe_key,
    )
