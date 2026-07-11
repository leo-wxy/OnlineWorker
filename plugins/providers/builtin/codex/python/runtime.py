from __future__ import annotations

import asyncio
import logging
import os
import tomllib
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Optional

from config import get_data_dir
from core.telegram_formatting import format_telegram_assistant_final_text
from core.providers.lifecycle_runtime import _save_storage_via_lifecycle
from core.providers.message_runtime import _interrupt_active_turn
from core.providers.thread_runtime import interrupt_default_thread
from plugins.providers.builtin.codex.python.adapter import CodexAdapter
from plugins.providers.builtin.codex.python.approval_policy import (
    SOURCE_REMOTE_PROXY,
    SOURCE_TUI_HOST,
    is_app_server_approval_source,
)
from plugins.providers.builtin.codex.python.errors import is_codex_unmaterialized_error
from plugins.providers.builtin.codex.python.interactions import parse_approval_request
from plugins.providers.builtin.codex.python.process import AppServerProcess
from plugins.providers.builtin.codex.python.remote_proxy import ensure_codex_remote_message_proxy
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from plugins.providers.builtin.codex.python.semantic_events import (
    parse_codex_app_server_semantic_event,
)
from plugins.providers.builtin.codex.python import storage_runtime
from plugins.providers.builtin.codex.python.transport import (
    is_default_unix_endpoint,
    is_unix_endpoint,
    onlineworker_codex_unix_url,
    unix_socket_accepting,
)
from plugins.providers.builtin.codex.python.tui_host_protocol import (
    clear_stale_host_artifacts,
    read_host_status,
)

if TYPE_CHECKING:
    from core.state import AppState, PendingCommandWrapper
    from core.storage import ThreadInfo, WorkspaceInfo

logger = logging.getLogger(__name__)

CODEX_RECONNECT_GRACE_SECONDS = 3.0
CODEX_RECONNECT_POLL_SECONDS = 0.1
DEFAULT_REASONING_OPTIONS = ["minimal", "low", "medium", "high", "xhigh"]
CODEX_APP_SERVER_RESOLVED_METHOD = "serverRequest/resolved"
CODEX_CAPACITY_ABORT_REASON = "Selected model is at capacity. Please try a different model."
CODEX_CAPACITY_AUTO_CONTINUE_TEXT = "继续"
CODEX_CAPACITY_AUTO_CONTINUE_MAX_ATTEMPTS = 2
CODEX_CAPACITY_AUTO_CONTINUE_COOLDOWN_SECONDS = 60.0


def _thread_topic_id(state: "AppState", ws_info: "WorkspaceInfo", thread_info: "ThreadInfo") -> int | None:
    workspace_id = state.get_workspace_storage_key(ws_info) or ws_info.daemon_workspace_id or f"{ws_info.tool}:{ws_info.name}"
    return state.get_thread_topic_id(workspace_id, ws_info, thread_info)


def log_app_server_process_snapshot(
    proc: Optional[AppServerProcess],
    *,
    reason: str,
) -> None:
    if proc is None:
        return
    try:
        logger.warning("[app-server-process] %s %s", reason, proc.diagnostics_snapshot())
    except Exception as e:
        logger.debug("记录 app-server 进程诊断失败：%s", e)


def _request_key(value) -> str:
    return str(value or "").strip()


def _is_remote_proxy_mirror_for_request(
    approval,
    request_id: str,
    *,
    thread_id: str = "",
    command: str = "",
) -> bool:
    if str(getattr(approval, "approval_source", "") or "") != SOURCE_REMOTE_PROXY:
        return False
    proxy_request_id = _request_key(getattr(approval, "request_id", ""))
    if not proxy_request_id.rsplit(":", 1)[-1] == request_id:
        return False
    if not thread_id and not command:
        return False
    approval_thread_id = str(getattr(approval, "thread_id", "") or "").strip()
    if thread_id and approval_thread_id != thread_id:
        return False
    approval_command = str(getattr(approval, "cmd", "") or "").strip()
    if command and approval_command != command:
        return False
    return True


def _is_pending_codex_app_server_approval(
    approval,
    request_id: str,
    *,
    thread_id: str = "",
    command: str = "",
) -> bool:
    if str(getattr(approval, "tool_type", "") or "") != "codex":
        return False
    source = str(getattr(approval, "approval_source", "") or "")
    if source == SOURCE_REMOTE_PROXY:
        approval_request_id = _request_key(getattr(approval, "request_id", ""))
        if approval_request_id == request_id:
            if not thread_id and not command:
                return True
            approval_thread_id = str(getattr(approval, "thread_id", "") or "").strip()
            if thread_id and approval_thread_id != thread_id:
                return False
            approval_command = str(getattr(approval, "cmd", "") or "").strip()
            if command and approval_command != command:
                return False
            return True
        return _is_remote_proxy_mirror_for_request(
            approval,
            request_id,
            thread_id=thread_id,
            command=command,
        )
    if _request_key(getattr(approval, "request_id", "")) == request_id:
        return is_app_server_approval_source(source)
    return _is_remote_proxy_mirror_for_request(
        approval,
        request_id,
        thread_id=thread_id,
        command=command,
    )


def _approval_identity(params: dict, request_id) -> tuple[str, str]:
    if not isinstance(params, dict):
        return "", ""
    info = parse_approval_request(params, request_id=request_id, provider_id="codex")
    return str(info.thread_id or "").strip(), str(info.command or "").strip()


def has_pending_codex_app_server_approval(
    state: "AppState",
    request_id,
    params: dict | None = None,
) -> bool:
    request_key = _request_key(request_id)
    if not request_key:
        return False
    thread_id, command = _approval_identity(params or {}, request_id)
    for approval in state.pending_approvals.values():
        if _is_pending_codex_app_server_approval(
            approval,
            request_key,
            thread_id=thread_id,
            command=command,
        ):
            return True
    return False


async def handle_approval_callback(state, approval, action: str, query, msg_id: int) -> bool:
    request_id = _request_key(getattr(approval, "request_id", ""))
    if str(getattr(approval, "approval_source", "") or "") != SOURCE_REMOTE_PROXY:
        return False
    if not _is_pending_codex_app_server_approval(
        approval,
        request_id,
        thread_id=str(getattr(approval, "thread_id", "") or "").strip(),
        command=str(getattr(approval, "cmd", "") or "").strip(),
    ):
        return False

    resolved = state.resolve_pending_approval_decision(
        "codex",
        request_id,
        action,
        message="TG 已拒绝" if action == "exec_deny" else "",
    )
    if not resolved:
        state.pending_approvals.pop(msg_id, None)
        await query.edit_message_text("❌ 回复授权失败：remote proxy 已不再等待该审批。")
        logger.warning(
            "[approval] codex_remote_proxy pending decision missing "
            "request_id=%s action=%s msg_id=%s",
            getattr(approval, "request_id", ""),
            action,
            msg_id,
        )
        return True

    state.pending_approvals.pop(msg_id, None)
    logger.info(
        "[approval] codex_remote_proxy request_id=%s action=%s msg_id=%s",
        getattr(approval, "request_id", ""),
        action,
        msg_id,
    )
    return True


async def mark_codex_app_server_approval_resolved(
    state: "AppState",
    bot,
    group_chat_id: int,
    *,
    request_id,
    thread_id: str = "",
) -> int:
    request_key = _request_key(request_id)
    if not request_key:
        return 0

    resolved: list[tuple[int, object]] = []
    for msg_id, approval in list(state.pending_approvals.items()):
        if _is_pending_codex_app_server_approval(
            approval,
            request_key,
            thread_id=thread_id,
        ):
            resolved.append((msg_id, approval))
            state.pending_approvals.pop(msg_id, None)

    for msg_id, approval in resolved:
        command = str(getattr(approval, "cmd", "") or "").strip()
        lines = ["⚠️ 此 Codex 授权请求已由 Codex 端处理或清理，TG 按钮已失效。"]
        if command:
            lines.append("")
            lines.append(f"命令：{command[:200]}")
        try:
            await bot.edit_message_text(
                chat_id=group_chat_id,
                message_id=msg_id,
                text="\n".join(lines),
            )
        except Exception as e:
            logger.debug(
                "[codex-approval-sync] 更新已失效 TG 授权消息失败 request=%s msg=%s thread=%s err=%s",
                request_key,
                msg_id,
                thread_id or str(getattr(approval, "thread_id", "") or ""),
                e,
            )

    if resolved:
        logger.info(
            "[codex-approval-sync] app-server resolved request=%s thread=%s cleared_tg=%s",
            request_key,
            thread_id or "-",
            len(resolved),
        )
    return len(resolved)


