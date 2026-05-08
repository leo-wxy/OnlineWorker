# bot/handlers/thread.py
"""
/new  — 在当前 workspace 下新建 codex thread，并创建对应 Telegram Topic
/list — 列出当前 workspace 的 thread
/archive — 归档指定（或当前）thread：关闭 Telegram Topic，标记 archived=True

thread Topic 内的原始 `/xxx` 默认透传给底层工具；onlineWorker 自己的 thread 控制
改由控制卡片按钮触发。

workspace 上下文优先级：
  1. 消息发自 workspace Topic → 用该 workspace
  2. 消息发自 thread Topic → 用该 thread 所属 workspace
  3. 消息发自全局 Topic 或未知 → 用 active_workspace
"""
import logging
from typing import Callable, Optional
from plugins.providers.builtin.codex.python.tui_bridge import (
    archive_codex_thread_via_tui_bridge,
    enqueue_codex_tui_message,
    is_codex_local_owner_mode,
    start_thread_via_tui_bridge,
)
from core.providers.facts import (
    list_provider_threads,
    query_provider_active_thread_ids,
    read_provider_thread_history,
)
from core.providers.registry import classify_provider, get_provider, provider_not_enabled_message
from telegram import Update
from telegram.ext import ContextTypes
from core.state import AppState
from core.storage import (
    WorkspaceInfo,
    ThreadInfo,
    save_storage,
)
from bot.handlers.common import _send_to_group, reconcile_workspace_threads_with_source
from bot.handlers.workspace import make_thread_open_callback_data
from bot.thread_controls import send_thread_control_panel, thread_interrupt_supported
from bot.utils import TopicNotFoundError

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


def _resolve_workspace(state: AppState, src_topic_id: Optional[int]) -> Optional[WorkspaceInfo]:
    """
    根据消息所在 topic_id 推断当前 workspace：
    - workspace Topic → 直接返回该 workspace
    - thread Topic → 返回 thread 所属 workspace
    - 其他 → 返回 active_workspace
    """
    if src_topic_id is not None:
        # workspace Topic？
        ws = state.find_workspace_by_topic_id(src_topic_id)
        if ws is not None:
            return ws
        # thread Topic？
        found = state.find_thread_by_topic_id(src_topic_id)
        if found is not None:
            return found[0]
    return state.get_active_workspace()


def _make_thread_topic_name(tool: str, ws_name: str, preview: Optional[str], thread_id: str) -> str:
    """生成 thread Topic 名称：[tool/ws_name] preview（最长 128 字符）。"""
    prefix = f"[{tool}/{ws_name}] "
    if preview:
        body = preview.strip().replace("\n", " ")
    else:
        body = f"thread-{thread_id[-8:]}"
    return (prefix + body)[:128]


def _extract_started_thread_id(result: object) -> str:
    """兼容 provider start_thread 的两种返回结构。"""
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError(f"start_thread 返回无效 thread id：{result}")
    return str(thread_id)


async def _rollback_failed_new_thread(
    state: AppState,
    bot,
    group_chat_id: int,
    ws: WorkspaceInfo,
    thread_id: Optional[str],
    topic_id: Optional[int],
) -> None:
    """清理 /new 失败留下的本地 thread 占位和 TG topic。"""
    if thread_id:
        ws.threads.pop(thread_id, None)

    if topic_id is None:
        return

    try:
        await bot.delete_forum_topic(
            chat_id=group_chat_id,
            message_thread_id=topic_id,
        )
        logger.info(f"已回滚删除新建失败的 Topic {topic_id}")
        return
    except Exception as e:
        logger.warning(f"回滚删除 Topic {topic_id} 失败，尝试关闭：{e}")

    try:
        await bot.close_forum_topic(
            chat_id=group_chat_id,
            message_thread_id=topic_id,
        )
        logger.info(f"已回滚关闭新建失败的 Topic {topic_id}")
    except Exception as e:
        logger.warning(f"回滚关闭 Topic {topic_id} 失败：{e}")


