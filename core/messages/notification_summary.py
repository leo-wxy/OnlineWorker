from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from core.messages.events import MessageEvent
from core.notifications.result_summary import (
    notification_summary_text,
    notification_text_without_urls,
    notification_title_from_summary,
)
from core.notifications.summary_rules import (
    NotificationSummaryRules,
    fallback_from_text,
    load_notification_summary_rules,
)

logger = logging.getLogger(__name__)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _compact_notification_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _notification_rules() -> NotificationSummaryRules:
    import config

    return load_notification_summary_rules(config.get_data_dir())


def _clean_completed_summary_line(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(?:[-*+•]\s+|\d+[.)]\s*)", "", text).strip()
    return notification_text_without_urls(text)


def _completed_summary_line_is_noise(
    value: str,
    rules: NotificationSummaryRules | None = None,
) -> bool:
    active_rules = rules or _notification_rules()
    text = _compact_notification_text(value)
    if not text:
        return True
    if text in active_rules.section_headings:
        return True
    if text.endswith((":", "：")) and len(text) <= 24:
        return True
    if any(text.startswith(prefix) for prefix in active_rules.noise_prefixes):
        return True
    if any(token in text for token in active_rules.noise_contains):
        return True
    if any(text.endswith(suffix) for suffix in active_rules.noise_suffixes):
        return True

    lowered = text.lower()
    if lowered.startswith("```"):
        return True
    if any(pattern.search(text) for pattern in active_rules._compiled_noise_regexes):
        return True
    return False


def _completed_summary_fallback(
    value: str | None,
    rules: NotificationSummaryRules | None = None,
) -> tuple[str, str]:
    active_rules = rules or _notification_rules()
    return fallback_from_text(value, active_rules)


def _completed_summary_points(
    value: str | None,
    rules: NotificationSummaryRules | None = None,
    *,
    include_fallback: bool = True,
) -> list[str]:
    active_rules = rules or _notification_rules()
    section = ""
    in_code_block = False
    points: list[str] = []
    for raw_line in str(value or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        text = _clean_completed_summary_line(raw_line)
        if not text:
            continue
        if text in active_rules.section_headings:
            section = text
            continue
        if section in active_rules.stop_sections:
            continue
        if active_rules.result_sections and section not in active_rules.result_sections:
            continue
        if _completed_summary_line_is_noise(text, active_rules):
            continue
        points.append(notification_summary_text(text, active_rules))

    if points:
        return points

    if not include_fallback:
        return []
    _title, fallback_summary = _completed_summary_fallback(value, active_rules)
    fallback = fallback_summary or notification_summary_text(value, active_rules)
    return [fallback] if fallback else []


def _local_completed_summary_title_and_body(
    value: str | None,
    current_title: str = "",
) -> tuple[str, str]:
    rules = _notification_rules()
    points = _completed_summary_points(value, rules, include_fallback=False)
    fallback_title, fallback_summary = _completed_summary_fallback(value, rules)
    if fallback_title and fallback_summary and fallback_title != current_title:
        return fallback_title, fallback_summary
    if not points:
        return "", ""
    title = notification_title_from_summary(points[0], rules)
    if title and title != current_title:
        return title, points[0]
    return "", ""


def _local_completed_summary_message(value: str | None) -> str:
    points = _completed_summary_points(value)
    text = points[1] if len(points) > 1 else (points[0] if points else "")
    return f"完成摘要：{text}" if text else "任务已完成"


def _ai_preview_title(value: str | None) -> str:
    return _compact_notification_text(notification_text_without_urls(value) or value).strip(" -_|:：，。；,.")


def _ai_summary_text(value: str | None) -> str:
    return _compact_notification_text(notification_text_without_urls(value) or value)


async def _build_completed_summary(
    *,
    final_message: str | None,
    current_title: str = "",
    current_task_summary: str | None = "",
    agent_name: str = "",
    status: str = "completed",
    provider_id: str = "",
    run_scenario: Callable[[str, dict[str, str]], Awaitable[Any]],
) -> tuple[str, str, str]:
    fallback_title, fallback_summary = _local_completed_summary_title_and_body(final_message, current_title)
    fallback_message = _local_completed_summary_message(final_message)
    try:
        result = await run_scenario(
            "notification_summary",
            {
                "task_summary": current_task_summary or "",
                "final_message": final_message or "",
                "agent_name": agent_name,
                "status": status,
                "provider_id": provider_id,
            },
        )
    except Exception as exc:
        logger.warning("[notification] AI 摘要场景异常，使用本地规则: %s", exc)
        return fallback_title, fallback_summary, fallback_message

    if not result.ok:
        return fallback_title, fallback_summary, fallback_message

    ai_title = _ai_preview_title(result.data.get("preview_title"))
    ai_summary = _ai_summary_text(result.data.get("summary"))
    if not ai_title or not ai_summary:
        return fallback_title, fallback_summary, fallback_message
    return ai_title, "", f"完成摘要：{ai_summary}"


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
        task_name, task_summary, message = await _build_completed_summary(
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
