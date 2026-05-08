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
from dataclasses import dataclass
from typing import Any, Optional
from telegram import Bot
from core.state import AppState, PendingApproval, PendingQuestion, PendingQuestionGroup, StreamingTurn
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from plugins.providers.builtin.codex.python.tui_bridge import (
    remember_codex_tg_synced_final_reply,
)
from core.providers.session_events import SessionEvent, normalize_session_event
from core.telegram_formatting import format_telegram_assistant_final_text
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
    if thread_info.topic_id is not None:
        return thread_info.topic_id

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
        thread_info.topic_id = topic.message_thread_id
        if state.storage is not None:
            save_storage(state.storage)

        logger.info(
            "[streaming] 已按需 materialize thread topic: tool=%s ws=%s thread=%s topic=%s",
            ws_info.tool,
            ws_info.name,
            thread_id[:12],
            thread_info.topic_id,
        )

        replay_cursor = await _replay_thread_history(
            bot=bot,
            group_chat_id=group_chat_id,
            topic_id=thread_info.topic_id,
            thread_id=thread_id,
            sessions_dir=None,
            tool_name=ws_info.tool,
        )
        if (
            replay_cursor
            and thread_info.history_sync_cursor != replay_cursor
            and state.storage is not None
        ):
            thread_info.history_sync_cursor = replay_cursor
            save_storage(state.storage)
        return thread_info.topic_id
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


@dataclass
class ApprovalInfo:
    """Unified approval info extracted from different sources."""
    request_id: Any
    thread_id: Optional[str]
    command: str
    reason: str
    tool_name: str
    proposed_amendment: list
    amendment_decision: dict
    tool_type: str
    always_patterns: list
    approval_source: str = "app_server"


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
) -> None:
    """Shared approval UI: format text, send message, record PendingApproval, attach keyboard."""
    text = tg_approval_request_text(
        command=info.command,
        reason=info.reason,
        tool_type=info.tool_type,
    )

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
        keyboard = build_approval_keyboard(msg_id)
        await bot.edit_message_reply_markup(
            chat_id=group_chat_id,
            message_id=msg_id,
            reply_markup=keyboard,
        )
        logger.info(f"[approval_request] 已推送 tool={info.tool_type} msg_id={msg_id}")
    except Exception as e:
        logger.error(f"推送授权请求到 Telegram 失败：{e}")


def _resolve_approval_target(
    state: AppState,
    ws_daemon_id: str,
    thread_id: Optional[str],
) -> tuple[str, Optional[int], Optional[str]]:
    """审批消息必须命中明确 thread topic，否则返回错误原因并交给 owner DM 兜底。"""
    if not thread_id:
        return "", None, "approval missing thread_id"

    found = state.find_thread_by_id_global(thread_id)
    if not found:
        return "", None, f"thread not found: {thread_id}"

    ws_info, thread_info = found
    workspace_id = ws_info.daemon_workspace_id or ws_daemon_id or ""

    if thread_info.archived:
        _repair_local_archived_thread_if_active(state, ws_info, thread_info)
    if thread_info.archived:
        return workspace_id, None, f"thread archived: {thread_id}"

    if thread_info.topic_id is None:
        return workspace_id, None, f"thread topic missing: {thread_id}"

    return workspace_id, thread_info.topic_id, None


