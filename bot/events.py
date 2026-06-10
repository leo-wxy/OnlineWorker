# bot/events.py
"""
daemon 事件 → Telegram 推送

事件结构：
    method = "app-server-event"
    params = {
        "message": {"method": "<event_method>", "params": {...}},
        "workspace_id": "<daemon workspace UUID>"
    }

OUT-01 流式输出架构：
    turn/started             → 发占位消息 "⏳ 思考中..."，记入 streaming_turns[thread_id]
    item/agentMessage/delta  → 累积 delta 到 buffer，600ms 节流 edit 占位消息
    item/completed           → agentMessage: 用完整 text 做最终 edit
                             → shellCommand: 追加到 shell_summaries
    turn/completed           → 收口当前流式消息并清理 streaming 状态

其他事件：
    item/commandExecution/requestApproval → 推送沙盒权限授权请求，附带 Allow/Deny 按钮
"""
import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Optional
from telegram import Bot
from core.messages.events import create_message_event
from core.state import AppState, PendingApproval, PendingQuestion, PendingQuestionGroup, StreamingTurn
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from plugins.providers.builtin.codex.python.tui_bridge import (
    remember_codex_tg_synced_final_reply,
)
from core.messages.session_bridge import message_event_from_session_event
from core.providers.session_events import SessionEvent, normalize_session_event
from core.providers.topic_policy import provider_allows_unbound_thread_topic_materialization
from core.providers.registry import get_provider, list_providers
from core.providers.interactions import (
    ProviderApprovalRequest as ApprovalInfo,
    ProviderQuestionRequest,
    parse_standard_question_request,
)
from core.telegram_formatting import format_telegram_assistant_final_text
from core.notifications import NotificationEvent, build_notification_router
from core.notifications.result_summary import (
    notification_safe_preview_title as _notification_safe_preview_title,
    notification_summary_text as _notification_summary_text,
    notification_text_is_url_only as _notification_text_is_url_only,
    notification_title_from_summary as _notification_title_from_summary,
    short_notification_title as _short_notification_title,
)
from core.messages.publishing import (
    publish_approval_requested,
    publish_notification_activity,
    publish_session_message_event,
)
from core.ai.scenarios import run_ai_scenario
from core.storage import save_storage, ThreadInfo
from bot.handlers.common import (
    _send_to_group,
    _truncate_text,
    clear_stale_thread_archive_if_active,
    tg_approval_request_text,
    tg_empty_turn_completed_text,
)
from bot.handlers.workspace import (
    _make_thread_topic_name,
    _replay_thread_history,
)
from bot.event_helpers import (
    build_incomplete_turn_text as _build_incomplete_turn_text,
    codex_semantic_kind as _codex_semantic_kind,
    codex_semantic_payload as _codex_semantic_payload,
    extract_thread_id as _extract_thread_id,
    extract_turn_id as _extract_turn_id,
    is_network_error as _is_network_error,
    looks_like_markdown_final_text as _looks_like_markdown_final_text,
    normalize_streamed_reply_for_sync as _normalize_streamed_reply_for_sync,
)
from bot.keyboards import build_approval_keyboard, build_question_keyboard

logger = logging.getLogger(__name__)

# 流式输出节流间隔（秒）
THROTTLE_INTERVAL = 0.6


# 防止 turn/started 并发重复建同一个 thread topic
_MATERIALIZING_THREAD_TOPICS: set[str] = set()


def _workspace_key(state: AppState, ws_info) -> str:
    return state.get_workspace_storage_key(ws_info) or ws_info.daemon_workspace_id or f"{ws_info.tool}:{ws_info.name}"


def _workspace_topic_id(state: AppState, ws_info) -> Optional[int]:
    return state.get_workspace_topic_id(_workspace_key(state, ws_info), ws_info)


def _thread_topic_id(state: AppState, ws_info, thread_info: ThreadInfo) -> Optional[int]:
    return state.get_thread_topic_id(_workspace_key(state, ws_info), ws_info, thread_info)


def _workspace_path_from_id(workspace_id: str) -> str:
    if ":" not in workspace_id:
        return ""
    return workspace_id.split(":", 1)[1]


def _provider_should_materialize_unbound_thread_topic(
    state: AppState,
    thread_id: str,
) -> bool:
    found = state.find_thread_by_id_global(thread_id)
    if not found:
        return True

    ws_info, thread_info = found
    return provider_allows_unbound_thread_topic_materialization(state, ws_info, thread_info)


async def _materialize_thread_topic_if_needed(
    state: AppState,
    bot: Bot,
    group_chat_id: int,
    thread_id: str,
) -> Optional[int]:
    """为正在真实流式中的 thread 懒创建 TG topic。

    只在 thread 已注册但 topic_id 仍为空时触发，避免启动时为所有历史 thread
    批量铺开 topic。创建成功后顺带回放最近历史，保证新 topic 具备基本上下文。
    """
    found = state.find_thread_by_id_global(thread_id)
    if not found:
        return None

    ws_info, thread_info = found
    existing_topic_id = _thread_topic_id(state, ws_info, thread_info)
    if existing_topic_id is not None:
        return existing_topic_id

    if thread_id in _MATERIALIZING_THREAD_TOPICS:
        return None

    _MATERIALIZING_THREAD_TOPICS.add(thread_id)
    try:
        thread_info.archived = False
        thread_info.is_active = True

        topic_name = _make_thread_topic_name(
            ws_info.tool or "unknown",
            ws_info.name,
            thread_info.preview,
            thread_id,
        )
        topic = await bot.create_forum_topic(chat_id=group_chat_id, name=topic_name)
        topic_id = topic.message_thread_id
        workspace_key = state.get_workspace_storage_key(ws_info)
        if workspace_key is not None:
            state.bind_telegram_session_topic(
                workspace_key,
                ws_info,
                thread_info,
                topic_id,
                display_name=thread_info.preview,
            )
        else:
            thread_info.topic_id = topic_id
        if state.storage is not None:
            save_storage(state.storage)

        logger.info(
            "[streaming] 已按需 materialize thread topic: tool=%s ws=%s thread=%s topic=%s",
            ws_info.tool,
            ws_info.name,
            thread_id[:12],
            topic_id,
        )

        replay_cursor = thread_info.history_sync_cursor or None
        if not replay_cursor:
            replay_cursor = await _replay_thread_history(
                bot=bot,
                group_chat_id=group_chat_id,
                topic_id=topic_id,
                thread_id=thread_id,
                sessions_dir=None,
                tool_name=ws_info.tool,
            )
        if replay_cursor and thread_info.history_sync_cursor != replay_cursor and state.storage is not None:
            thread_info.history_sync_cursor = replay_cursor
            save_storage(state.storage)
        return topic_id
    except Exception as e:
        logger.warning(
            "[streaming] 按需 materialize thread topic 失败: tool=%s ws=%s thread=%s err=%s",
            ws_info.tool,
            ws_info.name,
            thread_id[:12],
            e,
        )
        return None
    finally:
        _MATERIALIZING_THREAD_TOPICS.discard(thread_id)


def _repair_local_archived_thread_if_active(
    state: AppState,
    ws_info,
    thread_info,
) -> bool:
    repaired = clear_stale_thread_archive_if_active(state, ws_info, thread_info)
    if repaired and state.storage is not None:
        save_storage(state.storage)
    return repaired


async def send_approval_to_telegram(
    state: AppState,
    bot: Bot,
    group_chat_id: int,
    topic_id: Optional[int],
    workspace_id: str,
    info: ApprovalInfo,
    *,
    interactive: bool = True,
    notice_suffix: str = "",
) -> None:
    """Send app-server approval UI, record PendingApproval, and attach buttons."""
    text = tg_approval_request_text(
        command=info.command,
        reason=info.reason,
        tool_type=info.tool_type,
    )
    if notice_suffix:
        text = f"{text}\n\n{notice_suffix}"

    try:
        sent = await _send_to_group(
            bot, group_chat_id, text,
            topic_id=topic_id,
            parse_mode="Markdown",
        )
        if sent is None:
            logger.error("推送授权请求失败：sent=None")
            return

        msg_id = sent.message_id
        state.pending_approvals[msg_id] = PendingApproval(
            request_id=info.request_id,
            workspace_id=workspace_id,
            thread_id=info.thread_id or "",
            cmd=info.command,
            justification=info.reason,
            tool_name=info.tool_name,
            proposed_amendment=info.proposed_amendment,
            amendment_decision=info.amendment_decision,
            tool_type=info.tool_type,
            approval_source=info.approval_source,
        )
        publish_approval_requested(
            state,
            state.pending_approvals[msg_id],
            workspace_id=workspace_id,
            source="telegram",
        )
        if interactive:
            keyboard = build_approval_keyboard(msg_id)
            await bot.edit_message_reply_markup(
                chat_id=group_chat_id,
                message_id=msg_id,
                reply_markup=keyboard,
            )
        logger.info(
            "[approval_request] 已推送 tool=%s topic=%s msg_id=%s thread=%s request_id=%s interactive=%s",
            info.tool_type,
            topic_id,
            msg_id,
            info.thread_id,
            info.request_id,
            interactive,
        )
    except Exception as e:
        logger.error(f"推送授权请求到 Telegram 失败：{e}")


