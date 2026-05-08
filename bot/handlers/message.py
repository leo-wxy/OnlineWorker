# bot/handlers/message.py
"""
消息路由：按 message_thread_id 判断属于哪一层 Topic，分层处理。

三层结构：
  全局 Topic（provider 控制台）
    → 普通文本：提示发 /workspace
    → slash 命令由统一 slash router 处理

  workspace Topic（[provider] workspace）
    → 普通文本：提示用 /new

  thread Topic（[provider/workspace] ...）
    → 文本默认发给底层工具
    → onlineWorker 控制：通过本地线程命令或 thread 控制卡片触发
"""
import logging
from typing import Callable, Optional
from plugins.providers.builtin.codex.python.tui_bridge import (
    enqueue_codex_tui_message,
    is_codex_local_owner_mode,
)
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.providers.registry import classify_provider, get_provider, provider_not_enabled_message
from telegram import Update
from telegram.ext import ContextTypes
from bot.interaction_specs import (
    CommandWrapperDispatchRequest,
    apply_command_wrapper_selection,
    consume_command_wrapper_text_input,
    refresh_command_wrapper,
)
from core.state import AppState, PendingCommandWrapper
from core.storage import save_storage, ThreadInfo
from bot.keyboards import (
    build_command_wrapper_keyboard,
    parse_approval_callback,
    parse_command_wrapper_callback,
    parse_question_callback,
)
from bot.handlers.common import (
    clear_stale_thread_archive_if_active,
    _send_to_group,
    tg_send_failed_text,
)
from bot.handlers.thread import handle_thread_control_callback

logger = logging.getLogger(__name__)


def _provider_unavailable_message(state: AppState, tool_name: str) -> str | None:
    if state.config is None:
        return None
    classification = classify_provider(tool_name, state.config)
    if classification == "unknown_provider" and get_provider(tool_name) is not None:
        return None
    if classification in {"available", "hidden_provider"}:
        return None
    return provider_not_enabled_message(tool_name, classification)


def _preview_for_message(text: str | None, caption: str | None, has_photo: bool) -> str | None:
    if text and text.strip():
        return text.strip()[:80]
    if caption and caption.strip():
        return caption.strip()[:80]
    if has_photo:
        return "[图片]"
    return None


def _resolve_question_runtime(state: AppState, pending_question) -> tuple[str, object | None, object | None]:
    tool_name = (
        getattr(pending_question, "tool_name", "") or
        state.get_tool_for_workspace(getattr(pending_question, "workspace_id", "")) or
        ""
    )
    if tool_name and _provider_unavailable_message(state, tool_name):
        return tool_name, None, None
    adapter = state.get_adapter(tool_name) if tool_name else None
    if adapter is None and getattr(pending_question, "workspace_id", ""):
        adapter = state.get_adapter_for_workspace(pending_question.workspace_id)
    provider = get_provider(tool_name) if tool_name else None
    interactions = getattr(provider, "interactions", None) if provider is not None else None
    reply_question = getattr(interactions, "reply_question", None)
    if tool_name and adapter is not None and callable(reply_question):
        return tool_name, adapter, reply_question

    adapter_reply_question = getattr(adapter, "reply_question", None) if adapter is not None else None
    if adapter is not None and callable(adapter_reply_question):
        async def _reply_question(adapter_obj, pending_question_obj, answers):
            await adapter_obj.reply_question(pending_question_obj.question_id, answers)

        return tool_name, adapter, _reply_question

    candidates: list[tuple[str, object, object]] = []
    for name, candidate_adapter in state.iter_adapters():
        candidate_provider = get_provider(name)
        candidate_interactions = (
            getattr(candidate_provider, "interactions", None)
            if candidate_provider is not None
            else None
        )
        candidate_reply = getattr(candidate_interactions, "reply_question", None)
        if candidate_adapter is not None and callable(candidate_reply):
            candidates.append((name, candidate_adapter, candidate_reply))
        elif candidate_adapter is not None and callable(getattr(candidate_adapter, "reply_question", None)):
            async def _reply_question(adapter_obj, pending_question_obj, answers):
                await adapter_obj.reply_question(pending_question_obj.question_id, answers)

            candidates.append((name, candidate_adapter, _reply_question))
    if len(candidates) == 1:
        return candidates[0]
    return tool_name, adapter, reply_question


