# bot/handlers/common.py
"""
基础命令处理器：/start /ping /echo /status /active /restart /stop
"""
import asyncio
import logging
import os
import sys
import time
from typing import Callable, Optional
from telegram import Bot, Update
from telegram.ext import ContextTypes
from config import is_provider_exposed
from core.providers.facts import list_provider_threads, query_provider_active_thread_ids
from core.providers.registry import get_provider
from core.state import AppState
from core.storage import save_storage
from bot.utils import (
    MAX_TG_LEN,
    utf16_len as _utf16_len,
    truncate_text as _truncate_text,
    send_to_group as _send_to_group,
)

logger = logging.getLogger(__name__)


_AUTHORITATIVE_THREAD_FACT_TOOLS = {"claude"}


def _load_authoritative_thread_ids(ws_info) -> Optional[set[str]]:
    """对 thread 事实源可完全信任的 provider，返回当前可见 thread 集合。"""
    tool_name = getattr(ws_info, "tool", "")
    if tool_name not in _AUTHORITATIVE_THREAD_FACT_TOOLS:
        return None

    try:
        sessions = list_provider_threads(tool_name, getattr(ws_info, "path", ""), limit=200)
    except Exception as e:
        logger.warning(
            "[archive-repair] 查询 provider thread 列表失败，跳过 authoritative 清理，tool=%s ws=%s err=%s",
            tool_name,
            getattr(ws_info, "name", ""),
            e,
        )
        return None

    return {
        str(session.get("id") or "")
        for session in sessions
        if isinstance(session, dict) and session.get("id")
    }


def clear_stale_thread_archive_if_active(state: AppState, ws_info, thread_info, *, active_ids: Optional[set[str]] = None) -> bool:
    """当 source 事实源显示 thread 仍活跃时，清除本地误标 archived。"""
    if not getattr(thread_info, "archived", False):
        return False
    if getattr(ws_info, "tool", "") == "claude":
        return False

    if active_ids is None:
        try:
            active_ids = query_provider_active_thread_ids(ws_info.tool, ws_info.path)
        except Exception as e:
            logger.warning(
                "[archive-repair] 查询活跃 thread 失败，tool=%s ws=%s tid=%s err=%s",
                getattr(ws_info, "tool", ""),
                getattr(ws_info, "name", ""),
                getattr(thread_info, "thread_id", ""),
                e,
            )
            return False

    if getattr(thread_info, "thread_id", "") not in (active_ids or set()):
        return False

    thread_info.archived = False
    thread_info.is_active = True
    logger.warning(
        "[archive-repair] 已清理本地误归档状态，tool=%s ws=%s tid=%s",
        getattr(ws_info, "tool", ""),
        getattr(ws_info, "name", ""),
        getattr(thread_info, "thread_id", ""),
    )
    return True


def reconcile_workspace_threads_with_source(
    state: AppState,
    ws_info,
    *,
    active_ids: Optional[set[str]] = None,
    persist: bool = True,
) -> tuple[Optional[set[str]], bool]:
    """按 source 事实源刷新 workspace 内 thread 的 active/archive 可见状态。"""
    if active_ids is None:
        try:
            active_ids = query_provider_active_thread_ids(ws_info.tool, ws_info.path)
        except Exception as e:
            logger.warning(
                "[archive-repair] 查询 workspace 活跃 thread 失败，tool=%s ws=%s err=%s",
                getattr(ws_info, "tool", ""),
                getattr(ws_info, "name", ""),
                e,
            )
            return None, False

    changed = False
    removable_thread_ids: list[str] = []
    authoritative_ids = _load_authoritative_thread_ids(ws_info)
    if authoritative_ids is not None:
        authoritative_ids |= set(active_ids or set())

    for thread_id, thread_info in list(ws_info.threads.items()):
        if (
            getattr(ws_info, "tool", "") == "claude"
            and authoritative_ids is not None
            and thread_id not in authoritative_ids
            and getattr(thread_info, "topic_id", None) is None
            and str(getattr(thread_info, "source", "") or "unknown").strip().lower() != "app"
        ):
            removable_thread_ids.append(thread_id)
            changed = True
            continue
        if authoritative_ids is not None and thread_id not in authoritative_ids:
            thread_changed = False
            if not getattr(thread_info, "archived", False):
                thread_info.archived = True
                changed = True
                thread_changed = True
            if getattr(thread_info, "is_active", False):
                thread_info.is_active = False
                changed = True
                thread_changed = True
            if thread_changed:
                logger.info(
                    "[archive-repair] 已隐藏不在事实源中的残留 thread，tool=%s ws=%s tid=%s",
                    getattr(ws_info, "tool", ""),
                    getattr(ws_info, "name", ""),
                    thread_id,
                )
            continue
        next_active = thread_id in active_ids
        if (
            getattr(ws_info, "tool", "") == "claude"
            and not next_active
            and not getattr(thread_info, "archived", False)
            and getattr(thread_info, "topic_id", None) is None
            and str(getattr(thread_info, "source", "") or "unknown").strip().lower() != "app"
        ):
            removable_thread_ids.append(thread_id)
            changed = True
            continue
        if getattr(thread_info, "is_active", False) != next_active:
            thread_info.is_active = next_active
            changed = True
        if clear_stale_thread_archive_if_active(
            state,
            ws_info,
            thread_info,
            active_ids=active_ids,
        ):
            changed = True

    for thread_id in removable_thread_ids:
        ws_info.threads.pop(thread_id, None)

    if changed and persist and state.storage is not None:
        save_storage(state.storage)

    return active_ids, changed


