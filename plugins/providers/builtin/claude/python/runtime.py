from __future__ import annotations

import logging
from dataclasses import replace

from core.providers.interaction_runtime import reply_question_via_adapter
from core.providers.lifecycle_runtime import (
    _save_storage_via_lifecycle,
    _sync_provider_threads_from_facts,
    resolve_default_reconnect_topic_id,
)
from core.providers.message_runtime import _interrupt_active_turn, send_default_message
from core.providers.thread_runtime import (
    activate_default_new_thread,
    archive_default_thread,
    interrupt_default_thread,
    resolve_default_thread_adapter,
)
from core.providers.workspace_runtime import default_normalize_server_threads
from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter, resolve_claude_bin
from plugins.providers.builtin.claude.python.storage_runtime import infer_claude_thread_source_from_logs

logger = logging.getLogger(__name__)


def _extract_started_thread_id(result: object) -> str:
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError(f"Claude start_thread 返回无效 thread id：{result}")
    return str(thread_id)


def build_approval_reply(approval, action: str) -> tuple[str, dict]:
    if action == "exec_deny":
        return "❌ 已拒绝", {"behavior": "deny"}

    if action == "exec_allow_always":
        return "✅ 已总是允许", {"behavior": "allow", "scope": "session"}

    return "✅ 已允许", {"behavior": "allow"}


async def _maybe_remap_imported_thread(state, adapter, ws_info, thread_info):
    if ws_info.tool != "claude":
        return thread_info

    thread_source = str(getattr(thread_info, "source", "") or "unknown").strip().lower()
    if thread_source == "unknown":
        inferred_source = infer_claude_thread_source_from_logs(
            thread_info.thread_id,
            thread_info.topic_id,
        )
        if inferred_source != "unknown":
            thread_info.source = inferred_source
            thread_source = inferred_source
            logger.info(
                "[provider-message] 已根据历史日志识别 claude thread 来源 "
                "thread=%s source=%s topic=%s",
                thread_info.thread_id[:8],
                inferred_source,
                thread_info.topic_id,
            )

    return thread_info


async def _detach_imported_thread_for_app_send(adapter, ws_info, thread_info):
    """Move a TG topic from an imported history session to a fresh app-owned session."""
    workspace_id = ws_info.daemon_workspace_id
    old_thread_id = thread_info.thread_id
    old_topic_id = thread_info.topic_id

    result = await adapter.start_thread(workspace_id)
    new_thread_id = _extract_started_thread_id(result)
    if new_thread_id == old_thread_id:
        raise RuntimeError("Claude start_thread 返回了与 imported thread 相同的 thread id")

    imported_record = replace(
        thread_info,
        thread_id=old_thread_id,
        topic_id=None,
        streaming_msg_id=None,
        last_tg_user_message_id=None,
    )
    ws_info.threads[old_thread_id] = imported_record

    thread_info.thread_id = new_thread_id
    thread_info.topic_id = old_topic_id
    thread_info.source = "app"
    thread_info.is_active = True
    thread_info.streaming_msg_id = None
    thread_info.history_sync_cursor = None
    thread_info.last_tg_user_message_id = None
    ws_info.threads[new_thread_id] = thread_info

    logger.info(
        "[provider-message] claude imported thread 已拆分为 app session "
        "old=%s new=%s topic=%s",
        old_thread_id[:8],
        new_thread_id[:8],
        old_topic_id,
    )
    return thread_info


async def prepare_send(
    state,
    adapter,
    ws_info,
    thread_info,
    *,
    update,
    context,
    group_chat_id: int,
    src_topic_id,
    text,
    has_photo: bool,
) -> bool:
    workspace_id = ws_info.daemon_workspace_id
    active_turn = state.streaming_turns.get(thread_info.thread_id)
    has_active_owned_turn = bool(
        active_turn is not None and active_turn.turn_id and not active_turn.completed
    )
    await _interrupt_active_turn(
        state,
        adapter,
        workspace_id,
        thread_info.thread_id,
        label="claude",
    )

    if not has_active_owned_turn:
        thread_info = await _maybe_remap_imported_thread(
            state,
            adapter,
            ws_info,
            thread_info,
        )
        thread_source = str(getattr(thread_info, "source", "") or "unknown").strip().lower()
        if thread_source == "imported":
            thread_info = await _detach_imported_thread_for_app_send(
                adapter,
                ws_info,
                thread_info,
            )
    await adapter.resume_thread(workspace_id, thread_info.thread_id)
    return True


