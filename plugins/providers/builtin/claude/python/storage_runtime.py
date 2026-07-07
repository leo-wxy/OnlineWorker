from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CLAUDE_SESSIONS_DIR = "~/.claude/sessions"
CLAUDE_PROJECTS_DIR = "~/.claude/projects"
CLAUDE_HISTORY_PATH = "~/.claude/history.jsonl"
_CLAUDE_STORAGE_CACHE: dict[str, object] = {
    "key": None,
    "signature": None,
    "sessions": [],
    "history": {},
}
_CLAUDE_THREAD_SNAPSHOT_CACHE: dict[str, object] = {
    "key": None,
    "signature": None,
    "snapshot": None,
}


def clear_claude_storage_cache() -> None:
    _CLAUDE_STORAGE_CACHE.update(
        {
            "key": None,
            "signature": None,
            "sessions": [],
            "history": {},
        }
    )
    _CLAUDE_THREAD_SNAPSHOT_CACHE.update(
        {
            "key": None,
            "signature": None,
            "snapshot": None,
        }
    )


def _default_claude_storage_cache_key() -> tuple[str, str, str]:
    return (
        os.path.expanduser(CLAUDE_SESSIONS_DIR),
        os.path.expanduser(CLAUDE_PROJECTS_DIR),
        os.path.expanduser(CLAUDE_HISTORY_PATH),
    )


def _claude_path_signature(path: str) -> tuple[int, int]:
    try:
        stat = os.stat(path)
    except OSError:
        return (0, 0)
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _claude_tree_signature(root: str, suffixes: tuple[str, ...]) -> tuple:
    if not os.path.isdir(root):
        return ()

    entries: list[tuple[str, int, int]] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "subagents")
        for fname in sorted(files):
            if not fname.endswith(suffixes):
                continue
            path = os.path.join(current_root, fname)
            mtime_ns, size = _claude_path_signature(path)
            entries.append((os.path.relpath(path, root), mtime_ns, size))
    return tuple(entries)


def _default_claude_storage_signature() -> tuple:
    sessions_root, projects_root, history_path = _default_claude_storage_cache_key()
    return (
        _claude_tree_signature(sessions_root, (".json",)),
        _claude_tree_signature(projects_root, (".jsonl",)),
        _claude_path_signature(history_path),
    )


def _clone_claude_session_row(row: dict) -> dict:
    cloned = dict(row)
    if isinstance(row.get("entrypoints"), set):
        cloned["entrypoints"] = set(row["entrypoints"])
    elif isinstance(row.get("entrypoints"), (list, tuple)):
        cloned["entrypoints"] = list(row["entrypoints"])
    return cloned


def _load_default_claude_storage_snapshot() -> tuple[list[dict], dict[str, dict]]:
    key = _default_claude_storage_cache_key()
    signature = _default_claude_storage_signature()
    if (
        _CLAUDE_STORAGE_CACHE.get("key") == key
        and _CLAUDE_STORAGE_CACHE.get("signature") == signature
    ):
        return (
            [
                _clone_claude_session_row(row)
                for row in (_CLAUDE_STORAGE_CACHE.get("sessions") or [])
                if isinstance(row, dict)
            ],
            dict(_CLAUDE_STORAGE_CACHE.get("history") or {}),
        )

    sessions = _load_claude_sessions(None)
    history = _build_claude_history_index(None)
    _CLAUDE_STORAGE_CACHE.update(
        {
            "key": key,
            "signature": signature,
            "sessions": sessions,
            "history": history,
        }
    )
    return [_clone_claude_session_row(row) for row in sessions], dict(history)


def _load_claude_storage_snapshot(
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
) -> tuple[list[dict], dict[str, dict]]:
    if sessions_dir is None and history_path is None:
        return _load_default_claude_storage_snapshot()
    return _load_claude_sessions(sessions_dir), _build_claude_history_index(history_path)


def _load_claude_sessions_cached(sessions_dir: Optional[str] = None) -> list[dict]:
    if sessions_dir is None:
        sessions, _history = _load_default_claude_storage_snapshot()
        return sessions
    return _load_claude_sessions(sessions_dir)


