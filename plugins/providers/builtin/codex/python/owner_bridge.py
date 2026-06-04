from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from config import get_data_dir
from core.messages.publishing import (
    publish_user_message_accepted,
    publish_user_message_submitted,
)
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text
from plugins.providers.builtin.codex.python.adapter import DEFAULT_APPROVALS_REVIEWER
from plugins.providers.builtin.codex.python import runtime_state as codex_state


OWNER_BRIDGE_SOCKET_FILENAME = "codex_owner_bridge.sock"
logger = logging.getLogger(__name__)


def owner_bridge_socket_path(data_dir: Optional[str] = None) -> Optional[str]:
    resolved = data_dir if data_dir is not None else get_data_dir()
    if not resolved:
        return None
    return os.path.join(resolved, OWNER_BRIDGE_SOCKET_FILENAME)


def _resolve_workspace_id(state, adapter, thread_id: str, cwd: str) -> Optional[str]:
    thread_map = getattr(adapter, "_thread_workspace_map", {})
    if isinstance(thread_map, dict):
        mapped = thread_map.get(thread_id)
        if isinstance(mapped, str) and mapped:
            return mapped

    storage = getattr(state, "storage", None)
    workspaces = getattr(storage, "workspaces", {}) if storage is not None else {}
    for storage_key, ws in workspaces.items():
        if getattr(ws, "tool", "") != "codex":
            continue
        threads = getattr(ws, "threads", {}) or {}
        if thread_id in threads:
            return getattr(ws, "daemon_workspace_id", None) or storage_key

    normalized_cwd = cwd.strip()
    if not normalized_cwd:
        return None

    for storage_key, ws in workspaces.items():
        if getattr(ws, "tool", "") != "codex":
            continue
        if getattr(ws, "path", "") != normalized_cwd:
            continue
        return getattr(ws, "daemon_workspace_id", None) or storage_key

    return f"codex:{normalized_cwd}"


def _extract_started_thread_id(result: object) -> str:
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    if not thread_id:
        raise RuntimeError(f"Codex start_thread 返回无效 thread id：{result}")
    return str(thread_id)


def _ensure_storage_workspace(state, workspace_id: str, cwd: str):
    from core.storage import AppStorage, WorkspaceInfo

    if getattr(state, "storage", None) is None:
        state.storage = AppStorage()

    storage = state.storage
    ws_info = storage.workspaces.get(workspace_id)
    if ws_info is None:
        ws_info = WorkspaceInfo(
            name=os.path.basename(cwd) or cwd,
            path=cwd,
            tool="codex",
            daemon_workspace_id=workspace_id,
        )
        storage.workspaces[workspace_id] = ws_info
    else:
        if cwd:
            ws_info.path = cwd
        ws_info.tool = "codex"
        ws_info.daemon_workspace_id = workspace_id
    return ws_info


def _persist_storage(state, data_dir: Optional[str]) -> None:
    from core.storage import STORAGE_PATH, save_storage

    storage = getattr(state, "storage", None)
    if storage is None:
        return

    if data_dir:
        save_storage(storage, path=os.path.join(data_dir, STORAGE_PATH))
    else:
        save_storage(storage)


async def _send_on_thread(
    adapter,
    workspace_id: str,
    thread_id: str,
    text: str,
    attachments,
    *,
    approval_policy=None,
    approvals_reviewer=None,
    sandbox_policy=None,
):
    from bot.handlers.common import is_codex_unmaterialized_error

    try:
        await adapter.resume_thread(workspace_id, thread_id)
    except Exception as exc:
        if not is_codex_unmaterialized_error(exc):
            raise
    send_kwargs = {}
    if approval_policy is not None:
        send_kwargs["approval_policy"] = approval_policy
    if approvals_reviewer is not None:
        send_kwargs["approvals_reviewer"] = approvals_reviewer
    if sandbox_policy is not None:
        send_kwargs["sandbox_policy"] = sandbox_policy
    await adapter.send_user_message(
        workspace_id,
        thread_id,
        text,
        attachments=attachments,
        **send_kwargs,
    )


