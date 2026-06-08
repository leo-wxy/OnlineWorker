from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "auth_header",
    "auth_token",
    "bearer",
    "cookie",
    "env",
    "password",
    "secret",
    "token",
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _is_sensitive_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _public_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        public: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                public[key_text] = "[redacted]"
            else:
                public[key_text] = _public_payload(item, depth=depth + 1)
        return public
    if isinstance(value, (list, tuple)):
        return [_public_payload(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 4000:
            return f"{value[:4000]}…"
        return value
    return str(value)


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_event(payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(_stable_json(payload).encode("utf-8")).hexdigest()
    return f"evt_{digest[:20]}"


@dataclass(frozen=True)
class MessageEvent:
    event_id: str
    kind: str
    provider_id: str = ""
    workspace_id: str = ""
    workspace_path: str = ""
    session_id: str = ""
    turn_id: str = ""
    source: str = ""
    created_at: float = 0.0
    dedupe_key: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionActivity:
    provider_id: str
    session_id: str
    workspace_id: str = ""
    workspace_path: str = ""
    title: str = ""
    status: str = "idle"
    attention_reason: str = ""
    attention_kind: str = ""
    request_id: str = ""
    approval_source: str = ""
    last_user_message: str = ""
    last_assistant_message: str = ""
    last_final_message: str = ""
    last_event_kind: str = ""
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "workspaceId": self.workspace_id,
            "workspacePath": self.workspace_path,
            "sessionId": self.session_id,
            "title": self.title,
            "status": self.status,
            "attentionReason": self.attention_reason,
            "attentionKind": self.attention_kind,
            "requestId": self.request_id,
            "approvalSource": self.approval_source,
            "lastUserMessage": self.last_user_message,
            "lastAssistantMessage": self.last_assistant_message,
            "lastFinalMessage": self.last_final_message,
            "lastEventKind": self.last_event_kind,
            "updatedAt": self.updated_at,
        }


def create_message_event(
    kind: str,
    *,
    provider_id: str = "",
    workspace_id: str = "",
    workspace_path: str = "",
    session_id: str = "",
    turn_id: str = "",
    source: str = "",
    payload: dict[str, Any] | None = None,
    dedupe_key: str = "",
    event_id: str = "",
    created_at: float | None = None,
) -> MessageEvent:
    timestamp = float(time.time() if created_at is None else created_at)
    public_payload = _public_payload(payload or {})
    normalized = {
        "kind": _clean(kind),
        "provider_id": _clean(provider_id),
        "workspace_id": _clean(workspace_id),
        "workspace_path": _clean(workspace_path),
        "session_id": _clean(session_id),
        "turn_id": _clean(turn_id),
        "source": _clean(source),
        "dedupe_key": _clean(dedupe_key),
        "payload": public_payload,
    }
    resolved_event_id = _clean(event_id) or _hash_event(
        normalized if dedupe_key else {**normalized, "created_at": timestamp}
    )
    return MessageEvent(
        event_id=resolved_event_id,
        kind=normalized["kind"],
        provider_id=normalized["provider_id"],
        workspace_id=normalized["workspace_id"],
        workspace_path=normalized["workspace_path"],
        session_id=normalized["session_id"],
        turn_id=normalized["turn_id"],
        source=normalized["source"],
        created_at=timestamp,
        dedupe_key=normalized["dedupe_key"],
        payload=public_payload,
    )