def _build_claude_thread_snapshot(
    session_rows: list[dict],
    history_index: dict[str, dict],
) -> dict[str, list[dict]]:
    session_by_id = {row["id"]: row for row in session_rows}
    all_session_ids = set(session_by_id.keys()) | set(history_index.keys())
    by_workspace: dict[str, list[dict]] = {}

    for session_id in all_session_ids:
        row = session_by_id.get(session_id)
        history_info = history_index.get(session_id, {})
        logical_cwd = _normalize_claude_project_path(history_info.get("project")) or (
            row["cwd"] if row else ""
        )
        if not logical_cwd:
            continue
        if _is_claude_noise_workspace_path(logical_cwd):
            continue
        if row and _should_skip_claude_session_from_workspace_list(row.get("sessionFile"), row):
            continue

        preview = history_info.get("preview") or (row or {}).get("preview")
        if row is None and not preview:
            continue

        created_at = int((row or {}).get("createdAt") or 0) or int(history_info.get("updatedAt") or 0)
        updated_at = int(history_info.get("updatedAt") or 0) or created_at
        by_workspace.setdefault(logical_cwd, []).append(
            {
                "id": session_id,
                "preview": preview,
                "createdAt": created_at,
                "updatedAt": updated_at,
            }
        )

    for threads in by_workspace.values():
        threads.sort(
            key=lambda item: (
                int(item.get("createdAt") or 0),
                int(item.get("updatedAt") or 0),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )

    return by_workspace


def _load_claude_thread_snapshot(
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
) -> dict[str, list[dict]]:
    if sessions_dir is not None or history_path is not None:
        session_rows, history_index = _load_claude_storage_snapshot(sessions_dir, history_path)
        return _build_claude_thread_snapshot(session_rows, history_index)

    key = _default_claude_storage_cache_key()
    signature = _default_claude_storage_signature()
    if (
        _CLAUDE_THREAD_SNAPSHOT_CACHE.get("key") == key
        and _CLAUDE_THREAD_SNAPSHOT_CACHE.get("signature") == signature
    ):
        cached = _CLAUDE_THREAD_SNAPSHOT_CACHE.get("snapshot")
        if isinstance(cached, dict):
            return {
                str(workspace): [_clone_claude_session_row(thread) for thread in threads]
                for workspace, threads in cached.items()
                if isinstance(threads, list)
            }

    session_rows, history_index = _load_default_claude_storage_snapshot()
    snapshot = _build_claude_thread_snapshot(session_rows, history_index)
    _CLAUDE_THREAD_SNAPSHOT_CACHE.update(
        {
            "key": key,
            "signature": signature,
            "snapshot": snapshot,
        }
    )
    return {
        workspace: [_clone_claude_session_row(thread) for thread in threads]
        for workspace, threads in snapshot.items()
    }


def _normalize_claude_message_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def infer_claude_thread_source_from_logs(
    thread_id: str,
    topic_id: Optional[int],
    *,
    log_paths: Optional[list[str]] = None,
) -> str:
    prefix = str(thread_id or "").strip()[:8]
    if not prefix or topic_id is None:
        return "unknown"

    on_demand_pattern = re.compile(
        rf"\[on-demand\]\s+thread\s+{re.escape(prefix)}.*?→\s+Topic\s+{int(topic_id)}\b"
    )
    app_created_pattern = re.compile(
        rf"新建\s+thread\s+{re.escape(prefix)}.*?→\s+Topic\s+{int(topic_id)}\b"
    )
    for path in log_paths or _default_onlineworker_log_paths():
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                payload = f.read()
        except Exception:
            continue
        if on_demand_pattern.search(payload):
            return "imported"
        if app_created_pattern.search(payload):
            return "app"
    return "unknown"


def _default_onlineworker_log_paths() -> list[str]:
    from config import get_data_dir

    data_dir = get_data_dir()
    if data_dir:
        base = os.path.join(data_dir, "onlineworker.log")
        return [base, *(f"{base}.{idx}" for idx in range(1, 4))]
    return ["/tmp/onlineworker.log"]


def _is_claude_display_command(display: str) -> bool:
    text = (display or "").strip()
    return text.startswith("/")


def _iter_claude_history_rows(history_path: Optional[str] = None):
    if history_path is None:
        history_path = os.path.expanduser(CLAUDE_HISTORY_PATH)
    if not os.path.exists(history_path):
        return
    try:
        with open(history_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                yield row
    except Exception:
        return


def _normalize_claude_project_path(raw_value) -> str:
    project = str(raw_value or "").strip()
    if project and os.path.isabs(project):
        return project
    return ""


def _claude_project_dir_slug(cwd: str) -> str:
    normalized = _normalize_claude_project_path(cwd)
    return normalized.replace(os.path.sep, "-") if normalized else ""


def _claude_session_file_preference(row: dict) -> tuple[int, int]:
    session_file = str(row.get("sessionFile") or "").strip()
    if not session_file:
        return (0, 0)

    created_at = int(row.get("createdAt") or 0)
    cwd = str(row.get("cwd") or "")
    if _is_claude_noise_workspace_path(cwd):
        return (1, created_at)

    parent_name = os.path.basename(os.path.dirname(session_file))
    expected_slug = _claude_project_dir_slug(cwd)
    if expected_slug and parent_name == expected_slug:
        return (3, created_at)
    return (2, created_at)


def _parse_claude_timestamp(raw_value) -> int:
    if isinstance(raw_value, (int, float)):
        return int(raw_value)
    text = str(raw_value or "").strip()
    if not text:
        return 0
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except Exception:
        return 0


def _usage_date_from_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if len(text) < 10:
        return ""
    candidate = text[:10]
    if (
        len(candidate) == 10
        and candidate[4] == "-"
        and candidate[7] == "-"
        and candidate[:4].isdigit()
        and candidate[5:7].isdigit()
        and candidate[8:].isdigit()
    ):
        return candidate
    return ""


def _number_usage_value(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _int_usage_value(value: object) -> int:
    return max(0, int(_number_usage_value(value)))


def _collect_jsonl_files(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    result: list[str] = []
    for current_root, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d != "subagents")
        for fname in sorted(files):
            if fname.endswith(".jsonl"):
                result.append(os.path.join(current_root, fname))
    result.sort()
    return result


def summarize_claude_usage(
    start_date: str,
    end_date: str,
    projects_dir: Optional[str] = None,
) -> dict:
    projects_root = os.path.expanduser(projects_dir or CLAUDE_PROJECTS_DIR)
    start = str(start_date or "").strip()
    end = str(end_date or "").strip()
    buckets: dict[str, dict[str, object]] = {}
    processed_hashes: set[str] = set()

    for fpath in _collect_jsonl_files(projects_root):
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                lines = list(f)
        except Exception:
            continue

        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            date = _usage_date_from_timestamp(row.get("timestamp"))
            if not date or (start and date < start) or (end and date > end):
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            message_id = str(message.get("id") or "").strip()
            request_id = str(row.get("requestId") or "").strip()
            if message_id and request_id:
                unique_hash = f"{message_id}:{request_id}"
                if unique_hash in processed_hashes:
                    continue
                processed_hashes.add(unique_hash)

            input_tokens = _int_usage_value(usage.get("input_tokens"))
            output_tokens = _int_usage_value(usage.get("output_tokens"))
            cache_creation_tokens = _int_usage_value(usage.get("cache_creation_input_tokens"))
            cache_read_tokens = _int_usage_value(usage.get("cache_read_input_tokens"))
            total_tokens = (
                input_tokens
                + output_tokens
                + cache_creation_tokens
                + cache_read_tokens
            )
            if total_tokens == 0:
                continue

            bucket = buckets.setdefault(
                date,
                {
                    "date": date,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 0,
                    "totalCostUsd": None,
                },
            )
            bucket["inputTokens"] = int(bucket["inputTokens"]) + input_tokens
            bucket["outputTokens"] = int(bucket["outputTokens"]) + output_tokens
            bucket["cacheCreationTokens"] = int(bucket["cacheCreationTokens"]) + cache_creation_tokens
            bucket["cacheReadTokens"] = int(bucket["cacheReadTokens"]) + cache_read_tokens
            bucket["totalTokens"] = int(bucket["totalTokens"]) + total_tokens
            cost = _number_usage_value(row.get("costUSD"))
            if cost > 0:
                bucket["totalCostUsd"] = float(bucket["totalCostUsd"] or 0) + cost

    return {
        "days": [
            buckets[date]
            for date in sorted(buckets.keys(), reverse=True)
        ]
    }


def _load_legacy_claude_sessions_from_dir(sessions_dir: str) -> list[dict]:
    if not os.path.isdir(sessions_dir):
        return []

    result: list[dict] = []
    for entry in sorted(os.listdir(sessions_dir)):
        if not entry.endswith(".json"):
            continue
        fpath = os.path.join(sessions_dir, entry)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                session = json.load(f)
        except Exception as e:
            logger.debug(f"[scan_claude_sessions] 跳过文件 {fpath}：{e}")
            continue
        if not isinstance(session, dict):
            continue
        session_id = session.get("sessionId")
        cwd = session.get("cwd")
        if not session_id or not isinstance(session_id, str):
            continue
        if not cwd or not isinstance(cwd, str) or not os.path.isabs(cwd):
            continue
        started_at = _parse_claude_timestamp(session.get("startedAt") or 0)
        result.append(
            {
                "id": session_id,
                "cwd": cwd,
                "createdAt": started_at,
            }
        )
    return result


def _load_claude_project_sessions_from_dir(projects_dir: str) -> list[dict]:
    if not os.path.isdir(projects_dir):
        return []

    result: list[dict] = []
    for root, dirs, files in os.walk(projects_dir):
        dirs[:] = sorted(d for d in dirs if d != "subagents")
        for entry in sorted(files):
            if not entry.endswith(".jsonl"):
                continue
            fpath = os.path.join(root, entry)
            session_id = os.path.splitext(entry)[0]
            cwd = ""
            created_at = 0
            preview = None
            entrypoints: set[str] = set()
            first_user_text = ""
            user_turn_count = 0
            assistant_turn_count = 0
            assistant_all_login_failed = True
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(row, dict):
                            continue
                        row_session_id = row.get("sessionId")
                        if isinstance(row_session_id, str) and row_session_id:
                            session_id = row_session_id
                        row_cwd = row.get("cwd")
                        if not cwd and isinstance(row_cwd, str) and os.path.isabs(row_cwd):
                            cwd = row_cwd
                        row_timestamp = _parse_claude_timestamp(row.get("timestamp"))
                        if row_timestamp and (created_at == 0 or row_timestamp < created_at):
                            created_at = row_timestamp
                        entrypoint = str(row.get("entrypoint") or "").strip()
                        if entrypoint:
                            entrypoints.add(entrypoint)

                        if row.get("isSidechain") is True:
                            continue
                        row_type = str(row.get("type") or "").strip()
                        if row_type in ("user", "last-prompt"):
                            text = _extract_claude_row_text(row)
                            if text and not _is_claude_display_command(text) and not preview:
                                preview = text
                        if row_type not in ("user", "assistant"):
                            continue
                        text = _extract_claude_row_text(row)
                        if not text:
                            continue
                        if row_type == "user" and _is_claude_display_command(text):
                            continue
                        if row_type == "user":
                            user_turn_count += 1
                            if not first_user_text:
                                first_user_text = text
                        else:
                            assistant_turn_count += 1
                            if not _is_claude_login_failed_text(text):
                                assistant_all_login_failed = False
            except Exception as e:
                logger.debug(f"[scan_claude_projects] 跳过文件 {fpath}：{e}")
                continue

            if not session_id or not cwd:
                continue
            if created_at == 0:
                created_at = int(os.path.getmtime(fpath) * 1000)
            result.append(
                {
                    "id": session_id,
                    "cwd": cwd,
                    "createdAt": created_at,
                    "sessionFile": fpath,
                    "preview": preview,
                    "entrypoints": entrypoints,
                    "sessionFileCwd": cwd,
                    "firstUserText": first_user_text,
                    "userTurnCount": user_turn_count,
                    "assistantTurnCount": assistant_turn_count,
                    "assistantAllLoginFailed": assistant_all_login_failed,
                }
            )
    return result


def _load_claude_sessions(sessions_dir: Optional[str] = None) -> list[dict]:
    if sessions_dir is None:
        stores: list[tuple[str, str]] = [
            ("legacy", os.path.expanduser(CLAUDE_SESSIONS_DIR)),
            ("project", os.path.expanduser(CLAUDE_PROJECTS_DIR)),
        ]
    else:
        explicit_store = os.path.expanduser(sessions_dir)
        stores = [("legacy", explicit_store), ("project", explicit_store)]

    deduped: dict[str, dict] = {}
    for store_kind, store in stores:
        if store_kind == "legacy":
            rows = _load_legacy_claude_sessions_from_dir(store)
        else:
            rows = _load_claude_project_sessions_from_dir(store)

        for row in rows:
            existing = deduped.get(row["id"])
            if existing is None:
                deduped[row["id"]] = dict(row)
                continue
            existing_created_at = int(existing.get("createdAt") or 0)
            row_created_at = int(row.get("createdAt") or 0)
            if existing_created_at and row_created_at:
                existing["createdAt"] = min(existing_created_at, row_created_at)
            else:
                existing["createdAt"] = existing_created_at or row_created_at
            if not existing.get("cwd") and row.get("cwd"):
                existing["cwd"] = row["cwd"]
            if row.get("sessionFile") and (
                _claude_session_file_preference(row)
                > _claude_session_file_preference(existing)
            ):
                existing["sessionFile"] = row["sessionFile"]

    return list(deduped.values())


def _build_claude_history_index(history_path: Optional[str] = None) -> dict[str, dict]:
    by_session: dict[str, dict] = {}
    for row in _iter_claude_history_rows(history_path):
        session_id = row.get("sessionId")
        if not session_id or not isinstance(session_id, str):
            continue
        display = str(row.get("display") or "").strip()
        timestamp = int(row.get("timestamp") or 0)
        project = _normalize_claude_project_path(row.get("project"))
        info = by_session.setdefault(
            session_id,
            {
                "updatedAt": 0,
                "preview": None,
                "project": project,
            },
        )
        if timestamp > int(info.get("updatedAt") or 0):
            info["updatedAt"] = timestamp
        if not info.get("project") and project:
            info["project"] = project
        if not info.get("preview") and display and not _is_claude_display_command(display):
            info["preview"] = display
    return by_session


def _iter_claude_project_rows(session_file: Optional[str]):
    if not session_file or not os.path.exists(session_file):
        return
    try:
        with open(session_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                yield row
    except Exception:
        return


def _extract_claude_content_text(content) -> str:
    if isinstance(content, str):
        return _normalize_claude_message_text(content)
    if isinstance(content, dict):
        if "text" in content:
            return _normalize_claude_message_text(content.get("text"))
        return _extract_claude_content_text(content.get("content"))
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            text = _normalize_claude_message_text(item)
        elif isinstance(item, dict):
            item_type = str(item.get("type") or "").strip()
            if item_type not in ("text", "input_text", "output_text"):
                continue
            text = _normalize_claude_message_text(item.get("text"))
        else:
            continue
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _extract_claude_row_text(row: dict) -> str:
    message = row.get("message")
    if isinstance(message, dict):
        text = _extract_claude_content_text(message.get("content"))
        if text:
            return text
    if row.get("type") == "last-prompt":
        return _normalize_claude_message_text(row.get("lastPrompt"))
    return ""


def _find_claude_project_session_file(
    session_id: str,
    sessions_dir: Optional[str] = None,
) -> Optional[str]:
    for row in _load_claude_sessions_cached(sessions_dir):
        if row.get("id") == session_id and row.get("sessionFile"):
            return row["sessionFile"]

    search_roots = [
        os.path.expanduser(CLAUDE_PROJECTS_DIR)
        if sessions_dir is None
        else os.path.expanduser(sessions_dir)
    ]
    target_name = f"{session_id}.jsonl"
    matches: list[str] = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for current_root, dirs, files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if d != "subagents")
            if target_name in files:
                matches.append(os.path.join(current_root, target_name))

    if not matches:
        return None

    matches.sort(
        key=lambda path: (
            0 if _is_claude_noise_workspace_path(_read_claude_project_session_cwd(path) or "") else 1,
            int(os.path.getmtime(path) * 1000),
            path,
        ),
        reverse=True,
    )
    return matches[0]


def _read_claude_project_session_cwd(session_file: Optional[str]) -> Optional[str]:
    for row in _iter_claude_project_rows(session_file):
        cwd = _normalize_claude_project_path(row.get("cwd"))
        if cwd:
            return cwd
    return None


def _read_claude_project_turns(session_file: Optional[str]) -> list[dict]:
    turns: list[dict] = []
    for row in _iter_claude_project_rows(session_file):
        if row.get("isSidechain") is True:
            continue
        row_type = str(row.get("type") or "").strip()
        if row_type not in ("user", "assistant"):
            continue
        text = _extract_claude_row_text(row)
        if not text:
            continue
        if row_type == "user" and _is_claude_display_command(text):
            continue
        turns.append(
            {
                "role": row_type,
                "text": text,
                "timestamp": _parse_claude_timestamp(row.get("timestamp")),
            }
        )
    return turns


def _is_claude_login_failed_text(text: str) -> bool:
    normalized = str(text or "").strip()
    return normalized == "Not logged in · Please run /login"


def _is_claude_noise_workspace_path(path: str) -> bool:
    normalized = str(path or "").strip()
    return (
        "/.worktrees/" in normalized
        or normalized.startswith("/private/tmp/")
        or (
            normalized.startswith("/private/var/folders/")
            and "/T/tmp" in normalized
        )
    )


def _is_claude_smoke_prompt_text(text: str) -> bool:
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    return lowered in {"reply with exactly ok", "please reply with exactly ok"} or normalized == "请只回复 OK"


def _collect_claude_session_entrypoints(session_file: Optional[str]) -> set[str]:
    entrypoints: set[str] = set()
    for row in _iter_claude_project_rows(session_file):
        entrypoint = str(row.get("entrypoint") or "").strip()
        if entrypoint:
            entrypoints.add(entrypoint)
    return entrypoints


def _should_skip_claude_session_from_workspace_list(
    session_file: Optional[str],
    session_info: Optional[dict] = None,
) -> bool:
    session_file_cwd = (
        _normalize_claude_project_path((session_info or {}).get("sessionFileCwd"))
        or _read_claude_project_session_cwd(session_file)
    )
    if session_file_cwd and _is_claude_noise_workspace_path(session_file_cwd):
        return True

    raw_entrypoints = (session_info or {}).get("entrypoints")
    if isinstance(raw_entrypoints, set):
        entrypoints = raw_entrypoints
    elif isinstance(raw_entrypoints, (list, tuple)):
        entrypoints = {str(item).strip() for item in raw_entrypoints if str(item).strip()}
    else:
        entrypoints = _collect_claude_session_entrypoints(session_file)

    if session_info is not None and all(
        key in session_info
        for key in (
            "firstUserText",
            "userTurnCount",
            "assistantTurnCount",
            "assistantAllLoginFailed",
        )
    ):
        user_turn_count = int(session_info.get("userTurnCount") or 0)
        assistant_turn_count = int(session_info.get("assistantTurnCount") or 0)
        if entrypoints == {"cli"} and assistant_turn_count == 0:
            return True
        if user_turn_count + assistant_turn_count == 0:
            return False
        if assistant_turn_count == 0:
            return False
        if user_turn_count > 1:
            return False
        user_prompt = str(session_info.get("firstUserText") or "").strip()
        if _is_claude_smoke_prompt_text(user_prompt):
            return True
        return bool(session_info.get("assistantAllLoginFailed"))

    turns = _read_claude_project_turns(session_file)
    assistant_turns = [turn for turn in turns if turn.get("role") == "assistant"]
    if entrypoints == {"cli"} and not assistant_turns:
        return True
    if not turns:
        return False

    user_turns = [turn for turn in turns if turn.get("role") == "user"]
    if not assistant_turns:
        return False
    if len(user_turns) > 1:
        return False

    user_prompt = str(user_turns[0].get("text") or "").strip() if user_turns else ""
    if _is_claude_smoke_prompt_text(user_prompt):
        return True

    return all(_is_claude_login_failed_text(turn.get("text", "")) for turn in assistant_turns)


def scan_claude_session_cwds(
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
) -> list[dict]:
    thread_snapshot = _load_claude_thread_snapshot(sessions_dir, history_path)
    if not thread_snapshot:
        return []

    cwd_stats: dict[str, dict] = {}
    for cwd, threads in thread_snapshot.items():
        if not cwd or not threads:
            continue
        latest = max(
            max(int(thread.get("createdAt") or 0), int(thread.get("updatedAt") or 0))
            for thread in threads
        )
        cwd_stats[cwd] = {
            "path": cwd,
            "name": os.path.basename(cwd),
            "thread_count": len(threads),
            "_latest_created_at": latest,
        }

    result = list(cwd_stats.values())
    result.sort(
        key=lambda item: (
            int(item["thread_count"]),
            int(item["_latest_created_at"]),
            str(item["path"]),
        ),
        reverse=True,
    )
    for item in result:
        item.pop("_latest_created_at", None)
    return result


def list_claude_threads_by_cwd(
    cwd: str,
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    thread_snapshot = _load_claude_thread_snapshot(sessions_dir, history_path)
    result = thread_snapshot.get(cwd, [])
    return [dict(item) for item in result[:limit]]


def read_claude_thread_history(
    session_id: str,
    history_path: Optional[str] = None,
    limit: int = 10,
    sessions_dir: Optional[str] = None,
) -> list[dict]:
    session_file = _find_claude_project_session_file(session_id, sessions_dir=sessions_dir)
    turns = _read_claude_project_turns(session_file)
    if turns:
        return turns[-limit:]

    turns: list[dict] = []
    for row in _iter_claude_history_rows(history_path):
        if row.get("sessionId") != session_id:
            continue
        display = str(row.get("display") or "").strip()
        if not display or _is_claude_display_command(display):
            continue
        turns.append(
            {
                "role": "user",
                "text": display,
                "timestamp": int(row.get("timestamp") or 0),
            }
        )
    return turns[-limit:]


def query_claude_active_session_ids(
    workspace_path: str,
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
) -> set[str]:
    thread_snapshot = _load_claude_thread_snapshot(sessions_dir, history_path)
    return {
        item["id"]
        for item in thread_snapshot.get(workspace_path, [])
    }


def query_claude_running_session_ids(
    workspace_path: str,
    sessions_dir: Optional[str] = None,
    history_path: Optional[str] = None,
) -> set[str]:
    from plugins.providers.builtin.claude.python.adapter import inspect_claude_thread_busy_state

    session_rows, history_index = _load_claude_storage_snapshot(sessions_dir, history_path)
    running_ids: set[str] = set()
    for row in session_rows:
        session_id = str(row.get("id") or "").strip()
        if not session_id:
            continue
        history_info = history_index.get(session_id, {})
        logical_cwd = _normalize_claude_project_path(history_info.get("project")) or str(
            row.get("cwd") or ""
        )
        if logical_cwd != workspace_path:
            continue
        if _is_claude_noise_workspace_path(logical_cwd):
            continue
        if _should_skip_claude_session_from_workspace_list(row.get("sessionFile"), row):
            continue
        session_file = str(row.get("sessionFile") or "").strip()
        if not session_id or not session_file:
            continue
        try:
            activity = inspect_claude_thread_busy_state(session_file)
        except Exception:
            continue
        if isinstance(activity, dict) and activity.get("busy") is True:
            running_ids.add(session_id)
    return running_ids
