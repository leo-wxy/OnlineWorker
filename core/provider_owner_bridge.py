from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import time
import uuid
from types import SimpleNamespace
from typing import Optional

from config import get_data_dir
from core.messages.events import create_message_event
from core.provider_session_new import (
    build_provider_session_summary,
    _checkpoint_new_session,
    publish_new_session_recovery,
    send_started_provider_thread_message,
    start_real_provider_thread,
    validate_provider_thread_target,
    validate_new_provider_thread_request,
)
from core.provider_session_archive import commit_session_archive
from core.providers.registry import get_provider
from core.storage import ThreadInfo, WorkspaceInfo, save_storage
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text
from core.user_messages.recovery import checkpoint_send_recovery, new_session_recovery_view, publish_send_recovery, restore_send_recoveries
from core.messages.publishing import (
    publish_approval_answered,
    publish_user_message_accepted,
    publish_user_message_event,
    publish_user_message_failed,
    publish_user_message_submitted,
    report_user_message_failure,
)


OWNER_BRIDGE_SOCKET_FILENAME = "provider_owner_bridge.sock"
OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS = 5.0
OWNER_BRIDGE_USAGE_TIMEOUT_SECONDS = 5.0
OWNER_BRIDGE_SLOW_REQUEST_WARNING_SECONDS = 0.25
OWNER_BRIDGE_PREVIEW_HYDRATION_LIMIT = 6
OWNER_BRIDGE_PREVIEW_MAX_LENGTH = 220
OWNER_BRIDGE_STREAM_QUEUE_SIZE = 256
CONTROLLED_THREAD_SOURCES = {"app", "provider", "telegram_new_thread"}
logger = logging.getLogger(__name__)
ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s(])(/(?:Users|Applications|Volumes|private|tmp|var)/[^\s)]+)")


def _stream_queue(writer):
    queue = asyncio.Queue(maxsize=OWNER_BRIDGE_STREAM_QUEUE_SIZE)
    closed = asyncio.Event()

    def enqueue(payload):
        if closed.is_set():
            return
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.warning("[provider-owner-bridge] stream queue full; disconnecting for snapshot recovery")
            closed.set()
            writer.close()

    return queue, closed, enqueue


async def _run_stream_writer(reader, writer, queue, closed, snapshot):
    if closed.is_set():
        return

    async def send(payload):
        writer.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()

    async def write_loop():
        await send(snapshot)
        while True:
            await send(await queue.get())

    tasks = [asyncio.create_task(write_loop()), asyncio.create_task(reader.read()), asyncio.create_task(closed.wait())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def provider_owner_bridge_socket_path(data_dir: Optional[str] = None) -> Optional[str]:
    resolved = data_dir if data_dir is not None else get_data_dir()
    if not resolved:
        return None
    return os.path.join(resolved, OWNER_BRIDGE_SOCKET_FILENAME)


def _workspace_key(provider_id: str, workspace_dir: str) -> str:
    return f"{provider_id}:{workspace_dir}"


def _resolve_workspace_and_thread(state, provider_id: str, thread_id: str, workspace_dir: str):
    normalized_thread_id = str(thread_id or "").strip()
    normalized_workspace_dir = str(workspace_dir or "").strip()

    if normalized_thread_id:
        workspace, thread = _find_existing_session_binding(state, provider_id, normalized_thread_id)
        if workspace is not None:
            if normalized_workspace_dir and workspace.path != normalized_workspace_dir:
                return None, None
            return workspace, thread

    if not normalized_workspace_dir:
        return None, None

    storage = getattr(state, "storage", None)
    if storage is not None:
        for storage_key, ws in storage.workspaces.items():
            if getattr(ws, "tool", "") != provider_id:
                continue
            if getattr(ws, "path", "") != normalized_workspace_dir:
                continue
            thread = ws.threads.get(normalized_thread_id)
            if thread is None:
                thread = storage.workspaces[storage_key].threads.setdefault(
                    normalized_thread_id,
                    _new_thread_info(
                        normalized_thread_id,
                        source=_new_thread_source(provider_id),
                    ),
                )
            return ws, thread

        workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
        ws = WorkspaceInfo(
            name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
            path=normalized_workspace_dir,
            tool=provider_id,
            topic_id=None,
            daemon_workspace_id=workspace_id,
            threads={},
        )
        thread = _new_thread_info(
            normalized_thread_id,
            source=_new_thread_source(provider_id),
        )
        ws.threads[normalized_thread_id] = thread
        storage.workspaces[workspace_id] = ws
        try:
            save_storage(storage)
        except Exception:
            logger.debug("[provider-owner-bridge] 保存临时 workspace 失败", exc_info=True)
        return ws, thread

    workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
    ws = SimpleNamespace(
        name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
        path=normalized_workspace_dir,
        tool=provider_id,
        topic_id=None,
        daemon_workspace_id=workspace_id,
        threads={},
    )
    thread = _new_thread_info(
        normalized_thread_id,
        source=_new_thread_source(provider_id),
    )
    ws.threads[normalized_thread_id] = thread
    return ws, thread


def _resolve_workspace(state, provider_id: str, workspace_dir: str):
    normalized_workspace_dir = str(workspace_dir or "").strip()
    if not normalized_workspace_dir:
        return None

    storage = getattr(state, "storage", None)
    if storage is not None:
        for ws in storage.workspaces.values():
            if getattr(ws, "tool", "") != provider_id:
                continue
            if getattr(ws, "path", "") == normalized_workspace_dir:
                return ws

        workspace_id = _workspace_key(provider_id, normalized_workspace_dir)
        ws = WorkspaceInfo(
            name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
            path=normalized_workspace_dir,
            tool=provider_id,
            topic_id=None,
            daemon_workspace_id=workspace_id,
            threads={},
        )
        storage.workspaces[workspace_id] = ws
        try:
            save_storage(storage)
        except Exception:
            logger.debug("[provider-owner-bridge] 保存新建 workspace 失败", exc_info=True)
        return ws

    return SimpleNamespace(
        name=os.path.basename(normalized_workspace_dir) or normalized_workspace_dir,
        path=normalized_workspace_dir,
        tool=provider_id,
        topic_id=None,
        daemon_workspace_id=_workspace_key(provider_id, normalized_workspace_dir),
        threads={},
    )


def _build_provider_approval_reply(provider, approval, action: str) -> tuple[str, dict]:
    interactions = getattr(provider, "interactions", None) if provider is not None else None
    build_reply = getattr(interactions, "build_approval_reply", None) if interactions is not None else None
    if callable(build_reply):
        return build_reply(approval, action)

    if action == "exec_deny":
        return "❌ 已拒绝", {"decision": "decline"}
    if action == "exec_allow_always":
        amendment_decision = getattr(approval, "amendment_decision", {}) or {}
        if amendment_decision:
            return "✅ 已总是允许", amendment_decision
        return "✅ 已总是允许", {"decision": "acceptForSession"}
    return "✅ 已允许", {"decision": "accept"}


def _resolve_raw_approval_request_id(
    state,
    provider_id: str,
    request_id: str,
    *,
    thread_id: str = "",
    workspace_id: str = "",
):
    request_id_text = str(request_id or "").strip()
    if not request_id_text:
        return request_id

    pending_approvals = getattr(state, "pending_approvals", {}) or {}
    for approval in pending_approvals.values():
        if str(getattr(approval, "request_id", "")).strip() != request_id_text:
            continue
        approval_provider = str(
            getattr(approval, "tool_type", "") or getattr(approval, "tool_name", "")
        ).strip()
        if approval_provider and approval_provider != provider_id:
            continue
        approval_thread = str(getattr(approval, "thread_id", "") or "").strip()
        if thread_id and approval_thread and approval_thread != thread_id:
            continue
        approval_workspace = str(getattr(approval, "workspace_id", "") or "").strip()
        if workspace_id and approval_workspace and approval_workspace != workspace_id:
            continue
        return getattr(approval, "request_id")

    bus = getattr(state, "message_bus", None)
    recent_events = getattr(bus, "recent_events", None)
    if callable(recent_events):
        for event in reversed(recent_events()):
            if str(event.get("kind") or "") != "approval.requested":
                continue
            if str(event.get("provider_id") or "") != provider_id:
                continue
            if thread_id and str(event.get("session_id") or "") != thread_id:
                continue
            if workspace_id and str(event.get("workspace_id") or "") != workspace_id:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if str(payload.get("requestId") or "").strip() == request_id_text:
                return payload.get("rawRequestId", request_id)

    return request_id


def _new_thread_source(provider_id: str) -> str:
    provider = get_provider(provider_id)
    thread_hooks = getattr(provider, "thread_hooks", None) if provider is not None else None
    resolver = (
        getattr(thread_hooks, "new_imported_thread_source", None)
        if thread_hooks is not None
        else None
    )
    if callable(resolver):
        source = str(resolver() or "").strip()
        if source:
            return source
    return "app"


def _new_thread_info(thread_id: str, *, source: str = "app"):
    return ThreadInfo(thread_id=thread_id, is_active=True, source=source)


def _is_app_state_thread_id(provider_id: str, thread_id: str) -> bool:
    normalized_provider_id = str(provider_id or "").strip()
    normalized_thread_id = str(thread_id or "").strip()
    return bool(normalized_provider_id) and normalized_thread_id.startswith(f"app:{normalized_provider_id}:")


def _state_only_session_rows(state, provider_id: str, facts, seen: set[tuple[str, str]]) -> list[dict]:
    # Session Tab must only show provider-backed sessions. App-created
    # state-only placeholders are draft implementation details, not sessions.
    _ = (state, provider_id, facts, seen)
    return []


async def _run_sync_with_timeout(
    label: str,
    func,
    *args,
    timeout: float,
    **kwargs,
):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} timed out after {int(timeout * 1000)}ms") from exc


def _session_archived_in_storage(state, provider_id: str, session_id: str) -> bool:
    storage = getattr(state, "storage", None)
    if storage is None:
        return False
    matched = False
    for ws in storage.workspaces.values():
        if getattr(ws, "tool", "") != provider_id:
            continue
        thread = ws.threads.get(session_id)
        if thread is None:
            continue
        matched = True
        if not bool(getattr(thread, "archived", False)):
            return False
    return matched


