import asyncio
import logging
import os
from typing import Optional
import urllib.error
import urllib.request

from config import ToolConfig, get_data_dir
from plugins.providers.builtin.codex.python.adapter import CodexAdapter
from plugins.providers.builtin.codex.python.process import AppServerProcess
from core.providers.facts import query_provider_active_thread_ids
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from plugins.providers.builtin.codex.python import storage_runtime
from plugins.providers.builtin.codex.python.tui_host_client import send_message_to_codex_tui_host
from plugins.providers.builtin.codex.python.tui_host_protocol import read_host_status
from plugins.providers.builtin.codex.python.tui_host_runtime import CodexTuiHost
from plugins.providers.builtin.codex.python.tui_realtime_mirror import seed_codex_watch_baseline, watch_codex_thread
from core.state import AppState
from core.storage import WorkspaceInfo, save_storage
from core.telegram_formatting import format_telegram_assistant_final_text

logger = logging.getLogger(__name__)

read_thread_history = storage_runtime.read_thread_history


def _revive_stale_archived_thread_if_active(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    thread,
    *,
    active_ids: Optional[set[str]] = None,
) -> tuple[bool, Optional[set[str]]]:
    if not getattr(thread, "archived", False):
        return False, active_ids

    if active_ids is None:
        try:
            active_ids = query_provider_active_thread_ids(ws.tool, ws.path)
        except Exception as e:
            logger.warning(
                "[tui-bridge] 查询活跃 thread 失败，tool=%s ws=%s tid=%s err=%s",
                ws.tool,
                ws.name,
                thread_id,
                e,
            )
            active_ids = set()

    if thread_id not in active_ids:
        return False, active_ids

    thread.archived = False
    thread.is_active = True
    if state.storage is not None:
        save_storage(state.storage)
    logger.warning(
        "[tui-bridge] 已清理本地误归档 thread，tool=%s ws=%s tid=%s",
        ws.tool,
        ws.name,
        thread_id,
    )
    return True, active_ids


def _is_final_answer(item: dict) -> bool:
    return (
        item.get("role") == "assistant"
        and (item.get("text") or "").strip() != ""
        and item.get("phase") == "final_answer"
    )


def _final_reply_signature(item: dict) -> str:
    timestamp = item.get("timestamp") or ""
    text = (item.get("text") or "").strip()
    return f"{timestamp}\n{text}"


def _final_reply_text_signature(text: str) -> str:
    return f"__text__\n{(text or '').strip()}"


def _final_reply_turn_id(item: dict) -> str:
    return str(
        item.get("turn_id")
        or item.get("turnId")
        or item.get("turn")
        or ""
    ).strip()


def _latest_final_answer(history: list[dict]) -> Optional[dict]:
    final_answers = [item for item in history if _is_final_answer(item)]
    if not final_answers:
        return None
    return final_answers[-1]


def _is_reply_already_synced(state: AppState, thread_id: str, item: dict) -> bool:
    latest_signature = _final_reply_signature(item)
    latest_text_signature = _final_reply_text_signature(item.get("text") or "")
    runtime = codex_state.get_runtime(state)
    synced = runtime.last_synced_assistant.get(thread_id)
    if synced == latest_signature:
        return True
    if synced == latest_text_signature:
        # 之前仅靠实时链路记录了 text-only 去重签名，这里升级成带 timestamp 的稳定签名。
        runtime.last_synced_assistant[thread_id] = latest_signature
        return True
    run = codex_state.get_current_run(state, thread_id)
    item_turn_id = _final_reply_turn_id(item)
    if (
        run is not None
        and run.final_reply_synced_to_tg
        and item_turn_id
        and item_turn_id == run.turn_id
    ):
        # live event path 已按 run ledger 标记最终回复送达；后台轮询只补签名，避免重复发 TG。
        runtime.last_synced_assistant[thread_id] = latest_signature
        return True
    return False


