from __future__ import annotations

import re

from core.messages.events import MessageEvent, SessionActivity


NEEDS_ATTENTION_STATUS = "needs_attention"
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
UUID_TITLE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
TRUNCATED_UUID_TITLE_RE = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{1,4}){1,4}$", re.IGNORECASE)


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
        "command",
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


def _is_placeholder_title(title: str, session_id: str) -> bool:
    value = _compact(title)
    return (
        not value
        or value == _compact(session_id)
        or UUID_TITLE_RE.match(value) is not None
        or TRUNCATED_UUID_TITLE_RE.match(value) is not None
    )


def _activity_title(activity: SessionActivity) -> str:
    if not _is_placeholder_title(activity.title, activity.session_id):
        return activity.title
    for value in (activity.last_user_message,):
        summary = _compact(value)
        if summary:
            return summary[:160]
    return ""


def _clear_attention(activity: SessionActivity) -> None:
    activity.attention_reason = ""
    activity.attention_kind = ""
    activity.request_id = ""
    activity.approval_source = ""
    activity.mirrored_only = False


def _preserve_attention_preview(activity: SessionActivity) -> None:
    if _compact(activity.last_assistant_message):
        return
    if _compact(activity.last_user_message):
        return
    summary = _compact(activity.attention_reason)
    if summary:
        activity.last_assistant_message = summary[:500]


def _reset_live_summary_for_new_input(activity: SessionActivity) -> None:
    activity.last_assistant_message = ""
    activity.last_final_message = ""


def _is_terminal(activity: SessionActivity) -> bool:
    return activity.status in {COMPLETED_STATUS, FAILED_STATUS}


def _is_user_interruption(event: MessageEvent) -> bool:
    payload = event.payload or {}
    status = _compact(payload.get("status")).lower()
    reason = _compact(payload.get("reason") or payload.get("error") or payload.get("message")).lower()
    if status == "interrupted":
        return True
    if status and status not in {"aborted", "cancelled", "canceled"}:
        return False
    return reason in {
        "interrupted",
        "user interrupted",
        "user_cancelled",
        "user_canceled",
        "任务已取消",
        "用户已取消",
        "用户中断",
    } or "interrupted by user" in reason


class SessionActivityProjection:
    def __init__(self) -> None:
        self._activities: dict[str, SessionActivity] = {}

    def update(self, event: MessageEvent) -> None:
        if not event.provider_id or not event.session_id:
            return

        key = f"{event.provider_id}:{event.session_id}"
        if event.kind == "session.archived":
            self._activities.pop(key, None)
            return

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
        request_id = _compact(payload.get("requestId") or payload.get("request_id"))
        approval_source = _compact(
            payload.get("approvalSource") or payload.get("approval_source") or payload.get("rawMethod")
        )
        title = _compact(payload.get("title") or payload.get("taskSummary") or payload.get("preview"))
        if title and title != event.session_id:
            activity.title = title[:160]
        elif not activity.title:
            activity.title = event.session_id

        summary = _summary_from_payload(event)
        if event.kind == "message.user.submitted":
            if summary:
                activity.last_user_message = summary
                if _is_placeholder_title(activity.title, event.session_id):
                    activity.title = summary[:160]
                if not _is_terminal(activity):
                    _reset_live_summary_for_new_input(activity)
        elif event.kind == "message.user.accepted":
            if summary:
                activity.last_user_message = summary
                if _is_placeholder_title(activity.title, event.session_id):
                    activity.title = summary[:160]
            if not _is_terminal(activity):
                _reset_live_summary_for_new_input(activity)
                activity.status = RUNNING_STATUS
                _clear_attention(activity)
        elif event.kind in {
            "turn.started",
            "message.assistant.delta",
            "item.started",
            "item.completed",
            "shell.command.completed",
        }:
            if event.turn_id:
                activity.active_turn_id = event.turn_id
            if event.kind != "turn.started" and summary:
                activity.last_assistant_message = summary
            activity.status = RUNNING_STATUS
            _clear_attention(activity)
        elif event.kind == "message.assistant.final":
            if summary:
                activity.last_assistant_message = summary
                activity.last_final_message = summary
            activity.status = COMPLETED_STATUS
            activity.active_turn_id = ""
            _clear_attention(activity)
        elif event.kind == "turn.completed":
            if activity.status != NEEDS_ATTENTION_STATUS:
                activity.status = COMPLETED_STATUS
                activity.active_turn_id = ""
                if _is_user_interruption(event):
                    activity.attention_reason = "任务已由用户中断"
                    activity.attention_kind = "interrupted"
                    activity.request_id = ""
                    activity.approval_source = ""
                    activity.mirrored_only = False
                elif activity.attention_kind != "interrupted":
                    _clear_attention(activity)
        elif event.kind == "turn.failed":
            activity.active_turn_id = ""
            if _is_user_interruption(event):
                activity.status = COMPLETED_STATUS
                activity.attention_reason = "任务已由用户中断"
                activity.attention_kind = "interrupted"
            else:
                activity.status = FAILED_STATUS
                activity.attention_reason = summary or "任务失败"
                activity.attention_kind = "failure"
            activity.request_id = ""
            activity.approval_source = ""
            activity.mirrored_only = False
        elif event.kind == "approval.requested":
            prompt = _compact(payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt"))
            if prompt:
                activity.last_user_message = prompt[:500]
                if _is_placeholder_title(activity.title, event.session_id):
                    activity.title = prompt[:160]
            activity.status = NEEDS_ATTENTION_STATUS
            activity.attention_reason = summary or "需要处理授权请求"
            activity.attention_kind = "approval"
            activity.request_id = request_id
            activity.approval_source = approval_source
            activity.mirrored_only = payload.get("mirroredOnly") is True
        elif event.kind == "approval.answered":
            _preserve_attention_preview(activity)
            if not _is_terminal(activity):
                activity.status = RUNNING_STATUS
                _clear_attention(activity)
        elif event.kind == "question.requested":
            activity.status = NEEDS_ATTENTION_STATUS
            activity.attention_reason = summary or "需要回答问题"
            activity.attention_kind = "question"
            activity.request_id = ""
            activity.approval_source = ""
            activity.mirrored_only = payload.get("mirroredOnly") is True
        elif event.kind == "question.answered":
            if not _is_terminal(activity):
                activity.status = RUNNING_STATUS
                _clear_attention(activity)

        activity.last_event_kind = event.kind
        activity.updated_at = max(activity.updated_at, event.created_at)

    def list(self) -> list[dict]:
        return [self._to_dict(activity) for activity in self._sorted_activities()]

    def get(self, provider_id: str, session_id: str) -> dict | None:
        activity = self._activities.get(f"{provider_id}:{session_id}")
        return self._to_dict(activity) if activity is not None else None

    def _sorted_activities(self) -> list[SessionActivity]:
        return sorted(
            self._activities.values(),
            key=lambda item: (item.updated_at, item.provider_id, item.session_id),
            reverse=True,
        )

    def _to_dict(self, activity: SessionActivity) -> dict:
        data = activity.to_dict()
        data["title"] = _activity_title(activity)
        return data
