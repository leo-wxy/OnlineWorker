from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from plugins.providers.builtin.codex.python.account_model import (
    AccountModelError,
    AccountRecord,
    AuthMode,
    create_account_record,
)


MAX_IMPORT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class ImportErrorInfo:
    code: str
    message: str


@dataclass(frozen=True)
class ParseItemResult:
    index: int
    status: Literal["accepted", "skipped", "rejected", "ambiguous"]
    record: AccountRecord | None = field(default=None, repr=False)
    error: ImportErrorInfo | None = None


@dataclass(frozen=True)
class ParseBatchResult:
    items: tuple[ParseItemResult, ...] = ()
    error: ImportErrorInfo | None = None

    @property
    def records(self) -> list[AccountRecord]:
        return [item.record for item in self.items if item.status == "accepted" and item.record is not None]


_ERRORS = {
    "invalid_json": "文件不是有效 JSON。",
    "too_large": "导入内容超过大小限制。",
    "unsupported_shape": "仅支持账号对象或账号数组。",
    "unsupported_version": "不支持该账号导出版本。",
    "invalid_item": "账号条目必须是对象。",
    "unsupported_auth_mode": "不支持该账号认证类型。",
    "missing_required_fields": "账号条目缺少必需字段。",
    "invalid_required_fields": "账号条目的必需字段类型无效。",
    "missing_identity": "无法确定账号身份。",
    "identity_mismatch": "账号身份字段不一致。",
}


def _error(code: str) -> ImportErrorInfo:
    return ImportErrorInfo(code, _ERRORS[code])


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _require_keys(item: dict[str, Any], names: tuple[str, ...]) -> None:
    if any(name not in item for name in names):
        raise AccountModelError("missing_required_fields")
    if any(not isinstance(item[name], str) for name in names):
        raise AccountModelError("invalid_required_fields")


def _validate_token(item: dict[str, Any]) -> AuthMode:
    _require_keys(
        item,
        ("id_token", "access_token", "refresh_token", "account_id", "last_refresh", "email", "type", "expired"),
    )
    if item["type"] != "codex":
        raise AccountModelError("invalid_required_fields")
    return "token"


def _validate_agent_identity(item: dict[str, Any]) -> AuthMode:
    _require_keys(item, ("auth_mode", "account_id", "user_id", "email", "type"))
    nested = item.get("agent_identity")
    if item["type"] != "codex" or not isinstance(nested, dict):
        raise AccountModelError("invalid_required_fields")
    _require_keys(nested, ("agent_runtime_id", "agent_private_key", "account_id", "chatgpt_user_id"))
    if not all(_text(nested[name]) for name in ("agent_runtime_id", "agent_private_key", "account_id", "chatgpt_user_id")):
        raise AccountModelError("missing_required_fields")
    if _text(item["account_id"]) != _text(nested["account_id"]) or _text(item["user_id"]) != _text(nested["chatgpt_user_id"]):
        raise AccountModelError("identity_mismatch")
    return "agentIdentity"


def _validate_api_key(item: dict[str, Any]) -> AuthMode:
    _require_keys(item, ("auth_mode", "OPENAI_API_KEY", "email"))
    if not _text(item["OPENAI_API_KEY"]):
        raise AccountModelError("missing_identity")
    return "apikey"


def _parse_item(item: object, *, source: str) -> AccountRecord:
    if not isinstance(item, dict):
        raise AccountModelError("invalid_item")
    auth_mode = item.get("auth_mode")
    if auth_mode == "agentIdentity":
        mode = _validate_agent_identity(item)
    elif auth_mode == "apikey":
        mode = _validate_api_key(item)
    elif auth_mode in (None, "", "oauth", "token"):
        mode = _validate_token(item)
    else:
        raise AccountModelError("unsupported_auth_mode")
    return create_account_record(item, auth_mode=mode, source=source)


def parse_cockpit_tools(raw: str | bytes | dict | list, *, source: str = "cockpit_tools") -> ParseBatchResult:
    if isinstance(raw, bytes):
        if len(raw) > MAX_IMPORT_BYTES:
            return ParseBatchResult(error=_error("too_large"))
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ParseBatchResult(error=_error("invalid_json"))
    elif isinstance(raw, str):
        if len(raw.encode("utf-8")) > MAX_IMPORT_BYTES:
            return ParseBatchResult(error=_error("too_large"))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return ParseBatchResult(error=_error("invalid_json"))
    else:
        parsed = raw

    if isinstance(parsed, dict) and "version" in parsed and "accounts" in parsed:
        return ParseBatchResult(error=_error("unsupported_version"))
    if isinstance(parsed, dict):
        values = [parsed]
    elif isinstance(parsed, list):
        values = parsed
    else:
        return ParseBatchResult(error=_error("unsupported_shape"))

    results: list[ParseItemResult] = []
    for index, item in enumerate(values):
        try:
            results.append(ParseItemResult(index, "accepted", _parse_item(item, source=source)))
        except AccountModelError as exc:
            code = exc.code if exc.code in _ERRORS else "invalid_item"
            results.append(ParseItemResult(index, "rejected", error=_error(code)))
    return ParseBatchResult(tuple(results))


def parse_local_auth(raw: str | bytes | dict | list) -> ParseBatchResult:
    return parse_cockpit_tools(raw, source="local_file")


def export_cockpit_tools(records: list[AccountRecord]) -> str:
    return json.dumps([record.credentials for record in records], ensure_ascii=False, indent=2)
