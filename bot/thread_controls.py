from plugins.providers.builtin.codex.python.tui_bridge import is_codex_local_owner_mode
from core.storage import ThreadInfo, WorkspaceInfo
from bot.handlers.common import _send_to_group
from bot.keyboards import build_thread_control_keyboard


def thread_interrupt_supported(state, ws: WorkspaceInfo) -> bool:
    return not (ws.tool == "codex" and is_codex_local_owner_mode(state, ws))


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
    await _send_to_group(
        bot,
        group_chat_id,
        build_thread_control_text(state, ws, thread_info, intro=intro),
        topic_id=topic_id if topic_id is not None else thread_info.topic_id,
        parse_mode="Markdown",
        reply_markup=build_thread_control_keyboard(
            allow_interrupt=thread_interrupt_supported(state, ws),
        ),
    )
