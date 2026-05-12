from __future__ import annotations

import asyncio
import json
import logging
import os
from types import SimpleNamespace
from typing import Optional

from config import get_data_dir
from core.providers.registry import get_provider


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
                    _new_thread_info(normalized_thread_id),
                )
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
    thread = _new_thread_info(normalized_thread_id)
    ws.threads[normalized_thread_id] = thread
    return ws, thread


def _new_thread_info(thread_id: str):
    return SimpleNamespace(
        thread_id=thread_id,
        topic_id=None,
        preview=None,
        archived=False,
        streaming_msg_id=None,
        last_tg_user_message_id=None,
        history_sync_cursor=None,
        is_active=True,
        source="app",
    )


def _runtime_health_from_lines(lines: list[str], adapter) -> str:
    if adapter is not None:
        return "healthy" if bool(getattr(adapter, "connected", False)) else "degraded"

    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    for line in normalized_lines:
        lowered = line.lower()
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
    return "unknown"


def _status_lines_for_provider(state, provider_id: str, provider) -> list[str]:
    status_builder = getattr(provider, "status_builder", None)
    if callable(status_builder):
        raw_lines = status_builder(state) or []
        return [str(line).strip() for line in raw_lines if str(line).strip()]

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
            elif request_type == "runtime_status":
                response = await self._handle_runtime_status(request)
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

    async def _handle_read_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip() or None
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
                sessions_dir=workspace_dir,
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
            content = str(turn.get("content") or turn.get("text") or "").strip()
            if not content:
                continue
            normalized.append({"role": role, "content": content})

        return {"ok": True, "session": normalized}

    async def _handle_runtime_status(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        lines = _status_lines_for_provider(self.state, provider_id, provider)
        adapter = self.state.get_adapter(provider_id)
        detail = " · ".join(lines) if lines else None
        return {
            "ok": True,
            "health": _runtime_health_from_lines(lines, adapter),
            "detail": detail,
            "lines": lines,
        }

    async def _handle_send_message(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("thread_id") or "").strip()
        text = str(request.get("text") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not thread_id:
            return {"ok": False, "error": "缺少 thread_id"}
        if not text:
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
            )
            if should_continue is False:
                return {
                    "ok": True,
                    "accepted": False,
                    "provider_id": provider_id,
                    "thread_id": thread_id,
                    "workspace_id": workspace_id,
                }

            await message_hooks.send(
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
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "accepted": True,
            "provider_id": provider_id,
            "thread_id": thread_id,
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
