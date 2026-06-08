from __future__ import annotations

import logging
from typing import Any

from core.messages.events import create_message_event
from core.messages.session_bridge import message_event_from_session_event
from core.notifications.events import NotificationEvent
from core.providers.session_events import SessionEvent
from core.user_messages.contracts import UserMessageSendRequest

logger = logging.getLogger(__name__)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _workspace_path_from_id(workspace_id: str) -> str:
    if ":" not in workspace_id:
        return ""
    return workspace_id.split(":", 1)[1]


def _attachment_summary(attachments: list[dict] | None) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        public.append(
            {
                "kind": _clean(item.get("kind")),
                "name": _clean(item.get("name")),
                "mimeType": _clean(item.get("mime_type") or item.get("mimeType")),
                "sizeBytes": item.get("size_bytes") or item.get("sizeBytes") or 0,
            }
        )
    return public


def _publish(state: Any, event) -> bool:
    bus = getattr(state, "message_bus", None)
    publish = getattr(bus, "publish", None)
    if not callable(publish):
        return False
    try:
        return bool(publish(event))
    except Exception:
        logger.warning(
            "[message-bus] publish failed kind=%s event_id=%s",
            getattr(event, "kind", ""),
            getattr(event, "event_id", ""),
            exc_info=True,
        )
        return False


def publish_session_message_event(state: Any, session_event: SessionEvent) -> bool:
    return _publish(state, message_event_from_session_event(session_event))


def publish_user_message_event(
    state: Any,
    request: UserMessageSendRequest,
    *,
    text: str,
    workspace_path: str = "",
    event_id: str = "",
    kind: str = "message.user.accepted",
) -> bool:
    event_kind = _clean(kind) or "message.user.accepted"
    provider_id = _clean(request.provider_id)
    workspace_id = _clean(request.workspace_id)
    thread_id = _clean(request.thread_id)
    source = _clean(request.source) or "unknown"
    attachments = _attachment_summary(request.attachments)
    payload: dict[str, Any] = {
        "text": _clean(text),
        "hasAttachments": bool(attachments),
        "attachments": attachments,
    }
    if request.metadata:
        payload["metadata"] = dict(request.metadata)

    dedupe_parts = ["user", event_kind, source, provider_id, workspace_id, thread_id, event_id]
    resolved_event_id = f"{event_kind}:{event_id}" if event_id else ""
    event = create_message_event(
        event_kind,
        provider_id=provider_id,
        workspace_id=workspace_id,
        workspace_path=_clean(workspace_path) or _workspace_path_from_id(workspace_id),
        session_id=thread_id,
        source=source,
        payload=payload,
        dedupe_key=":".join(part for part in dedupe_parts if part) if event_id else "",
        event_id=resolved_event_id,
    )
    return _publish(state, event)


def publish_user_message_submitted(
    state: Any,
    request: UserMessageSendRequest,
    *,
    text: str,
    workspace_path: str = "",
    event_id: str = "",
) -> bool:
    return publish_user_message_event(
        state,
        request,
        text=text,
        workspace_path=workspace_path,
        event_id=event_id,
        kind="message.user.submitted",
    )


def publish_user_message_accepted(
    state: Any,
    request: UserMessageSendRequest,
    *,
    text: str,
    workspace_path: str = "",
    event_id: str = "",
) -> bool:
    return publish_user_message_event(
        state,
        request,
        text=text,
        workspace_path=workspace_path,
        event_id=event_id,
        kind="message.user.accepted",
    )


def publish_approval_answered(
    state: Any,
    approval: Any,
    *,
    action: str,
    source: str = "telegram",
    message_id: int | None = None,
) -> bool:
    provider_id = _clean(getattr(approval, "tool_type", "") or getattr(approval, "tool_name", ""))
    workspace_id = _clean(getattr(approval, "workspace_id", ""))
    thread_id = _clean(getattr(approval, "thread_id", ""))
    request_id = _clean(getattr(approval, "request_id", ""))
    event = create_message_event(
        "approval.answered",
        provider_id=provider_id,
        workspace_id=workspace_id,
        workspace_path=_workspace_path_from_id(workspace_id),
        session_id=thread_id,
        source=source,
        payload={
            "requestId": request_id,
            "decision": _clean(action),
            "messageId": message_id or 0,
        },
        dedupe_key=":".join(
            part
            for part in (
                "approval.answered",
                provider_id,
                workspace_id,
                thread_id,
                request_id,
                _clean(action),
            )
            if part
        ),
    )
    return _publish(state, event)