def _status_provider_names(state: AppState) -> list[str]:
    names: list[str] = []
    if state.config is not None:
        for tool in state.config.tools:
            if is_provider_exposed(tool.name) and tool.name not in names:
                names.append(tool.name)
    if not names:
        names.append("codex")
    for name in state.registered_adapter_names():
        if is_provider_exposed(name) and name not in names:
            names.append(name)
    return names


def tg_processing_ack_text() -> str:
    """TG 在 TUI 主控模式下的最小处理中文案。"""
    return "✅ 已收到，处理中。完成后会把最终回复同步到这里。"


def tg_send_failed_text(error: object) -> str:
    """TG 发送失败时的统一提示。"""
    return f"❌ 发送失败：{error}"


def is_codex_unmaterialized_error(error: object) -> bool:
    """判断 codex 是否因 thread 尚未 materialize 而拒绝 resume/archive。"""
    text = str(error).lower()
    return (
        "not materialized yet" in text
        or "no rollout found for thread id" in text
    )


def tg_empty_turn_completed_text() -> str:
    """当 turn 没有产生正文时，给 TG 的最小完成态提示。"""
    return "✅ 已完成"


def tg_approval_request_text(command: str, reason: str, tool_type: str) -> str:
    """审批请求的最小文案契约。"""
    cmd_display = f"`{command[:200]}`" if command else "（未知命令）"
    reason_raw = reason[:300] if reason else "（无说明）"
    reason_display = reason_raw.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")

    text = (
        f"⚠️ **沙盒权限请求**\n\n"
        f"命令：{cmd_display}\n\n"
        f"理由：{reason_display}"
    )

    return text


def make_start_handler(group_chat_id: int) -> Callable:
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_to_group(
            context.bot, group_chat_id,
            "👋 onlineWorker 已启动！\n"
            "• /workspace add <名字> <路径> — 添加项目\n"
            "• /workspace switch <名字> — 切换项目\n"
            "• /new — 在当前 workspace 开启新 thread（创建 Topic）\n"
            "• /archive — 归档当前 thread\n"
            "• /history — 查看当前 thread 最近 10 条历史\n"
            "• /active — 预热 adapter 连接，减少首次响应延迟\n"
            "• 在 Thread Topic 里发消息 → 直接传给对应 CLI thread",
        )
    return start


def make_ping_handler(group_chat_id: int) -> Callable:
    async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_to_group(context.bot, group_chat_id, "pong")
    return ping


def make_echo_handler(group_chat_id: int) -> Callable:
    async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        content = " ".join(context.args) if context.args else ""
        if not content:
            await _send_to_group(context.bot, group_chat_id, "用法：/echo <内容>")
            return
        await _send_to_group(context.bot, group_chat_id, f"🔁 {content}")
    return echo