def remember_codex_tg_synced_final_reply(
    state: AppState,
    thread_id: str,
    *,
    text: str,
) -> None:
    """记录某条已经在 TG 展示过的 final reply，用于后台补偿同步去重。"""
    normalized = (text or "").strip()
    if not normalized:
        return

    runtime = codex_state.get_runtime(state)
    runtime.last_synced_assistant[thread_id] = _final_reply_text_signature(normalized)

    try:
        history = read_thread_history(thread_id, limit=20)
    except Exception:
        history = []

    latest_item = _latest_final_answer(history)
    if latest_item is None:
        return

    latest_text = (latest_item.get("text") or "").strip()
    if latest_text == normalized:
        runtime.last_synced_assistant[thread_id] = _final_reply_signature(latest_item)


async def _send_formatted_final_reply_to_group(
    bot,
    group_chat_id: int,
    topic_id: int,
    thread_id: str,
    raw_text: str,
) -> None:
    from bot.handlers.common import _send_to_group

    rendered = format_telegram_assistant_final_text(raw_text)
    attempts = [(rendered.text, rendered.parse_mode)]
    if rendered.parse_mode is not None:
        attempts.append((rendered.fallback_text, None))

    last_error: Optional[Exception] = None
    for text, parse_mode in attempts:
        try:
            kwargs = {}
            if parse_mode:
                kwargs["parse_mode"] = parse_mode
            await _send_to_group(
                bot,
                group_chat_id,
                text,
                topic_id=topic_id,
                **kwargs,
            )
            return
        except Exception as e:
            last_error = e
            if parse_mode is not None:
                logger.warning(
                    "[tui-bridge] 发送最终回复富文本到 TG 失败，回退 plain text "
                    "thread=%s…: %s",
                    thread_id[:12],
                    e,
                )
                continue
            break

    if last_error is not None:
        raise last_error


def is_codex_tui_control_mode(state: AppState, ws: Optional[WorkspaceInfo] = None) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_name = ws.tool if ws is not None else "codex"
    tool_cfg = cfg.get_tool(tool_name)
    return bool(tool_cfg and tool_cfg.name == "codex" and tool_cfg.control_mode == "tui")


def is_codex_local_owner_mode(state: AppState, ws: Optional[WorkspaceInfo] = None) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_name = ws.tool if ws is not None else "codex"
    tool_cfg = cfg.get_tool(tool_name)
    if not tool_cfg or tool_cfg.name != "codex":
        return False
    return tool_cfg.control_mode == "tui"


def should_auto_manage_codex_host(state: AppState, ws: Optional[WorkspaceInfo] = None) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_name = ws.tool if ws is not None else "codex"
    tool_cfg = cfg.get_tool(tool_name)
    return bool(tool_cfg and tool_cfg.name == "codex" and tool_cfg.control_mode == "app" and tool_cfg.protocol == "ws")


def uses_codex_shared_live_transport(state: AppState, ws: Optional[WorkspaceInfo] = None) -> bool:
    cfg = state.config
    if cfg is None:
        return False
    tool_name = ws.tool if ws is not None else "codex"
    tool_cfg = cfg.get_tool(tool_name)
    if not tool_cfg or tool_cfg.name != "codex":
        return False
    live_transport = str(getattr(tool_cfg, "live_transport", "") or "").strip().lower()
    if live_transport:
        return live_transport == "shared_ws"
    return tool_cfg.protocol == "ws"


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_live_host_status(state: AppState) -> Optional[dict]:
    data_dir = state.config.data_dir if state.config and state.config.data_dir else get_data_dir()
    status = read_host_status(data_dir)
    if not status or not status.get("online"):
        return None
    socket_path = status.get("socket_path")
    pid = status.get("pid")
    if not socket_path or not isinstance(socket_path, str) or not os.path.exists(socket_path):
        return None
    if not _pid_alive(pid):
        return None
    return status


