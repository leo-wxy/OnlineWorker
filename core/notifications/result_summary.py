from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from core.ai.scenarios import run_ai_scenario
from core.notifications.summary_rules import (
    NotificationSummaryRules,
    fallback_from_text,
    limit_text,
    load_notification_summary_rules,
    title_from_summary,
)

logger = logging.getLogger(__name__)

NOTIFICATION_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _compact_notification_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _notification_rules() -> NotificationSummaryRules:
    import config

    return load_notification_summary_rules(config.get_data_dir())


def short_notification_title(value: str | None, rules: NotificationSummaryRules | None = None) -> str:
    active_rules = rules or _notification_rules()
    return limit_text(value, active_rules.title_limit)


def _notification_ai_preview_title(value: str | None) -> str:
    return _compact_notification_text(notification_text_without_urls(value) or value).strip(" -_|:：，。；,.")


def notification_text_without_urls(value: str | None) -> str:
    text = _compact_notification_text(value)
    if not text:
        return ""
    return _compact_notification_text(NOTIFICATION_URL_PATTERN.sub("", text)).strip(" -_|:：")


def notification_text_is_url_only(value: str | None) -> bool:
    text = _compact_notification_text(value)
    return bool(text and NOTIFICATION_URL_PATTERN.fullmatch(text))


def notification_safe_preview_title(value: str | None) -> str:
    if notification_text_is_url_only(value):
        return ""
    return short_notification_title(notification_text_without_urls(value) or value)


def notification_title_from_summary(
    value: str | None,
    rules: NotificationSummaryRules | None = None,
) -> str:
    text = notification_text_without_urls(value)
    if not text:
        return ""
    active_rules = rules or _notification_rules()
    return title_from_summary(text, active_rules)


def notification_summary_text(
    value: str | None,
    rules: NotificationSummaryRules | None = None,
) -> str:
    active_rules = rules or _notification_rules()
    return limit_text(
        notification_text_without_urls(value) or value,
        active_rules.summary_limit,
    )


def _notification_ai_summary_text(value: str | None) -> str:
    return _compact_notification_text(notification_text_without_urls(value) or value)


def _notification_result_fallback(
    value: str | None,
    rules: NotificationSummaryRules | None = None,
) -> tuple[str, str]:
    active_rules = rules or _notification_rules()
    return fallback_from_text(value, active_rules)


def _notification_clean_result_line(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"^(?:[-*+•]\s+|\d+[.)]\s*)", "", text).strip()
    return notification_text_without_urls(text)


def _notification_result_line_is_noise(
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


def _notification_result_points(
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
        text = _notification_clean_result_line(raw_line)
        if not text:
            continue
        if text in active_rules.section_headings:
            section = text
            continue
        if section in active_rules.stop_sections:
            continue
        if active_rules.result_sections and section not in active_rules.result_sections:
            continue
        if _notification_result_line_is_noise(text, active_rules):
            continue
        points.append(notification_summary_text(text, active_rules))

    if points:
        return points

    if not include_fallback:
        return []
    _title, fallback_summary = _notification_result_fallback(value, active_rules)
    fallback = fallback_summary or notification_summary_text(value, active_rules)
    return [fallback] if fallback else []


def notification_result_task_override(
    value: str | None,
    current_title: str = "",
) -> tuple[str, str]:
    rules = _notification_rules()
    points = _notification_result_points(value, rules, include_fallback=False)
    fallback_title, fallback_summary = _notification_result_fallback(value, rules)
    if fallback_title and fallback_summary and fallback_title != current_title:
        return fallback_title, fallback_summary
    if not points:
        return "", ""
    title = notification_title_from_summary(points[0], rules)
    if title and title != current_title:
        return title, points[0]
    return "", ""


def notification_result_message(value: str | None) -> str:
    points = _notification_result_points(value)
    text = points[1] if len(points) > 1 else (points[0] if points else "")
    return f"完成摘要：{text}" if text else "任务已完成"


async def notification_result_task_override_with_ai(
    *,
    final_message: str | None,
    current_title: str = "",
    current_task_summary: str | None = "",
    agent_name: str = "",
    status: str = "completed",
    provider_id: str = "",
    run_scenario: Callable[[str, dict[str, str]], Awaitable[Any]] = run_ai_scenario,
) -> tuple[str, str, str]:
    fallback_title, fallback_summary = notification_result_task_override(final_message, current_title)
    fallback_message = notification_result_message(final_message)
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

    ai_title = _notification_ai_preview_title(result.data.get("preview_title"))
    ai_summary = _notification_ai_summary_text(result.data.get("summary"))
    if not ai_title or not ai_summary:
        return fallback_title, fallback_summary, fallback_message
    return ai_title, "", f"完成摘要：{ai_summary}"