async def handle_codex_app_server_resolution_event(
    state: "AppState",
    bot,
    group_chat_id: int,
    method: str,
    params: dict,
) -> int:
    if method != "app-server-event" or not isinstance(params, dict):
        return 0
    message = params.get("message")
    if not isinstance(message, dict):
        return 0
    if str(message.get("method") or "") != CODEX_APP_SERVER_RESOLVED_METHOD:
        return 0
    payload = message.get("params")
    if not isinstance(payload, dict):
        payload = {}
    request_id = (
        payload.get("requestId")
        or payload.get("request_id")
        or message.get("id")
    )
    thread_id = str(payload.get("threadId") or payload.get("thread_id") or "")
    return await mark_codex_app_server_approval_resolved(
        state,
        bot,
        group_chat_id,
        request_id=request_id,
        thread_id=thread_id,
    )


def is_codex_capacity_abort_reason(reason: str) -> bool:
    return CODEX_CAPACITY_ABORT_REASON in str(reason or "").strip()


def _resolve_codex_capacity_workspace_id(state: "AppState", adapter, params: dict, thread_id: str) -> str:
    workspace_id = str(params.get("workspace_id") or "").strip()
    if workspace_id:
        return workspace_id
    workspace_map = getattr(adapter, "_thread_workspace_map", {}) or {}
    workspace_id = str(workspace_map.get(thread_id) or "").strip()
    if workspace_id:
        return workspace_id
    found = state.find_thread_by_id_global(thread_id)
    if not found:
        return ""
    ws_info, _thread_info = found
    return str(getattr(ws_info, "daemon_workspace_id", "") or "").strip()


async def maybe_auto_continue_capacity_abort(
    state: "AppState",
    adapter,
    method: str,
    params: dict,
) -> bool:
    if method != "app-server-event" or not isinstance(params, dict):
        return False
    message = params.get("message")
    if not isinstance(message, dict):
        return False
    raw_method = str(message.get("method") or "").strip()
    payload = message.get("params")
    if not isinstance(payload, dict):
        payload = {}

    event = parse_codex_app_server_semantic_event(raw_method, payload)
    if event is None or event.kind != "turn_aborted" or not is_codex_capacity_abort_reason(event.reason):
        return False

    thread_id = str(event.thread_id or "").strip()
    if not thread_id:
        logger.warning("[codex-capacity] 容量中断缺少 thread_id，跳过自动续跑")
        return False

    runtime = codex_state.get_runtime(state)
    now = asyncio.get_running_loop().time()
    attempts = runtime.thread_capacity_auto_continue_attempts.get(thread_id, 0)
    last_at = runtime.thread_capacity_auto_continue_last_at.get(thread_id, 0.0)
    if attempts >= CODEX_CAPACITY_AUTO_CONTINUE_MAX_ATTEMPTS:
        logger.warning(
            "[codex-capacity] 自动续跑已达上限 thread=%s attempts=%s",
            thread_id[:12],
            attempts,
        )
        return False
    if last_at and (now - last_at) < CODEX_CAPACITY_AUTO_CONTINUE_COOLDOWN_SECONDS:
        logger.info(
            "[codex-capacity] 冷却中跳过自动续跑 thread=%s delta=%.2fs",
            thread_id[:12],
            now - last_at,
        )
        return False

    workspace_id = _resolve_codex_capacity_workspace_id(state, adapter, params, thread_id)
    if not workspace_id:
        logger.warning(
            "[codex-capacity] 无法解析 workspace，跳过自动续跑 thread=%s",
            thread_id[:12],
        )
        return False

    runtime.thread_capacity_auto_continue_last_at[thread_id] = now
    runtime.thread_capacity_auto_continue_attempts[thread_id] = attempts + 1
    workspace_map = getattr(adapter, "_thread_workspace_map", None)
    if isinstance(workspace_map, dict):
        workspace_map[thread_id] = workspace_id

    try:
        await adapter.resume_thread(workspace_id, thread_id)
        await adapter.send_user_message(
            workspace_id,
            thread_id,
            CODEX_CAPACITY_AUTO_CONTINUE_TEXT,
            approvals_reviewer="user",
        )
    except Exception as exc:
        logger.warning(
            "[codex-capacity] 自动续跑失败 thread=%s workspace=%s attempt=%s err=%s",
            thread_id[:12],
            workspace_id,
            attempts + 1,
            exc,
        )
        return False

    logger.warning(
        "[codex-capacity] 已自动补发继续 thread=%s workspace=%s attempt=%s",
        thread_id[:12],
        workspace_id,
        attempts + 1,
    )
    return True


def make_codex_server_request_handler(state: "AppState", fallback_handler):
    async def on_server_request(method: str, params: dict, request_id: int) -> None:
        if has_pending_codex_app_server_approval(state, request_id, params):
            logger.info(
                "[codex-approval-sync] skip duplicate app-server approval request method=%s request=%s",
                method,
                request_id,
            )
            return
        await fallback_handler(method, params, request_id)

    return on_server_request


def build_incomplete_reply_text(partial_text: str, reason: str) -> str:
    base = partial_text.strip()
    status_text = "已中断" if reason == "interrupted" else "已终止"
    return (
        f"{base}\n\n"
        f"⚠️ 本轮回复{status_text}，以上内容不完整。请重试。"
    )


async def edit_final_reply_with_fallback(
    bot,
    *,
    chat_id: int,
    message_id: int,
    raw_text: str,
    thread_id: str,
) -> bool:
    from bot.handlers.common import _truncate_text

    rendered = format_telegram_assistant_final_text(raw_text)
    attempts = [(rendered.text, rendered.parse_mode)]
    if rendered.parse_mode is not None:
        attempts.append((rendered.fallback_text, None))

    for text, parse_mode in attempts:
        try:
            kwargs = {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text if parse_mode else _truncate_text(text),
            }
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await bot.edit_message_text(**kwargs)
            return True
        except Exception as e:
            if parse_mode is not None:
                logger.warning(
                    "[codex] 恢复最终回复富文本 edit 失败，回退 plain text "
                    "thread=%s… msg_id=%s: %s",
                    thread_id[:12],
                    message_id,
                    e,
                )
                continue
            logger.debug(
                "[codex] 恢复最终回复 plain text edit 失败 thread=%s… msg_id=%s: %s",
                thread_id[:12],
                message_id,
                e,
            )
            return False
    return False


def build_approval_reply(approval, action: str) -> tuple[str, dict]:
    source = str(getattr(approval, "approval_source", "") or "")
    if source == SOURCE_TUI_HOST:
        if action == "exec_deny":
            return "❌ 已拒绝", {"host_action": "exec_deny"}
        if action == "exec_allow_always":
            return "✅ 已总是允许", {"host_action": "exec_allow_always"}
        return "✅ 已允许", {"host_action": "exec_allow"}

    if source in {"execCommandApproval", "applyPatchApproval"}:
        if action == "exec_deny":
            return "❌ 已拒绝", {"decision": "denied"}
        if action == "exec_allow_always" and approval.amendment_decision:
            return "✅ 已总是允许", approval.amendment_decision
        if action == "exec_allow_always":
            return "✅ 已总是允许", {"decision": "approved_for_session"}
        return "✅ 已允许", {"decision": "approved"}

    if source == "item/permissions/requestApproval":
        if action == "exec_deny":
            return "❌ 已拒绝", {"permissions": {}, "scope": "turn"}
        permissions = getattr(approval, "amendment_decision", {}) or {}
        permissions = permissions.get("permissions") if isinstance(permissions, dict) else None
        scope = "session" if action == "exec_allow_always" else "turn"
        return "✅ 已总是允许" if scope == "session" else "✅ 已允许", {
            "permissions": permissions or {},
            "scope": scope,
        }

    if action == "exec_deny":
        return "❌ 已拒绝", {"decision": "decline"}

    if action == "exec_allow_always" and approval.amendment_decision:
        return "✅ 已总是允许", approval.amendment_decision

    if action == "exec_allow_always":
        return "✅ 已总是允许", {"decision": "acceptForSession"}

    return "✅ 已允许", {"decision": "accept"}


