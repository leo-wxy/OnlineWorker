from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import stat
import struct
import subprocess
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import websockets
import websockets.exceptions

from config import default_data_dir, get_data_dir
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text
from plugins.providers.builtin.codex.python.approval_policy import (
    NOTICE_REMOTE_PROXY_CONTROL,
    SOURCE_REMOTE_PROXY,
)
from plugins.providers.builtin.codex.python.interactions import (
    SERVER_REQUEST_METHODS,
    parse_approval_request,
)
from plugins.providers.builtin.codex.python.transport import (
    is_unix_endpoint,
    prepare_unix_socket_path,
    resolve_unix_socket_path,
)

logger = logging.getLogger(__name__)

CODEX_REMOTE_TEXT_METHODS = {"turn/start", "turn/steer"}
CODEX_REMOTE_TEXT_TYPES = {"text"}
CODEX_THREAD_COLLECTION_METHODS = {"thread/list", "thread/search"}
CODEX_THREAD_LIST_METHOD = "thread/list"
CODEX_APP_SERVER_RESOLVED_METHOD = "serverRequest/resolved"
CODEX_REMOTE_PROXY_SOCKET_NAME = "codex_remote_proxy.sock"
DEFAULT_APPROVAL_TIMEOUT_SECONDS = 600.0
MACOS_LOCAL_PEERPID = 2
UPSTREAM_UNAVAILABLE_CLOSE_CODE = 1013


def _thread_topic_id(state, ws_info, thread_info) -> int | None:
    workspace_id = state.get_workspace_storage_key(ws_info) or getattr(ws_info, "daemon_workspace_id", "") or f"{getattr(ws_info, 'tool', 'codex')}:{getattr(ws_info, 'name', '')}"
    return state.get_thread_topic_id(workspace_id, ws_info, thread_info)
UPSTREAM_UNAVAILABLE_CLOSE_REASON = "codex app-server unavailable"


def _is_local_ws_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "ws":
        return False
    return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _is_supported_upstream_url(url: str) -> bool:
    return _is_local_ws_url(url) or is_unix_endpoint(url)


def _extract_thread_id(params: dict[str, Any]) -> str:
    thread_id = params.get("threadId") or params.get("thread_id")
    if not thread_id:
        item = params.get("item")
        if isinstance(item, dict):
            thread_id = item.get("threadId") or item.get("thread_id")
    return str(thread_id or "").strip()