async def _notify_owner_about_unroutable_approval(
    state: AppState,
    bot: Bot,
    info: ApprovalInfo,
    *,
    route_error: str,
    ws_daemon_id: str,
) -> None:
    owner_chat_id = state.config.allowed_user_id if state.config else None
    if owner_chat_id is None:
        logger.error(
            "[approval_route] 无法通知 owner：allowed_user_id 缺失 error=%s thread=%s ws=%s",
            route_error,
            info.thread_id or "N/A",
            ws_daemon_id or "N/A",
        )
        return

    lines = [
        "⚠️ 沙盒权限请求无法路由到对应 Thread Topic，已改为仅通知 owner。",
        f"原因：{route_error}",
        f"工具：{info.tool_type}",
    ]
    if info.thread_id:
        lines.append(f"Thread: {info.thread_id}")
    if ws_daemon_id:
        lines.append(f"Workspace: {ws_daemon_id}")
    if info.command:
        lines.append(f"命令：{info.command[:200]}")
    if info.reason:
        lines.append(f"理由：{info.reason[:300]}")

    try:
        await bot.send_message(chat_id=owner_chat_id, text="\n".join(lines))
        logger.info(
            "[approval_route] 已通知 owner chat=%s error=%s thread=%s ws=%s",
            owner_chat_id,
            route_error,
            info.thread_id or "N/A",
            ws_daemon_id or "N/A",
        )
    except Exception as e:
        logger.error(
            "[approval_route] 通知 owner 失败 chat=%s error=%s thread=%s ws=%s send_error=%s",
            owner_chat_id,
            route_error,
            info.thread_id or "N/A",
            ws_daemon_id or "N/A",
            e,
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

    # 策略 1：通过 thread_id 全局查找（跨所有 workspace）
    if thread_id:
        found = state.find_thread_by_id_global(thread_id)
        if found:
            ws, t = found
            if t.archived:
                _repair_local_archived_thread_if_active(state, ws, t)
            if not t.archived:
                thread_found = True
                topic_id = t.topic_id  # 可能为 None（按需创建模式）
                logger.debug(
                    f"[resolve_topic] 全局找到 thread：ws={ws.name} tool={ws.tool} "
                    f"thread={thread_id[:12]}… topic={topic_id}"
                )

    # 策略 2：thread 未知但有 ws_daemon_id，尝试查找 workspace topic
    if not thread_found and ws_daemon_id:
        ws = state.find_workspace_by_daemon_id(ws_daemon_id)
        if ws:
            topic_id = ws.topic_id
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
    if topic_id is None and (thread_id or ws_daemon_id):
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


def make_event_handler(state: AppState, bot: Bot, group_chat_id: int):
    """
    返回 daemon 事件回调。

    路由逻辑：
    1. 从 params 拿 workspace_id
    2. 找对应 workspace（按 daemon_workspace_id）
    3. 从 event_params 拿 threadId
    4. 找对应 thread → 拿 topic_id
    5. 推送到对应 Telegram Topic
    """

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

    async def _handle_approval(ctx: EventContext) -> None:
        """item/commandExecution/requestApproval"""
        approval_params = ctx.event_params
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
            from core.providers.registry import get_provider

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

        command = approval_params.get("command") or ""
        reason = (
            approval_params.get("reason")
            or approval_params.get("justification")
            or ""
        )
        tool_name = str(approval_params.get("toolName") or approval_params.get("tool_name") or "").strip()

        available_decisions = approval_params.get("availableDecisions", [])
        proposed_amendment: list = []
        amendment_decision: dict = {}
        for d in available_decisions:
            if isinstance(d, dict) and "acceptWithExecpolicyAmendment" in d:
                amendment_decision = d
                amend = d["acceptWithExecpolicyAmendment"].get("execpolicy_amendment", [])
                if isinstance(amend, list):
                    proposed_amendment = amend
                break

        always_patterns = approval_params.get("_always_patterns", [])

        info = ApprovalInfo(
            request_id=request_id,
            thread_id=thread_id,
            command=command,
            reason=reason,
            tool_name=tool_name,
            proposed_amendment=proposed_amendment,
            amendment_decision=amendment_decision,
            tool_type=provider_name or "codex",
            always_patterns=always_patterns,
            approval_source="hook_bridge" if approval_params.get("_codex_hook_bridge") else "app_server",
        )

        workspace_id, topic_id, route_error = _resolve_approval_target(
            state,
            ctx.ws_daemon_id,
            thread_id,
        )
        if route_error is not None:
            logger.error(
                "[approval_route] %s tool=%s thread=%s ws=%s",
                route_error,
                info.tool_type,
                thread_id or "N/A",
                ctx.ws_daemon_id or "N/A",
            )
            await _notify_owner_about_unroutable_approval(
                state,
                bot,
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

    async def _handle_question(ctx: EventContext) -> None:
        """question/asked"""
        question_id = ctx.event_params.get("questionId", "")
        header = ctx.event_params.get("header", "")
        question_text = ctx.event_params.get("question", "")
        options = ctx.event_params.get("options", [])
        multiple = ctx.event_params.get("multiple", False)
        custom = ctx.event_params.get("custom", True)
        sub_index = ctx.event_params.get("subIndex", 0)
        sub_total = ctx.event_params.get("subTotal", 1)

        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = ctx.event_params.get("threadId")

        topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)

        # Build display text (plain text, no Markdown — question content is uncontrolled)
        lines = []
        if sub_total > 1:
            lines.append(f"❓ {header} ({sub_index + 1}/{sub_total})" if header else f"❓ Question ({sub_index + 1}/{sub_total})")
        else:
            lines.append(f"❓ {header}" if header else "❓ Question")
        if question_text:
            lines.append(f"\n{question_text}")
        if options:
            lines.append("")
            for i, opt in enumerate(options):
                label = opt.get("label", f"选项 {i + 1}")
                desc = opt.get("description", "")
                if desc:
                    lines.append(f"  {i + 1}. {label} — {desc}")
                else:
                    lines.append(f"  {i + 1}. {label}")
        if multiple:
            lines.append("\n（多选模式，点选后点确认提交）")

        text = "\n".join(lines)

        try:
            sent = await _send_to_group(bot, group_chat_id, text, topic_id=topic_id)
            if sent is None:
                logger.error("推送 question 失败：sent=None")
                return

            msg_id = sent.message_id

            workspace_id = ""
            tool_name = ""
            if thread_id:
                found2 = state.find_thread_by_id_global(thread_id)
                if found2:
                    workspace_id = found2[0].daemon_workspace_id or ""
                    tool_name = found2[0].tool or ""
            if not tool_name and ctx.ws_daemon_id:
                tool_name = state.get_tool_for_workspace(ctx.ws_daemon_id) or ""

            group: PendingQuestionGroup | None = None
            if sub_total > 1:
                if question_id not in state.pending_question_groups:
                    group = PendingQuestionGroup(
                        question_id=question_id,
                        session_id=thread_id or "",
                        workspace_id=workspace_id,
                        total=sub_total,
                    )
                    state.pending_question_groups[question_id] = group
                else:
                    group = state.pending_question_groups[question_id]
                group.msg_ids[sub_index] = msg_id

            cb_ts = int(time.time())

            pq = PendingQuestion(
                question_id=question_id,
                session_id=thread_id or "",
                workspace_id=workspace_id,
                tool_name=tool_name,
                header=header,
                question_text=question_text,
                options=options,
                multiple=multiple,
                custom=custom,
                group=group,
                sub_index=sub_index,
                topic_id=topic_id,
                cb_ts=cb_ts,
            )
            state.pending_questions[msg_id] = pq

            keyboard = build_question_keyboard(msg_id, options, multiple=multiple, custom=custom)
            await bot.edit_message_reply_markup(
                chat_id=group_chat_id,
                message_id=msg_id,
                reply_markup=keyboard,
            )
            logger.info(
                f"[question] 已推送 question={question_id} sub={sub_index + 1}/{sub_total} "
                f"msg_id={msg_id} options={len(options)} multiple={multiple} custom={custom}"
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
        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = ctx.event_params.get("threadId") or ctx.event_params.get("thread_id")
        if not thread_id:
            return

        delta = ctx.event_params.get("delta", "")
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
        if not isinstance(item, dict):
            return
        item_type = item.get("type", "")
        semantic_payload = _codex_semantic_payload(ctx)
        semantic_kind = _codex_semantic_kind(ctx)

        thread_id = ctx.thread_id
        if not thread_id:
            thread_id = (
                ctx.event_params.get("threadId")
                or ctx.event_params.get("thread_id")
                or item.get("threadId")
            )
        event_turn_id = _extract_turn_id(ctx.event_params)

        if item_type == "agentMessage":
            text = str(item.get("text", "")).strip()
            phase = str(item.get("phase", "") or "")
            if semantic_payload:
                text = str(semantic_payload.get("text") or text).strip()
                phase = str(semantic_payload.get("phase") or phase or "")
                if semantic_kind == "assistant_progress" and not phase:
                    phase = "commentary"
                elif semantic_kind == "turn_completed" and not phase:
                    phase = "final_answer"
            if not phase and ctx.event.provider and ctx.event.provider != "codex":
                # Some provider event streams omit phase; their completed agentMessage
                # is treated as the user-visible final assistant reply.
                phase = "final_answer"
            if not text or not thread_id:
                return

            st = state.streaming_turns.get(thread_id)
            ws = _resolve_workspace_info(state, ctx.ws_daemon_id, thread_id)
            topic_id = _resolve_topic_id(state, ctx.ws_daemon_id, thread_id, ctx.event_params)
            prefix = "🤖" if phase == "final_answer" else "💭"
            delivered_to_tg = False

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
                if phase == "final_answer":
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
                    if phase == "final_answer":
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
            return

        if item_type == "shellCommand":
            # 只记录日志，不推送到 TG（工具调用结果不属于文字类消息）
            cmd = item.get("command", "")
            logger.debug(f"[item/completed] shellCommand 忽略推送 thread={thread_id[:8] if thread_id else '?'} cmd={cmd[:60]}")

    async def _handle_turn_completed(ctx: EventContext) -> None:
        """turn/completed / turn_aborted"""
        turn = ctx.event_params.get("turn", {})
        semantic_payload = _codex_semantic_payload(ctx)
        semantic_kind = _codex_semantic_kind(ctx)
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

        status = ""
        if isinstance(turn, dict):
            status = turn.get("status", "")
        if not status:
            status = ctx.event_params.get("status", "")
        if not status and semantic_kind == "turn_aborted":
            status = "aborted"
        if not status and ctx.event.kind == "turn_aborted":
            status = "aborted"

        st = state.streaming_turns.get(thread_id)
        event_turn_id = _extract_turn_id(ctx.event_params)
        run_status = status or "completed"
        if st is not None:
            if st.completed:
                logger.debug(f"[streaming] turn/completed 已由 final item 收口 thread={thread_id[:8]}")
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
                reason = ""
                if isinstance(turn, dict):
                    reason = str(turn.get("reason") or "")
                if not reason:
                    reason = str(ctx.event_params.get("reason") or "")
                if not reason:
                    reason = str(semantic_payload.get("reason") or "")
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
                streamed_reply_text = _normalize_streamed_reply_for_sync(st.buffer)
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

        tool_name = ws_info.tool or "provider"
        prefix = f"[{tool_name}/{ws_info.name}] "
        body = title.strip().replace("\n", " ") if title else f"thread-{thread_id[-8:]}"
        topic_name = (prefix + body)[:128]

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
        title = ctx.event_params.get("title", "")
        if not thread_id or not title:
            return

        found = state.find_thread_by_id_global(thread_id)
        if not found:
            logger.debug(f"[title_update] thread {thread_id[:8]}… 未注册，跳过")
            return

        ws_info, thread_info = found
        if not thread_info.topic_id:
            return

        tool_name = ws_info.tool or "provider"
        prefix = f"[{tool_name}/{ws_info.name}] "
        new_topic_name = (prefix + title.strip().replace("\n", " "))[:128]

        try:
            await bot.edit_forum_topic(
                chat_id=group_chat_id,
                message_thread_id=thread_info.topic_id,
                name=new_topic_name,
            )
            thread_info.preview = title
            if state.storage:
                save_storage(state.storage)
            logger.info(f"[title_update] Topic {thread_info.topic_id} renamed → {new_topic_name}")
        except Exception as e:
            logger.warning(f"[title_update] rename Topic {thread_info.topic_id} 失败：{e}")

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

        msg = params.get("message", {})
        thread_id = event.thread_id
        ws_daemon_id = event.workspace_id

        logger.debug(
            f"[event] {event.raw_method} kind={event.kind} semantic={event.semantic_kind or '-'} "
            f"ws={ws_daemon_id[:8] if ws_daemon_id else '?'} "
            f"thread={thread_id[:8] if thread_id else '?'}"
        )

        ctx = EventContext(
            event=event,
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
        item/commandExecution/requestApproval → 推送沙盒权限授权请求
    """
    async def on_server_request(method: str, params: dict, request_id: int) -> None:
        if method != "item/commandExecution/requestApproval":
            logger.debug(f"[server_request] 忽略未处理的 method={method}")
            return

        thread_id: Optional[str] = params.get("threadId")
        command = params.get("command") or ""
        reason = params.get("reason") or ""
        available_decisions = params.get("availableDecisions", [])

        proposed_amendment: list = []
        amendment_decision: dict = {}
        for d in available_decisions:
            if isinstance(d, dict) and "acceptWithExecpolicyAmendment" in d:
                amendment_decision = d
                amend = d["acceptWithExecpolicyAmendment"].get("execpolicy_amendment", [])
                if isinstance(amend, list):
                    proposed_amendment = amend
                break

        if not proposed_amendment:
            proposed_amendment = params.get("proposedExecpolicyAmendment") or []

        info = ApprovalInfo(
            request_id=request_id,
            thread_id=thread_id,
            command=command,
            reason=reason,
            tool_name="",
            proposed_amendment=proposed_amendment if isinstance(proposed_amendment, list) else [],
            amendment_decision=amendment_decision,
            tool_type="codex",
            always_patterns=[],
        )

        workspace_id, topic_id, route_error = _resolve_approval_target(
            state,
            "",
            thread_id,
        )
        if route_error is not None:
            logger.error(
                "[approval_route] %s tool=codex thread=%s ws=%s",
                route_error,
                thread_id or "N/A",
                workspace_id or "N/A",
            )
            await _notify_owner_about_unroutable_approval(
                state,
                bot,
                info,
                route_error=route_error,
                ws_daemon_id=workspace_id,
            )
            return

        logger.info(
            f"[approval_request] id={request_id} thread={thread_id[:8] if thread_id else '?'} "
            f"cmd={command[:60]} topic={topic_id}"
        )
        await send_approval_to_telegram(
            state, bot, group_chat_id, topic_id, workspace_id, info,
        )

    return on_server_request
