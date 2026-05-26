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


@dataclass(frozen=True)
class UserMessageHookContext:
    source: str
    provider_id: str
    workspace_id: str
    thread_id: str
    has_attachments: bool
    is_command_dispatch: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserMessageHookResult:
    text: str
    changed: bool = False
    hook_id: str = ""
    reason: str = ""
