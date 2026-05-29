from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

RULES_FILENAME = "notification_summary_rules.yaml"
DEFAULT_RULES_PATH = Path(__file__).with_name(RULES_FILENAME)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _int_value(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class NotificationTitleRule:
    pattern: str
    title: str


@dataclass(frozen=True)
class NotificationFallbackRule:
    pattern: str
    title: str
    summary: str


@dataclass(frozen=True)
class NotificationSummaryRules:
    title_limit: int = 16
    summary_limit: int = 80
    result_sections: tuple[str, ...] = ()
    stop_sections: tuple[str, ...] = ()
    noise_prefixes: tuple[str, ...] = ()
    noise_contains: tuple[str, ...] = ()
    noise_suffixes: tuple[str, ...] = ()
    noise_regexes: tuple[str, ...] = ()
    title_rules: tuple[NotificationTitleRule, ...] = ()
    fallback_rules: tuple[NotificationFallbackRule, ...] = ()
    title_strip_prefixes: tuple[str, ...] = ()
    title_remove_patterns: tuple[str, ...] = ()
    _compiled_noise_regexes: tuple[re.Pattern, ...] = field(default=(), init=False, repr=False)
    _compiled_title_rules: tuple[tuple[re.Pattern, str], ...] = field(default=(), init=False, repr=False)
    _compiled_fallback_rules: tuple[tuple[re.Pattern, str, str], ...] = field(default=(), init=False, repr=False)
    _compiled_title_remove_patterns: tuple[re.Pattern, ...] = field(default=(), init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled_noise_regexes", _compile_patterns(self.noise_regexes))
        object.__setattr__(
            self,
            "_compiled_title_rules",
            tuple(
                (pattern, rule.title)
                for rule in self.title_rules
                for pattern in _compile_patterns((rule.pattern,))
            ),
        )
        object.__setattr__(
            self,
            "_compiled_title_remove_patterns",
            _compile_patterns(self.title_remove_patterns),
        )
        object.__setattr__(
            self,
            "_compiled_fallback_rules",
            tuple(
                (pattern, rule.title, rule.summary)
                for rule in self.fallback_rules
                for pattern in _compile_patterns((rule.pattern,))
            ),
        )

    @property
    def section_headings(self) -> set[str]:
        return {*self.result_sections, *self.stop_sections}


def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    compiled: list[re.Pattern] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            logger.warning("[notification-summary] 忽略无效正则 pattern=%r error=%s", pattern, exc)
    return tuple(compiled)


def _rules_from_raw(raw: Any) -> NotificationSummaryRules:
    data = raw if isinstance(raw, dict) else {}
    limits = data.get("limits") if isinstance(data.get("limits"), dict) else {}
    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    noise = data.get("noise") if isinstance(data.get("noise"), dict) else {}
    title = data.get("title") if isinstance(data.get("title"), dict) else {}
    fallback = data.get("fallback") if isinstance(data.get("fallback"), dict) else {}
    raw_title_rules = title.get("rules") if isinstance(title.get("rules"), list) else []
    raw_fallback_rules = fallback.get("rules") if isinstance(fallback.get("rules"), list) else []
    title_rules = [
        NotificationTitleRule(
            pattern=str(item.get("pattern") or "").strip(),
            title=str(item.get("title") or "").strip(),
        )
        for item in raw_title_rules
        if isinstance(item, dict)
        and str(item.get("pattern") or "").strip()
        and str(item.get("title") or "").strip()
    ]
    fallback_rules = [
        NotificationFallbackRule(
            pattern=str(item.get("pattern") or "").strip(),
            title=str(item.get("title") or "").strip(),
            summary=str(item.get("summary") or "").strip(),
        )
        for item in raw_fallback_rules
        if isinstance(item, dict)
        and str(item.get("pattern") or "").strip()
        and str(item.get("title") or "").strip()
        and str(item.get("summary") or "").strip()
    ]
    return NotificationSummaryRules(
        title_limit=_int_value(limits.get("title"), 16),
        summary_limit=_int_value(limits.get("summary"), 80),
        result_sections=tuple(_string_list(sections.get("result"))),
        stop_sections=tuple(_string_list(sections.get("stop"))),
        noise_prefixes=tuple(_string_list(noise.get("prefixes"))),
        noise_contains=tuple(_string_list(noise.get("contains"))),
        noise_suffixes=tuple(_string_list(noise.get("suffixes"))),
        noise_regexes=tuple(_string_list(noise.get("regexes"))),
        title_rules=tuple(title_rules),
        fallback_rules=tuple(fallback_rules),
        title_strip_prefixes=tuple(_string_list(title.get("strip_prefixes"))),
        title_remove_patterns=tuple(_string_list(title.get("remove_patterns"))),
    )


def _load_rules_file(path: Path) -> NotificationSummaryRules | None:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("[notification-summary] 读取规则失败 path=%s error=%s", path, exc)
        return None
    return _rules_from_raw(raw)


def load_notification_summary_rules(data_dir: str | None = None) -> NotificationSummaryRules:
    if data_dir:
        custom_rules = _load_rules_file(Path(data_dir).expanduser() / RULES_FILENAME)
        if custom_rules is not None:
            return custom_rules

    default_rules = _load_rules_file(DEFAULT_RULES_PATH)
    if default_rules is not None:
        return default_rules
    return NotificationSummaryRules()


def limit_text(value: str | None, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return f"{text[: limit - 1]}…"


def title_from_summary(value: str | None, rules: NotificationSummaryRules) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    for pattern, title in rules._compiled_title_rules:
        if pattern.search(text):
            return title

    candidate = text
    for pattern in rules._compiled_title_remove_patterns:
        candidate = pattern.sub("", candidate)
    candidate = candidate.strip(" -_|:：，。；,.")
    for prefix in rules.title_strip_prefixes:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):].strip(" -_|:：，。；,.")
            break
    first_clause = re.split(r"[，。；,.!?！？;:：\n]", candidate, maxsplit=1)[0].strip()
    return limit_text(first_clause or candidate or text, rules.title_limit)


def fallback_from_text(value: str | None, rules: NotificationSummaryRules) -> tuple[str, str]:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "", ""
    for pattern, title, summary in rules._compiled_fallback_rules:
        if pattern.search(text):
            return title, limit_text(summary, rules.summary_limit)
    return "", ""
