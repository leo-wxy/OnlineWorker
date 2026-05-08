# core/codex_adapter.py
"""
CodexAdapter — codex app-server JSON-RPC 客户端。

支持两种底层传输：
  - WebSocket (`ws://...`)
  - stdio (`stdio://`)

是 DaemonClient 的 drop-in replacement，保持相同的公开接口和回调签名。
"""
import asyncio
from contextlib import suppress
import json
import logging
from collections import deque
from typing import Any, Callable, Awaitable, Optional

import websockets
import websockets.exceptions

logger = logging.getLogger(__name__)

# 回调类型，必须与 daemon.py 完全一致
EventCallback = Callable[[str, Any], Awaitable[None]]
ServerRequestCallback = Callable[[str, Any, int], Awaitable[None]]


class CodexAdapter:
    """WebSocket JSON-RPC 客户端，codex app-server 的 drop-in DaemonClient 替代。"""

    def __init__(self):
        self._ws: Optional[websockets.ClientConnection] = None
        self._stdio_process: Optional[asyncio.subprocess.Process] = None
        self._stdio_stdin = None
        self._stdio_stdout = None
        self._stdio_buffer = bytearray()
        self._transport: str = "ws"
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._event_callbacks: list[EventCallback] = []
        self._server_request_callbacks: list[ServerRequestCallback] = []
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self._recv_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._event_worker_task: Optional[asyncio.Task] = None
        self._server_request_worker_task: Optional[asyncio.Task] = None
        self._event_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._server_request_queue: asyncio.Queue[tuple[str, dict[str, Any], Any]] = asyncio.Queue()
        self._connected = False
        self._disconnect_notified = False
        # 心跳容错：允许连续失败 N 次才断开（提升稳定性）
        self._heartbeat_fail_count = 0
        self._heartbeat_max_fails = 3
        # workspace_id → cwd 路径映射
        self._workspace_cwd_map: dict[str, str] = {}
        # thread_id → workspace_id 映射（用于事件路由）
        self._thread_workspace_map: dict[str, str] = {}
        # 最近协议收发摘要，用于 1006 / EOF 断线诊断
        self._recent_inbound_messages: deque[str] = deque(maxlen=6)
        self._recent_outbound_messages: deque[str] = deque(maxlen=6)

    @staticmethod
    def _extract_thread_id_from_result(result: Any) -> Optional[str]:
        """从 RPC 返回中提取 thread id，兼容 {id} 与 {thread:{id}}。"""
        if not isinstance(result, dict):
            return None
        thread_id = result.get("id")
        if not thread_id:
            thread = result.get("thread")
            if isinstance(thread, dict):
                thread_id = thread.get("id")
        return str(thread_id) if thread_id else None

    @staticmethod
    def _extract_thread_id_from_event_params(params: dict[str, Any]) -> Optional[str]:
        """从 app-server event params 中提取 thread id。"""
        thread_id = (
            params.get("threadId")
            or params.get("thread_id")
        )
        if not thread_id:
            thread = params.get("thread")
            if isinstance(thread, dict):
                thread_id = (
                    thread.get("id")
                    or thread.get("threadId")
                    or thread.get("thread_id")
                )
        if not thread_id:
            turn = params.get("turn", {})
            if isinstance(turn, dict):
                thread_id = turn.get("threadId") or turn.get("thread_id")
        if not thread_id:
            item = params.get("item", {})
            if isinstance(item, dict):
                thread_id = item.get("threadId") or item.get("thread_id")
        return str(thread_id) if thread_id else None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect(
        self,
        url: str,
        *,
        process: Optional[asyncio.subprocess.Process] = None,
    ) -> None:
        """连接 app-server，发送 initialize 握手，启动接收和心跳循环。"""
        self._transport = "stdio" if url == "stdio://" else "ws"
        if self._transport == "ws":
            # 关闭 websockets 库自带的 ping/pong 定时器，统一使用我们自己的心跳策略。
            # 运行态里默认 20s keepalive 会在长 turn 期间误判，表现为 1006/无关闭握手断开。
            self._ws = await websockets.connect(
                url,
                max_size=None,
                ping_interval=None,
                ping_timeout=None,
            )
        else:
            if process is None:
                raise RuntimeError("stdio 模式连接 app-server 时缺少 process")
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("stdio 模式连接 app-server 时缺少 stdin/stdout")
            self._stdio_process = process
            self._stdio_stdin = process.stdin
            self._stdio_stdout = process.stdout

        # ⚠️ 关键：initialize 握手必须用手动 send/recv，
        # 不能用 _call()，因为此时 _recv_loop 尚未启动，_call() 会死锁。
        init_req = json.dumps({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "onlineWorker", "version": "1.0.0"},
            },
        })
        await self._send_raw(init_req)
        resp_raw = await asyncio.wait_for(self._recv_raw(), timeout=10.0)
        self._record_protocol_message("inbound", resp_raw)
        resp = json.loads(resp_raw)
        logger.info(f"app-server initialize 响应：{json.dumps(resp)[:200]}")

        # id=1 已被 initialize 消耗
        self._next_id = 2
        self._connected = True
        self._disconnect_notified = False
        self._heartbeat_fail_count = 0  # 重置心跳失败计数

        # 启动接收循环和心跳
        self._recv_task = asyncio.create_task(self._recv_loop(), name="adapter-recv")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="adapter-heartbeat")

    async def disconnect(self) -> None:
        """断开连接，取消所有后台任务。"""
        self._connected = False
        self._disconnect_notified = True
        self._fail_pending_requests(RuntimeError("app-server 连接断开"))
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self._event_worker_task and not self._event_worker_task.done():
            self._event_worker_task.cancel()
        if self._server_request_worker_task and not self._server_request_worker_task.done():
            self._server_request_worker_task.cancel()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._stdio_stdin:
            try:
                self._stdio_stdin.close()
            except Exception:
                pass
        self._ws = None
        self._stdio_process = None
        self._stdio_stdin = None
        self._stdio_stdout = None
        self._stdio_buffer.clear()
        logger.info("已断开 app-server 连接")

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # 事件订阅（与 DaemonClient 签名完全一致）
    # ------------------------------------------------------------------

    def on_event(self, callback: EventCallback) -> None:
        """注册事件回调。"""
        self._event_callbacks.append(callback)

    def on_server_request(self, callback: ServerRequestCallback) -> None:
        """注册 server request 回调（如 requestApproval）。"""
        self._server_request_callbacks.append(callback)

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        """注册断线回调。"""
        self._disconnect_callbacks.append(callback)

    # ------------------------------------------------------------------
    # 内部 RPC 调用
    # ------------------------------------------------------------------

    async def _call(self, method: str, params: dict) -> Any:
        """发送 JSON-RPC 请求，等待响应，返回 result。"""
        if not self._connected:
            raise RuntimeError("未连接到 app-server")

        req_id = self._next_id
        self._next_id += 1

        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut

        payload = json.dumps({"id": req_id, "method": method, "params": params})
        try:
            await self._send_raw(payload)
        except Exception:
            current_fut = self._pending.pop(req_id, None) or fut
            if current_fut.done():
                with suppress(Exception, asyncio.CancelledError):
                    current_fut.exception()
            else:
                current_fut.cancel()
            raise

        try:
            result = await asyncio.wait_for(fut, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise TimeoutError(f"app-server RPC 超时：method={method}")

    # ------------------------------------------------------------------
    # RPC 方法（与 DaemonClient 签名完全一致）
    # ------------------------------------------------------------------

    async def list_workspaces(self) -> list[dict]:
        """返回硬编码的单一 workspace 条目（app-server 即是 workspace）。"""
        return [{"id": "app-server", "name": "codex", "path": ""}]

    async def list_threads(self, workspace_id: str, limit: int = 20) -> list[dict]:
        cwd = self._workspace_cwd_map.get(workspace_id)
        params: dict[str, Any] = {"limit": limit}
        if cwd:
            params["cwd"] = cwd
        result = await self._call("thread/list", params)
        # app-server 返回 {data: [...], nextCursor: ...}
        if isinstance(result, dict):
            return result.get("data", [])
        return result if isinstance(result, list) else []

    async def start_thread(self, workspace_id: str) -> dict:
        cwd = self._workspace_cwd_map.get(workspace_id)
        params: dict[str, Any] = {}
        if cwd:
            params["cwd"] = cwd
        result = await self._call("thread/start", params)
        # 记录新 thread 的 workspace 映射
        thread_id = self._extract_thread_id_from_result(result)
        if thread_id and workspace_id:
            self._thread_workspace_map[thread_id] = workspace_id
            logger.debug(f"[thread_map] 新 thread 映射：{thread_id[:12]}… → {workspace_id}")
        return result

    async def resume_thread(self, workspace_id: str, thread_id: str) -> dict:
        # 记录 thread → workspace 映射，确保后续事件能正确路由
        if thread_id and workspace_id:
            self._thread_workspace_map[thread_id] = workspace_id
            logger.debug(f"[thread_map] 记录映射：thread={thread_id[:12]}… → workspace={workspace_id}")
        return await self._call("thread/resume", {"threadId": thread_id})

    async def archive_thread(self, workspace_id: str, thread_id: str) -> dict:
        return await self._call("thread/archive", {"threadId": thread_id})

    async def send_user_message(
        self,
        workspace_id: str,
        thread_id: str,
        text: str,
        *,
        approval_policy: Any | None = None,
        approvals_reviewer: str | None = None,
        sandbox_policy: Any | None = None,
    ) -> dict:
        """发送用户消息。注意 input 是数组格式（Pitfall 8）。"""
        if thread_id and workspace_id:
            self._thread_workspace_map[thread_id] = workspace_id
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": text}],
        }
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if approvals_reviewer is not None:
            params["approvalsReviewer"] = approvals_reviewer
        if sandbox_policy is not None:
            params["sandboxPolicy"] = sandbox_policy
        return await self._call("turn/start", params)

    async def list_models(self, *, include_hidden: bool = False, limit: int = 20) -> list[dict]:
        """读取 codex app-server 暴露的模型列表。"""
        params: dict[str, Any] = {
            "includeHidden": include_hidden,
            "limit": limit,
        }
        result = await self._call("model/list", params)
        if isinstance(result, dict):
            data = result.get("data", [])
            return data if isinstance(data, list) else []
        return result if isinstance(result, list) else []

    async def set_thread_model_config(
        self,
        workspace_id: str,
        thread_id: str,
        *,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> dict:
        """通过 app-server 官方 turn/start override 更新当前 thread 的模型配置。"""
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [],
        }
        if model is not None:
            params["model"] = model
        if reasoning_effort is not None:
            params["effort"] = reasoning_effort
        if thread_id and workspace_id:
            self._thread_workspace_map[thread_id] = workspace_id
        return await self._call("turn/start", params)

    async def skills_list(self, workspace_id: str) -> list[dict]:
        cwd = self._workspace_cwd_map.get(workspace_id)
        params: dict[str, Any] = {}
        if cwd:
            params["cwds"] = [cwd]
        result = await self._call("skills/list", params)
        if isinstance(result, dict):
            data = result.get("data", [])
            if isinstance(data, list) and data:
                return data[0].get("skills", [])
        return result if isinstance(result, list) else []

    async def turn_interrupt(self, workspace_id: str, thread_id: str, turn_id: str) -> dict:
        return await self._call("turn/interrupt", {
            "threadId": thread_id,
            "turnId": turn_id,
        })

    async def connect_workspace(self, workspace_id: str) -> dict:
        """No-op：app-server 是单进程服务所有 workspace。"""
        return {}

    async def reply_server_request(self, workspace_id: str, request_id: Any, result: Any) -> None:
        """
        回复 server request（如授权响应）。

        关键差异（Pitfall 3）：
        - daemon 用 self.call("respond_to_server_request", {...})（RPC 代理）
        - app-server 需要直接发送原始 JSON-RPC 响应 {"id": request_id, "result": result}
        """
        if not self._connected:
            raise RuntimeError("未连接到 app-server")
        response = json.dumps({"id": request_id, "result": result})
        await self._send_raw(response)
        decision = ""
        if isinstance(result, dict):
            decision = str(result.get("decision") or "")
        logger.info(
            "reply_server_request sent request_id=%s workspace_id=%s decision=%s payload=%s",
            request_id,
            workspace_id,
            decision or "-",
            json.dumps(result, ensure_ascii=False)[:200],
        )

    async def get_latest_thread(self, workspace_id: str) -> Optional[dict]:
        """获取该 workspace 最近更新的 thread（非 ephemeral、非子 agent）。"""
        threads = await self.list_threads(workspace_id, limit=50)
        main_threads = [
            t for t in threads
            if not t.get("ephemeral", False)
            and isinstance(t.get("source"), str)
        ]
        if not main_threads:
            return None
        main_threads.sort(key=lambda t: t.get("updatedAt", 0), reverse=True)
        return main_threads[0]

    # ------------------------------------------------------------------
    # Workspace CWD 映射
    # ------------------------------------------------------------------

    def register_workspace_cwd(self, workspace_id: str, cwd: str) -> None:
        """注册 workspace_id → cwd 路径映射。"""
        self._workspace_cwd_map[workspace_id] = cwd
        logger.debug(f"注册 workspace cwd 映射：{workspace_id} → {cwd}")

    def _resolve_workspace_id_from_params(self, params: dict) -> str:
        """从事件参数中提取 workspace_id，用于事件信封包装。
        
        如果找不到明确的映射，返回空字符串而不是猜测。
        """
        # 策略 1：通过 threadId 查找已知映射
        thread_id = params.get("threadId") or params.get("thread_id")
        if not thread_id:
            thread = params.get("thread")
            if isinstance(thread, dict):
                thread_id = thread.get("id")
        if not thread_id:
            item = params.get("item")
            if isinstance(item, dict):
                thread_id = item.get("threadId")

        if thread_id and thread_id in self._thread_workspace_map:
            return self._thread_workspace_map[thread_id]

        # 找不到映射时返回空字符串（不再 fallback 到第一个 workspace）
        if thread_id:
            logger.error(
                f"[CodexAdapter] 无法解析 workspace_id：thread_id={thread_id} 未找到映射"
            )
        return ""

    def _summarize_protocol_message(self, raw: str) -> str:
        try:
            msg = json.loads(raw)
        except Exception:
            preview = raw.replace("\n", "\\n")
            return f"raw={preview[:120]}"

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})
        params = params if isinstance(params, dict) else {}
        result = msg.get("result", {})
        result = result if isinstance(result, dict) else {}

        thread_id = (
            params.get("threadId")
            or params.get("thread_id")
            or (params.get("thread", {}) or {}).get("id")
            or (params.get("item", {}) or {}).get("threadId")
            or (result.get("thread", {}) or {}).get("id")
        )
        turn_id = (
            params.get("turnId")
            or (params.get("turn", {}) or {}).get("id")
            or (result.get("turn", {}) or {}).get("id")
        )
        item_id = params.get("itemId") or (params.get("item", {}) or {}).get("id")
        command = params.get("command") or (params.get("item", {}) or {}).get("command") or ""

        parts = [f"id={msg_id}" if msg_id is not None else "id=-"]
        if method:
            parts.append(f"method={method}")
        if thread_id:
            parts.append(f"thread={thread_id[:18]}")
        if turn_id:
            parts.append(f"turn={turn_id[:18]}")
        if item_id:
            parts.append(f"item={item_id[:18]}")
        if command:
            parts.append(f"cmd={str(command).replace(chr(10), ' ')[:80]}")
        if "error" in msg:
            error = msg.get("error")
            if isinstance(error, dict):
                parts.append(f"error={str(error.get('message') or '')[:80]}")
            else:
                parts.append(f"error={str(error)[:80]}")
        return " ".join(parts)

    def _record_protocol_message(self, direction: str, raw: str) -> None:
        summary = self._summarize_protocol_message(raw)
        if direction == "inbound":
            self._recent_inbound_messages.append(summary)
        else:
            self._recent_outbound_messages.append(summary)

    def _build_disconnect_diagnostics(self) -> str:
        inbound = " | ".join(self._recent_inbound_messages) or "-"
        outbound = " | ".join(self._recent_outbound_messages) or "-"
        pending_ids = ",".join(str(req_id) for req_id in sorted(self._pending.keys())) or "-"
        return (
            f"transport={self._transport} "
            f"pending={len(self._pending)}[{pending_ids}] "
            f"event_q={self._event_queue.qsize()} "
            f"server_q={self._server_request_queue.qsize()} "
            f"recent_inbound=[{inbound}] "
            f"recent_outbound=[{outbound}]"
        )

    def _fail_pending_requests(self, error: Exception) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(error)
        self._pending.clear()

    def _notify_disconnect_callbacks_once(self) -> None:
        if self._disconnect_notified:
            return
        self._disconnect_notified = True
        for cb in self._disconnect_callbacks:
            try:
                cb()
            except Exception as e:
                logger.error(f"断线回调异常：{e}")

    # ------------------------------------------------------------------
    # 心跳
    # ------------------------------------------------------------------

    async def _send_raw(self, payload: str) -> None:
        """按当前 transport 发送原始 JSON-RPC 文本。"""
        self._record_protocol_message("outbound", payload)
        if self._transport == "ws":
            if self._ws is None:
                raise RuntimeError("WebSocket 未连接")
            try:
                await self._ws.send(payload)
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"app-server WebSocket 发送失败，连接已关闭：{e}")
                logger.warning("[disconnect_diagnostics] %s", self._build_disconnect_diagnostics())
                self._connected = False
                self._fail_pending_requests(RuntimeError("app-server 连接断开"))
                self._notify_disconnect_callbacks_once()
                raise RuntimeError("app-server 连接断开") from e
            return

        if self._stdio_stdin is None:
            raise RuntimeError("stdio stdin 未连接")
        self._stdio_stdin.write((payload + "\n").encode())
        await self._stdio_stdin.drain()

    async def _recv_raw(self) -> str:
        """按当前 transport 读取一条原始 JSON-RPC 文本。"""
        if self._transport == "ws":
            if self._ws is None:
                raise RuntimeError("WebSocket 未连接")
            raw = await self._ws.recv()
            return raw.decode() if isinstance(raw, bytes) else raw

        if self._stdio_stdout is None:
            raise RuntimeError("stdio stdout 未连接")
        while True:
            newline_index = self._stdio_buffer.find(b"\n")
            if newline_index != -1:
                raw = bytes(self._stdio_buffer[:newline_index])
                del self._stdio_buffer[:newline_index + 1]
                return raw.decode(errors="replace")

            chunk = await self._stdio_stdout.read(65536)
            if not chunk:
                raise EOFError("stdio 连接已关闭")
            self._stdio_buffer.extend(chunk)

    async def _heartbeat_loop(self) -> None:
        """
        每 30 秒做一次传输层保活。
        - ws 模式：使用底层 websocket ping，避免在活跃 turn 中额外插入业务 RPC
        - stdio 模式：保留 thread/list(limit=1) 作为轻量探活
        容错机制：允许连续失败 3 次才触发断线（提升稳定性）。
        """
        while self._connected:
            await asyncio.sleep(30)
            if not self._connected:
                break
            try:
                if self._transport == "ws":
                    if self._ws is None:
                        raise RuntimeError("WebSocket 未连接")
                    pong_waiter = await self._ws.ping()
                    await pong_waiter
                else:
                    await self._call("thread/list", {"limit": 1})
                # 心跳成功，重置失败计数
                if self._heartbeat_fail_count > 0:
                    logger.info(f"[heartbeat] 心跳恢复，重置失败计数（之前失败 {self._heartbeat_fail_count} 次）")
                    self._heartbeat_fail_count = 0
            except Exception as e:
                self._heartbeat_fail_count += 1
                logger.warning(
                    f"[heartbeat] 心跳失败 ({self._heartbeat_fail_count}/{self._heartbeat_max_fails})：{e}"
                )
                
                # 只有连续失败达到阈值才触发断线
                if self._heartbeat_fail_count >= self._heartbeat_max_fails:
                    logger.error(
                        f"[heartbeat] 连续失败 {self._heartbeat_fail_count} 次，触发断线"
                    )
                    self._connected = False
                    self._fail_pending_requests(RuntimeError("app-server 连接断开"))
                    self._notify_disconnect_callbacks_once()
                    break

    # ------------------------------------------------------------------
    # 接收循环
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        """
        持续读取 app-server 消息，分发给 pending futures 或事件回调。
        改进错误处理：连接断开时触发回调，但不抛异常。
        """
        try:
            while self._connected:
                try:
                    raw = await self._recv_raw()
                except EOFError:
                    logger.warning("app-server stdio 连接已关闭")
                    logger.warning("[disconnect_diagnostics] %s", self._build_disconnect_diagnostics())
                    self._connected = False
                    break
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning(f"app-server WebSocket 连接已关闭：{e.code} {e.reason}")
                    logger.warning("[disconnect_diagnostics] %s", self._build_disconnect_diagnostics())
                    self._connected = False
                    break
                except Exception as e:
                    logger.error(f"接收 app-server 消息异常：{e}")
                    # 非连接关闭的异常，尝试继续运行
                    continue

                try:
                    await self._dispatch(raw)
                except Exception as e:
                    logger.error(f"消息分发异常：{e}，消息内容：{raw[:200]}")
                    # 分发失败不应导致整个接收循环崩溃
                    continue
        except asyncio.CancelledError:
            logger.info("接收循环被取消")
        except Exception as e:
            logger.error(f"app-server 接收循环异常：{e}")
            self._connected = False
        finally:
            if not self._connected:
                self._fail_pending_requests(RuntimeError("app-server 连接断开"))
                self._notify_disconnect_callbacks_once()

    # ------------------------------------------------------------------
    # 消息分发 — 事件兼容桥核心
    # ------------------------------------------------------------------

    def _ensure_event_worker(self) -> None:
        """确保通知事件由独立 worker 顺序消费，避免阻塞 WebSocket 接收循环。"""
        if self._event_worker_task and not self._event_worker_task.done():
            return

        self._event_worker_task = asyncio.create_task(
            self._event_worker_loop(),
            name="adapter-event-worker",
        )

    async def _event_worker_loop(self) -> None:
        """顺序消费 server notification，保持事件顺序但不阻塞 _recv_loop。"""
        try:
            while True:
                method, envelope = await self._event_queue.get()
                try:
                    for cb in self._event_callbacks:
                        try:
                            await cb(method, envelope)
                        except Exception as e:
                            event_method = envelope.get("message", {}).get("method", "?")
                            logger.error(f"事件回调异常 method={event_method}：{e}")
                finally:
                    self._event_queue.task_done()
        except asyncio.CancelledError:
            logger.info("事件分发循环被取消")

    def _ensure_server_request_worker(self) -> None:
        """确保 server request 由独立 worker 顺序消费，避免阻塞 WebSocket 接收循环。"""
        if self._server_request_worker_task and not self._server_request_worker_task.done():
            return

        self._server_request_worker_task = asyncio.create_task(
            self._server_request_worker_loop(),
            name="adapter-server-request-worker",
        )

    async def _server_request_worker_loop(self) -> None:
        """顺序消费 server request，保持请求顺序但不阻塞 _recv_loop。"""
        try:
            while True:
                method, params, request_id = await self._server_request_queue.get()
                try:
                    for cb in self._server_request_callbacks:
                        try:
                            await cb(method, params, request_id)
                        except Exception as e:
                            logger.error(f"server request 回调异常 method={method}：{e}")
                finally:
                    self._server_request_queue.task_done()
        except asyncio.CancelledError:
            logger.info("server request 分发循环被取消")

    async def _dispatch(self, raw: str) -> None:
        """解析 JSON 消息，路由到对应的 future、事件回调或 server request 回调。"""
        if not raw:
            return
        self._record_protocol_message("inbound", raw)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"收到非 JSON 消息：{raw[:100]}")
            return

        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        # 调试日志：记录所有含 requestApproval 的原始消息
        if "requestApproval" in raw or "Approval" in raw:
            logger.info(f"[raw_approval] {raw[:600]}")

        if msg_id is not None and method:
            # ── Server request（如 requestApproval）──
            # 关键决策（Pitfall 1）：只派发给 on_server_request 回调，
            # 不同时包装为 app-server-event。避免 events.py 中两条路径都触发导致重复。
            logger.debug(f"收到 server request id={msg_id} method={method}")
            if self._server_request_callbacks:
                self._ensure_server_request_worker()
                await self._server_request_queue.put((method, params, msg_id))

        elif msg_id is not None and not method:
            # ── RPC 响应 ──
            fut = self._pending.pop(msg_id, None)
            if fut is None or fut.done():
                return
            if "error" in msg:
                fut.set_exception(RuntimeError(msg["error"].get("message", "unknown error")))
            else:
                # app-server 响应是单层 {id, result: <data>}，无需双层解包（Pitfall 2）
                fut.set_result(msg.get("result"))

        elif method and msg_id is None:
            # ── Server notification（事件）──
            # 先维护 thread_id → workspace_id 映射，再包装事件信封。
            # 这样像 turn/started 这类首个事件，如果携带 cwd，也能在当前事件内解析到 workspace。
            self._update_thread_workspace_map(method, params)
            workspace_id = self._resolve_workspace_id_from_params(params)
            envelope = {
                "message": {"method": method, "params": params},
                "workspace_id": workspace_id,
            }
            if self._event_callbacks:
                self._ensure_event_worker()
                await self._event_queue.put(("app-server-event", envelope))

    def _update_thread_workspace_map(self, method: str, params: dict) -> None:
        """从事件中提取 threadId，更新 thread → workspace 反向映射。"""
        thread_id = self._extract_thread_id_from_event_params(params)

        if thread_id and thread_id not in self._thread_workspace_map:
            # 尝试基于 cwd 关联
            cwd = params.get("cwd") or ""
            if cwd:
                for ws_id, ws_cwd in self._workspace_cwd_map.items():
                    if ws_cwd == cwd:
                        self._thread_workspace_map[thread_id] = ws_id
                        logger.debug(f"[thread_map] cwd 关联：{thread_id[:12]}… → {ws_id}")
                        return
            # 找不到明确映射时不猜测，等后续事件补全（如 thread/start 会写入映射）
            logger.debug(f"[thread_map] thread {thread_id[:12]}… 暂无 workspace 映射，跳过")
