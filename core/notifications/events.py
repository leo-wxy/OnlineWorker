from __future__ import annotations

from dataclasses import dataclass


NOTIFICATION_STATUSES = frozenset({"needs_action", "failed", "completed"})
STATUS_LABELS = {
    "needs_action": "需要处理",
    "failed": "失败",
    "completed": "完成",
}


def _clean(value: str) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class NotificationEvent:
    status: str
    agent_name: str
    task_name: str
    message: str
    task_id: str
    agent_id: str

    def __post_init__(self) -> None:
        normalized_status = _clean(self.status)
        if normalized_status not in NOTIFICATION_STATUSES:
            raise ValueError(f"Unsupported notification status: {self.status!r}")
        object.__setattr__(self, "status", normalized_status)

        for field_name in ("agent_name", "task_name", "message", "task_id", "agent_id"):
            value = _clean(getattr(self, field_name))
            if not value:
                raise ValueError(f"NotificationEvent.{field_name} is required")
            object.__setattr__(self, field_name, value)

    @property
    def dedupe_key(self) -> str:
        return f"{self.task_id}:{self.agent_id}:{self.status}"


def format_notification_text(event: NotificationEvent) -> str:
    label = STATUS_LABELS[event.status]
    return f"{label} · {event.agent_name} · {event.task_name}\n{event.message}"
