from __future__ import annotations

from telegram import Bot

from bot.utils import truncate_text
from core.notifications.events import NotificationEvent, format_notification_text
from core.notifications.registry import NotificationPluginDescriptor
from core.notifications.router import NotificationSendResult


class TelegramNotificationChannel:
    name = "telegram"

    def __init__(
        self,
        *,
        bot_token: str,
        recipient_user_id: str | int,
        bot: Bot | None = None,
    ) -> None:
        self.bot = bot or Bot(token=str(bot_token or "").strip())
        self.recipient_user_id = int(str(recipient_user_id or "").strip())

    async def send(self, event: NotificationEvent) -> NotificationSendResult:
        try:
            await self.bot.send_message(
                chat_id=self.recipient_user_id,
                text=truncate_text(format_notification_text(event)),
            )
        except Exception as exc:
            return NotificationSendResult(channel=self.name, success=False, error=str(exc))
        return NotificationSendResult(channel=self.name, success=True)


def create_telegram_channel(**kwargs) -> TelegramNotificationChannel:
    config = kwargs.get("config") if isinstance(kwargs.get("config"), dict) else {}

    bot_token = kwargs.get("bot_token") or config.get("bot_token")
    recipient_user_id = kwargs.get("recipient_user_id") or config.get("recipient_user_id")

    return TelegramNotificationChannel(
        bot_token=bot_token,
        recipient_user_id=recipient_user_id,
        bot=kwargs.get("bot"),
    )


def create_notification_descriptor() -> NotificationPluginDescriptor:
    return NotificationPluginDescriptor(
        name="telegram",
        label="Telegram",
        default_enabled=True,
        channel_factory=create_telegram_channel,
        settings_fields=(
            {
                "key": "bot_token",
                "label": "Bot Token",
                "type": "secret",
                "required": True,
                "description": "Telegram bot token used only for notification delivery.",
            },
            {
                "key": "recipient_user_id",
                "label": "Recipient User ID",
                "type": "string",
                "required": True,
                "default": "",
                "description": "Telegram user id that receives notification messages.",
            },
        ),
    )
