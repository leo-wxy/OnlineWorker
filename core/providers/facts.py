from __future__ import annotations

from typing import Optional

from core.providers.registry import classify_provider, get_provider, provider_not_enabled_message


def _require_provider(tool_name: str, *, config=None):
    if config is None:
        provider = get_provider(tool_name)
        if provider is None:
            raise ValueError(provider_not_enabled_message(tool_name, "unknown_provider"))
        return provider

    classification = classify_provider(tool_name, config)
    if classification not in {"available", "hidden_provider"}:
        raise ValueError(provider_not_enabled_message(tool_name, classification))
    provider = get_provider(tool_name, config)
    if provider is None:
        raise ValueError(provider_not_enabled_message(tool_name, "unknown_provider"))
    return provider


def scan_provider_workspaces(tool_name: str, *, sessions_dir: Optional[str] = None, config=None):
    provider = _require_provider(tool_name, config=config)
    return provider.facts.scan_workspaces(sessions_dir=sessions_dir)


def list_provider_threads(tool_name: str, workspace_path: str, *, limit: int = 20, config=None):
    provider = _require_provider(tool_name, config=config)
    return provider.facts.list_threads(workspace_path, limit=limit)


def read_provider_thread_history(
    tool_name: str,
    thread_id: str,
    *,
    limit: int = 10,
    sessions_dir: Optional[str] = None,
    config=None,
):
    provider = _require_provider(tool_name, config=config)
    return provider.facts.read_thread_history(
        thread_id,
        limit=limit,
        sessions_dir=sessions_dir,
    )


def query_provider_active_thread_ids(tool_name: str, workspace_path: str, *, config=None):
    provider = _require_provider(tool_name, config=config)
    return provider.facts.query_active_thread_ids(workspace_path)
