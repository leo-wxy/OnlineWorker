from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.messages.events import MessageEvent
from core.notifications.result_summary import (
    notification_result_task_override_with_ai,
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _event_text(event: MessageEvent) -> str:
    payload = event.payload or {}
    for key in ("text", "finalMessage", "lastFinalMessage", "lastAssistantMessage", "message"):
        text = _clean(payload.get(key))
        if text:
            return text
    return ""


def _summary_key(provider_id: str, session_id: str, turn_id: str = "") -> str:
    provider = _clean(provider_id)
    session = _clean(session_id)
    turn = _clean(turn_id)
    return f"{provider}:{session}:{turn}" if turn else f"{provider}:{session}"


@dataclass(frozen=True)
class NotificationSummaryResult:
    task_name_override: str = ""
    task_summary_override: str = ""
    message: str = ""


class NotificationSummaryConsumer:
    """Consumes canonical message events and prepares notification summaries."""

    def __init__(self) -> None:
        self._final_messages: dict[str, str] = {}

    def observe(self, event: MessageEvent) -> None:
        if event.kind != "message.assistant.final":
            return
        if not event.provider_id or not event.session_id:
            return
        text = _event_text(event)
        if not text:
            return
        self._final_messages[_summary_key(event.provider_id, event.session_id)] = text
        if event.turn_id:
            self._final_messages[_summary_key(event.provider_id, event.session_id, event.turn_id)] = text

    def final_message(self, *, provider_id: str, session_id: str, turn_id: str = "") -> str:
        if turn_id:
            text = self._final_messages.get(_summary_key(provider_id, session_id, turn_id), "")
            if text:
                return text
        return self._final_messages.get(_summary_key(provider_id, session_id), "")

    async def build_completed_notification(
        self,
        *,
        final_message: str | None,
        provider_id: str = "",
        session_id: str = "",
        turn_id: str = "",
        current_title: str = "",
        current_task_summary: str | None = "",
        agent_name: str = "",
        status: str = "completed",
        run_scenario: Callable[[str, dict[str, str]], Awaitable[Any]],
    ) -> NotificationSummaryResult:
        final_text = _clean(final_message) or self.final_message(
            provider_id=provider_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        task_name, task_summary, message = await notification_result_task_override_with_ai(
            final_message=final_text,
            current_title=current_title,
            current_task_summary=current_task_summary,
            agent_name=agent_name,
            status=status,
            provider_id=provider_id,
            run_scenario=run_scenario,
        )
        return NotificationSummaryResult(
            task_name_override=task_name,
            task_summary_override=task_summary,
            message=message,
        )

