import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Optional

from config import get_data_dir
from core.provider_runtime_state import ProviderWatchState
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import WorkspaceInfo
from plugins.providers.builtin.codex.python.storage_runtime import find_session_file

logger = logging.getLogger(__name__)

DIAGNOSTICS_FILENAME = "codex_tui_mirror_status.json"
ACTIVE_POLL_INTERVAL_SECONDS = 0.5
WARM_POLL_INTERVAL_SECONDS = 1.5
IDLE_POLL_INTERVAL_SECONDS = 5.0
FINAL_GRACE_TTL_SECONDS = 30.0
DEFAULT_WATCH_TTL_SECONDS = 900.0
DIAGNOSTICS_WRITE_INTERVAL_SECONDS = 1.0


def watch_codex_thread(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    *,
    ttl_seconds: float = DEFAULT_WATCH_TTL_SECONDS,
) -> None:
    """将 thread 放入高频观察集合，后续只对这些活跃 thread 做增量 tail。"""
    if state.storage is None:
        return

    thread = ws.threads.get(thread_id)
    if thread is None:
        return

    runtime = codex_state.get_runtime(state)
    now = time.monotonic()
    watch = runtime.watched_threads.get(thread_id)
    if watch is None:
        runtime.watched_threads[thread_id] = ProviderWatchState(
            workspace_id=ws.daemon_workspace_id or "",
            topic_id=thread.topic_id or ws.topic_id or 0,
            active_until=now + ttl_seconds,
            poll_interval_seconds=ACTIVE_POLL_INTERVAL_SECONDS,
            next_poll_at=now,
            last_activity_at=now,
        )
        return

    watch.workspace_id = ws.daemon_workspace_id or watch.workspace_id
    watch.topic_id = thread.topic_id or watch.topic_id
    watch.active_until = now + ttl_seconds
    watch.poll_interval_seconds = ACTIVE_POLL_INTERVAL_SECONDS
    watch.next_poll_at = now
    watch.idle_polls = 0


def seed_codex_watch_baseline(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    *,
    sessions_dir: Optional[str] = None,
    ttl_seconds: float = DEFAULT_WATCH_TTL_SECONDS,
) -> None:
    """
    在发送 TG 注入消息前建立 watch 基线，避免把旧 commentary 重放为新一轮 turn。
    仅记录当前文件大小，不解析历史内容。
    """
    watch_codex_thread(state, ws, thread_id, ttl_seconds=ttl_seconds)
    watch = codex_state.get_runtime(state).watched_threads.get(thread_id)
    if watch is None:
        return

    session_file = find_session_file(thread_id, sessions_dir)
    if session_file is None:
        return

    watch.session_file = session_file
    try:
        watch.last_offset = os.path.getsize(session_file)
    except OSError:
        return


def _should_auto_watch_bound_codex_threads(state: AppState) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_cfg = cfg.get_tool("codex")
    if not tool_cfg or tool_cfg.name != "codex":
        return False
    if str(getattr(tool_cfg, "control_mode", "") or "app").strip().lower() != "app":
        return False
    live_transport = str(getattr(tool_cfg, "live_transport", "") or "").strip().lower()
    return live_transport != "shared_ws"


def _synced_final_text_signature(state: AppState, thread_id: str) -> str:
    synced = str(codex_state.get_runtime(state).last_synced_assistant.get(thread_id) or "")
    if synced.startswith("__text__\n"):
        return synced.split("\n", 1)[1]
    if "\n" in synced:
        return synced.split("\n", 1)[1]
    return ""


