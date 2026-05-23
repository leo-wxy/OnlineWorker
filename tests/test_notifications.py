from __future__ import annotations

import textwrap
from unittest.mock import AsyncMock

import pytest

from core.notifications.events import NotificationEvent, format_notification_text
from core.notifications.registry import (
    NotificationPluginDescriptor,
    _load_bundled_notification_descriptors,
    iter_overlay_notification_manifest_paths,
    load_notification_plugins,
)
from core.notifications.router import NotificationRouter, NotificationSendResult
from core.notifications.runtime import build_notification_channels, build_notification_router
from plugins.notifications.builtin.telegram.python.channel import (
    TelegramNotificationChannel,
    create_notification_descriptor,
)


class RecordingChannel:
    name = "recording"

    def __init__(self):
        self.events = []

    async def send(self, event):
        self.events.append(event)
        return True


class FailingChannel:
    name = "failing"

    def __init__(self):
        self.calls = 0

    async def send(self, event):
        self.calls += 1
        return False


class ErrorResultChannel:
    name = "error-result"

    async def send(self, event):
        return NotificationSendResult(
            channel=self.name,
            success=False,
            error="Forbidden: bot can't initiate conversation with a user",
        )


def _event(**overrides):
    values = {
        "status": "needs_action",
        "agent_name": "Codex",
        "task_name": "Phase 6",
        "message": "需要处理",
        "task_id": "task-1",
        "agent_id": "codex-1",
    }
    values.update(overrides)
    return NotificationEvent(**values)


def test_notification_event_formats_minimal_text_and_dedupe_key():
    event = _event()

    assert event.dedupe_key == "task-1:codex-1:needs_action"
    assert format_notification_text(event) == "需要处理 · Codex · Phase 6\n需要处理"


def test_notification_runtime_builds_router_from_enabled_config(monkeypatch):
    captured = {}

    def create_channel(**kwargs):
        captured.update(kwargs)
        channel = RecordingChannel()
        channel.name = "custom"
        return channel

    monkeypatch.setattr(
        "core.notifications.runtime.load_notification_plugins",
        lambda: {
            "custom": NotificationPluginDescriptor(
                name="custom",
                label="Custom",
                channel_factory=create_channel,
            )
        },
    )
    app_config = type("Config", (), {})()
    app_config.enabled_notification_channels = [
        type(
            "ChannelConfig",
            (),
            {
                "name": "custom",
                "config": {"webhook_url": "https://example.invalid/webhook"},
            },
        )()
    ]

    channels = build_notification_channels(app_config)
    router = build_notification_router(app_config)

    assert [channel.name for channel in channels] == ["custom"]
    assert router.list_channels() == ("custom",)
    assert captured["config"] == {"webhook_url": "https://example.invalid/webhook"}


def test_notification_runtime_skips_channels_with_incomplete_config(monkeypatch):
    def create_channel(**kwargs):
        raise ValueError("missing config")

    monkeypatch.setattr(
        "core.notifications.runtime.load_notification_plugins",
        lambda: {
            "custom": NotificationPluginDescriptor(
                name="custom",
                label="Custom",
                channel_factory=create_channel,
            )
        },
    )
    app_config = type("Config", (), {})()
    app_config.enabled_notification_channels = [
        type("ChannelConfig", (), {"name": "custom", "config": {}})()
    ]

    router = build_notification_router(app_config)

    assert router.list_channels() == ()


@pytest.mark.asyncio
async def test_notification_router_dedupes_same_task_agent_status():
    channel = RecordingChannel()
    router = NotificationRouter(channels=[channel], clock=lambda: 100.0)

    first = await router.notify(_event())
    second = await router.notify(_event())

    assert first.sent is True
    assert second.sent is False
    assert second.skipped is True
    assert second.reason == "deduped"
    assert len(channel.events) == 1


@pytest.mark.asyncio
async def test_notification_router_default_dedupe_window_expires_after_five_minutes():
    now = 100.0
    channel = RecordingChannel()
    router = NotificationRouter(channels=[channel], clock=lambda: now)

    first = await router.notify(_event())
    now += 301.0
    second = await router.notify(_event())

    assert first.sent is True
    assert second.sent is True
    assert len(channel.events) == 2


@pytest.mark.asyncio
async def test_notification_router_sends_status_change_as_new_event():
    channel = RecordingChannel()
    router = NotificationRouter(channels=[channel], clock=lambda: 100.0)

    await router.notify(_event(status="needs_action"))
    result = await router.notify(_event(status="failed", message="失败了"))

    assert result.sent is True
    assert [event.status for event in channel.events] == ["needs_action", "failed"]


