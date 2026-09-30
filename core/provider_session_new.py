from __future__ import annotations

from dataclasses import dataclass

from core.messages.publishing import (
    publish_user_message_accepted,
    publish_user_message_submitted,
    report_user_message_failure,
)
from core.providers.registry import get_provider
from core.storage import ThreadInfo, WorkspaceInfo, save_storage
from core.messages.events import create_message_event
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text


@dataclass(frozen=True)
class StartedProviderThread:
    thread_id: str
    thread_info: ThreadInfo
    created_thread: bool


@dataclass(frozen=True)
class SentProviderThreadMessage:
    thread_id: str
    text: str


class _FirstMessageRejected(RuntimeError):
    pass


def _checkpoint_new_session(state, ws_info, thread_info):
    recovery = thread_info.new_session_recovery
    try:
        if state.storage is not None:
            save_storage(state.storage)
    except Exception as exc:
        prefix = "首消息已发送，保存恢复状态失败" if recovery.get("send_status") == "sent" else "保存恢复状态失败"
        recovery["error"] = f"{prefix}: {exc}"
        state.message_bus.publish(create_message_event(
            "session.recovery.updated", provider_id=ws_info.tool, session_id=thread_info.thread_id,
            workspace_id=ws_info.daemon_workspace_id or "", workspace_path=ws_info.path,
            payload={"summary": recovery["error"], "recoveryStatus": recovery.get("send_status", "pending"), "error": recovery["error"], "text": recovery.get("text", ""), "title": thread_info.preview or ""},
        ))
        raise
    state.message_bus.publish(create_message_event(
        "session.recovery.updated", provider_id=ws_info.tool, session_id=thread_info.thread_id,
        workspace_id=ws_info.daemon_workspace_id or "", workspace_path=ws_info.path,
        payload={"recoveryStatus": recovery.get("send_status", "pending"), "error": recovery.get("error") or recovery.get("bind_error", ""), "text": recovery.get("text", ""), "title": thread_info.preview or ""},
    ))


def extract_started_thread_id(result: object) -> str:
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    return str(thread_id or "").strip()


def _new_thread_info(thread_id: str, *, source: str) -> ThreadInfo:
    return ThreadInfo(thread_id=thread_id, is_active=True, source=source)


def validate_new_provider_thread_request(
    state,
    ws_info: WorkspaceInfo,
    *,
    text: str | None,
    attachments,
    provider=None,
) -> str | None:
    resolved_provider = provider or get_provider(str(getattr(ws_info, "tool", "") or ""), getattr(state, "config", None))
    thread_hooks = getattr(resolved_provider, "thread_hooks", None) if resolved_provider is not None else None
    validate_new_thread = getattr(thread_hooks, "validate_new_thread", None) if thread_hooks is not None else None
    if not callable(validate_new_thread):
        return None

    normalized_text = str(text or "").strip()
    initial_text = normalized_text if normalized_text else ("<attachment>" if attachments else None)
    return validate_new_thread(state, ws_info, initial_text)


async def start_real_provider_thread(
    adapter, ws_info, workspace_id, **kwargs,
):
    state = kwargs.get("state")
    if state is None:
        return await _start_real_provider_thread(adapter, ws_info, workspace_id, **kwargs)
    # ponytail: serialize creation per app state; use per-request locks if throughput matters.
    async with state.new_session_lock:
        return await _start_real_provider_thread(adapter, ws_info, workspace_id, **kwargs)