def include_state_only_thread(thread_info) -> bool:
    return (
        str(getattr(thread_info, "source", "") or "unknown").strip().lower() == "app"
        and bool(getattr(thread_info, "is_active", False))
    )


def thread_control_intro_extra(thread_id: str, state_text: str) -> str:
    return "\n此 Topic 由 OnlineWorker 托管；Codex app-server 权限请求会在这里显示 TG 审批按钮。"


def thread_interrupt_supported(state, ws) -> bool:
    from plugins.providers.builtin.codex.python.tui_bridge import is_codex_local_owner_mode

    return not is_codex_local_owner_mode(state, ws)


def _load_codex_defaults(config_path: str | None = None) -> tuple[str | None, str | None]:
    path = os.path.expanduser(config_path or "~/.codex/config.toml")
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        logger.info("未找到 codex 配置文件：%s", path)
        return None, None
    except Exception as exc:
        logger.warning("读取 codex 配置失败 path=%s error=%s", path, exc)
        return None, None

    model = raw.get("model")
    effort = raw.get("model_reasoning_effort")
    return (
        model if isinstance(model, str) and model.strip() else None,
        effort if isinstance(effort, str) and effort.strip() else None,
    )


def _normalize_model_entries(
    models: list[dict],
    current_model: str | None,
) -> list[dict]:
    seen: set[str] = set()
    visible: list[dict] = []

    for item in models:
        model_name = str(item.get("model") or "").strip()
        if not model_name or item.get("hidden"):
            continue
        if model_name in seen:
            continue
        seen.add(model_name)
        visible.append(item)

    visible.sort(
        key=lambda item: (
            str(item.get("model") or "") != (current_model or ""),
            not bool(item.get("isDefault")),
            str(item.get("displayName") or item.get("model") or "").lower(),
        )
    )

    selected = visible[:6]
    selected_names = {str(item.get("model") or "") for item in selected}
    if current_model and current_model not in selected_names:
        selected.insert(
            0,
            {
                "model": current_model,
                "displayName": current_model,
                "hidden": False,
                "isDefault": False,
                "supportedReasoningEfforts": [],
            },
        )
    return selected


def _resolve_reasoning_options(
    models: list[dict],
    current_model: str | None,
    current_effort: str | None,
) -> list[str]:
    target = None
    if current_model:
        target = next(
            (
                item for item in models
                if str(item.get("model") or "").strip() == current_model
            ),
            None,
        )
    if target is None:
        target = next((item for item in models if item.get("isDefault")), None)
    if target is None and models:
        target = models[0]

    options: list[str] = []
    if isinstance(target, dict):
        for item in target.get("supportedReasoningEfforts") or []:
            if not isinstance(item, dict):
                continue
            effort = str(item.get("reasoningEffort") or "").strip()
            if effort and effort not in options:
                options.append(effort)

    for effort in [current_effort, *DEFAULT_REASONING_OPTIONS]:
        if effort and effort not in options:
            options.append(effort)
    return options


def _build_model_prompt_text(
    *,
    current_model: str | None,
    current_effort: str | None,
    selected_model: str | None,
    selected_effort: str | None,
    current_step: str,
) -> str:
    step_title = {
        "select_model": "第 1 步：选择模型",
        "select_effort": "第 2 步：选择推理强度",
        "confirm": "第 3 步：确认应用",
    }.get(current_step, "Codex `/model`")
    lines = [
        "Codex `/model`",
        f"当前基线模型：{current_model or '未知'}",
        f"当前基线推理：{current_effort or '未知'}",
        "",
        step_title,
        f"待应用模型：{selected_model or '未选择'}",
        f"待应用推理：{selected_effort or '未选择'}",
        "当前基线读取自 `~/.codex/config.toml`；thread 级 override 不一定会立即回写到该文件。",
    ]
    if current_step == "select_model":
        lines.append("点击模型会进入下一步；如果只想改推理，可直接点“继续选择推理”。")
    elif current_step == "select_effort":
        lines.append("点击推理会进入确认页；如果保持当前推理，可直接点“继续确认”。")
    elif current_step == "confirm":
        lines.append("确认后，会一次性把模型和推理强度应用到当前 thread 的后续 turns。")
    return "\n".join(lines)


def _preferred_model_name(models: list[dict], current_model: str | None) -> str | None:
    if current_model:
        return current_model

    default_model = next(
        (
            str(item.get("model") or "").strip()
            for item in models
            if item.get("isDefault") and str(item.get("model") or "").strip()
        ),
        None,
    )
    if default_model:
        return default_model
    if models:
        first_model = str(models[0].get("model") or "").strip()
        return first_model or None
    return None


def _preferred_effort_name(
    efforts: list[str],
    current_effort: str | None,
) -> str | None:
    if current_effort:
        return current_effort
    if efforts:
        return efforts[0]
    return None


def _copy_option(
    option,
    *,
    label: str | None = None,
) -> "PendingCommandWrapperOption":
    from core.state import PendingCommandWrapperOption

    return PendingCommandWrapperOption(
        label=label or option.label,
        value=option.value,
        action=option.action,
        description=option.description,
    )


def render_model_wrapper(pending: "PendingCommandWrapper") -> "PendingCommandWrapper":
    from core.state import PendingCommandWrapperOption

    selected_model = pending.selected_model or pending.current_model
    selected_effort = pending.selected_effort or pending.current_effort
    current_step = pending.current_step or "select_model"

    if current_step == "select_model":
        options = [
            _copy_option(
                option,
                label=f"{'✅ ' if option.value == selected_model else ''}{option.label}",
            )
            for option in pending.model_options
        ]
        options.append(
            PendingCommandWrapperOption(
                label="继续选择推理",
                value="",
                action="next_effort",
            )
        )
    elif current_step == "select_effort":
        options = [
            _copy_option(
                option,
                label=f"{'✅ ' if option.value == selected_effort else ''}{option.label}",
            )
            for option in pending.effort_options
        ]
        options.extend(
            [
                PendingCommandWrapperOption(
                    label="← 返回模型",
                    value="",
                    action="back_model",
                ),
                PendingCommandWrapperOption(
                    label="继续确认",
                    value="",
                    action="next_confirm",
                ),
            ]
        )
    else:
        options = [
            PendingCommandWrapperOption(
                label="← 重新选模型",
                value="",
                action="back_model",
            ),
            PendingCommandWrapperOption(
                label="← 重新选推理",
                value="",
                action="back_effort",
            ),
            PendingCommandWrapperOption(
                label="✅ 应用到当前 thread",
                value="apply",
                action="apply",
            ),
        ]

    pending.prompt_text = _build_model_prompt_text(
        current_model=pending.current_model,
        current_effort=pending.current_effort,
        selected_model=selected_model,
        selected_effort=selected_effort,
        current_step=current_step,
    )
    pending.current_step = current_step
    pending.selected_model = selected_model
    pending.selected_effort = selected_effort
    pending.options = options
    return pending


async def build_model_wrapper(
    state: "AppState",
    command_name: str,
    args: list[str],
    ws_info: "WorkspaceInfo",
    thread_info: "ThreadInfo",
) -> "PendingCommandWrapper | None":
    from core.state import PendingCommandWrapper, PendingCommandWrapperOption

    if command_name != "model":
        return None

    adapter = state.get_adapter("codex")
    if adapter is None or not adapter.connected:
        return None

    models = await adapter.list_models(include_hidden=False, limit=20)
    current_model, current_effort = _load_codex_defaults()
    visible_models = _normalize_model_entries(models, current_model)
    reasoning_options = _resolve_reasoning_options(visible_models, current_model, current_effort)

    if not visible_models:
        return None

    model_options: list[PendingCommandWrapperOption] = []
    for item in visible_models:
        model_name = str(item.get("model") or "").strip()
        if not model_name:
            continue
        display_name = str(item.get("displayName") or model_name).strip()
        model_options.append(
            PendingCommandWrapperOption(
                label=f"模型: {display_name}",
                value=model_name,
                action="set_model",
                description=display_name,
            )
        )

    effort_options: list[PendingCommandWrapperOption] = []
    for effort in reasoning_options:
        effort_options.append(
            PendingCommandWrapperOption(
                label=f"推理: {effort}",
                value=effort,
                action="set_effort",
            )
        )

    preferred_model = _preferred_model_name(visible_models, current_model)
    preferred_effort = _preferred_effort_name(reasoning_options, current_effort)
    if preferred_model is None or preferred_effort is None:
        return None

    pending = PendingCommandWrapper(
        command_name="model",
        workspace_id=ws_info.daemon_workspace_id or "",
        thread_id=thread_info.thread_id,
        topic_id=_thread_topic_id(state, ws_info, thread_info),
        tool_name=ws_info.tool,
        prompt_text="",
        options=[],
        current_step="select_model",
        current_model=preferred_model,
        current_effort=preferred_effort,
        selected_model=preferred_model,
        selected_effort=preferred_effort,
        model_options=model_options,
        effort_options=effort_options,
    )
    return render_model_wrapper(pending)