def _ensure_bound_codex_thread_watches(
    state: AppState,
    *,
    sessions_dir: Optional[str] = None,
) -> bool:
    if not _should_auto_watch_bound_codex_threads(state):
        return False
    if state.storage is None:
        return False

    changed = False
    now = time.monotonic()

    for ws in state.storage.workspaces.values():
        if getattr(ws, "tool", "") != "codex":
            continue
        if getattr(ws, "archived", False):
            continue

        for thread_id, thread in (getattr(ws, "threads", {}) or {}).items():
            if getattr(thread, "archived", False):
                continue
            topic_id = getattr(thread, "topic_id", None)
            if topic_id is None:
                continue

            runtime = codex_state.get_runtime(state)
            watch = runtime.watched_threads.get(thread_id)
            if watch is None:
                watch_codex_thread(state, ws, thread_id)
                watch = runtime.watched_threads.get(thread_id)
                if watch is None:
                    continue
                session_file = find_session_file(thread_id, sessions_dir)
                if session_file is not None:
                    watch.session_file = session_file
                    try:
                        watch.last_offset = os.path.getsize(session_file)
                    except OSError:
                        pass
                synced_text = _synced_final_text_signature(state, thread_id)
                if synced_text:
                    watch.last_final_text = synced_text
                changed = True
                continue

            watch.workspace_id = ws.daemon_workspace_id or watch.workspace_id
            watch.topic_id = topic_id or ws.topic_id or watch.topic_id
            watch.active_until = now + DEFAULT_WATCH_TTL_SECONDS

    return changed


def diagnostics_snapshot_path() -> Optional[str]:
    data_dir = get_data_dir()
    if not data_dir:
        return None
    return os.path.join(data_dir, DIAGNOSTICS_FILENAME)


def clear_codex_tui_diagnostics_snapshot() -> None:
    path = diagnostics_snapshot_path()
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as e:
        logger.debug(f"[tui-mirror] 删除 diagnostics 快照失败：{e}")


def write_codex_tui_diagnostics_snapshot(state: AppState) -> None:
    path = diagnostics_snapshot_path()
    if not path:
        return

    now_monotonic = time.monotonic()
    now_epoch = time.time()
    payload = {
        "tool": "codex",
        "mode": "tui",
        "generated_at_epoch": now_epoch,
        "mirror_task_running": bool(
            codex_state.get_runtime(state).mirror_task is not None
            and not codex_state.get_runtime(state).mirror_task.done()
        ),
        "streaming_turn_count": len(state.streaming_turns),
        "watched_thread_count": len(codex_state.get_runtime(state).watched_threads),
        "watched_threads": [],
    }

    runtime = codex_state.get_runtime(state)
    for thread_id, watch in sorted(runtime.watched_threads.items()):
        payload["watched_threads"].append(
            {
                "thread_id": thread_id,
                "workspace_id": watch.workspace_id,
                "topic_id": watch.topic_id,
                "session_file": watch.session_file,
                "last_offset": watch.last_offset,
                "turn_started_sent": watch.turn_started_sent,
                "poll_interval_seconds": watch.poll_interval_seconds,
                "seconds_until_next_poll": max(0.0, watch.next_poll_at - now_monotonic),
                "seconds_until_expire": max(0.0, watch.active_until - now_monotonic),
                "seconds_since_activity": (
                    max(0.0, now_monotonic - watch.last_activity_at)
                    if watch.last_activity_at > 0
                    else None
                ),
                "idle_polls": watch.idle_polls,
                "has_commentary": bool(watch.last_commentary_text),
                "has_final": bool(watch.last_final_text),
            }
        )

    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix="codex-tui-mirror-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        runtime.last_diagnostics_write = now_monotonic
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def _set_watch_poll_interval(watch: ProviderWatchState, interval_seconds: float, now: float) -> None:
    watch.poll_interval_seconds = interval_seconds
    watch.next_poll_at = now + interval_seconds


def _promote_watch_activity(watch: ProviderWatchState, now: float) -> None:
    watch.last_activity_at = now
    watch.idle_polls = 0
    _set_watch_poll_interval(watch, ACTIVE_POLL_INTERVAL_SECONDS, now)


def _mark_watch_idle(watch: ProviderWatchState, now: float) -> None:
    watch.idle_polls += 1
    if watch.idle_polls >= 6:
        interval = IDLE_POLL_INTERVAL_SECONDS
    elif watch.idle_polls >= 2:
        interval = WARM_POLL_INTERVAL_SECONDS
    else:
        interval = ACTIVE_POLL_INTERVAL_SECONDS
    _set_watch_poll_interval(watch, interval, now)


