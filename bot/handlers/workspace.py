# bot/handlers/workspace.py
"""
/workspace 命令：列出所有已知 workspace（扫描各工具的 sessions 目录），按需打开。

三层 Topic 结构：
  codex                        ← 工具全局控制台（/workspace 在这里响应）
  [codex] nm_common_cache      ← workspace 控制台（/new /list 在这里响应）
  [codex/nm_common_cache] ...  ← thread Topic（消息直接发给 codex）

交互流程：
  /workspace
    → 扫描所有已启用工具的 sessions 目录，列出所有 cwd
    → inline keyboard 每行一个按钮，✅ 表示已打开
  点击已打开的 workspace → 发消息到该 workspace Topic 提示已打开
  点击未打开的 workspace → 注册 daemon + 创建 workspace Topic + 同步最新 10 个 thread
"""
import logging
import hashlib
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes, CallbackQueryHandler
from config import Config
from core.providers.facts import (
    list_provider_threads,
    query_provider_active_thread_ids,
    read_provider_thread_history,
    scan_provider_workspaces,
)
from core.providers.registry import classify_provider, get_provider, provider_not_enabled_message
from core.state import AppState
from core.storage import (
    WorkspaceInfo, ThreadInfo,
    save_storage,
)
from bot.handlers.common import (
    _send_to_group,
    clear_stale_thread_archive_if_active,
    reconcile_workspace_threads_with_source,
)
from bot.thread_controls import send_thread_control_panel
from bot.utils import TopicNotFoundError

logger = logging.getLogger(__name__)


def _provider_unavailable_message(state: AppState, tool_name: str) -> str | None:
    if state.config is None:
        return None
    classification = classify_provider(tool_name, state.config)
    if classification in {"available", "hidden_provider"}:
        return None
    return provider_not_enabled_message(tool_name, classification)


# bot_data key：存储本次 /workspace 扫描到的列表（供 callback 按 index 查找）
_WS_LIST_KEY = "workspace_list_session"

# 每次打开 workspace 时同步的最大 thread 数
_THREAD_SYNC_LIMIT = 10
_THREAD_HISTORY_SYNC_LOOKBACK = 50

# 正在创建 topic 的 thread_id 集合，防止并发重复创建
_creating_topics: set[str] = set()
_THREAD_OPEN_V2_PREFIX = "thread_open_v2"


def _get_workspace_hooks(tool_name: str):
    provider = get_provider(tool_name)
    return provider.workspace_hooks if provider is not None else None


def _normalize_provider_server_threads(tool_name: str, server_threads: list[dict], *, limit: int) -> list[dict]:
    hooks = _get_workspace_hooks(tool_name)
    normalize = getattr(hooks, "normalize_server_threads", None) if hooks is not None else None
    if callable(normalize):
        return normalize(server_threads, limit=limit)

    threads = [item for item in server_threads if not item.get("ephemeral", False)]
    threads.sort(key=lambda item: item.get("updatedAt", 0), reverse=True)
    return threads[:limit]


async def _notify_provider_workspace_opened(tool_name: str, adapter, path: str, workspace_id: str) -> None:
    hooks = _get_workspace_hooks(tool_name)
    callback = getattr(hooks, "on_workspace_opened", None) if hooks is not None else None
    if callable(callback):
        await callback(adapter, path, workspace_id)


def _list_provider_local_threads(tool_name: str, workspace_path: str, *, limit: int) -> list[dict]:
    hooks = _get_workspace_hooks(tool_name)
    list_local_threads = getattr(hooks, "list_local_threads", None) if hooks is not None else None
    if callable(list_local_threads):
        return list_local_threads(workspace_path, limit=limit)
    return []


def _make_thread_topic_name(tool_name: str, ws_name: str, preview: Optional[str], thread_id: str) -> str:
    """生成 thread Topic 名称：[tool/ws_name] preview（最长 128 字符）。"""
    prefix = f"[{tool_name}/{ws_name}] "
    if preview:
        body = preview.strip().replace("\n", " ")
    else:
        body = f"thread-{thread_id[-8:]}"
    return (prefix + body)[:128]


def _make_thread_open_token(value: str) -> str:
    """生成稳定短 token，供 thread_open callback 唯一定位使用。"""
    return hashlib.blake2s(value.encode("utf-8"), digest_size=8).hexdigest()


def _history_turn_signature(turn: dict) -> str:
    role = str(turn.get("role") or "").strip()
    timestamp = int(turn.get("timestamp") or 0)
    text = str(turn.get("text") or "").strip()
    payload = f"{role}\n{timestamp}\n{text}".encode("utf-8")
    return hashlib.blake2s(payload, digest_size=16).hexdigest()


def _format_history_turn_message(turn: dict) -> Optional[str]:
    role = str(turn.get("role") or "").strip()
    text = str(turn.get("text") or "").strip()
    if not text:
        return None
    if role == "user":
        return f"👤 {text[:3000]}"
    if role == "assistant":
        truncated = text[:3000]
        if len(text) > 3000:
            truncated += "\n…（截断）"
        return f"🤖 {truncated}"
    return None


