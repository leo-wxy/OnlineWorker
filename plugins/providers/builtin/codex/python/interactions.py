from __future__ import annotations

import json
import shlex
from typing import Any

from core.providers.interactions import (
    ProviderApprovalRequest,
    ProviderQuestionRequest,
    parse_standard_question_request,
)


SERVER_REQUEST_METHODS = (
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "execCommandApproval",
    "applyPatchApproval",
)


def _str_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _list_value(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _compact_permissions(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    compacted = {}
    for key, item in value.items():
        if item is None:
            continue
        if isinstance(item, dict):
            nested = _compact_permissions(item)
            if nested:
                compacted[key] = nested
        elif isinstance(item, list):
            compacted[key] = [entry for entry in item if entry is not None]
        else:
            compacted[key] = item
    return compacted


def _json_display(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _command_display(payload: dict[str, Any]) -> str:
    command = payload.get("command")
    if isinstance(command, list):
        return shlex.join([_str_value(item) for item in command])
    if command is not None:
        return _str_value(command)

    permissions = _compact_permissions(payload.get("permissions"))
    if permissions:
        return f"request permissions: {_json_display(permissions)}"

    grant_root = _str_value(payload.get("grantRoot") or payload.get("grant_root")).strip()
    if grant_root:
        return f"request file access: {grant_root}"

    file_changes = _dict_value(payload.get("fileChanges") or payload.get("file_changes"))
    if file_changes:
        paths = ", ".join(str(path) for path in list(file_changes.keys())[:5])
        more = " ..." if len(file_changes) > 5 else ""
        return f"apply patch: {paths}{more}"

    return ""


def _approval_decision_fields(payload: dict[str, Any]) -> tuple[list, dict]:
    available_decisions = _list_value(payload.get("availableDecisions"))
    for decision in available_decisions:
        if not isinstance(decision, dict):
            continue
        amendment = decision.get("acceptWithExecpolicyAmendment")
        if not isinstance(amendment, dict):
            continue
        proposed = _list_value(amendment.get("execpolicy_amendment"))
        return proposed, decision

    proposed = _list_value(payload.get("proposedExecpolicyAmendment"))
    permissions = _compact_permissions(payload.get("permissions"))
    if permissions:
        return proposed, {"permissions": permissions}
    return proposed, {}


def parse_approval_request(
    payload: dict[str, Any] | None,
    *,
    request_id: Any = None,
    provider_id: str = "codex",
    default_thread_id: str | None = None,
    approval_source: str = "app_server",
) -> ProviderApprovalRequest:
    data = _dict_value(payload)
    proposed_amendment, amendment_decision = _approval_decision_fields(data)
    thread_id = _str_value(
        data.get("threadId")
        or data.get("thread_id")
        or data.get("conversationId")
        or data.get("conversation_id")
        or default_thread_id
    ).strip()
    normalized_provider = _str_value(data.get("_provider") or provider_id).strip()

    return ProviderApprovalRequest(
        request_id=data.get("request_id") or data.get("requestId") or request_id,
        thread_id=thread_id or None,
        command=_command_display(data),
        reason=_str_value(data.get("reason") or data.get("justification")),
        tool_name=_str_value(data.get("toolName") or data.get("tool_name")).strip(),
        proposed_amendment=proposed_amendment,
        amendment_decision=amendment_decision,
        tool_type=normalized_provider,
        always_patterns=_list_value(data.get("_always_patterns")),
        approval_source=approval_source,
    )


def parse_question_request(
    payload: dict[str, Any] | None,
    *,
    provider_id: str = "codex",
    default_thread_id: str | None = None,
    question_source: str = "app_server",
) -> ProviderQuestionRequest:
    return parse_standard_question_request(
        payload,
        provider_id=provider_id,
        default_thread_id=default_thread_id,
        question_source=question_source,
    )
