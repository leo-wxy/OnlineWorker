from __future__ import annotations


def extract_started_thread_id(result: object) -> str:
    thread_id = result.get("id") if isinstance(result, dict) else None
    if not thread_id and isinstance(result, dict):
        thread = result.get("thread", {})
        if isinstance(thread, dict):
            thread_id = thread.get("id")
    return str(thread_id or "").strip()
