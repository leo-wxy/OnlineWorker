from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from config import get_data_dir, load_config, load_provider_runtime_config
from core.providers.overlay import iter_overlay_manifest_paths, load_manifest
from core.providers.registry import get_provider
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from core.user_messages.contracts import UserMessageSendRequest
from core.user_messages.gateway import prepare_user_message_text


def _workspace_path(workspace: Any) -> str:
    if not isinstance(workspace, dict):
        return ""
    raw = workspace.get("path") or workspace.get("workspace") or workspace.get("cwd") or ""
    return str(raw).strip()


def _thread_id(thread: Any) -> str:
    if not isinstance(thread, dict):
        return ""
    return str(thread.get("id") or thread.get("thread_id") or "").strip()


def _thread_title(thread: dict[str, Any], thread_id: str) -> str:
    preview = thread.get("title") or thread.get("name") or thread.get("preview")
    title = str(preview or "").strip()
    return title or thread_id


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(primary: Any, fallback: Any) -> Any:
    return primary if primary is not None else fallback


def _unix_time_seconds() -> int:
    return int(time.time())


def _normalize_usage_day(day: Any) -> dict[str, Any] | None:
    if not isinstance(day, dict):
        return None
    date = str(day.get("date") or "").strip()
    if not date:
        return None

    return {
        "date": date,
        "inputTokens": _int_value(
            _first_present(day.get("inputTokens"), day.get("input_tokens"))
        ),
        "outputTokens": _int_value(
            _first_present(day.get("outputTokens"), day.get("output_tokens"))
        ),
        "cacheCreationTokens": _int_value(
            _first_present(
                _first_present(day.get("cacheCreationTokens"), day.get("cache_creation_tokens")),
                _first_present(
                    day.get("cacheCreationInputTokens"),
                    day.get("cache_creation_input_tokens"),
                ),
            )
        ),
        "cacheReadTokens": _int_value(
            _first_present(
                _first_present(day.get("cacheReadTokens"), day.get("cache_read_tokens")),
                _first_present(day.get("cacheReadInputTokens"), day.get("cache_read_input_tokens")),
            )
        ),
        "totalTokens": _int_value(
            _first_present(day.get("totalTokens"), day.get("total_tokens"))
        ),
        "totalCostUsd": _float_or_none(
            _first_present(day.get("totalCostUsd"), day.get("total_cost_usd"))
        ),
    }


def _normalize_usage_summary(provider_id: str, raw_summary: Any) -> dict[str, Any]:
    raw = raw_summary if isinstance(raw_summary, dict) else {}
    days = [
        normalized
        for normalized in (
            _normalize_usage_day(day)
            for day in (raw.get("days") if isinstance(raw.get("days"), list) else [])
        )
        if normalized is not None
    ]
    days.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return {
        "providerId": str(raw.get("providerId") or raw.get("provider_id") or provider_id),
        "days": days,
        "updatedAtEpoch": _int_value(
            _first_present(raw.get("updatedAtEpoch"), raw.get("updated_at_epoch"))
            if _first_present(raw.get("updatedAtEpoch"), raw.get("updated_at_epoch")) is not None
            else _unix_time_seconds()
        ),
        "unsupportedReason": raw.get("unsupportedReason") or raw.get("unsupported_reason"),
    }


def _normalize_provider_turn_content(turn: dict[str, Any]) -> str:
    content = str(turn.get("content") or turn.get("text") or "").strip()
    if content:
        return content
    if str(turn.get("kind") or "").strip() == "error":
        return str(turn.get("error") or "").strip()
    return ""


def _normalize_provider_turn(turn: dict[str, Any]) -> dict[str, str]:
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
    if kind:
        normalized["kind"] = kind

    return normalized


def _builtin_manifest_paths() -> list[Path]:
    plugin_root = Path(__file__).resolve().parents[2] / "plugins" / "providers" / "builtin"
    if not plugin_root.exists():
        return []
    return sorted(plugin_root.glob("*/plugin.yaml"))


def _iter_manifest_paths() -> list[Path]:
    return [*_builtin_manifest_paths(), *iter_overlay_manifest_paths()]