def start_codex_tui_realtime_mirror_loop(
    state: AppState,
    bot,
    group_chat_id: int,
    *,
    poll_interval: float = ACTIVE_POLL_INTERVAL_SECONDS,
    sessions_dir: Optional[str] = None,
) -> asyncio.Task:
    """启动 codex TUI 过程级实时镜像循环。"""

    async def _worker() -> None:
        from bot.events import make_event_handler

        handler = make_event_handler(state, bot, group_chat_id)
        while True:
            try:
                await sync_codex_tui_realtime_once(
                    state,
                    handler,
                    sessions_dir=sessions_dir,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[tui-mirror] codex 实时镜像循环异常：{e}")

            idle_sleep = max(0.1, min(_next_global_sleep_seconds(state), IDLE_POLL_INTERVAL_SECONDS))
            await asyncio.sleep(idle_sleep)

    return asyncio.create_task(_worker(), name="codex-tui-realtime-mirror")


def _next_global_sleep_seconds(state: AppState) -> float:
    runtime = codex_state.get_runtime(state)
    if not runtime.watched_threads:
        return IDLE_POLL_INTERVAL_SECONDS
    now = time.monotonic()
    waits = [
        max(0.0, watch.next_poll_at - now)
        for watch in runtime.watched_threads.values()
    ]
    return min(waits) if waits else IDLE_POLL_INTERVAL_SECONDS


async def sync_codex_tui_realtime_once(
    state: AppState,
    handler,
    *,
    sessions_dir: Optional[str] = None,
) -> None:
    """单轮同步：只遍历活跃 watch 集合，而不是全量 thread。"""
    now = time.monotonic()
    touched = _ensure_bound_codex_thread_watches(state, sessions_dir=sessions_dir)
    runtime = codex_state.get_runtime(state)
    watched = list(runtime.watched_threads.items())

    for thread_id, watch in watched:
        if now > watch.active_until and thread_id not in state.streaming_turns:
            runtime.watched_threads.pop(thread_id, None)
            touched = True
            continue
        if watch.next_poll_at > now:
            continue
        await sync_watched_thread_once(
            state,
            handler,
            thread_id,
            watch,
            sessions_dir=sessions_dir,
        )

    if touched or (now - runtime.last_diagnostics_write >= DIAGNOSTICS_WRITE_INTERVAL_SECONDS):
        write_codex_tui_diagnostics_snapshot(state)


async def sync_watched_thread_once(
    state: AppState,
    handler,
    thread_id: str,
    watch: ProviderWatchState,
    *,
    sessions_dir: Optional[str] = None,
) -> None:
    """对单个被 watch 的 thread 做 session 增量读取。"""
    now = time.monotonic()
    watch.last_poll_at = now

    if watch.session_file is None:
        watch.session_file = find_session_file(thread_id, sessions_dir)
        if watch.session_file is None:
            _mark_watch_idle(watch, now)
            return
        if watch.last_offset == 0:
            try:
                watch.last_offset = os.path.getsize(watch.session_file)
            except OSError:
                _mark_watch_idle(watch, now)
                return

    try:
        stat = os.stat(watch.session_file)
    except OSError:
        _mark_watch_idle(watch, now)
        return

    if stat.st_size < watch.last_offset:
        watch.last_offset = 0

    if stat.st_size <= watch.last_offset:
        _mark_watch_idle(watch, now)
        return

    try:
        with open(watch.session_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(watch.last_offset)
            new_data = f.read()
            watch.last_offset = f.tell()
    except OSError:
        _mark_watch_idle(watch, now)
        return

    saw_activity = False
    for raw_line in new_data.splitlines():
        item = _parse_response_item(raw_line)
        if item is None:
            continue
        if item["role"] != "assistant" or not item["text"]:
            continue

        if item["phase"] == "commentary":
            saw_activity = True
            if thread_id in state.streaming_turns and not watch.turn_started_sent:
                watch.last_commentary_text = item["text"]
                continue
            await _apply_commentary_update(
                handler,
                watch,
                thread_id,
                item["text"],
            )
        elif item["phase"] == "final_answer":
            saw_activity = True
            if thread_id in state.streaming_turns and not watch.turn_started_sent:
                watch.last_final_text = item["text"]
                continue
            await _apply_final_update(
                state,
                handler,
                watch,
                thread_id,
                item["text"],
                item["timestamp"],
            )

    if saw_activity:
        _promote_watch_activity(watch, now)
    else:
        _mark_watch_idle(watch, now)


def _parse_response_item(line: str) -> Optional[dict]:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    if obj.get("type") != "response_item":
        return None

    payload = obj.get("payload", {})
    text = ""
    content_items = payload.get("content")
    if not isinstance(content_items, list):
        content_items = []
    for content in content_items:
        if content.get("type") in ("output_text", "text"):
            text = content.get("text", "")
            if text:
                break

    return {
        "role": payload.get("role"),
        "phase": payload.get("phase", ""),
        "text": text,
        "timestamp": obj.get("timestamp", ""),
    }


async def _apply_commentary_update(handler, watch: ProviderWatchState, thread_id: str, new_text: str) -> None:
    if not watch.turn_started_sent:
        await _emit_turn_started(handler, watch.workspace_id, thread_id)
        watch.turn_started_sent = True

    old_text = watch.last_commentary_text
    if new_text.startswith(old_text):
        delta = new_text[len(old_text):]
        if delta:
            await _emit_delta(handler, watch.workspace_id, thread_id, delta)
    else:
        await _emit_item_completed_commentary(handler, watch.workspace_id, thread_id, new_text)
    watch.last_commentary_text = new_text


async def _apply_final_update(
    state: AppState,
    handler,
    watch: ProviderWatchState,
    thread_id: str,
    new_text: str,
    timestamp: str,
) -> None:
    normalized = (new_text or "").strip()
    runtime = codex_state.get_runtime(state)
    synced = str(runtime.last_synced_assistant.get(thread_id) or "")
    if normalized and synced in {f"{timestamp}\n{normalized}", f"__text__\n{normalized}"}:
        if timestamp:
            runtime.last_synced_assistant[thread_id] = f"{timestamp}\n{normalized}"
        watch.last_final_text = normalized
        watch.turn_started_sent = False
        watch.active_until = time.monotonic() + FINAL_GRACE_TTL_SECONDS
        return

    if not watch.turn_started_sent:
        await _emit_turn_started(handler, watch.workspace_id, thread_id)
        watch.turn_started_sent = True

    if normalized != watch.last_final_text:
        await _emit_item_completed_final(handler, watch.workspace_id, thread_id, new_text)
        await _emit_turn_completed(handler, watch.workspace_id, thread_id)
        if timestamp and normalized:
            runtime.last_synced_assistant[thread_id] = f"{timestamp}\n{normalized}"
        watch.last_final_text = normalized
        watch.turn_started_sent = False
        watch.active_until = time.monotonic() + FINAL_GRACE_TTL_SECONDS


async def _emit_turn_started(handler, workspace_id: str, thread_id: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "turn/started",
                "params": {
                    "threadId": thread_id,
                    "turn": {"source": "tui-mirror"},
                },
            },
        },
    )


async def _emit_delta(handler, workspace_id: str, thread_id: str, delta: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "delta": delta,
                },
            },
        },
    )


async def _emit_item_completed_commentary(handler, workspace_id: str, thread_id: str, text: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "item": {
                        "type": "agentMessage",
                        "threadId": thread_id,
                        "phase": "commentary",
                        "text": text,
                    },
                },
            },
        },
    )


async def _emit_item_completed_final(handler, workspace_id: str, thread_id: str, text: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "item": {
                        "type": "agentMessage",
                        "threadId": thread_id,
                        "phase": "final_answer",
                        "text": text,
                    },
                },
            },
        },
    )


async def _emit_turn_completed(handler, workspace_id: str, thread_id: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {"status": "completed", "source": "tui-mirror"},
                },
            },
        },
    )
