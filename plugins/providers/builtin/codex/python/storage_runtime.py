from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CODEX_SESSIONS_DIR = "~/.codex/sessions"
_CODEX_SESSION_FILE_CACHE: dict[str, dict[str, object]] = {}


def _is_codex_subagent_source(source) -> bool:
    """判断 codex threads.source 是否表示 subagent 线程。"""
    if not source or source == "vscode":
        return False
    if isinstance(source, dict):
        return "subagent" in source
    if not isinstance(source, str):
        return False
    try:
        parsed = json.loads(source)
    except Exception:
        return False
    return isinstance(parsed, dict) and "subagent" in parsed


def scan_codex_session_cwds(sessions_dir: Optional[str] = None) -> list[dict]:
    """
    扫描 ~/.codex/sessions/ 中所有 session 的 cwd，去重后返回列表。
    每项：{"path": "/abs/path", "name": "<basename>", "thread_count": <int>}
    按最近活跃时间倒序排列（取目录 mtime）。
    """
    cwd_counts = dict(_build_codex_session_index(sessions_dir).get("workspace_counts", {}))

    result = []
    for path, count in cwd_counts.items():
        result.append({
            "path": path,
            "name": os.path.basename(path),
            "thread_count": count,
        })
    result.sort(key=lambda x: x["thread_count"], reverse=True)
    return result


def _parse_codex_timestamp_ms(value) -> int:
    """将 codex session_meta 中的 ISO 时间解析为毫秒时间戳。"""
    if not value or not isinstance(value, str):
        return 0
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
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


