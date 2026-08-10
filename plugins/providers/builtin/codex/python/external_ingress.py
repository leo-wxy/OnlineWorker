from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any

from watchfiles import Change, awatch

from plugins.providers.builtin.codex.python.storage_runtime import (
    is_codex_user_visible_session,
)


logger = logging.getLogger(__name__)

_OWNED_THREAD_SOURCES = {"app", "provider", "telegram_new_thread"}


@dataclass
class _RolloutState:
    session_id: str
    cwd: str = ""
    source: Any = None
    thread_source: str = ""
    parent_thread_id: str = ""
    user_visible: bool = True
    turn_id: str = ""
    prompt: str = ""
    final_text: str = ""
    started_turn_id: str = ""
    terminal_turn_ids: set[str] = field(default_factory=set)


@dataclass
class _RolloutCursor:
    path: str
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


def _is_rollout_path(path: str) -> bool:
    name = os.path.basename(path)
    return name.startswith("rollout-") and name.endswith(".jsonl")


def _rollout_watch_filter(_change: Change, path: str) -> bool:
    return _is_rollout_path(path)


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
        self._rollouts: dict[str, _RolloutState] = {}
        self._cursors: dict[str, _RolloutCursor] = {}
        self._pending_files: set[str] = set()
        self._watch_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._drain_task: asyncio.Task | None = None
        self._closed = True

    @property
    def running(self) -> bool:
        return (
            not self._closed
            and self._watch_task is not None
            and not self._watch_task.done()
        )

    async def start(self) -> dict[str, Any]:
        if self.running:
            return {"state": "running", "sessionsDir": self._sessions_dir}
        if sys.platform != "darwin":
            return {
                "state": "unsupported",
                "detail": "Codex Desktop rollout ingress requires macOS FSEvents",
                "sessionsDir": self._sessions_dir,
            }
        if not os.path.isdir(self._sessions_dir):
            return {
                "state": "unavailable",
                "detail": "Codex sessions directory does not exist",
                "sessionsDir": self._sessions_dir,
            }

        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._closed = False
        try:
            self._seed_existing_rollouts()
            self._watch_task = self._loop.create_task(
                self._watch_changes(),
                name="codex-desktop-rollout-fsevents",
            )
            await asyncio.sleep(0)
            if self._watch_task.done():
                self._watch_task.result()
        except Exception:
            await self.close()
            raise

        logger.info(
            "[codex-external-ingress] 已通过 FSEvents 监听 Desktop rollout tracked=%s root=%s",
            len(self._cursors),
            self._sessions_dir,
        )
        return {"state": "running", "sessionsDir": self._sessions_dir}

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()

        current = asyncio.current_task()
        tasks = (self._watch_task, self._drain_task)
        self._watch_task = None
        self._drain_task = None
        pending_tasks = [
            task
            for task in tasks
            if task is not None and task is not current and not task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        self._loop = None
        self._stop_event = None
        self._pending_files.clear()
        self._cursors.clear()
        self._rollouts.clear()

    def _seed_existing_rollouts(self) -> None:
        for root, dirnames, filenames in os.walk(self._sessions_dir, followlinks=False):
            dirnames[:] = [
                name
                for name in dirnames
                if not os.path.islink(os.path.join(root, name))
            ]
            for filename in filenames:
                if not _is_rollout_path(filename):
                    continue
                path = os.path.abspath(os.path.join(root, filename))
                self._seed_rollout_state(path)

    def _seed_rollout_state(self, path: str) -> None:
        try:
            size = os.path.getsize(path)
            with open(path, "rb") as source:
                head = source.read(min(size, 256 * 1024))
                tail_start = max(0, size - 256 * 1024)
                if tail_start:
                    source.seek(tail_start)
                    tail = source.read()
                else:
                    tail = b""
        except OSError:
            return

        state = self._rollouts.setdefault(
            path,
            _RolloutState(session_id=_thread_id_from_rollout_path(path)),
        )
        for raw in (head + (b"\n" + tail if tail else b"")).splitlines():
            self._update_rollout_state(state, raw, historical=True)
        partial = b""
        if size and not (tail or head).endswith(b"\n"):
            candidate = (tail or head).rsplit(b"\n", 1)[-1]
            try:
                json.loads(candidate.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                partial = candidate
        self._cursors[path] = _RolloutCursor(
            path=path,
            offset=size,
            partial=partial,
        )

    async def _watch_changes(self) -> None:
        stop_event = self._stop_event
        if stop_event is None:
            return
        try:
            async for changes in awatch(
                self._sessions_dir,
                watch_filter=_rollout_watch_filter,
                debounce=50,
                step=10,
                stop_event=stop_event,
                force_polling=False,
                recursive=True,
                ignore_permission_denied=True,
            ):
                if self._closed:
                    break
                for change, raw_path in changes:
                    path = os.path.abspath(raw_path)
                    if change == Change.deleted:
                        self._pending_files.discard(path)
                        self._cursors.pop(path, None)
                        self._rollouts.pop(path, None)
                    else:
                        self._pending_files.add(path)
                self._ensure_drain_task()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[codex-external-ingress] FSEvents 监听失败", exc_info=True)

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
                for path in pending:
                    await self._read_appended_lines(path)
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
                and self._pending_files
            ):
                self._loop.call_soon(self._ensure_drain_task)

    async def _read_appended_lines(self, path: str) -> None:
        cursor = self._cursors.setdefault(path, _RolloutCursor(path=path))
        try:
            size = os.path.getsize(path)
        except OSError:
            self._cursors.pop(path, None)
            self._rollouts.pop(path, None)
            return
        if size < cursor.offset:
            cursor.offset = 0
            cursor.partial = b""
        if size <= cursor.offset:
            return

        chunks: list[bytes] = []
        try:
            with open(path, "rb") as source:
                source.seek(cursor.offset)
                while cursor.offset < size:
                    chunk = source.read(min(256 * 1024, size - cursor.offset))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    cursor.offset += len(chunk)
        except OSError:
            return
        if not chunks:
            return

        data = cursor.partial + b"".join(chunks)
        lines = data.split(b"\n")
        cursor.partial = lines.pop() if lines else data
        for raw in lines:
            if raw.strip():
                await self._process_rollout_line(path, raw)

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
            state.source = payload.get("source")
            state.thread_source = str(payload.get("thread_source") or "").strip()
            source = state.source if isinstance(state.source, dict) else {}
            subagent = source.get("subagent") if isinstance(source, dict) else None
            thread_spawn = (
                subagent.get("thread_spawn") if isinstance(subagent, dict) else None
            )
            state.parent_thread_id = str(
                thread_spawn.get("parent_thread_id")
                if isinstance(thread_spawn, dict)
                else ""
            ).strip()
            state.user_visible = is_codex_user_visible_session(
                state.source,
                thread_source=state.thread_source,
            )
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
        if not state.user_visible:
            return
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
