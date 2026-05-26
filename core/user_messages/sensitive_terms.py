from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SensitiveTerm:
    value: str
    kind: str
    action: str
    replacement: str = ""
    severity: str = "medium"


@dataclass(frozen=True)
class SensitiveTermMatch:
    value: str
    kind: str
    action: str
    replacement: str
    severity: str
    start: int
    end: int


DEFAULT_SENSITIVE_TERMS: tuple[SensitiveTerm, ...] = (
    SensitiveTerm("你妈的", "abuse_prefix", "drop", severity="high"),
    SensitiveTerm("他妈的", "venting_prefix", "drop", severity="medium"),
    SensitiveTerm("妈的", "venting_prefix", "drop", severity="medium"),
    SensitiveTerm("艹", "venting_prefix", "drop", severity="medium"),
    SensitiveTerm("傻逼", "insult", "drop", severity="high"),
    SensitiveTerm("傻比", "insult", "drop", severity="high"),
    SensitiveTerm("sb", "insult", "drop", severity="medium"),
    SensitiveTerm("SB", "insult", "drop", severity="medium"),
    SensitiveTerm("这破玩意", "derogatory_object", "replace", replacement="这个", severity="low"),
)


class SensitiveTermMatcher:
    def __init__(self, terms: tuple[SensitiveTerm, ...] = DEFAULT_SENSITIVE_TERMS):
        self._terms = sorted(terms, key=lambda item: len(item.value), reverse=True)

    def find_matches(self, text: str) -> list[SensitiveTermMatch]:
        source = str(text or "")
        matches: list[SensitiveTermMatch] = []
        occupied: list[tuple[int, int]] = []

        for term in self._terms:
            if not term.value:
                continue
            start = 0
            while True:
                index = source.find(term.value, start)
                if index < 0:
                    break
                end = index + len(term.value)
                start = index + 1
                if any(not (end <= used_start or index >= used_end) for used_start, used_end in occupied):
                    continue
                occupied.append((index, end))
                matches.append(
                    SensitiveTermMatch(
                        value=term.value,
                        kind=term.kind,
                        action=term.action,
                        replacement=term.replacement,
                        severity=term.severity,
                        start=index,
                        end=end,
                    )
                )

        return sorted(matches, key=lambda item: item.start)


def default_sensitive_term_matcher() -> SensitiveTermMatcher:
    return SensitiveTermMatcher()