async def _reply_pending_question(state: AppState, pending_question, answers: list[list[str]]) -> None:
    tool_name, adapter, reply_question = _resolve_question_runtime(state, pending_question)
    label = tool_name or "当前 provider"
    if tool_name:
        unavailable = _provider_unavailable_message(state, tool_name)
        if unavailable:
            raise RuntimeError(unavailable)

    if adapter is None or not getattr(adapter, "connected", False):
        raise RuntimeError(f"{label} 未连接，无法回复。")
    if not callable(reply_question):
        raise RuntimeError(f"{label} 未注册问题回复能力。")

    await reply_question(adapter, pending_question, answers)


async def _dispatch_thread_message(
    state: AppState,
    ws_info,
    thread_info,
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    group_chat_id: int,
    src_topic_id: int | None,
    text: str | None,
    has_photo: bool,
    caption: str | None = None,
) -> None:
    unavailable = _provider_unavailable_message(state, ws_info.tool)
    if unavailable:
        raise RuntimeError(unavailable)

    adapter = state.get_adapter(ws_info.tool)
    provider = get_provider(ws_info.tool, state.config)
    message_hooks = provider.message_hooks if provider is not None else None
    original_thread_id = thread_info.thread_id
    original_preview = thread_info.preview
    original_topic_id = thread_info.topic_id
    original_source = str(getattr(thread_info, "source", "") or "unknown")
    original_is_active = bool(getattr(thread_info, "is_active", False))
    original_history_sync_cursor = getattr(thread_info, "history_sync_cursor", None)
    original_streaming_msg_id = getattr(thread_info, "streaming_msg_id", None)
    original_last_tg_user_message_id = getattr(thread_info, "last_tg_user_message_id", None)

    if has_photo and not (message_hooks and message_hooks.supports_photo):
        raise RuntimeError(f"当前 {ws_info.tool} thread 不支持图片消息。")
    if thread_info.archived and clear_stale_thread_archive_if_active(state, ws_info, thread_info):
        if state.storage is not None:
            save_storage(state.storage)
    if thread_info.archived:
        raise RuntimeError("该 thread 已归档，无法发送消息。")

    workspace_id = ws_info.daemon_workspace_id
    if not workspace_id:
        raise RuntimeError("workspace 未关联 daemon ID。")

    handle_local_owner = (
        getattr(message_hooks, "handle_local_owner", None)
        if message_hooks is not None
        else None
    )
    if callable(handle_local_owner):
        handled = await handle_local_owner(
            state,
            adapter,
            ws_info,
            thread_info,
            update=update,
            context=context,
            group_chat_id=group_chat_id,
            src_topic_id=src_topic_id,
            text=text,
            has_photo=has_photo,
        )
        if handled:
            return

    if message_hooks is not None:
        adapter = await message_hooks.ensure_connected(
            state,
            adapter,
            ws_info,
            update=update,
            context=context,
            group_chat_id=group_chat_id,
            src_topic_id=src_topic_id,
        )

    if adapter is None or not adapter.connected:
        raise RuntimeError(f"{ws_info.tool} 未连接")

    should_continue = True
    try:
        if message_hooks is not None:
            should_continue = await message_hooks.prepare_send(
                state,
                adapter,
                ws_info,
                thread_info,
                update=update,
                context=context,
                group_chat_id=group_chat_id,
                src_topic_id=src_topic_id,
                text=text,
                has_photo=has_photo,
            )
        else:
            await adapter.resume_thread(workspace_id, thread_info.thread_id)

        if not should_continue:
            return

        if message_hooks is not None:
            await message_hooks.send(
                state,
                adapter,
                ws_info,
                thread_info,
                update=update,
                context=context,
                group_chat_id=group_chat_id,
                src_topic_id=src_topic_id,
                text=text,
                has_photo=has_photo,
            )
        else:
            await adapter.send_user_message(workspace_id, thread_info.thread_id, text)
    except Exception:
        if thread_info.thread_id != original_thread_id:
            ws_info.threads.pop(thread_info.thread_id, None)
            thread_info.thread_id = original_thread_id
            thread_info.topic_id = original_topic_id
            thread_info.preview = original_preview
            thread_info.source = original_source
            thread_info.is_active = original_is_active
            thread_info.history_sync_cursor = original_history_sync_cursor
            thread_info.streaming_msg_id = original_streaming_msg_id
            thread_info.last_tg_user_message_id = original_last_tg_user_message_id
            ws_info.threads[original_thread_id] = thread_info
        raise

    remapped = thread_info.thread_id != original_thread_id
    source_changed = str(getattr(thread_info, "source", "") or "unknown") != original_source
    preview_value = _preview_for_message(text, caption, has_photo)
    preview_changed = False
    if (remapped or not thread_info.preview) and preview_value and preview_value != thread_info.preview:
        thread_info.preview = preview_value
        preview_changed = True

    message = update.effective_message
    tg_message_id = int(getattr(message, "message_id", 0) or 0)
    reply_anchor_changed = False
    if tg_message_id > 0:
        if getattr(thread_info, "last_tg_user_message_id", None) != tg_message_id:
            thread_info.last_tg_user_message_id = tg_message_id
            reply_anchor_changed = True
        if original_thread_id and original_thread_id != thread_info.thread_id:
            state.thread_last_tg_user_message_ids.pop(original_thread_id, None)
        state.thread_last_tg_user_message_ids[thread_info.thread_id] = tg_message_id

    if remapped or source_changed or preview_changed or reply_anchor_changed:
        if state.storage is None:
            logger.warning("storage 为 None，跳过保存（发送后 thread 元数据更新）")
        else:
            save_storage(state.storage)

    logger.info(f"[TG] 消息已发送到 thread {thread_info.thread_id[:8]}…")