def _get_thread_provider(tool_name: str):
    return get_provider(tool_name)


def _get_thread_hooks(tool_name: str):
    provider = _get_thread_provider(tool_name)
    return provider.thread_hooks if provider is not None else None


def _resolve_thread_adapter(state: AppState, ws: WorkspaceInfo):
    """优先返回 provider thread hook 指定的 adapter。"""
    hooks = _get_thread_hooks(ws.tool)
    resolve_adapter = getattr(hooks, "resolve_adapter", None) if hooks is not None else None
    if callable(resolve_adapter):
        return resolve_adapter(state, ws)

    tool_adapter = state.get_adapter(ws.tool)
    if tool_adapter and tool_adapter.connected:
        return tool_adapter
    return None


def _list_provider_local_threads(tool_name: str, workspace_path: str, *, limit: int = 20) -> list[dict]:
    provider = _get_thread_provider(tool_name)
    hooks = provider.workspace_hooks if provider is not None else None
    list_local_threads = getattr(hooks, "list_local_threads", None) if hooks is not None else None
    if not callable(list_local_threads):
        return []
    return list_local_threads(workspace_path, limit=limit)


def _list_provider_subagent_thread_ids(tool_name: str, thread_ids: list[str]) -> set[str]:
    provider = _get_thread_provider(tool_name)
    facts = provider.facts if provider is not None else None
    list_subagent_thread_ids = getattr(facts, "list_subagent_thread_ids", None) if facts is not None else None
    if not callable(list_subagent_thread_ids):
        return set()
    return set(list_subagent_thread_ids(thread_ids) or set())


def _collect_session_ids(sessions: list[dict]) -> set[str]:
    return {
        str(session.get("id") or "")
        for session in sessions
        if isinstance(session, dict) and session.get("id")
    }


def _validate_new_thread_request(state: AppState, ws: WorkspaceInfo, initial_text: str | None) -> str | None:
    hooks = _get_thread_hooks(ws.tool)
    validate_new_thread = getattr(hooks, "validate_new_thread", None) if hooks is not None else None
    if callable(validate_new_thread):
        return validate_new_thread(state, ws, initial_text)
    return None


async def _activate_new_thread_in_source(
    state: AppState,
    adapter,
    ws: WorkspaceInfo,
    workspace_id: str,
    thread_id: str,
    initial_text: str | None,
) -> None:
    hooks = _get_thread_hooks(ws.tool)
    activate_new_thread = getattr(hooks, "activate_new_thread", None) if hooks is not None else None
    if callable(activate_new_thread):
        await activate_new_thread(state, adapter, ws, workspace_id, thread_id, initial_text)
        return

    await adapter.resume_thread(workspace_id, thread_id)
    if initial_text:
        await adapter.send_user_message(workspace_id, thread_id, initial_text)


def _list_sort_key(session: dict) -> tuple[int, int, str]:
    """统一 /list 排序：优先按创建时间，其次按更新时间。"""
    created_at = int(session.get("createdAt") or 0)
    updated_at = int(session.get("updatedAt") or 0)
    thread_id = str(session.get("id") or "")
    return (created_at, updated_at, thread_id)


def _should_include_state_only_thread(tool_name: str, thread_info: ThreadInfo) -> bool:
    if tool_name != "codex":
        return True
    if thread_info.topic_id is not None:
        return True
    return str(thread_info.source or "unknown").strip().lower() == "app"


def _resolve_thread_from_topic(
    state: AppState,
    src_topic_id: Optional[int],
) -> Optional[tuple[WorkspaceInfo, ThreadInfo]]:
    if src_topic_id is None:
        return None
    return state.find_thread_by_topic_id(src_topic_id)


