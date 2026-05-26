from __future__ import annotations

from core.user_messages.contracts import (
    UserMessageHookContext,
    UserMessageHookResult,
    UserMessageSendRequest,
)
from core.user_messages.hooks import run_before_user_message_send_hooks


async def prepare_user_message_text(
    state,
    request: UserMessageSendRequest,
) -> UserMessageHookResult:
    metadata = request.metadata or {}
    context = UserMessageHookContext(
        source=request.source,
        provider_id=request.provider_id,
        workspace_id=request.workspace_id,
        thread_id=request.thread_id,
        has_attachments=bool(request.attachments),
        is_command_dispatch=bool(metadata.get("is_command_dispatch", False)),
        metadata=metadata,
    )
    return await run_before_user_message_send_hooks(state, request.text, context)