def _question_text(info: ProviderQuestionRequest) -> str:
    lines = []
    if info.sub_total > 1:
        lines.append(
            f"❓ {info.header} ({info.sub_index + 1}/{info.sub_total})"
            if info.header
            else f"❓ Question ({info.sub_index + 1}/{info.sub_total})"
        )
    else:
        lines.append(f"❓ {info.header}" if info.header else "❓ Question")
    if info.question:
        lines.append(f"\n{info.question}")
    if info.options:
        lines.append("")
        for i, opt in enumerate(info.options):
            label = opt.get("label", f"选项 {i + 1}")
            desc = opt.get("description", "")
            if desc:
                lines.append(f"  {i + 1}. {label} — {desc}")
            else:
                lines.append(f"  {i + 1}. {label}")
    if info.multiple:
        lines.append("\n（多选模式，点选后点确认提交）")
    return "\n".join(lines)


async def send_question_to_telegram(
    state: AppState,
    bot: Bot,
    group_chat_id: int,
    topic_id: Optional[int],
    workspace_id: str,
    info: ProviderQuestionRequest,
) -> None:
    """Shared question UI: send prompt, record PendingQuestion, attach keyboard."""
    try:
        sent = await _send_to_group(bot, group_chat_id, _question_text(info), topic_id=topic_id)
        if sent is None:
            logger.error("推送 question 失败：sent=None")
            return

        msg_id = sent.message_id
        group: PendingQuestionGroup | None = None
        if info.sub_total > 1:
            if info.question_id not in state.pending_question_groups:
                group = PendingQuestionGroup(
                    question_id=info.question_id,
                    session_id=info.thread_id or "",
                    workspace_id=workspace_id,
                    total=info.sub_total,
                )
                state.pending_question_groups[info.question_id] = group
            else:
                group = state.pending_question_groups[info.question_id]
            group.msg_ids[info.sub_index] = msg_id

        cb_ts = int(time.time())
        pq = PendingQuestion(
            question_id=info.question_id,
            session_id=info.thread_id or "",
            workspace_id=workspace_id,
            tool_name=info.tool_type,
            header=info.header,
            question_text=info.question,
            options=info.options,
            multiple=info.multiple,
            custom=info.custom,
            group=group,
            sub_index=info.sub_index,
            topic_id=topic_id,
            cb_ts=cb_ts,
        )
        state.pending_questions[msg_id] = pq

        keyboard = build_question_keyboard(msg_id, info.options, multiple=info.multiple, custom=info.custom)
        await bot.edit_message_reply_markup(
            chat_id=group_chat_id,
            message_id=msg_id,
            reply_markup=keyboard,
        )
        logger.info(
            "[question] 已推送 tool=%s question=%s request=%s sub=%s/%s msg_id=%s "
            "options=%s multiple=%s custom=%s",
            info.tool_type,
            info.question_id,
            "-",
            info.sub_index + 1,
            info.sub_total,
            msg_id,
            len(info.options),
            info.multiple,
            info.custom,
        )
    except Exception as e:
        logger.error(f"推送 question 到 Telegram 失败：{e}")


def _resolve_approval_target(
    state: AppState,
    ws_daemon_id: str,
    thread_id: Optional[str],
) -> tuple[str, Optional[int], Optional[str]]:
    """审批消息必须命中明确 thread topic，否则返回错误原因并交给 owner DM 兜底。"""
    if not thread_id:
        return "", None, "approval missing thread_id"

    found = state.find_thread_by_id_global(thread_id)
    if not found and ws_daemon_id:
        ws_info = state.find_workspace_by_daemon_id(ws_daemon_id)
        tool_name = state.get_tool_for_workspace(ws_daemon_id)
        runtime = state.get_provider_runtime(tool_name) if tool_name else None
        watched_threads = getattr(runtime, "watched_threads", {}) if runtime is not None else {}
        watch_state = watched_threads.get(thread_id) if isinstance(watched_threads, dict) else None
        if watch_state is not None:
            workspace_id = str(getattr(watch_state, "workspace_id", "") or "")
            topic_id = getattr(watch_state, "topic_id", None)
            if topic_id is not None:
                return workspace_id or getattr(ws_info, "daemon_workspace_id", "") or ws_daemon_id, topic_id, None
    if not found and not ws_daemon_id:
        for tool_name, runtime in state.provider_runtime_state.items():
            watched_threads = getattr(runtime, "watched_threads", {})
            if not isinstance(watched_threads, dict):
                continue
            watch_state = watched_threads.get(thread_id)
            if watch_state is None:
                continue
            workspace_id = str(getattr(watch_state, "workspace_id", "") or "")
            topic_id = getattr(watch_state, "topic_id", None)
            if topic_id is not None:
                return workspace_id, topic_id, None

    if not found and ws_daemon_id:
        ws_info = state.find_workspace_by_daemon_id(ws_daemon_id)
        if ws_info is not None:
            workspace_id = ws_info.daemon_workspace_id or ws_daemon_id
            thread_map = getattr(ws_info, "threads", {}) or {}
            if thread_id in thread_map:
                found = (ws_info, thread_map[thread_id])

    if not found:
        return "", None, f"thread not found: {thread_id}"

    ws_info, thread_info = found
    workspace_id = ws_info.daemon_workspace_id or ws_daemon_id or ""

    if thread_info.archived:
        _repair_local_archived_thread_if_active(state, ws_info, thread_info)
    if thread_info.archived:
        return workspace_id, None, f"thread archived: {thread_id}"

    topic_id = _thread_topic_id(state, ws_info, thread_info)
    if topic_id is None:
        return workspace_id, None, f"thread topic missing: {thread_id}"

    return workspace_id, topic_id, None


def _parse_provider_approval_request(
    provider_id: str,
    params: dict,
    *,
    request_id: Any = None,
    default_thread_id: Optional[str] = None,
    approval_source: str = "app_server",
) -> ApprovalInfo:
    descriptor = get_provider(provider_id)
    interactions = descriptor.interactions if descriptor is not None else None
    parser = getattr(interactions, "parse_approval_request", None) if interactions is not None else None
    if not callable(parser):
        raise RuntimeError(f"provider does not support approval requests: {provider_id}")
    return parser(
        params,
        request_id=request_id,
        provider_id=provider_id,
        default_thread_id=default_thread_id,
        approval_source=approval_source,
    )


def _parse_provider_question_request(
    provider_id: str,
    params: dict,
    *,
    default_thread_id: Optional[str] = None,
    question_source: str = "app_server",
) -> ProviderQuestionRequest:
    descriptor = get_provider(provider_id)
    interactions = descriptor.interactions if descriptor is not None else None
    parser = getattr(interactions, "parse_question_request", None) if interactions is not None else None
    if callable(parser):
        return parser(
            params,
            provider_id=provider_id,
            default_thread_id=default_thread_id,
            question_source=question_source,
        )
    return parse_standard_question_request(
        params,
        provider_id=provider_id,
        default_thread_id=default_thread_id,
        question_source=question_source,
    )


def _provider_supports_server_request_method(provider_id: str, method: str) -> bool:
    descriptor = get_provider(provider_id)
    interactions = descriptor.interactions if descriptor is not None else None
    methods = getattr(interactions, "server_request_methods", ()) if interactions is not None else ()
    return method in methods


def _provider_for_server_request_method(
    state: AppState,
    method: str,
    params: dict,
) -> str:
    ws_daemon_id = str(
        params.get("_workspaceId")
        or params.get("workspaceId")
        or params.get("workspace_id")
        or ""
    )
    if ws_daemon_id:
        provider_id = str(state.get_tool_for_workspace(ws_daemon_id) or "").strip()
        if provider_id and _provider_supports_server_request_method(provider_id, method):
            return provider_id

    for descriptor in list_providers():
        interactions = descriptor.interactions
        methods = getattr(interactions, "server_request_methods", ()) if interactions is not None else ()
        parser = getattr(interactions, "parse_approval_request", None) if interactions is not None else None
        if method not in methods or not callable(parser):
            continue
        try:
            parsed = parser(params, provider_id=descriptor.name, approval_source=method)
        except Exception as exc:
            logger.debug(
                "[server_request] provider parser failed provider=%s method=%s err=%s",
                descriptor.name,
                method,
                exc,
            )
            continue
        thread_id = parsed.thread_id
        if not thread_id:
            continue
        found = state.find_thread_by_id_global(thread_id)
        if found:
            provider_id = str(found[0].tool or "").strip()
            if provider_id == descriptor.name:
                return descriptor.name
        runtime = state.get_provider_runtime(descriptor.name)
        watched_threads = getattr(runtime, "watched_threads", {}) if runtime is not None else {}
        if isinstance(watched_threads, dict) and thread_id in watched_threads:
            return descriptor.name

    for descriptor in list_providers():
        interactions = descriptor.interactions
        methods = getattr(interactions, "server_request_methods", ()) if interactions is not None else ()
        if method in methods:
            return descriptor.name
    return ""