def _ensure_manifest_import_path(manifest_path: Path) -> None:
    overlay_root = manifest_path.parent.parent
    overlay_root_str = str(overlay_root)
    if overlay_root_str not in sys.path:
        sys.path.insert(0, overlay_root_str)


def _load_provider_descriptor(provider_id: str):
    normalized_provider_id = str(provider_id or "").strip()
    if not normalized_provider_id:
        raise ValueError("provider_id is required")

    registry_descriptor = get_provider(normalized_provider_id)
    if registry_descriptor is not None:
        return registry_descriptor

    for manifest_path in _iter_manifest_paths():
        manifest = load_manifest(manifest_path)
        manifest_id = str(manifest.get("id") or "").strip()
        if manifest_id != normalized_provider_id:
            continue
        entrypoint = str((manifest.get("entrypoints") or {}).get("python_descriptor") or "").strip()
        module_name, separator, factory_name = entrypoint.partition(":")
        if not separator or not module_name or not factory_name:
            raise ValueError(
                f"Provider plugin entrypoint must use module:function syntax: {entrypoint}"
            )
        _ensure_manifest_import_path(manifest_path)
        module = importlib.import_module(module_name)
        factory = getattr(module, factory_name)
        return factory()

    raise ValueError(f"Provider '{normalized_provider_id}' manifest not found")


def _provider_facts(provider_id: str):
    descriptor = _load_provider_descriptor(provider_id)
    facts = getattr(descriptor, "facts", None)
    if facts is None:
        raise ValueError(f"Provider '{provider_id}' does not expose facts hooks")
    return facts