async def refresh_model_wrapper(
    state: "AppState",
    pending: "PendingCommandWrapper",
    ws_info: "WorkspaceInfo",
    thread_info: "ThreadInfo",
) -> "PendingCommandWrapper":
    refreshed = await build_model_wrapper(
        state,
        pending.command_name,
        [],
        ws_info,
        thread_info,
    )
    if refreshed is None:
        raise RuntimeError("当前命令暂时无法在此 thread 中刷新。")

    model_values = {option.value for option in refreshed.model_options}
    effort_values = {option.value for option in refreshed.effort_options}
    if pending.selected_model in model_values:
        refreshed.selected_model = pending.selected_model
    if pending.selected_effort in effort_values:
        refreshed.selected_effort = pending.selected_effort
    if pending.current_step in {"select_model", "select_effort", "confirm"}:
        refreshed.current_step = pending.current_step
    return render_model_wrapper(refreshed)


async def apply_model_wrapper_selection(
    state: "AppState",
    pending: "PendingCommandWrapper",
    option_idx: int,
) -> "PendingCommandWrapper | str":
    if option_idx < 0 or option_idx >= len(pending.options):
        raise RuntimeError("选项索引无效。")

    streaming = state.streaming_turns.get(pending.thread_id)
    if streaming is not None and streaming.turn_id and not streaming.completed:
        raise RuntimeError("当前 thread 仍有进行中的 turn，请等待完成后再切换模型。")

    adapter = state.get_adapter("codex")
    if adapter is None or not adapter.connected:
        raise RuntimeError("codex 未连接，无法应用 `/model` 选择。")

    option = pending.options[option_idx]
    if option.action == "set_model":
        pending.selected_model = option.value
        pending.current_step = "select_effort"
        return render_model_wrapper(pending)

    if option.action == "next_effort":
        pending.current_step = "select_effort"
        return render_model_wrapper(pending)

    if option.action == "set_effort":
        pending.selected_effort = option.value
        pending.current_step = "confirm"
        return render_model_wrapper(pending)

    if option.action == "next_confirm":
        pending.current_step = "confirm"
        return render_model_wrapper(pending)

    if option.action == "back_model":
        pending.current_step = "select_model"
        return render_model_wrapper(pending)

    if option.action == "back_effort":
        pending.current_step = "select_effort"
        return render_model_wrapper(pending)

    selected_model = pending.selected_model or pending.current_model
    selected_effort = pending.selected_effort or pending.current_effort
    if option.action != "apply":
        raise RuntimeError("未知的命令 wrapper 操作。")
    if not selected_model or not selected_effort:
        raise RuntimeError("请先完成模型与推理强度选择。")

    await adapter.set_thread_model_config(
        pending.workspace_id,
        pending.thread_id,
        model=selected_model,
        reasoning_effort=selected_effort,
    )
    return (
        "✅ 已为当前 thread 应用 `/model` 设置。\n"
        f"模型：{selected_model}\n"
        f"推理强度：{selected_effort}\n"
        "后续 turns 将使用新的配置。"
    )


async def _wait_for_adapter_reconnect(state):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + CODEX_RECONNECT_GRACE_SECONDS

    while True:
        adapter = state.get_adapter("codex")
        if adapter is not None and adapter.connected:
            return adapter

        remaining = deadline - loop.time()
        if remaining <= 0:
            return adapter

        await asyncio.sleep(min(CODEX_RECONNECT_POLL_SECONDS, remaining))


async def ensure_connected(state, adapter, ws_info, *, update, context, group_chat_id: int, src_topic_id):
    if adapter is not None and adapter.connected:
        return adapter

    logger.info(
        "[provider-message] codex adapter 未连接，进入短暂重连等待 thread=%s",
        getattr(getattr(ws_info, "threads", None), "thread_id", "")[:8],
    )
    adapter = await _wait_for_adapter_reconnect(state)
    if adapter is not None and adapter.connected:
        logger.info("[provider-message] codex adapter 已恢复，继续发送")
    return adapter


async def handle_local_owner(
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
    from bot.handlers.common import _send_to_group, tg_send_failed_text
    from plugins.providers.builtin.codex.python.tui_bridge import (
        enqueue_codex_tui_message,
        should_route_codex_messages_to_tui_host,
    )

    should_route_to_tui = should_route_codex_messages_to_tui_host(state, ws_info)
    if not should_route_to_tui:
        return False

    try:
        await enqueue_codex_tui_message(
            state,
            ws_info,
            context.bot,
            group_chat_id,
            src_topic_id or _thread_topic_id(state, ws_info, thread_info) or 0,
            thread_info.thread_id,
            text,
        )

        if not thread_info.preview:
            thread_info.preview = text[:80]
            if state.storage is not None:
                from core.storage import save_storage
                save_storage(state.storage)

        logger.info("[provider-message] codex 本地 owner 已接管 thread=%s", thread_info.thread_id[:8])
    except Exception as e:
        logger.error("[provider-message] codex 本地 owner 发送失败：%s", e)
        await _send_to_group(
            context.bot,
            group_chat_id,
            tg_send_failed_text(e),
            topic_id=src_topic_id,
        )
    return True


def can_route_cli_approval_to_tui_host(state, thread_id: str) -> bool:
    if not thread_id:
        return False
    from plugins.providers.builtin.codex.python.tui_host_protocol import read_host_status

    host = codex_state.get_tui_host(state)
    if (
        host is not None
        and getattr(host, "thread_id", "") == thread_id
        and bool(getattr(host, "is_running", False))
    ):
        return True

    data_dir = getattr(getattr(state, "config", None), "data_dir", None) or get_data_dir()
    try:
        status = read_host_status(data_dir)
    except Exception:
        return False
    if not isinstance(status, dict) or not status.get("online"):
        return False
    return str(status.get("active_thread_id") or "").strip() == thread_id


def _codex_thread_has_source_record(workspace_path: str, thread_id: str) -> bool:
    if not workspace_path or not thread_id:
        return False
    try:
        active_ids = storage_runtime.query_codex_active_thread_ids(workspace_path)
    except Exception:
        logger.debug("[codex] 查询源端 active thread 失败", exc_info=True)
        active_ids = set()
    if thread_id in active_ids:
        return True
    return storage_runtime.find_session_file(thread_id) is not None


def _extract_started_thread_id(result: object) -> str:
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError(f"Codex start_thread 返回无效 thread id：{result}")
    return str(thread_id)


async def _codex_thread_can_resume_in_app_server(
    adapter,
    workspace_id: str,
    thread_id: str,
) -> bool:
    if not workspace_id or not thread_id:
        return False
    try:
        await adapter.resume_thread(workspace_id, thread_id)
        return True
    except Exception:
        logger.info(
            "[codex] app-server resume thread 失败，将创建新 thread old=%s",
            thread_id[:12],
            exc_info=True,
        )
        return False


def _replace_thread_binding(ws_info, thread_info, new_thread_id: str) -> None:
    old_thread_id = str(getattr(thread_info, "thread_id", "") or "")
    if not new_thread_id or new_thread_id == old_thread_id:
        return
    if old_thread_id:
        ws_info.threads.pop(old_thread_id, None)
    thread_info.thread_id = new_thread_id
    thread_info.source = "app"
    thread_info.is_active = True
    ws_info.threads[new_thread_id] = thread_info


async def try_route_owner_bridge_send(state, ws_info, thread_info, *, text: str):
    if not text:
        return False
    thread_id = str(getattr(thread_info, "thread_id", "") or "").strip()
    if str(getattr(thread_info, "source", "") or "").strip().lower() == "app":
        logger.info(
            "[codex-owner-bridge] app source thread 改走 app-server send thread=%s",
            thread_id[:12],
        )
        return False
    if not _codex_thread_has_source_record(str(getattr(ws_info, "path", "") or ""), thread_id):
        logger.info(
            "[codex-owner-bridge] thread 尚未在 Codex 源端物化，改走 app-server send thread=%s",
            thread_id[:12],
        )
        return False
    from plugins.providers.builtin.codex.python.tui_bridge import (
        ensure_codex_tui_host_bound,
    )

    bound = await ensure_codex_tui_host_bound(state, ws_info, thread_id, allow_owner_bridge=True)
    if not bound or not can_route_cli_approval_to_tui_host(state, thread_id):
        raise RuntimeError(f"codex_tui_host 未就绪，无法接管当前 TG 会话 thread={thread_id}")
    from plugins.providers.builtin.codex.python.tui_host_client import (
        send_message_to_codex_tui_host,
    )

    await send_message_to_codex_tui_host(
        state,
        ws_info,
        thread_id,
        text,
        topic_id=_thread_topic_id(state, ws_info, thread_info),
    )
    return "codex_tui_host"


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
    thread_id = str(getattr(thread_info, "thread_id", "") or "")
    thread_source = str(getattr(thread_info, "source", "") or "").strip().lower()
    should_materialize_app_thread = (
        thread_source == "app"
        and not await _codex_thread_can_resume_in_app_server(adapter, workspace_id, thread_id)
    )

    if should_materialize_app_thread:
        original_thread_id = thread_info.thread_id
        result = await adapter.start_thread(workspace_id)
        new_thread_id = _extract_started_thread_id(result)
        _replace_thread_binding(ws_info, thread_info, new_thread_id)
        logger.info(
            "[provider-message] codex app-state thread 首次发送已创建源端 thread old=%s new=%s",
            str(original_thread_id)[:8],
            new_thread_id[:8],
        )
    await _interrupt_active_turn(
        state,
        adapter,
        workspace_id,
        thread_info.thread_id,
        label="codex",
    )
    return True


async def send_message(
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
) -> None:
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        seed_codex_watch_baseline,
        watch_codex_thread,
    )

    seed_codex_watch_baseline(state, ws_info, thread_info.thread_id)
    codex_state.mark_send_started(state, thread_info.thread_id)
    state.mark_provider_task_summary("codex", thread_info.thread_id, text)
    if attachments:
        await adapter.send_user_message(
            ws_info.daemon_workspace_id,
            thread_info.thread_id,
            text,
            attachments=attachments,
        )
        watch_codex_thread(state, ws_info, thread_info.thread_id)
        return
    await adapter.send_user_message(ws_info.daemon_workspace_id, thread_info.thread_id, text)
    watch_codex_thread(state, ws_info, thread_info.thread_id)


