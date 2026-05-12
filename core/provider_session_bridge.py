from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from core.providers.overlay import iter_overlay_manifest_paths, load_manifest


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
    preview = thread.get("preview") or thread.get("title") or thread.get("name")
    title = str(preview or "").strip()
    return title or thread_id


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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


def _workspace_id(provider_id: str, workspace_path: str) -> str:
    normalized_provider_id = str(provider_id or "").strip()
    normalized_workspace = str(workspace_path or "").strip()
    return f"{normalized_provider_id}:{normalized_workspace}"


async def _provider_session_adapter(descriptor, provider_id: str):
    metadata = getattr(descriptor, "metadata", None)
    bin_value = ""
    app_server_port = 0
    transport_kind = ""
    owner_transport = ""
    live_transport = ""
    if metadata is not None:
        bin_value = str(getattr(metadata, "bin", "") or "").strip()
        owner_transport = str(getattr(metadata, "owner_transport", "") or "").strip()
        live_transport = str(getattr(metadata, "live_transport", "") or "").strip()
        transport = getattr(metadata, "transport", None)
        if transport is not None:
            app_server_port = int(getattr(transport, "app_server_port", 0) or 0)
            transport_kind = str(getattr(transport, "type", "") or "").strip()

    runtime_hooks = getattr(descriptor, "runtime_hooks", None)
    if not callable(getattr(runtime_hooks, "start", None)):
        raise ValueError(f"Provider '{provider_id}' does not expose runtime start hooks")

    class _State:
        def __init__(self):
            self.adapters: dict[str, Any] = {}

        def set_adapter(self, tool_name: str, adapter_obj) -> None:
            if adapter_obj is None:
                self.adapters.pop(tool_name, None)
            else:
                self.adapters[tool_name] = adapter_obj

        def get_adapter(self, tool_name: str):
            return self.adapters.get(tool_name)

    class _Manager:
        def __init__(self):
            self.state = _State()
            self.storage = type("Storage", (), {"workspaces": {}})()
            self.gid = 0

    tool_cfg = type(
        "ToolCfg",
        (),
        {
            "name": provider_id,
            "codex_bin": bin_value or provider_id,
            "app_server_port": app_server_port,
            "protocol": transport_kind,
            "owner_transport": owner_transport or transport_kind,
            "live_transport": live_transport or transport_kind,
        },
    )()
    manager = _Manager()
    await runtime_hooks.start(manager, bot=None, tool_cfg=tool_cfg)
    active_adapter = manager.state.get_adapter(provider_id)
    if active_adapter is None:
        raise RuntimeError(f"Provider '{provider_id}' runtime did not register adapter")
    return active_adapter


def list_provider_session_rows(
    provider_id: str,
    *,
    limit_per_workspace: int = 100,
) -> list[dict[str, Any]]:
    facts = _provider_facts(provider_id)
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
                    "workspace": workspace_path,
                    "archived": archived,
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
    sessions_dir: str | None = None,
) -> list[dict[str, str]]:
    facts = _provider_facts(provider_id)
    turns = facts.read_thread_history(session_id, limit=limit, sessions_dir=sessions_dir)

    normalized: list[dict[str, str]] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(turn.get("content") or turn.get("text") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


async def send_provider_session_message(
    provider_id: str,
    session_id: str,
    text: str,
    *,
    workspace_dir: str | None = None,
) -> None:
    descriptor = _load_provider_descriptor(provider_id)
    message_hooks = getattr(descriptor, "message_hooks", None)
    if message_hooks is None or not callable(getattr(message_hooks, "send", None)):
        raise ValueError(f"Provider '{provider_id}' does not expose send hooks")

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise ValueError("session_id is required")

    trimmed_text = str(text or "").strip()
    if not trimmed_text:
        raise ValueError("text is required")

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

    await message_hooks.send(
        state=None,
        adapter=adapter,
        ws_info=ws_info,
        thread_info=thread_info,
        update=None,
        context=None,
        group_chat_id=0,
        src_topic_id=None,
        text=trimmed_text,
        has_photo=False,
    )
