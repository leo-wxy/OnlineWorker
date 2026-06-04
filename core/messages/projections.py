from __future__ import annotations

from core.messages.events import MessageEvent, SessionActivity


NEEDS_ATTENTION_STATUS = "needs_attention"
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
IDLE_STATUS = "idle"


def _compact(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _summary_from_payload(event: MessageEvent) -> str:
    payload = event.payload or {}
    for key in (
        "text",
        "message",
        "finalMessage",
        "lastFinalMessage",
        "lastAssistantMessage",
        "delta",
        "summary",
        "preview",
        "reason",
        "error",
    ):
        value = _compact(payload.get(key))
        if value:
            return value[:500]
    attachments = payload.get("attachments")
    if isinstance(attachments, list) and attachments:
        return f"[{len(attachments)} attachments]"
    return ""


class SessionActivityProjection:
    def __init__(self) -> None:
        self._activities: dict[str, SessionActivity] = {}

    def update(self, event: MessageEvent) -> None:
        if not event.provider_id or not event.session_id:
            return

        key = f"{event.provider_id}:{event.session_id}"
        activity = self._activities.get(key)
        if activity is None:
            activity = SessionActivity(
                provider_id=event.provider_id,
                session_id=event.session_id,
            )
            self._activities[key] = activity

        if event.workspace_id:
            activity.workspace_id = event.workspace_id
        if event.workspace_path:
            activity.workspace_path = event.workspace_path

        payload = event.payload or {}
        title = _compact(payload.get("title") or payload.get("taskSummary") or payload.get("preview"))
        if title:
            activity.title = title[:160]
        elif not activity.title:
            activity.title = event.session_id

        summary = _summary_from_payload(event)
        if event.kind == "message.user.submitted":
            if summary:
                activity.last_user_message = summary
                if not activity.title:
                    activity.title = summary[:160]
        elif event.kind == "message.user.accepted":
            if summary:
                activity.last_user_message = summary
                if not activity.title:
                    activity.title = summary[:160]
            activity.status = RUNNING_STATUS
            activity.attention_reason = ""
        elif event.kind in {"turn.started", "message.assistant.delta"}:
            if event.kind == "message.assistant.delta" and summary:
                activity.last_assistant_message = summary
            activity.status = RUNNING_STATUS
        elif event.kind == "message.assistant.final":
            if summary:
                activity.last_assistant_message = summary
                activity.last_final_message = summary
                if not activity.title:
                    activity.title = summary[:160]
            activity.status = COMPLETED_STATUS
            activity.attention_reason = ""
        elif event.kind == "turn.completed":
            if activity.status != NEEDS_ATTENTION_STATUS:
                activity.status = COMPLETED_STATUS
                activity.attention_reason = ""
        elif event.kind == "turn.failed":
            activity.status = FAILED_STATUS
            activity.attention_reason = summary or "任务失败"
        elif event.kind == "approval.requested":
            activity.status = NEEDS_ATTENTION_STATUS
            activity.attention_reason = summary or "需要处理授权请求"
        elif event.kind == "approval.answered":
            activity.status = RUNNING_STATUS
            activity.attention_reason = ""
        elif event.kind == "question.requested":
            activity.status = NEEDS_ATTENTION_STATUS
            activity.attention_reason = summary or "需要回答问题"
        elif event.kind == "question.answered":
            activity.status = RUNNING_STATUS
            activity.attention_reason = ""

        activity.last_event_kind = event.kind
        activity.updated_at = max(activity.updated_at, event.created_at)

    def list(self) -> list[dict]:
        return [
            activity.to_dict()
            for activity in sorted(
                self._activities.values(),
                key=lambda item: (item.updated_at, item.provider_id, item.session_id),
                reverse=True,
            )
        ]

    def get(self, provider_id: str, session_id: str) -> dict | None:
        activity = self._activities.get(f"{provider_id}:{session_id}")
        return activity.to_dict() if activity is not None else None
