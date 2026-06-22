import asyncio
import json
import logging
import os
import pty
import signal
import sys
import time
from typing import Optional

from core.providers.facts import query_provider_active_thread_ids
from plugins.providers.builtin.codex.python.tui_host_protocol import (
    build_send_message_request,
    host_socket_path,
    write_host_status,
)
from core.storage import load_storage, save_storage
from plugins.providers.builtin.codex.python.storage_runtime import list_codex_threads_by_cwd

logger = logging.getLogger(__name__)


def build_codex_resume_command(
    *,
    codex_bin: str,
    thread_id: str,
    cwd: str,
    remote_url: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> list[str]:
    cmd = [
        codex_bin,
        "resume",
        thread_id,
        "--cd",
        cwd,
    ]
    if remote_url:
        cmd[3:3] = ["--remote", remote_url]
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def _config_override_value(args: list[str], index: int) -> str:
    current = args[index]
    if current.startswith("--config="):
        return current.split("=", 1)[1]
    if current.startswith("-c") and current != "-c":
        return current[2:]
    if index + 1 < len(args):
        return args[index + 1]
    return ""


def _has_approvals_reviewer_override(args: list[str]) -> bool:
    for index, arg in enumerate(args):
        if arg == "--config" or arg == "-c" or arg.startswith("--config=") or (
            arg.startswith("-c") and arg != "-c"
        ):
            if _config_override_value(args, index).strip().startswith("approvals_reviewer"):
                return True
    return False


def ensure_codex_tui_host_extra_args(extra_args: Optional[list[str]] = None) -> list[str]:
    args = list(extra_args or [])
    if not _has_approvals_reviewer_override(args):
        args.extend(["-c", 'approvals_reviewer="user"'])
    return args


def build_codex_tui_child_env(
    *,
    base_env: Optional[dict[str, str]] = None,
    cwd: str,
    thread_id: str,
) -> dict[str, str]:
    env = dict(base_env if base_env is not None else os.environ)
    env["PWD"] = cwd
    env["CODEX_THREAD_ID"] = thread_id
    env["ONLINEWORKER_CODEX_TUI_HOST"] = "1"
    return env


def encode_terminal_input(text: str) -> bytes:
    # Use bracketed paste to reduce the chance that multiline content or special
    # characters are interpreted as interactive shortcuts.
    return b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~\r"


def validate_thread_binding(*, active_thread_id: Optional[str], request_thread_id: str) -> None:
    if active_thread_id != request_thread_id:
        raise RuntimeError(
            f"当前 TUI 绑定 thread={active_thread_id or '<none>'}，无法投递到 thread={request_thread_id}"
        )


def resolve_host_thread_id(
    *,
    cwd: str,
    data_dir: str,
    thread_id: Optional[str] = None,
    topic_id: Optional[int] = None,
) -> str:
    if thread_id:
        return thread_id

    if topic_id is not None:
        raise RuntimeError(
            "当前版本不再从 onlineworker_state.json 按 topic_id 反查 codex thread；"
            "请传入 codex thread_id。"
        )

    recent_threads = list_codex_threads_by_cwd(cwd, limit=1)
    if recent_threads:
        latest_thread_id = recent_threads[0].get("id")
        if latest_thread_id:
            return latest_thread_id

    raise RuntimeError("当前工作区下没有可恢复的 codex thread，请先在 TUI 或 TG 中创建/激活一个 thread")


async def run_codex_tui_host_once(
    *,
    data_dir: str,
    cwd: str,
    target: Optional[str] = None,
    remote_url: Optional[str] = None,
    provider_bin: Optional[str] = None,
    codex_bin: str = "codex",
    extra_args: Optional[list[str]] = None,
) -> int:
    resolved_bin = str(provider_bin or codex_bin or "codex")
    normalized_target = str(target or "").strip()
    explicit_thread_id = normalized_target or None
    explicit_topic_id = None
    if normalized_target.isdigit():
        explicit_topic_id = int(normalized_target)
        explicit_thread_id = None

    thread_id = resolve_host_thread_id(
        cwd=cwd,
        data_dir=data_dir,
        thread_id=explicit_thread_id,
        topic_id=explicit_topic_id,
    )
    host = CodexTuiHost(
        data_dir=data_dir,
        thread_id=thread_id,
        cwd=cwd,
        remote_url=remote_url,
        codex_bin=resolved_bin,
        extra_args=extra_args,
    )
    return await host.run()


class CodexTuiHost:
    def __init__(
        self,
        *,
        data_dir: str,
        thread_id: str,
        cwd: str,
        remote_url: Optional[str] = None,
        codex_bin: str = "codex",
        extra_args: Optional[list[str]] = None,
    ) -> None:
        self.data_dir = data_dir
        self.thread_id = thread_id
        self.cwd = cwd
        self.remote_url = remote_url or ""
        self.codex_bin = codex_bin
        self.extra_args = ensure_codex_tui_host_extra_args(extra_args)
        self.socket_path = host_socket_path(data_dir)
        if self.socket_path is None:
            raise RuntimeError("缺少 codex TUI host socket 路径")

        self._server: Optional[asyncio.AbstractServer] = None
        self._master_fd: Optional[int] = None
        self._child_pid: Optional[int] = None
        self._pump_task: Optional[asyncio.Task] = None
        self._status_task: Optional[asyncio.Task] = None

    async def run(self) -> int:
        await self.start()
        try:
            return await self._wait_for_child_exit()
        finally:
            await self.stop()

    async def start(self) -> None:
        if self._child_pid is not None:
            return

        os.makedirs(self.data_dir, exist_ok=True)
        if self.socket_path and os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        cmd = build_codex_resume_command(
            codex_bin=self.codex_bin,
            thread_id=self.thread_id,
            cwd=self.cwd,
            remote_url=self.remote_url or None,
            extra_args=self.extra_args,
        )
        child_pid, master_fd = pty.fork()
        if child_pid == 0:
            os.chdir(self.cwd)
            child_env = build_codex_tui_child_env(
                base_env=dict(os.environ),
                cwd=self.cwd,
                thread_id=self.thread_id,
            )
            os.environ.clear()
            os.environ.update(child_env)
            os.execvp(cmd[0], cmd)

        self._child_pid = child_pid
        self._master_fd = master_fd
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        self._pump_task = asyncio.create_task(self._pump_terminal_output(), name="codex-tui-host-pump")
        self._status_task = asyncio.create_task(self._status_loop(), name="codex-tui-host-status")
        await self._write_status()

    async def stop(self) -> None:
        if self._status_task and not self._status_task.done():
            self._status_task.cancel()
        if self._pump_task and not self._pump_task.done():
            self._pump_task.cancel()

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass

        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

        child_pid = self._child_pid
        self._child_pid = None
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGHUP)
            except ProcessLookupError:
                pass

        await self._write_status(force_offline=True)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            request_type = request.get("type")

            if request_type == "send_message":
                response = await self._handle_send_message(request)
            elif request_type == "ping":
                response = {
                    "ok": True,
                    "pong": True,
                    "active_thread_id": self.thread_id,
                }
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
        request_thread_id = request.get("thread_id") or ""
        text = request.get("text") or ""

        try:
            validate_thread_binding(
                active_thread_id=self.thread_id,
                request_thread_id=request_thread_id,
            )
        except RuntimeError as e:
            return {
                "ok": False,
                "error": str(e),
                "active_thread_id": self.thread_id,
            }

        if not text:
            return {
                "ok": False,
                "error": "空消息，拒绝发送",
                "active_thread_id": self.thread_id,
            }

        if self._master_fd is None or self._child_pid is None:
            return {
                "ok": False,
                "error": "codex TUI host 未运行",
                "active_thread_id": self.thread_id,
            }

        try:
            os.write(self._master_fd, encode_terminal_input(text))
        except OSError as e:
            return {
                "ok": False,
                "error": f"写入 TUI 失败：{e}",
                "active_thread_id": self.thread_id,
            }

        return {
            "ok": True,
            "accepted": True,
            "active_thread_id": self.thread_id,
        }

    async def _status_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self._write_status()

    async def _write_status(self, *, force_offline: bool = False) -> None:
        child_alive = False
        if not force_offline and self._child_pid is not None:
            child_alive = self._child_alive(self._child_pid)

        payload = {
            "online": child_alive and self._server is not None,
            "pid": os.getpid(),
            "child_pid": self._child_pid,
            "cwd": self.cwd,
            "remote_url": self.remote_url,
            "active_thread_id": self.thread_id,
            "socket_path": self.socket_path,
            "updated_at_epoch": time.time(),
        }
        write_host_status(payload, data_dir=self.data_dir)

    @property
    def is_running(self) -> bool:
        return self._child_pid is not None and self._child_alive(self._child_pid)

    async def _pump_terminal_output(self) -> None:
        if self._master_fd is None:
            return

        while self._child_pid is not None and self._child_alive(self._child_pid):
            try:
                data = await asyncio.to_thread(os.read, self._master_fd, 4096)
            except OSError:
                break

            if not data:
                break

            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except Exception:
                break

    async def _wait_for_child_exit(self) -> int:
        while self._child_pid is not None:
            pid, status = os.waitpid(self._child_pid, os.WNOHANG)
            if pid == self._child_pid:
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                if os.WIFSIGNALED(status):
                    return 128 + os.WTERMSIG(status)
                return 1
            await asyncio.sleep(0.5)
        return 0

    @staticmethod
    def _child_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False


async def send_message_request(
    *,
    socket_path: str,
    thread_id: str,
    text: str,
    topic_id: Optional[int] = None,
) -> dict:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(
            json.dumps(
                build_send_message_request(thread_id=thread_id, text=text, topic_id=topic_id),
                ensure_ascii=False,
            ).encode("utf-8")
            + b"\n"
        )
        await writer.drain()
        raw = await reader.readline()
        return json.loads(raw.decode("utf-8")) if raw else {}
    finally:
        writer.close()
        await writer.wait_closed()