@pytest.mark.asyncio
async def test_notification_router_does_not_cache_failed_delivery():
    channel = FailingChannel()
    router = NotificationRouter(channels=[channel], clock=lambda: 100.0)

    first = await router.notify(_event())
    second = await router.notify(_event())

    assert first.sent is False
    assert first.reason == "all_channels_failed"
    assert second.sent is False
    assert channel.calls == 2


@pytest.mark.asyncio
async def test_notification_router_reports_channel_errors():
    channel = ErrorResultChannel()
    router = NotificationRouter(channels=[channel], clock=lambda: 100.0)

    result = await router.notify(_event())

    assert result.sent is False
    assert result.reason == "all_channels_failed"
    assert result.errors == (
        "error-result: Forbidden: bot can't initiate conversation with a user",
    )


def test_builtin_telegram_descriptor_is_notification_plugin():
    descriptor = create_notification_descriptor()

    assert isinstance(descriptor, NotificationPluginDescriptor)
    assert descriptor.name == "telegram"
    assert descriptor.default_enabled is True
    assert descriptor.channel_factory is not None


def test_bundled_notification_catalog_supports_manifestless_runtime(monkeypatch):
    monkeypatch.setattr(
        "core.notifications.registry.iter_builtin_notification_manifest_paths",
        lambda: [],
    )

    descriptors = load_notification_plugins([])

    assert list(descriptors) == ["telegram"]
    assert descriptors["telegram"].channel_factory is not None


def test_bundled_notification_catalog_has_telegram_descriptor():
    descriptors = _load_bundled_notification_descriptors()

    assert list(descriptors) == ["telegram"]


@pytest.mark.asyncio
async def test_telegram_notification_channel_sends_formatted_text():
    bot = type("Bot", (), {})()
    bot.send_message = AsyncMock()
    channel = TelegramNotificationChannel(
        bot=bot,
        bot_token="ignored-in-test",
        recipient_user_id="456",
    )

    result = await channel.send(_event(status="completed", message="已完成"))

    assert result.success is True
    assert result.channel == "telegram"
    bot.send_message.assert_awaited_once_with(
        chat_id=456,
        text="完成 · Codex · Phase 6\n已完成",
    )


@pytest.mark.asyncio
async def test_telegram_notification_factory_uses_plugin_config():
    bot = type("Bot", (), {})()
    bot.send_message = AsyncMock()

    descriptor = create_notification_descriptor()
    channel = descriptor.channel_factory(
        config={"bot_token": "notify-token", "recipient_user_id": "789"},
        bot=bot,
    )
    result = await channel.send(_event())

    assert result.success is True
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 789


def test_telegram_descriptor_declares_plugin_settings():
    descriptor = create_notification_descriptor()

    field_keys = [field["key"] for field in descriptor.settings_fields]
    assert field_keys == ["bot_token", "recipient_user_id"]
    assert descriptor.settings_fields[0]["type"] == "secret"


def test_notification_registry_loads_external_plugin(tmp_path):
    plugin_dir = tmp_path / "custom_notify"
    python_dir = plugin_dir / "python"
    python_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            """
            schema_version: 1
            id: custom_notify
            kind: notification
            label: Custom Notify
            entrypoints:
              python_descriptor: custom_notify.python.channel:create_notification_descriptor
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (python_dir / "__init__.py").write_text("", encoding="utf-8")
    (python_dir / "channel.py").write_text(
        textwrap.dedent(
            """
            from core.notifications.registry import NotificationPluginDescriptor


            def create_notification_descriptor():
                return NotificationPluginDescriptor(
                    name="custom_notify",
                    label="Custom Notify",
                    default_enabled=True,
                    channel_factory=lambda **kwargs: None,
                )
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    descriptors = load_notification_plugins([tmp_path])

    assert "telegram" in descriptors
    assert "custom_notify" in descriptors
    assert descriptors["custom_notify"].label == "Custom Notify"


def test_notification_registry_reads_overlay_env(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "env_notify"
    python_dir = plugin_dir / "python"
    python_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        textwrap.dedent(
            """
            schema_version: 1
            id: env_notify
            kind: notification
            label: Env Notify
            entrypoints:
              python_descriptor: env_notify.python.channel:create_notification_descriptor
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (python_dir / "__init__.py").write_text("", encoding="utf-8")
    (python_dir / "channel.py").write_text(
        textwrap.dedent(
            """
            from core.notifications.registry import NotificationPluginDescriptor


            def create_notification_descriptor():
                return NotificationPluginDescriptor(
                    name="env_notify",
                    label="Env Notify",
                    default_enabled=False,
                    channel_factory=lambda **kwargs: None,
                )
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ONLINEWORKER_NOTIFICATION_OVERLAY", str(tmp_path))

    manifests = iter_overlay_notification_manifest_paths()
    descriptors = load_notification_plugins()

    assert manifests == [plugin_dir / "plugin.yaml"]
    assert "telegram" in descriptors
    assert descriptors["env_notify"].default_enabled is False
