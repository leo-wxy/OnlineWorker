from __future__ import annotations

from core.user_messages.contracts import UserMessageHookResult, UserMessageSendRequest


MESSAGE_REWRITE_TEMPORARILY_DISABLED = True


async def prepare_user_message_text(
    state,
    request: UserMessageSendRequest,
) -> UserMessageHookResult:
    return UserMessageHookResult(text=str(request.text or ""))