def _log_discarded_unroutable_approval(
    info: ApprovalInfo,
    *,
    route_error: str,
    ws_daemon_id: str,
) -> None:
    logger.warning(
        "[approval_target] 丢弃未绑定 topic 的审批请求 error=%s tool=%s thread=%s ws=%s cmd=%s",
        route_error,
        info.tool_type or "unknown",
        info.thread_id or "N/A",
        ws_daemon_id or "N/A",
        (info.command or "")[:200],
    )


def _resolve_topic_id(
    state: AppState,
    ws_daemon_id: str,
    thread_id: Optional[str],
    event_params: dict,
) -> Optional[int]:
    """根据 thread_id 解析目标 topic_id。

    策略：
    1. 如果有 thread_id，全局查找（跨所有 workspace）
    2. 如果找不到 thread 且有 ws_daemon_id，查找该 workspace 的 topic
    3. 如果仍然找不到，记录错误但不再 fallback 到 active_workspace

    注意：当 thread 已注册但 topic_id 尚为 None（/new 占位阶段，create_forum_topic
    还未返回），返回 None 而不是 fallback，让调用方跳过该事件。
    这样可避免 SSE 事件（turn/started 等）在 topic 创建完成前被错误路由到 workspace topic。
    """
    topic_id: Optional[int] = None
    thread_found = False
    thread_waiting_for_topic = False

    # 策略 1：通过 thread_id 全局查找（跨所有 workspace）
    if thread_id:
        found = state.find_thread_by_id_global(thread_id)
        if found:
            ws, t = found
            if t.archived:
                _repair_local_archived_thread_if_active(state, ws, t)
            if not t.archived:
                thread_found = True
                topic_id = _thread_topic_id(state, ws, t)  # 可能为 None（按需创建模式）
                thread_waiting_for_topic = topic_id is None
                if topic_id is not None:
                    logger.debug(
                        f"[resolve_topic] 全局找到 thread：ws={ws.name} tool={ws.tool} "
                        f"thread={thread_id[:12]}… topic={topic_id}"
                    )
                else:
                    logger.debug(
                        f"[resolve_topic] 全局找到 thread 但 topic_id 为空：ws={ws.name} tool={ws.tool} "
                        f"thread={thread_id[:12]}…，等待按需创建"
                    )

    # 策略 2：thread 未知但有 ws_daemon_id，尝试查找 workspace topic
    if not thread_found and ws_daemon_id:
        ws = state.find_workspace_by_daemon_id(ws_daemon_id)
        if ws:
            topic_id = _workspace_topic_id(state, ws)
            if topic_id:
                logger.debug(
                    f"[resolve_topic] thread 未知，使用 workspace topic: "
                    f"ws={ws.name} tool={ws.tool} topic={topic_id}"
                )
            else:
                logger.error(
                    f"[resolve_topic] workspace 找到但无 topic_id：ws={ws.name} thread={thread_id or 'N/A'}"
                )
        else:
            logger.error(
                f"[resolve_topic] 无法找到 workspace：ws_daemon_id={ws_daemon_id} thread={thread_id or 'N/A'}"
            )

    # 策略 3：如果仍然没有 topic_id，记录错误但不再 fallback
    if topic_id is None and thread_waiting_for_topic:
        logger.debug(
            f"[resolve_topic] thread 已注册但 topic_id 为空，等待按需 materialize："
            f"thread={thread_id or 'N/A'} ws_daemon_id={ws_daemon_id or 'N/A'}"
        )
    if topic_id is None and (thread_id or ws_daemon_id) and not thread_found:
        logger.error(
            f"[resolve_topic] 无法解析 topic_id：thread={thread_id or 'N/A'} "
            f"ws_daemon_id={ws_daemon_id or 'N/A'} - 事件可能被丢弃"
        )

    return topic_id


def _resolve_workspace_info(
    state: AppState,
    ws_daemon_id: str,
    thread_id: Optional[str],
):
    if ws_daemon_id:
        ws = state.find_workspace_by_daemon_id(ws_daemon_id)
        if ws is not None:
            return ws
    if thread_id:
        found = state.find_thread_by_id_global(thread_id)
        if found:
            ws, _thread = found
            return ws
    return None