async def _start_real_provider_thread(
    adapter,
    ws_info: WorkspaceInfo,
    workspace_id: str,
    *,
    provider_id: str,
    preview: str | None,
    source: str,
    state=None,
    recovery_key: str = "",
    attachments=None,
) -> StartedProviderThread:
    if recovery_key:
        for thread_info in ws_info.threads.values():
            recovery = thread_info.new_session_recovery
            if recovery.get("request_id") == recovery_key:
                if recovery.get("text") != (preview or "") or recovery.get("attachments", []) != (attachments or []):
                    raise ValueError("恢复请求与原始首消息不一致")
                return StartedProviderThread(thread_info.thread_id, thread_info, False)
    start_thread = getattr(adapter, "start_thread", None)
    if not callable(start_thread):
        raise RuntimeError(f"{provider_id} adapter 不支持创建会话")

    result = await start_thread(workspace_id)
    thread_id = extract_started_thread_id(result)
    if not thread_id:
        raise RuntimeError(f"{provider_id} start_thread 返回无效 thread id")
    if thread_id.startswith(f"app:{provider_id}:"):
        raise RuntimeError(f"{provider_id} start_thread 返回了本地占位 thread id")

    existing_thread = ws_info.threads.get(thread_id)
    created_thread = existing_thread is None
    thread_info = existing_thread or _new_thread_info(thread_id, source=source)
    thread_info.thread_id = thread_id
    thread_info.preview = preview or getattr(thread_info, "preview", None)
    thread_info.archived = False
    thread_info.is_active = True
    if str(getattr(thread_info, "source", "") or "").strip() in {"", "unknown"}:
        thread_info.source = source
    ws_info.threads[thread_id] = thread_info
    if state is not None:
        thread_info.new_session_recovery = {
            "request_id": recovery_key, "text": preview or "", "attachments": attachments or [],
            "send_status": "pending", "bind_status": "pending" if source == "telegram_new_thread" else "not_required",
        }
        _checkpoint_new_session(state, ws_info, thread_info)

    return StartedProviderThread(
        thread_id=thread_id,
        thread_info=thread_info,
        created_thread=created_thread,
    )


def build_provider_session_summary(
    ws_info: WorkspaceInfo,
    thread_info: ThreadInfo,
    *,
    preview_text: str | None,
    provider_active: bool,
    now: int,
) -> dict:
    thread_id = str(getattr(thread_info, "thread_id", "") or "")
    preview = str(preview_text or getattr(thread_info, "preview", "") or "")
    return {
        "id": thread_id,
        "title": preview or thread_id,
        "preview": preview,
        "workspace": str(getattr(ws_info, "path", "") or ""),
        "archived": bool(getattr(thread_info, "archived", False)),
        "providerActive": bool(provider_active),
        "updatedAt": now,
        "createdAt": now,
        "source": str(getattr(thread_info, "source", "") or "provider"),
    }


async def send_started_provider_thread_message(state, ws_info, thread_info, workspace_id, **kwargs):
    recovery = thread_info.new_session_recovery
    if not recovery:
        return await _send_started_provider_thread_message(state, ws_info, thread_info, workspace_id, **kwargs)
    status = recovery.get("send_status")
    if status == "sent":
        recovery.pop("error", None)
        _checkpoint_new_session(state, ws_info, thread_info)
        return SentProviderThreadMessage(thread_info.thread_id, recovery.get("sent_text", recovery.get("text", "")))
    if status in {"sending", "unknown"}:
        raise RuntimeError("首消息发送结果不确定，请先核实原会话；禁止自动重复发送")
    recovery.pop("error", None)
    recovery["send_status"] = "sending"
    try:
        _checkpoint_new_session(state, ws_info, thread_info)
    except Exception:
        recovery["send_status"] = "pending"
        raise
    try:
        result = await _send_started_provider_thread_message(state, ws_info, thread_info, workspace_id, **kwargs)
    except BaseException as exc:
        recovery["send_status"] = "failed" if isinstance(exc, _FirstMessageRejected) else "unknown"
        recovery["error"] = str(exc) if isinstance(exc, _FirstMessageRejected) else f"首消息发送结果不确定，请先核实原会话: {exc}"
        _checkpoint_new_session(state, ws_info, thread_info)
        raise
    recovery.update(send_status="sent", sent_text=result.text)
    _checkpoint_new_session(state, ws_info, thread_info)
    return result


