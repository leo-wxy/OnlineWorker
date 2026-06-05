from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from types import SimpleNamespace
from typing import Optional

from config import get_data_dir
from core.providers.registry import get_provider
from core.storage import ThreadInfo, WorkspaceInfo, save_storage
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text
from core.messages.publishing import (
    publish_user_message_accepted,
    publish_user_message_submitted,
)


OWNER_BRIDGE_SOCKET_FILENAME = "provider_owner_bridge.sock"
logger = logging.getLogger(__name__)


def provider_owner_bridge_socket_path(data_dir: Optional[str] = None) -> Optional[str]:
    resolved = data_dir if data_dir is not None else get_data_dir()
    if not resolved:
        return None
    return os.path.join(resolved, OWNER_BRIDGE_SOCKET_FILENAME)


def _workspace_key(provider_id: str, workspace_dir: str) -> str:
    return f"{provider_id}:{workspace_dir}"


def _resolve_workspace_and_thread(state, provider_id: str, thread_id: str, workspace_dir: str):
    normalized_thread_id = str(thread_id or "").strip()
    normalized_workspace_dir = str(workspace_dir or "").strip()

    if normalized_thread_id:
        found = state.find_thread_by_id_global(normalized_thread_id)
        if found is not None:
            return found

    if not normalized_workspace_dir:
        return None, None

    storage = getattr(state, "storage", None)
    if storage is not None:
        for storage_key, ws in storage.workspaces.items():
            if getattr(ws, "tool", "") != provider_id:
                continue
            if getattr(ws, "path", "") != normalized_workspace_dir:
                continue
            thread = ws.threads.get(normalized_thread_id)
            if thread is None:
                thread = storage.workspaces[storage_key].threads.setdefault(
                    normalized_thread_id,
                    _new_thread_info(
                        normalized_thread_id,
                        source=_new_thread_source(provider_id),
                    ),
                )
            return ws, thread

        workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
        ws = WorkspaceInfo(
            name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
            path=normalized_workspace_dir,
            tool=provider_id,
            topic_id=None,
            daemon_workspace_id=workspace_id,
            threads={},
        )
        thread = _new_thread_info(
            normalized_thread_id,
            source=_new_thread_source(provider_id),
        )
        ws.threads[normalized_thread_id] = thread
        storage.workspaces[workspace_id] = ws
        try:
            save_storage(storage)
        except Exception:
            logger.debug("[provider-owner-bridge] 保存临时 workspace 失败", exc_info=True)
        return ws, thread

    workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
    ws = SimpleNamespace(
        name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
        path=normalized_workspace_dir,
        tool=provider_id,
        topic_id=None,
        daemon_workspace_id=workspace_id,
        threads={},
    )
    thread = _new_thread_info(
        normalized_thread_id,
        source=_new_thread_source(provider_id),
    )
    ws.threads[normalized_thread_id] = thread
    return ws, thread


def _resolve_workspace_and_thread_for_mirror(state, provider_id: str, thread_id: str, workspace_dir: str):
    normalized_thread_id = str(thread_id or "").strip()
    normalized_workspace_dir = str(workspace_dir or "").strip()

    if normalized_thread_id:
        found = state.find_thread_by_id_global(normalized_thread_id)
        if found is not None:
            return found

    if getattr(state, "storage", None) is not None and normalized_workspace_dir:
        for ws in state.storage.workspaces.values():
            if getattr(ws, "tool", "") != provider_id:
                continue
            if getattr(ws, "path", "") != normalized_workspace_dir:
                continue
            thread = ws.threads.get(normalized_thread_id)
            if thread is None:
                thread = _new_thread_info(
                    normalized_thread_id,
                    source=_new_thread_source(provider_id),
                )
            return ws, thread

    if not normalized_workspace_dir:
        return None, None

    workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
    ws = SimpleNamespace(
        name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
        path=normalized_workspace_dir,
        tool=provider_id,
        topic_id=None,
        daemon_workspace_id=workspace_id,
        threads={},
    )
    thread = _new_thread_info(
        normalized_thread_id,
        source=_new_thread_source(provider_id),
    )
    return ws, thread