def resolve_thread_adapter(state, ws):
    tool_adapter = state.get_adapter(ws.tool)
    if tool_adapter and tool_adapter.connected:
        return tool_adapter
    return None


def validate_new_thread(state, ws, initial_text: str | None) -> str | None:
    from plugins.providers.builtin.codex.python.tui_bridge import is_codex_local_owner_mode

    if not initial_text:
        return (
            "codex 当前不能创建空 thread。\n"
            "请使用 `/new <初始消息>`，这样源端 thread 才会 materialize，"
            "后续 `/archive` 才能走真实归档。"
        )
    if is_codex_local_owner_mode(state, ws):
        return (
            "当前主控模式暂不支持 /new。\n"
            "请先在现有 thread 中继续对话，后续再补 thread 创建链路。"
        )
    return None


async def activate_new_thread(
    state,
    adapter,
    ws,
    workspace_id: str,
    thread_id: str,
    initial_text: str | None,
) -> None:
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        seed_codex_watch_baseline,
        watch_codex_thread,
    )

    seed_codex_watch_baseline(state, ws, thread_id)
    await adapter.send_user_message(workspace_id, thread_id, initial_text)
    watch_codex_thread(state, ws, thread_id)


async def archive_thread(state, ws, thread_id: str, active_adapter) -> None:
    from plugins.providers.builtin.codex.python.tui_bridge import archive_codex_thread_via_tui_bridge

    try:
        await archive_codex_thread_via_tui_bridge(state, ws, thread_id)
    except Exception as e:
        if is_codex_unmaterialized_error(e):
            raise RuntimeError(
                "codex thread 尚未发送首条消息，源端还未 materialize，"
                "暂时无法执行真实 archive；请先发送一条消息后再归档。"
            ) from e
        raise


archive_thread.requires_adapter = False


async def interrupt_thread(
    state,
    ws,
    thread_info,
    active_adapter,
    turn_id: str,
) -> None:
    if not turn_id:
        raise RuntimeError("当前没有可中断的活跃任务。")
    await interrupt_default_thread(state, ws, thread_info, active_adapter, turn_id)


def normalize_server_threads(server_threads: list[dict], *, limit: int) -> list[dict]:
    main_threads = [
        t for t in server_threads
        if not t.get("ephemeral", False) and isinstance(t.get("source"), str)
    ]
    main_threads.sort(key=lambda t: t.get("updatedAt", 0), reverse=True)
    return main_threads[:limit]


def list_local_threads(workspace_path: str, *, limit: int = 20) -> list[dict]:
    return storage_runtime.list_codex_session_meta_threads_by_cwd(workspace_path, limit=limit)


async def recover_stale_stream(
    manager,
    bot,
    thread_id: str,
    *,
    turn_id: Optional[str] = None,
    partial_text: str,
    message_id: int,
    max_attempts: int = 6,
    poll_interval: float = 0.5,
) -> bool:
    from bot.handlers.common import _truncate_text
    from plugins.providers.builtin.codex.python.storage_runtime import (
        read_codex_turn_terminal_message,
        read_codex_turn_terminal_outcome,
        read_thread_history,
    )
    from plugins.providers.builtin.codex.python.tui_bridge import (
        remember_codex_tg_synced_final_reply,
    )

    partial = partial_text.strip()
    if not partial or not message_id:
        return False

    for attempt in range(max_attempts):
        terminal_outcome = read_codex_turn_terminal_outcome(
            thread_id,
            turn_id=turn_id,
        )
        terminal_status = ""
        terminal_reason = ""
        if isinstance(terminal_outcome, dict):
            terminal_status = str(terminal_outcome.get("status") or "")
            terminal_reason = str(terminal_outcome.get("reason") or "")

        if terminal_status == "aborted":
            try:
                await bot.edit_message_text(
                    chat_id=manager.gid,
                    message_id=message_id,
                    text=_truncate_text(
                        build_incomplete_reply_text(partial, terminal_reason)
                    ),
                )
                logger.info(
                    "[codex] 已收口半截 streaming 消息 "
                    "thread=%s… msg_id=%s source=turn_aborted",
                    thread_id[:12],
                    message_id,
                )
                return True
            except Exception as e:
                logger.debug(
                    "[codex] 收口半截 streaming 消息失败 thread=%s… msg_id=%s: %s",
                    thread_id[:12],
                    message_id,
                    e,
                )

        terminal_message = read_codex_turn_terminal_message(
            thread_id,
            turn_id=turn_id,
        )
        if terminal_message and turn_id:
            try:
                edited = await edit_final_reply_with_fallback(
                    bot,
                    chat_id=manager.gid,
                    message_id=message_id,
                    raw_text=terminal_message.strip(),
                    thread_id=thread_id,
                )
                if not edited:
                    raise RuntimeError("formatted recovery edit returned false")
                logger.info(
                    "[codex] 已恢复半截 streaming 消息 "
                    "thread=%s… msg_id=%s source=task_complete_exact_turn",
                    thread_id[:12],
                    message_id,
                )
                remember_codex_tg_synced_final_reply(
                    manager.state,
                    thread_id,
                    text=terminal_message,
                )
                codex_state.mark_run(
                    manager.state,
                    thread_id=thread_id,
                    final_reply_synced_to_tg=True,
                )
                return True
            except Exception as e:
                logger.debug(
                    "[codex] 恢复半截 streaming 消息失败 thread=%s… msg_id=%s: %s",
                    thread_id[:12],
                    message_id,
                    e,
                )
        try:
            history = read_thread_history(thread_id, limit=6)
        except Exception as e:
            logger.debug("[codex] 读取 thread 历史失败，跳过恢复 thread=%s…: %s", thread_id[:12], e)
            return False

        latest_assistant = next(
            (
                item.get("text", "").strip()
                for item in reversed(history)
                if item.get("role") == "assistant" and item.get("text")
            ),
            "",
        )

        recovery_candidates = []
        if terminal_message:
            recovery_candidates.append(("task_complete", terminal_message.strip()))
        if latest_assistant:
            recovery_candidates.append(("history", latest_assistant))

        recovered_source = ""
        recovered_text = ""
        for source, candidate in recovery_candidates:
            if candidate and candidate.startswith(partial):
                recovered_source = source
                recovered_text = candidate
                break

        if recovered_text:
            try:
                edited = await edit_final_reply_with_fallback(
                    bot,
                    chat_id=manager.gid,
                    message_id=message_id,
                    raw_text=recovered_text,
                    thread_id=thread_id,
                )
                if not edited:
                    raise RuntimeError("formatted recovery edit returned false")
                logger.info(
                    "[codex] 已恢复半截 streaming 消息 "
                    "thread=%s… msg_id=%s source=%s",
                    thread_id[:12],
                    message_id,
                    recovered_source,
                )
                remember_codex_tg_synced_final_reply(
                    manager.state,
                    thread_id,
                    text=recovered_text,
                )
                codex_state.mark_run(
                    manager.state,
                    thread_id=thread_id,
                    final_reply_synced_to_tg=True,
                )
                return True
            except Exception as e:
                logger.debug(
                    "[codex] 恢复半截 streaming 消息失败 thread=%s… msg_id=%s: %s",
                    thread_id[:12],
                    message_id,
                    e,
                )
        elif latest_assistant or terminal_message:
            logger.debug(
                "[codex] 最新终态/assistant 还不是当前 partial 的扩展，继续等待 "
                "thread=%s…",
                thread_id[:12],
            )

        if attempt < max_attempts - 1:
            await asyncio.sleep(poll_interval)

    return False


