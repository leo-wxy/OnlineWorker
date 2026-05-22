from __future__ import annotations

from core.providers.registry import get_provider


def provider_allows_unbound_thread_topic_materialization(
    state,
    ws_info,
    thread_info,
) -> bool:
    """Return whether a provider allows auto-creating a TG topic for this thread."""
    provider_id = str(getattr(ws_info, "tool", "") or "")
    provider = get_provider(provider_id, getattr(state, "config", None))
    if provider is None:
        provider = get_provider(provider_id)
    hooks = getattr(provider, "session_event_hooks", None) if provider is not None else None
    policy = (
        getattr(hooks, "should_materialize_unbound_thread_topic", None)
        if hooks is not None
        else None
    )
    if not callable(policy):
        return True
    return bool(policy(state, ws_info, thread_info))
