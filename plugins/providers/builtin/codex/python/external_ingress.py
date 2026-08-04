from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
import select
import sys
from typing import Any


logger = logging.getLogger(__name__)

_OWNED_THREAD_SOURCES = {"app", "provider", "telegram_new_thread"}
_WATCH_FLAGS = (
    getattr(select, "KQ_NOTE_WRITE", 0)
    | getattr(select, "KQ_NOTE_EXTEND", 0)
    | getattr(select, "KQ_NOTE_ATTRIB", 0)
    | getattr(select, "KQ_NOTE_DELETE", 0)
    | getattr(select, "KQ_NOTE_RENAME", 0)
    | getattr(select, "KQ_NOTE_REVOKE", 0)
)
_RELOAD_FLAGS = (
    getattr(select, "KQ_NOTE_DELETE", 0)
    | getattr(select, "KQ_NOTE_RENAME", 0)
    | getattr(select, "KQ_NOTE_REVOKE", 0)
)


@dataclass
class _RolloutState:
    session_id: str
    cwd: str = ""
    turn_id: str = ""
    prompt: str = ""
    final_text: str = ""
    started_turn_id: str = ""
    terminal_turn_ids: set[str] = field(default_factory=set)


@dataclass
class _VnodeWatch:
    fd: int
    path: str
    is_dir: bool
    offset: int = 0
    partial: bytes = b""


def _thread_id_from_rollout_path(path: str) -> str:
    name = Path(path).name
    if not name.startswith("rollout-") or not name.endswith(".jsonl"):
        return ""
    parts = name[:-6].split("-")
    if len(parts) < 6:
        return ""
    return "-".join(parts[-5:])


