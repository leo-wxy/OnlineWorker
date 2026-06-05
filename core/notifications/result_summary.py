from __future__ import annotations

import re

from core.notifications.summary_rules import (
    NotificationSummaryRules,
    limit_text,
    load_notification_summary_rules,
    title_from_summary,
)

NOTIFICATION_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _compact_notification_text(value: str | None) -> str:
    return " ".join(str(value or "").split()).strip()


def _notification_rules() -> NotificationSummaryRules:
    import config

    return load_notification_summary_rules(config.get_data_dir())


def short_notification_title(value: str | None, rules: NotificationSummaryRules | None = None) -> str:
    active_rules = rules or _notification_rules()
    return limit_text(value, active_rules.title_limit)


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