async def _archive_thread_in_source(state: AppState, ws: WorkspaceInfo, thread_id: str) -> None:
    """先归档源工具，成功后才允许写本地 archived 状态。"""
    unavailable = _provider_unavailable_message(state, ws.tool)
    if unavailable:
        raise RuntimeError(unavailable)

    workspace_id = ws.daemon_workspace_id
    if not workspace_id:
        raise RuntimeError("workspace 未关联 daemon ID")

    hooks = _get_thread_hooks(ws.tool)
    archive_thread = getattr(hooks, "archive_thread", None) if hooks is not None else None
    active_adapter = _resolve_thread_adapter(state, ws)
    if callable(archive_thread):
        requires_adapter = bool(getattr(archive_thread, "requires_adapter", True))
        if requires_adapter and not active_adapter:
            raise RuntimeError(f"未连接 {ws.tool}，无法执行真实归档")
        await archive_thread(state, ws, thread_id, active_adapter)
        return

    if not active_adapter:
        raise RuntimeError(f"未连接 {ws.tool}，无法执行真实归档")
    await active_adapter.archive_thread(workspace_id, thread_id)


async def _interrupt_thread_in_source(
    state: AppState,
    ws: WorkspaceInfo,
    thread_info: ThreadInfo,
) -> None:
    unavailable = _provider_unavailable_message(state, ws.tool)
    if unavailable:
        raise RuntimeError(unavailable)

    workspace_id = ws.daemon_workspace_id
    if not workspace_id:
        raise RuntimeError("workspace 未关联 daemon ID")

    if not thread_interrupt_supported(state, ws):
        raise RuntimeError("当前主控模式暂不支持从 TG 远程中断，请回到 TUI 主控界面操作。")

    active_adapter = _resolve_thread_adapter(state, ws)
    if not active_adapter:
        raise RuntimeError(f"未连接 {ws.tool}，无法执行中断")

    streaming_state = state.streaming_turns.get(thread_info.thread_id)
    turn_id = streaming_state.turn_id if streaming_state and streaming_state.turn_id else ""

    hooks = _get_thread_hooks(ws.tool)
    interrupt_thread = getattr(hooks, "interrupt_thread", None) if hooks is not None else None
    if callable(interrupt_thread):
        await interrupt_thread(state, ws, thread_info, active_adapter, turn_id)
        return

    await active_adapter.turn_interrupt(workspace_id, thread_info.thread_id, turn_id)


async def _handle_archive_request(
    state: AppState,
    bot,
    group_chat_id: int,
    src_topic_id: Optional[int],
    *,
    thread_id_arg: Optional[str] = None,
) -> None:
    found = _resolve_thread_from_topic(state, src_topic_id)

    ws = _resolve_workspace(state, src_topic_id)
    if found is None and thread_id_arg and ws:
        thread_info = state.find_thread_by_id(ws, thread_id_arg)
        if thread_info:
            found = (ws, thread_info)

    reply_topic_id = (ws.topic_id if ws else None) or src_topic_id

    if found is None:
        await _send_to_group(
            bot,
            group_chat_id,
            "⚠️ 未找到对应 thread。\n"
            "在 thread Topic 里点“归档”，或在 workspace Topic 里执行 /archive <thread_id>",
            topic_id=reply_topic_id,
        )
        return

    ws_info, thread_info = found

    try:
        await _archive_thread_in_source(state, ws_info, thread_info.thread_id)
    except Exception as e:
        logger.error(f"真实归档 thread 失败：{e}")
        await _send_to_group(
            bot,
            group_chat_id,
            f"❌ 归档失败：{e}",
            topic_id=reply_topic_id,
        )
        return

    cfg = state.config
    delete_topic = cfg.delete_archived_topics if cfg else True
    action_text = "处理完成"

    thread_info.archived = True

    if thread_info.topic_id:
        try:
            if delete_topic:
                await bot.delete_forum_topic(
                    chat_id=group_chat_id,
                    message_thread_id=thread_info.topic_id,
                )
                logger.info(f"已删除 Topic {thread_info.topic_id}")
                action_text = "已删除"
            else:
                await bot.close_forum_topic(
                    chat_id=group_chat_id,
                    message_thread_id=thread_info.topic_id,
                )
                logger.info(f"已关闭 Topic {thread_info.topic_id}")
                action_text = "已关闭"

            if delete_topic:
                thread_info.topic_id = None
        except Exception as e:
            logger.warning(f"{'删除' if delete_topic else '关闭'} Topic 失败：{e}")
            action_text = "操作失败"

    if state.storage is None:
        logger.warning("storage 为 None，跳过保存（归档 thread）")
    else:
        save_storage(state.storage)

    await _send_to_group(
        bot,
        group_chat_id,
        f"thread `{thread_info.thread_id[-8:]}…` 已归档，Topic {action_text}。",
        topic_id=reply_topic_id,
        parse_mode="Markdown",
    )