async def _send_started_provider_thread_message(
    state,
    ws_info: WorkspaceInfo,
    thread_info: ThreadInfo,
    workspace_id: str,
    *,
    provider_id: str,
    text: str,
    attachments,
    source: str,
    provider=None,
    adapter=None,
    metadata: dict | None = None,
) -> SentProviderThreadMessage:
    resolved_provider = provider or get_provider(
        str(getattr(ws_info, "tool", "") or ""),
        getattr(state, "config", None),
    )
    if resolved_provider is None:
        raise RuntimeError(f"Provider '{provider_id}' 未启用")

    prepared = await prepare_user_message_text(
        state,
        UserMessageSendRequest(
            source=source,
            provider_id=provider_id,
            workspace_id=str(workspace_id),
            thread_id=str(thread_info.thread_id),
            text=text,
            attachments=attachments,
            metadata=metadata or {},
        ),
    )
    prepared_text = prepared.text

    message_request = UserMessageSendRequest(
        source=source,
        provider_id=provider_id,
        workspace_id=str(workspace_id),
        thread_id=str(thread_info.thread_id),
        text=prepared_text,
        attachments=attachments,
        metadata=metadata or {},
    )
    publish_user_message_submitted(
        state,
        message_request,
        text=prepared_text,
        workspace_path=str(getattr(ws_info, "path", "") or ""),
    )

    with report_user_message_failure(
        state, message_request, text=prepared_text,
        workspace_path=str(getattr(ws_info, "path", "") or ""),
    ):
        message_hooks = getattr(resolved_provider, "message_hooks", None)
        if message_hooks is not None:
            resolved_adapter = adapter
            ensure_connected = getattr(message_hooks, "ensure_connected", None)
            if callable(ensure_connected):
                connected_adapter = await ensure_connected(
                    state,
                    resolved_adapter,
                    ws_info,
                    update=None,
                    context=None,
                    group_chat_id=0,
                    src_topic_id=None,
                )
                if connected_adapter is not None:
                    resolved_adapter = connected_adapter
                    if hasattr(state, "set_adapter"):
                        state.set_adapter(provider_id, resolved_adapter)

            if resolved_adapter is None:
                raise RuntimeError(f"{provider_id} adapter 未连接")

            if hasattr(state, "mark_provider_send_started"):
                state.mark_provider_send_started(provider_id, str(thread_info.thread_id))

            send_result = await message_hooks.send(
                state,
                resolved_adapter,
                ws_info,
                thread_info,
                update=None,
                context=None,
                group_chat_id=0,
                src_topic_id=None,
                text=prepared_text,
                has_photo=False,
                attachments=attachments,
            )
            if isinstance(send_result, dict) and str(send_result.get("status") or "") == "error":
                raise _FirstMessageRejected(str(send_result.get("error") or f"{provider_id} send failed"))
        else:
            resolved_adapter = adapter
            if resolved_adapter is None:
                raise RuntimeError(f"{provider_id} adapter 未连接")

            thread_hooks = getattr(resolved_provider, "thread_hooks", None)
            activate_new_thread = getattr(thread_hooks, "activate_new_thread", None) if thread_hooks is not None else None
            if callable(activate_new_thread):
                await activate_new_thread(
                    state,
                    resolved_adapter,
                    ws_info,
                    workspace_id,
                    str(thread_info.thread_id),
                    prepared_text,
                )
            else:
                await resolved_adapter.resume_thread(workspace_id, str(thread_info.thread_id))
                if prepared_text:
                    await resolved_adapter.send_user_message(
                        workspace_id,
                        str(thread_info.thread_id),
                        prepared_text,
                    )

        publish_user_message_accepted(
            state, message_request, text=prepared_text,
            workspace_path=str(getattr(ws_info, "path", "") or ""),
        )

        return SentProviderThreadMessage(
            thread_id=str(thread_info.thread_id),
            text=prepared_text,
        )
