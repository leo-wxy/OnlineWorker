from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from plugins.providers.builtin.codex.python.account_store import AccountStore, AccountStoreError, operation_lock
from plugins.providers.builtin.codex.python.apply import ApplyError, apply_account, export_accounts, refresh_current, resolve_effective_home
from plugins.providers.builtin.codex.python.compat import ParseBatchResult, parse_cockpit_tools
from plugins.providers.builtin.codex.python.oauth import OAuthError, cancel_oauth, complete_oauth, start_oauth
from plugins.providers.builtin.codex.python.quota import QuotaError, fetch_quota, refresh_oauth_record
from plugins.providers.builtin.codex.python.session_assets import (
    SessionAssetError,
    list_sessions,
    list_trash,
    repair_visibility,
    restore_sessions,
    trash_sessions,
)
from plugins.providers.builtin.codex.python.session_package import export_sessions, import_sessions


_FORBIDDEN_KEYS = {
    "home", "path", "authpath", "sessionroot", "codexhome", "dataroot", "nativepaths",
    "endpoint", "issuer", "clientid", "clientsecret", "authorizeendpoint", "tokenendpoint",
}


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = "".join(character for character in str(key).casefold() if character.isalnum())
            if normalized in _FORBIDDEN_KEYS or _has_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_has_forbidden_key(item) for item in value)
    return False


def _ok(**data: object) -> dict[str, object]:
    return {"ok": True, **data}


def _failure(code: str) -> dict[str, object]:
    messages = {
        "invalid_request": "账号操作参数无效。",
        "unsupported_action": "不支持该账号操作。",
        "import_failed": "没有可导入的账号。",
        "oauth_not_pending": "OAuth 授权已失效，请重新开始。",
        "oauth_expired": "OAuth 授权已过期，请重新开始。",
        "oauth_cancelled": "OAuth 授权已取消。",
        "state_mismatch": "OAuth 回调校验失败。",
        "apply_failed": "账号应用失败，原配置已恢复。",
    }
    return {"ok": False, "error": {"code": code, "message": messages.get(code, "账号操作失败。")}}


def _import_result(store: AccountStore, parsed: ParseBatchResult) -> dict[str, object]:
    if parsed.error:
        return _failure(parsed.error.code)
    items: list[dict[str, object]] = []
    imported = 0
    for item in parsed.items:
        if item.record is None:
            items.append({"index": item.index, "status": item.status, "error": item.error.code if item.error else None})
            continue
        status = store.upsert(item.record)
        imported += 1
        items.append({"index": item.index, "status": status, "accountId": item.record.identity_key})
    if not imported:
        return {**_failure("import_failed"), "items": items}
    return _ok(imported=imported, items=items)


def _trusted_path(context: dict, mode: str) -> str:
    values = context.get("native_paths")
    matches = [item.get("path") for item in values if isinstance(item, dict) and item.get("mode") == mode] if isinstance(values, list) else []
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise AccountStoreError("invalid_capability")
    return matches[0]


def _refresh_quota(store: AccountStore, account_id: str) -> None:
    record = store.get(account_id)
    try:
        quota = fetch_quota(record)
    except QuotaError as exc:
        if exc.code == "unauthorized":
            try:
                record = refresh_oauth_record(record)
                store.upsert(record)
                quota = fetch_quota(record)
            except QuotaError as refresh_error:
                exc = refresh_error
            else:
                store.set_quota(account_id, quota)
                return
        quota = {
            "status": "error",
            "errorCode": exc.code,
            "refreshedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    store.set_quota(account_id, quota)


def handle_account_feature(*, action: str, payload: Any, context: Any) -> dict[str, object]:
    if not isinstance(payload, dict) or not isinstance(context, dict) or _has_forbidden_key(payload):
        return _failure("invalid_request")
    data_root = context.get("data_root")
    if not isinstance(data_root, str) or not data_root:
        return _failure("invalid_request")
    store = AccountStore(data_root)
    try:
        if action == "accounts.list":
            current = refresh_current(store)
            current_id = current.get("accountId")
            return _ok(
                current=current,
                accounts=store.list_redacted(current_id if isinstance(current_id, str) else None),
            )
        if action == "accounts.import":
            return _import_result(store, parse_cockpit_tools(payload.get("content"), source=str(payload.get("source") or "manual")))
        if action == "oauth.start":
            return _ok(**start_oauth(store.root, payload.get("redirectUri")))
        if action == "oauth.cancel":
            cancel_oauth(store.root)
            return _ok(cancelled=True)
        if action == "oauth.complete":
            with operation_lock(store.root):
                raw = complete_oauth(store.root, payload.get("callbackUrl"))
                result = _import_result(store, parse_cockpit_tools(raw, source="oauth"))
                if result.get("ok"):
                    cancel_oauth(store.root)
                return result
        if action == "accounts.refresh":
            ids = payload.get("accountIds")
            if ids is not None and (not isinstance(ids, list) or not all(isinstance(item, str) for item in ids)):
                return _failure("invalid_request")
            targets = list(dict.fromkeys(ids if ids is not None else [item["id"] for item in store.list_redacted()]))
            for account_id in targets:
                _refresh_quota(store, account_id)
            return _ok(refreshed=len(targets))
        if action == "accounts.apply":
            account_id = payload.get("accountId")
            if not isinstance(account_id, str):
                return _failure("invalid_request")
            result = apply_account(store, account_id)
            return _ok(result=result)
        if action == "accounts.export":
            ids = payload.get("accountIds")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                return _failure("invalid_request")
            return _ok(export=export_accounts(store, ids, _trusted_path(context, "save")))
        if action == "sessions.list":
            home = resolve_effective_home()
            query = payload.get("query") if isinstance(payload.get("query"), str) else ""
            kind = payload.get("kind") if isinstance(payload.get("kind"), str) else "conversation"
            if payload.get("trash") is True:
                return _ok(sessions=list_trash(store.root), usage30d={"cost": {"status": "unavailable"}})
            return _ok(**list_sessions(home, query=query, include_usage=False, kind=kind))
        if action == "sessions.usage":
            return _ok(usage30d=list_sessions(resolve_effective_home(), kind="conversation")["usage30d"])
        if action == "sessions.export":
            ids = payload.get("sessionIds")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                return _failure("invalid_request")
            with operation_lock(store.root):
                return _ok(export=export_sessions(resolve_effective_home(), ids, _trusted_path(context, "save")))
        if action == "sessions.import":
            with operation_lock(store.root):
                return _ok(importResult=import_sessions(resolve_effective_home(), _trusted_path(context, "open")))
        if action == "sessions.trash":
            ids = payload.get("sessionIds")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                return _failure("invalid_request")
            return _ok(trash=trash_sessions(store.root, resolve_effective_home(), ids))
        if action == "sessions.restore":
            ids = payload.get("sessionIds")
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                return _failure("invalid_request")
            return _ok(restore=restore_sessions(store.root, resolve_effective_home(), ids))
        if action == "sessions.repair":
            with operation_lock(store.root):
                return _ok(repair=repair_visibility(resolve_effective_home()))
        return _failure("unsupported_action")
    except (AccountStoreError, OAuthError, QuotaError, ApplyError, SessionAssetError, OSError, ValueError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        code = getattr(exc, "code", "action_failed")
        return _failure(code)
