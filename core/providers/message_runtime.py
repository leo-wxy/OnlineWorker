from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _interrupt_active_turn(state, adapter, workspace_id: str, thread_id: str, *, label: str) -> None:
    st = state.streaming_turns.get(thread_id)
    if st is None or st.completed or not st.turn_id:
        return

    try:
        await adapter.turn_interrupt(workspace_id, thread_id, st.turn_id)
        logger.info(
            "[provider-message] 已中断活跃 %s turn thread=%s turn=%s",
            label,
            thread_id[:8],
            st.turn_id[:12],
        )
    except Exception as e:
        logger.warning(
            "[provider-message] 中断活跃 %s turn 失败，继续发送新消息 "
            "thread=%s turn=%s error=%s",
            label,
            thread_id[:8],
            st.turn_id[:12],
            e,
        )


async def ensure_default_connected(state, adapter, ws_info, *, update, context, group_chat_id: int, src_topic_id):
    return adapter


async def prepare_default_send(
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
) -> bool:
    workspace_id = ws_info.daemon_workspace_id
    await adapter.resume_thread(workspace_id, thread_info.thread_id)
    return True


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
) -> None:
    await adapter.send_user_message(ws_info.daemon_workspace_id, thread_info.thread_id, text)
