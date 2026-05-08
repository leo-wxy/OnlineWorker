from __future__ import annotations


def default_normalize_server_threads(server_threads: list[dict], *, limit: int) -> list[dict]:
    main_threads = [t for t in server_threads if not t.get("ephemeral", False)]
    main_threads.sort(key=lambda t: t.get("updatedAt", 0), reverse=True)
    return main_threads[:limit]
