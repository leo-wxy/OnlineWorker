from __future__ import annotations

from typing import Any

from core.notifications.registry import load_notification_plugins
from core.notifications.router import NotificationChannel, NotificationRouter


def build_notification_channels(app_config: Any) -> list[NotificationChannel]:
    descriptors = load_notification_plugins()
    channels: list[NotificationChannel] = []

    for channel_config in getattr(app_config, "enabled_notification_channels", ()):
        channel_id = str(getattr(channel_config, "name", "") or "").strip()
        if not channel_id:
            continue
        descriptor = descriptors.get(channel_id)
        if descriptor is None or descriptor.channel_factory is None:
            continue

        plugin_config = getattr(channel_config, "config", {}) or {}
        try:
            channel = descriptor.channel_factory(config=dict(plugin_config))
        except Exception:
            continue
        if channel is not None:
            channels.append(channel)

    return channels


def build_notification_router(app_config: Any, **kwargs: Any) -> NotificationRouter:
    return NotificationRouter(channels=build_notification_channels(app_config), **kwargs)