async def ensure_codex_tui_host_bound(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
) -> None:
    if not is_codex_local_owner_mode(state, ws):
        return

    live_status = _read_live_host_status(state)
    current_pid = os.getpid()

    # 外部 host 已在线时，优先尊重现有绑定；手工 TUI 模式不由 bot 抢占。
    if live_status and live_status.get("pid") != current_pid:
        async with codex_state.get_tui_host_lock(state):
            host = codex_state.get_tui_host(state)
            if host is not None:
                await host.stop()
                codex_state.set_tui_host(state, None)
        return

    if not should_auto_manage_codex_host(state, ws):
        return

    tool_cfg = state.config.get_tool("codex") if state.config else None
    if tool_cfg is None:
        raise RuntimeError("codex 未启用，无法启动本地 host")
    data_dir = state.config.data_dir if state.config and state.config.data_dir else get_data_dir()
    if not data_dir:
        raise RuntimeError("缺少 data_dir，无法启动 codex 本地 host")

    async with codex_state.get_tui_host_lock(state):
        host = codex_state.get_tui_host(state)
        if host is not None and host.thread_id == thread_id and host.cwd == ws.path and host.is_running:
            return

        if host is not None:
            await host.stop()
            codex_state.set_tui_host(state, None)

        # 在同一进程内重绑最新 thread，避免继续依赖 shared 4722。
        host = CodexTuiHost(
            data_dir=data_dir,
            thread_id=thread_id,
            cwd=ws.path,
            codex_bin=tool_cfg.codex_bin,
        )
        await host.start()
        codex_state.set_tui_host(state, host)
        logger.info(f"[tui-host] 已启动本地 codex host thread={thread_id[:12]}… cwd={ws.path}")


async def _resolve_codex_ws_url(
    state: AppState,
    tool_cfg: ToolConfig,
) -> tuple[str, Optional[AppServerProcess]]:
    app_server_url = tool_cfg.app_server_url or ""
    if app_server_url:
        return app_server_url, None

    port = tool_cfg.app_server_port or 4722
    ws_url = f"ws://127.0.0.1:{port}"
    readyz_url = f"http://127.0.0.1:{port}/readyz"

    try:
        if await _probe_url(readyz_url):
            return ws_url, None
    except Exception:
        logger.debug("探测现有 codex app-server 失败", exc_info=True)

    if is_codex_tui_control_mode(state):
        raise RuntimeError("codex TUI 模式未检测到 shared app-server，拒绝在 bridge 路径自启第二个实例")

    proc = AppServerProcess(
        codex_bin=tool_cfg.codex_bin,
        port=port,
        protocol="ws",
    )
    await proc.start()
    return ws_url, proc


async def _probe_url(url: str, timeout: float = 1.5) -> bool:
    loop = asyncio.get_event_loop()

    def _probe() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return getattr(resp, "status", 0) == 200
        except urllib.error.HTTPError as e:
            return e.code == 200
        except Exception:
            return False

    return await loop.run_in_executor(None, _probe)


async def with_codex_tui_bridge(
    state: AppState,
    ws: WorkspaceInfo,
    operation,
):
    cfg = state.config
    if cfg is None:
        raise RuntimeError("缺少配置，无法建立 codex bridge")
    tool_cfg = cfg.get_tool("codex")
    if tool_cfg is None:
        raise RuntimeError("codex 未启用，无法建立 bridge")

    ws_url, proc = await _resolve_codex_ws_url(state, tool_cfg)
    adapter = CodexAdapter()
    adapter.register_workspace_cwd(ws.daemon_workspace_id or f"codex:{ws.name}", ws.path)

    try:
        await adapter.connect(ws_url, process=proc._proc if proc else None)
        return await operation(adapter)
    finally:
        try:
            await adapter.disconnect()
        finally:
            if proc is not None:
                await proc.stop()


def get_persistent_codex_adapter(state: AppState) -> Optional[CodexAdapter]:
    """返回可复用的常驻 codex adapter；不可用时返回 None。"""
    adapter = state.get_adapter("codex")
    if adapter is None or not adapter.connected:
        return None
    return adapter


async def send_message_via_tui_host(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    text: str,
) -> dict:
    await ensure_codex_tui_host_bound(state, ws, thread_id)
    topic_id = None
    thread = ws.threads.get(thread_id)
    if thread is not None:
        topic_id = thread.topic_id
    codex_state.mark_send_started(state, thread_id)
    return await send_message_to_codex_tui_host(
        state,
        ws,
        thread_id,
        text,
        topic_id=topic_id,
    )


