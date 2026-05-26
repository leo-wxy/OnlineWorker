from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlparse

import websockets
import websockets.exceptions

from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text

logger = logging.getLogger(__name__)

CODEX_REMOTE_TEXT_METHODS = {"turn/start", "turn/steer"}
CODEX_REMOTE_TEXT_TYPES = {"text"}


def _is_local_ws_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "ws":
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _extract_thread_id(params: dict[str, Any]) -> str:
    return str(params.get("threadId") or params.get("thread_id") or "").strip()


def _extract_cwd(params: dict[str, Any]) -> str:
    return str(params.get("cwd") or "").strip()


async def rewrite_codex_remote_client_message(
    state,
    raw: str,
) -> tuple[str, bool]:
    try:
        payload = json.loads(raw)
    except Exception:
        return raw, False

    if not isinstance(payload, dict):
        return raw, False

    method = str(payload.get("method") or "")
    if method not in CODEX_REMOTE_TEXT_METHODS:
        return raw, False

    params = payload.get("params")
    if not isinstance(params, dict):
        return raw, False

    input_items = params.get("input")
    if not isinstance(input_items, list):
        return raw, False

    thread_id = _extract_thread_id(params)
    workspace_id = _extract_cwd(params) or thread_id
    changed = False

    for item in input_items:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in CODEX_REMOTE_TEXT_TYPES:
            continue
        if item.get("text_elements"):
            logger.info(
                "[codex-remote-proxy] 跳过带 text_elements 的用户输入，避免破坏 UI span method=%s thread=%s",
                method,
                thread_id[:12],
            )
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue

        result = await prepare_user_message_text(
            state,
            UserMessageSendRequest(
                source="codex_remote_proxy",
                provider_id="codex",
                workspace_id=workspace_id,
                thread_id=thread_id,
                text=text,
                attachments=[],
                metadata={
                    "codex_remote_method": method,
                    "app_server_proxy": True,
                },
            ),
        )
        if not result.changed:
            continue
        item["text"] = result.text
        changed = True
        logger.info(
            "[codex-remote-proxy] 已改写 Codex CLI 用户输入 method=%s thread=%s before_len=%s after_len=%s",
            method,
            thread_id[:12],
            len(text),
            len(result.text),
        )

    if not changed:
        return raw, False
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), True


class CodexRemoteMessageProxy:
    """Local WebSocket proxy that rewrites Codex TUI remote user messages before app-server receives them."""

    def __init__(
        self,
        *,
        state,
        upstream_url: str,
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
    ) -> None:
        if not _is_local_ws_url(upstream_url):
            raise ValueError(f"仅支持本机 ws:// app-server upstream: {upstream_url}")
        self.state = state
        self.upstream_url = upstream_url
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.listen_url = ""
        self._server: websockets.Server | None = None

    async def start(self) -> str:
        if self._server is not None:
            return self.listen_url

        self._server = await websockets.serve(
            self._handle_client,
            self.listen_host,
            self.listen_port,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
        )
        socket = next(iter(self._server.sockets or []), None)
        if socket is None:
            raise RuntimeError("codex remote proxy 未能获取监听 socket")
        host, port = socket.getsockname()[:2]
        host_value = "127.0.0.1" if host in {"0.0.0.0", "::"} else str(host)
        self.listen_url = f"ws://{host_value}:{port}"
        logger.info(
            "[codex-remote-proxy] listening=%s upstream=%s",
            self.listen_url,
            self.upstream_url,
        )
        return self.listen_url

    async def stop(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None
        self.listen_url = ""

    async def _handle_client(self, client: websockets.ServerConnection) -> None:
        try:
            async with websockets.connect(
                self.upstream_url,
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
                proxy=None,
            ) as upstream:
                await asyncio.gather(
                    self._relay_client_to_upstream(client, upstream),
                    self._relay_upstream_to_client(upstream, client),
                )
        except websockets.exceptions.ConnectionClosed:
            logger.debug("[codex-remote-proxy] websocket connection closed", exc_info=True)
        except Exception:
            logger.warning("[codex-remote-proxy] relay failed", exc_info=True)

    async def _relay_client_to_upstream(
        self,
        client: websockets.ServerConnection,
        upstream: websockets.ClientConnection,
    ) -> None:
        async for message in client:
            outbound = message
            if isinstance(message, str):
                outbound, _changed = await rewrite_codex_remote_client_message(
                    self.state,
                    message,
                )
            await upstream.send(outbound)

    async def _relay_upstream_to_client(
        self,
        upstream: websockets.ClientConnection,
        client: websockets.ServerConnection,
    ) -> None:
        async for message in upstream:
            await client.send(message)


async def ensure_codex_remote_message_proxy(state, upstream_url: str) -> str:
    runtime = state.get_provider_runtime("codex")
    proxy = runtime.remote_proxy
    if (
        proxy is not None
        and getattr(proxy, "upstream_url", "") == upstream_url
        and getattr(proxy, "listen_url", "")
    ):
        return proxy.listen_url

    if proxy is not None:
        await proxy.stop()
        runtime.remote_proxy = None

    proxy = CodexRemoteMessageProxy(state=state, upstream_url=upstream_url)
    listen_url = await proxy.start()
    runtime.remote_proxy = proxy
    return listen_url
