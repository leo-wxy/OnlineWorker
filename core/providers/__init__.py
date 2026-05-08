from __future__ import annotations

__all__ = [
    "ProviderDescriptor",
    "get_provider",
    "list_providers",
    "list_provider_threads",
    "query_provider_active_thread_ids",
    "read_provider_thread_history",
    "scan_provider_workspaces",
]


def __getattr__(name: str):
    if name in {"list_provider_threads", "query_provider_active_thread_ids", "read_provider_thread_history", "scan_provider_workspaces"}:
        from .facts import (
            list_provider_threads,
            query_provider_active_thread_ids,
            read_provider_thread_history,
            scan_provider_workspaces,
        )

        return {
            "list_provider_threads": list_provider_threads,
            "query_provider_active_thread_ids": query_provider_active_thread_ids,
            "read_provider_thread_history": read_provider_thread_history,
            "scan_provider_workspaces": scan_provider_workspaces,
        }[name]
    if name in {"ProviderDescriptor", "get_provider", "list_providers"}:
        from .registry import ProviderDescriptor, get_provider, list_providers

        return {
            "ProviderDescriptor": ProviderDescriptor,
            "get_provider": get_provider,
            "list_providers": list_providers,
        }[name]
    raise AttributeError(name)
