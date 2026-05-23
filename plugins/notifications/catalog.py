from __future__ import annotations

from collections.abc import Callable, Iterable

from core.notifications.registry import NotificationPluginDescriptor
from plugins.notifications.builtin.telegram.python.channel import (
    create_notification_descriptor as create_telegram_descriptor,
)


def iter_bundled_notification_factories() -> Iterable[Callable[[], NotificationPluginDescriptor]]:
    return (create_telegram_descriptor,)
