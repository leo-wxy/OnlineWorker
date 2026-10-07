import time
from dataclasses import replace

from core.messages.events import create_message_event
from core.storage import save_storage


def new_session_recovery_view(thread):
    record = thread.new_session_recovery
    return {
        **record,
        "kind": "new-session", "requestId": record.get("request_id", ""),
        "status": "preparing" if record.get("send_status") == "pending" else record.get("send_status", "unknown"),
        "text": record.get("text", ""), "attachments": record.get("attachments", []),
        "error": record.get("error") or record.get("bind_error", ""), "updatedAt": record.get("updated_at", 0),
        "threadId": thread.thread_id,
    }


def publish_send_recovery(state, workspace, thread):
    record = dict(thread.send_recovery)
    if not record:
        return
    event = create_message_event(
        "session.recovery.updated", provider_id=workspace.tool, session_id=thread.thread_id,
        workspace_id=workspace.daemon_workspace_id or f"{workspace.tool}:{workspace.path}",
        workspace_path=workspace.path, source="send_recovery",
        created_at=record.get("updatedAt", 0),
        payload={"sendRecovery": {key: record.get(key) for key in ("requestId", "status", "error")},
                 "error": record.get("error", "")},
    )
    # Original input and attachment paths belong only in the private session projection.
    state.message_bus.publish(replace(event, conversation_payload={"sendRecovery": record}))


def record_delivery_receipt(state, workspace, thread, request_id, receipt, *, require_persistence=False):
    if thread.archived or workspace.threads.get(thread.thread_id) is not thread:
        return
    is_new = thread.send_recovery.get("requestId") != request_id
    record = thread.new_session_recovery if is_new else thread.send_recovery
    if record.get("request_id" if is_new else "requestId") != request_id:
        return
    record["providerReceipt"] = {**receipt, "requestId": request_id}
    try:
        save_storage(state.storage)
    except Exception as exc:
        # A receipt write failure never makes an accepted message safe to retry.
        record["error"] = f"Provider 回执保存失败: {exc}"
        if require_persistence:
            raise
    if is_new:
        from core.provider_session_new import publish_new_session_recovery
        publish_new_session_recovery(state, workspace, thread)
    else:
        publish_send_recovery(state, workspace, thread)


def checkpoint_send_recovery(state, workspace, thread, status, error=""):
    thread.send_recovery = {**thread.send_recovery, "status": status, "error": str(error), "updatedAt": time.time()}
    failure = None
    try:
        if state.storage is None:
            raise RuntimeError("会话存储不可用")
        save_storage(state.storage)
    except Exception as exc:
        failure = exc
        if status in {"preparing", "sending"}:
            thread.send_recovery["status"] = "failed"
        prefix = "消息已发送，但恢复记录保存失败" if status == "sent" else "恢复记录保存失败"
        thread.send_recovery["error"] = f"{prefix}: {exc}"
    publish_send_recovery(state, workspace, thread)
    if failure is not None and status in {"preparing", "sending"}:
        raise RuntimeError(thread.send_recovery["error"]) from failure


def restore_send_recoveries(state):
    for workspace in getattr(state.storage, "workspaces", {}).values():
        pending = workspace.pending_new_session
        if pending and any(thread.new_session_recovery.get("request_id") == pending.get("requestId")
                           for thread in workspace.threads.values()):
            workspace.pending_new_session = {}
            pending = {}
        if pending and pending.get("status") == "preparing":
            pending.update(status="unknown", error="创建过程中服务已重启，结果未知，原输入已保留。")
            try:
                save_storage(state.storage)
            except Exception:
                pass  # Keep the request blocked even when its recovery write fails.
        for thread in workspace.threads.values():
            if thread.archived:
                continue
            new_record = thread.new_session_recovery
            if new_record:
                from core.provider_session_new import _checkpoint_new_session, publish_new_session_recovery
                if new_record.get("send_status") in {"pending", "preparing", "sending"}:
                    new_record["send_status"] = "unknown" if new_record["send_status"] == "sending" else "failed"
                    new_record["error"] = "服务已重启，原请求已保留，请先核实会话。"
                    try:
                        _checkpoint_new_session(state, workspace, thread)
                    except Exception:
                        pass  # The checkpoint has already published the persistence failure.
                else:
                    publish_new_session_recovery(state, workspace, thread)
            record = thread.send_recovery
            if not record:
                continue
            if record.get("status") == "preparing":
                checkpoint_send_recovery(state, workspace, thread, "failed", "发送在提交前中断，可恢复原输入后重试。")
            elif record.get("status") == "sending":
                checkpoint_send_recovery(state, workspace, thread, "unknown", "发送过程中服务已重启，结果未知，请先核实原会话。")
            elif record.get("status") in {"failed", "unknown"}:
                publish_send_recovery(state, workspace, thread)
