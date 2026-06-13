from __future__ import annotations

import inspect
import logging

from core.providers.interactions import (
    ProviderApprovalRequest,
    parse_standard_question_request,
)
from core.providers.interaction_runtime import reply_question_via_adapter
from core.providers.lifecycle_runtime import (
    _save_storage_via_lifecycle,
    _sync_provider_threads_from_facts,
    resolve_default_reconnect_topic_id,
)
from core.providers.message_runtime import send_default_message
from core.providers.thread_runtime import (
    activate_default_new_thread,
    archive_default_thread,
    interrupt_default_thread,
    resolve_default_thread_adapter,
)
from core.providers.workspace_runtime import default_normalize_server_threads
from plugins.providers.builtin.claude.python.adapter import (
    ClaudeAdapter,
    format_claude_unavailable_message,
    should_block_claude_send_for_readiness,
)
from plugins.providers.builtin.claude.python.storage_runtime import infer_claude_thread_source_from_logs

logger = logging.getLogger(__name__)


def _list_value(value) -> list:
    return value if isinstance(value, list) else []


def _format_external_hook_status_line(status: dict | None) -> str:
    data = status if isinstance(status, dict) else {}
    state = str(data.get("state") or "").strip()
    detail = str(data.get("detail") or "").strip()
    if state == "installed":
        return "• Claude hook ingress：✅ 已安装"
    if state == "install_failed":
        suffix = f"：{detail}" if detail else ""
        return f"• Claude hook ingress：⚠️ 安装失败{suffix}"
    if state == "callback_unreachable":
        suffix = f"：{detail}" if detail else ""
        return f"• Claude hook ingress：⚠️ 回调不可用{suffix}"
    if state == "degraded_fallback":
        suffix = f"：{detail}" if detail else ""
        return f"• Claude hook ingress：⚠️ 已退化{suffix}"
    return ""


def parse_approval_request(
    payload: dict | None,
    *,
    request_id=None,
    provider_id: str = "claude",
    default_thread_id: str | None = None,
    approval_source: str = "app_server",
) -> ProviderApprovalRequest:
    data = payload if isinstance(payload, dict) else {}
    thread_id = str(data.get("threadId") or data.get("thread_id") or default_thread_id or "").strip()
    return ProviderApprovalRequest(
        request_id=data.get("request_id") or data.get("requestId") or request_id,
        thread_id=thread_id or None,
        command=str(data.get("command") or ""),
        reason=str(data.get("reason") or data.get("justification") or ""),
        tool_name=str(data.get("toolName") or data.get("tool_name") or "").strip(),
        proposed_amendment=_list_value(data.get("proposedExecpolicyAmendment")),
        amendment_decision={},
        tool_type=str(data.get("_provider") or provider_id or "").strip(),
        always_patterns=_list_value(data.get("_always_patterns")),
        approval_source=approval_source,
    )


def parse_question_request(
    payload: dict | None,
    *,
    provider_id: str = "claude",
    default_thread_id: str | None = None,
    question_source: str = "app_server",
):
    return parse_standard_question_request(
        payload,
        provider_id=provider_id,
        default_thread_id=default_thread_id,
        question_source=question_source,
    )


def should_materialize_unbound_thread_topic(state, ws_info, thread_info) -> bool:
    # App/Session Tab-created Claude sessions stay inside the desktop app until
    # a TG topic is explicitly bound.
    return _thread_topic_id(state, ws_info, thread_info) is not None


def _thread_topic_id(state, ws_info, thread_info) -> int | None:
    workspace_id = state.get_workspace_storage_key(ws_info) or ws_info.daemon_workspace_id or f"{ws_info.tool}:{ws_info.name}"
    return state.get_thread_topic_id(workspace_id, ws_info, thread_info)


def new_imported_thread_source() -> str:
    return "imported"


def build_approval_reply(approval, action: str) -> tuple[str, dict]:
    if action == "exec_deny":
        return "❌ 已拒绝", {"behavior": "deny"}

    if action == "exec_allow_always":
        return "✅ 已总是允许", {"behavior": "allow", "scope": "session"}

    return "✅ 已允许", {"behavior": "allow"}


async def _refresh_inferred_thread_source(state, ws_info, thread_info) -> None:
    if ws_info.tool != "claude":
        return

    thread_source = str(getattr(thread_info, "source", "") or "unknown").strip().lower()
    if thread_source != "unknown":
        return

    topic_id = _thread_topic_id(state, ws_info, thread_info)
    inferred_source = infer_claude_thread_source_from_logs(
        thread_info.thread_id,
        topic_id,
    )
    if inferred_source != "unknown":
        thread_info.source = inferred_source
        logger.info(
            "[provider-message] 已根据历史日志识别 claude thread 来源 "
            "thread=%s source=%s topic=%s",
            thread_info.thread_id[:8],
            inferred_source,
            topic_id,
        )