async def start_thread_via_tui_bridge(state: AppState, ws: WorkspaceInfo) -> str:
    workspace_id = ws.daemon_workspace_id
    if not workspace_id:
        raise RuntimeError("workspace 未关联 daemon ID")

    def _extract_thread_id(result: object) -> str:
        thread_id = result.get("id") if isinstance(result, dict) else None
        if not thread_id and isinstance(result, dict):
            thread = result.get("thread", {})
            if isinstance(thread, dict):
                thread_id = thread.get("id")
        if not thread_id:
            raise RuntimeError(f"start_thread 返回无效结果：{result}")
        return thread_id

    adapter = get_persistent_codex_adapter(state)
    if adapter is not None:
        result = await adapter.start_thread(workspace_id)
        return _extract_thread_id(result)

    async def _op(tmp_adapter: CodexAdapter) -> str:
        result = await tmp_adapter.start_thread(workspace_id)
        return _extract_thread_id(result)

    return await with_codex_tui_bridge(state, ws, _op)


async def archive_codex_thread_via_tui_bridge(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
) -> dict:
    workspace_id = ws.daemon_workspace_id
    if not workspace_id:
        raise RuntimeError("workspace 未关联 daemon ID")

    adapter = get_persistent_codex_adapter(state)
    if adapter is not None:
        return await adapter.archive_thread(workspace_id, thread_id)

    async def _op(tmp_adapter: CodexAdapter) -> dict:
        return await tmp_adapter.archive_thread(workspace_id, thread_id)

    return await with_codex_tui_bridge(state, ws, _op)


async def send_message_via_tui_bridge(
    state: AppState,
    ws: WorkspaceInfo,
    thread_id: str,
    text: str,
) -> int:
    history_before = read_thread_history(thread_id, limit=50)
    baseline_assistant_len = len([item for item in history_before if _is_final_answer(item)])
    seed_codex_watch_baseline(state, ws, thread_id)
    await send_message_via_tui_host(state, ws, thread_id, text)
    watch_codex_thread(state, ws, thread_id)
    return baseline_assistant_len


async def enqueue_codex_tui_message(
    state: AppState,
    ws: WorkspaceInfo,
    bot,
    group_chat_id: int,
    topic_id: int,
    thread_id: str,
    text: str,
) -> int:
    """按 thread 串行发送 TG 消息到 codex TUI 主控链路。"""
    lock = codex_state.get_runtime(state).thread_locks.setdefault(thread_id, asyncio.Lock())
    async with lock:
        await codex_state.get_tui_thread_idle_event(state, thread_id).wait()
        baseline_len = await send_message_via_tui_bridge(state, ws, thread_id, text)
        schedule_codex_final_reply(
            state,
            bot,
            group_chat_id,
            topic_id,
            thread_id,
            baseline_len=baseline_len,
        )
        return baseline_len


def schedule_codex_final_reply(
    state: AppState,
    bot,
    group_chat_id: int,
    topic_id: int,
    thread_id: str,
    *,
    baseline_len: int,
    poll_interval: float = 2.0,
    max_wait_seconds: float = 600.0,
) -> asyncio.Task:
    async def _worker() -> None:
        deadline = asyncio.get_event_loop().time() + max_wait_seconds
        seen_assistant = baseline_len

        while asyncio.get_event_loop().time() < deadline:
            try:
                history = read_thread_history(thread_id, limit=50)
            except Exception as e:
                logger.debug(f"[tui-bridge] 读取 thread 历史失败 thread={thread_id[:12]}…: {e}")
                history = []

            final_turns = [item for item in history if _is_final_answer(item)]
            if len(final_turns) > seen_assistant:
                latest_item = final_turns[-1]
                latest = (latest_item.get("text") or "").strip()
                if latest:
                    latest_signature = _final_reply_signature(latest_item)
                    if _is_reply_already_synced(state, thread_id, latest_item):
                        return
                    try:
                        await _send_formatted_final_reply_to_group(
                            bot,
                            group_chat_id,
                            topic_id,
                            thread_id,
                            latest,
                        )
                        codex_state.get_runtime(state).last_synced_assistant[thread_id] = latest_signature
                    except Exception as e:
                        logger.warning(
                            f"[tui-bridge] 发送最终回复到 TG 失败 thread={thread_id[:12]}…: {e}"
                        )
                    return

            await asyncio.sleep(poll_interval)

        logger.info(f"[tui-bridge] 最终回复轮询超时 thread={thread_id[:12]}…")

    return asyncio.create_task(_worker(), name=f"codex-final-reply:{thread_id[:8]}")


