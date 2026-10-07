from __future__ import annotations

import re

from core.messages.events import MessageEvent, SessionActivity


NEEDS_ATTENTION_STATUS = "needs_attention"
RUNNING_STATUS = "running"
COMPLETED_STATUS = "completed"
FAILED_STATUS = "failed"
TURN_SCOPED_ACTIVITY_KINDS = {
    "message.assistant.delta",
    "message.assistant.final",
    "item.started",
    "item.completed",
    "shell.command.completed",
    "turn.completed",
    "turn.failed",
    "approval.requested",
    "approval.answered",
    "question.requested",
    "question.answered",
}
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
    activity.questions = []
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


def _update_conversation(activity: SessionActivity, event: MessageEvent, *, full: bool = False) -> None:
    turns = activity.conversation_turns
    payload = {**(event.payload or {}), **event.conversation_payload} if full else event.payload or {}
    window = 50 if full else 6
    if event.kind == "session.history.loaded":
        if not turns or full:
            history = [
                dict(turn) for turn in payload.get("turns", [])
                if isinstance(turn, dict) and turn.get("role") in {"user", "assistant"}
                and str(turn.get("content") or "").strip()
            ][-window:]
            if full and turns:
                history = _merge_conversation_history(history, turns)
            activity.conversation_turns = history[-window:]
        return
    if event.kind in {"turn.completed", "turn.failed"}:
        for turn in turns:
            if turn.get("pending") and (not event.turn_id or turn.get("turnId") == event.turn_id):
                turn["pending"] = False
                turn["displayMode"] = "markdown" if event.kind == "turn.completed" else "plain"
        return
    if event.kind not in {
        "message.user.submitted", "message.user.accepted",
        "message.assistant.delta", "message.assistant.final",
    }:
        return
    if event.source == "startup_bootstrap" and turns:
        return
    text = str(payload.get("text") or payload.get("delta") or payload.get("message") or "")
    role = "user" if event.kind.startswith("message.user.") else "assistant"
    if role == "user":
        attached = [f"[Attached {item.get('kind') or 'file'}] {item.get('name') or 'attachment'}"
                    for item in payload.get("attachments", []) if isinstance(item, dict)]
        if attached:
            text = "\n".join(([text] if text else []) + attached)
    if not text:
        return
    item_id = str(payload.get("itemId") or "")
    message_request_id = str(payload.get("messageRequestId") or "")
    turn_id = event.turn_id
    existing = None
    if role == "user" and event.kind == "message.user.accepted":
        existing = next((turn for turn in reversed(turns)
                         if turn["role"] == "user" and (
                             turn.get("messageRequestId") == message_request_id if message_request_id
                             else turn["content"] == text
                         )), None)
    elif role == "assistant":
        existing = next((turn for turn in reversed(turns)
                         if turn["role"] == role and turn.get("turnId", "") == turn_id
                         and turn.get("itemId", "") == item_id
                         and (item_id or turn.get("pending"))), None)
    if existing is None:
        existing = {"role": role, "content": "", "itemId": item_id, "turnId": turn_id}
        if message_request_id:
            existing["messageRequestId"] = message_request_id
        turns.append(existing)
    incremental = event.kind == "message.assistant.delta" and not payload.get("isSnapshot")
    if incremental and existing.get("pending") is False:
        return
    content = existing["content"] + text if incremental else text
    existing["content"] = content if full else content[:4000]
    existing["pending"] = role == "assistant" and event.kind == "message.assistant.delta" and not payload.get("isSnapshot")
    existing["displayMode"] = "markdown" if event.kind == "message.assistant.final" else "plain"
    del turns[:-window]


def _merge_conversation_history(history: list[dict], live: list[dict]) -> list[dict]:
    def same(left, right):
        if left["role"] != right["role"]:
            return False
        left_id, right_id = left.get("itemId"), right.get("itemId")
        if left_id and right_id:
            return left_id == right_id and left.get("turnId", "") == right.get("turnId", "")
        # ponytail: legacy history has no item IDs; align its suffix until providers expose them.
        return left["content"] == right["content"]

    for overlap in range(min(len(history), len(live)), 0, -1):
        if all(same(left, right) for left, right in zip(history[-overlap:], live[:overlap])):
            return history[:-overlap] + live
    return history + live