def _build_provider_approval_reply(approval, action: str) -> tuple[str, dict]:
    tool_name = getattr(approval, "tool_type", "") or ""
    provider = get_provider(tool_name) if tool_name else None
    interactions = getattr(provider, "interactions", None) if provider is not None else None
    build_reply = getattr(interactions, "build_approval_reply", None)
    if callable(build_reply):
        return build_reply(approval, action)

    if action == "exec_deny":
        return "❌ 已拒绝", {"decision": "decline"}
    if action == "exec_allow_always":
        return "✅ 已总是允许", {"decision": "acceptForSession"}
    return "✅ 已允许", {"decision": "accept"}


def _build_codex_hook_approval_reply(action: str) -> tuple[str, dict]:
    if action == "exec_deny":
        return "❌ 已拒绝", {"behavior": "deny"}
    if action == "exec_allow_always":
        return "✅ 已总是允许", {"behavior": "allow", "scope": "session"}
    return "✅ 已允许", {"behavior": "allow"}


async def _safe_answer_callback(
    query,
    *,
    context: str,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    """尽量 answer callback，但失败时不阻断真正的业务处理。"""
    try:
        if text is None:
            await query.answer()  # type: ignore[union-attr]
        else:
            await query.answer(text, show_alert=show_alert)  # type: ignore[union-attr]
    except Exception as e:
        logger.warning(
            f"[callback] answer 失败 context={context} "
            f"data={getattr(query, 'data', None)!r} error={e}"
        )


def make_message_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    收到用户文本或图片消息，按所在 Topic 层级路由处理。
    """
    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None:
            return
        text = msg.text
        raw_photos = getattr(msg, "photo", None)
        has_photo = isinstance(raw_photos, (list, tuple)) and len(raw_photos) > 0
        if not text and not has_photo:
            return

        src_topic_id: Optional[int] = msg.message_thread_id
        
        # 添加调试日志
        if has_photo:
            logger.info(
                f"[message_handler] 收到图片消息：topic_id={src_topic_id} "
                f"caption={(msg.caption or '')[:50]!r}… "
                f"from={update.effective_user.id if update.effective_user else 'None'}"
            )
        else:
            logger.info(
                f"[message_handler] 收到消息：topic_id={src_topic_id} "
                f"text={text[:50]!r}… from={update.effective_user.id if update.effective_user else 'None'}"
            )

        # ── 层级判断 ──────────────────────────────────────────────────────

        # 1. 全局 Topic（provider 控制台）
        if state.is_global_topic(src_topic_id):
            await _send_to_group(
                context.bot, group_chat_id,
                "发送 /workspace 查看和打开 workspace。",
                topic_id=src_topic_id,
            )
            return

        # 2. workspace Topic
        ws = state.find_workspace_by_topic_id(src_topic_id) if src_topic_id else None
        if ws is not None:
            await _send_to_group(
                context.bot, group_chat_id,
                f"当前在 workspace `{ws.name}` 控制台。\n"
                f"• /new — 开启新 thread\n"
                f"• /list — 查看已有 thread",
                topic_id=src_topic_id,
                parse_mode="Markdown",
            )
            return

        # 3. thread Topic — 查找所属 workspace 和对应 adapter
        found = state.find_thread_by_topic_id(src_topic_id) if src_topic_id else None

        if found is not None:
            ws_info, thread_info = found

            # ── 先检查是否有 awaiting_text 的 question（自定义输入模式）──
            if src_topic_id is not None:
                awaiting = state.find_awaiting_text_question(src_topic_id)
                if awaiting is not None:
                    if has_photo or not text or not text.strip():
                        await _send_to_group(
                            context.bot, group_chat_id,
                            "当前问题正在等待文字输入，请直接发送文本回复。",
                            topic_id=src_topic_id,
                        )
                        return

                    a_msg_id, pq = awaiting
                    pq.awaiting_text = False  # 消费掉

                    tool_name, question_adapter, reply_question = _resolve_question_runtime(state, pq)
                    if question_adapter is None or not getattr(question_adapter, "connected", False):
                        await _send_to_group(
                            context.bot, group_chat_id,
                            f"❌ {(tool_name or '当前 provider')} 未连接，无法回复。",
                            topic_id=src_topic_id,
                        )
                        return
                    if not callable(reply_question):
                        await _send_to_group(
                            context.bot, group_chat_id,
                            f"❌ {(tool_name or '当前 provider')} 未注册问题回复能力。",
                            topic_id=src_topic_id,
                        )
                        return

                    answer = [text.strip()]
                    display = f"✅ 自定义输入：*{text.strip()[:100]}*"

                    # 编辑原 question 消息
                    try:
                        await context.bot.edit_message_text(
                            chat_id=group_chat_id,
                            message_id=a_msg_id,
                            text=f"{display}\n\n问题：{pq.header or pq.question_text[:100]}",
                            parse_mode="Markdown",
                        )
                    except Exception as e:
                        logger.debug(f"[custom_input] edit 消息失败: {e}")

                    # 提交答案
                    pq.answer = answer
                    if pq.group is not None:
                        pq.group.answers[pq.sub_index] = answer
                        state.pending_questions.pop(a_msg_id, None)

                        if pq.group.all_answered:
                            all_answers = pq.group.collect_answers()
                            try:
                                await _reply_pending_question(state, pq, all_answers)
                                logger.info(f"[question] custom input 完成，全部 sub 已提交 question={pq.group.question_id}")
                            except Exception as e:
                                logger.error(f"回复 question group 失败：{e}")
                            state.pending_question_groups.pop(pq.group.question_id, None)
                        else:
                            remaining = pq.group.total - len(pq.group.answers)
                            logger.info(f"[question] custom input sub {pq.sub_index + 1}/{pq.group.total}，剩余 {remaining}")
                    else:
                        state.pending_questions.pop(a_msg_id, None)
                        try:
                            await _reply_pending_question(state, pq, [answer])
                            logger.info(f"[question] 自定义输入已提交 question={pq.question_id} answer={text.strip()[:50]}")
                        except Exception as e:
                            logger.error(f"回复 question 失败：{e}")
                            await _send_to_group(
                                context.bot, group_chat_id,
                                f"❌ 回复失败：{e}",
                                topic_id=src_topic_id,
                            )
                    return

                awaiting_wrapper = state.find_awaiting_text_command_wrapper(src_topic_id)
                if awaiting_wrapper is not None:
                    if has_photo or not text or not text.strip():
                        await _send_to_group(
                            context.bot,
                            group_chat_id,
                            "当前命令正在等待文字参数，请直接发送文本。",
                            topic_id=src_topic_id,
                        )
                        return

                    wrapper_id, pending = awaiting_wrapper
                    try:
                        updated = consume_command_wrapper_text_input(pending, text)
                    except Exception as e:
                        await _send_to_group(
                            context.bot,
                            group_chat_id,
                            f"❌ 参数处理失败：{e}",
                            topic_id=src_topic_id,
                        )
                        return

                    state.pending_command_wrappers[wrapper_id] = updated
                    try:
                        panel_message_id = int(updated.panel_message_id or 0)
                        if panel_message_id > 0:
                            await context.bot.edit_message_text(
                                chat_id=group_chat_id,
                                message_id=panel_message_id,
                                text=updated.prompt_text,
                                parse_mode="Markdown",
                                reply_markup=build_command_wrapper_keyboard(wrapper_id, updated.options),
                            )
                        else:
                            panel_message = await _send_to_group(
                                context.bot,
                                group_chat_id,
                                updated.prompt_text,
                                topic_id=src_topic_id,
                                parse_mode="Markdown",
                                reply_markup=build_command_wrapper_keyboard(wrapper_id, updated.options),
                            )
                            updated.panel_message_id = int(getattr(panel_message, "message_id", 0) or 0)
                    except Exception as e:
                        logger.debug(f"[command_wrapper] 更新参数面板失败: {e}")
                    return

            try:
                await _dispatch_thread_message(
                    state,
                    ws_info,
                    thread_info,
                    update=update,
                    context=context,
                    group_chat_id=group_chat_id,
                    src_topic_id=src_topic_id,
                    text=text,
                    has_photo=has_photo,
                    caption=msg.caption,
                )
            except Exception as e:
                logger.error(f"发送消息失败：{e}")
                await _send_to_group(
                    context.bot, group_chat_id,
                    tg_send_failed_text(e),
                    topic_id=src_topic_id,
                )
            return

        # 未知 Topic，忽略
        logger.debug(f"未知 topic_id={src_topic_id}，忽略消息")

    return handle_message


def make_callback_handler(state: AppState, group_chat_id: int) -> Callable:

    async def _submit_question_answer(
        state: AppState,
        pq,
        msg_id: int,
        answer: list[str],
        query,
        display: str,
    ) -> None:
        """
        提交单个 sub-question 的答案。

        如果是多 sub-question group，等所有都回答完再一次性调用 reply_question。
        单独的 question（无 group）直接提交。
        """
        from core.state import PendingQuestionGroup

        pq.answer = answer

        if pq.group is not None:
            # 多 sub-question：记录答案到 group
            group: PendingQuestionGroup = pq.group
            group.answers[pq.sub_index] = answer

            # 更新此 sub-question 的消息显示
            try:
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"{display}\n\n问题：{pq.header or pq.question_text[:100]}",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.debug(f"[question] edit sub msg 失败: {e}")

            # 从 pending 移除此 sub
            state.pending_questions.pop(msg_id, None)

            if not group.all_answered:
                # 还有未回答的 sub-question
                remaining = group.total - len(group.answers)
                logger.info(
                    f"[question] sub {pq.sub_index + 1}/{group.total} 已回答，"
                    f"剩余 {remaining} 个"
                )
                return

            # 全部回答完毕，合并提交
            all_answers = group.collect_answers()
            try:
                await _reply_pending_question(state, pq, all_answers)
                logger.info(
                    f"[question] 全部 {group.total} 个 sub-question 已回答，"
                    f"已提交 question={group.question_id}"
                )
            except Exception as e:
                logger.error(f"回复 question group 失败：{e}")

            # 清理 group
            state.pending_question_groups.pop(group.question_id, None)
        else:
            # 单独 question，直接提交
            state.pending_questions.pop(msg_id, None)
            try:
                await _reply_pending_question(state, pq, [answer])
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"{display}\n\n问题：{pq.header or pq.question_text[:100]}",
                    parse_mode="Markdown",
                )
                logger.info(
                    f"[question] 已回复 question={pq.question_id} "
                    f"answer={answer}"
                )
            except Exception as e:
                logger.error(f"回复 question 失败：{e}")
                await query.edit_message_text(f"❌ 回复失败：{e}")  # type: ignore[union-attr]

    async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        data = query.data  # type: ignore[union-attr]
        action, _, remainder = data.partition(":")  # type: ignore[union-attr]
        logger.info(f"[callback] 收到 callback data={data!r}")
        await _safe_answer_callback(query, context="initial")

        # ── exec_approval 系列 ────────────────────────────────────────────
        if action in ("exec_allow", "exec_deny", "exec_allow_always"):
            action, msg_id, expired = parse_approval_callback(data)

            if expired:
                logger.warning(f"[approval] callback 已过期 action={action} msg_id={msg_id}")
                try:
                    await query.edit_message_reply_markup(reply_markup=None)  # type: ignore[union-attr]
                except Exception as e:
                    logger.warning(f"[callback] 清除过期授权按钮失败：{e}")
                await _safe_answer_callback(
                    query,
                    context="approval-expired",
                    text="此授权请求已过期，请重新触发。",
                    show_alert=True,
                )
                return

            approval = state.pending_approvals.get(msg_id)
            if approval is None:
                logger.warning(f"[approval] 未找到 pending approval msg_id={msg_id} action={action}")
                await query.edit_message_text("⚠️ 此授权请求已失效或已处理。")  # type: ignore[union-attr]
                return

            approval_source = str(getattr(approval, "approval_source", "") or "app_server")
            if approval_source == "hook_bridge":
                label, reply_body = _build_codex_hook_approval_reply(action)
                if getattr(approval, "tool_name", ""):
                    reply_body["tool_name"] = approval.tool_name
            else:
                label, reply_body = _build_provider_approval_reply(approval, action)

            try:
                if getattr(approval, "approval_source", "") == "hook_bridge":
                    bridge = codex_state.get_hook_bridge(state)
                    if bridge is None or not getattr(bridge, "is_running", False):
                        raise RuntimeError("Codex hook bridge 未运行，无法回复授权。")
                    await bridge.reply_server_request(approval.request_id, reply_body)
                else:
                    tool_name = approval.tool_type or state.get_tool_for_workspace(approval.workspace_id) or ""
                    unavailable = _provider_unavailable_message(state, tool_name) if tool_name else None
                    if unavailable:
                        await query.edit_message_text(f"❌ 回复授权失败：{unavailable}")  # type: ignore[union-attr]
                        return
                    active_adapter = state.get_adapter(tool_name) if tool_name else None
                    if active_adapter is None:
                        active_adapter = state.get_adapter_for_workspace(approval.workspace_id)
                    if not active_adapter or not active_adapter.connected:
                        logger.warning(
                            f"[approval] adapter 未连接 action={action} msg_id={msg_id} "
                            f"tool={tool_name or approval.tool_type or '?'} ws={approval.workspace_id}"
                        )
                        await query.edit_message_text("❌ 未连接，无法回复授权。")  # type: ignore[union-attr]
                        return
                    await active_adapter.reply_server_request(
                        approval.workspace_id,
                        approval.request_id,
                        reply_body,
                    )
                if approval.tool_type == "codex" or codex_state.has_interruption(state, approval.request_id):
                    codex_state.resolve_interruption(
                        state,
                        approval.request_id,
                        status="resolved",
                        tg_message_id=msg_id,
                    )
                state.pending_approvals.pop(msg_id, None)
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"{label}\n\n命令：`{approval.cmd[:200]}`",
                    parse_mode="Markdown",
                )
                logger.info(f"[approval] request_id={approval.request_id} tool={approval.tool_type} reply={reply_body}")
            except Exception as e:
                logger.error(f"回复授权失败：{e}")
                await query.edit_message_text(f"❌ 回复授权失败：{e}")  # type: ignore[union-attr]
            return

        # ── question 选项回调（q_ans / q_tog / q_sub / q_cus） ──────────
        if action in ("q_ans", "q_tog", "q_sub", "q_cus"):
            act, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)

            if expired:
                try:
                    await query.edit_message_reply_markup(reply_markup=None)  # type: ignore[union-attr]
                except Exception as e:
                    logger.warning(f"[callback] 清除过期问题按钮失败：{e}")
                await _safe_answer_callback(
                    query,
                    context="question-expired",
                    text="此提问已过期。",
                    show_alert=True,
                )
                return

            pq = state.pending_questions.get(msg_id)
            if pq is None:
                await query.edit_message_text("⚠️ 此提问已失效或已回答。")  # type: ignore[union-attr]
                return

            tool_name, question_adapter, reply_question = _resolve_question_runtime(state, pq)
            if question_adapter is None or not getattr(question_adapter, "connected", False):
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"❌ {(tool_name or '当前 provider')} 未连接，无法回复。"
                )
                return
            if not callable(reply_question):
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"❌ {(tool_name or '当前 provider')} 未注册问题回复能力。"
                )
                return

            # ── q_ans: 单选直接提交 ──────────────────────────────────────
            if act == "q_ans":
                if option_idx < 0 or option_idx >= len(pq.options):
                    await query.edit_message_text("⚠️ 选项索引无效。")  # type: ignore[union-attr]
                    return

                selected_label = pq.options[option_idx].get("label", f"选项 {option_idx + 1}")
                answer = [selected_label]
                await _submit_question_answer(
                    state, pq, msg_id, answer, query,
                    display=f"✅ 已选择：*{selected_label}*",
                )
                return

            # ── q_tog: 多选 toggle ───────────────────────────────────────
            if act == "q_tog":
                if option_idx < 0 or option_idx >= len(pq.options):
                    await _safe_answer_callback(
                        query,
                        context="question-toggle-invalid-index",
                        text="选项索引无效。",
                        show_alert=True,
                    )
                    return

                # toggle 选中状态
                if option_idx in pq.selected:
                    pq.selected.discard(option_idx)
                else:
                    pq.selected.add(option_idx)

                # 重建 keyboard（更新选中状态）
                from bot.keyboards import build_question_keyboard
                keyboard = build_question_keyboard(
                    msg_id, pq.options,
                    multiple=True,
                    custom=pq.custom,
                    selected=pq.selected,
                )
                try:
                    await query.edit_message_reply_markup(reply_markup=keyboard)  # type: ignore[union-attr]
                except Exception as e:
                    logger.debug(f"[q_tog] edit keyboard 失败: {e}")

                selected_labels = [pq.options[i].get("label", "?") for i in sorted(pq.selected)]
                await _safe_answer_callback(
                    query,
                    context="question-toggle-selected",
                    text=f"已选：{', '.join(selected_labels) if selected_labels else '（无）'}",
                )
                return

            # ── q_sub: 多选确认提交 ──────────────────────────────────────
            if act == "q_sub":
                if not pq.selected:
                    await _safe_answer_callback(
                        query,
                        context="question-submit-empty",
                        text="请至少选择一个选项。",
                        show_alert=True,
                    )
                    return

                selected_labels = [pq.options[i].get("label", f"选项 {i + 1}") for i in sorted(pq.selected)]
                await _submit_question_answer(
                    state, pq, msg_id, selected_labels, query,
                    display=f"✅ 已选择：*{', '.join(selected_labels)}*",
                )
                return

            # ── q_cus: 自定义输入 ────────────────────────────────────────
            if act == "q_cus":
                pq.awaiting_text = True
                # 移除按钮，提示用户输入
                try:
                    await query.edit_message_text(  # type: ignore[union-attr]
                        f"❓ **{pq.header or 'Question'}**\n\n"
                        f"{pq.question_text}\n\n"
                        f"✍️ _请在此 Topic 中直接回复你的答案：_",
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"[q_cus] edit 消息失败: {e}")
                await _safe_answer_callback(
                    query,
                    context="question-custom-input",
                    text="请输入自定义答案",
                )
                return

            return

        if action in ("cmdw_sel", "cmdw_ref", "cmdw_can"):
            act, wrapper_id, cb_ts, option_idx, expired = parse_command_wrapper_callback(data)

            if expired:
                state.pending_command_wrappers.pop(wrapper_id, None)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)  # type: ignore[union-attr]
                except Exception as e:
                    logger.warning(f"[callback] 清除过期命令面板按钮失败：{e}")
                await _safe_answer_callback(
                    query,
                    context="command-wrapper-expired",
                    text="此命令面板已过期，请重新发送命令。",
                    show_alert=True,
                )
                return

            pending = state.pending_command_wrappers.get(wrapper_id)
            if pending is None:
                await query.edit_message_text("⚠️ 此命令面板已失效。")  # type: ignore[union-attr]
                return

            if act == "cmdw_can":
                state.pending_command_wrappers.pop(wrapper_id, None)
                await query.edit_message_text(  # type: ignore[union-attr]
                    f"已关闭 `/{pending.command_name}` 面板。",
                    parse_mode="Markdown",
                )
                return

            if act == "cmdw_ref":
                try:
                    refreshed = await refresh_command_wrapper(state, pending)
                except Exception as e:
                    await _safe_answer_callback(
                        query,
                        context="command-wrapper-refresh-error",
                        text=str(e),
                        show_alert=True,
                    )
                    return

                state.pending_command_wrappers[wrapper_id] = refreshed
                await query.edit_message_text(  # type: ignore[union-attr]
                    refreshed.prompt_text,
                    parse_mode="Markdown",
                    reply_markup=build_command_wrapper_keyboard(wrapper_id, refreshed.options),
                )
                return

            try:
                result_text = await apply_command_wrapper_selection(state, pending, option_idx)
            except Exception as e:
                await _safe_answer_callback(
                    query,
                    context="command-wrapper-selection-error",
                    text=str(e),
                    show_alert=True,
                )
                return

            if isinstance(result_text, PendingCommandWrapper):
                state.pending_command_wrappers[wrapper_id] = result_text
                await query.edit_message_text(  # type: ignore[union-attr]
                    result_text.prompt_text,
                    parse_mode="Markdown",
                    reply_markup=build_command_wrapper_keyboard(wrapper_id, result_text.options),
                )
                return

            if isinstance(result_text, CommandWrapperDispatchRequest):
                found = state.find_thread_by_id_global(pending.thread_id)
                if found is None:
                    await _safe_answer_callback(
                        query,
                        context="command-wrapper-thread-missing",
                        text="当前 thread 已不存在。",
                        show_alert=True,
                    )
                    return

                ws_info, thread_info = found
                try:
                    await _dispatch_thread_message(
                        state,
                        ws_info,
                        thread_info,
                        update=update,
                        context=context,
                        group_chat_id=group_chat_id,
                        src_topic_id=getattr(getattr(query, "message", None), "message_thread_id", None),
                        text=result_text.command_text,
                        has_photo=False,
                    )
                except Exception as e:
                    await _safe_answer_callback(
                        query,
                        context="command-wrapper-dispatch-error",
                        text=str(e),
                        show_alert=True,
                    )
                    return

                state.pending_command_wrappers.pop(wrapper_id, None)
                await query.edit_message_text(result_text.completion_text)  # type: ignore[union-attr]
                return

            state.pending_command_wrappers.pop(wrapper_id, None)
            await query.edit_message_text(result_text)  # type: ignore[union-attr]
            return

        if action == "threadctl":
            if await handle_thread_control_callback(
                state,
                context.bot,
                group_chat_id,
                query,
                remainder,
            ):
                return

        # ── 普通 confirm/cancel ───────────────────────────────────────────
        msg_id_str = remainder  # "confirm:123" → remainder = "123"
        pending = state.pending_confirmation
        if pending is None or str(pending.message_id) != msg_id_str:
            await query.edit_message_text("⚠️ 此确认请求已失效。")  # type: ignore[union-attr]
            return

        state.clear_pending()

        if action == "confirm":
            await query.edit_message_text(  # type: ignore[union-attr]
                f"✅ 已确认，内容：\n\n{pending.original_text}"
            )
        elif action == "cancel":
            await query.edit_message_text("❌ 已取消。")  # type: ignore[union-attr]
        else:
            await query.edit_message_text("⚠️ 未知操作。")  # type: ignore[union-attr]

    return handle_callback
