from __future__ import annotations

from dataclasses import dataclass
import re

from core.user_messages.sensitive_terms import (
    SensitiveTermMatch,
    default_sensitive_term_matcher,
)


@dataclass(frozen=True)
class NeutralizeResult:
    text: str
    changed: bool
    matches: list[SensitiveTermMatch]


def _apply_matches(text: str, matches: list[SensitiveTermMatch]) -> str:
    if not matches:
        return text

    parts: list[str] = []
    cursor = 0
    for match in matches:
        parts.append(text[cursor:match.start])
        if match.action == "replace":
            parts.append(match.replacement)
        cursor = match.end
    parts.append(text[cursor:])
    return "".join(parts)


def _cleanup_text(text: str) -> str:
    cleaned = re.sub(r"[ \t]{2,}", " ", text)
    cleaned = re.sub(r"^[,，。！？!?\s]+", "", cleaned)
    cleaned = re.sub(r"[,，。！？!?\s]+$", "", cleaned)
    cleaned = re.sub(r"([,，。！？!?]){2,}", r"\1", cleaned)
    cleaned = re.sub(r"这什么([^，。！？!?\n]*问题)", r"这是什么\1", cleaned)
    return cleaned.strip()


def _split_fenced_code_blocks(text: str) -> list[str]:
    return re.split(r"(```[\s\S]*?```)", text)


def neutralize_abusive_language(text: str) -> NeutralizeResult:
    original = str(text or "")
    if not original:
        return NeutralizeResult(text=original, changed=False, matches=[])

    matcher = default_sensitive_term_matcher()
    all_matches: list[SensitiveTermMatch] = []
    normalized_parts: list[str] = []

    for part in _split_fenced_code_blocks(original):
        if part.startswith("```") and part.endswith("```"):
            normalized_parts.append(part)
            continue
        matches = matcher.find_matches(part)
        all_matches.extend(matches)
        normalized_parts.append(_cleanup_text(_apply_matches(part, matches)))

    normalized = "".join(normalized_parts)
    return NeutralizeResult(
        text=normalized,
        changed=normalized != original,
        matches=all_matches,
    )