async def _remap_unmaterialized_thread_for_app_send(
    state,
    adapter,
    *,
    workspace_id: str,
    cwd: str,
    requested_thread_id: str,
    preview: str | None,
    data_dir: Optional[str],
) -> str:
    from core.storage import ThreadInfo

    result = await adapter.start_thread(workspace_id)
    new_thread_id = _extract_started_thread_id(result)
    if new_thread_id == requested_thread_id:
        raise RuntimeError("Codex start_thread 返回了与原 thread 相同的 thread id")

    ws_info = _ensure_storage_workspace(state, workspace_id, cwd)
    existing_thread = ws_info.threads.get(requested_thread_id)
    if existing_thread is not None:
        existing_thread.is_active = False

    ws_info.threads[new_thread_id] = ThreadInfo(
        thread_id=new_thread_id,
        preview=preview,
        archived=False,
        is_active=True,
        source="app",
    )
    adapter._thread_workspace_map[new_thread_id] = workspace_id
    _persist_storage(state, data_dir)
    logger.info(
        "[codex-owner-bridge] 旧 thread 物化失败，切换到新 app thread old=%s new=%s workspace=%s",
        requested_thread_id[:12],
        new_thread_id[:12],
        workspace_id,
    )
    return new_thread_id


class CodexOwnerBridge:
    def __init__(self, state, *, data_dir: Optional[str] = None):
        self.state = state
        self.data_dir = data_dir if data_dir is not None else get_data_dir()
        self.socket_path = owner_bridge_socket_path(self.data_dir)
        self._server: Optional[asyncio.base_events.Server] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        if self.is_running:
            return
        if not self.socket_path:
            raise RuntimeError("缺少 data_dir，无法启动 codex owner bridge")

        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        logger.info("[codex-owner-bridge] 已启动 socket=%s", self.socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        if self.socket_path:
            logger.info("[codex-owner-bridge] 已停止 socket=%s", self.socket_path)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            raw = await reader.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            request_type = request.get("type")
            if request_type == "send_message":
                response = await self._handle_send_message(request)
            else:
                response = {
                    "ok": False,
                    "error": f"unsupported request type: {request_type}",
                }
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_send_message(self, request: dict) -> dict:
        from bot.handlers.common import is_codex_unmaterialized_error

        thread_id = str(request.get("thread_id") or "").strip()
        text = str(request.get("text") or "").strip()
        cwd = str(request.get("cwd") or "").strip()
        attachments = request.get("attachments") or []
        source = str(request.get("source") or "session_tab").strip() or "session_tab"
        approval_policy = request.get("approval_policy")
        approvals_reviewer = request.get("approvals_reviewer")
        sandbox_policy = request.get("sandbox_policy")

        if not thread_id:
            return {"ok": False, "error": "缺少 thread_id"}
        if not text and not attachments:
            return {"ok": False, "error": "空消息，拒绝发送"}

        adapter = self.state.get_adapter("codex")
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": "codex owner adapter 未连接"}

        workspace_id = _resolve_workspace_id(self.state, adapter, thread_id, cwd)
        if workspace_id:
            register_workspace_cwd = getattr(adapter, "register_workspace_cwd", None)
            if cwd and callable(register_workspace_cwd):
                register_workspace_cwd(workspace_id, cwd)
            adapter._thread_workspace_map[thread_id] = workspace_id
        else:
            workspace_id = ""

        gateway_result = await prepare_user_message_text(
            self.state,
            UserMessageSendRequest(
                source=source,
                provider_id="codex",
                workspace_id=str(workspace_id),
                thread_id=thread_id,
                text=text,
                attachments=attachments,
            ),
        )
        text = gateway_result.text
        message_event_request = UserMessageSendRequest(
            source=source,
            provider_id="codex",
            workspace_id=str(workspace_id),
            thread_id=thread_id,
            text=text,
            attachments=attachments,
            metadata={"bridge": "codex_owner"},
        )
        publish_user_message_submitted(
            self.state,
            message_event_request,
            text=text,
            workspace_path=cwd,
        )

        tracked_thread = None
        if hasattr(self.state, "find_thread_by_id_global"):
            found = self.state.find_thread_by_id_global(thread_id)
            if found is not None:
                _, tracked_thread = found
        preview = getattr(tracked_thread, "preview", None)
        can_remap = bool(cwd) and (
            tracked_thread is None or getattr(tracked_thread, "source", "unknown") != "app"
        )
        requested_thread_id = thread_id
        effective_thread_id = thread_id
        created_new_thread = False
        logger.info(
            "[codex-owner-bridge] send_message thread=%s workspace=%s cwd=%s",
            thread_id,
            workspace_id or "-",
            cwd or "-",
        )

        try:
            codex_state.mark_send_started(self.state, effective_thread_id)
            self.state.mark_provider_task_summary("codex", effective_thread_id, text)
            if workspace_id:
                try:
                    await _send_on_thread(
                        adapter,
                        workspace_id,
                        effective_thread_id,
                        text,
                        attachments,
                        approval_policy=approval_policy,
                        approvals_reviewer=approvals_reviewer,
                        sandbox_policy=sandbox_policy,
                    )
                except Exception as exc:
                    if not (can_remap and is_codex_unmaterialized_error(exc)):
                        raise
                    effective_thread_id = await _remap_unmaterialized_thread_for_app_send(
                        self.state,
                        adapter,
                        workspace_id=workspace_id,
                        cwd=cwd,
                        requested_thread_id=requested_thread_id,
                        preview=preview,
                        data_dir=self.data_dir,
                    )
                    created_new_thread = effective_thread_id != requested_thread_id
                    codex_state.mark_send_started(self.state, effective_thread_id)
                    self.state.mark_provider_task_summary("codex", effective_thread_id, text)
                    await _send_on_thread(
                        adapter,
                        workspace_id,
                        effective_thread_id,
                        text,
                        attachments,
                        approval_policy=approval_policy,
                        approvals_reviewer=approvals_reviewer,
                        sandbox_policy=sandbox_policy,
                    )
            else:
                try:
                    await adapter._call("thread/resume", {"threadId": thread_id})
                except Exception as exc:
                    if not is_codex_unmaterialized_error(exc):
                        raise
                input_items = []
                if text:
                    input_items.append({"type": "text", "text": text})
                for attachment in attachments:
                    if not isinstance(attachment, dict):
                        continue
                    kind = str(attachment.get("kind") or "").strip().lower()
                    path = str(attachment.get("path") or "").strip()
                    name = str(attachment.get("name") or "").strip()
                    if kind == "image" and path:
                        input_items.append({"type": "localImage", "path": path})
                    elif kind == "file":
                        summary = f"[Attached file] {name or path}"
                        if path:
                            summary = f"{summary}\nPath: {path}"
                        input_items.append({"type": "text", "text": summary})
                turn_params = {
                    "threadId": thread_id,
                    "input": input_items,
                    "approvalsReviewer": approvals_reviewer or DEFAULT_APPROVALS_REVIEWER,
                }
                if approval_policy is not None:
                    turn_params["approvalPolicy"] = approval_policy
                if sandbox_policy is not None:
                    normalize_sandbox_policy = getattr(
                        adapter,
                        "_normalize_sandbox_policy_for_app_server",
                        None,
                    )
                    if callable(normalize_sandbox_policy):
                        sandbox_policy = normalize_sandbox_policy(sandbox_policy)
                    turn_params["sandboxPolicy"] = sandbox_policy
                await adapter._call("turn/start", turn_params)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        if workspace_id and cwd:
            _ensure_storage_workspace(self.state, workspace_id, cwd)
            _persist_storage(self.state, self.data_dir)
        publish_user_message_accepted(
            self.state,
            UserMessageSendRequest(
                source=source,
                provider_id="codex",
                workspace_id=str(workspace_id),
                thread_id=effective_thread_id,
                text=text,
                attachments=attachments,
                metadata={"bridge": "codex_owner"},
            ),
            text=text,
            workspace_path=cwd,
        )

        return {
            "ok": True,
            "accepted": True,
            "requested_thread_id": requested_thread_id,
            "thread_id": effective_thread_id,
            "workspace_id": workspace_id,
            "created_new_thread": created_new_thread,
        }


async def ensure_codex_owner_bridge_started(state) -> Optional[CodexOwnerBridge]:
    bridge = codex_state.get_owner_bridge(state)
    if bridge is not None and bridge.is_running:
        return bridge

    bridge = CodexOwnerBridge(state)
    if not bridge.socket_path:
        logger.info("[codex-owner-bridge] 缺少 data_dir，跳过 owner bridge 启动")
        return None
    await bridge.start()
    codex_state.set_owner_bridge(state, bridge)
    return bridge


async def stop_codex_owner_bridge(state) -> None:
    bridge = codex_state.get_owner_bridge(state)
    if bridge is None:
        return
    await bridge.stop()
    codex_state.set_owner_bridge(state, None)