async def _handle_history_request(
    state: AppState,
    bot,
    group_chat_id: int,
    src_topic_id: Optional[int],
    *,
    limit: int = 10,
) -> None:
    found = _resolve_thread_from_topic(state, src_topic_id)
    if not found:
        await _send_to_group(
            bot,
            group_chat_id,
            "⚠️ 请在 thread Topic 中使用此操作。",
            topic_id=src_topic_id,
        )
        return

    ws_info, thread_info = found
    thread_id = thread_info.thread_id
    tool_name = str(ws_info.tool or "").strip()
    if not tool_name:
        await _send_to_group(
            bot,
            group_chat_id,
            "❌ 当前 thread 未关联 provider。",
            topic_id=src_topic_id,
        )
        return
    unavailable = _provider_unavailable_message(state, tool_name)
    if unavailable:
        await _send_to_group(
            bot,
            group_chat_id,
            f"❌ 读取历史失败：{unavailable}",
            topic_id=src_topic_id,
        )
        return

    try:
        turns = read_provider_thread_history(
            tool_name,
            thread_id,
            limit=limit,
            sessions_dir=None,
        )
    except Exception as e:
        logger.warning(f"读取 thread {thread_id[:8]}… 历史失败：{e}")
        await _send_to_group(
            bot,
            group_chat_id,
            f"❌ 读取历史失败：{e}",
            topic_id=src_topic_id,
        )
        return

    if not turns:
        await _send_to_group(
            bot,
            group_chat_id,
            "📭 暂无历史消息。",
            topic_id=src_topic_id,
        )
        return

    await _send_to_group(
        bot,
        group_chat_id,
        f"📜 历史记录（最近 {len(turns)} 条）：",
        topic_id=src_topic_id,
    )

    for turn in turns:
        role = turn.get("role", "")
        text = turn.get("text", "").strip()
        if not text:
            continue
        if role == "user":
            out = f"👤 {text[:3000]}"
        elif role == "assistant":
            truncated = text[:3000]
            if len(text) > 3000:
                truncated += "\n…（截断）"
            out = f"🤖 {truncated}"
        else:
            continue
        try:
            await _send_to_group(bot, group_chat_id, out, topic_id=src_topic_id)
        except Exception as e:
            logger.warning(f"发送历史消息失败：{e}")

    logger.info(f"thread {thread_id[:8]}… history 完成（{len(turns)} 条）")


async def handle_thread_control_callback(
    state: AppState,
    bot,
    group_chat_id: int,
    query,
    action: str,
) -> bool:
    if action not in {"help", "history", "interrupt", "archive"}:
        return False

    src_topic_id = query.message.message_thread_id if getattr(query, "message", None) else None
    found = _resolve_thread_from_topic(state, src_topic_id)

    if action == "help":
        if not found:
            await _send_to_group(
                bot,
                group_chat_id,
                "⚠️ 当前 Topic 未关联 thread。",
                topic_id=src_topic_id,
            )
            return True
        ws_info, thread_info = found
        await send_thread_control_panel(
            state,
            bot,
            group_chat_id,
            ws_info,
            thread_info,
            intro="Thread 控制说明已刷新。",
            topic_id=src_topic_id,
        )
        return True

    if action == "history":
        await _handle_history_request(
            state,
            bot,
            group_chat_id,
            src_topic_id,
            limit=10,
        )
        return True

    if action == "interrupt":
        if not found:
            await _send_to_group(
                bot,
                group_chat_id,
                "⚠️ 当前 Topic 未关联 thread。",
                topic_id=src_topic_id,
            )
            return True
        ws_info, thread_info = found
        try:
            await _interrupt_thread_in_source(state, ws_info, thread_info)
        except Exception as e:
            await _send_to_group(
                bot,
                group_chat_id,
                f"❌ 中断失败：{e}",
                topic_id=src_topic_id,
            )
            return True
        await _send_to_group(
            bot,
            group_chat_id,
            "🛑 已发送中断请求。",
            topic_id=src_topic_id,
        )
        return True

    await _handle_archive_request(
        state,
        bot,
        group_chat_id,
        src_topic_id,
    )
    return True