def _build_history_sync_batches(header: str, turn_messages: list[str], *, max_chars: int = 3500) -> list[str]:
    batches: list[str] = []
    current = header.strip()

    for msg in turn_messages:
        if not msg:
            continue
        addition = f"\n\n{msg}" if current else msg
        if current and len(current) + len(addition) > max_chars:
            batches.append(current)
            current = msg
            continue
        current += addition

    if current:
        batches.append(current)
    return batches


async def _sync_existing_claude_thread_history(
    *,
    bot,
    group_chat_id: int,
    topic_id: int,
    thread_info: ThreadInfo,
    thread_id: str,
    storage,
) -> bool:
    try:
        history = read_provider_thread_history(
            "claude",
            thread_id,
            limit=_THREAD_HISTORY_SYNC_LOOKBACK,
            sessions_dir=None,
        )
    except Exception as e:
        logger.warning(f"[thread_open] 读取 Claude thread {thread_id[:8]}… 历史失败：{e}")
        return False

    if not history:
        logger.info(
            "[claude-history-sync] thread=%s topic=%s 无历史可同步",
            thread_id[:12],
            topic_id,
        )
        return False

    current_cursor = thread_info.history_sync_cursor or None
    latest_cursor = _history_turn_signature(history[-1])
    turns_to_send: list[dict] = []
    snapshot_mode = False

    if current_cursor:
        matched_index = -1
        for index in range(len(history) - 1, -1, -1):
            if _history_turn_signature(history[index]) == current_cursor:
                matched_index = index
                break
        if matched_index >= 0:
            turns_to_send = history[matched_index + 1:]
        else:
            snapshot_mode = True
            turns_to_send = history[-_THREAD_SYNC_LIMIT:]
    else:
        snapshot_mode = True
        turns_to_send = history[-_THREAD_SYNC_LIMIT:]

    if not turns_to_send:
        if thread_info.history_sync_cursor != latest_cursor:
            thread_info.history_sync_cursor = latest_cursor
            if storage:
                save_storage(storage)
        logger.info(
            "[claude-history-sync] thread=%s topic=%s 已是最新，无需补齐",
            thread_id[:12],
            topic_id,
        )
        return False

    header = (
        f"🔄 当前会话快照（最近 {len(turns_to_send)} 条）："
        if snapshot_mode
        else f"🔄 同步到 {len(turns_to_send)} 条新消息："
    )
    rendered_turns = [
        msg
        for msg in (_format_history_turn_message(turn) for turn in turns_to_send)
        if msg
    ]
    for batch in _build_history_sync_batches(header, rendered_turns):
        await _send_to_group(
            bot,
            group_chat_id,
            batch,
            topic_id=topic_id,
        )

    if thread_info.history_sync_cursor != latest_cursor:
        thread_info.history_sync_cursor = latest_cursor
        if storage:
            save_storage(storage)
    logger.info(
        "[claude-history-sync] thread=%s topic=%s mode=%s sent=%s",
        thread_id[:12],
        topic_id,
        "snapshot" if snapshot_mode else "incremental",
        len(turns_to_send),
    )
    return True


def _get_workspace_callback_identity(storage_key: str, ws: WorkspaceInfo) -> str:
    return ws.daemon_workspace_id or storage_key or f"{ws.tool}:{ws.name}"


def make_thread_open_callback_data(ws_id: str, thread_id: str) -> str:
    """构造 thread_open 唯一 callback_data，避免 thread id 前缀冲突。"""
    return f"{_THREAD_OPEN_V2_PREFIX}:{_make_thread_open_token(ws_id)}:{_make_thread_open_token(thread_id)}"


def _resolve_thread_open_workspace(storage, data: str) -> tuple[Optional[WorkspaceInfo], Optional[str], Optional[str]]:
    """解析 callback 所属 workspace 与 thread 定位 key。

    返回：(workspace, unique_thread_token, legacy_thread_prefix)
    """
    if data.startswith(f"{_THREAD_OPEN_V2_PREFIX}:"):
        _, ws_token, thread_token = data.split(":", 2)
        matches: list[tuple[str, WorkspaceInfo]] = []
        for storage_key, ws in storage.workspaces.items():
            ws_id = _get_workspace_callback_identity(storage_key, ws)
            if _make_thread_open_token(ws_id) == ws_token:
                matches.append((ws_id, ws))
        if len(matches) != 1:
            return None, None, None
        return matches[0][1], thread_token, None

    if not data.startswith("thread_open:"):
        return None, None, None

    remaining = data[len("thread_open:"):]
    for storage_key, ws in storage.workspaces.items():
        ws_id = _get_workspace_callback_identity(storage_key, ws)
        prefix = f"{ws_id}:"
        if remaining.startswith(prefix):
            return ws, None, remaining[len(prefix):]
    return None, None, None


