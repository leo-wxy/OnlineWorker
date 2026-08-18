from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from plugins.providers.builtin.codex.python.account_model import AccountRecord, classify_external_account, decode_jwt_payload
from plugins.providers.builtin.codex.python.account_store import AccountStore, AccountStoreError, atomic_write, operation_lock
from plugins.providers.builtin.codex.python.compat import export_cockpit_tools, parse_local_auth
from plugins.providers.builtin.codex.python.transport import default_codex_home


class ApplyError(RuntimeError):
    def __init__(self, code: str, *, rolled_back: bool = False):
        super().__init__(code)
        self.code = code
        self.rolled_back = rolled_back


def resolve_effective_home() -> Path:
    return Path(default_codex_home()).expanduser().resolve()


def project_auth_file(record: AccountRecord) -> dict:
    value = record.credentials
    if record.auth_mode == "apikey":
        return {"auth_mode": "apikey", "OPENAI_API_KEY": value["OPENAI_API_KEY"]}
    if record.auth_mode == "agentIdentity":
        return {"auth_mode": "agentIdentity", "agent_identity": deepcopy(value["agent_identity"])}
    if not value.get("access_token"):
        raise ApplyError("missing_access_token")
    if not value.get("id_token") and not value.get("refresh_token"):
        return {"OPENAI_API_KEY": None, "personal_access_token": value["access_token"]}
    return {
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": value.get("id_token", ""),
            "access_token": value["access_token"],
            "refresh_token": value.get("refresh_token", ""),
            "account_id": value.get("account_id") or None,
        },
        "last_refresh": value.get("last_refresh") or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def auth_file_to_portable(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    if value.get("auth_mode") == "apikey" and isinstance(value.get("OPENAI_API_KEY"), str):
        portable = deepcopy(value)
        if not isinstance(portable.get("email"), str):
            portable["email"] = "API Key"
        return portable
    if value.get("auth_mode") == "agentIdentity" and isinstance(value.get("agent_identity"), dict):
        identity = deepcopy(value["agent_identity"])
        portable = deepcopy(value)
        portable.update({
            "auth_mode": "agentIdentity",
            "agent_identity": identity,
            "account_id": str(identity.get("account_id", "")),
            "user_id": str(identity.get("chatgpt_user_id", "")),
            "email": identity.get("email") if isinstance(identity.get("email"), str) else "",
            "type": "codex",
        })
        return portable
    tokens = value.get("tokens")
    if not isinstance(tokens, dict):
        return None
    claims = decode_jwt_payload(tokens.get("id_token"))
    portable = deepcopy(value)
    portable.update({
        "id_token": tokens.get("id_token") if isinstance(tokens.get("id_token"), str) else "",
        "access_token": tokens.get("access_token") if isinstance(tokens.get("access_token"), str) else "",
        "refresh_token": tokens.get("refresh_token") if isinstance(tokens.get("refresh_token"), str) else "",
        "account_id": tokens.get("account_id") if isinstance(tokens.get("account_id"), str) else "",
        "last_refresh": value.get("last_refresh") if isinstance(value.get("last_refresh"), str) else "",
        "email": claims.get("email") if isinstance(claims.get("email"), str) else "",
        "type": "codex",
        "expired": "",
    })
    return portable


def _auth_path(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(home, 0o700)
    path = home / "auth.json"
    if path.is_symlink() or path.parent.resolve() != home:
        raise ApplyError("unsafe_auth_path")
    return path


def _contains(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _contains(actual[key], value) for key, value in expected.items())
    return actual == expected


def apply_account(store: AccountStore, account_id: str, *, home: Path | None = None) -> dict[str, object]:
    effective_home = resolve_effective_home() if home is None else home.resolve()
    auth_path = _auth_path(effective_home)
    with operation_lock(store.root):
        record = store.get(account_id)
        old_auth = auth_path.read_bytes() if auth_path.exists() else None
        old_mode = auth_path.stat().st_mode & 0o777 if auth_path.exists() else None
        try:
            raw = json.dumps(project_auth_file(record), ensure_ascii=False, indent=2).encode()
            atomic_write(auth_path, raw, backup=auth_path.exists())
            if json.loads(auth_path.read_bytes()) != json.loads(raw):
                raise ApplyError("auth_readback_failed")
            return {"accountId": account_id, "applied": True}
        except Exception as exc:
            try:
                if old_auth is None:
                    auth_path.unlink(missing_ok=True)
                else:
                    atomic_write(auth_path, old_auth)
                    if old_mode is not None:
                        os.chmod(auth_path, old_mode)
            except Exception as rollback_exc:
                raise ApplyError("apply_failed", rolled_back=False) from rollback_exc
            if isinstance(exc, ApplyError):
                raise ApplyError(exc.code, rolled_back=True) from exc
            raise ApplyError("apply_failed", rolled_back=True) from exc


def refresh_current(store: AccountStore, *, home: Path | None = None) -> dict[str, object]:
    effective_home = resolve_effective_home() if home is None else home.resolve()
    auth_path = effective_home / "auth.json"
    if not auth_path.exists():
        return {"state": "none"}
    if auth_path.is_symlink():
        raise ApplyError("unsafe_auth_path")
    managed = store.list_records()
    try:
        auth = json.loads(auth_path.read_text(encoding="utf-8"))
        projected = [record for record in managed if _contains(auth, project_auth_file(record))]
        if len(projected) == 1:
            return {"state": "matched", "accountId": projected[0].identity_key, "display": projected[0].identity_display}
        if len(projected) > 1:
            return {"state": "ambiguous"}
        portable = auth_file_to_portable(auth)
        parsed = parse_local_auth(portable) if portable is not None else None
        current = parsed.records[0] if parsed and parsed.records else None
    except (OSError, json.JSONDecodeError):
        current = None
    state = classify_external_account(current, managed)
    matched = current.identity_key if current and state == "matched" else None
    return {"state": state, "accountId": matched, "display": current.identity_display if current else None}


def export_accounts(store: AccountStore, account_ids: list[str], destination: str | Path) -> dict[str, object]:
    path = Path(destination)
    if path.is_symlink():
        raise ApplyError("unsafe_export_path")
    parent = path.parent.resolve()
    target = parent / path.name
    records = [store.get(account_id) for account_id in account_ids]
    if not records:
        raise ApplyError("empty_selection")
    raw = export_cockpit_tools(records).encode()
    atomic_write(target, raw)
    return {"fileName": target.name, "count": len(records), "sizeBytes": len(raw)}
