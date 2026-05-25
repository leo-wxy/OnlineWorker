from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderApprovalRequest:
    request_id: Any
    thread_id: str | None
    command: str
    reason: str
    tool_name: str
    proposed_amendment: list = field(default_factory=list)
    amendment_decision: dict = field(default_factory=dict)
    tool_type: str = ""
    always_patterns: list = field(default_factory=list)
    approval_source: str = "app_server"


@dataclass(frozen=True)
class ProviderQuestionRequest:
    question_id: str
    thread_id: str | None
    header: str
    question: str
    options: list[dict[str, Any]]
    multiple: bool = False
    custom: bool = True
    sub_index: int = 0
    sub_total: int = 1
    tool_type: str = ""
    question_source: str = "app_server"


def create_provider_question_request(
    *,
    question_id: str,
    thread_id: str | None,
    header: str = "",
    question: str = "",
    options: list[dict[str, Any]] | None = None,
    multiple: bool = False,
    custom: bool = True,
    sub_index: int = 0,
    sub_total: int = 1,
    tool_type: str = "",
    question_source: str = "app_server",
) -> ProviderQuestionRequest:
    normalized_thread_id = str(thread_id).strip() if thread_id is not None else ""
    return ProviderQuestionRequest(
        question_id=str(question_id or ""),
        thread_id=normalized_thread_id or None,
        header=str(header or ""),
        question=str(question or ""),
        options=options if isinstance(options, list) else [],
        multiple=bool(multiple),
        custom=bool(custom),
        sub_index=int(sub_index or 0),
        sub_total=int(sub_total or 1),
        tool_type=str(tool_type or "").strip(),
        question_source=question_source,
    )


def parse_standard_question_request(
    payload: dict[str, Any] | None,
    *,
    provider_id: str = "",
    default_thread_id: str | None = None,
    question_source: str = "app_server",
) -> ProviderQuestionRequest:
    data = payload if isinstance(payload, dict) else {}
    thread_id = str(data.get("threadId") or data.get("thread_id") or default_thread_id or "").strip()
    options = data.get("options")
    return create_provider_question_request(
        question_id=str(data.get("questionId") or data.get("question_id") or ""),
        thread_id=thread_id or None,
        header=str(data.get("header") or ""),
        question=str(data.get("question") or ""),
        options=options if isinstance(options, list) else [],
        multiple=bool(data.get("multiple", False)),
        custom=bool(data.get("custom", True)),
        sub_index=int(data.get("subIndex") or data.get("sub_index") or 0),
        sub_total=int(data.get("subTotal") or data.get("sub_total") or 1),
        tool_type=str(data.get("_provider") or provider_id or "").strip(),
        question_source=question_source,
    )