def make_workspace_handler(state: AppState, group_chat_id: int, cfg: Config):
    """
    /workspace → 扫描所有已启用工具的 sessions 目录，列出所有 cwd，inline keyboard 每行一个按钮。
    回复到命令所在的 topic（通常是 codex 全局 topic）。
    """
    async def workspace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        storage = state.storage
        # 回复到命令所在的 topic
        src_topic_id = update.effective_message.message_thread_id if update.effective_message else None

        # 判断当前在哪个工具的全局 Topic，只扫描该工具
        current_tool = state.get_tool_by_global_topic(src_topic_id)

        if current_tool:
            target_tools = [t for t in cfg.enabled_tools if t.name == current_tool]
        else:
            # 不在全局 Topic（如 workspace topic 或未知），扫描全部
            target_tools = cfg.enabled_tools

        await _send_to_group(context.bot, group_chat_id, "正在扫描……", topic_id=src_topic_id)

        # 扫描目标工具的 sessions
        all_items: list[dict] = []
        for tool in target_tools:
            items = scan_provider_workspaces(tool.name)
            for item in items:
                item["tool"] = tool.name
                all_items.append(item)

        if not all_items:
            await _send_to_group(context.bot, group_chat_id, "未发现任何 session。", topic_id=src_topic_id)
            return

        # 已打开（有 Topic）的 (tool, path) 集合
        opened: dict[tuple, WorkspaceInfo] = {}
        if storage:
            for ws in storage.workspaces.values():
                if ws.topic_id is not None:
                    opened[(ws.tool, ws.path)] = ws

        # 存入 bot_data 供 callback 按 index 查找
        context.bot_data[_WS_LIST_KEY] = {
            "items": all_items,
            "cfg": cfg,
            "group_chat_id": group_chat_id,
        }

        # 构建 keyboard
        keyboard = []
        for i, item in enumerate(all_items):
            key = (item["tool"], item["path"])
            ws_info = opened.get(key)
            status = "✅" if ws_info is not None else "📂"
            label = f"{status} [{item['tool']}] {item['name']}  ({item['thread_count']} threads)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"ws_open:{i}")])

        await _send_to_group(
            context.bot, group_chat_id,
            f"共发现 *{len(all_items)}* 个 workspace，点击打开：",
            topic_id=src_topic_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    return workspace


def make_ws_open_callback_handler(state: AppState, group_chat_id: int) -> CallbackQueryHandler:
    """
    处理 ws_open:<idx> callback：
    - 已打开（有 Topic）→ 发提示消息到该 workspace Topic
    - 未打开 → 注册 daemon + 创建 workspace Topic（名为 [tool] ws_name）+ 同步最新 10 个 thread
    """
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        await query.answer()

        data = query.data or ""
        if not data.startswith("ws_open:"):
            return

        try:
            idx = int(data.split(":")[1])
        except (ValueError, IndexError):
            await query.edit_message_text("❌ 参数解析失败")
            return

        session = context.bot_data.get(_WS_LIST_KEY)
        if not session:
            await query.edit_message_text("会话已过期，请重新执行 /workspace")
            return

        items: list[dict] = session["items"]
        cfg: Config = session["cfg"]

        if idx >= len(items):
            await query.edit_message_text("❌ 索引越界")
            return

        item = items[idx]
        path: str = item["path"]
        name: str = item["name"]
        tool_name: str = item["tool"]
        storage = state.storage
        unavailable = _provider_unavailable_message(state, tool_name)
        if unavailable:
            await query.edit_message_text(f"❌ {unavailable}")
            return

        # 找到对应 tool 配置
        tool_cfg = cfg.get_tool(tool_name)
        if tool_cfg is None:
            await query.edit_message_text(f"❌ {provider_not_enabled_message(tool_name, 'disabled_provider')}")
            return

        # 检查是否已打开
        existing_ws: Optional[WorkspaceInfo] = None
        if storage:
            for ws in storage.workspaces.values():
                if ws.tool == tool_name and ws.path == path and ws.topic_id is not None:
                    existing_ws = ws
                    break

        if existing_ws is not None:
            # 直接发消息到已有 topic，如果 topic 被删了会抛 TopicNotFoundError
            bot = query.get_bot()
            try:
                await query.edit_message_text(
                    f"`[{tool_name}] {name}` 已打开，跳转到对应 Topic。",
                    parse_mode="Markdown",
                )
                await _send_to_group(
                    bot, group_chat_id,
                    f"workspace `{name}` 已打开。",
                    topic_id=existing_ws.topic_id,
                    parse_mode="Markdown",
                )
                return
            except TopicNotFoundError:
                # topic 已被删除，重建 workspace topic（保留 thread 数据）
                logger.info(f"workspace {name} 的 topic {existing_ws.topic_id} 已不存在，重建 topic")
                try:
                    ws_topic_name = f"[{tool_name}] {name}"[:128]
                    new_topic = await bot.create_forum_topic(chat_id=group_chat_id, name=ws_topic_name)
                    existing_ws.topic_id = new_topic.message_thread_id
                    if storage:
                        save_storage(storage)
                    logger.info(f"workspace {name} topic 重建成功：{existing_ws.topic_id}")

                    await query.edit_message_text(
                        f"✅ `[{tool_name}] {name}` topic 已重建",
                        parse_mode="Markdown",
                    )

                    # 发送 thread 列表 + 按钮到新的 workspace topic
                    await _send_workspace_thread_overview(
                        state, bot, group_chat_id, existing_ws, tool_name,
                    )
                except Exception as e:
                    logger.error(f"重建 workspace {name} topic 失败：{e}")
                    await query.edit_message_text(f"❌ 重建 topic 失败：{e}")
                return

        # 未打开，执行注册流程
        await query.edit_message_text(
            f"正在打开 `[{tool_name}] {name}`……",
            parse_mode="Markdown",
        )

        bot = query.get_bot()
        try:
            ws_info = await _open_workspace(
                bot=bot,
                state=state,
                storage=storage,
                group_chat_id=group_chat_id,
                tool_cfg=tool_cfg,
                name=name,
                path=path,
            )
        except Exception as e:
            logger.error(f"打开 workspace 失败：{e}")
            await _send_to_group(
                bot, group_chat_id,
                f"❌ 打开 `[{tool_name}] {name}` 失败：{e}",
                parse_mode="Markdown",
            )
            return

        thread_count = len(ws_info.threads)
        await _send_to_group(
            bot, group_chat_id,
            f"✅ `[{tool_name}] {name}` 已打开\n"
            f"路径：`{path}`\n"
            f"已同步 {thread_count} 个最新 thread。",
            topic_id=ws_info.topic_id,
            parse_mode="Markdown",
        )

    return CallbackQueryHandler(callback, pattern=r"^ws_open:")


def make_thread_open_callback_handler(state: AppState, group_chat_id: int) -> CallbackQueryHandler:
    """
    Handle thread_open callback:
    - `thread_open_v2:<ws_token>:<thread_token>`：当前唯一定位格式
    - `thread_open:<ws_id>:<thread_id_prefix>`：旧格式，只做兼容读取
    """
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        logger.info(f"[thread_open] callback triggered, query={query is not None}")
        if query is None:
            return
        
        data = query.data or ""
        logger.info(f"[thread_open] callback_data='{data}'")
        
        await query.answer()

        if not (data.startswith("thread_open:") or data.startswith(f"{_THREAD_OPEN_V2_PREFIX}:")):
            logger.info(f"[thread_open] data 不匹配，跳过")
            return

        storage = state.storage
        if not storage:
            await query.answer("❌ Storage 未初始化", show_alert=True)
            return

        ws_info, thread_token, thread_id_prefix = _resolve_thread_open_workspace(storage, data)
        if not ws_info or not (thread_token or thread_id_prefix):
            await query.answer("❌ Workspace 未找到", show_alert=True)
            return
        unavailable = _provider_unavailable_message(state, ws_info.tool)
        if unavailable:
            await query.answer(f"❌ {unavailable}", show_alert=True)
            return

        logger.info(
            "[thread_open] 解析完成: ws=%s token=%s prefix=%s",
            ws_info.daemon_workspace_id or f"{ws_info.tool}:{ws_info.name}",
            thread_token,
            thread_id_prefix,
        )

        # Find the thread — 先查 state.json，没有则从 SQLite 补注册
        thread_info = None
        full_tid = None
        if thread_token:
            state_matches = [
                (tid, tinfo)
                for tid, tinfo in ws_info.threads.items()
                if _make_thread_open_token(tid) == thread_token
            ]
            if len(state_matches) == 1:
                full_tid, thread_info = state_matches[0]
            elif len(state_matches) > 1:
                await query.answer("❌ thread 标识冲突，请重新 /list", show_alert=True)
                return
        else:
            legacy_matches = [
                (tid, tinfo)
                for tid, tinfo in ws_info.threads.items()
                if tid.startswith(thread_id_prefix) or tid[:32] == thread_id_prefix
            ]
            if len(legacy_matches) == 1:
                full_tid, thread_info = legacy_matches[0]
            elif len(legacy_matches) > 1:
                await query.answer("⚠️ 旧按钮已过期，请重新运行 /list", show_alert=True)
                return

        local_fallback_threads = None
        if not thread_info:
            # state.json 里没有，从各 provider 的本地事实源查
            db_sessions = list_provider_threads(ws_info.tool, ws_info.path, limit=50)
            local_fallback_threads = _list_provider_local_threads(ws_info.tool, ws_info.path, limit=50)
            if thread_token:
                db_matches = [
                    s for s in db_sessions
                    if _make_thread_open_token(s.get("id", "")) == thread_token
                ]
            else:
                db_matches = [
                    s for s in db_sessions
                    if (s.get("id", "").startswith(thread_id_prefix) or s.get("id", "")[:32] == thread_id_prefix)
                ]
                if len(db_matches) > 1:
                    await query.answer("⚠️ 旧按钮已过期，请重新运行 /list", show_alert=True)
                    return

            if len(db_matches) > 1:
                await query.answer("❌ thread 标识冲突，请重新 /list", show_alert=True)
                return

            matched = db_matches[0] if db_matches else None

            if not matched:
                fallback_threads = local_fallback_threads or []
                if thread_token:
                    fallback_matches = [
                        s for s in fallback_threads
                        if _make_thread_open_token(s.get("id", "")) == thread_token
                    ]
                else:
                    fallback_matches = [
                        s for s in fallback_threads
                        if (s.get("id", "").startswith(thread_id_prefix) or s.get("id", "")[:32] == thread_id_prefix)
                    ]
                    if len(fallback_matches) > 1:
                        await query.answer("⚠️ 旧按钮已过期，请重新运行 /list", show_alert=True)
                        return
                if len(fallback_matches) > 1:
                    await query.answer("❌ thread 标识冲突，请重新 /list", show_alert=True)
                    return
                if fallback_matches:
                    matched = fallback_matches[0]

            if matched:
                sid = matched.get("id", "")
                full_tid = sid
                thread_info = ThreadInfo(
                    thread_id=sid,
                    topic_id=None,
                    preview=matched.get("preview"),
                    archived=False,
                    is_active=True,
                    source="imported" if ws_info.tool == "claude" else "unknown",
                )
                ws_info.threads[sid] = thread_info
                if storage:
                    save_storage(storage)

        if not thread_info:
            await query.answer("❌ Thread 未找到", show_alert=True)
            return

        # 创建前刷新 preview，避免使用 state.json 中过期的缓存名称。
        previous_preview = thread_info.preview
        preview_changed = False
        try:
            latest_preview = None
            db_threads = list_provider_threads(ws_info.tool, ws_info.path, limit=100)
            local_threads = local_fallback_threads or _list_provider_local_threads(ws_info.tool, ws_info.path, limit=100)

            for item in db_threads:
                if item.get("id") == full_tid:
                    latest_preview = item.get("preview") or item.get("title") or None
                    break
            if not latest_preview:
                for item in local_threads:
                    if item.get("id") == full_tid:
                        latest_preview = item.get("preview") or item.get("title") or None
                        break
            if latest_preview and latest_preview != thread_info.preview:
                thread_info.preview = latest_preview
                preview_changed = True
        except Exception as e:
            logger.debug(f"[thread_open] 刷新 preview 失败，继续使用缓存值：{e}")
        if preview_changed and storage:
            save_storage(storage)

        if thread_info.archived:
            revived = clear_stale_thread_archive_if_active(state, ws_info, thread_info)
            if revived and storage:
                save_storage(storage)
            if thread_info.archived:
                await query.answer("⚠️ 该 thread 已归档，请重新 /list 或新建 thread", show_alert=True)
                return

        # 并发保护：同一 thread 同时只允许一个创建/验证流程
        if full_tid in _creating_topics:
            await query.answer("⏳ 正在处理中，请稍候", show_alert=False)
            return
        _creating_topics.add(full_tid)

        try:
            bot = query.get_bot()
            if thread_info.topic_id is not None:
                old_topic_id = thread_info.topic_id
                # 直接发消息验证 topic 是否存在
                try:
                    await _send_to_group(
                        bot, group_chat_id,
                        f"thread `{full_tid[-8:]}` ✅ 已存在，跳转中。",
                        topic_id=thread_info.topic_id,
                        parse_mode="Markdown",
                    )
                    if preview_changed and thread_info.topic_id is not None:
                        topic_name = _make_thread_topic_name(
                            ws_info.tool,
                            ws_info.name,
                            thread_info.preview,
                            full_tid,
                        )
                        await bot.edit_forum_topic(
                            chat_id=group_chat_id,
                            message_thread_id=thread_info.topic_id,
                            name=topic_name,
                        )
                        logger.info(
                            "[thread_open] 已同步重命名 topic %s: %r -> %r",
                            thread_info.topic_id,
                            previous_preview,
                            thread_info.preview,
                        )
                    if ws_info.tool == "claude":
                        await _sync_existing_claude_thread_history(
                            bot=bot,
                            group_chat_id=group_chat_id,
                            topic_id=thread_info.topic_id,
                            thread_info=thread_info,
                            thread_id=full_tid,
                            storage=storage,
                        )
                    await send_thread_control_panel(
                        state,
                        bot,
                        group_chat_id,
                        ws_info,
                        thread_info,
                        intro=f"thread `{full_tid[-8:]}` 已就绪，继续对话或使用下方按钮。",
                        topic_id=thread_info.topic_id,
                    )
                    await query.answer(f"已有 Topic {old_topic_id}", show_alert=False)
                    return
                except TopicNotFoundError:
                    # topic 已被删除，清掉旧 topic_id，继续走下面的创建流程
                    logger.info(f"thread {full_tid[:8]}… 的 topic {thread_info.topic_id} 已不存在，将重建")
                    await _send_to_group(
                        bot, group_chat_id,
                        f"⚠️ thread {full_tid[-8:]} 旧 topic id={old_topic_id} 已失效，重建中…",
                        topic_id=ws_info.topic_id,
                    )
                    thread_info.topic_id = None
                    if storage:
                        save_storage(storage)

            # Create the topic
            tool_name = ws_info.tool
            topic_name = _make_thread_topic_name(
                tool_name,
                ws_info.name,
                thread_info.preview,
                full_tid,
            )

            try:
                topic = await bot.create_forum_topic(chat_id=group_chat_id, name=topic_name)
                thread_info.topic_id = topic.message_thread_id
                if storage:
                    save_storage(storage)
                logger.info(f"[on-demand] thread {full_tid[:8]}… → Topic {thread_info.topic_id}")

                await query.answer("✅ Topic 已创建")
                await _send_to_group(
                    bot, group_chat_id,
                    f"✅ thread {full_tid[-8:]} 新建 topic id={thread_info.topic_id}",
                    topic_id=ws_info.topic_id,
                )

                # Replay history
                replay_cursor = await _replay_thread_history(
                    bot=bot,
                    group_chat_id=group_chat_id,
                    topic_id=thread_info.topic_id,
                    thread_id=full_tid,
                    sessions_dir=None,
                    tool_name=tool_name,
                )
                if replay_cursor and thread_info.history_sync_cursor != replay_cursor:
                    thread_info.history_sync_cursor = replay_cursor
                    if storage:
                        save_storage(storage)
                await send_thread_control_panel(
                    state,
                    bot,
                    group_chat_id,
                    ws_info,
                    thread_info,
                    intro=f"thread `{full_tid[-8:]}` 已打开，继续对话或使用下方按钮。",
                    topic_id=thread_info.topic_id,
                )
            except Exception as e:
                logger.warning(f"[on-demand] 创建 Topic 失败：{e}")
                await query.answer(f"❌ 创建失败：{e}", show_alert=True)
        finally:
            _creating_topics.discard(full_tid)

    return CallbackQueryHandler(callback, pattern=r"^thread_open")


async def _open_workspace(
    bot,
    state: AppState,
    storage,
    group_chat_id: int,
    tool_cfg,
    name: str,
    path: str,
) -> WorkspaceInfo:
    """
    打开 workspace 并初始化：
    1. 生成合成 workspace_id，注册 adapter cwd 映射
    2. 创建 workspace 管理 Topic（名为 "[tool] ws_name"）
    3. 同步最新 N 个 thread（adapter 优先，无数据时从 sessions 扫描）
    4. 为每个 thread 建 Topic（名为 "[tool/ws_name] preview"）
    5. 回放每个 thread 最近 10 条历史消息到对应 Topic
    返回 WorkspaceInfo。
    """
    tool_name = tool_cfg.name
    unavailable = _provider_unavailable_message(state, tool_name)
    if unavailable:
        raise RuntimeError(unavailable)

    # 1. 合成 workspace_id（前缀区分工具类型，供 get_adapter_for_workspace 路由）
    ws_id = f"{tool_name}:{name}"

    # 2. 创建 workspace 管理 Topic，名为 "[tool] ws_name"
    ws_topic_name = f"[{tool_name}] {name}"[:128]
    topic = await bot.create_forum_topic(chat_id=group_chat_id, name=ws_topic_name)
    topic_id = topic.message_thread_id

    # 3. 保存到 storage — 如果已有 WorkspaceInfo 则复用（保留 thread 映射），只更新 topic_id
    storage_key = f"{tool_name}:{name}"
    if storage and storage_key in storage.workspaces:
        ws_info = storage.workspaces[storage_key]
        ws_info.topic_id = topic_id
        ws_info.daemon_workspace_id = ws_id
        # 不清 threads，保留已有的 topic_id 映射
    else:
        ws_info = WorkspaceInfo(
            name=name,
            path=path,
            tool=tool_name,
            topic_id=topic_id,
            daemon_workspace_id=ws_id,
        )
    if storage:
        storage.workspaces[storage_key] = ws_info
        if storage.active_workspace is None:
            storage.active_workspace = storage_key
        save_storage(storage)

    # 4. 注册 adapter cwd 映射 + 同步 thread
    threads_from_server: list[dict] = []
    active_adapter = state.get_adapter_for_workspace(ws_id)
    if active_adapter and active_adapter.connected:
        # 注册 workspace cwd 映射
        active_adapter.register_workspace_cwd(ws_id, path)

        try:
            server_threads = await active_adapter.list_threads(ws_id, limit=_THREAD_SYNC_LIMIT * 3)
            threads_from_server = _normalize_provider_server_threads(
                tool_name,
                server_threads,
                limit=_THREAD_SYNC_LIMIT,
            )
        except Exception as e:
            logger.warning(f"从 {tool_name} 获取 thread 列表失败：{e}")

        try:
            await _notify_provider_workspace_opened(tool_name, active_adapter, path, ws_id)
        except Exception as e:
            logger.warning(f"{tool_name} workspace open hook 失败：{e}")
    else:
        logger.warning(f"{tool_name} 未连接，跳过 thread 同步")

    # 若 adapter 没有返回 thread，则回退到 provider 本地事实源
    if not threads_from_server:
        threads_from_server = list_provider_threads(tool_name, path, limit=_THREAD_SYNC_LIMIT)
        if threads_from_server:
            logger.info(
                f"从 {tool_name} 本地事实源扫描到 {len(threads_from_server)} 个 thread（workspace={name}）"
            )
        else:
            threads_from_server = _list_provider_local_threads(tool_name, path, limit=_THREAD_SYNC_LIMIT)
            if threads_from_server:
                logger.info(f"从 {tool_name} 本地 fallback 扫描到 {len(threads_from_server)} 个 thread（workspace={name}）")

    # 注册 ThreadInfo
    needs_save = False
    for dt in threads_from_server:
        tid = dt.get("id", "")
        if not tid or tid in ws_info.threads:
            continue
        preview = dt.get("preview") or dt.get("title") or None
        ws_info.threads[tid] = ThreadInfo(
            thread_id=tid,
            topic_id=None,
            preview=preview,
            archived=False,
            source="imported",
        )
        needs_save = True

    active_ids = query_provider_active_thread_ids(tool_name, path)
    if needs_save and storage:
        save_storage(storage)
    _active_ids, _changed = reconcile_workspace_threads_with_source(
        state,
        ws_info,
        active_ids=active_ids,
    )

    # 5b. Topics are created on-demand (when user clicks thread button)
    # Removed automatic batch creation to avoid overwhelming the group with topics
    # for tid, tinfo in ws_info.threads.items():
    #     if tinfo.topic_id is not None or tinfo.archived:
    #         continue
    #     if not tinfo.is_active:
    #         continue
    #     try:
    #         prefix = f"[{tool_name}/{name}] "
    #         body = tinfo.preview if tinfo.preview else f"thread-{tid[-8:]}"
    #         tname = (prefix + body)[:128]
    #         t_topic = await bot.create_forum_topic(chat_id=group_chat_id, name=tname)
    #         tinfo.topic_id = t_topic.message_thread_id
    #         logger.info(f"thread {tid[:8]}… → Topic {tinfo.topic_id}")
    #         if storage:
    #             save_storage(storage)
    #     except Exception as e:
    #         logger.warning(f"为 thread {tid[:8]}… 建 Topic 失败：{e}")

    # 5c. Send overview message to workspace topic
    await _send_workspace_thread_overview(
        state,
        bot,
        group_chat_id,
        ws_info,
        tool_name,
        active_ids=active_ids,
    )

    return ws_info


async def _send_workspace_thread_overview(
    state: AppState,
    bot, group_chat_id: int, ws_info: WorkspaceInfo, tool_name: str,
    *,
    active_ids: Optional[set[str]] = None,
) -> None:
    """发送 workspace 的 thread 概览 + 按钮到 workspace topic。"""
    name = ws_info.name
    ws_id = ws_info.daemon_workspace_id or f"{tool_name}:{name}"
    topic_id = ws_info.topic_id

    reconcile_workspace_threads_with_source(state, ws_info, active_ids=active_ids)

    display_threads: list[dict] = []
    if tool_name == "claude":
        archived_ids = {
            tid
            for tid, tinfo in ws_info.threads.items()
            if getattr(tinfo, "archived", False)
        }
        for session in list_provider_threads(tool_name, ws_info.path, limit=100):
            tid = str(session.get("id") or "")
            if not tid or tid in archived_ids:
                continue
            thread_info = ws_info.threads.get(tid)
            display_threads.append(
                {
                    "id": tid,
                    "preview": session.get("preview") or session.get("title") or getattr(thread_info, "preview", None),
                    "topic_id": getattr(thread_info, "topic_id", None),
                    "is_active": tid in (active_ids or set()),
                }
            )
    else:
        for tid, thread_info in ws_info.threads.items():
            if thread_info.archived:
                continue
            display_threads.append(
                {
                    "id": tid,
                    "preview": thread_info.preview,
                    "topic_id": thread_info.topic_id,
                    "is_active": thread_info.is_active,
                }
            )

    active_threads = [item for item in display_threads if item["is_active"]]
    inactive_threads = [item for item in display_threads if not item["is_active"]]

    lines = [f"📂 [{tool_name}] {name}\n"]

    if active_threads:
        lines.append(f"Active ({len(active_threads)}):")
        for item in active_threads[:20]:
            tid = item["id"]
            label = item["preview"] or f"thread-{tid[-8:]}"
            status = "✅" if item["topic_id"] else "▸"
            lines.append(f"  {status} {label}")

    if inactive_threads:
        shown = inactive_threads[:10]
        remaining = len(inactive_threads) - len(shown)
        lines.append(f"\nInactive ({len(inactive_threads)}):")
        for item in shown:
            tid = item["id"]
            label = item["preview"] or f"thread-{tid[-8:]}"
            lines.append(f"  ▹ {label}")
        if remaining > 0:
            lines.append(f"  ... (+{remaining} more)")

    overview_text = "\n".join(lines)

    # 所有非归档 thread 都生成按钮（已有 topic 的点击后会验证而非重建）
    buttons = []
    for item in display_threads:
        tid = item["id"]
        label = item["preview"] or f"thread-{tid[-8:]}"
        icon = "✅" if item["topic_id"] else "📌"
        label = f"{icon} {label}"[:40]
        buttons.append([InlineKeyboardButton(
            label,
            callback_data=make_thread_open_callback_data(ws_id, tid)
        )])
        if len(buttons) >= 20:
            break

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    try:
        await _send_to_group(
            bot, group_chat_id,
            overview_text,
            topic_id=topic_id,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.warning(f"发送 workspace 概览消息失败：{e}")


async def _replay_thread_history(
    bot,
    group_chat_id: int,
    topic_id: int,
    thread_id: str,
    sessions_dir: Optional[str],
    limit: int = 10,
    tool_name: str = "",
) -> Optional[str]:
    """
    读取 thread 的历史对话并发送到 Telegram Topic（作为历史回放）。
    每条消息格式：
      用户消息：👤 <text>
      AI 回复：🤖 <text>（截断到 3000 字符）

    具体历史来源由 provider facts 决定。
    """
    try:
        history = read_provider_thread_history(
            tool_name,
            thread_id,
            limit=limit,
            sessions_dir=sessions_dir,
        )
    except Exception as e:
        logger.warning(f"读取 thread {thread_id[:8]}… 历史失败：{e}")
        return None

    if not history:
        return None

    # 发一条提示头
    try:
        await _send_to_group(
            bot, group_chat_id,
            f"📜 历史记录（最近 {len(history)} 条）：",
            topic_id=topic_id,
        )
    except Exception as e:
        logger.warning(f"发送历史头到 Topic {topic_id} 失败：{e}")
        return None

    # 每条单独发一条消息
    for turn in history:
        msg = _format_history_turn_message(turn)
        if not msg:
            continue
        try:
            await _send_to_group(bot, group_chat_id, msg, topic_id=topic_id)
        except Exception as e:
            logger.warning(f"发送历史消息到 Topic {topic_id} 失败：{e}")
    return _history_turn_signature(history[-1])


def make_cli_handler(state: AppState, group_chat_id: int, cfg: Config):
    """
    /cli 命令：在 General topic 列出所有工具，显示其全局 topic 状态，提供创建/重建按钮。
    
    功能：
    1. 列出所有已启用的 provider（如 codex、claude、overlay provider 等）
    2. 显示每个工具的全局 topic 状态（已创建 ✅ / 未创建 ⚠️）
    3. 提供按钮创建/重建工具的全局 topic
    """
    async def cli(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        storage = state.storage
        # 回复到命令所在的 topic（通常是 General topic）
        src_topic_id = update.effective_message.message_thread_id if update.effective_message else None
        
        if not cfg.enabled_tools:
            await _send_to_group(context.bot, group_chat_id, "❌ 没有启用任何工具", topic_id=src_topic_id)
            return
        
        # 检查每个工具的全局 topic 状态
        lines = ["🔧 *工具管理*\n"]
        keyboard = []
        
        for tool in cfg.enabled_tools:
            tool_name = tool.name
            # 查找该工具的全局 topic（从 global_topic_ids 中查找）
            global_topic_id = None
            if storage and storage.global_topic_ids:
                global_topic_id = storage.global_topic_ids.get(tool_name)
            
            if global_topic_id:
                status = "✅ 已创建"
                callback_data = f"cli_recreate:{tool_name}"
                button_label = f"🔄 重建 {tool_name}"
            else:
                status = "⚠️ 未创建"
                callback_data = f"cli_create:{tool_name}"
                button_label = f"➕ 创建 {tool_name}"
            
            lines.append(f"• *{tool_name}*: {status}")
            keyboard.append([InlineKeyboardButton(button_label, callback_data=callback_data)])
        
        text = "\n".join(lines)
        await _send_to_group(
            context.bot, group_chat_id,
            text,
            topic_id=src_topic_id,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    return cli


def make_cli_callback_handler(state: AppState, group_chat_id: int, cfg: Config) -> CallbackQueryHandler:
    """
    处理 cli_create:<tool> 和 cli_recreate:<tool> callback：
    创建或重建工具的全局 topic
    """
    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None:
            return
        
        data = query.data or ""
        await query.answer()
        
        if not (data.startswith("cli_create:") or data.startswith("cli_recreate:")):
            return
        
        parts = data.split(":", 1)
        if len(parts) != 2:
            await query.answer("❌ 参数解析失败", show_alert=True)
            return
        
        action = parts[0]  # cli_create 或 cli_recreate
        tool_name = parts[1]
        
        # 查找工具配置
        tool_cfg = None
        for t in cfg.enabled_tools:
            if t.name == tool_name:
                tool_cfg = t
                break
        
        if not tool_cfg:
            await query.answer(f"❌ 工具 {tool_name} 未启用", show_alert=True)
            return
        
        storage = state.storage
        if not storage:
            await query.answer("❌ Storage 未初始化", show_alert=True)
            return
        
        bot = query.get_bot()
        
        # 如果是重建，先检查是否已存在
        existing_topic_id = storage.global_topic_ids.get(tool_name) if storage.global_topic_ids else None
        
        if action == "cli_recreate:" and not existing_topic_id:
            await query.answer(f"⚠️ {tool_name} topic 不存在，将创建新的", show_alert=False)
        
        try:
            # 创建工具的全局 topic
            topic_name = tool_name
            topic = await bot.create_forum_topic(chat_id=group_chat_id, name=topic_name)
            new_topic_id = topic.message_thread_id
            
            # 更新 storage (global_topic_ids 是 tool_name -> topic_id)
            storage.global_topic_ids[tool_name] = new_topic_id
            save_storage(storage)
            
            action_text = "重建" if action == "cli_recreate:" else "创建"
            logger.info(f"[cli] {action_text}工具全局 topic: {tool_name} → {new_topic_id}")
            
            await query.answer(f"✅ {tool_name} topic 已{action_text}", show_alert=False)
            
            # 发送欢迎消息到新 topic
            welcome_msg = f"🔧 *{tool_name}* 工具已启动\n\n使用 `/workspace` 列出并打开工作目录"
            await _send_to_group(
                bot, group_chat_id,
                welcome_msg,
                topic_id=new_topic_id,
                parse_mode="Markdown",
            )
            
        except Exception as e:
            logger.error(f"[cli] 创建/重建 {tool_name} topic 失败：{e}")
            await query.answer(f"❌ 操作失败：{e}", show_alert=True)
    
    return CallbackQueryHandler(callback, pattern=r"^cli_(create|recreate):")

    logger.info(f"thread {thread_id[:8]}… 历史回放完成（{len(history)} 条）")
