from __future__ import annotations


def resolve_default_thread_adapter(state, ws):
    return state.get_adapter(ws.tool)


async def activate_default_new_thread(
    state,
    adapter,
    ws,
    workspace_id: str,
    thread_id: str,
    initial_text: str | None,
) -> None:
    await adapter.resume_thread(workspace_id, thread_id)
    if initial_text:
        await adapter.send_user_message(workspace_id, thread_id, initial_text)


async def archive_default_thread(state, ws, thread_id: str, active_adapter) -> None:
    await active_adapter.archive_thread(ws.daemon_workspace_id, thread_id)


async def interrupt_default_thread(
    state,
    ws,
    thread_info,
    active_adapter,
    turn_id: str,
) -> None:
    await active_adapter.turn_interrupt(ws.daemon_workspace_id, thread_info.thread_id, turn_id)