def _content_text(payload: dict[str, Any]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") not in {"input_text", "output_text", "text"}:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _task_complete_text(payload: dict[str, Any]) -> str:
    value = payload.get("last_agent_message")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "message"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return ""


class CodexDesktopRolloutIngress:
    """Turns externally-owned Codex Desktop rollout appends into provider events."""

    def __init__(self, *, adapter, state, sessions_dir: str | None = None) -> None:
        self._adapter = adapter
        self._state = state
        self._sessions_dir = os.path.abspath(
            os.path.expanduser(sessions_dir or "~/.codex/sessions")
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._kqueue = None
        self._watches_by_fd: dict[int, _VnodeWatch] = {}
        self._fd_by_path: dict[str, int] = {}
        self._rollouts: dict[str, _RolloutState] = {}
        self._pending_files: set[int] = set()
        self._needs_rescan = False
        self._drain_task: asyncio.Task | None = None
        self._closed = True

    @property
    def running(self) -> bool:
        return not self._closed and self._kqueue is not None

    async def start(self) -> dict[str, Any]:
        if self.running:
            return {"state": "running", "sessionsDir": self._sessions_dir}
        if (
            sys.platform != "darwin"
            or not hasattr(select, "kqueue")
            or not hasattr(asyncio.get_running_loop(), "add_reader")
        ):
            return {
                "state": "unsupported",
                "detail": "Codex Desktop rollout ingress requires macOS kqueue",
                "sessionsDir": self._sessions_dir,
            }
        if not os.path.isdir(self._sessions_dir):
            return {
                "state": "unavailable",
                "detail": "Codex sessions directory does not exist",
                "sessionsDir": self._sessions_dir,
            }

        self._loop = asyncio.get_running_loop()
        self._kqueue = select.kqueue()
        self._closed = False
        try:
            self._scan_tree(initial=True)
            self._loop.add_reader(self._kqueue.fileno(), self._on_kqueue_ready)
            self._pending_files.update(
                watch.fd for watch in self._watches_by_fd.values() if not watch.is_dir
            )
            self._ensure_drain_task()
        except Exception:
            await self.close()
            raise

        logger.info(
            "[codex-external-ingress] 已监听 Desktop rollout files=%s dirs=%s root=%s",
            sum(not watch.is_dir for watch in self._watches_by_fd.values()),
            sum(watch.is_dir for watch in self._watches_by_fd.values()),
            self._sessions_dir,
        )
        return {"state": "running", "sessionsDir": self._sessions_dir}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._loop is not None and self._kqueue is not None:
            try:
                self._loop.remove_reader(self._kqueue.fileno())
            except Exception:
                pass

        current = asyncio.current_task()
        drain_task = self._drain_task
        self._drain_task = None
        if drain_task is not None and drain_task is not current and not drain_task.done():
            drain_task.cancel()
            await asyncio.gather(drain_task, return_exceptions=True)

        for fd in list(self._watches_by_fd):
            self._unregister_fd(fd)
        if self._kqueue is not None:
            try:
                self._kqueue.close()
            except Exception:
                pass
        self._kqueue = None
        self._loop = None
        self._pending_files.clear()
        self._needs_rescan = False

    def _scan_tree(self, *, initial: bool) -> None:
        seen: set[str] = set()
        for root, dirnames, filenames in os.walk(self._sessions_dir, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not os.path.islink(os.path.join(root, name))
            ]
            root_path = os.path.abspath(root)
            seen.add(root_path)
            self._register_path(root_path, is_dir=True, initial=initial)
            for filename in filenames:
                if not filename.startswith("rollout-") or not filename.endswith(".jsonl"):
                    continue
                path = os.path.abspath(os.path.join(root, filename))
                seen.add(path)
                self._register_path(path, is_dir=False, initial=initial)

        for path, fd in list(self._fd_by_path.items()):
            if path not in seen:
                self._unregister_fd(fd)

    def _register_path(self, path: str, *, is_dir: bool, initial: bool) -> None:
        existing_fd = self._fd_by_path.get(path)
        if existing_fd is not None:
            existing = self._watches_by_fd.get(existing_fd)
            try:
                path_stat = os.stat(path)
                fd_stat = os.fstat(existing_fd)
            except OSError:
                self._unregister_fd(existing_fd)
            else:
                if (
                    existing is not None
                    and existing.is_dir == is_dir
                    and path_stat.st_dev == fd_stat.st_dev
                    and path_stat.st_ino == fd_stat.st_ino
                ):
                    return
                self._unregister_fd(existing_fd)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        if is_dir:
            flags |= getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(path, flags)
            stat = os.fstat(fd)
        except OSError:
            return

        watch = _VnodeWatch(
            fd=fd,
            path=path,
            is_dir=is_dir,
            offset=stat.st_size if initial and not is_dir else 0,
        )
        try:
            event = select.kevent(
                fd,
                filter=select.KQ_FILTER_VNODE,
                flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                fflags=_WATCH_FLAGS,
                udata=fd,
            )
            self._kqueue.control([event], 0, 0)
        except Exception:
            os.close(fd)
            return

        self._watches_by_fd[fd] = watch
        self._fd_by_path[path] = fd
        if is_dir:
            return
        if initial:
            self._seed_rollout_state(watch)
        else:
            self._rollouts.setdefault(
                watch.path,
                _RolloutState(session_id=_thread_id_from_rollout_path(watch.path)),
            )
        self._pending_files.add(fd)

    def _unregister_fd(self, fd: int) -> None:
        watch = self._watches_by_fd.pop(fd, None)
        if watch is None:
            return
        self._fd_by_path.pop(watch.path, None)
        self._pending_files.discard(fd)
        if not watch.is_dir:
            self._rollouts.pop(watch.path, None)
        if self._kqueue is not None:
            try:
                event = select.kevent(
                    fd,
                    filter=select.KQ_FILTER_VNODE,
                    flags=select.KQ_EV_DELETE,
                )
                self._kqueue.control([event], 0, 0)
            except Exception:
                pass
        try:
            os.close(fd)
        except OSError:
            pass

    def _seed_rollout_state(self, watch: _VnodeWatch) -> None:
        state = self._rollouts.setdefault(
            watch.path,
            _RolloutState(session_id=_thread_id_from_rollout_path(watch.path)),
        )
        try:
            size = os.fstat(watch.fd).st_size
            head = os.pread(watch.fd, min(size, 256 * 1024), 0)
            tail_start = max(0, size - 256 * 1024)
            tail = os.pread(watch.fd, size - tail_start, tail_start) if tail_start else b""
        except OSError:
            return
        for raw in (head + (b"\n" + tail if tail else b"")).splitlines():
            self._update_rollout_state(state, raw, historical=True)

    def _on_kqueue_ready(self) -> None:
        if self._closed or self._kqueue is None:
            return
        try:
            events = self._kqueue.control(None, 512, 0)
        except Exception:
            logger.warning("[codex-external-ingress] 读取 kqueue 事件失败", exc_info=True)
            return
        for event in events:
            fd = int(event.udata if event.udata is not None else event.ident)
            watch = self._watches_by_fd.get(fd)
            if watch is None:
                continue
            if watch.is_dir:
                self._needs_rescan = True
            else:
                self._pending_files.add(fd)
            if int(event.fflags or 0) & _RELOAD_FLAGS:
                self._needs_rescan = True
        self._ensure_drain_task()

    def _ensure_drain_task(self) -> None:
        if self._closed or self._loop is None:
            return
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = self._loop.create_task(
                self._drain_pending(),
                name="codex-desktop-rollout-ingress",
            )

    async def _drain_pending(self) -> None:
        try:
            while not self._closed:
                pending = list(self._pending_files)
                self._pending_files.clear()
                for fd in pending:
                    await self._read_appended_lines(fd)

                if self._needs_rescan:
                    self._needs_rescan = False
                    self._scan_tree(initial=False)
                    continue
                if not self._pending_files:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[codex-external-ingress] 处理 rollout 追加失败", exc_info=True)
        finally:
            if (
                not self._closed
                and self._loop is not None
                and (self._needs_rescan or self._pending_files)
            ):
                self._loop.call_soon(self._ensure_drain_task)

    async def _read_appended_lines(self, fd: int) -> None:
        watch = self._watches_by_fd.get(fd)
        if watch is None or watch.is_dir:
            return
        try:
            size = os.fstat(fd).st_size
        except OSError:
            self._needs_rescan = True
            return
        if size < watch.offset:
            watch.offset = 0
            watch.partial = b""
        if size <= watch.offset:
            return

        chunks: list[bytes] = []
        while watch.offset < size:
            try:
                chunk = os.pread(fd, min(256 * 1024, size - watch.offset), watch.offset)
            except OSError:
                self._needs_rescan = True
                return
            if not chunk:
                break
            chunks.append(chunk)
            watch.offset += len(chunk)
        if not chunks:
            return

        data = watch.partial + b"".join(chunks)
        lines = data.split(b"\n")
        watch.partial = lines.pop() if lines else data
        for raw in lines:
            if raw.strip():
                await self._process_rollout_line(watch.path, raw)

    def _update_rollout_state(
        self,
        state: _RolloutState,
        raw: bytes,
        *,
        historical: bool,
    ) -> tuple[str, dict[str, Any]] | None:
        try:
            row = json.loads(raw.decode("utf-8", errors="ignore"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        row_type = str(row.get("type") or "")
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if row_type == "session_meta":
            state.session_id = str(payload.get("id") or state.session_id).strip()
            state.cwd = str(payload.get("cwd") or state.cwd).strip()
        elif row_type == "turn_context":
            state.turn_id = str(
                payload.get("turn_id") or payload.get("turnId") or state.turn_id
            ).strip()
        elif row_type == "event_msg":
            payload_type = str(payload.get("type") or "")
            event_turn_id = str(
                payload.get("turn_id") or payload.get("turnId") or ""
            ).strip()
            if payload_type == "task_started" and event_turn_id:
                state.turn_id = event_turn_id
                state.prompt = ""
                state.final_text = ""
            elif payload_type in {"task_complete", "turn_aborted"} and historical:
                if event_turn_id:
                    state.terminal_turn_ids.add(event_turn_id)
        elif row_type == "response_item":
            role = str(payload.get("role") or "")
            phase = str(payload.get("phase") or "")
            text = _content_text(payload)
            if role == "user" and text:
                state.prompt = text
            elif role == "assistant" and phase == "final_answer" and text:
                state.final_text = text
        return row_type, payload

    async def _process_rollout_line(self, path: str, raw: bytes) -> None:
        state = self._rollouts.setdefault(
            path,
            _RolloutState(session_id=_thread_id_from_rollout_path(path)),
        )
        parsed = self._update_rollout_state(state, raw, historical=False)
        if parsed is None or not state.session_id:
            return
        row_type, payload = parsed
        if not self._should_publish_session(state.session_id):
            return

        if row_type == "response_item" and str(payload.get("role") or "") == "user":
            if not state.prompt or not state.turn_id or state.started_turn_id == state.turn_id:
                return
            result = await self._adapter.ingest_external_hook_payload(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": state.session_id,
                    "turn_id": state.turn_id,
                    "cwd": state.cwd,
                    "prompt": state.prompt,
                    "source": "codex_rollout",
                }
            )
            if not isinstance(result, dict) or result.get("accepted") is not False:
                state.started_turn_id = state.turn_id
            return

        if row_type != "event_msg":
            return
        payload_type = str(payload.get("type") or "")
        if payload_type != "task_complete":
            return
        turn_id = str(
            payload.get("turn_id") or payload.get("turnId") or state.turn_id
        ).strip()
        if not turn_id or turn_id in state.terminal_turn_ids:
            return
        final_text = _task_complete_text(payload) or state.final_text
        hook_event_name = "Stop" if state.started_turn_id == turn_id else "AgentTurnComplete"
        hook_payload: dict[str, Any] = {
            "hook_event_name": hook_event_name,
            "session_id": state.session_id,
            "turn_id": turn_id,
            "cwd": state.cwd,
            "last_assistant_message": final_text,
            "source": "codex_rollout",
        }
        if hook_event_name == "AgentTurnComplete" and state.prompt:
            hook_payload["input_messages"] = [state.prompt]
        result = await self._adapter.ingest_external_hook_payload(hook_payload)
        if not isinstance(result, dict) or result.get("accepted") is not False:
            state.terminal_turn_ids.add(turn_id)
            state.turn_id = turn_id
            logger.info(
                "[codex-external-ingress] 已接收 Desktop completion session=%s turn=%s",
                state.session_id[:12],
                turn_id[:12],
            )

    def _should_publish_session(self, session_id: str) -> bool:
        live_check = getattr(self._adapter, "has_authoritative_live_session", None)
        if callable(live_check) and live_check(session_id):
            return False
        found = self._state.find_thread_by_id_global(session_id)
        if not found:
            return True
        _workspace, thread = found
        source = str(getattr(thread, "source", "") or "unknown").strip().lower()
        if source in _OWNED_THREAD_SOURCES:
            return False
        if source != "imported":
            return True
        config = getattr(self._state, "config", None)
        tool = config.get_tool("codex") if config is not None else None
        live_transport = str(getattr(tool, "live_transport", "") or "").strip().lower()
        return live_transport not in {"shared_ws", "shared_unix"}
