# bot/handlers/common.py
"""
基础命令处理器：/start /ping /echo /status /active /restart /stop
"""
import asyncio
import inspect
import logging
import os
import sys
import time
from datetime import date, timedelta
from typing import Any, Callable, Optional
from telegram import Update
from telegram.ext import ContextTypes
from config import is_provider_exposed
from core.provider_session_bridge import get_provider_usage_summary
from core.providers.facts import list_provider_threads, query_provider_active_thread_ids
from core.providers.registry import get_provider
from core.state import AppState
from core.storage import save_storage
from bot.utils import (
    truncate_text as _truncate_text,
    send_to_group as _send_to_group,
)

logger = logging.getLogger(__name__)

def _load_authoritative_thread_ids(ws_info) -> Optional[set[str]]:
    """对 thread 事实源可完全信任的 provider，返回当前可见 thread 集合。"""
    tool_name = getattr(ws_info, "tool", "")
    provider = get_provider(tool_name)
    facts = provider.facts if provider is not None else None
    if not bool(getattr(facts, "thread_list_is_authoritative", False)):
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


def get_route_aware_thread_topic_id(
    state: AppState,
    ws_info,
    thread_info,
) -> Optional[int]:
    """Return the active Telegram topic through the configured route store."""
    workspace_id = (
        state.get_workspace_storage_key(ws_info)
        or getattr(ws_info, "daemon_workspace_id", None)
        or f"{getattr(ws_info, 'tool', '')}:{getattr(ws_info, 'name', '')}"
    )
    return state.get_thread_topic_id(workspace_id, ws_info, thread_info)


