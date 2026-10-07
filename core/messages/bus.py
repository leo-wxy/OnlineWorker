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
        self._delivery_subscribers: list[Callable] = []
        self._activity_projection = SessionActivityProjection()
        self._conversation_projection = SessionActivityProjection(full_conversation=True)
        self._hydrated_sessions: set[tuple[str, str]] = set()
        self._hidden_sessions: set[tuple[str, str]] = set()
        self.notification_summary = NotificationSummaryConsumer()

    def subscribe(self, callback: Callable[[MessageEvent], object]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def subscribe_delivery(self, callback) -> Callable[[], None]:
        self._delivery_subscribers.append(callback)

        def unsubscribe():
            if callback in self._delivery_subscribers:
                self._delivery_subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: MessageEvent, *, delivery_context=None) -> bool:
        session_key = (event.provider_id, event.session_id)
        if event.workspace_path.startswith("/"):
            activity = self.session_activity(*session_key) or {}
            workspace_path = activity.get("workspacePath") or ""
            if workspace_path.startswith("/") and workspace_path != event.workspace_path:
                return False
        if event.kind == "session.hidden":
            self._hidden_sessions.add(session_key)
        elif session_key in self._hidden_sessions:
            return False
        if event.dedupe_key and event.dedupe_key in self._seen_dedupe_keys:
            return False
        for subscriber in tuple(self._delivery_subscribers):
            try:
                if subscriber(event, delivery_context) is False:
                    return False
            except Exception:
                logger.warning("[message-bus] delivery subscriber failed kind=%s", event.kind, exc_info=True)
        if event.dedupe_key:
            self._seen_dedupe_keys.add(event.dedupe_key)

        if len(self._events) == self.max_events:
            evicted = self._events[0]
            if evicted.dedupe_key:
                self._seen_dedupe_keys.discard(evicted.dedupe_key)
        self._events.append(event)
        self._activity_projection.update(event)
        self._conversation_projection.update(event)
        if event.kind == "session.history.loaded" and event.payload.get("historyWindow") == 50:
            self._hydrated_sessions.add(session_key)
        elif event.kind in {"session.archived", "session.hidden"}:
            self._hydrated_sessions.discard(session_key)
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

    def session_conversation(self, provider_id: str, session_id: str) -> list[dict]:
        activity = self._conversation_projection.get(provider_id, session_id)
        return activity["conversationTurns"] if activity else []

    def session_send_recovery(self, provider_id: str, session_id: str) -> dict | None:
        activity = self._conversation_projection.get(provider_id, session_id)
        return activity.get("sendRecovery") or None if activity else None

    def session_history_loaded(self, provider_id: str, session_id: str) -> bool:
        return (provider_id, session_id) in self._hydrated_sessions
