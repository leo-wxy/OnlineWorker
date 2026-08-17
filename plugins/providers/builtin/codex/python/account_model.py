from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal


AuthMode = Literal["token", "agentIdentity", "apikey"]


class AccountModelError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class AccountRecord:
    auth_mode: AuthMode
    identity_key: str
    identity_display: str
    source: str
    credentials: dict[str, Any] = field(repr=False)


@dataclass(frozen=True)
class UpsertResult:
    status: Literal["inserted", "updated", "ambiguous"]
    index: int | None
    record: AccountRecord | None = field(repr=False)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _identity_parts(credentials: dict[str, Any], auth_mode: AuthMode) -> tuple[str, str]:
    email = _text(credentials.get("email"))
    if auth_mode == "token":
        identity = _text(credentials.get("account_id")) or email.casefold()
        if not identity:
            raise AccountModelError("missing_identity")
        return identity, email or identity

    if auth_mode == "agentIdentity":
        nested = credentials.get("agent_identity")
        if not isinstance(nested, dict):
            raise AccountModelError("missing_identity")
        account_id = _text(nested.get("account_id")) or _text(credentials.get("account_id"))
        user_id = _text(nested.get("chatgpt_user_id")) or _text(credentials.get("user_id"))
        runtime_id = _text(nested.get("agent_runtime_id"))
        if not account_id or not user_id or not runtime_id:
            raise AccountModelError("missing_identity")
        return "\0".join((account_id, user_id, runtime_id)), email or account_id

    api_key = _text(credentials.get("OPENAI_API_KEY"))
    if not api_key:
        raise AccountModelError("missing_identity")
    display = email or _text(credentials.get("api_provider_name")) or "API Key"
    return api_key, display


def create_account_record(
    credentials: dict[str, Any],
    *,
    auth_mode: AuthMode,
    source: str,
) -> AccountRecord:
    identity, display = _identity_parts(credentials, auth_mode)
    digest = hashlib.sha256(f"{auth_mode}\0{identity}".encode()).hexdigest()
    return AccountRecord(
        auth_mode=auth_mode,
        identity_key=f"{auth_mode}:{digest}",
        identity_display=display,
        source=source,
        credentials=deepcopy(credentials),
    )


def stable_identity_key(record: AccountRecord) -> str:
    return record.identity_key


def _deep_merge(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def upsert_account(records: list[AccountRecord], incoming: AccountRecord) -> UpsertResult:
    matches = [index for index, record in enumerate(records) if record.identity_key == incoming.identity_key]
    if len(matches) > 1:
        return UpsertResult("ambiguous", None, None)
    if not matches:
        records.append(incoming)
        return UpsertResult("inserted", len(records) - 1, incoming)

    index = matches[0]
    updated = create_account_record(
        _deep_merge(records[index].credentials, incoming.credentials),
        auth_mode=incoming.auth_mode,
        source=incoming.source,
    )
    records[index] = updated
    return UpsertResult("updated", index, updated)


def classify_external_account(
    current: AccountRecord | None,
    managed: list[AccountRecord],
) -> Literal["matched", "unmanaged", "ambiguous"]:
    if current is None:
        return "unmanaged"
    matches = sum(record.identity_key == current.identity_key for record in managed)
    if matches > 1:
        return "ambiguous"
    return "matched" if matches == 1 else "unmanaged"


def redacted_index_dto(
    record: AccountRecord,
    *,
    is_current: bool = False,
    external_state: str = "managed",
) -> dict[str, object]:
    _, digest = record.identity_key.split(":", 1)
    return {
        "id": record.identity_key,
        "stableIdentityDisplay": record.identity_display,
        "identityKeyHash": digest,
        "authMode": record.auth_mode,
        "source": record.source,
        "isCurrent": is_current,
        "externalState": external_state,
    }