def schedule_stale_stream_recovery(
    manager,
    bot,
    thread_id: str,
    *,
    turn_id: Optional[str] = None,
    partial_text: str,
    message_id: int,
) -> bool:
    recovery_tasks = manager.get_stale_recovery_tasks("codex")
    existing = recovery_tasks.get(thread_id)
    if existing is not None and not existing.done():
        logger.info("[codex] stale stream 后台恢复已在进行中 thread=%s…", thread_id[:12])
        return False

    async def _runner() -> None:
        try:
            recovered = await recover_stale_stream(
                manager,
                bot,
                thread_id,
                turn_id=turn_id,
                partial_text=partial_text,
                message_id=message_id,
                max_attempts=40,
                poll_interval=0.5,
            )
            if recovered:
                logger.info(
                    "[codex] stale stream 后台恢复成功 thread=%s… msg_id=%s",
                    thread_id[:12],
                    message_id,
                )
            else:
                logger.info(
                    "[codex] stale stream 后台恢复超时 thread=%s… msg_id=%s",
                    thread_id[:12],
                    message_id,
                )
        except asyncio.CancelledError:
            raise
        finally:
            current = recovery_tasks.get(thread_id)
            try:
                current_task = asyncio.current_task()
            except RuntimeError:
                current_task = None
            if current_task is None or current is current_task:
                recovery_tasks.pop(thread_id, None)

    task = asyncio.create_task(
        _runner(),
        name=f"codex-stale-recovery-{thread_id[:8]}",
    )
    recovery_tasks[thread_id] = task
    return True


async def prime_thread_mappings(manager, adapter) -> None:
    from core.providers.facts import query_provider_active_thread_ids

    if not manager.storage.workspaces:
        return

    needs_save = False
    for ws_info in manager.storage.workspaces.values():
        if ws_info.tool != "codex" or not ws_info.daemon_workspace_id:
            continue
        active_ids = None
        for thread_id, thread_info in ws_info.threads.items():
            if thread_info.archived:
                if active_ids is None:
                    try:
                        active_ids = query_provider_active_thread_ids(ws_info.tool, ws_info.path)
                    except Exception as e:
                        logger.warning(
                            "[lifecycle] 查询活跃 thread 失败，tool=%s ws=%s err=%s",
                            ws_info.tool,
                            ws_info.name,
                            e,
                        )
                        active_ids = set()
                if thread_id not in active_ids:
                    continue
                thread_info.archived = False
                thread_info.is_active = True
                needs_save = True
                logger.warning(
                    "[lifecycle] 已清理本地误归档 thread，tool=%s ws=%s tid=%s",
                    ws_info.tool,
                    ws_info.name,
                    thread_id,
                )
            adapter._thread_workspace_map[thread_id] = ws_info.daemon_workspace_id

    if needs_save:
        _save_storage_via_lifecycle(manager)


async def setup_connection(manager, bot, adapter, **kwargs) -> None:
    from bot.events import make_event_handler, make_server_request_handler
    from plugins.providers.builtin.codex.python.owner_bridge import ensure_codex_owner_bridge_started
    from core.storage import ThreadInfo

    manager.state.set_adapter("codex", adapter)
    if hasattr(adapter, "enable_thread_policy_lookup"):
        adapter.enable_thread_policy_lookup(True)
    event_handler = make_event_handler(manager.state, bot, manager.gid)

    async def codex_event_handler(method: str, params: dict) -> None:
        await handle_codex_app_server_resolution_event(
            manager.state,
            bot,
            manager.gid,
            method,
            params,
        )
        await event_handler(method, params)
        await maybe_auto_continue_capacity_abort(manager.state, adapter, method, params)

    adapter.on_event(codex_event_handler)
    adapter.on_server_request(
        make_codex_server_request_handler(
            manager.state,
            make_server_request_handler(manager.state, bot, manager.gid),
        )
    )
    await prime_thread_mappings(manager, adapter)

    if not manager.storage.workspaces:
        await ensure_codex_owner_bridge_started(manager.state)
        return

    for ws_name, ws_info in manager.storage.workspaces.items():
        if ws_info.tool != "codex" or not ws_info.daemon_workspace_id:
            continue

        adapter.register_workspace_cwd(ws_info.daemon_workspace_id, ws_info.path)
        logger.info("workspace cwd 已注册：%s", ws_name)

        try:
            # 预热 app-server 当前可见 thread 的 workspace 映射。
            # 否则运行中的 live thread 若尚未落入本地 storage，首批事件会因空 workspace_id 被消息总线丢弃。
            live_threads = await adapter.list_threads(ws_info.daemon_workspace_id, limit=50)
            for thread in live_threads or []:
                if not isinstance(thread, dict):
                    continue
                thread_id = str(thread.get("id") or "").strip()
                if thread_id:
                    adapter._thread_workspace_map[thread_id] = ws_info.daemon_workspace_id
        except Exception as e:
            logger.warning(
                "预热 codex thread 映射失败：workspace=%s err=%s",
                ws_name,
                e,
            )

        needs_save = False
        for thread_id, thread_info in ws_info.threads.items():
            streaming_state = manager.state.streaming_turns.get(thread_id)
            if (
                thread_info.streaming_msg_id is not None
                and _thread_topic_id(manager.state, ws_info, thread_info) is not None
                and streaming_state is not None
            ):
                if streaming_state.throttle_task and not streaming_state.throttle_task.done():
                    streaming_state.throttle_task.cancel()
                    streaming_state.throttle_task = None
                recovered = await recover_stale_stream(
                    manager,
                    bot,
                    thread_id,
                    turn_id=streaming_state.turn_id,
                    partial_text=streaming_state.buffer,
                    message_id=streaming_state.message_id or thread_info.streaming_msg_id,
                )
                if not recovered:
                    schedule_stale_stream_recovery(
                        manager,
                        bot,
                        thread_id,
                        turn_id=streaming_state.turn_id,
                        partial_text=streaming_state.buffer,
                        message_id=streaming_state.message_id or thread_info.streaming_msg_id,
                    )
            if thread_info.streaming_msg_id is not None:
                thread_info.streaming_msg_id = None
                needs_save = True
                logger.info("[codex] 清理残留 streaming_msg_id thread=%s…", thread_id[:12])
            if thread_id in manager.state.streaming_turns:
                manager.state.streaming_turns.pop(thread_id, None)
                logger.info("[codex] 清理残留 streaming_turn thread=%s…", thread_id[:12])

        if not ws_info.threads:
            logger.info("workspace %s 无 thread 记录，从 app-server 同步…", ws_name)
            try:
                adapter_threads = await adapter.list_threads(ws_info.daemon_workspace_id, limit=50)
                main_threads = [
                    t for t in adapter_threads
                    if not t.get("ephemeral", False)
                    and isinstance(t.get("source"), str)
                ]
                for dt in main_threads:
                    tid = dt.get("id", "")
                    if not tid:
                        continue
                    preview = dt.get("preview") or dt.get("title") or None
                    ws_info.threads[tid] = ThreadInfo(
                        thread_id=tid,
                        topic_id=None,
                        preview=preview,
                        archived=False,
                        source="unknown",
                    )
                logger.info("迁移完成：导入 %s 个 thread", len(ws_info.threads))
                needs_save = True
            except Exception as e:
                logger.error("迁移 thread 列表失败：%s", e)

        if needs_save:
            _save_storage_via_lifecycle(manager)

    await ensure_codex_owner_bridge_started(manager.state)


