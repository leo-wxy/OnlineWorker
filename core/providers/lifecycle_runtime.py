from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _save_storage_via_lifecycle(manager) -> None:
    from core import lifecycle as lifecycle_module

    lifecycle_module.save_storage(manager.storage)


def _sync_provider_threads_from_facts(
    manager,
    provider_name: str,
    ws_info,
    *,
    limit: int,
    log_prefix: str,
    source_for_new: str = "unknown",
) -> bool:
    from core.providers.facts import list_provider_threads
    from core.storage import ThreadInfo

    needs_save = False
    local_threads = list_provider_threads(provider_name, ws_info.path, limit=limit)
    for dt in local_threads:
        tid = dt.get("id", "")
        if not tid or tid in ws_info.threads:
            continue
        preview = dt.get("preview") or None
        ws_info.threads[tid] = ThreadInfo(
            thread_id=tid,
            topic_id=None,
            preview=preview,
            archived=False,
            source=source_for_new,
        )
        needs_save = True
        logger.info("%s 补同步 thread %s… preview=%s", log_prefix, tid[:12], preview)
    return needs_save


def resolve_default_reconnect_topic_id(manager, provider_name: str):
    return manager.state.get_global_topic_id(provider_name)