async def _reject_if_external_thread_busy(adapter, thread_id: str) -> None:
    inspect_thread_activity = getattr(adapter, "inspect_thread_activity", None)
    if not callable(inspect_thread_activity):
        return

    activity = await inspect_thread_activity(thread_id)
    if not isinstance(activity, dict) or not activity.get("busy"):
        return

    message = str(activity.get("message") or "").strip()
    if not message:
        message = "当前 Claude session 正在本地执行，请等待结束或显式 fork。"
    raise RuntimeError(message)


async def _reject_if_claude_not_ready(adapter) -> None:
    check_readiness = getattr(adapter, "check_readiness", None)
    if not callable(check_readiness):
        return

    readiness_result = check_readiness(force=True)
    readiness = await readiness_result if inspect.isawaitable(readiness_result) else readiness_result
    if should_block_claude_send_for_readiness(readiness):
        raise RuntimeError(format_claude_unavailable_message(readiness))


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
    attachments=None,
) -> bool:
    workspace_id = ws_info.daemon_workspace_id
    active_turn = state.streaming_turns.get(thread_info.thread_id)
    has_active_owned_turn = bool(
        active_turn is not None and active_turn.turn_id and not active_turn.completed
    )

    if not has_active_owned_turn:
        await _refresh_inferred_thread_source(state, ws_info, thread_info)
        await _reject_if_external_thread_busy(adapter, thread_info.thread_id)
    await _reject_if_claude_not_ready(adapter)
    await adapter.resume_thread(workspace_id, thread_info.thread_id)
    return True


async def start_runtime(manager, bot, tool_cfg) -> None:
    """Start Claude local adapter backed by the provider-owned CLI runtime."""
    configured_claude_bin = str(tool_cfg.codex_bin or "claude").strip() or "claude"
    configured_auth = getattr(tool_cfg, "auth", None) or None
    launch_methods = getattr(tool_cfg, "launch_methods", None) or None
    if launch_methods:
        adapter = ClaudeAdapter(
            claude_bin=configured_claude_bin,
            auth=configured_auth,
            launch_methods=launch_methods,
        )
    else:
        adapter = ClaudeAdapter(claude_bin=configured_claude_bin, auth=configured_auth)
    await adapter.connect()
    data_dir = manager.state.config.data_dir if manager.state.config is not None else None
    if data_dir:
        adapter.configure_hook_bridge(data_dir)
        start_hook_bridge = getattr(adapter, "start_hook_bridge", None)
        if callable(start_hook_bridge):
            result = start_hook_bridge(data_dir)
            if inspect.isawaitable(result):
                await result
        install_external_hook_ingress = getattr(adapter, "install_external_hook_ingress", None)
        if callable(install_external_hook_ingress):
            result = install_external_hook_ingress()
            if inspect.isawaitable(result):
                await result
    else:
        logger.info("[claude] 缺少 data_dir，跳过 hook bridge 配置")
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
            topic_id = _thread_topic_id(manager.state, ws_info, thread_info)
            if thread_info.archived or topic_id is None:
                continue
            if not thread_info.is_active:
                continue

            try:
                synced = await _sync_existing_claude_thread_history(
                    bot=bot,
                    group_chat_id=manager.gid,
                    topic_id=topic_id,
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
                    topic_id,
                )
                manager.state.invalidate_telegram_topic(topic_id)
                thread_info.topic_id = None
                state_changed = True
            except Exception as e:
                logger.warning(
                    "[claude-startup-sync] 同步失败：ws=%s tid=%s topic=%s err=%s",
                    ws_name,
                    thread_id[:12],
                    topic_id,
                    e,
                )

    if state_changed:
        save_storage(manager.storage)
    if synced_count > 0:
        logger.info("[claude-startup-sync] 已补齐 %s 个 Claude topic", synced_count)
    else:
        logger.info("[claude-startup-sync] 无需补齐 Claude topic")


async def build_status_lines(state) -> list[str]:
    adapter = state.get_adapter("claude")
    if adapter is not None and adapter.connected:
        lines: list[str]
        readiness = getattr(adapter, "readiness", None)
        if isinstance(readiness, dict) and readiness.get("ready") is False:
            detail = str(readiness.get("detail") or "").strip()
            suffix = f"：{detail}" if detail else ""
            lines = [f"• claude CLI：⚠️ 已连接，但不可用{suffix}"]
        elif getattr(adapter, "auth_ready", None) is False:
            lines = ["• claude CLI：⚠️ 已连接，但不可用：Claude CLI is not logged in."]
        else:
            lines = ["• claude CLI：✅ 已连接"]
        hook_line = _format_external_hook_status_line(
            getattr(adapter, "external_hook_status", None)
        )
        if hook_line:
            lines.append(hook_line)
        return lines
    if adapter is not None:
        return ["• claude CLI：❌ 已断开"]
    return []