def _new_thread_source(provider_id: str) -> str:
    provider = get_provider(provider_id)
    thread_hooks = getattr(provider, "thread_hooks", None) if provider is not None else None
    resolver = (
        getattr(thread_hooks, "new_imported_thread_source", None)
        if thread_hooks is not None
        else None
    )
    if callable(resolver):
        source = str(resolver() or "").strip()
        if source:
            return source
    return "app"


def _new_thread_info(thread_id: str, *, source: str = "app"):
    return ThreadInfo(
        thread_id=thread_id,
        topic_id=None,
        preview=None,
        archived=False,
        streaming_msg_id=None,
        last_tg_user_message_id=None,
        history_sync_cursor=None,
        is_active=True,
        source=source,
    )


def _runtime_health_from_lines(lines: list[str], adapter) -> str:
    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    for line in normalized_lines:
        lowered = line.lower()
        if (
            "⚠️" in line
            or "未鉴权" in line
            or "不可用" in line
            or "unavailable" in lowered
            or "not logged in" in lowered
        ):
            return "degraded"
        if "✅" in line or "已连接" in line or "connected" in lowered or "healthy" in lowered:
            return "healthy"
        if (
            "❌" in line
            or "已断开" in line
            or "disconnected" in lowered
            or "degraded" in lowered
            or "failed" in lowered
        ):
            return "degraded"
        if "未启动" in line or "stopped" in lowered:
            return "stopped"
    if adapter is not None:
        return "healthy" if bool(getattr(adapter, "connected", False)) else "degraded"
    return "unknown"


def _normalize_provider_turn_content(turn: dict) -> str:
    content = str(turn.get("content") or turn.get("text") or "").strip()
    if content:
        return content
    if str(turn.get("kind") or "").strip() == "error":
        return str(turn.get("error") or "").strip()
    return ""


def _normalize_provider_turn(turn: dict) -> dict:
    role = str(turn.get("role") or "").strip()
    normalized = {
        "role": role,
        "content": _normalize_provider_turn_content(turn),
    }

    kind = str(turn.get("kind") or "").strip()
    display_mode = str(turn.get("displayMode") or turn.get("display_mode") or "").strip()
    if display_mode in {"plain", "markdown"}:
        normalized["displayMode"] = display_mode
    elif kind == "error":
        normalized["displayMode"] = "plain"
    if kind:
        normalized["kind"] = kind

    return normalized


def _approval_mirror_dedupe_key(
    provider_id: str,
    thread_id: str,
    workspace_dir: str,
    payload: dict,
) -> str:
    command = _approval_mirror_command(payload)
    return "\x1f".join(
        [
            str(provider_id or ""),
            str(thread_id or ""),
            str(workspace_dir or ""),
            str(command or ""),
        ]
    )