def _find_existing_session_binding(state, provider_id: str, session_id: str):
    storage = getattr(state, "storage", None)
    if storage is not None:
        for workspace in storage.workspaces.values():
            if workspace.tool == provider_id and session_id in workspace.threads:
                return workspace, workspace.threads[session_id]
    find_thread = getattr(state, "find_thread_by_id_global", None)
    found = find_thread(session_id) if callable(find_thread) and session_id else None
    if found is None:
        return None, None
    ws, thread = found
    if str(getattr(ws, "tool", "") or "").strip() != provider_id:
        return None, None
    return ws, thread


async def _ensure_message_adapter(state, provider_id, provider, workspace):
    adapter = state.get_adapter(provider_id)
    ensure_connected = getattr(getattr(provider, "message_hooks", None), "ensure_connected", None)
    if callable(ensure_connected):
        connected = await ensure_connected(state, adapter, workspace, update=None, context=None,
                                           group_chat_id=0, src_topic_id=None)
        if connected is not None:
            adapter = connected
    if adapter is None or not getattr(adapter, "connected", False):
        raise RuntimeError(f"{provider_id} adapter 未连接")
    state.set_adapter(provider_id, adapter)
    return adapter


def _resolve_session_adapter(state, provider_id: str, ws):
    workspace_id = str(getattr(ws, "daemon_workspace_id", "") or "").strip()
    get_for_workspace = getattr(state, "get_adapter_for_workspace", None)
    adapter = get_for_workspace(workspace_id) if callable(get_for_workspace) and workspace_id else None
    if adapter is None:
        get_adapter = getattr(state, "get_adapter", None)
        adapter = get_adapter(provider_id) if callable(get_adapter) else None
    return adapter


def _active_session_turn_id(state, activity: dict, session_id: str) -> str:
    projected_turn_id = str(activity.get("activeTurnId") or "").strip()
    if projected_turn_id:
        return projected_turn_id
    streaming = (getattr(state, "streaming_turns", {}) or {}).get(session_id)
    return str(getattr(streaming, "turn_id", "") or "").strip()


def _session_control_facts(state, activity: dict) -> dict:
    provider_id = str(activity.get("providerId") or "").strip()
    session_id = str(activity.get("sessionId") or "").strip()
    result = {
        "canInterrupt": False,
        "canRecover": False,
        "controlReason": "",
        "controlMode": "external",
    }
    if activity.get("mirroredOnly") is True:
        result["controlReason"] = "此 Session 由外部客户端控制，请在原客户端处理。"
        return result

    ws, thread = _find_existing_session_binding(state, provider_id, session_id)
    if ws is None or thread is None:
        result["controlReason"] = "此 Session 没有 OnlineWorker 托管的控制通道。"
        return result
    source = str(getattr(thread, "source", "") or "unknown").strip().lower()
    if source not in CONTROLLED_THREAD_SOURCES:
        result["controlReason"] = "此 Session 由外部客户端控制，请在原客户端处理。"
        return result
    if bool(getattr(thread, "archived", False)):
        result["controlReason"] = "此 Session 已归档。"
        return result

    provider = get_provider(provider_id, getattr(state, "config", None))
    hooks = getattr(provider, "thread_hooks", None) if provider is not None else None
    adapter = _resolve_session_adapter(state, provider_id, ws)
    connected = adapter is not None and bool(getattr(adapter, "connected", False))
    result["controlMode"] = "owned"

    turn_id = _active_session_turn_id(state, activity, session_id)
    interrupt = getattr(hooks, "interrupt_thread", None) if hooks is not None else None
    interrupt_supported = getattr(hooks, "interrupt_supported", None) if hooks is not None else None
    supported = False
    if callable(interrupt) and callable(interrupt_supported):
        try:
            supported = bool(interrupt_supported(state, ws))
        except Exception:
            logger.debug(
                "[provider-owner-bridge] 读取中断能力失败 provider=%s session=%s",
                provider_id,
                session_id[:12],
                exc_info=True,
            )
    result["canInterrupt"] = bool(supported and connected and turn_id)

    activity_status = str(activity.get("status") or "").strip()
    attention_kind = str(activity.get("attentionKind") or "").strip()
    recoverable_state = activity_status == "failed" or attention_kind in {"failure", "stalled", "recovery"}
    message_hooks = getattr(provider, "message_hooks", None) if provider is not None else None
    ensure_connected = getattr(message_hooks, "ensure_connected", None) if message_hooks is not None else None
    result["canRecover"] = bool(
        recoverable_state
        and (
            callable(getattr(adapter, "resume_thread", None))
            or callable(ensure_connected)
        )
    )

    if result["canInterrupt"] or result["canRecover"]:
        return result
    if not connected:
        result["controlReason"] = f"{provider_id} adapter 未连接。"
    elif activity_status == "running" and not turn_id:
        result["controlReason"] = "当前 Session 没有可中断的活跃任务。"
    elif recoverable_state:
        result["controlReason"] = "当前 Provider 不支持恢复此 Session。"
    return result


def _recent_session_events(bus, provider_id: str, session_id: str, *, limit: int = 5) -> list[dict]:
    recent_events = getattr(bus, "recent_events", None)
    if not callable(recent_events):
        return []
    matches: list[dict] = []
    for event in reversed(recent_events()):
        if str(event.get("provider_id") or "").strip() != provider_id:
            continue
        if str(event.get("session_id") or "").strip() != session_id:
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        summary = ""
        for key in ("text", "message", "reason", "error", "command", "status"):
            summary = " ".join(str(payload.get(key) or "").split()).strip()
            if summary:
                break
        matches.append(
            {
                "kind": str(event.get("kind") or ""),
                "createdAt": float(event.get("created_at") or 0),
                "summary": summary[:220],
            }
        )
        if len(matches) >= limit:
            break
    return matches


def _decorate_session_activity(state, activity: dict, bus=None) -> dict:
    decorated = dict(activity)
    decorated.update(_session_control_facts(state, decorated))
    if bus is not None:
        decorated["recentEvents"] = _recent_session_events(
            bus,
            str(decorated.get("providerId") or "").strip(),
            str(decorated.get("sessionId") or "").strip(),
        )
    return decorated


def _filter_visible_session_activities(state, activities: list[dict], limit: int, *, bus=None) -> list[dict]:
    visible = [
        _decorate_session_activity(state, activity, bus)
        for activity in activities
        if not _session_archived_in_storage(
            state,
            str(activity.get("providerId") or "").strip(),
            str(activity.get("sessionId") or "").strip(),
        )
    ]
    return visible[:limit]


def _runtime_health_from_lines(lines: list[str], adapter) -> str:
    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    lowered_lines = [(line, line.lower()) for line in normalized_lines]
    if any(
        "⚠️" in line
        or "未鉴权" in line
        or "不可用" in line
        or "unavailable" in lowered
        or "not logged in" in lowered
        or "❌" in line
        or "已断开" in line
        or "disconnected" in lowered
        or "degraded" in lowered
        or "failed" in lowered
        for line, lowered in lowered_lines
    ):
        return "degraded"
    for line, lowered in lowered_lines:
        if "未启动" in line or "stopped" in lowered:
            return "stopped"
    for line, lowered in lowered_lines:
        if "✅" in line or "已连接" in line or "connected" in lowered or "healthy" in lowered:
            return "healthy"
    if adapter is not None:
        return "healthy" if bool(getattr(adapter, "connected", False)) else "degraded"
    return "unknown"


def _normalize_provider_turn_content(turn: dict) -> str:
    content = str(turn.get("content") or turn.get("text") or "").strip()
    if content:
        return content
    if str(turn.get("kind") or "").strip() == "error":
        return str(turn.get("error") or "").strip()
    return ""


def _normalize_provider_turn(turn: dict) -> dict:
    role = str(turn.get("role") or "").strip()
    normalized = {
        "role": role,
        "content": _normalize_provider_turn_content(turn),
    }

    kind = str(turn.get("kind") or "").strip()
    display_mode = str(turn.get("displayMode") or turn.get("display_mode") or "").strip()
    if display_mode in {"plain", "markdown"}:
        normalized["displayMode"] = display_mode
    elif kind == "error":
        normalized["displayMode"] = "plain"
    elif role == "assistant":
        normalized["displayMode"] = "plain" if turn.get("phase") == "commentary" else "markdown"
    if kind:
        normalized["kind"] = kind
    for field in ("timestamp", "turnId", "itemId", "phase"):
        if turn.get(field):
            normalized[field] = turn[field]

    return normalized


def _compact_preview_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _sanitize_preview_text(value: str) -> str:
    text = _compact_preview_text(value)
    if not text:
        return ""
    text = ABSOLUTE_PATH_RE.sub(lambda match: match.group(0).replace(match.group(1), "[path]"), text)
    return text[:OWNER_BRIDGE_PREVIEW_MAX_LENGTH].strip()


def _preview_equals_title(preview: str, title: str) -> bool:
    normalized_preview = _compact_preview_text(preview)
    normalized_title = _compact_preview_text(title)
    return bool(normalized_preview and normalized_title and normalized_preview == normalized_title)


def _preview_is_low_signal(preview: str, title: str) -> bool:
    normalized_preview = _compact_preview_text(preview)
    if not normalized_preview:
        return True
    if _preview_equals_title(normalized_preview, title):
        return True
    return False


def _preview_from_turns(turns: list[dict], *, title: str) -> str:
    for turn in reversed(turns or []):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        content = _sanitize_preview_text(_normalize_provider_turn_content(turn))
        if not content:
            continue
        if role == "assistant" and not _preview_equals_title(content, title):
            return content
    for turn in reversed(turns or []):
        if not isinstance(turn, dict):
            continue
        content = _sanitize_preview_text(_normalize_provider_turn_content(turn))
        if not content:
            continue
        if not _preview_equals_title(content, title):
            return content
    return ""