def _extract_cwd(params: dict[str, Any]) -> str:
    return str(params.get("cwd") or "").strip()


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _json_rpc_id_key(request_id: Any) -> str:
    return json.dumps(request_id, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_rpc_id_candidate_keys(request_id: Any) -> list[str]:
    keys = [_json_rpc_id_key(request_id)]
    text_key = str(request_id or "").strip()
    if text_key and text_key not in keys:
        keys.append(text_key)
    return keys


def _state_data_dir(state) -> str:
    cfg = getattr(state, "config", None)
    data_dir = str(getattr(cfg, "data_dir", "") or "").strip()
    return data_dir or get_data_dir() or default_data_dir()


def default_codex_remote_proxy_url(data_dir: str | None = None) -> str:
    root = os.path.abspath(os.path.expanduser(str(data_dir or default_data_dir())))
    return f"unix://{os.path.join(root, CODEX_REMOTE_PROXY_SOCKET_NAME)}"


def _harden_unix_socket_permissions(socket_path: str) -> None:
    parent = os.path.dirname(socket_path)
    if parent:
        try:
            os.chmod(parent, 0o700)
        except Exception:
            logger.warning(
                "[codex-remote-proxy] 设置 unix socket 目录权限失败 path=%s",
                parent,
                exc_info=True,
            )
    try:
        os.chmod(socket_path, 0o600)
    except Exception:
        logger.warning(
            "[codex-remote-proxy] 设置 unix socket 权限失败 path=%s",
            socket_path,
            exc_info=True,
        )


def _client_peer_pid(client: websockets.ServerConnection) -> int | None:
    transport = getattr(client, "transport", None)
    if transport is None:
        return None
    sock = transport.get_extra_info("socket")
    if sock is None:
        return None
    try:
        raw = sock.getsockopt(0, MACOS_LOCAL_PEERPID, 4)
    except OSError:
        return None
    if not raw or len(raw) < 4:
        return None
    pid = struct.unpack("i", raw[:4])[0]
    return pid if pid > 0 else None


def _cwd_for_pid(pid: int) -> str:
    if pid <= 0:
        return ""
    lsof_bin = "/usr/sbin/lsof" if os.path.exists("/usr/sbin/lsof") else "lsof"
    try:
        result = subprocess.run(
            [lsof_bin, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            path = line[1:].strip()
            if path and os.path.isabs(path):
                return path
    return ""


def _client_process_cwd(client: websockets.ServerConnection) -> str:
    pid = _client_peer_pid(client)
    if pid is None:
        return ""
    return _cwd_for_pid(pid)


async def _close_websocket_safely(
    connection: websockets.ServerConnection | websockets.ClientConnection,
    *,
    code: int = 1000,
    reason: str = "",
) -> None:
    with contextlib.suppress(Exception):
        await connection.close(code=code, reason=reason)


def _log_task_result(result: Any, *, label: str) -> None:
    if result is None:
        return
    if isinstance(result, asyncio.CancelledError):
        return
    if isinstance(result, websockets.exceptions.ConnectionClosed):
        logger.debug("[codex-remote-proxy] %s connection closed: %s", label, result)
        return
    if isinstance(result, Exception):
        logger.warning(
            "[codex-remote-proxy] %s failed",
            label,
            exc_info=(type(result), result, result.__traceback__),
        )


def _consume_task_exception(task: asyncio.Task, *, label: str) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.debug(
            "[codex-remote-proxy] failed to inspect task result label=%s",
            label,
            exc_info=True,
        )
        return
    _log_task_result(exc, label=label)


class _ProxyConnectionContext:
    def __init__(self, *, connection_id: str, client_cwd: str = "") -> None:
        self.connection_id = connection_id
        self.client_cwd = client_cwd
        self.thread_collection_cwds: dict[str, str] = {}
        self.pending_approval_races: dict[str, _ProxyApprovalRace] = {}
        self.upstream_send_lock = asyncio.Lock()
        self.background_tasks: set[asyncio.Task] = set()

    def track_background_task(self, task: asyncio.Task) -> None:
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        task.add_done_callback(
            lambda completed: _consume_task_exception(
                completed,
                label=f"background task connection={self.connection_id}",
            )
        )

    async def cancel_background_tasks(self) -> None:
        if not self.background_tasks:
            return
        tasks = list(self.background_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.background_tasks.clear()


class _ProxyApprovalRace:
    def __init__(
        self,
        *,
        request_id: Any,
        request_key: str,
        proxy_request_id: str,
        method: str,
        thread_id: str,
        pending,
    ) -> None:
        self.request_id = request_id
        self.request_key = request_key
        self.proxy_request_id = proxy_request_id
        self.method = method
        self.thread_id = thread_id
        self.pending = pending
        self.answered = False
        self.answer_source = ""

    def mark_answered(self, source: str) -> bool:
        if self.answered:
            return False
        self.answered = True
        self.answer_source = source
        self.pending.event.set()
        return True


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
    return _json_dumps(payload), True


class CodexRemoteMessageProxy:
    """Local proxy for Codex remote clients.

    The proxy supports ws:// and unix:// app-server upstreams. Besides user
    message rewrite, it mirrors app-server approval server requests to
    OnlineWorker/TG while still forwarding them to the Codex CLI so the native
    approval UI remains available.
    """

    def __init__(
        self,
        *,
        state,
        upstream_url: str,
        listen_url: str = "",
        listen_host: str = "127.0.0.1",
        listen_port: int = 0,
        approval_timeout_seconds: float = DEFAULT_APPROVAL_TIMEOUT_SECONDS,
    ) -> None:
        if not _is_supported_upstream_url(upstream_url):
            raise ValueError(f"仅支持本机 ws:// 或 unix:// app-server upstream: {upstream_url}")
        if listen_url and not (_is_local_ws_url(listen_url) or is_unix_endpoint(listen_url)):
            raise ValueError(f"仅支持本机 ws:// 或 unix:// proxy listen: {listen_url}")
        self.state = state
        self.upstream_url = upstream_url
        self.listen_url = listen_url
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.approval_timeout_seconds = approval_timeout_seconds
        self._server: websockets.Server | None = None
        self._unix_socket_path: str | None = None
        self._connection_seq = 0

    def _resolved_listen_url(self) -> str:
        if self.listen_url:
            return self.listen_url
        if is_unix_endpoint(self.upstream_url):
            return default_codex_remote_proxy_url(_state_data_dir(self.state))
        return ""

    async def start(self) -> str:
        if self._server is not None:
            return self.listen_url

        listen_url = self._resolved_listen_url()
        if is_unix_endpoint(listen_url):
            socket_path = prepare_unix_socket_path(listen_url)
            self._server = await websockets.unix_serve(
                self._handle_client,
                path=socket_path,
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
                compression=None,
            )
            self._unix_socket_path = socket_path
            _harden_unix_socket_permissions(socket_path)
            self.listen_url = f"unix://{socket_path}"
        else:
            self._server = await websockets.serve(
                self._handle_client,
                self.listen_host,
                self.listen_port,
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
                compression=None,
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
        if self._unix_socket_path:
            try:
                mode = os.stat(self._unix_socket_path).st_mode
                if stat.S_ISSOCK(mode):
                    os.unlink(self._unix_socket_path)
            except FileNotFoundError:
                pass
            except Exception:
                logger.warning(
                    "[codex-remote-proxy] 清理 unix socket 失败 path=%s",
                    self._unix_socket_path,
                    exc_info=True,
                )
            self._unix_socket_path = None
        self.listen_url = ""

    def _connect_upstream(self):
        if is_unix_endpoint(self.upstream_url):
            return websockets.unix_connect(
                path=resolve_unix_socket_path(self.upstream_url),
                uri="ws://localhost/",
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
                compression=None,
            )
        return websockets.connect(
            self.upstream_url,
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            proxy=None,
            compression=None,
        )

    def _next_connection_id(self) -> str:
        self._connection_seq += 1
        return f"{self._connection_seq}"

    async def _handle_client(self, client: websockets.ServerConnection) -> None:
        connection_id = self._next_connection_id()
        context = _ProxyConnectionContext(
            connection_id=connection_id,
            client_cwd=_client_process_cwd(client),
        )
        if context.client_cwd:
            logger.info(
                "[codex-remote-proxy] client cwd resolved connection=%s cwd=%s",
                connection_id,
                context.client_cwd,
            )
        tasks: list[asyncio.Task] = []
        try:
            async with self._connect_upstream() as upstream:
                tasks = [
                    asyncio.create_task(
                        self._relay_client_to_upstream(client, upstream, context)
                    ),
                    asyncio.create_task(
                        self._relay_upstream_to_client(upstream, client, context)
                    ),
                ]
                try:
                    await asyncio.wait(
                        tasks,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for result in results:
                        _log_task_result(
                            result,
                            label=f"relay task connection={connection_id}",
                        )
                    await context.cancel_background_tasks()
                    await _close_websocket_safely(upstream)
                    await _close_websocket_safely(client)
        except websockets.exceptions.ConnectionClosed:
            logger.debug("[codex-remote-proxy] websocket connection closed", exc_info=True)
        except (OSError, TimeoutError, asyncio.TimeoutError, websockets.exceptions.InvalidHandshake):
            logger.warning(
                "[codex-remote-proxy] upstream app-server unavailable upstream=%s",
                self.upstream_url,
                exc_info=True,
            )
            await context.cancel_background_tasks()
            await _close_websocket_safely(
                client,
                code=UPSTREAM_UNAVAILABLE_CLOSE_CODE,
                reason=UPSTREAM_UNAVAILABLE_CLOSE_REASON,
            )
        except Exception:
            logger.warning("[codex-remote-proxy] relay failed", exc_info=True)
            await context.cancel_background_tasks()
            await _close_websocket_safely(client)

    async def _relay_client_to_upstream(
        self,
        client: websockets.ServerConnection,
        upstream: websockets.ClientConnection,
        context: _ProxyConnectionContext,
    ) -> None:
        async for message in client:
            suppress_client_response = False
            outbound = message
            if isinstance(message, str):
                suppress_client_response = self._maybe_mark_cli_approval_response(
                    message,
                    context,
                )
                if suppress_client_response:
                    continue
                outbound, _changed = await rewrite_codex_remote_client_message(
                    self.state,
                    message,
                )
                outbound = self._maybe_rewrite_thread_list_request(outbound, context)
            async with context.upstream_send_lock:
                await upstream.send(outbound)

    async def _relay_upstream_to_client(
        self,
        upstream: websockets.ClientConnection,
        client: websockets.ServerConnection,
        context: _ProxyConnectionContext,
    ) -> None:
        async for message in upstream:
            if isinstance(message, str):
                self._maybe_start_server_request_mirror(
                    message,
                    context,
                    upstream,
                )
                self._maybe_handle_server_request_resolved(message, context)
            if isinstance(message, str):
                message = self._maybe_filter_thread_list_response(message, context)
            await client.send(message)

    def _maybe_mark_cli_approval_response(
        self,
        raw: str,
        context: _ProxyConnectionContext,
    ) -> bool:
        try:
            payload = json.loads(raw)
        except Exception:
            return False
        if not isinstance(payload, dict) or "method" in payload:
            return False
        request_id = payload.get("id")
        if request_id is None:
            return False

        request_key = _json_rpc_id_key(request_id)
        race = context.pending_approval_races.get(request_key)
        if race is None:
            return False

        if not race.mark_answered("cli"):
            context.pending_approval_races.pop(request_key, None)
            logger.info(
                "[codex-remote-proxy] 已忽略 CLI 延迟 approval 回复 method=%s thread=%s request=%s source=%s",
                race.method,
                race.thread_id[:12],
                race.proxy_request_id,
                race.answer_source or "unknown",
            )
            return True

        context.pending_approval_races.pop(request_key, None)
        self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
        self._discard_pending_telegram_approval(race.proxy_request_id)
        logger.info(
            "[codex-remote-proxy] approval 已由 CLI 原生弹窗处理 method=%s thread=%s request=%s",
            race.method,
            race.thread_id[:12],
            race.proxy_request_id,
        )
        return False

    def _maybe_handle_server_request_resolved(
        self,
        raw: str,
        context: _ProxyConnectionContext,
    ) -> bool:
        try:
            payload = json.loads(raw)
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        if str(payload.get("method") or "") != CODEX_APP_SERVER_RESOLVED_METHOD:
            return False

        params = payload.get("params")
        if not isinstance(params, dict):
            params = {}
        request_id = (
            params.get("requestId")
            or params.get("request_id")
            or payload.get("id")
        )
        if request_id is None:
            return False

        race = None
        for request_key in _json_rpc_id_candidate_keys(request_id):
            race = context.pending_approval_races.pop(request_key, None)
            if race is not None:
                break
        if race is None:
            logger.debug(
                "[codex-remote-proxy] app-server resolved unknown approval request=%s",
                request_id,
            )
            return False

        race.mark_answered("app_server_resolved")
        self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
        self._discard_pending_telegram_approval(race.proxy_request_id)
        logger.info(
            "[codex-remote-proxy] app-server resolved approval，已清理 TG mirror 状态 method=%s thread=%s request=%s raw_request=%s",
            race.method,
            race.thread_id[:12],
            race.proxy_request_id,
            request_id,
        )
        return True

    def _maybe_rewrite_thread_list_request(
        self,
        raw: str,
        context: _ProxyConnectionContext,
    ) -> str:
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        if not isinstance(payload, dict):
            return raw
        request_id = payload.get("id")
        method = str(payload.get("method") or "")
        if request_id is None or method not in CODEX_THREAD_COLLECTION_METHODS:
            return raw

        params = payload.get("params")
        if not isinstance(params, dict):
            params = {}
            payload["params"] = params

        requested_cwd = _extract_cwd(params)
        effective_cwd = requested_cwd or context.client_cwd
        context.thread_collection_cwds[_json_rpc_id_key(request_id)] = effective_cwd
        if requested_cwd or not effective_cwd or method != CODEX_THREAD_LIST_METHOD:
            if not effective_cwd:
                logger.warning(
                    "[codex-remote-proxy] %s 缺少 cwd 且无法解析客户端 cwd，响应将过滤为空 request=%s",
                    method,
                    request_id,
                )
            return raw

        params["cwd"] = effective_cwd
        logger.info(
            "[codex-remote-proxy] 已为 thread/list 补充 cwd request=%s cwd=%s",
            request_id,
            effective_cwd,
        )
        return _json_dumps(payload)

    def _maybe_filter_thread_list_response(
        self,
        raw: str,
        context: _ProxyConnectionContext,
    ) -> str:
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        if not isinstance(payload, dict):
            return raw
        request_id = payload.get("id")
        if request_id is None:
            return raw
        request_key = _json_rpc_id_key(request_id)
        if request_key not in context.thread_collection_cwds:
            return raw

        cwd = context.thread_collection_cwds.pop(request_key, "")
        result = payload.get("result")
        if not isinstance(result, dict):
            return raw
        data = result.get("data")
        if not isinstance(data, list):
            return raw

        if cwd:
            filtered = [
                item
                for item in data
                if isinstance(item, dict) and str(item.get("cwd") or "") == cwd
            ]
        else:
            filtered = []
        if len(filtered) == len(data):
            return raw

        result["data"] = filtered
        logger.info(
            "[codex-remote-proxy] 已过滤 thread/list 响应 request=%s cwd=%s before=%s after=%s",
            request_id,
            cwd or "<unknown>",
            len(data),
            len(filtered),
        )
        return _json_dumps(payload)

    def _maybe_start_server_request_mirror(
        self,
        raw: str,
        context: _ProxyConnectionContext,
        upstream: websockets.ClientConnection,
    ) -> None:
        try:
            payload = json.loads(raw)
        except Exception:
            return
        if not isinstance(payload, dict):
            return

        request_id = payload.get("id")
        method = str(payload.get("method") or "")
        if request_id is None or method not in SERVER_REQUEST_METHODS:
            return

        params = payload.get("params")
        if not isinstance(params, dict):
            params = {}
        target = self._resolve_approval_target(params)
        if target is None:
            logger.info(
                "[codex-remote-proxy] approval 未命中 OnlineWorker topic，透传给 CLI method=%s thread=%s",
                method,
                _extract_thread_id(params)[:12],
            )
            return
        workspace_id, topic_id, thread_id = target

        bot = getattr(self.state, "telegram_bot", None)
        group_chat_id = int(getattr(self.state, "group_chat_id", 0) or 0)
        if bot is None or not group_chat_id:
            logger.warning("[codex-remote-proxy] bot context unavailable，透传 approval 给 CLI")
            return

        proxy_request_id = f"{SOURCE_REMOTE_PROXY}:{context.connection_id}:{request_id}"
        info = parse_approval_request(
            params,
            request_id=proxy_request_id,
            provider_id="codex",
            default_thread_id=thread_id,
            approval_source=SOURCE_REMOTE_PROXY,
        )
        pending = self.state.ensure_pending_approval_decision("codex", proxy_request_id)
        request_key = _json_rpc_id_key(request_id)
        race = _ProxyApprovalRace(
            request_id=request_id,
            request_key=request_key,
            proxy_request_id=proxy_request_id,
            method=method,
            thread_id=thread_id,
            pending=pending,
        )
        context.pending_approval_races[request_key] = race
        task = asyncio.create_task(
            self._mirror_approval_to_telegram(
                context,
                upstream,
                race,
                workspace_id=workspace_id,
                topic_id=topic_id,
                group_chat_id=group_chat_id,
                info=info,
            ),
            name=f"codex-remote-proxy-approval-{proxy_request_id}",
        )
        context.track_background_task(task)

    async def _mirror_approval_to_telegram(
        self,
        context: _ProxyConnectionContext,
        upstream: websockets.ClientConnection,
        race: _ProxyApprovalRace,
        *,
        workspace_id: str,
        topic_id: int,
        group_chat_id: int,
        info,
    ) -> None:
        from bot.events import send_approval_to_telegram

        bot = getattr(self.state, "telegram_bot", None)
        if bot is None:
            return

        try:
            await send_approval_to_telegram(
                self.state,
                bot,
                group_chat_id,
                topic_id,
                workspace_id,
                info,
                interactive=True,
                notice_suffix=NOTICE_REMOTE_PROXY_CONTROL,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
            context.pending_approval_races.pop(race.request_key, None)
            logger.warning(
                "[codex-remote-proxy] approval 镜像到 TG 失败，保留 CLI 原生弹窗 method=%s thread=%s request=%s",
                race.method,
                race.thread_id[:12],
                race.proxy_request_id,
                exc_info=True,
            )
            return

        if not any(
            str(getattr(approval, "request_id", "") or "") == race.proxy_request_id
            for approval in self.state.pending_approvals.values()
        ):
            self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
            context.pending_approval_races.pop(race.request_key, None)
            logger.warning(
                "[codex-remote-proxy] approval 未成功登记到 TG pending，透传给 CLI method=%s thread=%s",
                race.method,
                race.thread_id[:12],
            )
            return

        logger.info(
            "[codex-remote-proxy] 已镜像 approval 到 TG，CLI 原生弹窗保持透传 method=%s thread=%s topic=%s request=%s",
            race.method,
            race.thread_id[:12],
            topic_id,
            race.proxy_request_id,
        )

        timed_out = False
        try:
            await asyncio.wait_for(
                race.pending.event.wait(),
                timeout=self.approval_timeout_seconds,
            )
            action = race.pending.decision or "exec_deny"
        except asyncio.TimeoutError:
            timed_out = True
            action = "exec_deny"
            logger.warning(
                "[codex-remote-proxy] approval 等待 TG/CLI 超时，按拒绝处理 method=%s thread=%s request=%s",
                race.method,
                race.thread_id[:12],
                race.proxy_request_id,
            )

        if race.answered:
            self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
            self._discard_pending_telegram_approval(race.proxy_request_id)
            return

        if action not in {"exec_allow", "exec_deny", "exec_allow_always"}:
            action = "exec_deny" if action == "deny" else "exec_allow"

        from plugins.providers.builtin.codex.python.runtime import build_approval_reply

        _label, reply_body = build_approval_reply(
            SimpleNamespace(
                approval_source=race.method,
                amendment_decision=info.amendment_decision,
            ),
            action,
        )
        if not race.mark_answered("tg_timeout" if timed_out else "telegram"):
            self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
            return

        try:
            await self._send_approval_reply_to_upstream(context, upstream, race, reply_body)
        except (OSError, websockets.exceptions.ConnectionClosed):
            logger.info(
                "[codex-remote-proxy] approval 回复时 upstream 已关闭 method=%s thread=%s request=%s source=%s",
                race.method,
                race.thread_id[:12],
                race.proxy_request_id,
                race.answer_source,
            )
        except Exception:
            logger.warning(
                "[codex-remote-proxy] approval 回复 upstream 失败 method=%s thread=%s request=%s source=%s",
                race.method,
                race.thread_id[:12],
                race.proxy_request_id,
                race.answer_source,
                exc_info=True,
            )
        finally:
            context.pending_approval_races.pop(race.request_key, None)
            self.state.discard_pending_approval_decision("codex", race.proxy_request_id)
            self._discard_pending_telegram_approval(race.proxy_request_id)
        logger.info(
            "[codex-remote-proxy] 已通过 %s 处理 approval method=%s thread=%s action=%s request=%s",
            race.answer_source,
            race.method,
            race.thread_id[:12],
            action,
            race.proxy_request_id,
        )

    async def _send_approval_reply_to_upstream(
        self,
        context: _ProxyConnectionContext,
        upstream: websockets.ClientConnection,
        race: _ProxyApprovalRace,
        reply_body: dict[str, Any],
    ) -> None:
        payload = _json_dumps({"id": race.request_id, "result": reply_body})
        async with context.upstream_send_lock:
            await upstream.send(payload)

    def _discard_pending_telegram_approval(self, request_id: str) -> None:
        for msg_id, approval in list(self.state.pending_approvals.items()):
            if str(getattr(approval, "request_id", "") or "") == request_id:
                self.state.pending_approvals.pop(msg_id, None)

    def _resolve_approval_target(self, params: dict[str, Any]) -> tuple[str, int, str] | None:
        thread_id = _extract_thread_id(params)
        if not thread_id:
            return None

        found = self.state.find_thread_by_id_global(thread_id)
        if found:
            ws_info, thread_info = found
            topic_id = _thread_topic_id(self.state, ws_info, thread_info)
            if getattr(thread_info, "archived", False) or topic_id is None:
                return None
            workspace_id = str(getattr(ws_info, "daemon_workspace_id", "") or "")
            if not workspace_id:
                workspace_id = f"{getattr(ws_info, 'tool', 'codex')}:{getattr(ws_info, 'path', '')}"
            return workspace_id, int(topic_id), thread_id

        runtime = self.state.get_provider_runtime("codex")
        watch_state = getattr(runtime, "watched_threads", {}).get(thread_id)
        if watch_state is not None:
            topic_id = getattr(watch_state, "topic_id", None)
            if topic_id is not None:
                workspace_id = str(getattr(watch_state, "workspace_id", "") or "")
                return workspace_id, int(topic_id), thread_id

        return None


async def ensure_codex_remote_message_proxy(
    state,
    upstream_url: str,
    *,
    listen_url: str = "",
) -> str:
    runtime = state.get_provider_runtime("codex")
    desired_listen_url = listen_url or (
        default_codex_remote_proxy_url(_state_data_dir(state))
        if is_unix_endpoint(upstream_url)
        else ""
    )
    proxy = runtime.remote_proxy
    if (
        proxy is not None
        and getattr(proxy, "upstream_url", "") == upstream_url
        and getattr(proxy, "listen_url", "")
        and (not desired_listen_url or getattr(proxy, "listen_url", "") == desired_listen_url)
    ):
        return proxy.listen_url

    if proxy is not None:
        await proxy.stop()
        runtime.remote_proxy = None

    proxy = CodexRemoteMessageProxy(
        state=state,
        upstream_url=upstream_url,
        listen_url=desired_listen_url,
    )
    active_listen_url = await proxy.start()
    runtime.remote_proxy = proxy
    return active_listen_url