async def sync_existing_topics_after_startup(manager, bot) -> None:
    from bot.handlers.common import reconcile_workspace_threads_with_source
    from core.storage import save_storage
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        bootstrap_bound_codex_thread_activity,
    )

    state_changed = False

    for ws_name, ws_info in manager.storage.workspaces.items():
        if ws_info.tool != "codex":
            continue

        active_ids = storage_runtime.query_codex_active_thread_ids(ws_info.path)
        _, repaired = reconcile_workspace_threads_with_source(
            manager.state,
            ws_info,
            active_ids=active_ids,
            persist=False,
        )
        if repaired:
            logger.info(
                "[codex-startup-sync] 已修正 workspace thread 活跃状态 ws=%s active=%s",
                ws_name,
                len(active_ids),
            )
            state_changed = True

    recovered = bootstrap_bound_codex_thread_activity(manager.state)
    if state_changed:
        save_storage(manager.storage)
    if recovered:
        logger.info("[codex-startup-sync] 已恢复已绑定 Codex thread activity/watch")
    else:
        logger.info("[codex-startup-sync] 无需恢复 Codex thread activity/watch")


async def setup_adapter_connection(manager, bot, adapter) -> None:
    await manager._setup_provider_connection("codex", bot, adapter)


def resolve_reconnect_topic_id(manager, provider_name: str):
    return (
        manager.state.get_active_workspace_topic_id_for_tool(provider_name)
        or manager.state.get_global_topic_id(provider_name)
    )


async def probe_url(url: str, timeout: float = 1.5) -> bool:
    loop = asyncio.get_event_loop()

    def _probe() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return getattr(resp, "status", 0) == 200
        except urllib.error.HTTPError as e:
            return e.code == 200
        except Exception:
            return False

    return await loop.run_in_executor(None, _probe)


async def resolve_connection_target(tool_cfg) -> Optional[str]:
    app_server_url = getattr(tool_cfg, "app_server_url", "") or ""
    if app_server_url:
        if is_default_unix_endpoint(app_server_url):
            logger.info("codex 使用托管默认 unix app-server：%s", app_server_url)
            return None
        if is_unix_endpoint(app_server_url):
            if unix_socket_accepting(app_server_url):
                logger.info("codex 使用外部 unix app-server：%s", app_server_url)
                return app_server_url
            logger.info("codex 指定 unix app-server 未运行，将启动托管实例：%s", app_server_url)
            return None
        logger.info("codex 使用外部 app-server：%s", app_server_url)
        return app_server_url

    if tool_cfg.protocol != "ws" or not tool_cfg.app_server_port:
        return None

    readyz_url = f"http://127.0.0.1:{tool_cfg.app_server_port}/readyz"
    if await probe_url(readyz_url):
        ws_url = f"ws://127.0.0.1:{tool_cfg.app_server_port}"
        logger.info("检测到已存在 codex app-server，直接连接：%s", ws_url)
        return ws_url

    return None


async def connect_adapter_with_retry(
    manager,
    bot,
    proc: Optional[AppServerProcess],
    ws_url: str,
) -> None:
    adapter = CodexAdapter()

    def _on_disconnect():
        logger.warning("app-server 连接断开，准备重连…")
        log_app_server_process_snapshot(proc, reason="owner_disconnect")
        schedule_reconnect(manager, bot, proc, ws_url)

    adapter.on_disconnect(_on_disconnect)

    try:
        await adapter.connect(ws_url, process=proc._proc if proc else None)
        logger.info("app-server 连接成功")
        await setup_adapter_connection(manager, bot, adapter)

        if proc is not None:
            manager._process_monitor_started = True
            asyncio.create_task(monitor_process_health(manager, bot, proc, ws_url))
    except Exception as e:
        logger.error("app-server 连接失败：%s", e)
        logger.error("首次连接 app-server 失败，已切换到后台重连")
        schedule_reconnect(manager, bot, proc, ws_url)


async def reconnect_loop(
    manager,
    bot,
    proc: Optional[AppServerProcess],
    ws_url: str,
) -> None:
    from bot.handlers.common import _send_to_group

    notify_topic_id = manager._resolve_provider_reconnect_topic_id("codex")

    try:
        await _send_to_group(
            bot,
            manager.gid,
            "⚠️ app-server 连接断开，正在重连…",
            topic_id=notify_topic_id,
        )
    except Exception:
        pass

    manager.state.set_adapter("codex", None)

    delay = 2.0
    max_delay = 60.0
    attempt = 0

    while True:
        attempt += 1
        logger.info("第 %s 次重连 app-server（等待 %.0fs）…", attempt, delay)
        await asyncio.sleep(delay)

        if proc is not None:
            if proc.protocol == "stdio" and proc.running:
                logger.info("stdio 模式重连前重启 app-server 进程…")
                try:
                    await proc.stop()
                except Exception as e:
                    logger.debug("stdio 模式停止旧 app-server 失败：%s", e)

            if not proc.running:
                logger.warning("app-server 进程已停止，尝试重启…")
                try:
                    ws_url = await proc.start()
                    logger.info("app-server 进程已重启")
                    if proc.protocol != "stdio":
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.warning("app-server 进程重启失败：%s", e)
                    delay = min(delay * 2, max_delay)
                    continue
            else:
                pid = proc._proc.pid if proc._proc else "?"
                logger.debug("app-server 进程运行中 (pid=%s)", pid)

        adapter = CodexAdapter()

        def _on_disconnect_again():
            logger.warning("app-server 重连后再次断开，重新触发重连循环…")
            log_app_server_process_snapshot(proc, reason="owner_disconnect_after_reconnect")
            schedule_reconnect(manager, bot, proc, ws_url)

        adapter.on_disconnect(_on_disconnect_again)

        try:
            await adapter.connect(ws_url, process=proc._proc if proc else None)
            logger.info("app-server 第 %s 次重连成功", attempt)
            await setup_adapter_connection(manager, bot, adapter)

            try:
                await _send_to_group(
                    bot,
                    manager.gid,
                    "✅ app-server 已重连，服务恢复正常。",
                    topic_id=notify_topic_id,
                )
            except Exception:
                pass

            if proc is not None and not manager._process_monitor_started:
                manager._process_monitor_started = True
                asyncio.create_task(monitor_process_health(manager, bot, proc, ws_url))

            return

        except Exception as e:
            logger.warning("第 %s 次重连失败：%s", attempt, e)
            delay = min(delay * 2, max_delay)