def clear_stale_thread_archive_if_active(state: AppState, ws_info, thread_info, *, active_ids: Optional[set[str]] = None) -> bool:
    """当 source 事实源显示 thread 仍活跃时，清除本地误标 archived。"""
    if not getattr(thread_info, "archived", False):
        return False
    provider = get_provider(getattr(ws_info, "tool", ""))
    facts = provider.facts if provider is not None else None
    if bool(getattr(facts, "preserve_archived_threads", False)):
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
    provider = get_provider(getattr(ws_info, "tool", ""))
    facts = provider.facts if provider is not None else None
    preserve_archived = bool(getattr(facts, "preserve_archived_threads", False))

    for thread_id, thread_info in list(ws_info.threads.items()):
        if (
            preserve_archived
            and authoritative_ids is not None
            and thread_id not in authoritative_ids
            and get_route_aware_thread_topic_id(state, ws_info, thread_info) is None
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
            preserve_archived
            and not next_active
            and not getattr(thread_info, "archived", False)
            and get_route_aware_thread_topic_id(state, ws_info, thread_info) is None
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
        for provider in filter(None, (get_provider(name) for name in state.registered_adapter_names())):
            if provider.name not in names:
                names.append(provider.name)
    for name in state.registered_adapter_names():
        if is_provider_exposed(name) and name not in names:
            names.append(name)
    return names

def tg_send_failed_text(error: object) -> str:
    """TG 发送失败时的统一提示。"""
    return f"❌ 发送失败：{error}"


def tg_empty_turn_completed_text() -> str:
    """当 turn 没有产生正文时，给 TG 的最小完成态提示。"""
    return "✅ 已完成"


async def _call_status_builder(status_builder, state) -> list[str]:
    raw_lines = status_builder(state)
    if inspect.isawaitable(raw_lines):
        raw_lines = await raw_lines
    return [str(line).strip() for line in (raw_lines or []) if str(line).strip()]


def tg_approval_request_text(command: str, reason: str, tool_type: str) -> str:
    """审批请求的最小文案契约。"""
    cmd_raw = (command or "")[:200].replace("`", "\\`")
    cmd_display = f"`{cmd_raw}`" if cmd_raw else "（未知命令）"
    reason_raw = reason[:300] if reason else "（无说明）"
    reason_display = reason_raw.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
    source_display = (tool_type or "provider").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")

    text = (
        f"⚠️ **沙盒权限请求**\n\n"
        f"来源：OnlineWorker 托管的 {source_display} app-server\n\n"
        f"命令：{cmd_display}\n\n"
        f"理由：{reason_display}\n\n"
        f"操作：点击下方按钮审批"
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
                "/token_usage — 查看当前 agent 最近用量\n"
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


def _token_usage_today() -> date:
    return date.today()


def _default_token_usage_range() -> tuple[str, str]:
    end_date = _token_usage_today()
    start_date = end_date - timedelta(days=6)
    return start_date.isoformat(), end_date.isoformat()


def _usage_int(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _usage_cost(summary: dict[str, Any]) -> float | None:
    value = summary.get("totalCostUsd")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aggregate_usage_summary(summary: dict[str, Any]) -> dict[str, Any]:
    days = summary.get("days") if isinstance(summary.get("days"), list) else []
    totals = {
        "totalTokens": _usage_int(summary, "totalTokens"),
        "inputTokens": _usage_int(summary, "inputTokens"),
        "outputTokens": _usage_int(summary, "outputTokens"),
        "cacheCreationTokens": _usage_int(summary, "cacheCreationTokens"),
        "cacheReadTokens": _usage_int(summary, "cacheReadTokens"),
        "totalCostUsd": _usage_cost(summary),
    }

    day_total_tokens = 0
    cost_values: list[float] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        day_total_tokens += _usage_int(day, "totalTokens")
        day_cost = _usage_cost(day)
        if day_cost is not None:
            cost_values.append(day_cost)

    if totals["totalTokens"] <= 0 and day_total_tokens > 0:
        totals["totalTokens"] = day_total_tokens
        totals["inputTokens"] = sum(
            _usage_int(day, "inputTokens") for day in days if isinstance(day, dict)
        )
        totals["outputTokens"] = sum(
            _usage_int(day, "outputTokens") for day in days if isinstance(day, dict)
        )
        totals["cacheCreationTokens"] = sum(
            _usage_int(day, "cacheCreationTokens") for day in days if isinstance(day, dict)
        )
        totals["cacheReadTokens"] = sum(
            _usage_int(day, "cacheReadTokens") for day in days if isinstance(day, dict)
        )
    if totals["totalCostUsd"] is None and cost_values:
        totals["totalCostUsd"] = sum(cost_values)

    return totals


def _format_token_count(value: int) -> str:
    return f"{value:,}"


def _format_usage_cost(value: float | None) -> str:
    return "-" if value is None else f"${value:.6f}"


def _format_token_usage_summary(
    provider_id: str,
    summary: dict[str, Any],
    start_date: str,
    end_date: str,
) -> str:
    unsupported_reason = str(summary.get("unsupportedReason") or "").strip()
    if unsupported_reason:
        return f"{provider_id} 暂不支持用量读取：{unsupported_reason}"

    totals = _aggregate_usage_summary(summary)
    lines = [
        f"{provider_id} 用量",
        f"范围：{start_date} ~ {end_date}",
        f"总 token：{_format_token_count(totals['totalTokens'])}",
        f"输入：{_format_token_count(totals['inputTokens'])}",
        f"输出：{_format_token_count(totals['outputTokens'])}",
        f"Cache 写入：{_format_token_count(totals['cacheCreationTokens'])}",
        f"Cache 读取：{_format_token_count(totals['cacheReadTokens'])}",
        f"成本：{_format_usage_cost(totals['totalCostUsd'])}",
    ]

    days = [
        day for day in (summary.get("days") if isinstance(summary.get("days"), list) else [])
        if isinstance(day, dict) and str(day.get("date") or "").strip()
    ]
    if days:
        lines.append("")
        lines.append("最近记录：")
        for day in days[:7]:
            day_date = str(day.get("date") or "").strip()
            day_tokens = _format_token_count(_usage_int(day, "totalTokens"))
            day_cost = _format_usage_cost(_usage_cost(day))
            lines.append(f"• {day_date}：{day_tokens} token，成本 {day_cost}")
    else:
        lines.append("")
        lines.append("当前范围暂无用量记录。")

    return "\n".join(lines)


def make_token_usage_handler(state: AppState, group_chat_id: int) -> Callable:
    async def token_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None:
            return

        topic_id: Optional[int] = msg.message_thread_id
        provider_id = str(state.get_tool_by_global_topic(topic_id) or "").strip()
        if not provider_id:
            await _send_to_group(
                context.bot,
                group_chat_id,
                "/token_usage 只能在 agent topic 中使用。",
                topic_id=topic_id,
            )
            return

        start_date, end_date = _default_token_usage_range()

        try:
            summary = get_provider_usage_summary(provider_id, start_date, end_date)
        except ValueError as exc:
            await _send_to_group(
                context.bot,
                group_chat_id,
                f"{provider_id} 暂不支持用量读取：{exc}",
                topic_id=topic_id,
            )
            return
        except Exception as exc:
            logger.warning(
                "[token_usage] provider 用量读取失败，provider=%s range=%s..%s err=%s",
                provider_id,
                start_date,
                end_date,
                exc,
            )
            await _send_to_group(
                context.bot,
                group_chat_id,
                f"{provider_id} 用量读取失败：{exc}",
                topic_id=topic_id,
            )
            return

        await _send_to_group(
            context.bot,
            group_chat_id,
            _format_token_usage_summary(provider_id, summary, start_date, end_date),
            topic_id=topic_id,
        )

    return token_usage


def make_status_handler(state: AppState, group_chat_id: int) -> Callable:
    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        lines = ["📊 *onlineWorker 状态*", "• 服务：✅ 已启动"]
        for provider_name in _status_provider_names(state):
            descriptor = get_provider(provider_name)
            if descriptor is not None and descriptor.status_builder is not None:
                lines.extend(await _call_status_builder(descriptor.status_builder, state))
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