def make_event_handler(state: AppState, bot: Bot, group_chat_id: int, notification_router=None):
    """
    返回 daemon 事件回调。

    路由逻辑：
    1. 从 params 拿 workspace_id
    2. 找对应 workspace（按 daemon_workspace_id）
    3. 从 event_params 拿 threadId
    4. 找对应 thread → 拿 topic_id
    5. 推送到对应 Telegram Topic
    """

    if notification_router is None and state.config is not None:
        try:
            notification_router = build_notification_router(state.config)
        except Exception as e:
            logger.warning("[notification] 初始化通知路由失败：%s", e)
            notification_router = None

    def _display_agent_name(agent_id: str) -> str:
        name = str(agent_id or "").strip()
        if not name:
            return "Agent"
        known = {
            "codex": "Codex",
            "claude": "Claude",
        }
        return known.get(name.lower(), name[:1].upper() + name[1:])

    def _notification_explicit_task_summary(agent_id: str, thread_id: Optional[str]) -> str:
        if not agent_id or not thread_id:
            return ""
        run = state.get_provider_current_run(agent_id, thread_id)
        if run is not None and getattr(run, "task_summary", ""):
            return str(run.task_summary)
        summary = state.get_provider_task_summary(agent_id, thread_id)
        if summary:
            return str(summary)
        return ""

    def _notification_raw_task_summary(agent_id: str, thread_id: Optional[str]) -> str:
        summary = _notification_explicit_task_summary(agent_id, thread_id)
        if summary:
            return summary
        found = state.find_thread_by_id_global(thread_id)
        if found:
            _ws_info, thread_info = found
            if not _notification_text_is_url_only(thread_info.preview):
                return str(thread_info.preview or "")
        return ""

    def _notification_context(ctx: "EventContext", thread_id: Optional[str]):
        ws_info = _resolve_workspace_info(state, ctx.ws_daemon_id, thread_id)
        thread_info = None
        if thread_id:
            found = state.find_thread_by_id_global(thread_id)
            if found:
                ws_info, thread_info = found

        agent_id = str(
            (ws_info.tool if ws_info is not None else "")
            or ctx.event.provider
            or state.get_tool_for_workspace(ctx.ws_daemon_id)
            or "agent"
        ).strip()
        explicit_summary = _notification_explicit_task_summary(agent_id, thread_id)
        preview_title = (
            _notification_safe_preview_title(thread_info.preview)
            if thread_info is not None
            else ""
        )
        task_name = (
            _notification_title_from_summary(explicit_summary)
            or preview_title
            or _short_notification_title(ws_info.name if ws_info is not None else "")
            or (thread_id[:8] if thread_id else "")
            or "Task"
        )
        return agent_id, _display_agent_name(agent_id), task_name

    def _notification_task_id(ctx: "EventContext", thread_id: Optional[str], fallback_id: str = "") -> str:
        agent_id, _agent_name, _task_name = _notification_context(ctx, thread_id)
        run = None
        if thread_id and agent_id:
            run = state.get_provider_current_run(agent_id, thread_id)
        if run is not None and run.run_id:
            return str(run.run_id)
        turn_id = _extract_turn_id(ctx.event_params)
        return str(turn_id or fallback_id or thread_id or ctx.ws_daemon_id or "task")

    def _notification_task_summary(agent_id: str, thread_id: Optional[str]) -> str:
        summary = _notification_raw_task_summary(agent_id, thread_id)
        if _notification_text_is_url_only(summary):
            return ""
        return _notification_summary_text(summary)

    def _publish_buffered_final_message(
        ctx: "EventContext",
        *,
        thread_id: str,
        text: str,
        turn_id: str = "",
    ) -> None:
        normalized_text = str(text or "").strip()
        if not normalized_text or not thread_id:
            return

        bus = getattr(state, "message_bus", None)
        publish = getattr(bus, "publish", None)
        if not callable(publish):
            return

        dedupe_key = ""
        if turn_id:
            dedupe_key = ":".join(
                part
                for part in (
                    ctx.event.provider,
                    ctx.ws_daemon_id,
                    thread_id,
                    turn_id,
                    "message.assistant.final",
                    "tui-mirror-buffered",
                )
                if part
            )

        try:
            publish(
                create_message_event(
                    "message.assistant.final",
                    provider_id=ctx.event.provider,
                    workspace_id=ctx.ws_daemon_id,
                    workspace_path=_workspace_path_from_id(ctx.ws_daemon_id),
                    session_id=thread_id,
                    turn_id=turn_id,
                    source="provider_event",
                    payload={
                        "text": normalized_text,
                        "status": "completed",
                        "rawMethod": ctx.event.raw_method or "turn/completed",
                        "semanticKind": "turn_completed",
                    },
                    dedupe_key=dedupe_key,
                )
            )
        except Exception:
            logger.warning(
                "[message-bus] 发布 tui-mirror buffered final 失败 thread=%s turn=%s",
                thread_id[:8],
                (turn_id or "")[:12] or "?",
                exc_info=True,
            )

    async def _emit_notification(
        ctx: "EventContext",
        *,
        thread_id: Optional[str],
        status: str,
        message: str,
        task_id: str = "",
        task_name_override: str = "",
        task_summary_override: str | None = None,
    ) -> None:
        if notification_router is None:
            return

        agent_id, agent_name, task_name = _notification_context(ctx, thread_id)
        task_name = task_name_override or task_name
        task_summary = (
            task_summary_override
            if task_summary_override is not None
            else _notification_task_summary(agent_id, thread_id)
        )
        try:
            event = NotificationEvent(
                status=status,
                agent_name=agent_name,
                task_name=task_name,
                message=message,
                task_id=task_id or _notification_task_id(ctx, thread_id),
                agent_id=agent_id,
                task_summary=task_summary,
            )
            publish_notification_activity(state, event, "notification.requested")
            result = await notification_router.notify(event)
        except Exception as e:
            if "event" in locals():
                publish_notification_activity(
                    state,
                    event,
                    "notification.failed",
                    reason="exception",
                    errors=(str(e),),
                )
            logger.warning(
                "[notification] 发送任务通知异常 thread=%s status=%s error=%s",
                thread_id or "N/A",
                status,
                e,
            )
            return

        if result.sent:
            publish_notification_activity(
                state,
                event,
                "notification.emitted",
                channels=tuple(result.channels),
            )
            logger.info(
                "[notification] 已发送任务通知 channels=%s thread=%s status=%s",
                ",".join(result.channels),
                thread_id or "N/A",
                status,
            )
        else:
            skipped_kind = (
                "notification.skipped"
                if result.reason in {"deduped", "no_channels"}
                else "notification.failed"
            )
            publish_notification_activity(
                state,
                event,
                skipped_kind,
                reason=result.reason,
                errors=tuple(result.errors),
            )
        if not result.sent and result.reason not in {"deduped", "no_channels"}:
            detail = f" errors={'; '.join(result.errors)}" if result.errors else ""
            logger.warning(
                "[notification] 任务通知未发送 reason=%s thread=%s status=%s%s",
                result.reason,
                thread_id or "N/A",
                status,
                detail,
            )

    def _notification_for_turn_status(run_status: str, turn: Any, ctx: "EventContext") -> tuple[str, str]:
        normalized = str(run_status or "completed").strip().lower()
        if normalized in {"error", "failed", "cancelled", "canceled", "aborted"}:
            if normalized == "aborted":
                return "failed", "任务已中断"
            if normalized in {"cancelled", "canceled"}:
                return "failed", "任务已取消"
            error_text = ""
            if isinstance(turn, dict):
                error_text = str(turn.get("error") or "").strip()
            if not error_text:
                error_text = str(ctx.event_params.get("error") or "").strip()
            return "failed", f"任务失败：{error_text}" if error_text else "任务失败"
        return "completed", "任务已完成"

    def _is_codex_tui_mirror_completion(ctx: "EventContext", run_status: str, turn: Any) -> bool:
        if ctx.event.provider != "codex":
            return False
        if str(run_status or "completed").strip().lower() != "completed":
            return False
        if isinstance(turn, dict) and str(turn.get("source") or "").strip() == "tui-mirror":
            return True
        return str(ctx.event_params.get("source") or "").strip() == "tui-mirror"

    def _codex_final_reply_already_synced(
        thread_id: Optional[str],
        event_turn_id: Optional[str] = None,
    ) -> bool:
        if not thread_id:
            return False
        run = codex_state.get_current_run(state, thread_id)
        if run is None or not run.final_reply_synced_to_tg:
            return False
        if event_turn_id and run.turn_id and str(run.turn_id) != str(event_turn_id):
            return False
        return True

    def _claim_streaming_notification(
        st: StreamingTurn | None,
        thread_id: str,
        *,
        source: str,
    ) -> bool:
        if st is None:
            return True
        if st.notification_emitted:
            logger.info(
                "[notification] 跳过已占用的 streaming 通知 thread=%s source=%s",
                thread_id[:8],
                source,
            )
            return False
        st.notification_emitted = True
        return True

    def _completed_reply_text_from_stream(st: StreamingTurn | None) -> str:
        if st is None:
            return ""
        raw_text = (st.buffer or "").strip()
        if raw_text.startswith("💭 "):
            return ""
        text = _normalize_streamed_reply_for_sync(st.buffer)
        processing_placeholders = {
            "⏳ 思考中...",
            tg_empty_turn_completed_text(),
            "已收到",
            "已收到，处理中。",
            "分析中",
            "处理中",
            "还在整理中",
        }
        if not text or text in processing_placeholders:
            return ""
        return text

    async def _notification_for_completed_reply_text(
        ctx: "EventContext",
        thread_id: str,
        text: str,
    ) -> tuple[str, str, str, str | None]:
        notification_status, notification_message = _notification_for_turn_status(
            "completed",
            {"status": "completed"},
            ctx,
        )
        (
            snapshot_agent_id,
            snapshot_agent_name,
            task_name_snapshot,
        ) = _notification_context(ctx, thread_id)
        task_summary_snapshot = _notification_task_summary(snapshot_agent_id, thread_id)
        event_turn_id = _extract_turn_id(ctx.event_params)
        result = await state.message_bus.notification_summary.build_completed_notification(
            final_message=text,
            provider_id=snapshot_agent_id,
            session_id=thread_id,
            turn_id=event_turn_id or "",
            current_title=task_name_snapshot,
            current_task_summary=task_summary_snapshot,
            agent_name=snapshot_agent_name,
            status="completed",
            run_scenario=run_ai_scenario,
        )
        task_summary_override: str | None = None
        if result.task_summary_override or result.task_name_override:
            task_summary_override = result.task_summary_override
        return (
            notification_status,
            result.message or notification_message,
            result.task_name_override or task_name_snapshot,
            task_summary_override if task_summary_override is not None else task_summary_snapshot,
        )

    async def _do_edit(thread_id: str, st: StreamingTurn, text: str) -> bool:
        """实际执行 telegram 消息编辑，更新 last_edit_time。网络错误时最多重试 2 次。"""
        truncated = _truncate_text(text)
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                await bot.edit_message_text(
                    chat_id=group_chat_id,
                    message_id=st.message_id,
                    text=truncated,
                )
                st.last_edit_time = time.monotonic()
                return True
            except Exception as e:
                err_str = str(e)
                if "Message_too_long" in err_str or "message is too long" in err_str.lower():
                    logger.warning(f"[streaming] Message_too_long, 二次截断 thread={thread_id[:8]}")
                    try:
                        fallback = _truncate_text(text, limit=3800)
                        await bot.edit_message_text(
                            chat_id=group_chat_id,
                            message_id=st.message_id,
                            text=fallback,
                        )
                        st.last_edit_time = time.monotonic()
                        return True
                    except Exception as e2:
                        logger.error(f"[streaming] 二次截断仍失败 thread={thread_id[:8]}: {e2}")
                    return False
                elif "Message is not modified" in err_str:
                    return True  # 内容没变，可视为已同步
                elif _is_network_error(e) and attempt < max_retries:
                    wait = 1.0 * (attempt + 1)
                    logger.warning(f"[streaming] edit 网络错误，{wait}s 后重试 ({attempt+1}/{max_retries}) thread={thread_id[:8]}: {e}")
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.debug(f"[streaming] edit 失败 thread={thread_id[:8]}: {e}")
                    return False
        return False

    async def _do_formatted_final_edit(
        thread_id: str,
        st: StreamingTurn,
        raw_text: str,
    ) -> bool:
        rendered = format_telegram_assistant_final_text(raw_text)
        attempts = [(rendered.text, rendered.parse_mode)]
        if rendered.parse_mode is not None:
            attempts.append((rendered.fallback_text, None))

        for text, parse_mode in attempts:
            try:
                kwargs = {
                    "chat_id": group_chat_id,
                    "message_id": st.message_id,
                    "text": text if parse_mode else _truncate_text(text),
                }
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                await bot.edit_message_text(**kwargs)
                st.last_edit_time = time.monotonic()
                logger.info(
                    f"[streaming] 最终回复已按 {'HTML' if parse_mode else 'plain text'} edit "
                    f"thread={thread_id[:8]} msg_id={st.message_id}"
                )
                return True
            except Exception as e:
                err_str = str(e)
                if "Message is not modified" in err_str:
                    st.last_edit_time = time.monotonic()
                    logger.info(
                        f"[streaming] 最终回复 {'HTML' if parse_mode else 'plain text'} 已是最新，无需重复 edit "
                        f"thread={thread_id[:8]} msg_id={st.message_id}"
                    )
                    return True
                if parse_mode is not None:
                    logger.warning(
                        f"[streaming] 最终回复富文本 edit 失败，回退 plain text "
                        f"thread={thread_id[:8]}: {e}"
                    )
                    continue
                logger.debug(f"[streaming] 最终回复 plain text edit 失败 thread={thread_id[:8]}: {e}")
                return False
        return False

    async def _send_formatted_final_reply(
        thread_id: str,
        topic_id: int,
        raw_text: str,
    ) -> bool:
        rendered = format_telegram_assistant_final_text(raw_text)
        attempts = [(rendered.text, rendered.parse_mode)]
        if rendered.parse_mode is not None:
            attempts.append((rendered.fallback_text, None))

        for text, parse_mode in attempts:
            try:
                kwargs = {}
                if parse_mode:
                    kwargs["parse_mode"] = parse_mode
                await _send_to_group(
                    bot,
                    group_chat_id,
                    text if parse_mode else _truncate_text(text),
                    topic_id=topic_id,
                    **kwargs,
                )
                logger.info(
                    f"[event→TG] 最终回复已按 {'HTML' if parse_mode else 'plain text'} send "
                    f"thread={thread_id[:8]} topic={topic_id}"
                )
                return True
            except Exception as e:
                if parse_mode is not None:
                    logger.warning(
                        f"[event→TG] 最终回复富文本 send 失败，回退 plain text "
                        f"thread={thread_id[:8]}: {e}"
                    )
                    continue
                logger.error(f"[event→TG] fallback 发最终回复失败：{e}")
                return False
        return False

    def _is_stale_turn_event(st: StreamingTurn, event_turn_id: Optional[str]) -> bool:
        return bool(event_turn_id and st.turn_id and event_turn_id != st.turn_id)

    async def _finalize_replaced_streaming_turn(thread_id: str, st: StreamingTurn) -> None:
        if st.throttle_task and not st.throttle_task.done():
            st.throttle_task.cancel()
            st.throttle_task = None
        st.completed = True

        # 旧 turn 还停留在占位消息时，先把它收口，避免“思考中...”悬挂。
        if not st.placeholder_deleted or not st.buffer.strip() or st.buffer.strip() == "⏳ 思考中...":
            try:
                await _do_edit(thread_id, st, tg_empty_turn_completed_text())
            except Exception as e:
                logger.debug(f"[streaming] 收口被替换旧 turn 失败 thread={thread_id[:8]}: {e}")

        state.streaming_turns.pop(thread_id, None)
        codex_state.mark_tui_turn_completed(state, thread_id)

    def _ensure_throttle_task(thread_id: str, st: StreamingTurn) -> None:
        """
        确保有一个节流 loop 在运行。
        如果已有 task 且未结束，什么都不做（它会在 sleep 到期后 edit 最新 buffer）。
        否则创建新 task：立刻 edit 一次，然后每 THROTTLE_INTERVAL 再 edit 一次，
        直到 buffer 不再变化。
        """
        if st.throttle_task and not st.throttle_task.done():
            return  # 已有 loop 在跑，delta 只需更新 buffer，loop 自会取最新值

        async def _throttle_loop():
            # 第一次 edit：立刻执行
            last_sent = ""
            while thread_id in state.streaming_turns:
                st2 = state.streaming_turns.get(thread_id)
                if st2 is None or st2.completed:
                    break
                current = st2.buffer
                if current != last_sent:
                    await _do_edit(thread_id, st2, current)
                    last_sent = current
                # 等待节流间隔，期间 buffer 可能继续更新
                await asyncio.sleep(THROTTLE_INTERVAL)
                # 睡醒后再检查一次，如果 buffer 又变了就再 edit
                st2 = state.streaming_turns.get(thread_id)
                if st2 is None or st2.completed:
                    break
                if st2.buffer != last_sent:
                    await _do_edit(thread_id, st2, st2.buffer)
                    last_sent = st2.buffer
                else:
                    # buffer 没变，loop 结束（等下一个 delta 重新触发）
                    break

        st.throttle_task = asyncio.create_task(_throttle_loop())

    @dataclass
    class EventContext:
        """Per-event context passed to all handler functions."""
        event: SessionEvent
        message_event: Any
        msg: dict  # full message dict with id, method, params

        @property
        def ws_daemon_id(self) -> str:
            return self.event.workspace_id

        @property
        def thread_id(self) -> Optional[str]:
            return self.event.thread_id

        @property
        def event_params(self) -> dict:
            return self.event.payload

        @property
        def message_kind(self) -> str:
            return str(getattr(self.message_event, "kind", "") or "").strip()

        @property
        def message_payload(self) -> dict:
            payload = getattr(self.message_event, "payload", None)
            return payload if isinstance(payload, dict) else {}

    def _message_event_text(ctx: EventContext) -> str:
        payload = ctx.message_payload
        return str(
            payload.get("text")
            or payload.get("delta")
            or payload.get("message")
            or ""
        ).strip()

    def _message_event_title(ctx: EventContext) -> str:
        return str(ctx.message_payload.get("title") or "").strip()

    def _message_event_status(ctx: EventContext) -> str:
        return str(ctx.message_payload.get("status") or "").strip().lower()

    def _message_event_reason(ctx: EventContext) -> str:
        return str(ctx.message_payload.get("reason") or "").strip()

    def _canonical_turn_status(ctx: EventContext) -> str:
        status = _message_event_status(ctx)
        if ctx.message_kind == "turn.completed":
            return "completed"
        if ctx.message_kind == "turn.failed":
            if status in {"aborted", "cancelled", "canceled", "error", "failed"}:
                return status
            if _message_event_reason(ctx):
                return "aborted"
            return "failed"
        if ctx.event.kind == "turn_aborted":
            return "aborted"
        return status

    async def _handle_approval(ctx: EventContext) -> None:
        """item/commandExecution/requestApproval"""
        approval_params = ctx.event_params
        if approval_params.get("_mirroredOnly") is True:
            logger.info(
                "[approval_request] 外部 CLI 权限请求仅镜像到看板，不接管授权 thread=%s request=%s",
                ctx.thread_id or approval_params.get("threadId") or "N/A",
                approval_params.get("request_id") or ctx.msg.get("id") or "N/A",
            )
            return
        request_id = approval_params.get("request_id") or ctx.msg.get("id")
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = approval_params.get("threadId")
        provider_name = str(
            approval_params.get("_provider") or ctx.event.provider or ""
        ).strip()
        if provider_name == "unknown":
            provider_name = ""
        if provider_name and not approval_params.get("_provider"):
            if get_provider(provider_name) is None:
                provider_name = ""
        if not provider_name and thread_id:
            found = state.find_thread_by_id_global(thread_id)
            if found:
                provider_name = str(found[0].tool or "").strip()
        if not provider_name and thread_id:
            if codex_state.get_current_run(state, thread_id) is not None:
                provider_name = "codex"
        if not provider_name and ctx.ws_daemon_id:
            provider_name = str(
                state.get_tool_for_workspace(ctx.ws_daemon_id) or ""
            ).strip()

        info = _parse_provider_approval_request(
            provider_name or "codex",
            approval_params,
            request_id=request_id,
            default_thread_id=thread_id,
            approval_source="app_server",
        )

        workspace_id, topic_id, route_error = _resolve_approval_target(
            state,
            ctx.ws_daemon_id,
            thread_id,
        )
        if route_error is not None:
            logger.error(
                "[approval_target] %s tool=%s thread=%s ws=%s",
                route_error,
                info.tool_type,
                thread_id or "N/A",
                ctx.ws_daemon_id or "N/A",
            )
            _log_discarded_unroutable_approval(
                info,
                route_error=route_error,
                ws_daemon_id=ctx.ws_daemon_id,
            )
            return

        if info.tool_type == "codex" and thread_id and request_id is not None:
            codex_state.add_interruption(
                state,
                thread_id=thread_id,
                interruption_id=str(request_id),
            )
        await send_approval_to_telegram(state, bot, group_chat_id, topic_id, workspace_id, info)
        await _emit_notification(
            ctx,
            thread_id=thread_id,
            status="needs_action",
            message="需要处理授权请求",
            task_id=str(request_id or thread_id or workspace_id),
        )

    async def _handle_question(ctx: EventContext) -> None:
        """question/asked"""
        if ctx.event_params.get("_mirroredOnly") is True:
            logger.info(
                "[question] 外部 CLI question 仅镜像到看板，不接管输入 thread=%s question=%s",
                ctx.thread_id or ctx.event_params.get("threadId") or "N/A",
                ctx.event_params.get("questionId") or "N/A",
            )
            return
        question_request = _parse_provider_question_request(
            ctx.event.provider,
            ctx.event_params,
            default_thread_id=ctx.thread_id,
            question_source="app_server",
        )
        question_id = question_request.question_id
        thread_id = question_request.thread_id
        topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)

        try:
            workspace_id = ""
            tool_name = question_request.tool_type
            if question_request.thread_id:
                found2 = state.find_thread_by_id_global(question_request.thread_id)
                if found2:
                    workspace_id = found2[0].daemon_workspace_id or ""
                    tool_name = tool_name if tool_name and tool_name != "unknown" else found2[0].tool or ""
            if not workspace_id:
                workspace_id = ctx.ws_daemon_id
            if (not tool_name or tool_name == "unknown") and ctx.ws_daemon_id:
                tool_name = state.get_tool_for_workspace(ctx.ws_daemon_id) or ""
            if tool_name and tool_name != question_request.tool_type:
                question_request = replace(question_request, tool_type=tool_name)

            await send_question_to_telegram(
                state,
                bot,
                group_chat_id,
                topic_id,
                workspace_id,
                question_request,
            )
            await _emit_notification(
                ctx,
                thread_id=thread_id,
                status="needs_action",
                message="需要回答问题",
                task_id=question_id or thread_id or ctx.ws_daemon_id,
            )
        except Exception as e:
            logger.error(f"推送 question 到 Telegram 失败：{e}")

    async def _handle_turn_started(ctx: EventContext) -> None:
        """turn/started"""
        turn = ctx.event_params.get("turn", {})
        thread_id = ctx.thread_id
        turn_id = ""
        if isinstance(turn, dict):
            turn_id = turn.get("id", "") or turn.get("turnId", "")
        if not turn_id:
            turn_id = ctx.event_params.get("turnId") or ""
        if not thread_id:
            thread_id = (
                ctx.event_params.get("threadId")
                or ctx.event_params.get("thread_id")
                or (turn.get("threadId") if isinstance(turn, dict) else None)
            )
        if not thread_id:
            return

        topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)
        if topic_id is None:
            if not _provider_should_materialize_unbound_thread_topic(state, thread_id):
                logger.info(
                    "[streaming] turn/started provider thread 未绑定 TG topic，按 provider 策略跳过 TG 同步: "
                    "thread=%s provider=%s",
                    thread_id[:12],
                    ctx.event.provider or "?",
                )
                return
            else:
                topic_id = await _materialize_thread_topic_if_needed(
                    state,
                    bot,
                    group_chat_id,
                    thread_id,
                )
        if topic_id is None:
            # thread 已占位注册但 topic 还未创建完成，短暂等待后重试
            # （session.created 的 create_forum_topic 仍在进行中）
            for _ in range(20):  # 最多等 2s（20 × 0.1s）
                await asyncio.sleep(0.1)
                topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)
                if topic_id is not None:
                    break
            if topic_id is None:
                logger.warning(f"[streaming] turn/started topic_id 仍为 None，跳过 thread={thread_id[:8]}")
                return

        # 如果已有进行中的 turn（含 bot 重启后 SSE 重放场景），直接复用，不重复发占位消息
        if thread_id in state.streaming_turns:
            st = state.streaming_turns[thread_id]
            if turn_id and st.turn_id and turn_id != st.turn_id:
                logger.info(
                    f"[streaming] 检测到新 turn 覆盖旧 turn，切换承载消息 "
                    f"thread={thread_id[:8]} old={st.turn_id[:12]} new={turn_id[:12]}"
                )
                await _finalize_replaced_streaming_turn(thread_id, st)
            else:
                if turn_id:
                    st.turn_id = turn_id
                codex_state.mark_tui_turn_started(state, thread_id)
                logger.debug(f"[streaming] turn/started 重复，复用已有占位 thread={thread_id[:8]}")
                return

        try:
            sent = await _send_to_group(bot, group_chat_id, "⏳ 思考中...", topic_id=topic_id)
            if sent:
                if ctx.event.provider == "codex" and turn_id:
                    current_run = codex_state.get_current_run(state, thread_id)
                    if current_run is None or current_run.turn_id != turn_id:
                        codex_state.start_run(
                            state,
                            workspace_id=ctx.ws_daemon_id,
                            thread_id=thread_id,
                            turn_id=turn_id,
                        )
                    else:
                        codex_state.mark_run(state, thread_id=thread_id, status="started")
                codex_state.mark_tui_turn_started(state, thread_id)
                state.streaming_turns[thread_id] = StreamingTurn(
                    message_id=sent.message_id,
                    topic_id=topic_id,
                    turn_id=turn_id or None,
                    last_edit_time=0,
                )
                logger.info(f"[streaming] turn/started thread={thread_id[:8]} msg_id={sent.message_id}")
                # 持久化 msg_id，bot 重启后可恢复 streaming_turns
                ws = state.find_workspace_by_daemon_id(ctx.ws_daemon_id) if ctx.ws_daemon_id else None
                _storage = state.storage
                if ws and _storage:
                    tinfo = ws.threads.get(thread_id)
                    if tinfo:
                        tinfo.streaming_msg_id = sent.message_id
                        save_storage(_storage)
        except Exception as e:
            logger.error(f"[streaming] 发占位消息失败：{e}")

    async def _handle_item_started(ctx: EventContext) -> None:
        """item/started — no-op, just return."""
        return

    async def _handle_agent_message_delta(ctx: EventContext) -> None:
        """item/agentMessage/delta"""
        if ctx.message_kind != "message.assistant.delta":
            return
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = ctx.event_params.get("threadId") or ctx.event_params.get("thread_id")
        if not thread_id:
            return

        delta = _message_event_text(ctx)
        if not delta:
            return

        st = state.streaming_turns.get(thread_id)
        if st is None:
            logger.debug(f"[streaming] 收到 delta 但无 streaming turn, thread={thread_id[:8]}")
            return

        event_turn_id = _extract_turn_id(ctx.event_params)
        if _is_stale_turn_event(st, event_turn_id):
            logger.info(
                f"[streaming] 忽略旧 turn delta thread={thread_id[:8]} "
                f"event_turn={event_turn_id[:12]} current_turn={st.turn_id[:12]}"
            )
            return
        if ctx.event.provider == "codex":
            codex_state.mark_run(state, thread_id=thread_id, first_progress_at=True)

        # 第一个 delta：删除占位消息，发新消息，切换 message_id
        if not st.placeholder_deleted:
            st.placeholder_deleted = True
            try:
                await bot.delete_message(
                    chat_id=group_chat_id,
                    message_id=st.message_id,
                )
            except Exception as e:
                logger.debug(f"[streaming] 删除占位消息失败（忽略）: {e}")
            try:
                sent = await _send_to_group(bot, group_chat_id, delta, topic_id=st.topic_id)
                if sent:
                    st.message_id = sent.message_id
                    st.buffer = delta
                    ws = state.find_workspace_by_daemon_id(ctx.ws_daemon_id) if ctx.ws_daemon_id else None
                    _storage = state.storage
                    if ws and _storage:
                        tinfo = ws.threads.get(thread_id)
                        if tinfo and tinfo.streaming_msg_id != sent.message_id:
                            tinfo.streaming_msg_id = sent.message_id
                            save_storage(_storage)
                    logger.info(f"[streaming] 切换到新消息 thread={thread_id[:8]} new_msg_id={sent.message_id}")
                    return
            except Exception as e:
                logger.error(f"[streaming] 发新消息失败: {e}")
                return

        st.buffer += delta
        _ensure_throttle_task(thread_id, st)

    async def _handle_item_completed(ctx: EventContext) -> None:
        """item/completed — agentMessage or shellCommand."""
        item = ctx.event_params.get("item", {})
        item_type = item.get("type", "") if isinstance(item, dict) else ""
        semantic_payload = _codex_semantic_payload(ctx)
        is_final_answer = ctx.message_kind == "message.assistant.final"

        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = (
                ctx.event_params.get("threadId")
                or ctx.event_params.get("thread_id")
                or item.get("threadId")
            )
        event_turn_id = _extract_turn_id(ctx.event_params)

        if ctx.message_kind in {"message.assistant.delta", "message.assistant.final"}:
            text = _message_event_text(ctx)
            phase = "final_answer" if is_final_answer else "commentary"
            notification_status = ""
            notification_message = ""
            notification_task_name_override = ""
            notification_task_summary_override: str | None = None
            notification_task_name_snapshot = ""
            notification_task_summary_snapshot: str | None = None
            if semantic_payload:
                text = str(semantic_payload.get("text") or text).strip()
            if not text or not thread_id:
                return
            st = state.streaming_turns.get(thread_id)
            ws = _resolve_workspace_info(state, ctx.ws_daemon_id, thread_id)
            topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)
            prefix = "🤖" if phase == "final_answer" else "💭"
            delivered_to_tg = False

            if (
                is_final_answer
                and ctx.event.provider == "codex"
                and st is None
                and _codex_final_reply_already_synced(thread_id, event_turn_id)
            ):
                codex_state.mark_run(state, thread_id=thread_id, status="completed")
                logger.info(
                    "[event→TG] 跳过已同步 codex final duplicate thread=%s turn=%s",
                    thread_id[:8],
                    (event_turn_id or "")[:12] or "?",
                )
                return

            if is_final_answer and not notification_status:
                notification_status, notification_message = _notification_for_turn_status(
                    "completed",
                    {"status": "completed"},
                    ctx,
                )

            if st is not None and _is_stale_turn_event(st, event_turn_id):
                logger.info(
                    f"[streaming] 忽略旧 turn item/completed thread={thread_id[:8]} "
                    f"event_turn={event_turn_id[:12]} current_turn={st.turn_id[:12]}"
                )
                return

            if st is not None and not st.completed:
                # 有占位消息且 turn 未完成：edit 占位消息（覆盖"思考中..."或之前的流式内容）
                if st.throttle_task and not st.throttle_task.done():
                    st.throttle_task.cancel()
                    st.throttle_task = None
                if is_final_answer:
                    st.buffer = text
                    delivered_to_tg = await _do_formatted_final_edit(thread_id, st, text)
                    if delivered_to_tg:
                        st.completed = True
                else:
                    st.buffer = f"{prefix} {text}"
                    delivered_to_tg = await _do_edit(thread_id, st, st.buffer)
            elif st is not None and st.completed:
                logger.debug(
                    f"[item/completed] agentMessage turn 已结束，跳过 "
                    f"thread={thread_id[:8]} text={text[:60]}"
                )
            else:
                # 无占位消息（不在 streaming_turns 中）：发新消息
                if topic_id is None:
                    logger.warning(
                        f"[item/completed] thread topic_id 为 None，跳过发送消息 "
                        f"thread={thread_id[:8]} text={text[:60]}"
                    )
                else:
                    if is_final_answer:
                        delivered_to_tg = await _send_formatted_final_reply(thread_id, topic_id, text)
                    else:
                        out = _truncate_text(f"{prefix} {text}")
                        try:
                            await _send_to_group(bot, group_chat_id, out, topic_id=topic_id)
                            delivered_to_tg = True
                        except Exception as e:
                            logger.error(f"[event→TG] fallback 发 agentMessage 失败：{e}")
            if delivered_to_tg and phase == "final_answer" and ws is not None and ws.tool == "codex":
                remember_codex_tg_synced_final_reply(
                    state,
                    thread_id,
                    text=text,
                )
                codex_state.mark_run(
                    state,
                    thread_id=thread_id,
                    final_reply_synced_to_tg=True,
                )
            if is_final_answer and notification_status:
                if not _claim_streaming_notification(st, thread_id, source="item_completed"):
                    return
                if notification_status == "completed":
                    (
                        notification_status,
                        notification_message,
                        notification_task_name_override,
                        notification_task_summary_override,
                    ) = await _notification_for_completed_reply_text(ctx, thread_id, text)
                await _emit_notification(
                    ctx,
                    thread_id=thread_id,
                    status=notification_status,
                    message=notification_message,
                    task_name_override=notification_task_name_override or notification_task_name_snapshot,
                    task_summary_override=(
                        notification_task_summary_override
                        if notification_task_summary_override is not None
                        else notification_task_summary_snapshot
                    ),
                )
            return

        if ctx.message_kind == "shell.command.completed" or item_type == "shellCommand":
            # 只记录日志，不推送到 TG（工具调用结果不属于文字类消息）
            cmd = item.get("command", "")
            logger.debug(f"[item/completed] shellCommand 忽略推送 thread={thread_id[:8] if thread_id else '?'} cmd={cmd[:60]}")

    async def _handle_turn_completed(ctx: EventContext) -> None:
        """turn/completed / turn_aborted"""
        turn = ctx.event_params.get("turn", {})
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = (
                ctx.event_params.get("threadId")
                or ctx.event_params.get("thread_id")
                or (turn.get("threadId") if isinstance(turn, dict) else None)
                or (turn.get("thread_id") if isinstance(turn, dict) else None)
            )
        if not thread_id:
            return

        status = _canonical_turn_status(ctx)

        st = state.streaming_turns.get(thread_id)
        event_turn_id = _extract_turn_id(ctx.event_params)
        run_status = status or "completed"
        is_tui_mirror_completion = _is_codex_tui_mirror_completion(ctx, run_status, turn)
        completed_reply_text = ""
        if st is not None:
            if st.completed:
                logger.debug(f"[streaming] turn/completed 已由 final item 收口 thread={thread_id[:8]}")
                completed_reply_text = _completed_reply_text_from_stream(st)
                ws = _resolve_workspace_info(state, ctx.ws_daemon_id, thread_id)
                _storage = state.storage
                if ws and _storage:
                    tinfo = ws.threads.get(thread_id)
                    if tinfo and tinfo.streaming_msg_id is not None:
                        tinfo.streaming_msg_id = None
                        save_storage(_storage)
                state.streaming_turns.pop(thread_id, None)
                codex_state.mark_tui_turn_completed(state, thread_id)
                if ctx.event.provider == "codex":
                    codex_state.mark_run(
                        state,
                        thread_id=thread_id,
                        status=run_status,
                    )
                if _claim_streaming_notification(st, thread_id, source="turn_completed_done"):
                    if is_tui_mirror_completion and completed_reply_text and run_status == "completed":
                        (
                            notification_status,
                            notification_message,
                            task_name_override,
                            task_summary_override,
                        ) = await _notification_for_completed_reply_text(ctx, thread_id, completed_reply_text)
                        await _emit_notification(
                            ctx,
                            thread_id=thread_id,
                            status=notification_status,
                            message=notification_message,
                            task_name_override=task_name_override,
                            task_summary_override=task_summary_override,
                        )
                    elif not is_tui_mirror_completion:
                        notification_status, notification_message = _notification_for_turn_status(run_status, turn, ctx)
                        await _emit_notification(
                            ctx,
                            thread_id=thread_id,
                            status=notification_status,
                            message=notification_message,
                        )
                return
            if _is_stale_turn_event(st, event_turn_id):
                logger.info(
                    f"[streaming] 忽略旧 turn/completed thread={thread_id[:8]} "
                    f"event_turn={event_turn_id[:12]} current_turn={st.turn_id[:12]}"
                )
                return
            if st.throttle_task and not st.throttle_task.done():
                st.throttle_task.cancel()
            st.completed = True
            streamed_reply_text = ""

            if status == "aborted":
                reason = _message_event_reason(ctx)
                run_status = "aborted"
                try:
                    await _do_edit(
                        thread_id,
                        st,
                        _build_incomplete_turn_text(st.buffer, reason),
                    )
                except Exception as e:
                    logger.error(f"[streaming] edit aborted status 失败：{e}")
            elif status in {"error", "failed", "cancelled"}:
                err = (turn.get("error") if isinstance(turn, dict) else None) or "未知错误"
                label = "已失败" if status == "failed" else "已取消" if status == "cancelled" else "错误"
                run_status = status
                base = st.buffer.strip() or f"❌ {label}"
                error_text = f"\n\n❌ {label}：{err}"
                new_text = _truncate_text(base + error_text)
                try:
                    await _do_edit(thread_id, st, new_text)
                except Exception as e:
                    logger.error(f"[streaming] edit error status 失败：{e}")
            elif not st.buffer or st.buffer.strip() == "⏳ 思考中...":
                # 没有收到任何有效内容，把占位消息改为"✅ 已完成"，让用户知道任务执行完了
                try:
                    await _do_edit(thread_id, st, tg_empty_turn_completed_text())
                    logger.info(f"[streaming] 空 buffer turn 完成，edit 为已完成 thread={thread_id[:8]} msg_id={st.message_id}")
                except Exception as e:
                    logger.debug(f"[streaming] edit 已完成失败 thread={thread_id[:8]}: {e}")
            else:
                streamed_reply_text = _completed_reply_text_from_stream(st)
                if not streamed_reply_text:
                    # mirror/commentary-only completions may end with a local
                    # processing placeholder instead of a user-visible final
                    # reply. Treat them like an empty completion so they do not
                    # publish bogus final text or completion notifications.
                    try:
                        await _do_edit(thread_id, st, tg_empty_turn_completed_text())
                        logger.info(
                            f"[streaming] 空 buffer turn 完成，edit 为已完成 thread={thread_id[:8]} msg_id={st.message_id}"
                        )
                    except Exception as e:
                        logger.debug(f"[streaming] edit 已完成失败 thread={thread_id[:8]}: {e}")
                else:
                    completed_reply_text = streamed_reply_text
                    if _looks_like_markdown_final_text(streamed_reply_text):
                        try:
                            await _do_formatted_final_edit(thread_id, st, streamed_reply_text)
                        except Exception as e:
                            logger.debug(
                                f"[streaming] turn/completed final formatted edit 失败 "
                                f"thread={thread_id[:8]}: {e}"
                            )

            logger.info(f"[streaming] turn/completed thread={thread_id[:8]} status={status}")
            ws = _resolve_workspace_info(state, ctx.ws_daemon_id, thread_id)
            if streamed_reply_text and ws is not None and ws.tool == "codex":
                remember_codex_tg_synced_final_reply(
                    state,
                    thread_id,
                    text=streamed_reply_text,
                )
                codex_state.mark_run(
                    state,
                    thread_id=thread_id,
                    final_reply_synced_to_tg=True,
                )
            # 清除持久化的 streaming_msg_id
            _storage = state.storage
            if ws and _storage:
                tinfo = ws.threads.get(thread_id)
                if tinfo and tinfo.streaming_msg_id is not None:
                    tinfo.streaming_msg_id = None
                    save_storage(_storage)
            # 从内存中移除，确保下一次 turn/started 不会误"复用"
            state.streaming_turns.pop(thread_id, None)
            codex_state.mark_tui_turn_completed(state, thread_id)
        else:
            codex_state.mark_tui_turn_completed(state, thread_id)
            logger.debug(f"[streaming] turn/completed 无 streaming state thread={thread_id[:8]}")

        if ctx.event.provider == "codex":
            codex_state.mark_run(
                state,
                thread_id=thread_id,
                status=run_status,
            )
        if st is None:
            if is_tui_mirror_completion:
                return
            if ctx.event.provider == "codex" and _codex_final_reply_already_synced(thread_id, event_turn_id):
                logger.info(
                    "[notification] 跳过已同步 codex completion duplicate thread=%s turn=%s",
                    thread_id[:8],
                    (event_turn_id or "")[:12] or "?",
                )
                return
            notification_status, notification_message = _notification_for_turn_status(run_status, turn, ctx)
            await _emit_notification(
                ctx,
                thread_id=thread_id,
                status=notification_status,
                message=notification_message,
            )
            return

        if _claim_streaming_notification(st, thread_id, source="turn_completed"):
            if is_tui_mirror_completion:
                if completed_reply_text:
                    _publish_buffered_final_message(
                        ctx,
                        thread_id=thread_id,
                        text=completed_reply_text,
                        turn_id=event_turn_id or "",
                    )
                    (
                        notification_status,
                        notification_message,
                        task_name_override,
                        task_summary_override,
                    ) = await _notification_for_completed_reply_text(ctx, thread_id, completed_reply_text)
                    await _emit_notification(
                        ctx,
                        thread_id=thread_id,
                        status=notification_status,
                        message=notification_message,
                        task_name_override=task_name_override,
                        task_summary_override=task_summary_override,
                    )
                return
            if not is_tui_mirror_completion:
                notification_status, notification_message = _notification_for_turn_status(run_status, turn, ctx)
                await _emit_notification(
                    ctx,
                    thread_id=thread_id,
                    status=notification_status,
                    message=notification_message,
                )

    async def _handle_session_created(ctx: EventContext) -> None:
        """session.created"""
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = ctx.event_params.get("threadId")
        title = ctx.event_params.get("title", "")
        if not thread_id:
            return

        found = state.find_thread_by_id_global(thread_id)
        if found:
            logger.debug(f"[session.created] thread {thread_id[:8]}… 已注册，跳过")
            return

        ws_info = state.find_workspace_by_daemon_id(ctx.ws_daemon_id) if ctx.ws_daemon_id else None
        if not ws_info:
            logger.debug(f"[session.created] 未找到 workspace ws={ctx.ws_daemon_id[:16] if ctx.ws_daemon_id else '?'}，跳过")
            return

        # 只注册 thread，不自动创建 TG topic
        # topic 由用户通过 /list 点按钮时按需创建
        thread_info = ThreadInfo(
            thread_id=thread_id,
            topic_id=None,
            preview=title or None,
            archived=False,
            is_active=True,
        )
        ws_info.threads[thread_id] = thread_info
        if state.storage:
            save_storage(state.storage)
        logger.info(f"[session.created] 注册 thread {thread_id[:8]}…（无 topic，等用户按需创建）")

    async def _handle_session_title_updated(ctx: EventContext) -> None:
        """session.title_updated"""
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = ctx.event_params.get("threadId")
        title = _message_event_title(ctx) or ctx.event_params.get("title", "")
        if not thread_id or not title:
            return

        found = state.find_thread_by_id_global(thread_id)
        if not found:
            logger.debug(f"[title_update] thread {thread_id[:8]}… 未注册，跳过")
            return

        ws_info, thread_info = found
        topic_id = _thread_topic_id(state, ws_info, thread_info)
        if not topic_id:
            return

        new_topic_name = _make_thread_topic_name(
            ws_info.tool or "provider",
            ws_info.name,
            title,
            thread_id,
        )

        try:
            await bot.edit_forum_topic(
                chat_id=group_chat_id,
                message_thread_id=topic_id,
                name=new_topic_name,
            )
            thread_info.preview = title
            if state.storage:
                save_storage(state.storage)
            logger.info(f"[title_update] Topic {topic_id} renamed → {new_topic_name}")
        except Exception as e:
            logger.warning(f"[title_update] rename Topic {topic_id} 失败：{e}")

    _EVENT_HANDLERS = {
        "approval_requested": _handle_approval,
        "question_requested": _handle_question,
        "turn_started": _handle_turn_started,
        "item_started": _handle_item_started,
        "assistant_delta": _handle_agent_message_delta,
        "assistant_completed": _handle_item_completed,
        "shell_command_completed": _handle_item_completed,
        "item_completed": _handle_item_completed,
        "turn_completed": _handle_turn_completed,
        "turn_aborted": _handle_turn_completed,
        "session_created": _handle_session_created,
        "session_title_updated": _handle_session_title_updated,
    }

    async def on_event(method: str, params: dict) -> None:
        event = normalize_session_event(method, params)
        if event is None:
            return
        message_event = message_event_from_session_event(event)

        msg = params.get("message", {})
        thread_id = event.thread_id
        ws_daemon_id = event.workspace_id

        logger.debug(
            f"[event] {event.raw_method} kind={event.kind} semantic={event.semantic_kind or '-'} "
            f"ws={ws_daemon_id[:8] if ws_daemon_id else '?'} "
            f"thread={thread_id[:8] if thread_id else '?'}"
        )
        publish_session_message_event(state, event)

        ctx = EventContext(
            event=event,
            message_event=message_event,
            msg=msg,
        )

        handler = _EVENT_HANDLERS.get(event.kind)
        if handler:
            await handler(ctx)

    return on_event