async def _invoke_message_hook_send(send_hook, *, adapter, ws_info, thread_info, text, attachments):
    underlying = getattr(send_hook, "__func__", None)
    if underlying is not None:
        await underlying(
            None,
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
        return

    await send_hook(
        None,
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


async def _invoke_thread_archive(archive_hook, *, state, adapter, ws_info, thread_id: str):
    underlying = getattr(archive_hook, "__func__", None)
    if underlying is not None:
        await underlying(state, ws_info, thread_id, adapter)
        return
    await archive_hook(state, ws_info, thread_id, adapter)


def _workspace_id(provider_id: str, workspace_path: str) -> str:
    normalized_provider_id = str(provider_id or "").strip()
    normalized_workspace = str(workspace_path or "").strip()
    return f"{normalized_provider_id}:{normalized_workspace}"


def _message_gateway_state():
    try:
        data_dir = get_data_dir()
        config = load_config(data_dir=data_dir) if data_dir else load_config()
    except Exception:
        return None
    return SimpleNamespace(config=config)


def _metadata_tool_cfg(descriptor, provider_id: str):
    metadata = getattr(descriptor, "metadata", None)
    bin_value = ""
    app_server_port = 0
    app_server_url = ""
    transport_kind = ""
    owner_transport = ""
    live_transport = ""
    control_mode = "app"
    if metadata is not None:
        bin_value = str(getattr(metadata, "bin", "") or "").strip()
        owner_transport = str(getattr(metadata, "owner_transport", "") or "").strip()
        live_transport = str(getattr(metadata, "live_transport", "") or "").strip()
        control_mode = str(getattr(metadata, "control_mode", "") or "").strip() or "app"
        transport = getattr(metadata, "transport", None)
        if transport is not None:
            app_server_port = int(getattr(transport, "app_server_port", 0) or 0)
            app_server_url = str(getattr(transport, "app_server_url", "") or "").strip()
            transport_kind = str(getattr(transport, "type", "") or "").strip()

    return SimpleNamespace(
        name=provider_id,
        bin=bin_value or provider_id,
        auth={},
        external_cli={},
        launch_methods=[],
        app_server_port=app_server_port,
        app_server_url=app_server_url,
        protocol=transport_kind,
        owner_transport=owner_transport or transport_kind,
        live_transport=live_transport or transport_kind,
        control_mode=control_mode,
    )


def _runtime_config_and_tool_cfg(descriptor, provider_id: str):
    data_dir = get_data_dir()
    try:
        config = load_provider_runtime_config(provider_id, data_dir=data_dir)
    except FileNotFoundError:
        config = SimpleNamespace(data_dir=data_dir)

    if not hasattr(config, "data_dir"):
        config.data_dir = data_dir

    get_provider_config = getattr(config, "get_provider", None)
    configured_tool = get_provider_config(provider_id) if callable(get_provider_config) else None
    if configured_tool is None:
        get_tool = getattr(config, "get_tool", None)
        configured_tool = get_tool(provider_id) if callable(get_tool) else None
    if configured_tool is not None:
        return config, configured_tool

    return config, _metadata_tool_cfg(descriptor, provider_id)


def _attach_adapter_registry(state, *, adapters: dict[str, Any] | None = None):
    state.adapters = dict(adapters or {})

    def get_adapter(tool_name: str):
        return state.adapters.get(tool_name)

    def set_adapter(tool_name: str, adapter_obj) -> None:
        if adapter_obj is None:
            state.adapters.pop(tool_name, None)
        else:
            state.adapters[tool_name] = adapter_obj

    state.get_adapter = get_adapter
    state.set_adapter = set_adapter
    return state


def _build_runtime_manager_stub(config):
    state = _attach_adapter_registry(
        SimpleNamespace(
            config=config,
            app_server_proc=None,
        )
    )
    manager = SimpleNamespace(
        state=state,
        storage=AppStorage(workspaces={}),
        gid=0,
        _tui_sync_tasks={},
        _tui_mirror_tasks={},
        _reconnect_tasks={},
        _reconnect_inflight={},
        _stale_recovery_tasks={},
    )

    def _set_task(tasks: dict[str, Any], provider: str, task) -> None:
        if task is None:
            tasks.pop(provider, None)
        else:
            tasks[provider] = task

    manager.get_tui_sync_task = lambda provider: manager._tui_sync_tasks.get(provider)
    manager.set_tui_sync_task = lambda provider, task: _set_task(manager._tui_sync_tasks, provider, task)
    manager.get_tui_mirror_task = lambda provider: manager._tui_mirror_tasks.get(provider)
    manager.set_tui_mirror_task = lambda provider, task: _set_task(manager._tui_mirror_tasks, provider, task)
    manager.get_reconnect_task = lambda provider: manager._reconnect_tasks.get(provider)
    manager.set_reconnect_task = lambda provider, task: _set_task(manager._reconnect_tasks, provider, task)
    manager.get_reconnect_inflight = lambda provider: bool(manager._reconnect_inflight.get(provider, False))
    manager.is_reconnect_inflight = manager.get_reconnect_inflight

    def set_reconnect_inflight(provider: str, value: bool) -> None:
        if value:
            manager._reconnect_inflight[provider] = True
        else:
            manager._reconnect_inflight.pop(provider, None)

    manager.set_reconnect_inflight = set_reconnect_inflight
    manager.get_stale_recovery_tasks = lambda provider: manager._stale_recovery_tasks.setdefault(provider, {})
    return manager


async def _provider_session_adapter(descriptor, provider_id: str):
    runtime_hooks = getattr(descriptor, "runtime_hooks", None)
    if not callable(getattr(runtime_hooks, "start", None)):
        raise ValueError(f"Provider '{provider_id}' does not expose runtime start hooks")
    config, tool_cfg = _runtime_config_and_tool_cfg(descriptor, provider_id)

    manager = _build_runtime_manager_stub(config)
    await runtime_hooks.start(manager, bot=None, tool_cfg=tool_cfg)
    active_adapter = manager.state.get_adapter(provider_id)
    if active_adapter is None:
        raise RuntimeError(f"Provider '{provider_id}' runtime did not register adapter")
    return active_adapter


def _workspace_path_for_session(provider_id: str, session_id: str, workspace_dir: str | None) -> str:
    workspace_path = str(workspace_dir or "").strip()
    if workspace_path:
        return workspace_path

    normalized_session_id = str(session_id or "").strip()
    for session in list_provider_session_rows(provider_id):
        if str(session.get("id") or "").strip() == normalized_session_id:
            workspace_path = str(session.get("workspace") or "").strip()
            if workspace_path:
                return workspace_path
    raise ValueError(f"workspace_dir is required for provider '{provider_id}' session archive")


def _bridge_state_for_archive(provider_id: str, session_id: str, workspace_path: str, adapter):
    workspace_id = _workspace_id(provider_id, workspace_path)
    thread_info = ThreadInfo(
        thread_id=session_id,
        topic_id=None,
        preview=None,
        archived=False,
        is_active=True,
        source="app",
    )
    ws_info = WorkspaceInfo(
        name=Path(workspace_path).name or workspace_path,
        path=workspace_path,
        tool=provider_id,
        topic_id=None,
        daemon_workspace_id=workspace_id,
        threads={session_id: thread_info},
    )
    gateway_state = _message_gateway_state()
    state = _attach_adapter_registry(
        SimpleNamespace(
            config=gateway_state.config if gateway_state is not None else None,
            storage=AppStorage(workspaces={workspace_id: ws_info}),
        ),
        adapters={provider_id: adapter} if adapter is not None else {},
    )
    return state, ws_info


def list_provider_session_rows(
    provider_id: str,
    *,
    limit_per_workspace: int = 100,
) -> list[dict[str, Any]]:
    facts = _provider_facts(provider_id)
    list_sessions = getattr(facts, "list_sessions", None)
    if callable(list_sessions):
        sessions: list[dict[str, Any]] = []
        for session in list_sessions(limit=limit_per_workspace) or []:
            if not isinstance(session, dict):
                continue
            thread_id = _thread_id(session)
            workspace_path = str(session.get("workspace") or session.get("path") or "").strip()
            if not thread_id or not workspace_path:
                continue
            sessions.append(
                {
                    "id": thread_id,
                    "title": _thread_title(session, thread_id),
                    "preview": str(session.get("preview") or "").strip(),
                    "workspace": workspace_path,
                    "archived": bool(session.get("archived", False)),
                    "providerActive": bool(session.get("providerActive", False)),
                    "updatedAt": _int_value(
                        session.get("updatedAt")
                        or session.get("updated_at")
                        or session.get("updated_at_epoch")
                        or session.get("createdAt")
                        or session.get("created_at")
                    ),
                    "createdAt": _int_value(
                        session.get("createdAt")
                        or session.get("created_at")
                        or session.get("updatedAt")
                        or session.get("updated_at")
                    ),
                }
            )
        sessions.sort(
            key=lambda item: (
                -_int_value(item.get("updatedAt")),
                -_int_value(item.get("createdAt")),
                str(item.get("id") or ""),
            )
        )
        return sessions

    sessions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for workspace in facts.scan_workspaces() or []:
        workspace_path = _workspace_path(workspace)
        if not workspace_path:
            continue

        try:
            active_ids = facts.query_active_thread_ids(workspace_path)
        except Exception:
            active_ids = set()
        normalized_active_ids = {str(item).strip() for item in active_ids if str(item).strip()}

        threads = facts.list_threads(workspace_path, limit=limit_per_workspace) or []
        for thread in threads:
            if not isinstance(thread, dict):
                continue
            thread_id = _thread_id(thread)
            if not thread_id:
                continue

            dedupe_key = (workspace_path, thread_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            archived = bool(thread.get("archived", False))
            if normalized_active_ids:
                archived = archived or thread_id not in normalized_active_ids

            sessions.append(
                {
                    "id": thread_id,
                    "title": _thread_title(thread, thread_id),
                    "preview": str(thread.get("preview") or "").strip(),
                    "workspace": workspace_path,
                    "archived": archived,
                    "providerActive": thread_id in normalized_active_ids,
                    "updatedAt": _int_value(
                        thread.get("updatedAt")
                        or thread.get("updated_at")
                        or thread.get("updated_at_epoch")
                        or thread.get("createdAt")
                        or thread.get("created_at")
                    ),
                    "createdAt": _int_value(
                        thread.get("createdAt")
                        or thread.get("created_at")
                        or thread.get("updatedAt")
                        or thread.get("updated_at")
                    ),
                }
            )

    sessions.sort(
        key=lambda item: (
            -_int_value(item.get("updatedAt")),
            -_int_value(item.get("createdAt")),
            str(item.get("id") or ""),
        )
    )
    return sessions


def read_provider_session_rows(
    provider_id: str,
    session_id: str,
    *,
    limit: int = 20,
    workspace_dir: str | None = None,
    sessions_dir: str | None = None,
) -> list[dict[str, str]]:
    _ = workspace_dir
    facts = _provider_facts(provider_id)
    turns = facts.read_thread_history(session_id, limit=limit, sessions_dir=sessions_dir)

    normalized: list[dict[str, str]] = []
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
    return normalized


def get_provider_usage_summary(
    provider_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    descriptor = _load_provider_descriptor(provider_id)
    usage_hooks = getattr(descriptor, "usage_hooks", None)
    get_summary = getattr(usage_hooks, "get_summary", None)
    if not callable(get_summary):
        raise ValueError(f"Provider '{provider_id}' does not expose usage hooks")

    raw_summary = get_summary(
        str(start_date or "").strip(),
        str(end_date or "").strip(),
    )
    return _normalize_usage_summary(provider_id, raw_summary)


async def send_provider_session_message(
    provider_id: str,
    session_id: str,
    text: str,
    *,
    workspace_dir: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    descriptor = _load_provider_descriptor(provider_id)
    message_hooks = getattr(descriptor, "message_hooks", None)
    if message_hooks is None or not callable(getattr(message_hooks, "send", None)):
        raise ValueError(f"Provider '{provider_id}' does not expose send hooks")

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")

    trimmed_text = str(text or "").strip()
    normalized_attachments = attachments or []
    if not trimmed_text and not normalized_attachments:
        raise ValueError("text or attachments is required")

    workspace_path = str(workspace_dir or "").strip()
    if not workspace_path:
        for session in list_provider_session_rows(provider_id):
            if str(session.get("id") or "").strip() == normalized_session_id:
                workspace_path = str(session.get("workspace") or "").strip()
                break
    if not workspace_path:
        raise ValueError(f"workspace_dir is required for provider '{provider_id}' send")

    adapter = await _provider_session_adapter(descriptor, provider_id)
    ws_info = {
        "tool": provider_id,
        "path": workspace_path,
        "daemon_workspace_id": _workspace_id(provider_id, workspace_path),
    }
    thread_info = {
        "thread_id": normalized_session_id,
    }
    gateway_result = await prepare_user_message_text(
        _message_gateway_state(),
        UserMessageSendRequest(
            source="provider_session_bridge",
            provider_id=provider_id,
            workspace_id=ws_info["daemon_workspace_id"],
            thread_id=normalized_session_id,
            text=trimmed_text,
            attachments=normalized_attachments,
        ),
    )
    trimmed_text = gateway_result.text

    await _invoke_message_hook_send(
        message_hooks.send,
        adapter=adapter,
        ws_info=ws_info,
        thread_info=thread_info,
        text=trimmed_text,
        attachments=normalized_attachments,
    )


async def archive_provider_session(
    provider_id: str,
    session_id: str,
    *,
    workspace_dir: str | None = None,
) -> None:
    descriptor = _load_provider_descriptor(provider_id)
    thread_hooks = getattr(descriptor, "thread_hooks", None)
    archive_thread = getattr(thread_hooks, "archive_thread", None) if thread_hooks is not None else None
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")

    workspace_path = _workspace_path_for_session(provider_id, normalized_session_id, workspace_dir)
    adapter = await _provider_session_adapter(descriptor, provider_id)
    state, ws_info = _bridge_state_for_archive(
        provider_id,
        normalized_session_id,
        workspace_path,
        adapter,
    )
    if callable(archive_thread):
        await _invoke_thread_archive(
            archive_thread,
            state=state,
            adapter=adapter,
            ws_info=ws_info,
            thread_id=normalized_session_id,
        )
        return

    adapter_archive = getattr(adapter, "archive_thread", None)
    if not callable(adapter_archive):
        raise ValueError(f"Provider '{provider_id}' does not expose real archive support")
    await adapter_archive(ws_info.daemon_workspace_id, normalized_session_id)