async def start_runtime(manager, bot, tool_cfg) -> None:
    """Start Claude local adapter backed by the provider-owned CLI runtime."""
    resolved_claude_bin = resolve_claude_bin(tool_cfg.codex_bin)
    if resolved_claude_bin != tool_cfg.codex_bin:
        logger.info(
            "[claude] 运行时二进制已解析：configured=%s resolved=%s",
            tool_cfg.codex_bin,
            resolved_claude_bin,
        )
    adapter = ClaudeAdapter(claude_bin=resolved_claude_bin)
    await adapter.connect()
    data_dir = manager.state.config.data_dir if manager.state.config is not None else None
    if data_dir:
        await adapter.start_hook_bridge(data_dir)
    else:
        logger.info("[claude] 缺少 data_dir，跳过 hook bridge 启动")
    await adapter.refresh_auth_status()
    manager.state.set_adapter("claude", adapter)
    await setup_connection(manager, bot, adapter)


async def shutdown_runtime(manager) -> None:
    claude = manager.state.get_adapter("claude")
    if claude is not None and hasattr(claude, "disconnect"):
        await claude.disconnect()


async def setup_connection(manager, bot, adapter, **kwargs) -> None:
    from bot.handlers.common import reconcile_workspace_threads_with_source
    from bot.events import make_event_handler, make_server_request_handler

    adapter.on_event(make_event_handler(manager.state, bot, manager.gid))
    adapter.on_server_request(make_server_request_handler(manager.state, bot, manager.gid))

    for ws_name, ws_info in manager.storage.workspaces.items():
        if ws_info.tool != "claude" or not ws_info.daemon_workspace_id:
            continue

        adapter.register_workspace_cwd(ws_info.daemon_workspace_id, ws_info.path)
        logger.info("[claude] workspace cwd 已注册：%s", ws_name)

        try:
            needs_save = _sync_provider_threads_from_facts(
                manager,
                "claude",
                ws_info,
                limit=20,
                log_prefix="[claude]",
                source_for_new="imported",
            )
            _active_ids, changed = reconcile_workspace_threads_with_source(
                manager.state,
                ws_info,
                persist=False,
            )
            needs_save = needs_save or changed
            if needs_save:
                _save_storage_via_lifecycle(manager)
        except Exception as e:
                logger.warning("[claude] 补同步 thread 失败：%s", e)


async def sync_existing_topics_after_startup(manager, bot) -> None:
    """启动后为已映射的 Claude topic 自动补齐当前会话历史。"""
    from bot.handlers.common import reconcile_workspace_threads_with_source
    from bot.handlers.workspace import _sync_existing_claude_thread_history
    from bot.utils import TopicNotFoundError
    from core.providers.facts import query_provider_active_thread_ids
    from core.storage import save_storage

    synced_count = 0
    state_changed = False

    for ws_name, ws_info in manager.storage.workspaces.items():
        if ws_info.tool != "claude":
            continue

        try:
            active_ids = query_provider_active_thread_ids("claude", ws_info.path)
        except ValueError:
            logger.debug("[claude-startup-sync] 跳过未知 workspace：%s", ws_name)
            continue

        _, repaired = reconcile_workspace_threads_with_source(
            manager.state,
            ws_info,
            active_ids=active_ids,
            persist=False,
        )
        state_changed = state_changed or repaired

        for thread_id, thread_info in ws_info.threads.items():
            if thread_info.archived or thread_info.topic_id is None:
                continue
            if not thread_info.is_active:
                continue

            try:
                synced = await _sync_existing_claude_thread_history(
                    bot=bot,
                    group_chat_id=manager.gid,
                    topic_id=thread_info.topic_id,
                    thread_info=thread_info,
                    thread_id=thread_id,
                    storage=manager.storage,
                )
                if synced:
                    synced_count += 1
            except TopicNotFoundError:
                logger.warning(
                    "[claude-startup-sync] topic 已不存在，清理映射：ws=%s tid=%s topic=%s",
                    ws_name,
                    thread_id[:12],
                    thread_info.topic_id,
                )
                thread_info.topic_id = None
                state_changed = True
            except Exception as e:
                logger.warning(
                    "[claude-startup-sync] 同步失败：ws=%s tid=%s topic=%s err=%s",
                    ws_name,
                    thread_id[:12],
                    thread_info.topic_id,
                    e,
                )

    if state_changed:
        save_storage(manager.storage)
    if synced_count > 0:
        logger.info("[claude-startup-sync] 已补齐 %s 个 Claude topic", synced_count)
    else:
        logger.info("[claude-startup-sync] 无需补齐 Claude topic")


def build_status_lines(state) -> list[str]:
    adapter = state.get_adapter("claude")
    if adapter is not None and adapter.connected:
        if getattr(adapter, "auth_ready", None) is False:
            return ["• claude CLI：⚠️ 已连接，但未鉴权"]
        if getattr(adapter, "auth_method", "") in ("apiKeyEnv", "proxyEnv"):
            return ["• claude CLI：✅ 已连接（API/Proxy）"]
        return ["• claude CLI：✅ 已连接"]
    if adapter is not None:
        return ["• claude CLI：❌ 已断开"]
    return []