async def sync_codex_tui_final_replies_once(
    state: AppState,
    bot,
    group_chat_id: int,
) -> None:
    """扫描 codex thread 的本地历史，将最新 assistant 完整回复同步到对应 TG topic。"""
    storage = state.storage
    if storage is None:
        return

    for ws in storage.workspaces.values():
        if ws.tool != "codex":
            continue
        if ws.archived if hasattr(ws, "archived") else False:
            continue

        active_ids: Optional[set[str]] = None
        for thread_id, thread in ws.threads.items():
            if thread.archived:
                _, active_ids = _revive_stale_archived_thread_if_active(
                    state,
                    ws,
                    thread_id,
                    thread,
                    active_ids=active_ids,
                )
            topic_id = thread.topic_id
            if thread.archived or topic_id is None:
                continue

            try:
                history = read_thread_history(thread_id, limit=50)
            except Exception as e:
                logger.debug(f"[tui-bridge] 读取 codex thread 历史失败 thread={thread_id[:12]}…: {e}")
                continue

            latest_item = _latest_final_answer(history)
            if latest_item is None:
                continue

            latest = (latest_item.get("text") or "").strip()
            if not latest:
                continue

            last_synced = codex_state.get_runtime(state).last_synced_assistant.get(thread_id)
            latest_signature = _final_reply_signature(latest_item)
            if _is_reply_already_synced(state, thread_id, latest_item):
                continue

            try:
                await _send_formatted_final_reply_to_group(
                    bot,
                    group_chat_id,
                    topic_id,
                    thread_id,
                    latest,
                )
                codex_state.get_runtime(state).last_synced_assistant[thread_id] = latest_signature
                run = codex_state.get_current_run(state, thread_id)
                item_turn_id = _final_reply_turn_id(latest_item)
                if run is not None and item_turn_id and item_turn_id == run.turn_id:
                    codex_state.mark_run(
                        state,
                        thread_id=thread_id,
                        final_reply_synced_to_tg=True,
                    )
                logger.info(f"[tui-bridge] 已同步 codex 最终回复到 TG thread={thread_id[:12]}… topic={topic_id}")
            except Exception as e:
                logger.warning(f"[tui-bridge] 同步 codex 最终回复到 TG 失败 thread={thread_id[:12]}…: {e}")


async def prime_codex_tui_reply_state(state: AppState) -> None:
    """启动轮询前先记录当前已存在的 final_answer，避免重启后把旧结果重放到 TG。"""
    storage = state.storage
    if storage is None:
        return

    for ws in storage.workspaces.values():
        if ws.tool != "codex":
            continue
        if ws.archived if hasattr(ws, "archived") else False:
            continue

        active_ids: Optional[set[str]] = None
        for thread_id, thread in ws.threads.items():
            if thread.archived:
                _, active_ids = _revive_stale_archived_thread_if_active(
                    state,
                    ws,
                    thread_id,
                    thread,
                    active_ids=active_ids,
                )
            topic_id = thread.topic_id
            if thread.archived or topic_id is None:
                continue

            try:
                history = read_thread_history(thread_id, limit=50)
            except Exception as e:
                logger.debug(f"[tui-bridge] 预热 codex thread 历史失败 thread={thread_id[:12]}…: {e}")
                continue

            latest_item = _latest_final_answer(history)
            if latest_item is None:
                continue

            codex_state.get_runtime(state).last_synced_assistant[thread_id] = _final_reply_signature(latest_item)


def start_codex_tui_sync_loop(
    state: AppState,
    bot,
    group_chat_id: int,
    *,
    poll_interval: float = 3.0,
) -> asyncio.Task:
    """启动 codex TUI 主控模式的后台最终回复同步循环。"""

    async def _worker() -> None:
        await prime_codex_tui_reply_state(state)
        while True:
            try:
                await sync_codex_tui_final_replies_once(state, bot, group_chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[tui-bridge] codex 最终回复同步循环异常：{e}")
            await asyncio.sleep(poll_interval)

    return asyncio.create_task(_worker(), name="codex-tui-sync-loop")