def _int_usage_value(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _codex_raw_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    input_tokens = _int_usage_value(value.get("input_tokens"))
    cached_input_tokens = _int_usage_value(
        value.get("cached_input_tokens") or value.get("cache_read_input_tokens")
    )
    output_tokens = _int_usage_value(value.get("output_tokens"))
    total_tokens = _int_usage_value(value.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = input_tokens + output_tokens
    return {
        "input": input_tokens,
        "cache_read": cached_input_tokens,
        "output": output_tokens,
        "total": total_tokens,
    }


def _subtract_codex_usage(
    current: dict[str, int],
    previous: Optional[dict[str, int]],
) -> dict[str, int]:
    previous = previous or {}
    return {
        "input": max(0, current["input"] - int(previous.get("input", 0))),
        "cache_read": max(0, current["cache_read"] - int(previous.get("cache_read", 0))),
        "output": max(0, current["output"] - int(previous.get("output", 0))),
        "total": max(0, current["total"] - int(previous.get("total", 0))),
    }


def _is_zero_codex_usage(raw: dict[str, int]) -> bool:
    return (
        raw["input"] == 0
        and raw["cache_read"] == 0
        and raw["output"] == 0
        and raw["total"] == 0
    )


def _collect_jsonl_files(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []
    result: list[str] = []
    for current_root, dirs, files in os.walk(root):
        dirs.sort()
        for fname in sorted(files):
            if fname.endswith(".jsonl"):
                result.append(os.path.join(current_root, fname))
    result.sort()
    return result


def _session_file_signature(fpath: str) -> tuple[int, int] | None:
    try:
        stat = os.stat(fpath)
    except OSError:
        return None
    return int(stat.st_mtime_ns), int(stat.st_size)


def _cached_scan_codex_session_file(
    fpath: str,
) -> tuple[Optional[dict], bool, dict[str, dict[str, object]]]:
    signature = _session_file_signature(fpath)
    if signature is None:
        _CODEX_SESSION_FILE_CACHE.pop(fpath, None)
        return None, False, {}

    cached = _CODEX_SESSION_FILE_CACHE.get(fpath)
    if cached is not None and cached.get("signature") == signature:
        return (
            cached.get("meta"),  # type: ignore[return-value]
            bool(cached.get("is_running", False)),
            cached.get("usage_buckets") or {},  # type: ignore[return-value]
        )

    meta, is_running, usage_buckets = _scan_codex_session_file(fpath)
    _CODEX_SESSION_FILE_CACHE[fpath] = {
        "signature": signature,
        "meta": meta,
        "is_running": is_running,
        "usage_buckets": usage_buckets,
    }
    return meta, is_running, usage_buckets


def _merge_codex_usage_bucket(
    target: dict[str, dict[str, object]],
    source: dict[str, dict[str, object]],
) -> None:
    for date, bucket in source.items():
        current = target.setdefault(
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
        current["inputTokens"] = int(current["inputTokens"]) + int(bucket.get("inputTokens") or 0)
        current["outputTokens"] = int(current["outputTokens"]) + int(bucket.get("outputTokens") or 0)
        current["cacheReadTokens"] = int(current["cacheReadTokens"]) + int(bucket.get("cacheReadTokens") or 0)
        current["totalTokens"] = int(current["totalTokens"]) + int(bucket.get("totalTokens") or 0)


def _scan_codex_session_file(fpath: str) -> tuple[Optional[dict], bool, dict[str, dict[str, object]]]:
    try:
        file_mtime_ms = int(os.path.getmtime(fpath) * 1000)
    except OSError:
        file_mtime_ms = 0

    preview: Optional[str] = None
    current_turn_id: Optional[str] = None
    usage_buckets: dict[str, dict[str, object]] = {}
    previous_totals: Optional[dict[str, int]] = None
    previous_seen_total_usage: Optional[dict[str, int]] = None
    meta_row: Optional[dict] = None

    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
            if first_line:
                try:
                    candidate = json.loads(first_line)
                except json.JSONDecodeError:
                    candidate = None
                if isinstance(candidate, dict) and candidate.get("type") == "session_meta":
                    payload = candidate.get("payload", {})
                    if not isinstance(payload, dict):
                        payload = {}
                    if not _is_codex_subagent_source(payload.get("source")):
                        cwd = payload.get("cwd") or candidate.get("cwd")
                        if isinstance(cwd, str) and cwd and os.path.isabs(cwd):
                            tid = (
                                payload.get("id")
                                or candidate.get("id")
                                or _extract_codex_thread_id_from_filename(os.path.basename(fpath))
                            )
                            if tid:
                                created_at = (
                                    _parse_codex_timestamp_ms(payload.get("timestamp"))
                                    or _parse_codex_timestamp_ms(candidate.get("timestamp"))
                                    or file_mtime_ms
                                )
                                meta_row = {
                                    "id": tid,
                                    "cwd": cwd,
                                    "preview": None,
                                    "createdAt": created_at,
                                    "updatedAt": max(created_at, file_mtime_ms),
                                    "sessionFile": fpath,
                                }

            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if preview is None and row.get("type") == "response_item":
                    payload = row.get("payload", {})
                    if isinstance(payload, dict) and payload.get("role") == "user":
                        maybe_preview = _build_user_text_from_response_items(payload.get("content", []))
                        if maybe_preview and not maybe_preview.startswith("#") and not maybe_preview.startswith("<"):
                            preview = maybe_preview

                if row.get("type") != "event_msg":
                    continue
                payload = row.get("payload", {})
                if not isinstance(payload, dict):
                    continue

                payload_type = str(payload.get("type") or "").strip()
                turn_id = str(payload.get("turn_id") or payload.get("turnId") or "").strip()
                if payload_type in {"task_started", "turn_context"} and turn_id:
                    current_turn_id = turn_id
                elif payload_type in {"task_complete", "turn_aborted"} and turn_id and current_turn_id == turn_id:
                    current_turn_id = None

                if payload_type != "token_count":
                    continue
                date = _usage_date_from_timestamp(row.get("timestamp"))
                if not date:
                    continue
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue

                last_usage = _codex_raw_usage(info.get("last_token_usage"))
                total_usage = _codex_raw_usage(info.get("total_token_usage"))
                if total_usage is not None:
                    if previous_seen_total_usage == total_usage:
                        continue
                    previous_seen_total_usage = dict(total_usage)

                if last_usage is not None:
                    raw = last_usage
                elif total_usage is not None:
                    raw = _subtract_codex_usage(total_usage, previous_totals)
                else:
                    continue

                if total_usage is not None:
                    previous_totals = dict(total_usage)
                if _is_zero_codex_usage(raw):
                    continue

                bucket = usage_buckets.setdefault(
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
                bucket["inputTokens"] = int(bucket["inputTokens"]) + raw["input"]
                bucket["outputTokens"] = int(bucket["outputTokens"]) + raw["output"]
                bucket["cacheReadTokens"] = int(bucket["cacheReadTokens"]) + raw["cache_read"]
                bucket["totalTokens"] = int(bucket["totalTokens"]) + (
                    raw["total"] or raw["input"] + raw["output"]
                )
    except Exception:
        return None, False, {}

    if meta_row is not None and preview:
        meta_row["preview"] = preview
    return meta_row, current_turn_id is not None, usage_buckets


def _query_codex_active_thread_rows_by_workspace() -> tuple[dict[str, set[str]], dict[str, list[dict]]]:
    import sqlite3

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    active_ids_by_workspace: dict[str, set[str]] = {}
    rows_by_workspace: dict[str, list[dict]] = {}
    if not os.path.exists(db_path):
        return active_ids_by_workspace, rows_by_workspace

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at, source, cwd
            FROM threads
            WHERE archived = 0
            ORDER BY created_at DESC
            """
        ).fetchall()
        conn.close()
    except Exception:
        return active_ids_by_workspace, rows_by_workspace

    for row in rows:
        if _is_codex_subagent_source(row["source"] or ""):
            continue
        workspace_path = str(row["cwd"] or "").strip()
        thread_id = str(row["id"] or "").strip()
        if not workspace_path or not thread_id:
            continue
        active_ids_by_workspace.setdefault(workspace_path, set()).add(thread_id)
        rows_by_workspace.setdefault(workspace_path, []).append(
            {
                "id": thread_id,
                "preview": row["title"] or None,
                "createdAt": row["created_at"] or 0,
                "updatedAt": row["updated_at"] or 0,
            }
        )
    return active_ids_by_workspace, rows_by_workspace


def _build_codex_session_index(
    sessions_dir: Optional[str] = None,
) -> dict[str, object]:
    sessions_root = os.path.expanduser(sessions_dir or CODEX_SESSIONS_DIR)
    workspace_counts: dict[str, int] = {}
    threads_by_workspace: dict[str, dict[str, dict]] = {}
    running_ids_by_workspace: dict[str, set[str]] = {}
    usage_buckets: dict[str, dict[str, object]] = {}
    current_files: set[str] = set()

    for fpath in _collect_jsonl_files(sessions_root):
        current_files.add(fpath)
        meta, is_running, file_usage_buckets = _cached_scan_codex_session_file(fpath)
        if meta is not None:
            workspace = str(meta["cwd"])
            workspace_counts[workspace] = workspace_counts.get(workspace, 0) + 1
            thread_map = threads_by_workspace.setdefault(workspace, {})
            item = {
                "id": meta["id"],
                "preview": meta.get("preview"),
                "createdAt": int(meta.get("createdAt") or 0),
                "updatedAt": int(meta.get("updatedAt") or 0),
            }
            existing = thread_map.get(meta["id"])
            if existing is None:
                thread_map[meta["id"]] = item
            else:
                if not existing.get("preview"):
                    existing["preview"] = item["preview"]
                existing["createdAt"] = max(int(existing.get("createdAt") or 0), item["createdAt"])
                existing["updatedAt"] = max(int(existing.get("updatedAt") or 0), item["updatedAt"])
            if is_running:
                running_ids_by_workspace.setdefault(workspace, set()).add(meta["id"])
        _merge_codex_usage_bucket(usage_buckets, file_usage_buckets)

    for cached_path in tuple(_CODEX_SESSION_FILE_CACHE.keys()):
        if cached_path not in current_files:
            _CODEX_SESSION_FILE_CACHE.pop(cached_path, None)

    return {
        "workspace_counts": workspace_counts,
        "threads_by_workspace": threads_by_workspace,
        "running_ids_by_workspace": running_ids_by_workspace,
        "usage_buckets": usage_buckets,
    }


def _read_codex_session_meta(fpath: str) -> Optional[dict]:
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline().strip()
    except Exception:
        return None

    if not first_line:
        return None

    try:
        meta = json.loads(first_line)
    except json.JSONDecodeError:
        return None

    if meta.get("type") != "session_meta":
        return None

    payload = meta.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    if _is_codex_subagent_source(payload.get("source")):
        return None

    cwd = payload.get("cwd") or meta.get("cwd")
    if not cwd or not isinstance(cwd, str) or not os.path.isabs(cwd):
        return None

    tid = (
        payload.get("id")
        or meta.get("id")
        or _extract_codex_thread_id_from_filename(os.path.basename(fpath))
    )
    if not tid:
        return None

    created_at = (
        _parse_codex_timestamp_ms(payload.get("timestamp"))
        or _parse_codex_timestamp_ms(meta.get("timestamp"))
        or int(os.path.getmtime(fpath) * 1000)
    )
    try:
        file_mtime_ms = int(os.path.getmtime(fpath) * 1000)
    except OSError:
        file_mtime_ms = created_at

    return {
        "id": tid,
        "cwd": cwd,
        "preview": _read_codex_first_user_preview_from_file(fpath),
        "createdAt": created_at,
        "updatedAt": max(created_at, file_mtime_ms),
        "sessionFile": fpath,
    }


def _codex_session_file_has_open_turn(fpath: str) -> bool:
    current_turn_id: Optional[str] = None
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "event_msg":
                    continue

                payload = obj.get("payload", {})
                if not isinstance(payload, dict):
                    continue
                payload_type = str(payload.get("type") or "").strip()
                turn_id = str(payload.get("turn_id") or payload.get("turnId") or "").strip()

                if payload_type in {"task_started", "turn_context"} and turn_id:
                    current_turn_id = turn_id
                    continue

                if payload_type in {"task_complete", "turn_aborted"} and turn_id:
                    if current_turn_id == turn_id:
                        current_turn_id = None
    except Exception:
        return False

    return current_turn_id is not None


def summarize_codex_usage(
    start_date: str,
    end_date: str,
    sessions_dir: Optional[str] = None,
) -> dict:
    start = str(start_date or "").strip()
    end = str(end_date or "").strip()
    buckets = dict(_build_codex_session_index(sessions_dir).get("usage_buckets", {}))

    return {
        "days": [
            buckets[date]
            for date in sorted(
                (
                    date
                    for date in buckets.keys()
                    if (not start or date >= start) and (not end or date <= end)
                ),
                reverse=True,
            )
        ]
    }


def _extract_codex_thread_id_from_filename(fname: str) -> str:
    """从 rollout-*.jsonl 文件名中提取 thread id。"""
    if not fname.endswith(".jsonl"):
        return ""
    parts = fname[:-6].split("-")
    if len(parts) < 6:
        return ""
    return "-".join(parts[-5:])


def _read_codex_first_user_preview_from_file(fpath: str) -> Optional[str]:
    """读取 session jsonl 中第一条真实用户输入，作为 /list 预览。"""
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            next(f, None)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "response_item":
                    continue
                payload = obj.get("payload", {})
                if payload.get("role") != "user":
                    continue
                for c in payload.get("content", []):
                    if c.get("type") != "input_text":
                        continue
                    text = (c.get("text") or "").strip()
                    if not text:
                        continue
                    if text.startswith("#") or text.startswith("<"):
                        continue
                    return text
    except Exception:
        return None
    return None


def _normalize_turn_text(text: str) -> str:
    return str(text or "").strip()


def _is_wrapper_open(text: str) -> Optional[str]:
    normalized = _normalize_turn_text(text)
    if not normalized.startswith("<image") or not normalized.endswith(">"):
        return None
    marker = "name=["
    start = normalized.find(marker)
    if start < 0:
        return None
    remainder = normalized[start + len(marker):]
    end = remainder.find("]")
    if end < 0:
        return None
    label = remainder[:end].strip()
    return label or None


def _is_wrapper_close(text: str) -> bool:
    return _normalize_turn_text(text) == "</image>"


def _image_summary_from_value(item: dict, pending_label: Optional[str] = None) -> Optional[str]:
    item_type = str(item.get("type") or "").strip().lower()
    if "image" not in item_type:
        return None

    image_ref = (
        item.get("image_url")
        or item.get("imageUrl")
        or item.get("path")
        or ""
    )
    normalized_ref = str(image_ref or "").strip()
    if not normalized_ref:
        return None

    if normalized_ref.startswith("data:"):
        label = (pending_label or "").strip() or "image"
        return f"[Attached image] {label}"

    if normalized_ref.startswith("file://"):
        normalized_ref = normalized_ref[len("file://"):]

    file_name = os.path.basename(normalized_ref.strip())
    label = file_name or (pending_label or "").strip()
    if not label:
        return None
    return f"[Attached image] {label}"


def _build_user_text_from_response_items(content: list[dict]) -> str:
    parts: list[str] = []
    pending_label: Optional[str] = None

    for item in content:
        item_type = str(item.get("type") or "").strip().lower()
        if item_type.endswith("text"):
            text = _normalize_turn_text(item.get("text") or "")
            if not text:
                continue
            label = _is_wrapper_open(text)
            if label is not None:
                pending_label = label
                continue
            if _is_wrapper_close(text):
                pending_label = None
                continue
            if text.startswith("#") or text.startswith("<"):
                continue
            parts.append(text)
            continue

        summary = _image_summary_from_value(item, pending_label)
        if summary:
            parts.append(summary)
            pending_label = None

    return "\n".join(part for part in parts if part).strip()


def _build_user_text_from_event_payload(payload: dict) -> str:
    parts: list[str] = []
    message = _normalize_turn_text(payload.get("message") or "")
    if message and not message.startswith("#") and not message.startswith("<"):
        parts.append(message)

    image_refs = []
    for key in ("local_images", "images"):
        raw_values = payload.get(key)
        if isinstance(raw_values, list):
            image_refs.extend(raw_values)

    for image_ref in image_refs:
        normalized_ref = str(image_ref or "").strip()
        if not normalized_ref:
            continue
        file_name = os.path.basename(normalized_ref)
        label = file_name or "image"
        parts.append(f"[Attached image] {label}")

    return "\n".join(part for part in parts if part).strip()


def _push_turn(turns: list[dict], *, role: str, text: str, timestamp: str, phase: str) -> None:
    normalized_text = _normalize_turn_text(text)
    if not normalized_text:
        return

    next_turn = {
        "role": role,
        "text": normalized_text,
        "timestamp": timestamp,
        "phase": phase,
    }
    if turns and turns[-1]["role"] == role:
        previous_text = turns[-1]["text"]
        if previous_text == normalized_text:
            turns[-1] = next_turn
            return

        def _logical_base(value: str) -> str:
            lines = [
                line.strip()
                for line in str(value or "").splitlines()
                if line.strip() and not line.strip().startswith("[Attached ")
            ]
            return "\n".join(lines).strip()

        if role == "user" and _logical_base(previous_text) == _logical_base(normalized_text):
            previous_has_attachment = "[Attached " in previous_text
            next_has_attachment = "[Attached " in normalized_text
            if not previous_has_attachment and next_has_attachment:
                turns[-1] = next_turn
            return

    turns.append(next_turn)


def list_codex_session_meta_threads_by_cwd(
    cwd: str,
    sessions_dir: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    threads_by_workspace = dict(_build_codex_session_index(sessions_dir).get("threads_by_workspace", {}))
    result = list(dict(threads_by_workspace.get(cwd, {})).values())
    result.sort(
        key=lambda item: (
            int(item.get("createdAt") or 0),
            int(item.get("updatedAt") or 0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return result[:limit]


def query_codex_active_thread_ids(
    workspace_path: str,
    sessions_dir: Optional[str] = None,
) -> set[str]:
    import sqlite3

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    active_ids: set[str] = set()

    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT id, source FROM threads WHERE cwd = ? AND archived = 0",
                (workspace_path,)
            ).fetchall()
            conn.close()
            active_ids.update(
                row[0]
                for row in rows
                if not _is_codex_subagent_source(row[1] or "")
            )
    except Exception:
        pass

    return active_ids


def query_codex_running_thread_ids(
    workspace_path: str,
    sessions_dir: Optional[str] = None,
) -> set[str]:
    running_ids_by_workspace = dict(_build_codex_session_index(sessions_dir).get("running_ids_by_workspace", {}))
    return set(running_ids_by_workspace.get(workspace_path, set()))


def find_session_file(thread_id: str, sessions_dir: Optional[str] = None) -> Optional[str]:
    if sessions_dir is None:
        sessions_dir = os.path.expanduser(CODEX_SESSIONS_DIR)
    if not os.path.isdir(sessions_dir):
        return None
    for root, dirs, files in os.walk(sessions_dir):
        dirs.sort()
        for fname in files:
            if thread_id in fname and fname.endswith(".jsonl"):
                return os.path.join(root, fname)
    return None


def read_thread_history(
    thread_id: str,
    sessions_dir: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    fpath = find_session_file(thread_id, sessions_dir)
    if not fpath:
        return []

    turns: list[dict] = []
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp = obj.get("timestamp", "")
                event_type = obj.get("type")
                payload = obj.get("payload", {})
                phase = str(payload.get("phase") or "")

                if event_type == "response_item":
                    role = payload.get("role")
                    if role == "user":
                        text = _build_user_text_from_response_items(payload.get("content", []))
                        _push_turn(
                            turns,
                            role="user",
                            text=text,
                            timestamp=timestamp,
                            phase=phase,
                        )
                    elif role == "assistant":
                        for c in payload.get("content", []):
                            if c.get("type") not in ("output_text", "text"):
                                continue
                            text = _normalize_turn_text(c.get("text", ""))
                            if text:
                                _push_turn(
                                    turns,
                                    role="assistant",
                                    text=text,
                                    timestamp=timestamp,
                                    phase=phase,
                                )
                                break
                    continue

                if event_type == "event_msg":
                    payload_type = payload.get("type")
                    if payload_type == "user_message":
                        text = _build_user_text_from_event_payload(payload)
                        _push_turn(
                            turns,
                            role="user",
                            text=text,
                            timestamp=timestamp,
                            phase=phase,
                        )
                    elif payload_type == "agent_message":
                        text = _normalize_turn_text(payload.get("message") or "")
                        _push_turn(
                            turns,
                            role="assistant",
                            text=text,
                            timestamp=timestamp,
                            phase=phase,
                        )
    except Exception:
        return []

    return turns[-limit:]


def _extract_codex_task_complete_text(payload: dict) -> str:
    last_agent_message = payload.get("last_agent_message")
    if isinstance(last_agent_message, str):
        return last_agent_message.strip()
    if isinstance(last_agent_message, dict):
        for key in ("text", "message"):
            value = last_agent_message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def read_codex_turn_terminal_message(
    thread_id: str,
    sessions_dir: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Optional[str]:
    fpath = find_session_file(thread_id, sessions_dir)
    if not fpath:
        return None

    latest_text: Optional[str] = None
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "event_msg":
                    continue

                payload = obj.get("payload", {})
                if payload.get("type") != "task_complete":
                    continue

                event_turn_id = payload.get("turn_id") or payload.get("turnId") or ""
                if turn_id is not None and event_turn_id != turn_id:
                    continue

                text = _extract_codex_task_complete_text(payload)
                if text:
                    latest_text = text
    except Exception:
        return None

    return latest_text


def read_codex_turn_terminal_outcome(
    thread_id: str,
    sessions_dir: Optional[str] = None,
    turn_id: Optional[str] = None,
) -> Optional[dict]:
    fpath = find_session_file(thread_id, sessions_dir)
    if not fpath:
        return None

    latest: Optional[dict] = None
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("type") != "event_msg":
                    continue

                payload = obj.get("payload", {})
                payload_type = payload.get("type")
                event_turn_id = payload.get("turn_id") or payload.get("turnId") or ""
                if turn_id is not None and event_turn_id != turn_id:
                    continue

                if payload_type == "task_complete":
                    latest = {
                        "status": "completed",
                        "text": _extract_codex_task_complete_text(payload),
                        "reason": "",
                    }
                elif payload_type == "turn_aborted":
                    latest = {
                        "status": "aborted",
                        "text": "",
                        "reason": str(payload.get("reason") or ""),
                    }
    except Exception:
        return None

    return latest


def list_codex_threads_by_cwd(
    cwd: str,
    limit: int = 20,
    sessions_dir: Optional[str] = None,
) -> list[dict]:
    import sqlite3

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    rows: list[dict] = []

    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT id, title, created_at, updated_at, source
                FROM threads
                WHERE cwd = ?
                  AND archived = 0
                ORDER BY created_at DESC
                LIMIT ?
            """, (cwd, limit * 3)).fetchall()
            conn.close()
    except Exception:
        rows = []

    result_by_id: dict[str, dict] = {}
    for meta in list_codex_session_meta_threads_by_cwd(cwd, sessions_dir=sessions_dir, limit=limit * 3):
        result_by_id[meta["id"]] = {
            "id": meta["id"],
            "preview": meta.get("preview"),
            "createdAt": int(meta.get("createdAt") or 0),
            "updatedAt": int(meta.get("updatedAt") or 0),
        }

    for r in rows:
        if _is_codex_subagent_source(r["source"] or ""):
            continue
        tid = r["id"]
        item = {
            "id": tid,
            "preview": r["title"] or None,
            "createdAt": r["created_at"] or 0,
            "updatedAt": r["updated_at"] or 0,
        }
        existing = result_by_id.get(tid)
        if existing is None:
            result_by_id[tid] = item
        else:
            if not existing.get("preview"):
                existing["preview"] = item["preview"]
            existing["createdAt"] = max(int(existing.get("createdAt") or 0), int(item["createdAt"] or 0))
            existing["updatedAt"] = max(int(existing.get("updatedAt") or 0), int(item["updatedAt"] or 0))

    result = list(result_by_id.values())
    result.sort(
        key=lambda item: (
            int(item.get("createdAt") or 0),
            int(item.get("updatedAt") or 0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return result[:limit]


def list_codex_sessions(
    limit: int = 100,
    sessions_dir: Optional[str] = None,
) -> list[dict]:
    index = _build_codex_session_index(sessions_dir)
    workspace_counts = dict(index.get("workspace_counts", {}))
    threads_by_workspace = dict(index.get("threads_by_workspace", {}))
    running_ids_by_workspace = dict(index.get("running_ids_by_workspace", {}))
    active_ids_by_workspace, sqlite_threads_by_workspace = _query_codex_active_thread_rows_by_workspace()
    workspaces = sorted(
        set(workspace_counts) | set(threads_by_workspace) | set(active_ids_by_workspace) | set(sqlite_threads_by_workspace),
        key=lambda item: (
            workspace_counts.get(item, 0),
            len(sqlite_threads_by_workspace.get(item, [])),
        ),
        reverse=True,
    )

    session_rows: list[dict] = []
    for workspace_path in workspaces:
        active_ids = active_ids_by_workspace.get(workspace_path, set())
        merged_by_id: dict[str, dict] = {}

        for item in list(threads_by_workspace.get(workspace_path, {}).values()):
            thread_id = str(item.get("id") or "").strip()
            if thread_id:
                merged_by_id[thread_id] = dict(item)

        for item in sqlite_threads_by_workspace.get(workspace_path, []):
            thread_id = str(item.get("id") or "").strip()
            if not thread_id:
                continue
            existing = merged_by_id.get(thread_id)
            if existing is None:
                merged_by_id[thread_id] = dict(item)
            else:
                if not existing.get("preview"):
                    existing["preview"] = item.get("preview")
                existing["createdAt"] = max(
                    int(existing.get("createdAt") or 0),
                    int(item.get("createdAt") or 0),
                )
                existing["updatedAt"] = max(
                    int(existing.get("updatedAt") or 0),
                    int(item.get("updatedAt") or 0),
                )

        running_ids = set(running_ids_by_workspace.get(workspace_path, set()))
        merged_items = list(merged_by_id.values())
        merged_items.sort(
            key=lambda item: (
                int(item.get("createdAt") or 0),
                int(item.get("updatedAt") or 0),
                str(item.get("id") or ""),
            ),
            reverse=True,
        )
        for item in merged_items:
            thread_id = str(item.get("id") or "").strip()
            if not thread_id:
                continue
            session_rows.append(
                {
                    "id": thread_id,
                    "title": str(item.get("preview") or thread_id).strip() or thread_id,
                    "workspace": workspace_path,
                    "archived": bool(active_ids) and thread_id not in active_ids,
                    "providerActive": thread_id in running_ids,
                    "updatedAt": int(item.get("updatedAt") or 0),
                    "createdAt": int(item.get("createdAt") or 0),
                }
            )

    session_rows.sort(
        key=lambda item: (
            -int(bool(item.get("providerActive"))),
            -int(item.get("updatedAt") or 0),
            -int(item.get("createdAt") or 0),
            str(item.get("id") or ""),
        )
    )
    return session_rows[:limit]


def list_codex_subagent_thread_ids(thread_ids: list[str]) -> set[str]:
    import sqlite3

    if not thread_ids:
        return set()

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    if not os.path.exists(db_path):
        return set()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in thread_ids)
        rows = conn.execute(
            f"""
            SELECT id, source
            FROM threads
            WHERE id IN ({placeholders})
            """,
            thread_ids,
        ).fetchall()
        conn.close()

        return {
            row["id"]
            for row in rows
            if _is_codex_subagent_source(row["source"] or "")
        }
    except Exception:
        return set()
