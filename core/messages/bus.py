from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable

from core.messages.events import MessageEvent
from core.messages.notification_summary import NotificationSummaryConsumer
from core.messages.projections import SessionActivityProjection

logger = logging.getLogger(__name__)


class MessageEventBus:
    def __init__(self, *, max_events: int = 500) -> None:
        self.max_events = max(1, int(max_events))
        self._events: deque[MessageEvent] = deque(maxlen=self.max_events)
        self._seen_dedupe_keys: set[str] = set()
        self._subscribers: list[Callable[[MessageEvent], object]] = []
        self._activity_projection = SessionActivityProjection()
        self.notification_summary = NotificationSummaryConsumer()

    def subscribe(self, callback: Callable[[MessageEvent], object]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def publish(self, event: MessageEvent) -> bool:
        if event.dedupe_key and event.dedupe_key in self._seen_dedupe_keys:
            return False
        if event.dedupe_key:
            self._seen_dedupe_keys.add(event.dedupe_key)

        self._events.append(event)
        self._activity_projection.update(event)
        self.notification_summary.observe(event)

        for subscriber in tuple(self._subscribers):
            try:
                subscriber(event)
            except Exception:
                logger.warning(
                    "[message-bus] subscriber failed kind=%s event_id=%s",
                    event.kind,
                    event.event_id,
                    exc_info=True,
                )
        return True

    def recent_events(self, limit: int | None = None) -> list[dict]:
        events = list(self._events)
        if limit is not None:
            events = events[-max(0, int(limit)):]
        return [event.to_dict() for event in events]

    def session_activities(self) -> list[dict]:
        return self._activity_projection.list()

    def session_activity(self, provider_id: str, session_id: str) -> dict | None:
        return self._activity_projection.get(provider_id, session_id)