class SessionActivityProjection:
    def __init__(self, *, full_conversation: bool = False) -> None:
        self._full_conversation = full_conversation
        self._activities: dict[str, SessionActivity] = {}
        self._turn_ids: dict[str, str] = {}
        self._message_request_ids: dict[str, str] = {}
        self._request_turn_ids: dict[str, str] = {}

    def update(self, event: MessageEvent) -> None:
        if not event.provider_id or not event.session_id:
            return

        key = f"{event.provider_id}:{event.session_id}"
        if event.kind in {"session.archived", "session.hidden"}:
            self._activities.pop(key, None)
            self._turn_ids.pop(key, None)
            self._message_request_ids.pop(key, None)
            self._request_turn_ids.pop(key, None)
            return

        activity = self._activities.get(key)
        if activity is None:
            activity = SessionActivity(
                provider_id=event.provider_id,
                session_id=event.session_id,
            )
            self._activities[key] = activity

        current_turn_id = self._turn_ids.get(key, "")
        if (
            event.kind in TURN_SCOPED_ACTIVITY_KINDS
            and current_turn_id
            and event.turn_id
            and event.turn_id != current_turn_id
        ):
            return
        if event.turn_id and (event.kind == "turn.started" or not current_turn_id):
            self._turn_ids[key] = event.turn_id

        payload = event.payload or {}
        message_request_id = _compact(payload.get("messageRequestId"))
        if event.kind == "message.user.submitted":
            self._message_request_ids[key] = message_request_id
            activity.last_message_request_id = message_request_id
            self._request_turn_ids[key] = current_turn_id
            activity.delivery_status = "submitted"
            activity.delivery_error = ""
        elif event.kind in {"message.user.queued", "message.user.accepted", "message.user.send_failed"}:
            latest_request_id = self._message_request_ids.get(key, "")
            if latest_request_id and message_request_id != latest_request_id:
                return
            if message_request_id and not latest_request_id:
                self._message_request_ids[key] = message_request_id
                activity.last_message_request_id = message_request_id

        _update_conversation(activity, event, full=self._full_conversation)

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
        if event.kind in {"message.assistant.delta", "message.assistant.final"} and activity.conversation_turns:
            summary = _compact(activity.conversation_turns[-1]["content"])[:500]
        if event.kind == "message.user.submitted":
            if summary:
                activity.last_user_message = summary
                if _is_placeholder_title(activity.title, event.session_id):
                    activity.title = summary[:160]
                if not _is_terminal(activity):
                    _reset_live_summary_for_new_input(activity)
        elif event.kind == "message.user.accepted":
            activity.delivery_status = "accepted"
            activity.delivery_error = ""
            if summary:
                activity.last_user_message = summary
                if _is_placeholder_title(activity.title, event.session_id):
                    activity.title = summary[:160]
            if not _is_terminal(activity):
                if not message_request_id:
                    _reset_live_summary_for_new_input(activity)
                activity.status = RUNNING_STATUS
                _clear_attention(activity)
        elif event.kind == "message.user.queued":
            activity.delivery_status = "queued"
        elif event.kind == "message.user.send_failed":
            activity.delivery_status = _compact(payload.get("deliveryStatus")) or "failed"
            activity.delivery_error = _compact(payload.get("error")) or "消息发送失败"
            if (
                not activity.active_turn_id
                and current_turn_id == self._request_turn_ids.get(key, current_turn_id)
                and (message_request_id or activity.status != RUNNING_STATUS)
            ):
                activity.status = FAILED_STATUS
                activity.attention_reason = _compact(payload.get("error")) or "消息发送失败"
                activity.attention_kind = "failure"
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
            if activity.attention_kind != "question" or event.kind == "turn.started":
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
            if activity._recovery_status:
                activity._recovery_status = COMPLETED_STATUS
                activity.active_turn_id = ""
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
            activity.questions = []
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
        elif event.kind == "session.recovery.updated":
            recovery_payload = event.conversation_payload if self._full_conversation else payload
            if "sendRecovery" in recovery_payload:
                activity.send_recovery = dict(recovery_payload["sendRecovery"])
                recovery_status = activity.send_recovery.get("status")
                if recovery_status in {"failed", "unknown"}:
                    activity.delivery_status = "uncertain" if recovery_status == "unknown" else "failed"
                    activity.delivery_error = str(activity.send_recovery.get("error") or "")
                    if not activity.active_turn_id and activity.status != RUNNING_STATUS:
                        if "sendRecovery" in payload and not activity._recovery_status:
                            activity._recovery_status = activity.status
                        activity.status = FAILED_STATUS
                elif recovery_status == "sent":
                    activity.delivery_status = "accepted"
                    activity.delivery_error = ""
                    if "sendRecovery" in payload and activity._recovery_status:
                        if activity.status == FAILED_STATUS:
                            activity.status = activity._recovery_status
                        activity._recovery_status = ""
            if payload.get("newSessionRequestId"):
                activity.new_session_request_id = str(payload["newSessionRequestId"])
            if payload.get("text"):
                activity.last_user_message = str(payload["text"])[:500]
            if "sendRecovery" not in payload and payload.get("error"):
                if not activity._recovery_status or activity.status != NEEDS_ATTENTION_STATUS:
                    activity._recovery_status = activity.status
                activity.status = NEEDS_ATTENTION_STATUS
                activity.attention_reason = str(payload["error"])
                activity.attention_kind = "failure"
                activity.delivery_error = str(payload["error"])
            elif "sendRecovery" not in payload and activity._recovery_status:
                if activity.status == NEEDS_ATTENTION_STATUS and activity.attention_kind == "failure":
                    activity.status = activity._recovery_status
                    _clear_attention(activity)
                activity._recovery_status = ""
                activity.delivery_error = ""
        elif event.kind == "approval.requested":
            activity.questions = []
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
            question_id = _compact(payload.get("questionId"))
            if activity.request_id != question_id:
                activity.questions = []
            activity.request_id = question_id
            activity.approval_source = ""
            activity.mirrored_only = payload.get("mirroredOnly") is True
            if question_id:
                question = {key: payload.get(key) for key in (
                    "questionId", "header", "question", "options", "multiple", "custom", "subIndex", "subTotal",
                )}
                activity.questions = sorted(
                    [item for item in activity.questions if item.get("subIndex") != question.get("subIndex")] + [question],
                    key=lambda item: item.get("subIndex") or 0,
                )
        elif event.kind == "question.answered":
            if not _is_terminal(activity) and (
                not activity.request_id or activity.request_id == _compact(payload.get("questionId"))
            ):
                activity.status = RUNNING_STATUS
                _clear_attention(activity)

        activity.last_event_kind = event.kind
        # Loading history is not new activity in the session.
        if event.kind != "session.history.loaded":
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
