import asyncio
import json
import logging
import os
import time
from typing import Optional

from core.messages.events import create_message_event
from core.provider_runtime_state import ProviderWatchState
from core.state import AppState
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import WorkspaceInfo
from plugins.providers.builtin.codex.python.storage_runtime import find_session_file, read_thread_history

logger = logging.getLogger(__name__)

ACTIVE_POLL_INTERVAL_SECONDS = 0.5
WARM_POLL_INTERVAL_SECONDS = 1.5
IDLE_POLL_INTERVAL_SECONDS = 5.0
FINAL_GRACE_TTL_SECONDS = 30.0
DEFAULT_WATCH_TTL_SECONDS = 900.0
WATCH_STATE_TOUCH_INTERVAL_SECONDS = 1.0
ACTIVE_BOOTSTRAP_TAIL_BYTES = 128 * 1024
COMMENTARY_IDLE_COMPLETION_POLLS = 6


def _workspace_key(state: AppState, ws: WorkspaceInfo) -> str:
    return state.get_workspace_storage_key(ws) or ws.daemon_workspace_id or f"{ws.tool}:{ws.name}"


def _workspace_topic_id(state: AppState, ws: WorkspaceInfo) -> int | None:
    return state.get_workspace_topic_id(_workspace_key(state, ws), ws)


def _thread_topic_id(state: AppState, ws: WorkspaceInfo, thread) -> int | None:
    return state.get_thread_topic_id(_workspace_key(state, ws), ws, thread)


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
    topic_id = _thread_topic_id(state, ws, thread) or _workspace_topic_id(state, ws)

    runtime = codex_state.get_runtime(state)
    now = time.monotonic()
    watch = runtime.watched_threads.get(thread_id)
    if watch is None:
        runtime.watched_threads[thread_id] = ProviderWatchState(
            workspace_id=ws.daemon_workspace_id or "",
            topic_id=topic_id,
            active_until=now + ttl_seconds,
            poll_interval_seconds=ACTIVE_POLL_INTERVAL_SECONDS,
            next_poll_at=now,
            last_activity_at=now,
        )
        return

    watch.workspace_id = ws.daemon_workspace_id or watch.workspace_id
    watch.topic_id = _thread_topic_id(state, ws, thread) or watch.topic_id
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
    # App/shared live modes already have an authoritative app-server event
    # chain. Auto-watching every bound thread from session files there creates a
    # second visible-message source. Keep file auto-watch only for local-owner
    # TUI mode, where session-file mirror is the main source.
    cfg = state.config
    if cfg is None:
        return False
    tool_cfg = cfg.get_tool("codex")
    if not tool_cfg or tool_cfg.name != "codex":
        return False
    return str(getattr(tool_cfg, "control_mode", "") or "").strip().lower() == "tui"


def _uses_shared_live_transport(state: AppState) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_cfg = cfg.get_tool("codex")
    if not tool_cfg or tool_cfg.name != "codex":
        return False
    live_transport = str(getattr(tool_cfg, "live_transport", "") or "").strip().lower()
    return live_transport in {"shared_ws", "shared_unix"}


def _should_watch_thread_from_session_file(state: AppState, thread) -> bool:
    if _should_auto_watch_bound_codex_threads(state):
        return True
    if not _uses_shared_live_transport(state):
        return False
    return str(getattr(thread, "source", "") or "").strip().lower() == "imported"


def _synced_final_text_signature(state: AppState, thread_id: str) -> str:
    synced = str(codex_state.get_runtime(state).last_synced_assistant.get(thread_id) or "")
    if synced.startswith("__text__\n"):
        return synced.split("\n", 1)[1]
    if "\n" in synced:
        return synced.split("\n", 1)[1]
    return ""