def make_server_request_handler(state: AppState, bot: Bot, group_chat_id: int):
    """
    返回 daemon server request 回调（处理需要用户响应的请求）。

    目前处理：
        Codex/Provider app-server approval requests → 推送沙盒权限授权请求
    """
    async def on_server_request(method: str, params: dict, request_id: int) -> None:
        provider_id = _provider_for_server_request_method(state, method, params)
        if not provider_id:
            logger.debug(f"[server_request] 忽略未处理的 method={method}")
            return

        info = _parse_provider_approval_request(
            provider_id,
            params,
            request_id=request_id,
            approval_source=method,
        )
        thread_id = info.thread_id

        ws_daemon_id = str(
            params.get("_workspaceId")
            or params.get("workspaceId")
            or params.get("workspace_id")
            or ""
        )
        workspace_id, topic_id, route_error = _resolve_approval_target(
            state,
            ws_daemon_id,
            thread_id,
        )
        if route_error is not None:
            logger.error(
                "[approval_target] %s tool=%s thread=%s ws=%s",
                route_error,
                provider_id,
                thread_id or "N/A",
                workspace_id or "N/A",
            )
            _log_discarded_unroutable_approval(
                info,
                route_error=route_error,
                ws_daemon_id=workspace_id,
            )
            return

        logger.info(
            f"[approval_request] id={request_id} thread={thread_id[:8] if thread_id else '?'} "
            f"cmd={info.command[:60]} topic={topic_id}"
        )
        await send_approval_to_telegram(
            state, bot, group_chat_id, topic_id, workspace_id, info,
        )

    return on_server_request
