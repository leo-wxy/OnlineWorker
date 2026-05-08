from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from config import get_data_dir
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

    return None


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

        if not thread_id:
            return {"ok": False, "error": "缺少 thread_id"}
        if not text:
            return {"ok": False, "error": "空消息，拒绝发送"}

        adapter = self.state.get_adapter("codex")
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": "codex owner adapter 未连接"}

        workspace_id = _resolve_workspace_id(self.state, adapter, thread_id, cwd)
        if workspace_id:
            adapter._thread_workspace_map[thread_id] = workspace_id
        logger.info(
            "[codex-owner-bridge] send_message thread=%s workspace=%s cwd=%s",
            thread_id,
            workspace_id or "-",
            cwd or "-",
        )

        try:
            codex_state.mark_send_started(self.state, thread_id)
            if workspace_id:
                try:
                    await adapter.resume_thread(workspace_id, thread_id)
                except Exception as exc:
                    if not is_codex_unmaterialized_error(exc):
                        raise
                await adapter.send_user_message(workspace_id, thread_id, text)
            else:
                try:
                    await adapter._call("thread/resume", {"threadId": thread_id})
                except Exception as exc:
                    if not is_codex_unmaterialized_error(exc):
                        raise
                await adapter._call(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": text}],
                    },
                )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {
            "ok": True,
            "accepted": True,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
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