def _latest_assistant_response_item_snapshot(path: str) -> dict | None:
    """Return the latest assistant text item near EOF with byte offsets."""
    try:
        file_size = os.path.getsize(path)
    except OSError:
        return None
    if file_size <= 0:
        return None

    start = max(0, file_size - ACTIVE_BOOTSTRAP_TAIL_BYTES)
    try:
        with open(path, "rb") as f:
            f.seek(start)
            if start > 0:
                partial = f.readline()
                start += len(partial)
            data = f.read()
    except OSError:
        return None

    offset = start
    latest: dict | None = None
    for raw_line in data.splitlines(keepends=True):
        line_offset = offset
        offset += len(raw_line)
        try:
            line = raw_line.decode("utf-8", errors="ignore")
        except Exception:
            continue
        item = _parse_response_item(line)
        if item is None:
            continue
        if item["role"] == "assistant" and item["text"]:
            latest = dict(item)
            latest["offset"] = line_offset
            latest["end_offset"] = offset
            latest["file_size"] = file_size
    return latest


def _remember_bootstrap_final(
    state: AppState,
    thread_id: str,
    watch: ProviderWatchState,
    item: dict,
) -> None:
    text = str(item.get("text") or "").strip()
    if not text:
        return
    timestamp = str(item.get("timestamp") or "").strip()
    watch.last_final_text = text
    signature = f"{timestamp}\n{text}" if timestamp else f"__text__\n{text}"
    codex_state.get_runtime(state).last_synced_assistant[thread_id] = signature


def _publish_startup_activity_bootstrap(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    thread,
    *,
    sessions_dir: Optional[str] = None,
) -> bool:
    bus = getattr(state, "message_bus", None)
    publish = getattr(bus, "publish", None)
    if not callable(publish):
        return False

    history = read_thread_history(thread_id, sessions_dir=sessions_dir, limit=20)
    latest_user = next(
        (
            str(item.get("text") or "").strip()
            for item in reversed(history)
            if item.get("role") == "user" and str(item.get("text") or "").strip()
        ),
        "",
    )
    latest_assistant = next(
        (
            item
            for item in reversed(history)
            if item.get("role") == "assistant" and str(item.get("text") or "").strip()
        ),
        None,
    )
    title = latest_user or str(getattr(thread, "preview", "") or "").strip()
    workspace_id = _workspace_key(state, ws)
    workspace_path = str(getattr(ws, "path", "") or "")

    published = False
    if latest_user:
        published = bool(
            publish(
                create_message_event(
                    "message.user.submitted",
                    provider_id="codex",
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    session_id=thread_id,
                    source="startup_bootstrap",
                    payload={"text": latest_user, "title": title or latest_user},
                    dedupe_key=f"codex:startup-bootstrap:user:{workspace_id}:{thread_id}",
                )
            )
        ) or published
    elif title:
        published = bool(
            publish(
                create_message_event(
                    "session.created",
                    provider_id="codex",
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    session_id=thread_id,
                    source="startup_bootstrap",
                    payload={"title": title, "preview": title},
                    dedupe_key=f"codex:startup-bootstrap:session:{workspace_id}:{thread_id}",
                )
            )
        ) or published

    if latest_assistant is None:
        return published

    assistant_text = str(latest_assistant.get("text") or "").strip()
    if not assistant_text:
        return published

    phase = str(latest_assistant.get("phase") or "").strip()
    if phase == "commentary":
        published = bool(
            publish(
                create_message_event(
                    "message.assistant.delta",
                    provider_id="codex",
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    session_id=thread_id,
                    turn_id=str(latest_assistant.get("turn_id") or ""),
                    source="startup_bootstrap",
                    payload={"delta": assistant_text, "title": title},
                    dedupe_key=f"codex:startup-bootstrap:commentary:{workspace_id}:{thread_id}",
                )
            )
        ) or published
    else:
        published = bool(
            publish(
                create_message_event(
                    "message.assistant.final",
                    provider_id="codex",
                    workspace_id=workspace_id,
                    workspace_path=workspace_path,
                    session_id=thread_id,
                    turn_id=str(latest_assistant.get("turn_id") or ""),
                    source="startup_bootstrap",
                    payload={"text": assistant_text, "status": "completed", "title": title},
                    dedupe_key=f"codex:startup-bootstrap:final:{workspace_id}:{thread_id}",
                )
            )
        ) or published
    return published