async def _hydrate_low_signal_session_previews(
    provider_id: str,
    facts,
    sessions: list[dict],
) -> None:
    read_thread_history = getattr(facts, "read_thread_history", None)
    if not callable(read_thread_history):
        return

    hydration_candidates = [
        session
        for session in sessions
        if bool(session.get("providerActive"))
        and _preview_is_low_signal(
            str(session.get("preview") or ""),
            str(session.get("title") or ""),
        )
    ][:OWNER_BRIDGE_PREVIEW_HYDRATION_LIMIT]
    if len(hydration_candidates) < OWNER_BRIDGE_PREVIEW_HYDRATION_LIMIT:
        latest_idle = next(
            (
                session
                for session in sessions
                if not bool(session.get("providerActive"))
                and _preview_is_low_signal(
                    str(session.get("preview") or ""),
                    str(session.get("title") or ""),
                )
            ),
            None,
        )
        if latest_idle is not None:
            hydration_candidates.append(latest_idle)

    async def hydrate_preview(session: dict) -> None:
        session_id = str(session.get("id") or "").strip()
        if not session_id:
            return
        turns = await _run_sync_with_timeout(
            f"{provider_id}.read_thread_history({session_id})",
            read_thread_history,
            session_id,
            limit=20,
            timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
        ) or []
        preview = _preview_from_turns(
            turns,
            title=str(session.get("title") or ""),
        )
        if preview:
            session["preview"] = preview

    results = await asyncio.gather(
        *(hydrate_preview(session) for session in hydration_candidates),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            logger.debug(
                "[provider-owner-bridge] list preview hydration skipped provider=%s error=%s",
                provider_id,
                result,
            )


async def _status_lines_for_provider(state, provider_id: str, provider) -> list[str]:
    status_builder = getattr(provider, "status_builder", None)
    if callable(status_builder):
        raw_lines = status_builder(state)
        if inspect.isawaitable(raw_lines):
            raw_lines = await raw_lines
        return [str(line).strip() for line in (raw_lines or []) if str(line).strip()]

    adapter = state.get_adapter(provider_id)
    if adapter is not None and getattr(adapter, "connected", False):
        return [f"• {provider_id}：✅ 已连接"]
    if adapter is not None:
        return [f"• {provider_id}：❌ 已断开"]
    return []


class ProviderOwnerBridge:
    def __init__(self, state, *, data_dir: Optional[str] = None):
        self.state = state
        self.data_dir = data_dir if data_dir is not None else get_data_dir()
        self.socket_path = provider_owner_bridge_socket_path(self.data_dir)
        self._server: Optional[asyncio.base_events.Server] = None
        self._pending_send_tasks: set[asyncio.Task] = set()
        self._new_session_tasks: dict[tuple[str, str, str], tuple[str, list, asyncio.Task]] = {}
        self._list_sessions_tasks: dict[tuple[str, int], asyncio.Task] = {}
        self._list_sessions_cache: dict[tuple[str, int], dict] = {}

    @property
    def is_running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        if self.is_running:
            return
        if not self.socket_path:
            raise RuntimeError("缺少 data_dir，无法启动 provider owner bridge")

        restore_send_recoveries(self.state)

        try:
            from core.usage.registry import get_usage_source_catalog
            await _run_sync_with_timeout(
                "usage_registry_warmup",
                get_usage_source_catalog,
                timeout=OWNER_BRIDGE_USAGE_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("[provider-owner-bridge] usage registry 预热失败")

        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)
        logger.info("[provider-owner-bridge] 已启动 socket=%s", self.socket_path)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        for task in tuple(self._pending_send_tasks):
            task.cancel()
        if self._pending_send_tasks:
            await asyncio.gather(*self._pending_send_tasks, return_exceptions=True)
            self._pending_send_tasks.clear()
        self._new_session_tasks.clear()

        if self.socket_path and os.path.exists(self.socket_path):
            try:
                os.remove(self.socket_path)
            except OSError:
                pass
        if self.socket_path:
            logger.info("[provider-owner-bridge] 已停止 socket=%s", self.socket_path)

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        started_at = time.perf_counter()
        request_type = "unknown"
        try:
            raw = await reader.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            request_type = str(request.get("type") or "unknown")
            if request_type == "send_message":
                response = await self._handle_send_message(request)
            elif request_type == "start_session_message":
                response = await self._handle_start_session_message(request)
            elif request_type == "list_sessions":
                response = await self._handle_list_sessions(request)
            elif request_type == "read_session":
                response = await self._handle_read_session(request)
            elif request_type == "create_session":
                response = await self._handle_create_session(request)
            elif request_type == "archive_session":
                response = await self._handle_archive_session(request)
            elif request_type == "runtime_status":
                response = await self._handle_runtime_status(request)
            elif request_type == "provider_plugin_load_failures":
                from core.providers.registry import provider_load_failures
                response = {"ok": True, "failures": provider_load_failures()}
            elif request_type == "usage_source_catalog":
                from core.usage.registry import get_usage_source_catalog
                try:
                    sources = await _run_sync_with_timeout(
                        "usage_source_catalog",
                        get_usage_source_catalog,
                        timeout=OWNER_BRIDGE_USAGE_TIMEOUT_SECONDS,
                    )
                    response = {"ok": True, "sources": sources}
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
            elif request_type == "usage_source_summary":
                response = await self._handle_usage_source_summary(request)
            elif request_type == "session_activities":
                response = await self._handle_session_activities(request)
            elif request_type == "session_activity_stream":
                await self._handle_session_activity_stream(reader, writer, request)
                return
            elif request_type == "session_event_stream":
                await self._handle_session_event_stream(reader, writer, request)
                return
            elif request_type == "reply_approval":
                response = await self._handle_reply_approval(request)
            elif request_type == "reply_question":
                response = await self._handle_reply_question(request)
            elif request_type == "session_control":
                response = await self._handle_session_control(request)
            elif request_type == "recheck_session_send":
                response = self._handle_recheck_session_send(request)
            elif request_type == "prepare_app_update":
                response = self._handle_prepare_app_update()
            elif request_type == "cancel_app_update":
                self.state.app_update_deadline = 0.0
                response = {"ok": True}
            elif request_type == "provider_hook_event":
                response = await self._handle_provider_hook_event(request)
            elif request_type == "mirror_approval":
                response = await self._handle_mirror_approval(request)
            else:
                response = {
                    "ok": False,
                    "error": f"unsupported request type: {request_type}",
                }
            writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            try:
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[provider-owner-bridge] 客户端已断开，跳过响应写入")
        except Exception as exc:
            logger.warning(
                "[provider-owner-bridge] 请求失败 type=%s error=%s",
                request_type,
                exc,
            )
            try:
                writer.write(
                    (
                        json.dumps(
                            {"ok": False, "error": str(exc)},
                            ensure_ascii=False,
                        )
                        + "\n"
                    ).encode("utf-8")
                )
                await writer.drain()
            except (OSError, RuntimeError):
                logger.debug("[provider-owner-bridge] 客户端已断开，跳过错误响应")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("[provider-owner-bridge] 客户端已断开，跳过关闭等待")
            elapsed = time.perf_counter() - started_at
            if elapsed >= OWNER_BRIDGE_SLOW_REQUEST_WARNING_SECONDS:
                logger.warning(
                    "[provider-owner-bridge] 慢请求 type=%s elapsed_ms=%d",
                    request_type,
                    int(elapsed * 1000),
                )

    async def _handle_list_sessions(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        force_refresh = bool(request.get("force_refresh", False))
        try:
            limit = int(request.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        if limit <= 0:
            limit = 100

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        facts = getattr(provider, "facts", None)
        if facts is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持会话列表"}
        list_sessions = getattr(facts, "list_sessions", None)
        if callable(list_sessions):
            cache_key = (provider_id, limit)
            if not force_refresh:
                cached = self._list_sessions_cache.get(cache_key)
                if cached is not None:
                    return cached

            task = self._list_sessions_tasks.get(cache_key)
            if task is None or task.done() or force_refresh:
                async def _load_sessions() -> dict:
                    raw_sessions = await _run_sync_with_timeout(
                        f"{provider_id}.list_sessions",
                        list_sessions,
                        limit=limit,
                        timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
                    ) or []
                    sessions = []
                    seen: set[tuple[str, str]] = set()
                    for session in raw_sessions:
                        if not isinstance(session, dict):
                            continue
                        thread_id = str(session.get("id") or session.get("thread_id") or "").strip()
                        workspace_path = str(
                            session.get("workspace")
                            or session.get("path")
                            or session.get("workspacePath")
                            or ""
                        ).strip()
                        if not thread_id or not workspace_path:
                            continue
                        dedupe_key = (workspace_path, thread_id)
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        title = str(
                            session.get("title")
                            or session.get("preview")
                            or session.get("name")
                            or thread_id
                        ).strip() or thread_id
                        preview = str(
                            session.get("preview")
                            or session.get("lastAssistantMessage")
                            or session.get("last_assistant_message")
                            or session.get("lastFinalMessage")
                            or session.get("last_final_message")
                            or session.get("lastUserMessage")
                            or session.get("last_user_message")
                            or ""
                        ).strip()
                        row = {
                            "id": thread_id,
                            "title": title,
                            "preview": preview,
                            "workspace": workspace_path,
                            "archived": bool(session.get("archived", False)),
                            "providerActive": bool(session.get("providerActive", False)),
                            "updatedAt": _safe_int(
                                session.get("updatedAt")
                                or session.get("updated_at")
                                or session.get("updated_at_epoch")
                                or session.get("createdAt")
                                or session.get("created_at")
                            ),
                            "createdAt": _safe_int(
                                session.get("createdAt")
                                or session.get("created_at")
                                or session.get("updatedAt")
                                or session.get("updated_at")
                            ),
                        }
                        source = str(session.get("source") or "").strip()
                        if source:
                            row["source"] = source
                        for field in ("workspaceGroup", "workspaceGroupKind"):
                            if isinstance(session.get(field), str):
                                row[field] = session[field].strip()
                        sessions.append(row)
                    sessions.extend(_state_only_session_rows(self.state, provider_id, facts, seen))
                    sessions.sort(
                        key=lambda item: (
                            -_safe_int(item.get("updatedAt")),
                            -_safe_int(item.get("createdAt")),
                            str(item.get("id") or ""),
                        )
                    )
                    await _hydrate_low_signal_session_previews(provider_id, facts, sessions)
                    response = {"ok": True, "sessions": sessions}
                    self._list_sessions_cache[cache_key] = response
                    return response

                task = asyncio.create_task(_load_sessions())
                self._list_sessions_tasks[cache_key] = task
            try:
                return await task
            except Exception:
                cached = self._list_sessions_cache.get(cache_key)
                if cached is not None:
                    return cached
                raise
            finally:
                current = self._list_sessions_tasks.get(cache_key)
                if current is task and task.done():
                    self._list_sessions_tasks.pop(cache_key, None)
        thread_list_is_authoritative = bool(
            getattr(facts, "thread_list_is_authoritative", False)
        )

        sessions = []
        seen: set[tuple[str, str]] = set()
        try:
            workspaces = await _run_sync_with_timeout(
                f"{provider_id}.scan_workspaces",
                facts.scan_workspaces,
                timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
            ) or []
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        for workspace in workspaces:
            if not isinstance(workspace, dict):
                continue
            workspace_path = str(
                workspace.get("path") or workspace.get("workspace") or workspace.get("cwd") or ""
            ).strip()
            if not workspace_path:
                continue

            normalized_active_ids: set[str] = set()
            if not thread_list_is_authoritative:
                try:
                    active_ids = await _run_sync_with_timeout(
                        f"{provider_id}.query_active_thread_ids({workspace_path})",
                        facts.query_active_thread_ids,
                        workspace_path,
                        timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
                    )
                except Exception:
                    active_ids = set()
                normalized_active_ids = {
                    str(item).strip() for item in active_ids if str(item).strip()
                }
            normalized_running_ids: set[str] = set()
            running_hook = getattr(facts, "query_running_thread_ids", None)
            if callable(running_hook):
                try:
                    running_ids = await _run_sync_with_timeout(
                        f"{provider_id}.query_running_thread_ids({workspace_path})",
                        running_hook,
                        workspace_path,
                        timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
                    )
                except Exception:
                    running_ids = set()
                normalized_running_ids = {
                    str(item).strip() for item in running_ids if str(item).strip()
                }

            try:
                threads = await _run_sync_with_timeout(
                    f"{provider_id}.list_threads({workspace_path})",
                    facts.list_threads,
                    workspace_path,
                    limit=limit,
                    timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
                ) or []
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

            for thread in threads:
                if not isinstance(thread, dict):
                    continue
                thread_id = str(thread.get("id") or thread.get("thread_id") or "").strip()
                if not thread_id:
                    continue

                dedupe_key = (workspace_path, thread_id)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                preview = thread.get("preview") or thread.get("title") or thread.get("name")
                title = str(preview or "").strip() or thread_id
                preview_text = str(
                    thread.get("preview")
                    or thread.get("lastAssistantMessage")
                    or thread.get("last_assistant_message")
                    or thread.get("lastFinalMessage")
                    or thread.get("last_final_message")
                    or thread.get("lastUserMessage")
                    or thread.get("last_user_message")
                    or ""
                ).strip()
                updated_at = _safe_int(
                    thread.get("updatedAt")
                    or thread.get("updated_at")
                    or thread.get("updated_at_epoch")
                    or thread.get("createdAt")
                    or thread.get("created_at")
                )
                created_at = _safe_int(
                    thread.get("createdAt")
                    or thread.get("created_at")
                    or thread.get("updatedAt")
                    or thread.get("updated_at")
                )
                archived = bool(thread.get("archived", False))
                provider_active = thread_id in normalized_running_ids if normalized_running_ids else False
                if normalized_active_ids:
                    archived = archived or thread_id not in normalized_active_ids

                row = {
                    "id": thread_id,
                    "title": title,
                    "preview": preview_text,
                    "workspace": workspace_path,
                    "archived": archived,
                    "providerActive": provider_active,
                    "updatedAt": updated_at,
                    "createdAt": created_at,
                }
                source = str(thread.get("source") or "").strip()
                if source:
                    row["source"] = source
                sessions.append(row)

        sessions.extend(_state_only_session_rows(self.state, provider_id, facts, seen))
        sessions.sort(
            key=lambda item: (
                -_safe_int(item.get("updatedAt")),
                -_safe_int(item.get("createdAt")),
                str(item.get("id") or ""),
            )
        )
        await _hydrate_low_signal_session_previews(provider_id, facts, sessions)
        return {"ok": True, "sessions": sessions}

    async def _handle_session_activities(self, request: dict) -> dict:
        try:
            limit = int(request.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        if limit <= 0:
            limit = 200

        bus = getattr(self.state, "message_bus", None)
        if bus is None or not callable(getattr(bus, "session_activities", None)):
            return {"ok": True, "activities": []}
        return {
            "ok": True,
            "activities": _filter_visible_session_activities(
                self.state,
                bus.session_activities(),
                limit,
                bus=bus,
            ),
        }

    async def _handle_session_activity_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: dict,
    ) -> None:
        try:
            limit = int(request.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        if limit <= 0:
            limit = 200

        bus = getattr(self.state, "message_bus", None)
        if bus is None or not callable(getattr(bus, "session_activities", None)):
            writer.write(
                (
                    json.dumps(
                        {
                            "ok": False,
                            "kind": "error",
                            "error": "message bus unavailable",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            return

        queue, closed, enqueue = _stream_queue(writer)

        def on_event(event) -> None:
            if not getattr(event, "provider_id", "") or not getattr(event, "session_id", ""):
                return
            if event.kind in {"session.archived", "session.hidden"}:
                payload = {
                    "ok": True,
                    "kind": "remove",
                    "providerId": event.provider_id,
                    "sessionId": event.session_id,
                }
                enqueue(payload)
                return
            activity = bus.session_activity(event.provider_id, event.session_id)
            if activity is None:
                return
            if _session_archived_in_storage(self.state, event.provider_id, event.session_id):
                payload = {
                    "ok": True,
                    "kind": "remove",
                    "providerId": event.provider_id,
                    "sessionId": event.session_id,
                }
                enqueue(payload)
                return
            payload = {
                "ok": True,
                "kind": "activity",
                "activity": _decorate_session_activity(self.state, activity, bus),
                "event": {
                    "kind": event.kind,
                    "eventId": event.event_id,
                },
            }
            enqueue(payload)

        unsubscribe = bus.subscribe(on_event)
        try:
            await _run_stream_writer(reader, writer, queue, closed,
                {
                    "ok": True,
                    "kind": "snapshot",
                    "activities": _filter_visible_session_activities(
                        self.state,
                        bus.session_activities(),
                        limit,
                        bus=bus,
                    ),
                }
            )
        finally:
            unsubscribe()

    async def _handle_session_event_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        request: dict,
    ) -> None:
        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()

        if not provider_id or not session_id:
            writer.write(
                (
                    json.dumps(
                        {
                            "kind": "error",
                            "error": "missing provider_id or session_id",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            return

        bus = getattr(self.state, "message_bus", None)
        if bus is None or not callable(getattr(bus, "subscribe", None)):
            writer.write(
                (
                    json.dumps(
                        {
                            "kind": "error",
                            "error": "message bus unavailable",
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            await writer.drain()
            return

        queue, closed, enqueue = _stream_queue(writer)

        def snapshot():
            activity = bus.session_activity(provider_id, session_id) or {}
            return {
                "kind": "replace_snapshot", "snapshot": bus.session_conversation(provider_id, session_id),
                "error": activity.get("deliveryError") or None,
                "recovery": bus.session_send_recovery(provider_id, session_id),
            }

        def on_event(event) -> None:
            if str(getattr(event, "provider_id", "") or "").strip() != provider_id:
                return
            if str(getattr(event, "session_id", "") or "").strip() != session_id:
                return
            if workspace_dir and str(getattr(event, "workspace_path", "") or "").strip() != workspace_dir:
                return
            if event.kind == "message.user.send_failed":
                activity = bus.session_activity(provider_id, session_id) or {}
                if activity.get("lastMessageRequestId") == event.payload.get("messageRequestId"):
                    enqueue({"kind": "send_failed", "semanticKind": event.kind, "error": event.payload.get("error"),
                             "recovery": bus.session_send_recovery(provider_id, session_id)})
            elif event.kind in {
                "message.user.submitted", "message.user.accepted", "message.assistant.delta",
                "message.assistant.final", "session.history.loaded", "turn.completed", "turn.failed",
                "session.recovery.updated",
                "session.archived", "session.hidden",
            }:
                enqueue(snapshot())

        unsubscribe = bus.subscribe(on_event)
        try:
            workspace, thread = _find_existing_session_binding(self.state, provider_id, session_id)
            if thread is not None and not bus.session_send_recovery(provider_id, session_id):
                if thread.new_session_recovery:
                    publish_new_session_recovery(self.state, workspace, thread)
                if thread.send_recovery:
                    publish_send_recovery(self.state, workspace, thread)
            if not bus.session_history_loaded(provider_id, session_id):
                response = await self._handle_read_session({
                    "provider_id": provider_id, "session_id": session_id, "limit": 50,
                    "workspace_dir": workspace_dir,
                })
                if not response.get("ok"):
                    writer.write((json.dumps({"kind": "error", "error": response.get("error"),
                        "recovery": bus.session_send_recovery(provider_id, session_id)}) + "\n").encode())
                    await writer.drain()
                    return
            initial_snapshot = snapshot()
            while not queue.empty():
                queue.get_nowait()
            await _run_stream_writer(reader, writer, queue, closed, initial_snapshot)
        finally:
            unsubscribe()

    def _handle_recheck_session_send(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        session_id = str(request.get("session_id") or "").strip()
        request_id = str(request.get("request_id") or "").strip()
        if not provider_id or not workspace_dir or len(request_id) > 128:
            return {"ok": False, "error": "无效的恢复请求"}
        workspace = next((ws for ws in getattr(self.state.storage, "workspaces", {}).values()
                          if ws.tool == provider_id and ws.path == workspace_dir), None)
        if workspace is None:
            return {"ok": False, "error": "工作区绑定已失效"}
        thread = workspace.threads.get(session_id) if session_id else next((item for item in workspace.threads.values()
            if request_id and item.new_session_recovery.get("request_id") == request_id), None)
        if session_id and thread is None:
            return {"ok": False, "error": "原会话不存在或绑定已变化"}
        if thread is None:
            pending = workspace.pending_new_session
            if pending and (not request_id or pending.get("requestId") == request_id):
                return {"ok": True, "accepted": False, "pending": pending.get("status") == "preparing",
                        "request_id": pending.get("requestId"), "recovery": dict(pending), "error": pending.get("error") or None}
            return {"ok": True, "accepted": False, "recovery": None,
                    "error": "尚未找到可核实的原请求；没有重新创建或发送消息。" if request_id else None}
        if thread.archived:
            return {"ok": False, "error": "原会话已归档"}
        is_new = thread.new_session_recovery.get("request_id") == request_id
        record = thread.new_session_recovery if is_new else thread.send_recovery
        if not request_id or record.get("request_id" if is_new else "requestId") != request_id:
            return {"ok": False, "error": "恢复请求与原会话不一致"}
        receipt = record.get("providerReceipt") or {}
        status_key = "send_status" if is_new else "status"
        if (receipt.get("requestId") == request_id and receipt.get("threadId") == thread.thread_id
                and receipt.get("status") in {"sent", "failed"}
                and record.get(status_key) not in {"pending", "preparing", "sending"}):
            if is_new:
                record.update(send_status=receipt["status"], error=receipt.get("error", ""))
                try:
                    _checkpoint_new_session(self.state, workspace, thread)
                except Exception:
                    pass  # The saved receipt still proves the provider outcome.
            else:
                checkpoint_send_recovery(self.state, workspace, thread, receipt["status"], receipt.get("error", ""))
                record = thread.send_recovery
        elif is_new:
            publish_new_session_recovery(self.state, workspace, thread)
        else:
            publish_send_recovery(self.state, workspace, thread)
        return {"ok": True, "accepted": record.get(status_key) == "sent", "thread_id": thread.thread_id,
                "request_id": request_id, "provider_id": provider_id, "workspace_id": workspace.daemon_workspace_id,
                "recovery": new_session_recovery_view(thread) if is_new else dict(record),
                "error": "未收到能关联原请求的 Provider 回执，发送结果仍未知。" if record.get(status_key) == "unknown" else record.get("error") or None}

    async def _handle_archive_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not thread_id:
            return {"ok": False, "error": "缺少 session_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        ws_info, thread_info = _resolve_workspace_and_thread(
            self.state,
            provider_id,
            thread_id,
            workspace_dir,
        )
        if ws_info is None or thread_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法定位 provider 会话"}

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id
        adapter = self.state.get_adapter(provider_id)
        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        if _is_app_state_thread_id(provider_id, thread_id):
            try:
                commit_session_archive(self.state, ws_info, thread_info, source="desktop_app", archive_mode="local_overlay")
            except Exception as exc:
                return {"ok": False, "error": f"本地归档失败: {exc}"}
            return {
                "ok": True,
                "provider_id": provider_id,
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "workspace_dir": ws_info.path,
                "archive_source": "local_state",
            }

        thread_hooks = getattr(provider, "thread_hooks", None)
        archive_thread = getattr(thread_hooks, "archive_thread", None) if thread_hooks is not None else None
        archive_mode = "provider"
        try:
            if callable(archive_thread):
                if getattr(archive_thread, "requires_adapter", True) and (adapter is None or not getattr(adapter, "connected", False)):
                    return {"ok": False, "error": f"{provider_id} adapter 未连接"}
                await archive_thread(self.state, ws_info, thread_id, adapter)
            elif callable(getattr(adapter, "archive_thread", None)):
                await adapter.archive_thread(workspace_id, thread_id)
            else:
                raise RuntimeError(f"Provider '{provider_id}' 不支持真实归档")
        except Exception as exc:
            unsupported = "does not expose a real source archive operation" in str(exc).lower() or "不支持真实归档" in str(exc)
            if request.get("allow_local_overlay") is not True or not unsupported:
                return {"ok": False, "error": str(exc)}
            archive_mode = "local_overlay"
        try:
            commit_session_archive(self.state, ws_info, thread_info, source="desktop_app", archive_mode=archive_mode)
        except Exception as exc:
            return {"ok": False, "error": f"归档后保存本地状态失败: {exc}"}
        return {
            "ok": True,
            "provider_id": provider_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
            "workspace_dir": ws_info.path,
            **({"archive_mode": archive_mode} if archive_mode == "local_overlay" else {}),
        }

    async def _handle_usage_source_summary(self, request: dict) -> dict:
        from core.usage.runtime import get_usage_source_summary

        plugin_id = str(request.get("plugin_id") or "").strip()
        source_id = str(request.get("source_id") or "").strip()
        start_date = str(request.get("start_date") or "").strip()
        end_date = str(request.get("end_date") or "").strip()
        timezone = str(request.get("timezone") or "local").strip() or "local"
        force_refresh = bool(request.get("force_refresh", False))
        if not plugin_id or not source_id:
            return {"ok": False, "error": "缺少 usage plugin/source id"}

        try:
            summary = await _run_sync_with_timeout(
                f"{plugin_id}/{source_id}.get_summary",
                get_usage_source_summary,
                plugin_id,
                source_id,
                start_date,
                end_date,
                timezone=timezone,
                force_refresh=force_refresh,
                timeout=35,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "summary": summary}

    async def _handle_create_session(self, request: dict) -> dict:
        try:
            with self.state.task_admission():
                return await self._handle_admitted_create_session(request)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    async def _handle_admitted_create_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        create_mode = str(request.get("create_mode") or request.get("mode") or "").strip()

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not workspace_dir:
            return {"ok": False, "error": "缺少 workspace_dir"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        ws_info = _resolve_workspace(self.state, provider_id, workspace_dir)
        if ws_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法创建 provider 会话"}

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id

        adapter = self.state.get_adapter(provider_id)
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": f"{provider_id} adapter 未连接"}
        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        if create_mode in {"app_state", "app", "state_only"}:
            thread_id = f"app:{provider_id}:{uuid.uuid4()}"
            thread_info = ws_info.threads.get(thread_id)
            if thread_info is None:
                thread_info = _new_thread_info(thread_id, source="app")
                ws_info.threads[thread_id] = thread_info
        else:
            try:
                started = await start_real_provider_thread(
                    adapter,
                    ws_info,
                    workspace_id,
                    provider_id=provider_id,
                    preview=None,
                    source=_new_thread_source(provider_id),
                )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            thread_id = started.thread_id
            thread_info = started.thread_info
        thread_info.archived = False
        thread_info.is_active = False
        thread_info.source = "app" if create_mode in {"app_state", "app", "state_only"} else thread_info.source
        thread_info.preview = getattr(thread_info, "preview", None) or "新建会话"

        if getattr(self.state, "storage", None) is not None:
            try:
                save_storage(self.state.storage)
            except Exception as exc:
                return {"ok": False, "error": f"会话已创建，但保存本地状态失败: {exc}"}
        self._list_sessions_cache.clear()

        now = int(time.time())
        return {
            "ok": True,
            "provider_id": provider_id,
            "thread_id": thread_id,
            "workspace_id": workspace_id,
            "workspace_dir": ws_info.path,
            "session": build_provider_session_summary(
                ws_info,
                thread_info,
                preview_text=thread_info.preview,
                provider_active=False,
                now=now,
            ),
        }

    async def _handle_read_session(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        try:
            limit = int(request.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        if limit <= 0:
            limit = 20

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not session_id:
            return {"ok": False, "error": "缺少 session_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        facts = getattr(provider, "facts", None)
        if facts is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持会话读取"}

        try:
            turns = await _run_sync_with_timeout(
                f"{provider_id}.read_thread_history({session_id})",
                facts.read_thread_history,
                session_id,
                limit=limit,
                timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        normalized = []
        for turn in turns or []:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "").strip()
            if role not in {"user", "assistant"}:
                continue
            normalized_turn = _normalize_provider_turn(turn)
            if not normalized_turn["content"]:
                continue
            normalized.append(normalized_turn)

        bus = getattr(self.state, "message_bus", None)
        if bus is not None:
            bus.publish(create_message_event(
                "session.history.loaded", provider_id=provider_id, session_id=session_id,
                workspace_path=str(request.get("workspace_dir") or ""), source="owner_history",
                payload={"turns": normalized, "historyWindow": limit},
            ))
            normalized = bus.session_conversation(provider_id, session_id)[-limit:]
        return {"ok": True, "session": normalized}

    def _handle_prepare_app_update(self) -> dict:
        busy = any(
            activity.get("status") in {"running", "needs_attention"}
            or activity.get("activeTurnId")
            or activity.get("deliveryStatus") in {"submitted", "queued", "uncertain"}
            for activity in self.state.message_bus.session_activities()
        )
        pending = self.state.active_task_dispatches or self.state.new_session_lock.locked()
        pending = pending or any(not task.done() for task in self._pending_send_tasks)
        pending = pending or any(runtime.active_threads
                                 for runtime in self.state.provider_runtime_state.values())
        if self.state.storage is not None:
            pending = pending or any(
                workspace.pending_new_session.get("status") in {"preparing", "unknown"}
                for workspace in self.state.storage.workspaces.values()
            )
            pending = pending or any(
                thread.send_recovery.get("status") in {"preparing", "sending", "unknown"}
                for workspace in self.state.storage.workspaces.values() for thread in workspace.threads.values()
            )
            pending = pending or any(
                thread.new_session_recovery.get("send_status") in {"pending", "preparing", "sending", "unknown"}
                and (thread.new_session_recovery.get("text") or thread.new_session_recovery.get("attachments"))
                for workspace in self.state.storage.workspaces.values() for thread in workspace.threads.values()
            )
        if busy or pending:
            return {"ok": False, "error": "仍有运行中、等待回答或正在发送的任务，或远程 CLI 连接尚未关闭，请处理完成后再安装更新。"}
        # A lost client must not leave task admission closed indefinitely.
        self.state.app_update_deadline = time.monotonic() + 30
        return {"ok": True}

    async def _handle_runtime_status(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        adapter = self.state.get_adapter(provider_id)
        lines = await _status_lines_for_provider(self.state, provider_id, provider)
        detail = " · ".join(lines) if lines else None
        return {
            "ok": True,
            "health": _runtime_health_from_lines(lines, adapter),
            "detail": detail,
            "lines": lines,
        }

    async def _handle_session_control(self, request: dict) -> dict:
        try:
            with self.state.task_admission():
                return await self._handle_admitted_session_control(request)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    async def _handle_admitted_session_control(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        action = str(request.get("action") or "").strip().lower()
        if not provider_id:
            return {"ok": False, "code": "invalid_request", "error": "缺少 provider_id"}
        if not session_id:
            return {"ok": False, "code": "invalid_request", "error": "缺少 session_id"}
        if action not in {"interrupt", "recover"}:
            return {
                "ok": False,
                "code": "invalid_request",
                "error": f"unsupported session action: {action}",
            }

        bus = getattr(self.state, "message_bus", None)
        activity = (
            bus.session_activity(provider_id, session_id)
            if bus is not None and callable(getattr(bus, "session_activity", None))
            else None
        ) or {
            "providerId": provider_id,
            "sessionId": session_id,
            "status": "running" if action == "interrupt" else "failed",
        }
        facts = _session_control_facts(self.state, activity)
        if facts["controlMode"] != "owned":
            return {
                "ok": False,
                "code": "not_owned",
                "error": facts["controlReason"] or "此 Session 不由 OnlineWorker 控制。",
            }

        allowed = facts["canInterrupt"] if action == "interrupt" else facts["canRecover"]
        if not allowed:
            return {
                "ok": False,
                "code": "unsupported",
                "error": facts["controlReason"] or f"当前 Session 不支持{action}。",
            }

        ws, thread = _find_existing_session_binding(self.state, provider_id, session_id)
        provider = get_provider(provider_id, getattr(self.state, "config", None))
        adapter = _resolve_session_adapter(self.state, provider_id, ws)
        if ws is None or thread is None or provider is None or (action == "interrupt" and adapter is None):
            return {"ok": False, "code": "unavailable", "error": "Session 控制通道不可用。"}

        try:
            if action == "interrupt":
                hooks = getattr(provider, "thread_hooks", None)
                interrupt = getattr(hooks, "interrupt_thread", None) if hooks is not None else None
                turn_id = _active_session_turn_id(self.state, activity, session_id)
                if not callable(interrupt) or not turn_id:
                    return {
                        "ok": False,
                        "code": "unsupported",
                        "error": "当前 Session 没有可中断的活跃任务。",
                    }
                result = interrupt(self.state, ws, thread, adapter, turn_id)
                if inspect.isawaitable(result):
                    await result
            else:
                if adapter is None or not bool(getattr(adapter, "connected", False)):
                    message_hooks = getattr(provider, "message_hooks", None)
                    ensure_connected = (
                        getattr(message_hooks, "ensure_connected", None)
                        if message_hooks is not None
                        else None
                    )
                    if callable(ensure_connected):
                        adapter = await ensure_connected(
                            self.state,
                            adapter,
                            ws,
                            update=None,
                            context=None,
                            group_chat_id=0,
                            src_topic_id=None,
                        )
                        if adapter is not None:
                            self.state.set_adapter(provider_id, adapter)
                if adapter is None or not bool(getattr(adapter, "connected", False)):
                    return {
                        "ok": False,
                        "code": "unavailable",
                        "error": f"{provider_id} adapter 未连接。",
                    }
                resume_thread = getattr(adapter, "resume_thread", None)
                if not callable(resume_thread):
                    return {
                        "ok": False,
                        "code": "unsupported",
                        "error": "当前 Provider 不支持恢复此 Session。",
                    }
                workspace_id = str(getattr(ws, "daemon_workspace_id", "") or "").strip()
                result = resume_thread(workspace_id, session_id)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            return {"ok": False, "code": "provider_error", "error": str(exc)}

        return {
            "ok": True,
            "accepted": True,
            "action": action,
            "provider_id": provider_id,
            "session_id": session_id,
            "awaiting_provider_event": action == "interrupt",
        }

    async def _handle_mirror_approval(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("thread_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}

        logger.info(
            "[provider-hook-mirror] 忽略 legacy mirror_approval；审批只走 app-server request/response "
            "provider=%s thread=%s workspace=%s source=%s",
            provider_id,
            thread_id[:12] if thread_id else "?",
            workspace_dir or "?",
            str(request.get("source") or ""),
        )
        return {"ok": True, "ignored": True, "reason": "approval_via_app_server_only"}

    async def _handle_provider_hook_event(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        payload = request.get("payload")
        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "缺少 hook payload"}

        adapter = self.state.get_adapter(provider_id)
        ingress = getattr(adapter, "ingest_external_hook_payload", None) if adapter is not None else None
        if not callable(ingress):
            return {
                "ok": False,
                "error": f"Provider '{provider_id}' 没有可用的 hook event ingress",
            }

        async def dispatch_hook_event() -> None:
            try:
                result = await ingress(payload)
                if isinstance(result, dict) and result.get("accepted") is False:
                    logger.warning(
                        "[provider-hook-event] 事件未接收 provider=%s event=%s session=%s reason=%s",
                        provider_id,
                        str(payload.get("hook_event_name") or ""),
                        str(payload.get("session_id") or "")[:12],
                        str(result.get("reason") or "unknown"),
                    )
                else:
                    logger.info(
                        "[provider-hook-event] 已接收 provider=%s event=%s session=%s emitted=%s",
                        provider_id,
                        str(payload.get("hook_event_name") or ""),
                        str(payload.get("session_id") or "")[:12],
                        str(result.get("emitted") or 0) if isinstance(result, dict) else "?",
                    )
            except Exception:
                logger.exception(
                    "[provider-hook-event] 分发失败 provider=%s event=%s session=%s",
                    provider_id,
                    str(payload.get("hook_event_name") or ""),
                    str(payload.get("session_id") or "")[:12],
                )

        task = asyncio.create_task(
            dispatch_hook_event(),
            name=f"provider-hook-event-{provider_id}",
        )
        self._pending_send_tasks.add(task)
        task.add_done_callback(self._pending_send_tasks.discard)
        return {"ok": True, "accepted": True}

    async def _handle_reply_approval(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        workspace_id = str(request.get("workspace_id") or "").strip()
        thread_id = str(request.get("session_id") or request.get("thread_id") or "").strip()
        request_id = str(request.get("request_id") or "").strip()
        action = str(request.get("action") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or request.get("workspace_path") or "").strip()
        approval_source = str(request.get("approval_source") or "app_server").strip() or "app_server"
        command = str(request.get("command") or "").strip()
        reason = str(request.get("reason") or request.get("attention_reason") or "").strip()

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not request_id:
            return {"ok": False, "error": "缺少 request_id"}
        if action not in {"exec_allow", "exec_deny", "exec_allow_always"}:
            return {"ok": False, "error": f"unsupported approval action: {action}"}

        if not workspace_id and (workspace_dir or thread_id):
            ws_info, _thread_info = _resolve_workspace_and_thread(
                self.state,
                provider_id,
                thread_id,
                workspace_dir,
            )
            workspace_id = (
                getattr(ws_info, "daemon_workspace_id", "") or _workspace_key(provider_id, workspace_dir)
                if ws_info is not None
                else workspace_id
            )

        approval = SimpleNamespace(
            request_id=request_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            cmd=command,
            justification=reason,
            tool_name=provider_id,
            tool_type=provider_id,
            amendment_decision=request.get("amendment_decision") or {},
            approval_source=approval_source,
        )

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}
        if not workspace_id:
            return {"ok": False, "error": "缺少 workspace_id，无法回复授权"}

        adapter = self.state.get_adapter(provider_id)
        if adapter is None or not getattr(adapter, "connected", False):
            adapter = self.state.get_adapter_for_workspace(workspace_id)
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": f"{provider_id} adapter 未连接"}
        reply_server_request = getattr(adapter, "reply_server_request", None)
        if not callable(reply_server_request):
            return {"ok": False, "error": f"{provider_id} adapter 不支持 reply_server_request"}

        label, reply_body = _build_provider_approval_reply(provider, approval, action)
        raw_request_id = _resolve_raw_approval_request_id(
            self.state,
            provider_id,
            request_id,
            thread_id=thread_id,
            workspace_id=workspace_id,
        )
        await reply_server_request(workspace_id, raw_request_id, reply_body)
        publish_approval_answered(
            self.state,
            approval,
            action=action,
            source="desktop_app",
        )
        return {
            "ok": True,
            "mode": "adapter",
            "provider_id": provider_id,
            "request_id": request_id,
            "action": action,
            "label": label,
        }

    async def _handle_reply_question(self, request: dict) -> dict:
        from core.providers.interaction_runtime import reply_question_via_adapter, submit_question_reply
        from core.state import PendingQuestion, PendingQuestionGroup

        provider_id = str(request.get("provider_id") or "").strip()
        session_id = str(request.get("session_id") or "").strip()
        question_id = str(request.get("question_id") or "").strip()
        activity = self.state.message_bus.session_activity(provider_id, session_id) or {}
        if (not question_id or activity.get("status") != "needs_attention"
                or activity.get("attentionKind") != "question" or activity.get("requestId") != question_id
                or activity.get("mirroredOnly")):
            return {"ok": False, "error": "问题已回答、已失效或由外部客户端控制。"}
        questions = activity.get("questions") or []
        answers = request.get("answers")
        if (not questions or not isinstance(answers, list) or len(answers) != len(questions)
                or [question.get("subIndex") for question in questions] != list(range(len(questions)))
                or any(question.get("subTotal") != len(questions) for question in questions)):
            return {"ok": False, "error": "问题尚未完整加载或答案数量不匹配。"}
        normalized = []
        for question, answer in zip(questions, answers):
            if not isinstance(answer, list) or not answer or any(not isinstance(value, str) or not value.strip() for value in answer):
                return {"ok": False, "error": "请回答所有问题。"}
            values = list(dict.fromkeys(value.strip() for value in answer))
            labels = {str(option.get("label") or "") for option in question.get("options") or []}
            if ((not question.get("multiple") and len(values) != 1)
                    or (not question.get("custom") and any(value not in labels for value in values))):
                return {"ok": False, "error": "答案不符合问题的选项或输入要求。"}
            normalized.append(values)
        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}
        adapter = self.state.get_adapter(provider_id)
        if adapter is None or not getattr(adapter, "connected", False):
            adapter = self.state.get_adapter_for_workspace(activity.get("workspaceId") or "")
        if adapter is None or not getattr(adapter, "connected", False):
            return {"ok": False, "error": f"{provider_id} adapter 未连接"}
        reply = getattr(getattr(provider, "interactions", None), "reply_question", None)
        if not callable(reply) and callable(getattr(adapter, "reply_question", None)):
            reply = reply_question_via_adapter
        if not callable(reply):
            return {"ok": False, "error": f"{provider_id} 未注册问题回复能力"}
        workspace_id = activity.get("workspaceId") or ""
        first = questions[0]
        group = PendingQuestionGroup(question_id, session_id, workspace_id, len(questions),
                                     answers=dict(enumerate(normalized))) if len(questions) > 1 else None
        pending = PendingQuestion(question_id, session_id, workspace_id, first.get("header") or "",
                                  first.get("question") or "", first.get("options") or [],
                                  multiple=bool(first.get("multiple")), custom=bool(first.get("custom")),
                                  group=group, tool_name=provider_id)
        try:
            await submit_question_reply(self.state, adapter, reply, pending, normalized, source="desktop_app")
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    async def _handle_send_message(self, request: dict) -> dict:
        try:
            with self.state.task_admission():
                return await self._handle_admitted_send_message(request)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    async def _handle_admitted_send_message(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        thread_id = str(request.get("thread_id") or "").strip()
        text = str(request.get("text") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        attachments = request.get("attachments") or []

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not thread_id:
            return {"ok": False, "error": "缺少 thread_id"}
        if not text and not attachments:
            return {"ok": False, "error": "空消息，拒绝发送"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}

        ws_info, thread_info = _find_existing_session_binding(self.state, provider_id, thread_id)
        if ws_info is None:
            query_ids = getattr(getattr(provider, "facts", None), "query_active_thread_ids", None)
            if not workspace_dir or not callable(query_ids):
                return {"ok": False, "error": "无法确认目标会话，请刷新会话列表后重试。"}
            try:
                active_ids = await _run_sync_with_timeout(
                    f"{provider_id}.query_active_thread_ids", query_ids, workspace_dir,
                    timeout=OWNER_BRIDGE_FACTS_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                return {"ok": False, "error": f"无法确认目标会话：{exc}"}
            if thread_id not in (active_ids or set()):
                return {"ok": False, "error": "目标会话不存在、已归档或不属于当前工作区，消息未发送。"}
            ws_info, thread_info = _resolve_workspace_and_thread(self.state, provider_id, thread_id, workspace_dir)
        if ws_info is None or thread_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法定位 provider 会话"}

        target_workspace = workspace_dir or ws_info.path

        def validate_target(expected_thread_id):
            validate_provider_thread_target(ws_info, thread_info, provider_id=provider_id,
                                            thread_id=expected_thread_id, workspace_path=target_workspace)
            if self.state.storage is not None and not any(ws is ws_info for ws in self.state.storage.workspaces.values()):
                raise RuntimeError("工作区绑定已失效，消息未发送，请刷新会话后重试。")

        try:
            validate_target(thread_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        request_id = str(request.get("request_id") or "").strip() if request.get("source", "session_tab") == "session_tab" else ""
        if len(request_id) > 128:
            return {"ok": False, "error": "无效的发送请求 ID"}
        if request.get("source", "session_tab") == "session_tab":
            if thread_info.new_session_recovery.get("send_status") in {"pending", "preparing", "sending", "unknown"}:
                return {"ok": False, "error": "原首消息尚未确认送达，请先核实会话，避免重复发送。"}
            if (thread_info.send_recovery.get("status") in {"preparing", "sending", "unknown"}
                    and thread_info.send_recovery.get("requestId") != request_id):
                return {"ok": False, "error": "上一条消息尚未确认送达，请先核实会话，避免重复发送。"}

        def checkpoint(status, error=""):
            if request_id and thread_info.send_recovery.get("requestId") == request_id:
                checkpoint_send_recovery(self.state, ws_info, thread_info, status, error)

        if request_id:
            previous = thread_info.send_recovery
            if previous.get("requestId") == request_id:
                if previous.get("text") != text or previous.get("attachments") != attachments:
                    return {"ok": False, "error": "发送请求 ID 与原输入不一致"}
                publish_send_recovery(self.state, ws_info, thread_info)
                return {"ok": True, "request_id": request_id, "thread_id": thread_id,
                        "accepted": previous.get("status") == "sent",
                        "error": previous.get("error") or (None if previous.get("status") == "sent" else "原请求尚未确认送达，请先核实会话。")}
            if previous.get("status") in {"preparing", "sending", "unknown"}:
                return {"ok": False, "error": "上一条消息尚未确认送达，请先核实会话，避免重复发送。"}
            # ponytail: retain the latest attempt per session; add an outbox if multiple failed drafts are needed.
            thread_info.send_recovery = {"requestId": request_id, "text": text, "attachments": attachments}
            try:
                checkpoint("preparing")
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
        adapter = self.state.get_adapter(provider_id)

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id

        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        message_hooks = getattr(provider, "message_hooks", None)
        if message_hooks is None:
            checkpoint("failed", f"Provider '{provider_id}' 不支持发送消息")
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持发送消息"}

        try:
            gateway_result = await prepare_user_message_text(self.state, UserMessageSendRequest(
                source=str(request.get("source") or "session_tab"),
                provider_id=provider_id,
                workspace_id=str(workspace_id),
                thread_id=thread_id,
                text=text,
                attachments=attachments,
            ))
        except Exception as exc:
            checkpoint("failed", exc)
            raise
        text = gateway_result.text
        message_event_request = UserMessageSendRequest(
            source=str(request.get("source") or "session_tab"),
            provider_id=provider_id,
            workspace_id=str(workspace_id),
            thread_id=thread_id,
            text=text,
            attachments=attachments,
            metadata={"bridge": "provider_owner", **({"messageRequestId": request_id} if request_id else {})},
        )
        publish_user_message_submitted(
            self.state,
            message_event_request,
            text=text,
            workspace_path=str(getattr(ws_info, "path", "") or ""),
        )

        source = str(request.get("source") or "session_tab")
        owner_bridge_router = getattr(message_hooks, "try_route_owner_bridge_send", None)
        if callable(owner_bridge_router) and not attachments and source != "session_tab":
            with report_user_message_failure(self.state, message_event_request, text=text, workspace_path=ws_info.path):
                validate_target(thread_id)
                route_result = await owner_bridge_router(
                    self.state, ws_info, thread_info, text=text,
                )
            if route_result:
                checkpoint("sent")
                self.state.mark_provider_send_started(provider_id, thread_id)
                publish_user_message_accepted(
                    self.state,
                    message_event_request,
                    text=text,
                    workspace_path=str(getattr(ws_info, "path", "") or ""),
                )
                return {
                    "ok": True,
                    "accepted": True,
                    "provider_id": provider_id,
                    "thread_id": thread_id,
                    "requested_thread_id": thread_id,
                    "remapped": False,
                    "workspace_id": workspace_id,
                    "transport": str(route_result) if isinstance(route_result, str) else "provider_owner_bridge",
                }

        original_thread_id = thread_info.thread_id
        original_topic_id = getattr(thread_info, "topic_id", None)
        original_preview = getattr(thread_info, "preview", None)
        original_source = str(getattr(thread_info, "source", "") or "unknown")
        original_is_active = bool(getattr(thread_info, "is_active", False))
        original_history_sync_cursor = getattr(thread_info, "history_sync_cursor", None)
        original_streaming_msg_id = getattr(thread_info, "streaming_msg_id", None)
        original_last_tg_user_message_id = getattr(thread_info, "last_tg_user_message_id", None)

        def rollback_thread_remap() -> bool:
            if thread_info.thread_id == original_thread_id:
                return False
            if thread_info.archived or ws_info.threads.get(thread_info.thread_id) is not thread_info:
                return False
            ws_info.threads.pop(thread_info.thread_id, None)
            thread_info.thread_id = original_thread_id
            thread_info.topic_id = original_topic_id
            thread_info.preview = original_preview
            thread_info.source = original_source
            thread_info.is_active = original_is_active
            thread_info.history_sync_cursor = original_history_sync_cursor
            thread_info.streaming_msg_id = original_streaming_msg_id
            thread_info.last_tg_user_message_id = original_last_tg_user_message_id
            ws_info.threads[original_thread_id] = thread_info
            return True

        skip_prepare_send = bool(request.get("_skip_prepare_send", False))
        try:
            validate_target(original_thread_id)
            previous_adapter = adapter
            adapter = await _ensure_message_adapter(self.state, provider_id, provider, ws_info)
            if adapter is not previous_adapter and hasattr(adapter, "register_workspace_cwd"):
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            validate_target(original_thread_id)
            self.state.mark_provider_send_started(provider_id, thread_id)
            if not skip_prepare_send:
                should_continue = await message_hooks.prepare_send(
                    self.state,
                    adapter,
                    ws_info,
                    thread_info,
                    update=None,
                    context=None,
                    group_chat_id=0,
                    src_topic_id=None,
                    text=text,
                    has_photo=False,
                    attachments=attachments,
                )
                if should_continue is False:
                    checkpoint("failed", "Provider 未接收消息，发送已取消。")
                    publish_user_message_failed(self.state, message_event_request, text=text,
                                                workspace_path=ws_info.path, error="Provider 未接收消息，发送已取消。")
                    return {
                        "ok": True,
                        "accepted": False,
                        "provider_id": provider_id,
                        "thread_id": thread_id,
                        "workspace_id": workspace_id,
                    }
            else:
                logger.info(
                    "[provider-owner-bridge] start_session_message 跳过 prepare_send provider=%s thread=%s",
                    provider_id,
                    thread_id[:12] if thread_id else "?",
                )
        except Exception as exc:
            rollback_thread_remap()
            checkpoint("failed", exc)
            publish_user_message_failed(self.state, message_event_request, text=text, workspace_path=ws_info.path, error=exc,
                                        delivery_status="failed" if request_id else "")
            return {"ok": False, "error": str(exc)}

        if thread_info.thread_id != original_thread_id and getattr(self.state, "storage", None) is not None:
            try:
                save_storage(self.state.storage)
            except Exception as exc:
                rollback_thread_remap()
                checkpoint("failed", exc)
                publish_user_message_failed(self.state, message_event_request, text=text, workspace_path=ws_info.path, error=exc)
                return {"ok": False, "error": f"保存 remapped thread 失败，消息未发送: {exc}"}

        delivery_request = UserMessageSendRequest(
            source=str(request.get("source") or "session_tab"),
            provider_id=provider_id, workspace_id=str(workspace_id),
            thread_id=str(thread_info.thread_id), text=text, attachments=attachments,
            metadata=message_event_request.metadata,
        )
        publish_user_message_event(
            self.state,
            delivery_request,
            text=text,
            workspace_path=str(getattr(ws_info, "path", "") or ""),
            kind="message.user.queued", delivery_status="queued",
        )

        async def execute_send() -> None:
            entered_send = False
            try:
                validate_target(delivery_request.thread_id)
                if request_id:
                    attachment_root = os.path.realpath(os.path.join(self.data_dir or "", "composer-attachments"))
                    for attachment in attachments:
                        path = os.path.realpath(str(attachment.get("path") or ""))
                        if not path.startswith(attachment_root + os.sep) or not os.path.isfile(path):
                            raise RuntimeError("附件已失效，请移除后重新选择附件。")
                checkpoint("sending")
                entered_send = True
                send_result = await message_hooks.send(
                    self.state,
                    adapter,
                    ws_info,
                    thread_info,
                    update=None,
                    context=None,
                    group_chat_id=0,
                    src_topic_id=None,
                    text=text,
                    has_photo=False,
                    attachments=attachments,
                )
                if isinstance(send_result, dict) and str(send_result.get("status") or "") == "error":
                    raise RuntimeError(str(send_result.get("error") or f"{provider_id} send failed"))
                checkpoint("sent")
                publish_user_message_accepted(self.state, delivery_request, text=text, workspace_path=ws_info.path)
            except (Exception, asyncio.CancelledError) as exc:
                checkpoint("unknown" if entered_send else "failed", str(exc) or "发送已中断")
                publish_user_message_failed(self.state, delivery_request, text=text, workspace_path=ws_info.path, error=exc,
                    delivery_status=("uncertain" if entered_send else "failed") if request_id else "")
                rolled_back = rollback_thread_remap() if not request_id else False
                if rolled_back and getattr(self.state, "storage", None) is not None:
                    try:
                        save_storage(self.state.storage)
                    except Exception:
                        logger.exception(
                            "[provider-owner-bridge] 后台发送失败后保存回滚失败 provider=%s thread=%s",
                            provider_id,
                            thread_id[:12] if thread_id else "?",
                        )
                logger.exception(
                    "[provider-owner-bridge] 后台发送失败 provider=%s thread=%s",
                    provider_id,
                    thread_id[:12] if thread_id else "?",
                )
                if isinstance(exc, asyncio.CancelledError):
                    raise

        task = asyncio.create_task(execute_send())
        self._pending_send_tasks.add(task)
        task.add_done_callback(self._pending_send_tasks.discard)

        return {
            "ok": True,
            "accepted": True,
            **({"request_id": request_id} if request_id else {}),
            "provider_id": provider_id,
            "thread_id": thread_info.thread_id,
            "requested_thread_id": thread_id,
            "remapped": thread_info.thread_id != thread_id,
            "workspace_id": workspace_id,
        }

    async def _execute_start_session_message(
        self,
        *,
        request: dict,
        provider_id: str,
        provider,
        ws_info,
        workspace_id: str,
        adapter,
        text: str,
        attachments,
    ) -> dict:
        recovery_key = str(request.get("request_id") or uuid.uuid4())
        try:
            started = await start_real_provider_thread(
                adapter,
                ws_info,
                workspace_id,
                provider_id=provider_id,
                preview=text,
                source="provider",
                state=self.state,
                recovery_key=recovery_key,
                attachments=attachments,
            )
        except Exception as exc:
            saved_thread = next((thread for thread in ws_info.threads.values()
                                 if thread.new_session_recovery.get("request_id") == recovery_key), None)
            if saved_thread is not None:
                saved_thread.new_session_recovery.update(send_status="failed", error=f"首消息未发送: {exc}")
                try:
                    _checkpoint_new_session(self.state, ws_info, saved_thread)
                except Exception:
                    pass
            if saved_thread is None and ws_info.pending_new_session.get("requestId") == recovery_key:
                ws_info.pending_new_session.update(status="unknown", error=f"创建结果未知，原输入已保留: {exc}")
                try:
                    save_storage(self.state.storage)
                except Exception as save_exc:
                    ws_info.pending_new_session["error"] += f"；恢复记录保存失败: {save_exc}"
            self._list_sessions_cache.clear()
            return {
                "ok": True, "accepted": False, "error": str(exc), "request_id": recovery_key,
                "thread_id": saved_thread.thread_id if saved_thread else "",
                "recovery": new_session_recovery_view(saved_thread) if saved_thread else dict(ws_info.pending_new_session),
            }
        thread_id = started.thread_id
        created_thread = started.created_thread
        thread_info = started.thread_info
        # The real thread checkpoint contains the input; the creation-only record is no longer needed.
        if ws_info.pending_new_session.get("requestId") == recovery_key:
            ws_info.pending_new_session = {}

        try:
            sent = await send_started_provider_thread_message(
                self.state,
                ws_info,
                thread_info,
                workspace_id,
                provider_id=provider_id,
                text=text,
                attachments=attachments,
                source=str(request.get("source") or "session_tab"),
                provider=provider,
                adapter=adapter,
                metadata={"bridge": "provider_owner"},
            )
        except Exception as exc:
            self._list_sessions_cache.clear()
            return {
                "ok": True,
                "error": thread_info.new_session_recovery.get("error") or str(exc),
                "provider_id": provider_id,
                "thread_id": thread_id,
                "requested_thread_id": thread_id,
                "workspace_id": workspace_id,
                "created_new_thread": created_thread,
                "request_id": recovery_key,
                "recovery": new_session_recovery_view(thread_info),
                "accepted": thread_info.new_session_recovery.get("send_status") == "sent",
            }
        self._list_sessions_cache.clear()

        now = int(time.time())
        effective_thread_id = str(sent.thread_id or thread_id)
        return {
            "ok": True,
            "accepted": True,
            "provider_id": provider_id,
            "thread_id": effective_thread_id,
            "requested_thread_id": thread_id,
            "workspace_id": workspace_id,
            "created_new_thread": created_thread,
            "request_id": recovery_key,
            "recovery": new_session_recovery_view(thread_info),
            "remapped": effective_thread_id != thread_id,
            "session": build_provider_session_summary(
                ws_info,
                thread_info,
                preview_text=sent.text,
                provider_active=True,
                now=now,
            ),
        }

    async def _handle_start_session_message(self, request: dict) -> dict:
        try:
            with self.state.task_admission():
                return await self._handle_admitted_start_session_message(request)
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

    async def _handle_admitted_start_session_message(self, request: dict) -> dict:
        provider_id = str(request.get("provider_id") or "").strip()
        workspace_dir = str(request.get("workspace_dir") or "").strip()
        text = str(request.get("text") or "").strip()
        attachments = request.get("attachments") or []

        if not provider_id:
            return {"ok": False, "error": "缺少 provider_id"}
        if not workspace_dir:
            return {"ok": False, "error": "缺少 workspace_dir"}
        if not text and not attachments:
            return {"ok": False, "error": "空消息，拒绝发送"}

        provider = get_provider(provider_id, getattr(self.state, "config", None))
        if provider is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 未启用"}
        if getattr(provider, "message_hooks", None) is None:
            return {"ok": False, "error": f"Provider '{provider_id}' 不支持发送消息"}

        ws_info = _resolve_workspace(self.state, provider_id, workspace_dir)
        if ws_info is None:
            return {"ok": False, "error": "缺少 workspace_dir，无法创建 provider 会话"}

        validation_error = validate_new_provider_thread_request(
            self.state,
            ws_info,
            text=text,
            attachments=attachments,
            provider=provider,
        )
        if validation_error:
            return {"ok": False, "error": validation_error}

        try:
            adapter = await _ensure_message_adapter(self.state, provider_id, provider, ws_info)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        workspace_id = getattr(ws_info, "daemon_workspace_id", None) or _workspace_key(provider_id, ws_info.path)
        ws_info.daemon_workspace_id = workspace_id

        if hasattr(adapter, "register_workspace_cwd"):
            try:
                adapter.register_workspace_cwd(workspace_id, ws_info.path)
            except Exception:
                logger.debug("[provider-owner-bridge] register_workspace_cwd 失败", exc_info=True)

        recovery_key = str(request.get("request_id") or uuid.uuid4())
        if len(recovery_key) > 128:
            return {"ok": False, "error": "无效的发送请求 ID"}
        request = {**request, "request_id": recovery_key}
        task_key = (provider_id, workspace_id, recovery_key)
        pending = self._new_session_tasks.get(task_key)
        if pending and (pending[0] != text or pending[1] != attachments):
            return {"ok": False, "error": "恢复请求与原始首消息不一致"}
        saved_thread = next((item for item in ws_info.threads.values()
                            if item.new_session_recovery.get("request_id") == recovery_key), None)
        creation = ws_info.pending_new_session
        if not pending and not saved_thread:
            if creation and creation.get("status") in {"preparing", "unknown"}:
                return {"ok": True, "accepted": False, "error": "上一次创建尚未确认，请先核实原请求。",
                        "request_id": creation.get("requestId"), "recovery": dict(creation)}
            # ponytail: retain one unresolved creation per workspace; use an outbox if parallel creation is required.
            ws_info.pending_new_session = {"kind": "new-session", "requestId": recovery_key, "status": "preparing",
                "text": text, "attachments": attachments, "error": "", "updatedAt": time.time()}
            try:
                save_storage(self.state.storage)
            except Exception as exc:
                ws_info.pending_new_session.update(status="failed", error=f"保存原输入失败，尚未创建会话: {exc}")
                return {"ok": True, "accepted": False, "error": ws_info.pending_new_session["error"],
                        "request_id": recovery_key, "recovery": dict(ws_info.pending_new_session)}
        task = pending[2] if pending else asyncio.create_task(
            self._execute_start_session_message(
                request=request,
                provider_id=provider_id,
                provider=provider,
                ws_info=ws_info,
                workspace_id=workspace_id,
                adapter=adapter,
                text=text,
                attachments=attachments,
            )
        )
        self._new_session_tasks[task_key] = (text, attachments, task)

        def clear_start_task(completed):
            current = self._new_session_tasks.get(task_key)
            if current is not None and current[2] is completed:
                self._new_session_tasks.pop(task_key, None)

        if pending is None:
            task.add_done_callback(clear_start_task)
        self._pending_send_tasks.add(task)
        task.add_done_callback(self._pending_send_tasks.discard)

        done, _pending = await asyncio.wait({task}, timeout=0.03)
        if done:
            return task.result()

        return {
            "ok": True,
            "accepted": True,
            "pending": True,
            "request_id": recovery_key,
            "provider_id": provider_id,
            "thread_id": "",
            "requested_thread_id": "",
            "workspace_id": workspace_id,
            "workspace_dir": ws_info.path,
            "created_new_thread": False,
            "remapped": False,
        }


async def ensure_provider_owner_bridge_started(state) -> Optional[ProviderOwnerBridge]:
    runtime = state.get_provider_runtime("__shared__")
    bridge = getattr(runtime, "owner_bridge", None)
    if bridge is not None and bridge.is_running:
        return bridge

    bridge = ProviderOwnerBridge(state)
    if not bridge.socket_path:
        logger.info("[provider-owner-bridge] 缺少 data_dir，跳过 owner bridge 启动")
        return None
    await bridge.start()
    runtime.owner_bridge = bridge
    return bridge


async def stop_provider_owner_bridge(state) -> None:
    runtime = state.get_provider_runtime("__shared__")
    bridge = getattr(runtime, "owner_bridge", None)
    if bridge is None:
        return
    await bridge.stop()
    runtime.owner_bridge = None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
