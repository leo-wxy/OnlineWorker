from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserMessageSendRequest:
    source: str
    provider_id: str
    workspace_id: str
    thread_id: str
    text: str | None
    attachments: list[dict] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