def schedule_reconnect(
    manager,
    bot,
    proc: Optional[AppServerProcess],
    ws_url: str,
) -> bool:
    if manager.is_reconnect_inflight("codex"):
        logger.info("codex 重连已在进行中，跳过重复调度")
        return False

    async def _runner() -> None:
        try:
            await reconnect_loop(manager, bot, proc, ws_url)
        finally:
            manager.set_reconnect_inflight("codex", False)
            manager.set_reconnect_task("codex", None)

    manager.set_reconnect_inflight("codex", True)
    manager.set_reconnect_task("codex", asyncio.get_event_loop().create_task(_runner()))
    return True


async def monitor_process_health(
    manager,
    bot,
    proc: AppServerProcess,
    ws_url: str,
) -> None:
    logger.info("[monitor] app-server 进程健康监控已启动")
    check_interval = 60

    while True:
        await asyncio.sleep(check_interval)

        if not proc.running:
            logger.error("[monitor] 检测到 app-server 进程已停止，触发重连…")
            log_app_server_process_snapshot(proc, reason="process_monitor_detected_exit")
            adapter = manager.state.get_adapter("codex")
            if adapter:
                adapter._connected = False
            schedule_reconnect(manager, bot, proc, ws_url)
            break

        pid = proc._proc.pid if proc._proc else "?"
        logger.debug("[monitor] app-server 进程运行正常 (pid=%s)", pid)


async def start_runtime(manager, bot, tool_cfg) -> None:
    from plugins.providers.builtin.codex.python.tui_bridge import (
        is_codex_local_owner_mode,
        start_codex_tui_sync_loop,
        uses_codex_shared_live_transport,
    )
    from plugins.providers.builtin.codex.python.tui_realtime_mirror import (
        start_codex_tui_realtime_mirror_loop,
        touch_codex_tui_watch_state,
    )

    data_dir = manager.state.config.data_dir if manager.state.config is not None else None

    control_mode = getattr(tool_cfg, "control_mode", "app")
    if is_codex_local_owner_mode(manager.state):
        if control_mode == "tui":
            logger.info("codex 运行于 TUI 本地主控模式：不启动 shared app-server，TG 通过本地 host/runtime 注入，输出由本地 mirror 同步")
        else:
            logger.info("codex 运行于 App 本地 owner 模式：不启动 shared app-server，由 bot 进程托管本地 codex host/runtime")
        sync_task = manager.get_tui_sync_task("codex")
        if sync_task is None or sync_task.done():
            sync_task = start_codex_tui_sync_loop(manager.state, bot, manager.gid)
            manager.set_tui_sync_task("codex", sync_task)
        mirror_task = manager.get_tui_mirror_task("codex")
        if mirror_task is None or mirror_task.done():
            mirror_task = start_codex_tui_realtime_mirror_loop(
                manager.state,
                bot,
                manager.gid,
            )
            manager.set_tui_mirror_task("codex", mirror_task)
            codex_state.get_runtime(manager.state).mirror_task = mirror_task
            touch_codex_tui_watch_state(manager.state)
        return

    if clear_stale_host_artifacts(data_dir):
        logger.info("已清理 stale codex TUI host artifacts")

    proc = None
    ws_url = await resolve_connection_target(tool_cfg)
    if ws_url is None:
        managed_unix = (
            tool_cfg.protocol == "unix"
            and is_default_unix_endpoint(tool_cfg.app_server_url)
        )
        listen_url = (
            onlineworker_codex_unix_url()
            if managed_unix
            else tool_cfg.app_server_url
        )
        proc = AppServerProcess(
            codex_bin=tool_cfg.bin,
            port=tool_cfg.app_server_port,
            protocol=tool_cfg.protocol,
            **({"listen_url": listen_url} if tool_cfg.protocol == "unix" else {}),
            **({"owned_unix": True} if managed_unix else {}),
        )
        ws_url = await proc.start()
        manager.state.app_server_proc = proc

    if control_mode == "hybrid":
        logger.info("codex 运行于 Hybrid 主控模式：保持 shared app-server 可用，并建立常驻 owner adapter；TUI 可 attach 同一实例")
    else:
        logger.info("codex 运行于 App 主控模式：App 持有常驻 owner adapter；TG 走实时链路，TUI 仅按需 attach")
    await connect_adapter_with_retry(manager, bot, proc, ws_url)
    if is_unix_endpoint(ws_url):
        try:
            proxy_url = await ensure_codex_remote_message_proxy(manager.state, ws_url)
            logger.info("[codex] 已启动 Codex remote Unix proxy：%s", proxy_url)
        except Exception:
            logger.warning(
                "[codex] 启动 Codex remote Unix proxy 失败，外部 CLI 将只能直连 app-server：%s",
                ws_url,
                exc_info=True,
            )
    if uses_codex_shared_live_transport(manager.state):
        # app-server live events already stream final replies into Telegram.
        # The legacy final-reply polling loop reads the same session file and
        # can send a second copy, so keep only the realtime mirror fallback here.
        mirror_task = manager.get_tui_mirror_task("codex")
        if mirror_task is None or mirror_task.done():
            mirror_task = start_codex_tui_realtime_mirror_loop(
                manager.state,
                bot,
                manager.gid,
            )
            manager.set_tui_mirror_task("codex", mirror_task)
            codex_state.get_runtime(manager.state).mirror_task = mirror_task
            touch_codex_tui_watch_state(manager.state)
    elif control_mode == "app":
        mirror_task = manager.get_tui_mirror_task("codex")
        if mirror_task is None or mirror_task.done():
            mirror_task = start_codex_tui_realtime_mirror_loop(
                manager.state,
                bot,
                manager.gid,
            )
            manager.set_tui_mirror_task("codex", mirror_task)
            codex_state.get_runtime(manager.state).mirror_task = mirror_task
            touch_codex_tui_watch_state(manager.state)


async def shutdown_runtime(manager) -> None:
    from plugins.providers.builtin.codex.python.owner_bridge import stop_codex_owner_bridge
    sync_task = manager.get_tui_sync_task("codex")
    if sync_task and not sync_task.done():
        sync_task.cancel()
    manager.set_tui_sync_task("codex", None)
    mirror_task = manager.get_tui_mirror_task("codex")
    if mirror_task and not mirror_task.done():
        mirror_task.cancel()
    manager.set_tui_mirror_task("codex", None)
    for task in manager.get_stale_recovery_tasks("codex").values():
        if not task.done():
            task.cancel()
    manager.get_stale_recovery_tasks("codex").clear()
    tui_host = codex_state.get_tui_host(manager.state)
    if tui_host is not None:
        await tui_host.stop()
        codex_state.set_tui_host(manager.state, None)
    remote_proxy = codex_state.get_runtime(manager.state).remote_proxy
    if remote_proxy is not None:
        await remote_proxy.stop()
        codex_state.get_runtime(manager.state).remote_proxy = None
    await stop_codex_owner_bridge(manager.state)
    adapter = manager.state.get_adapter("codex")
    if adapter:
        await adapter.disconnect()
        manager.state.set_adapter("codex", None)
    if manager.state.app_server_proc:
        await manager.state.app_server_proc.stop()


def _mode_label(state) -> str:
    tool_cfg = state.config.get_tool("codex") if state.config is not None else None
    codex_mode = tool_cfg.control_mode if tool_cfg is not None else "app"
    return {
        "app": "App",
        "tui": "TUI",
        "hybrid": "Hybrid",
    }.get(codex_mode, codex_mode)


def build_status_lines(state) -> list[str]:
    lines: list[str] = []
    codex_mode_label = _mode_label(state)
    tool_cfg = state.config.get_tool("codex") if state.config is not None else None
    control_mode = tool_cfg.control_mode if tool_cfg is not None else "app"

    if state.is_adapter_connected("codex"):
        lines.append(f"• codex app-server：✅ 已连接 ({codex_mode_label})")
        return lines

    if control_mode == "tui":
        host_status = read_host_status(
            state.config.data_dir if state.config is not None else None,
        )
        if host_status and host_status.get("online"):
            lines.append("• codex 本地 owner：✅ 已运行（host/runtime）")
        else:
            lines.append("• codex 本地 owner：⏳ 待按需启动（host/runtime）")
        return lines

    if control_mode == "hybrid":
        lines.append(f"• codex app-server：❌ 未连接 ({codex_mode_label})")
        return lines

    lines.append(f"• codex app-server：❌ 未连接 ({codex_mode_label})")
    return lines
