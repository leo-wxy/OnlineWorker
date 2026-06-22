from core.providers.registry import get_provider
from core.storage import ThreadInfo, WorkspaceInfo
from bot.handlers.common import _send_to_group
from bot.keyboards import build_thread_control_keyboard


def thread_interrupt_supported(state, ws: WorkspaceInfo) -> bool:
    provider = get_provider(ws.tool)
    hooks = provider.thread_hooks if provider is not None else None
    callback = getattr(hooks, "interrupt_supported", None) if hooks is not None else None
    if callable(callback):
        return bool(callback(state, ws))
    return True


def build_thread_control_text(state, ws: WorkspaceInfo, thread_info: ThreadInfo, *, intro: str | None = None) -> str:
    lines = []
    if intro:
        lines.append(intro.strip())

    if lines:
        lines.append("")

    lines.extend(
        [
            "在这个 Thread Topic 中：",
            "• `/archive` `/history` `/skills` 由 onlineWorker 本地处理",
            f"• 除上述控制命令外，其余文本与 `/xxx` 默认发送给 `{ws.tool}`",
            "• 线程控制也可以使用下方按钮",
            f"• Thread ID：`{thread_info.thread_id}`",
        ]
    )

    if not thread_interrupt_supported(state, ws):
        lines.append("• 当前主控模式下暂不支持从 TG 远程中断")

    return "\n".join(lines)


async def send_thread_control_panel(
    state,
    bot,
    group_chat_id: int,
    ws: WorkspaceInfo,
    thread_info: ThreadInfo,
    *,
    intro: str | None = None,
    topic_id: int | None = None,
) -> None:
    if topic_id is None:
        workspace_id = state.get_workspace_storage_key(ws) or ws.daemon_workspace_id or f"{ws.tool}:{ws.name}"
        topic_id = state.get_thread_topic_id(workspace_id, ws, thread_info)
    await _send_to_group(
        bot,
        group_chat_id,
        build_thread_control_text(state, ws, thread_info, intro=intro),
        topic_id=topic_id,
        parse_mode="Markdown",
        reply_markup=build_thread_control_keyboard(
            allow_interrupt=thread_interrupt_supported(state, ws),
        ),
    )