def _approval_mirror_command(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    command = payload.get("command")
    if not command and isinstance(tool_input, dict):
        command = tool_input.get("command") or tool_input.get("cmd")
    if command is None:
        command = payload.get("tool_name") or ""
    return str(command or "")


async def _status_lines_for_provider(state, provider_id: str, provider) -> list[str]:
    status_builder = getattr(provider, "status_builder", None)
    if callable(status_builder):
        raw_lines = status_builder(state)
        if inspect.isawaitable(raw_lines):
            raw_lines = await raw_lines
        return [str(line).strip() for line in (raw_lines or []) if str(line).strip()]

    adapter = state.get_adapter(provider_id)
    if adapter is not None and getattr(adapter, "connected", False):
        return [f"• {provider_id}：✅ 已连接"]
    if adapter is not None:
        return [f"• {provider_id}：❌ 已断开"]
    return []


class ProviderOwnerBridge:
    def __init__(self, state, *, data_dir: Optional[str] = None):
        self.state = state
        self.data_dir = data_dir if data_dir is not None else get_data_dir()
        self.socket_path = provider_owner_bridge_socket_path(self.data_dir)
        self._server: Optional[asyncio.base_events.Server] = None

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        if self.is_running:
            return
        if not self.socket_path:
            raise RuntimeError("缺少 data_dir，无法启动 provider owner bridge")

        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        logger.info("[provider-owner-bridge] 已启动 socket=%s", self.socket_path)

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
            logger.info("[provider-owner-bridge] 已停止 socket=%s", self.socket_path)

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
            elif request_type == "list_sessions":
                response = await self._handle_list_sessions(request)
            elif request_type == "read_session":
                response = await self._handle_read_session(request)
            elif request_type == "archive_session":
                response = await self._handle_archive_session(request)
            elif request_type == "runtime_status":
                response = await self._handle_runtime_status(request)
            elif request_type == "usage_summary":
                response = await self._handle_usage_summary(request)
            elif request_type == "session_activities":
                response = await self._handle_session_activities(request)
            elif request_type == "session_activity_stream":
                await self._handle_session_activity_stream(reader, writer, request)
                return
            elif request_type == "mirror_approval":
                response = await self._handle_mirror_approval(request)
            else:
                response = {
                    "ok": False,
                    "error": f"unsupported request type: {request_type}",
                }
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            try:
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[provider-owner-bridge] 客户端已断开，跳过响应写入")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[provider-owner-bridge] 客户端已断开，跳过关闭等待")

    async def _handle_list_sessions(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        try:
            limit = int(request.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        if limit <= 0:
            limit = 100

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        facts = getattr(provider, "facts", None)
        if facts is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持会话列表"}

        sessions = []
        seen: set[tuple[str, str]] = set()
        try:
            workspaces = facts.scan_workspaces() or []
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        for workspace in workspaces:
            if not isinstance(workspace, dict):
                continue
            workspace_path = str(
                workspace.get("path") or workspace.get("workspace") or workspace.get("cwd") or ""
            ).strip()
            if not workspace_path:
                continue

            try:
                active_ids = facts.query_active_thread_ids(workspace_path)
            except Exception:
                active_ids = set()
            normalized_active_ids = {
                str(item).strip() for item in active_ids if str(item).strip()
            }

            try:
                threads = facts.list_threads(workspace_path, limit=limit) or []
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

            for thread in threads:
                if not isinstance(thread, dict):
                    continue
                thread_id = str(thread.get("id") or thread.get("thread_id") or "").strip()
                if not thread_id:
                    continue

                dedupe_key = (workspace_path, thread_id)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                preview = thread.get("preview") or thread.get("title") or thread.get("name")
                title = str(preview or "").strip() or thread_id
                updated_at = _safe_int(
                    thread.get("updatedAt")
                    or thread.get("updated_at")
                    or thread.get("updated_at_epoch")
                    or thread.get("createdAt")
                    or thread.get("created_at")
                )
                created_at = _safe_int(
                    thread.get("createdAt")
                    or thread.get("created_at")
                    or thread.get("updatedAt")
                    or thread.get("updated_at")
                )
                archived = bool(thread.get("archived", False))
                if normalized_active_ids:
                    archived = archived or thread_id not in normalized_active_ids

                sessions.append(
                    {
                        "id": thread_id,
                        "title": title,
                        "workspace": workspace_path,
                        "archived": archived,
                        "updatedAt": updated_at,
                        "createdAt": created_at,
                    }
                )

        sessions.sort(
            key=lambda item: (
                -_safe_int(item.get("updatedAt")),
                -_safe_int(item.get("createdAt")),
                str(item.get("id") or ""),
            )
        )
        return {"ok": True, "sessions": sessions}

    async def _handle_session_activities(self, request: dict) -> dict:
        try:
            limit = int(request.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        if limit <= 0:
            limit = 200

        bus = getattr(self.state, "message_bus", None)
        if bus is None or not callable(getattr(bus, "session_activities", None)):
            return {"ok": True, "activities": []}
        return {
            "ok": True,
            "activities": bus.session_activities()[:limit],
        }

    async def _handle_session_activity_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: dict,
    ) -> None:
        try:
            limit = int(request.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        if limit <= 0:
            limit = 200

        bus = getattr(self.state, "message_bus", None)
        if bus is None or not callable(getattr(bus, "session_activities", None)):
            writer.write(
                (
                    json.dumps(
                        {
                            "ok": False,
                            "kind": "error",
                            "error": "message bus unavailable",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            return

        write_lock = asyncio.Lock()
        pending: set[asyncio.Task] = set()
        queued_payloads: list[dict] = []
        snapshot_sent = False

        async def send_payload(payload: dict) -> None:
            async with write_lock:
                writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()

        loop = asyncio.get_running_loop()

        def schedule_payload(payload: dict) -> None:
            task = loop.create_task(send_payload(payload))
            pending.add(task)
            task.add_done_callback(pending.discard)

        def on_event(event) -> None:
            nonlocal snapshot_sent
            if not getattr(event, "provider_id", "") or not getattr(event, "session_id", ""):
                return
            activity = bus.session_activity(event.provider_id, event.session_id)
            if activity is None:
                return
            payload = {
                "ok": True,
                "kind": "activity",
                "activity": activity,
                "event": {
                    "kind": event.kind,
                    "eventId": event.event_id,
                },
            }
            if not snapshot_sent:
                queued_payloads.append(payload)
                return
            schedule_payload(payload)

        unsubscribe = bus.subscribe(on_event)
        try:
            await send_payload(
                {
                    "ok": True,
                    "kind": "snapshot",
                    "activities": bus.session_activities()[:limit],
                }
            )
            snapshot_sent = True
            for payload in queued_payloads:
                schedule_payload(payload)
            queued_payloads.clear()
            await reader.read()
        finally:
            unsubscribe()
            for task in tuple(pending):
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _handle_archive_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not thread_id:
            return {"ok": False, "error": "缺少 session_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        adapter = self.state.get_adapter(provider_id)
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": f"{provider_id} adapter 未连接"}

        ws_info, thread_info = _resolve_workspace_and_thread(
            self.state,
            provider_id,
            thread_id,
            workspace_dir,
        )
        if ws_info is None or thread_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法定位 provider 会话"}

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id
        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        thread_hooks = getattr(provider, "thread_hooks", None)
        archive_thread = getattr(thread_hooks, "archive_thread", None) if thread_hooks is not None else None
        try:
            if callable(archive_thread):
                await archive_thread(self.state, ws_info, thread_id, adapter)
            elif callable(getattr(adapter, "archive_thread", None)):
                await adapter.archive_thread(workspace_id, thread_id)
            else:
                return {"ok": False, "error": f"Provider '{provider_id}' 不支持真实归档"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        thread_info.archived = True
        thread_info.is_active = False
        if getattr(self.state, "storage", None) is not None:
            try:
                save_storage(self.state.storage)
            except Exception as exc:
                thread_info.archived = False
                thread_info.is_active = True
                return {"ok": False, "error": f"真实归档成功，但保存本地归档状态失败: {exc}"}
        return {
            "ok": True,
            "provider_id": provider_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
            "workspace_dir": ws_info.path,
        }

    async def _handle_usage_summary(self, request: dict) -> dict:
        from core.provider_session_bridge import _normalize_usage_summary

        provider_id = str(request.get("provider_id") or "").strip()
        start_date = str(request.get("start_date") or "").strip()
        end_date = str(request.get("end_date") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        usage_hooks = getattr(provider, "usage_hooks", None)
        get_summary = getattr(usage_hooks, "get_summary", None)
        if not callable(get_summary):
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持用量读取"}

        try:
            raw_summary = get_summary(start_date, end_date)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "summary": _normalize_usage_summary(provider_id, raw_summary),
        }

    async def _handle_read_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        try:
            limit = int(request.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        if limit <= 0:
            limit = 20

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not session_id:
            return {"ok": False, "error": "缺少 session_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        facts = getattr(provider, "facts", None)
        if facts is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持会话读取"}

        try:
            turns = facts.read_thread_history(
                session_id,
                limit=limit,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        normalized = []
        for turn in turns or []:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip()
            if role not in {"user", "assistant"}:
                continue
            normalized_turn = _normalize_provider_turn(turn)
            if not normalized_turn["content"]:
                continue
            normalized.append(normalized_turn)

        return {"ok": True, "session": normalized}

    async def _handle_runtime_status(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        adapter = self.state.get_adapter(provider_id)
        lines = await _status_lines_for_provider(self.state, provider_id, provider)
        detail = " · ".join(lines) if lines else None
        return {
            "ok": True,
            "health": _runtime_health_from_lines(lines, adapter),
            "detail": detail,
            "lines": lines,
        }

    async def _handle_mirror_approval(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        logger.info(
            "[provider-hook-mirror] 忽略 legacy mirror_approval；审批只走 app-server request/response "
            "provider=%s thread=%s workspace=%s source=%s",
            provider_id,
            thread_id[:12] if thread_id else "?",
            workspace_dir or "?",
            str(request.get("source") or ""),
        )
        return {"ok": True, "ignored": True, "reason": "approval_via_app_server_only"}

    async def _handle_send_message(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("thread_id") or "").strip()
        text = str(request.get("text") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        attachments = request.get("attachments") or []

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not thread_id:
            return {"ok": False, "error": "缺少 thread_id"}
        if not text and not attachments:
            return {"ok": False, "error": "空消息，拒绝发送"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        adapter = self.state.get_adapter(provider_id)
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": f"{provider_id} adapter 未连接"}

        ws_info, thread_info = _resolve_workspace_and_thread(
            self.state,
            provider_id,
            thread_id,
            workspace_dir,
        )
        if ws_info is None or thread_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法定位 provider 会话"}

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id

        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        message_hooks = getattr(provider, "message_hooks", None)
        if message_hooks is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持发送消息"}

        gateway_result = await prepare_user_message_text(
            self.state,
            UserMessageSendRequest(
                source=str(request.get("source") or "session_tab"),
                provider_id=provider_id,
                workspace_id=str(workspace_id),
                thread_id=thread_id,
                text=text,
                attachments=attachments,
            ),
        )
        text = gateway_result.text
        message_event_request = UserMessageSendRequest(
            source=str(request.get("source") or "session_tab"),
            provider_id=provider_id,
            workspace_id=str(workspace_id),
            thread_id=thread_id,
            text=text,
            attachments=attachments,
            metadata={"bridge": "provider_owner"},
        )
        publish_user_message_submitted(
            self.state,
            message_event_request,
            text=text,
            workspace_path=str(getattr(ws_info, "path", "") or ""),
        )

        owner_bridge_router = getattr(message_hooks, "try_route_owner_bridge_send", None)
        if callable(owner_bridge_router) and not attachments:
            route_result = await owner_bridge_router(
                self.state,
                ws_info,
                thread_info,
                text=text,
            )
            if route_result:
                self.state.mark_provider_send_started(provider_id, thread_id)
                publish_user_message_accepted(
                    self.state,
                    message_event_request,
                    text=text,
                    workspace_path=str(getattr(ws_info, "path", "") or ""),
                )
                return {
                    "ok": True,
                    "accepted": True,
                    "provider_id": provider_id,
                    "thread_id": thread_id,
                    "requested_thread_id": thread_id,
                    "remapped": False,
                    "workspace_id": workspace_id,
                    "transport": str(route_result) if isinstance(route_result, str) else "provider_owner_bridge",
                }

        original_thread_id = thread_info.thread_id
        original_topic_id = getattr(thread_info, "topic_id", None)
        original_preview = getattr(thread_info, "preview", None)
        original_source = str(getattr(thread_info, "source", "") or "unknown")
        original_is_active = bool(getattr(thread_info, "is_active", False))
        original_history_sync_cursor = getattr(thread_info, "history_sync_cursor", None)
        original_streaming_msg_id = getattr(thread_info, "streaming_msg_id", None)
        original_last_tg_user_message_id = getattr(thread_info, "last_tg_user_message_id", None)

        def rollback_thread_remap() -> None:
            if thread_info.thread_id == original_thread_id:
                return
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

        try:
            self.state.mark_provider_send_started(provider_id, thread_id)
            connected_adapter = await message_hooks.ensure_connected(
                self.state,
                adapter,
                ws_info,
                update=None,
                context=None,
                group_chat_id=0,
                src_topic_id=None,
            )
            if connected_adapter is not None:
                adapter = connected_adapter
                self.state.set_adapter(provider_id, adapter)

            should_continue = await message_hooks.prepare_send(
                self.state,
                adapter,
                ws_info,
                thread_info,
                update=None,
                context=None,
                group_chat_id=0,
                src_topic_id=None,
                text=text,
                has_photo=False,
                attachments=attachments,
            )
            if should_continue is False:
                return {
                    "ok": True,
                    "accepted": False,
                    "provider_id": provider_id,
                    "thread_id": thread_id,
                    "workspace_id": workspace_id,
                }

            send_result = await message_hooks.send(
                self.state,
                adapter,
                ws_info,
                thread_info,
                update=None,
                context=None,
                group_chat_id=0,
                src_topic_id=None,
                text=text,
                has_photo=False,
                attachments=attachments,
            )
            if isinstance(send_result, dict) and str(send_result.get("status") or "") == "error":
                rollback_thread_remap()
                return {
                    "ok": False,
                    "error": str(send_result.get("error") or f"{provider_id} send failed"),
                    "provider_id": provider_id,
                    "thread_id": thread_id,
                    "workspace_id": workspace_id,
                }
        except Exception as exc:
            rollback_thread_remap()
            return {"ok": False, "error": str(exc)}

        publish_user_message_accepted(
            self.state,
            UserMessageSendRequest(
                source=str(request.get("source") or "session_tab"),
                provider_id=provider_id,
                workspace_id=str(workspace_id),
                thread_id=str(thread_info.thread_id),
                text=text,
                attachments=attachments,
                metadata={"bridge": "provider_owner"},
            ),
            text=text,
            workspace_path=str(getattr(ws_info, "path", "") or ""),
        )

        return {
            "ok": True,
            "accepted": True,
            "provider_id": provider_id,
            "thread_id": thread_info.thread_id,
            "requested_thread_id": thread_id,
            "remapped": thread_info.thread_id != thread_id,
            "workspace_id": workspace_id,
        }


async def ensure_provider_owner_bridge_started(state) -> Optional[ProviderOwnerBridge]:
    runtime = state.get_provider_runtime("__shared__")
    bridge = getattr(runtime, "owner_bridge", None)
    if bridge is not None and bridge.is_running:
        return bridge

    bridge = ProviderOwnerBridge(state)
    if not bridge.socket_path:
        logger.info("[provider-owner-bridge] 缺少 data_dir，跳过 owner bridge 启动")
        return None
    await bridge.start()
    runtime.owner_bridge = bridge
    return bridge


async def stop_provider_owner_bridge(state) -> None:
    runtime = state.get_provider_runtime("__shared__")
    bridge = getattr(runtime, "owner_bridge", None)
    if bridge is None:
        return
    await bridge.stop()
    runtime.owner_bridge = None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
