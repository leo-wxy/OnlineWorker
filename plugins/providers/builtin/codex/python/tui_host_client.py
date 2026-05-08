import asyncio
from typing import Optional

from config import get_data_dir
from plugins.providers.builtin.codex.python.tui_host_protocol import (
    build_send_message_request,
    decode_host_response,
    encode_host_request,
    host_socket_path,
    read_host_status,
)
from core.state import AppState
from core.storage import WorkspaceInfo


async def send_message_to_codex_tui_host(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    text: str,
    *,
    topic_id: Optional[int] = None,
    timeout_seconds: float = 5.0,
) -> dict:
    del ws

    data_dir = state.config.data_dir if state.config and state.config.data_dir else get_data_dir()
    status = read_host_status(data_dir)
    if not status:
        raise RuntimeError("未检测到 codex TUI host，请先用 codex_tui_host 启动当前 thread")

    active_thread_id = status.get("active_thread_id")
    if active_thread_id != thread_id:
        raise RuntimeError(
            f"当前 TUI 绑定 thread={active_thread_id or '<none>'}，无法投递到 thread={thread_id}"
        )

    socket_path = status.get("socket_path") or host_socket_path(data_dir)
    if not socket_path:
        raise RuntimeError("缺少 codex TUI host socket 路径")

    request = build_send_message_request(thread_id=thread_id, text=text, topic_id=topic_id)
    reader, writer = await asyncio.wait_for(
        asyncio.open_unix_connection(socket_path),
        timeout=timeout_seconds,
    )
    try:
        writer.write(encode_host_request(request))
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
    finally:
        writer.close()
        await writer.wait_closed()

    response = decode_host_response(raw)
    if not response.get("ok"):
        raise RuntimeError(response.get("error") or "codex TUI host 请求失败")
    return response
