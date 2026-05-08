import re
from typing import Any, Optional


_NETWORK_ERROR_TYPES = (
    ConnectionError,
    TimeoutError,
    OSError,
)

_MARKDOWN_FINAL_RE = re.compile(
    r"(^\s{0,3}#{1,6}\s+)"
    r"|(^\s*```[A-Za-z0-9_+-]*\s*$)"
    r"|(^\s*[-*+]\s+)"
    r"|(^\s*\d+\.\s+)"
    r"|(^\s*>\s+)"
    r"|(\[[^\]]+\]\(https?://[^\s)]+\))"
    r"|(`[^`\n]+`)"
    r"|(\*\*[^*\n]+\*\*)"
    r"|(__[^_\n]+__)",
    re.MULTILINE,
)


def looks_like_markdown_final_text(text: str) -> bool:
    return bool(_MARKDOWN_FINAL_RE.search(text or ""))


def is_network_error(exc: Exception) -> bool:
    if isinstance(exc, _NETWORK_ERROR_TYPES):
        return True
    err_str = str(exc).lower()
    return any(
        keyword in err_str
        for keyword in (
            "connecterror",
            "timeout",
            "broken",
            "reset",
            "eof",
            "connectionreset",
            "brokenpipe",
            "brokenresource",
        )
    )


def build_incomplete_turn_text(partial_text: str, reason: str) -> str:
    base = (partial_text or "").strip()
    status_text = "已中断" if reason == "interrupted" else "已终止"
    notice = f"⚠️ 本轮回复{status_text}，以上内容不完整。请重试。"
    if base:
        return f"{base}\n\n{notice}"
    return notice


def extract_thread_id(event_params: dict) -> Optional[str]:
    return (
        event_params.get("threadId")
        or event_params.get("thread_id")
        or event_params.get("thread", {}).get("id")
        or event_params.get("item", {}).get("threadId")
    )


def extract_turn_id(event_params: dict) -> Optional[str]:
    item = event_params.get("item", {})
    turn = event_params.get("turn", {})
    return (
        event_params.get("turnId")
        or event_params.get("turn_id")
        or (turn.get("id") if isinstance(turn, dict) else None)
        or (turn.get("turnId") if isinstance(turn, dict) else None)
        or (item.get("turnId") if isinstance(item, dict) else None)
        or ((item.get("turn", {}) or {}).get("id") if isinstance(item, dict) else None)
    )


def normalize_streamed_reply_for_sync(text: str) -> str:
    normalized = (text or "").strip()
    for prefix in ("🤖 ", "💭 "):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    return normalized


def codex_semantic_payload(ctx) -> dict[str, Any]:
    if ctx.event.provider != "codex":
        return {}
    payload = ctx.event.semantic_payload
    return payload if isinstance(payload, dict) else {}


def codex_semantic_kind(ctx) -> str:
    if ctx.event.provider != "codex":
        return ""
    return str(ctx.event.semantic_kind or "").strip()