def make_new_thread_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /new [<初始消息>]
    在当前 workspace 下新建 codex thread + Telegram Topic。
    可在 workspace Topic 或全局 Topic 里调用。
    """
    async def new_thread(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        src_topic_id = msg.message_thread_id if msg else None  # type: ignore[union-attr]

        ws = _resolve_workspace(state, src_topic_id)
        reply_topic_id = (ws.topic_id if ws else None) or src_topic_id

        if not ws:
            await _send_to_group(
                context.bot, group_chat_id,
                "⚠️ 未找到 workspace。请先用 /workspace 打开一个 workspace。",
                topic_id=reply_topic_id,
            )
            return
        unavailable = _provider_unavailable_message(state, ws.tool)
        if unavailable:
            await _send_to_group(
                context.bot,
                group_chat_id,
                f"❌ 新建 thread 失败：{unavailable}",
                topic_id=reply_topic_id,
            )
            return

        workspace_id = ws.daemon_workspace_id
        if not workspace_id:
            await _send_to_group(
                context.bot, group_chat_id,
                "❌ workspace 未关联 daemon ID。",
                topic_id=reply_topic_id,
            )
            return

        initial_text = " ".join(context.args).strip() if context.args else None

        validation_error = _validate_new_thread_request(state, ws, initial_text)
        if validation_error:
            await _send_to_group(
                context.bot,
                group_chat_id,
                validation_error,
                topic_id=reply_topic_id,
                parse_mode="Markdown",
            )
            return

        active_adapter = _resolve_thread_adapter(state, ws) if ws else None
        if not active_adapter or not active_adapter.connected:
            await _send_to_group(
                context.bot, group_chat_id,
                "❌ 未连接，无法新建 thread。",
                topic_id=reply_topic_id,
            )
            return

        thread_id: Optional[str] = None
        topic_id: Optional[int] = None

        try:
            # 1. daemon 中新建 thread
            result = await active_adapter.start_thread(workspace_id)
            thread_id = _extract_started_thread_id(result)

            # 1b. 立即占位注册 ThreadInfo（topic_id=None），避免 SSE 事件（turn/started 等）
            #     在 create_forum_topic 返回前触发时，_resolve_topic_id 找不到 thread
            #     而 fallback 到 workspace topic。
            thread_info = ThreadInfo(
                thread_id=thread_id,
                topic_id=None,
                preview=initial_text or None,
                archived=False,
                source="app",
            )
            ws.threads[thread_id] = thread_info
            # 注意：此处不 save_storage，topic_id 尚未确定

            # 2. 创建 Telegram Forum Topic
            topic_name = _make_thread_topic_name(ws.tool, ws.name, initial_text, thread_id)
            topic = await context.bot.create_forum_topic(chat_id=group_chat_id, name=topic_name)
            topic_id = topic.message_thread_id

            # 3. 更新 topic_id，先不持久化；只有源端 thread 就绪后才写入 storage
            thread_info.topic_id = topic_id

            await _activate_new_thread_in_source(
                state,
                active_adapter,
                ws,
                workspace_id,
                thread_id,
                initial_text,
            )

            if state.storage is None:
                logger.warning("storage 为 None，跳过保存（新 thread 创建）")
            else:
                save_storage(state.storage)

            logger.info(f"新建 thread {thread_id[:8]}… → Topic {topic_id}")

        except Exception as e:
            await _rollback_failed_new_thread(
                state=state,
                bot=context.bot,
                group_chat_id=group_chat_id,
                ws=ws,
                thread_id=thread_id,
                topic_id=topic_id,
            )
            logger.error(f"新建 thread 失败：{e}")
            await _send_to_group(
                context.bot, group_chat_id,
                f"❌ 新建 thread 失败：{e}",
                topic_id=reply_topic_id,
            )
            return

        if reply_topic_id is not None and reply_topic_id != topic_id:
            try:
                await _send_to_group(
                    context.bot,
                    group_chat_id,
                    f"✅ 新 thread 已创建，请切到新 Topic 继续。\nThread ID: `{thread_id}`",
                    topic_id=reply_topic_id,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"新建 thread 成功，但 workspace 确认消息发送失败：{e}")

        if initial_text:
            try:
                await send_thread_control_panel(
                    state,
                    context.bot,
                    group_chat_id,
                    ws,
                    thread_info,
                    intro=f"新 thread 已创建，初始消息已发送。\nThread ID: `{thread_id}`",
                    topic_id=topic_id,
                )
            except Exception as e:
                logger.warning(f"新建 thread 成功，但发送确认消息失败：{e}")
        else:
            try:
                await send_thread_control_panel(
                    state,
                    context.bot,
                    group_chat_id,
                    ws,
                    thread_info,
                    intro=f"新 thread 已创建，在此 Topic 继续对话。\nThread ID: `{thread_id}`",
                    topic_id=topic_id,
                )
            except Exception as e:
                logger.warning(f"新建 thread 成功，但发送确认消息失败：{e}")

    return new_thread


def make_list_thread_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /list
    列出当前 workspace 的所有 thread（最近 20 个）。
    为没有 topic 的 threads 提供 inline buttons（点击时创建 topic）。
    在 workspace Topic 里调用最自然。
    """
    async def list_threads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        src_topic_id = msg.message_thread_id if msg else None  # type: ignore[union-attr]
        logger.info(f"[/list] src_topic_id={src_topic_id}")

        ws = _resolve_workspace(state, src_topic_id)
        reply_topic_id = (ws.topic_id if ws else None) or src_topic_id
        logger.info(f"[/list] resolved ws={ws.name if ws else None} reply_topic_id={reply_topic_id}")

        if not ws:
            await _send_to_group(
                context.bot, group_chat_id,
                "⚠️ 未找到 workspace，请先用 /workspace 打开。",
                topic_id=reply_topic_id,
            )
            return
        unavailable = _provider_unavailable_message(state, ws.tool)
        if unavailable:
            await _send_to_group(
                context.bot,
                group_chat_id,
                f"❌ 获取 thread 列表失败：{unavailable}",
                topic_id=reply_topic_id,
            )
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        db_sessions = list_provider_threads(ws.tool, ws.path, limit=20)
        local_sessions = _list_provider_local_threads(ws.tool, ws.path, limit=20)
        active_ids, _ = reconcile_workspace_threads_with_source(state, ws)
        if active_ids is None:
            logger.debug("[/list] 查询活跃 thread 失败，继续使用空集合")
            active_ids = set()

        db_ids = _collect_session_ids(db_sessions)
        local_ids = _collect_session_ids(local_sessions)
        subagent_ids = _list_provider_subagent_thread_ids(
            ws.tool,
            list(db_ids | local_ids | set(ws.threads.keys())),
        )

        if subagent_ids:
            db_sessions = [
                session for session in db_sessions
                if str(session.get("id") or "") not in subagent_ids
            ]
            local_sessions = [
                session for session in local_sessions
                if str(session.get("id") or "") not in subagent_ids
            ]
            db_ids -= subagent_ids
            local_ids -= subagent_ids

        if ws.tool == "claude":
            archived_ids = {
                tid
                for tid, tinfo in ws.threads.items()
                if getattr(tinfo, "archived", False)
            }
            if archived_ids:
                db_sessions = [
                    session for session in db_sessions
                    if str(session.get("id") or "") not in archived_ids
                ]
                local_sessions = [
                    session for session in local_sessions
                    if str(session.get("id") or "") not in archived_ids
                ]
                db_ids -= archived_ids
                local_ids -= archived_ids

        max_persisted_created_at = max(
            int(s.get("createdAt") or 0)
            for s in (db_sessions + local_sessions)
        ) if (db_sessions or local_sessions) else 0

        state_only_sessions = []
        if ws.tool != "claude":
            synthetic_created_at = max_persisted_created_at + len(ws.threads) + 1
            for tid, tinfo in reversed(list(ws.threads.items())):
                if (
                    tinfo.archived
                    or tid in db_ids
                    or tid in local_ids
                    or tid in subagent_ids
                    or not _should_include_state_only_thread(ws.tool, tinfo)
                ):
                    continue
                state_only_sessions.append(
                    {
                        "id": tid,
                        "preview": tinfo.preview,
                        "createdAt": synthetic_created_at,
                        "updatedAt": 0,
                    }
                )
                synthetic_created_at -= 1

        state_ids = set(ws.threads.keys())
        local_only_sessions = []
        for session in local_sessions:
            tid = str(session.get("id") or "")
            if not tid or tid in db_ids or tid in state_ids:
                continue
            local_only_sessions.append(session)

        merged_sessions = state_only_sessions + local_only_sessions + db_sessions
        merged_sessions.sort(key=_list_sort_key, reverse=True)
        if not merged_sessions:
            await _send_to_group(
                context.bot, group_chat_id,
                f"workspace `{ws.name}` 暂无 thread，用 /new 新建。",
                topic_id=reply_topic_id,
                parse_mode="Markdown",
            )
            return

        lines = [f"*[{ws.tool}] {ws.name}* 的 thread 列表：\n"]
        buttons = []
        ws_id = ws.daemon_workspace_id or f"{ws.tool}:{ws.name}"

        for s in merged_sessions[:20]:
            tid = s.get("id", "")
            preview = (s.get("preview") or "")[:40]
            tid_short = tid[-8:]
            label = preview or f"thread-{tid_short}"
            existing_thread = ws.threads.get(tid)
            icon = "✅" if getattr(existing_thread, "topic_id", None) else "📌"
            lines.append(f"{icon} `{tid_short}`  {preview}")

            label = f"{icon} {label}"[:40]
            buttons.append([InlineKeyboardButton(
                label,
                callback_data=make_thread_open_callback_data(ws_id, tid)
            )])

        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        footer = f"\n\n💡 点击下方按钮打开 thread"

        try:
            await _send_to_group(
                context.bot, group_chat_id,
                "\n".join(lines) + footer,
                topic_id=reply_topic_id,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except TopicNotFoundError:
            if ws and ws.topic_id == reply_topic_id:
                logger.info(f"workspace {ws.name} topic {ws.topic_id} 已不存在，清除 topic_id")
                ws.topic_id = None
                if state.storage:
                    save_storage(state.storage)
            fallback_topic = src_topic_id if src_topic_id != reply_topic_id else None
            await _send_to_group(
                context.bot, group_chat_id,
                "⚠️ workspace topic 已失效，请用 /workspace 重新打开。\n\n" + "\n".join(lines) + footer,
                topic_id=fallback_topic,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )

    return list_threads


def make_archive_thread_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /archive [<thread_id>]
    - 在 thread Topic 里执行 → 归档当前 thread
    - 在 workspace Topic 里执行且带 thread_id → 归档指定 thread
    
    根据配置 delete_archived_topics 决定是删除还是仅关闭 topic。
    """
    async def archive_thread(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        src_topic_id = msg.message_thread_id if msg else None  # type: ignore[union-attr]
        thread_id_arg = context.args[0] if context.args else None
        await _handle_archive_request(
            state,
            context.bot,
            group_chat_id,
            src_topic_id,
            thread_id_arg=thread_id_arg,
        )

    return archive_thread


def make_skills_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /skills
    列出当前 workspace 已注册的 skill（通过 daemon skills_list RPC 获取）。
    可在 workspace Topic 或 thread Topic 里调用。
    """
    async def skills(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        src_topic_id = msg.message_thread_id if msg else None  # type: ignore[union-attr]

        ws = _resolve_workspace(state, src_topic_id)
        # 回复到命令所在 topic，而不是 workspace topic
        reply_topic_id = src_topic_id

        if not ws:
            await _send_to_group(
                context.bot, group_chat_id,
                "⚠️ 未找到 workspace，请先用 /workspace 打开。",
                topic_id=reply_topic_id,
            )
            return
        unavailable = _provider_unavailable_message(state, ws.tool)
        if unavailable:
            await _send_to_group(
                context.bot,
                group_chat_id,
                f"❌ 获取 skill 列表失败：{unavailable}",
                topic_id=reply_topic_id,
            )
            return

        active_adapter = state.get_adapter(ws.tool) if ws else None
        if not active_adapter or not active_adapter.connected:
            await _send_to_group(
                context.bot, group_chat_id,
                f"❌ {ws.tool if ws else '工具'} 未连接，无法获取 skill 列表。",
                topic_id=reply_topic_id,
            )
            return

        workspace_id = ws.daemon_workspace_id
        if not workspace_id:
            await _send_to_group(
                context.bot, group_chat_id,
                "❌ workspace 未关联 daemon ID。",
                topic_id=reply_topic_id,
            )
            return

        try:
            skill_list = await active_adapter.skills_list(workspace_id)
        except Exception as e:
            logger.error(f"获取 skill 列表失败：{e}")
            await _send_to_group(
                context.bot, group_chat_id,
                f"❌ 获取 skill 列表失败：{e}",
                topic_id=reply_topic_id,
            )
            return

        if not skill_list:
            await _send_to_group(
                context.bot, group_chat_id,
                f"*[{ws.tool}] {ws.name}* 暂无已注册的 skill。",
                topic_id=reply_topic_id,
                parse_mode="Markdown",
            )
            return

        # 按 scope 分组
        groups: dict[str, list[str]] = {}
        for skill in skill_list:
            name = skill.get("name") or "?"
            scope = skill.get("scope") or "user"
            enabled = skill.get("enabled", True)
            prefix = "" if enabled else "~"
            groups.setdefault(scope, []).append(f"{prefix}`{name}`")

        scope_order = ["project", "user", "system"]
        scope_labels = {"project": "项目", "user": "用户", "system": "系统"}

        lines = [f"*[{ws.tool}] {ws.name}* skill 列表（共 {len(skill_list)} 个）："]
        for scope in scope_order:
            if scope not in groups:
                continue
            label = scope_labels.get(scope, scope)
            names = "  ".join(groups[scope])
            lines.append(f"\n*{label}*\n{names}")

        # 加上其余未知 scope
        for scope, names_list in groups.items():
            if scope not in scope_order:
                names = "  ".join(names_list)
                lines.append(f"\n*{scope}*\n{names}")

        await _send_to_group(
            context.bot, group_chat_id,
            "\n".join(lines),
            topic_id=reply_topic_id,
            parse_mode="Markdown",
        )

    return skills


def make_history_handler(state: AppState, group_chat_id: int) -> Callable:
    """
    /history [<N>]
    在 thread Topic 里执行，显示最近 N 条历史对话（默认 10）。
    历史读取走 provider facts facade。
    """
    async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        src_topic_id = msg.message_thread_id if msg else None  # type: ignore[union-attr]

        # 解析 limit 参数
        limit = 10
        if context.args:
            try:
                limit = max(1, min(int(context.args[0]), 50))
            except ValueError:
                pass
        await _handle_history_request(
            state,
            context.bot,
            group_chat_id,
            src_topic_id,
            limit=limit,
        )

    return history