def publish_approval_requested(
    state: Any,
    approval: Any,
    *,
    workspace_id: str = "",
    workspace_path: str = "",
    source: str = "app_server",
) -> bool:
    provider_id = _clean(getattr(approval, "tool_type", "") or getattr(approval, "tool_name", ""))
    resolved_workspace_id = _clean(workspace_id or getattr(approval, "workspace_id", ""))
    thread_id = _clean(getattr(approval, "thread_id", ""))
    raw_request_id = getattr(approval, "request_id", "")
    request_id = _clean(raw_request_id)
    approval_source = _clean(getattr(approval, "approval_source", ""))
    command = _clean(getattr(approval, "command", "") or getattr(approval, "cmd", ""))
    reason = _clean(getattr(approval, "reason", "") or getattr(approval, "justification", ""))
    summary_parts = []
    if command:
        summary_parts.append(command)
    if reason:
        summary_parts.append(reason)
    event = create_message_event(
        "approval.requested",
        provider_id=provider_id,
        workspace_id=resolved_workspace_id,
        workspace_path=_clean(workspace_path) or _workspace_path_from_id(resolved_workspace_id),
        session_id=thread_id,
        source=_clean(source) or "app_server",
        payload={
            "requestId": request_id,
            "rawRequestId": raw_request_id,
            "approvalSource": approval_source,
            "command": command,
            "reason": reason,
            "summary": " · ".join(summary_parts),
        },
        dedupe_key=":".join(
            part
            for part in (
                "approval.requested",
                provider_id,
                resolved_workspace_id,
                thread_id,
                request_id,
                approval_source,
            )
            if part
        ),
    )
    return _publish(state, event)


def publish_session_archived(
    state: Any,
    *,
    provider_id: str,
    workspace_id: str,
    workspace_path: str = "",
    session_id: str,
    source: str = "desktop_app",
) -> bool:
    cleaned_provider_id = _clean(provider_id)
    cleaned_workspace_id = _clean(workspace_id)
    cleaned_session_id = _clean(session_id)
    event = create_message_event(
        "session.archived",
        provider_id=cleaned_provider_id,
        workspace_id=cleaned_workspace_id,
        workspace_path=_clean(workspace_path) or _workspace_path_from_id(cleaned_workspace_id),
        session_id=cleaned_session_id,
        source=_clean(source) or "desktop_app",
        payload={},
        dedupe_key=":".join(
            part
            for part in (
                "session.archived",
                cleaned_provider_id,
                cleaned_workspace_id,
                cleaned_session_id,
            )
            if part
        ),
    )
    return _publish(state, event)


def publish_question_answered(
    state: Any,
    pending_question: Any,
    answers: list[list[str]],
    *,
    source: str = "telegram",
    message_id: int | None = None,
) -> bool:
    workspace_id = _clean(getattr(pending_question, "workspace_id", ""))
    provider_id = _clean(
        getattr(pending_question, "tool_name", "")
        or (state.get_tool_for_workspace(workspace_id) if workspace_id and hasattr(state, "get_tool_for_workspace") else "")
    )
    session_id = _clean(getattr(pending_question, "session_id", ""))
    question_id = _clean(getattr(pending_question, "question_id", ""))
    event = create_message_event(
        "question.answered",
        provider_id=provider_id,
        workspace_id=workspace_id,
        workspace_path=_workspace_path_from_id(workspace_id),
        session_id=session_id,
        source=source,
        payload={
            "questionId": question_id,
            "header": _clean(getattr(pending_question, "header", "")),
            "answers": answers,
            "messageId": message_id or 0,
        },
        dedupe_key=":".join(
            part
            for part in (
                "question.answered",
                provider_id,
                workspace_id,
                session_id,
                question_id,
            )
            if part
        ),
    )
    return _publish(state, event)


def publish_notification_activity(
    state: Any,
    notification: NotificationEvent,
    kind: str,
    *,
    channels: tuple[str, ...] = (),
    reason: str = "",
    errors: tuple[str, ...] = (),
) -> bool:
    event_kind = _clean(kind)
    provider_id = _clean(notification.agent_id)
    payload: dict[str, Any] = {
        "status": notification.status,
        "agentName": notification.agent_name,
        "taskName": notification.task_name,
        "message": notification.message,
        "taskId": notification.task_id,
        "taskSummary": notification.task_summary,
        "channels": list(channels),
        "reason": _clean(reason),
        "errors": list(errors),
    }
    event = create_message_event(
        event_kind,
        provider_id=provider_id,
        source="notification",
        payload=payload,
        dedupe_key=f"notification:{event_kind}:{notification.dedupe_key}:{_clean(reason)}",
    )
    return _publish(state, event)