def _ensure_bound_codex_thread_watches(
    state: AppState,
    *,
    sessions_dir: Optional[str] = None,
) -> bool:
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
            if not _should_watch_thread_from_session_file(state, thread):
                continue
            topic_id = _thread_topic_id(state, ws, thread)
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
                        is_active_thread = bool(getattr(thread, "is_active", False))
                        if is_active_thread:
                            bootstrap_item = _latest_assistant_response_item_snapshot(session_file)
                            if bootstrap_item is not None and bootstrap_item.get("phase") == "commentary":
                                watch.last_offset = int(
                                    bootstrap_item.get("end_offset")
                                    or bootstrap_item.get("file_size")
                                    or os.path.getsize(session_file)
                                )
                                watch.last_commentary_text = str(bootstrap_item.get("text") or "")
                            else:
                                watch.last_offset = os.path.getsize(session_file)
                                if bootstrap_item is not None:
                                    _remember_bootstrap_final(state, thread_id, watch, bootstrap_item)
                        else:
                            watch.last_offset = os.path.getsize(session_file)
                    except OSError:
                        pass
                synced_text = _synced_final_text_signature(state, thread_id)
                if synced_text:
                    watch.last_final_text = synced_text
                if _publish_startup_activity_bootstrap(
                    state,
                    ws,
                    thread_id,
                    thread,
                    sessions_dir=sessions_dir,
                ):
                    logger.info(
                        "[tui-mirror] 已恢复 shared-live Codex thread activity thread=%s source=%s",
                        thread_id[:12],
                        str(getattr(thread, "source", "") or "unknown"),
                    )
                changed = True
                if not getattr(thread, "is_active", False):
                    continue
                watch.next_poll_at = 0.0

            watch.workspace_id = ws.daemon_workspace_id or watch.workspace_id
            watch.topic_id = topic_id or _workspace_topic_id(state, ws) or watch.topic_id
            watch.active_until = now + DEFAULT_WATCH_TTL_SECONDS

    return changed


def bootstrap_bound_codex_thread_activity(
    state: AppState,
    *,
    sessions_dir: Optional[str] = None,
) -> bool:
    """恢复已绑定 Codex thread 的 watch/activity 启动快照。"""
    changed = _ensure_bound_codex_thread_watches(state, sessions_dir=sessions_dir)
    if changed:
        touch_codex_tui_watch_state(state)
    return changed


def touch_codex_tui_watch_state(state: AppState) -> None:
    codex_state.get_runtime(state).last_watch_state_touch = time.monotonic()


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


async def _mark_watch_idle_or_complete(handler, watch: ProviderWatchState, thread_id: str, now: float) -> None:
    _mark_watch_idle(watch, now)
    if not watch.turn_started_sent or watch.idle_polls < COMMENTARY_IDLE_COMPLETION_POLLS:
        return
    await _emit_turn_completed(handler, watch.workspace_id, thread_id, "")
    watch.turn_started_sent = False
    watch.active_until = now + FINAL_GRACE_TTL_SECONDS
    logger.info("[tui-mirror] commentary idle completed thread=%s", thread_id)


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

    if touched or (now - runtime.last_watch_state_touch >= WATCH_STATE_TOUCH_INTERVAL_SECONDS):
        touch_codex_tui_watch_state(state)


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
            await _mark_watch_idle_or_complete(handler, watch, thread_id, now)
            return
        if watch.last_offset == 0:
            try:
                watch.last_offset = os.path.getsize(watch.session_file)
            except OSError:
                await _mark_watch_idle_or_complete(handler, watch, thread_id, now)
                return

    try:
        stat = os.stat(watch.session_file)
    except OSError:
        await _mark_watch_idle_or_complete(handler, watch, thread_id, now)
        return

    if stat.st_size < watch.last_offset:
        watch.last_offset = 0

    if stat.st_size <= watch.last_offset:
        await _mark_watch_idle_or_complete(handler, watch, thread_id, now)
        return

    try:
        with open(watch.session_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(watch.last_offset)
            new_data = f.read()
            watch.last_offset = f.tell()
    except OSError:
        await _mark_watch_idle_or_complete(handler, watch, thread_id, now)
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
                item["turn_id"],
            )
        elif item["phase"] == "final_answer":
            saw_activity = True
            await _apply_final_update(
                state,
                handler,
                watch,
                thread_id,
                item["text"],
                item["timestamp"],
                item["turn_id"],
            )

    if saw_activity:
        _promote_watch_activity(watch, now)
    else:
        await _mark_watch_idle_or_complete(handler, watch, thread_id, now)


