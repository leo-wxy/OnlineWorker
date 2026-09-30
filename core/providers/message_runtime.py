from __future__ import annotations

async def ensure_default_connected(state, adapter, ws_info, *, update, context, group_chat_id: int, src_topic_id):
    return adapter


async def send_default_message(
    state,
    adapter,
    ws_info,
    thread_info,
    *,
    update,
    context,
    group_chat_id: int,
    src_topic_id,
    text,
    has_photo: bool,
    attachments=None,
) -> None:
    if attachments:
        result = await adapter.send_user_message(
            ws_info.daemon_workspace_id,
            thread_info.thread_id,
            text,
            attachments=attachments,
        )
    else:
        result = await adapter.send_user_message(ws_info.daemon_workspace_id, thread_info.thread_id, text)
    if isinstance(result, dict) and str(result.get("status") or "") == "error":
        raise RuntimeError(str(result.get("error") or f"{ws_info.tool} send failed"))
    return result