def make_help_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /help 命令：按所在 topic 层级返回对应的命令说明。

    全局 topic   → 顶层命令
    workspace topic → workspace 级命令
    thread topic    → thread 级命令
    """
    async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None:
            return
        src_topic_id: Optional[int] = msg.message_thread_id

        # ── 层级判断 ──────────────────────────────────────────────────────

        # 1. 全局 topic（provider 控制台）
        if state.is_global_topic(src_topic_id):
            text = (
                "*onlineWorker 全局命令*\n\n"
                "/workspace — 查看并打开 workspace\n"
                "/status — 查看 bot 和各 provider 当前状态\n"
                "/help — 显示此帮助\n\n"
                "_在全局 Topic 里打开 workspace 后，会创建对应的 Workspace Topic。_"
            )
            await _send_to_group(
                context.bot, group_chat_id, text,
                topic_id=src_topic_id, parse_mode="Markdown",
            )
            return

        # 2. workspace topic
        ws = state.find_workspace_by_topic_id(src_topic_id) if src_topic_id else None
        if ws is not None:
            text = (
                f"*Workspace `{ws.name}` 命令*\n\n"
                "/new — 在此 workspace 开启新 thread（会创建对应 Thread Topic）\n"
                "/list — 列出此 workspace 下所有活跃 thread\n"
                "/help — 显示此帮助\n\n"
                f"_当前 provider：`{ws.tool}`。在 Thread Topic 里直接发消息即可继续对话。_"
            )
            await _send_to_group(
                context.bot, group_chat_id, text,
                topic_id=src_topic_id, parse_mode="Markdown",
            )
            return

        # 3. thread topic
        found = state.find_thread_by_topic_id(src_topic_id) if src_topic_id else None
        if found is not None:
            ws_info, thread_info = found
            text = (
                f"*Thread Topic 命令*\n\n"
                "直接发文本 — 发送给当前工具，继续当前对话\n"
                "`/archive` `/history` `/skills` — 由 onlineWorker 本地处理\n"
                "其他 `/xxx` — 默认发给当前工具\n"
                "线程控制按钮 — 查看帮助 / 历史 / 中断 / 归档\n\n"
                f"_当前 workspace：`{ws_info.name}`_\n"
                f"_当前 provider：`{ws_info.tool}`_"
            )
            await _send_to_group(
                context.bot, group_chat_id, text,
                topic_id=src_topic_id, parse_mode="Markdown",
            )
            return

        # 4. 未知 topic（兜底）
        text = (
            "*onlineWorker 命令速查*\n\n"
            "*全局 Topic*\n"
            "/workspace — 查看并打开 workspace\n"
            "/status — 查看当前状态\n\n"
            "*Workspace Topic*\n"
            "/new — 开启新 thread\n"
            "/list — 列出所有 thread\n\n"
            "*Thread Topic*\n"
            "直接发消息（包括 `/xxx`）— 与当前工具对话\n"
            "线程控制按钮 — 查看帮助 / 历史 / 中断 / 归档\n\n"
            "/help — 显示此帮助"
        )
        await _send_to_group(
            context.bot, group_chat_id, text,
            topic_id=src_topic_id, parse_mode="Markdown",
        )

    return help_handler


def make_status_handler(state: AppState, group_chat_id: int) -> Callable:
    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lines = ["📊 *onlineWorker 状态*", "• 服务：✅ 已启动"]
        for provider_name in _status_provider_names(state):
            descriptor = get_provider(provider_name)
            if descriptor is not None and descriptor.status_builder is not None:
                lines.extend(descriptor.status_builder(state))
                continue

            adapter = state.get_adapter(provider_name)
            if adapter is not None and getattr(adapter, "connected", False):
                lines.append(f"• {provider_name}：✅ 已连接")
            elif adapter is not None:
                lines.append(f"• {provider_name}：❌ 已断开")

        # 活跃 workspace
        ws = state.get_active_workspace()
        if ws:
            reconcile_workspace_threads_with_source(state, ws)
            lines.append(f"• 活跃 workspace：`{ws.name}` ({ws.path})")
            active_threads = [
                t for t in ws.threads.values()
                if t.is_active and not t.archived
            ]
            lines.append(f"• 活跃 thread 数：{len(active_threads)}")
        else:
            lines.append("• 活跃 workspace：无")

        if state.is_waiting_confirmation():
            lines.append("• 等待确认：⏳ 是")

        topic_id = state.get_active_workspace_topic_id()
        await _send_to_group(
            context.bot, group_chat_id, "\n".join(lines),
            topic_id=topic_id, parse_mode="Markdown",
        )
    return status


def make_restart_handler(group_chat_id: int) -> Callable:
    """/restart — 热重启 bot（os.execv 原地替换进程）。"""
    async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_to_group(
            context.bot, group_chat_id,
            "🔄 正在重启...",
            topic_id=update.effective_message.message_thread_id if update.effective_message else None,
        )

        async def _do_restart():
            await asyncio.sleep(1)  # 等消息发出去
            python = sys.executable
            os.execv(python, [python] + sys.argv)

        asyncio.create_task(_do_restart())

    return restart


def make_active_handler(state: AppState, group_chat_id: int) -> Callable:
    """/active — 预热所有 adapter 连接，减少首次消息延迟。"""
    async def active(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        topic_id = (
            update.effective_message.message_thread_id
            if update.effective_message else None
        )
        results = []
        t_start = time.monotonic()

        for tool_name, adapter in state.iter_adapters():
            if adapter is None or not adapter.connected:
                results.append(f"• {tool_name}：❌ 未连接")
                continue
            try:
                t0 = time.monotonic()
                await adapter.list_workspaces()
                elapsed = time.monotonic() - t0
                results.append(f"• {tool_name}：✅ {elapsed*1000:.0f}ms")
            except Exception as e:
                results.append(f"• {tool_name}：⚠️ {e}")

        total = time.monotonic() - t_start
        text = f"🔥 预热完成（{total*1000:.0f}ms）\n" + "\n".join(results)
        await _send_to_group(
            context.bot, group_chat_id, text, topic_id=topic_id,
        )

    return active


def make_stop_handler(group_chat_id: int) -> Callable:
    """/stop — 优雅停止 bot，让 run_polling 正常退出并触发 post_shutdown。"""
    async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await _send_to_group(
            context.bot, group_chat_id,
            "⏹️ 正在停止...",
            topic_id=update.effective_message.message_thread_id if update.effective_message else None,
        )
        # 通过 PTB 的 stop_running 结束 run_polling，让 post_shutdown() 有机会执行。
        # /restart 仍保留为 os.execv 的热重启路径。
        context.application.stop_running()

    return stop