def _parse_response_item(line: str) -> Optional[dict]:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None

    if obj.get("type") != "response_item":
        return None

    payload = obj.get("payload", {})
    turn_id = str(payload.get("turn_id") or payload.get("turnId") or "").strip()
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
        "turn_id": turn_id,
    }


async def _apply_commentary_update(
    handler,
    watch: ProviderWatchState,
    thread_id: str,
    new_text: str,
    turn_id: str,
) -> None:
    if not watch.turn_started_sent:
        await _emit_turn_started(handler, watch.workspace_id, thread_id, turn_id)
        watch.turn_started_sent = True

    old_text = watch.last_commentary_text
    if new_text.startswith(old_text):
        delta = new_text[len(old_text):]
        if delta:
            await _emit_delta(handler, watch.workspace_id, thread_id, delta, turn_id)
    else:
        await _emit_item_completed_commentary(
            handler,
            watch.workspace_id,
            thread_id,
            new_text,
            turn_id,
        )
    watch.last_commentary_text = new_text


async def _apply_final_update(
    state: AppState,
    handler,
    watch: ProviderWatchState,
    thread_id: str,
    new_text: str,
    timestamp: str,
    turn_id: str,
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
        await _emit_turn_started(handler, watch.workspace_id, thread_id, turn_id)
        watch.turn_started_sent = True

    if normalized != watch.last_final_text:
        await _emit_item_completed_final(handler, watch.workspace_id, thread_id, new_text, turn_id)
        await _emit_turn_completed(handler, watch.workspace_id, thread_id, turn_id)
        if timestamp and normalized:
            runtime.last_synced_assistant[thread_id] = f"{timestamp}\n{normalized}"
        watch.last_final_text = normalized
        watch.turn_started_sent = False
        watch.active_until = time.monotonic() + FINAL_GRACE_TTL_SECONDS


async def _emit_turn_started(handler, workspace_id: str, thread_id: str, turn_id: str) -> None:
    turn_payload = {"source": "tui-mirror"}
    if turn_id:
        turn_payload["id"] = turn_id
        turn_payload["threadId"] = thread_id
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "turn/started",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "turn": turn_payload,
                },
            },
        },
    )


async def _emit_delta(handler, workspace_id: str, thread_id: str, delta: str, turn_id: str) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "delta": delta,
                },
            },
        },
    )


async def _emit_item_completed_commentary(
    handler,
    workspace_id: str,
    thread_id: str,
    text: str,
    turn_id: str,
) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "type": "agentMessage",
                        "threadId": thread_id,
                        "turn": {"id": turn_id, "threadId": thread_id} if turn_id else {},
                        "phase": "commentary",
                        "text": text,
                    },
                },
            },
        },
    )


async def _emit_item_completed_final(
    handler,
    workspace_id: str,
    thread_id: str,
    text: str,
    turn_id: str,
) -> None:
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {
                        "type": "agentMessage",
                        "threadId": thread_id,
                        "turn": {"id": turn_id, "threadId": thread_id} if turn_id else {},
                        "phase": "final_answer",
                        "text": text,
                    },
                },
            },
        },
    )


async def _emit_turn_completed(handler, workspace_id: str, thread_id: str, turn_id: str) -> None:
    turn_payload = {"status": "completed", "source": "tui-mirror"}
    if turn_id:
        turn_payload["id"] = turn_id
        turn_payload["threadId"] = thread_id
    await handler(
        "app-server-event",
        {
            "workspace_id": workspace_id,
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "turn": turn_payload,
                },
            },
        },
    )
