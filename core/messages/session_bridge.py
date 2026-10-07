from __future__ import annotations

from typing import Any

from core.messages.events import MessageEvent, create_message_event
from core.providers.registry import get_provider
from core.providers.session_events import SessionEvent


def _text(value: Any) -> str:
    return str(value or "").strip()


def _event_text(event: SessionEvent) -> str:
    if event.kind == "assistant_delta":
        # Incremental chunks must retain boundary spaces and newlines.
        return str(event.payload.get("delta") or event.semantic_payload.get("text") or "")
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


def _completed_agent_message_is_final_by_default(provider_id: str) -> bool:
    descriptor = get_provider(provider_id)
    hooks = descriptor.session_event_hooks if descriptor is not None else None
    return bool(
        getattr(hooks, "completed_agent_message_is_final_by_default", True)
        if hooks is not None
        else True
    )


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
        if event.semantic_kind == "turn_aborted":
            return "turn.failed"
        if status in {"aborted", "cancelled", "canceled", "error", "failed"}:
            return "turn.failed"
        return "turn.completed"
    if event.kind == "assistant_completed":
        payload = event.payload or {}
        phase = _text(event.semantic_payload.get("phase") or payload.get("phase"))
        if phase == "final_answer" or event.semantic_kind == "turn_completed":
            return "message.assistant.final"
        if event.provider and _completed_agent_message_is_final_by_default(event.provider):
            # Some providers omit an explicit final phase while still
            # emitting a completed assistant message as the user-visible final
            # reply. Preserve the existing Telegram/runtime behavior here so all
            # bus consumers share the same boundary.
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
    raw_item = payload.get("item", {})
    item_id = _text(
        payload.get("item_id")
        or payload.get("itemId")
        or payload.get("id")
        or (raw_item.get("id") if isinstance(raw_item, dict) else "")
    )
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
    stable_identity = [request_id, item_id]
    if kind in {
        "message.user.submitted",
        "message.user.accepted",
        "message.assistant.final",
        "message.assistant.delta",
        "turn.started",
        "turn.completed",
        "turn.failed",
    }:
        stable_identity.append(event.turn_id or "")
    elif kind == "session.created":
        stable_identity.append("created")
    elif kind == "session.title_updated":
        stable_identity.append(title)
    elif kind == "question.requested":
        stable_identity.extend([_text(payload.get("questionId")), str(payload.get("subIndex", 0))])
    dedupe_key = ""
    # A turn contains multiple commentary messages; only a concrete item/request
    # can identify a repeated snapshot within that turn.
    if any(stable_identity) and (kind != "message.assistant.delta" or (
        event.raw_method == "item/completed" and (item_id or request_id)
    )):
        dedupe_key = ":".join(
            part
            for part in (
                event.provider,
                event.workspace_id,
                event.thread_id or "",
                kind,
                *stable_identity,
            )
            if part
        )

    public_payload: dict[str, Any] = {
        "rawMethod": event.raw_method,
        "semanticKind": event.semantic_kind,
    }
    if item_id:
        public_payload["itemId"] = item_id
    phase = _text(semantic_payload.get("phase") or payload.get("phase"))
    if phase:
        public_payload["phase"] = phase
    if kind == "message.assistant.delta" and event.raw_method == "item/completed":
        public_payload["isSnapshot"] = True
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
        from core.providers.interactions import parse_standard_question_request

        provider = get_provider(event.provider)
        parse_question = getattr(getattr(provider, "interactions", None), "parse_question_request", None)
        info = (parse_question or parse_standard_question_request)(
            payload, provider_id=event.provider, default_thread_id=event.thread_id,
        )
        public_payload.update({
            "questionId": info.question_id,
            "header": info.header,
            "question": info.question,
            "options": info.options,
            "multiple": info.multiple,
            "custom": info.custom,
            "subIndex": info.sub_index,
            "subTotal": info.sub_total,
        })
        prompt = _text(payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt"))
        if prompt:
            public_payload["prompt"] = prompt
        public_payload["message"] = info.question or info.header or "需要回答问题"

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
