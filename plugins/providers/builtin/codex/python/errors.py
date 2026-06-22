from __future__ import annotations


def is_codex_unmaterialized_error(error: object) -> bool:
    """判断 Codex 是否因 thread 尚未 materialize 而拒绝 resume/archive。"""
    text = str(error).lower()
    return (
        "not materialized yet" in text
        or "no rollout found for thread id" in text
        or "thread not found:" in text
    )
