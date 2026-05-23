from __future__ import annotations

import inspect
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from core.notifications.events import NotificationEvent


class NotificationChannel(Protocol):
    name: str

    async def send(self, event: NotificationEvent):
        ...


@dataclass(frozen=True)
class NotificationSendResult:
    channel: str
    success: bool
    error: str = ""


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    skipped: bool = False
    reason: str = ""
    channels: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class NotificationRouter:
    def __init__(
        self,
        channels: Iterable[NotificationChannel] | None = None,
        *,
        ttl_seconds: float = 5 * 60,
        clock=None,
    ) -> None:
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock or time.time
        self._channels: dict[str, NotificationChannel] = {}
        self._seen_at: dict[str, float] = {}
        for channel in channels or ():
            self.register_channel(channel)

    def register_channel(self, channel: NotificationChannel) -> None:
        channel_name = str(getattr(channel, "name", "") or "").strip()
        if not channel_name:
            raise ValueError("Notification channel name is required")
        self._channels[channel_name] = channel

    def list_channels(self) -> tuple[str, ...]:
        return tuple(self._channels)

    async def notify(
        self,
        event: NotificationEvent,
        *,
        channel_names: Sequence[str] | None = None,
    ) -> NotificationResult:
        self._purge_expired()
        if event.dedupe_key in self._seen_at:
            return NotificationResult(sent=False, skipped=True, reason="deduped")

        targets = self._resolve_targets(channel_names)
        if not targets:
            return NotificationResult(sent=False, reason="no_channels")

        sent_channels: list[str] = []
        errors: list[str] = []
        for channel in targets:
            result = await self._send_to_channel(channel, event)
            if result.success:
                sent_channels.append(channel.name)
            elif result.error:
                errors.append(f"{result.channel}: {result.error}")

        if not sent_channels:
            return NotificationResult(sent=False, reason="all_channels_failed", errors=tuple(errors))

        self._seen_at[event.dedupe_key] = float(self._clock())
        return NotificationResult(sent=True, channels=tuple(sent_channels))

    def _resolve_targets(self, channel_names: Sequence[str] | None) -> list[NotificationChannel]:
        if channel_names is None:
            return list(self._channels.values())
        targets: list[NotificationChannel] = []
        for name in channel_names:
            channel = self._channels.get(str(name or "").strip())
            if channel is not None:
                targets.append(channel)
        return targets

    async def _send_to_channel(self, channel: NotificationChannel, event: NotificationEvent) -> NotificationSendResult:
        channel_name = str(getattr(channel, "name", "") or "").strip() or "unknown"
        try:
            result = channel.send(event)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            return NotificationSendResult(channel=channel_name, success=False, error=str(exc))

        if isinstance(result, NotificationSendResult):
            return result
        return NotificationSendResult(channel=channel_name, success=bool(result))

    def _purge_expired(self) -> None:
        if self.ttl_seconds <= 0:
            self._seen_at.clear()
            return
        now = float(self._clock())
        expired_keys = [
            key
            for key, seen_at in self._seen_at.items()
            if now - seen_at >= self.ttl_seconds
        ]
        for key in expired_keys:
            self._seen_at.pop(key, None)
