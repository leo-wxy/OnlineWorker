# core/process.py
"""
codex app-server 子进程生命周期管理。

支持两种传输：
- `ws://127.0.0.1:<port>`：解析启动输出获取 listening URL 和 readyz URL
- `stdio://`：通过 stdin/stdout 走 JSON-RPC，不再占用本地端口
"""
import asyncio
import logging
import os
import urllib.request
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


def _build_subprocess_env() -> dict:
    """
    构建子进程 env，在继承当前 os.environ 的基础上，
    确保 PATH 包含常见工具目录（应对 .app 极简 PATH 或 PyInstaller 环境）。
    """
    env = os.environ.copy()
    home = os.path.expanduser("~")
    extra_paths = [
        os.path.join(home, ".local", "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    current_path = env.get("PATH", "")
    current_parts = [p for p in current_path.split(":") if p]
    # Prepend extra paths that are not already present
    prepend = [p for p in extra_paths if p not in current_parts]
    env["PATH"] = ":".join(prepend + current_parts) if current_parts else ":".join(prepend)
    return env


async def _read_process_failure(
    proc: asyncio.subprocess.Process,
    prefix: str,
    collected_lines: list[str],
) -> RuntimeError:
    """读取子进程剩余输出，返回包含真实失败原因的异常。"""
    exit_code = proc.returncode
    if exit_code is None:
        exit_code = await proc.wait()

    tail_text = ""
    if proc.stdout is not None:
        tail_text = (await proc.stdout.read()).decode(errors="replace").strip()

    details_parts = [line for line in collected_lines if line]
    if tail_text:
        details_parts.extend([line for line in tail_text.splitlines() if line])

    details = "\n".join(details_parts).strip() or "无启动输出"
    return RuntimeError(f"{prefix} (code={exit_code}): {details}")


class AppServerProcess:
    """管理 codex app-server 子进程的生命周期。"""

    def __init__(self, codex_bin: str = "codex", port: int = 0, protocol: str = "ws"):
        """
        Args:
            codex_bin: codex 可执行文件路径
            port: 监听端口，0 = 动态分配（OS 选择）
            protocol: "ws" 或 "stdio"
        """
        self.codex_bin = codex_bin
        self.port = port
        self.protocol = protocol
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stdout_task: Optional[asyncio.Task] = None
        self.ws_url: Optional[str] = None
        self.readyz_url: Optional[str] = None
        self._recent_output_lines: deque[str] = deque(maxlen=40)

    async def start(self) -> str:
        """启动 app-server，返回连接端点字符串（`ws://...` 或 `stdio://`）。"""
        if self._proc and self._proc.returncode is None:
            logger.info("app-server 已在运行，跳过启动")
            return self.ws_url if self.protocol == "ws" else "stdio://"

        listen_url = "stdio://" if self.protocol == "stdio" else f"ws://127.0.0.1:{self.port}"
        cmd = [self.codex_bin, "app-server", "--listen", listen_url]

        logger.info(f"启动 app-server：{' '.join(cmd)}")
        stderr_target = asyncio.subprocess.PIPE if self.protocol == "stdio" else asyncio.subprocess.STDOUT
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_target,
            env=_build_subprocess_env(),
        )

        if self.protocol == "stdio":
            return await self._start_stdio()
        return await self._start_ws()

    async def _start_stdio(self) -> str:
        """启动 stdio 模式 app-server。"""
        if self._proc is None:
            raise RuntimeError("app-server 进程未创建")
        if self._proc.stdout is None or self._proc.stdin is None:
            raise RuntimeError("app-server stdio 模式未拿到 stdin/stdout")

        self.ws_url = None
        self.readyz_url = None

        if self._proc.stderr is not None:
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(self._proc.stderr),
                name="app-server-stderr",
            )

        await asyncio.sleep(0.1)
        if self._proc.returncode is not None:
            raise await _read_process_failure(
                self._proc,
                "app-server 启动失败：进程退出",
                [],
            )

        logger.info("app-server 已就绪：stdio://")
        return "stdio://"

    async def _start_ws(self) -> str:
        """启动 WebSocket 模式 app-server。"""
        if self._proc is None:
            raise RuntimeError("app-server 进程未创建")

        # 解析合并后的启动输出，提取 listening URL 和 readyz URL
        if self._proc.stdout is None:
            raise RuntimeError("app-server 进程 stdout 为 None，无法读取启动输出")

        collected_lines = []
        for i in range(30):
            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=2.0)
                if not line:
                    await asyncio.sleep(0)
                    if self._proc.returncode is not None:
                        raise await _read_process_failure(
                            self._proc,
                            "app-server 进程提前退出",
                            collected_lines,
                        )
                    break
                text = line.decode().strip()
                collected_lines.append(text)
                self._record_output_line(text)
                logger.info(f"[app-server] {text}")
                
                if "listening on:" in text:
                    self.ws_url = text.split("listening on:")[1].strip()
                if "readyz:" in text:
                    self.readyz_url = text.split("readyz:")[1].strip()
                    break
            except asyncio.TimeoutError:
                if self._proc.returncode is not None:
                    raise await _read_process_failure(
                        self._proc,
                        "app-server 启动失败：进程退出",
                        collected_lines,
                    )
                continue

        if not self.ws_url:
            if self._proc.returncode is not None:
                raise await _read_process_failure(
                    self._proc,
                    "app-server 启动失败：进程退出",
                    collected_lines,
                )
            raise RuntimeError(f"app-server 启动失败：未能获取 listening URL。输出：{collected_lines}")

        # 轮询 /readyz 确认就绪
        await self._poll_readyz()
        self._stdout_task = asyncio.create_task(
            self._drain_stream(self._proc.stdout),
            name="app-server-stdout",
        )
        logger.info(f"app-server 已就绪：{self.ws_url}")
        return self.ws_url

    async def _drain_stream(self, stream: asyncio.StreamReader) -> None:
        """持续读取子进程输出，避免 pipe 因无人消费而阻塞。"""
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    self._record_output_line(text)
                    logger.info(f"[app-server] {text}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug(f"读取 app-server 输出失败：{e}")

    async def _drain_stderr(self, stream: asyncio.StreamReader) -> None:
        """兼容旧调用点，统一委托到通用 drain。"""
        await self._drain_stream(stream)

    def _record_output_line(self, text: str) -> None:
        text = text.strip()
        if text:
            self._recent_output_lines.append(text)

    def diagnostics_snapshot(self) -> str:
        """返回 app-server 子进程的最新诊断摘要。"""
        pid = self._proc.pid if self._proc is not None else None
        returncode = self._proc.returncode if self._proc is not None else None
        recent_output = " | ".join(self._recent_output_lines) or "-"
        return (
            f"pid={pid if pid is not None else '-'} "
            f"running={self.running} "
            f"returncode={returncode if returncode is not None else '-'} "
            f"protocol={self.protocol} "
            f"ws_url={self.ws_url or '-'} "
            f"readyz_url={self.readyz_url or '-'} "
            f"recent_output=[{recent_output}]"
        )

    async def _poll_readyz(self, timeout: float = 10.0, interval: float = 0.5) -> None:
        """轮询 /readyz 端点直到返回 HTTP 200 或超时。使用 run_in_executor 避免阻塞事件循环。"""
        if not self.readyz_url:
            logger.warning("无 readyz URL，跳过就绪检查")
            return

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            try:
                resp = await loop.run_in_executor(
                    None, lambda: urllib.request.urlopen(self.readyz_url)
                )
                if resp.status == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(interval)

        raise RuntimeError(f"app-server /readyz 未在 {timeout}s 内就绪")

    async def stop(self) -> None:
        """停止 app-server 子进程。"""
        if self._stdout_task and not self._stdout_task.done():
            self._stdout_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            logger.info("app-server 已停止")
        self._proc = None
        self.ws_url = None
        self.readyz_url = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None
