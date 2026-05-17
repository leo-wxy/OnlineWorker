from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


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
    if sessions_dir is None:
        sessions_dir = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(sessions_dir):
        return []

    cwd_counts: dict[str, int] = {}

    for root, dirs, files in os.walk(sessions_dir):
        dirs.sort()
        for fname in files:
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline().strip()
                if not first_line:
                    continue
                meta = json.loads(first_line)
                if meta.get("type") != "session_meta":
                    continue
                payload = meta.get("payload", {})
                if _is_codex_subagent_source(payload.get("source")):
                    continue
                cwd = payload.get("cwd") or meta.get("cwd")
                if cwd and isinstance(cwd, str) and os.path.isabs(cwd):
                    cwd_counts[cwd] = cwd_counts.get(cwd, 0) + 1
            except Exception as e:
                logger.debug(f"[scan_workspaces] 跳过文件：{e}")
                continue

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
    if sessions_dir is None:
        sessions_dir = os.path.expanduser("~/.codex/sessions")
    if not os.path.isdir(sessions_dir):
        return []

    by_thread_id: dict[str, dict] = {}

    for root, dirs, files in os.walk(sessions_dir):
        dirs.sort()
        for fname in sorted(files):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    first_line = f.readline().strip()
                if not first_line:
                    continue
                meta = json.loads(first_line)
                if meta.get("type") != "session_meta":
                    continue
                payload = meta.get("payload", {})
                if _is_codex_subagent_source(payload.get("source")):
                    continue
                meta_cwd = payload.get("cwd") or meta.get("cwd")
                if meta_cwd != cwd:
                    continue

                tid = (
                    payload.get("id")
                    or meta.get("id")
                    or _extract_codex_thread_id_from_filename(fname)
                )
                if not tid:
                    continue

                created_at = (
                    _parse_codex_timestamp_ms(payload.get("timestamp"))
                    or _parse_codex_timestamp_ms(meta.get("timestamp"))
                    or int(os.path.getmtime(fpath) * 1000)
                )
                item = {
                    "id": tid,
                    "preview": _read_codex_first_user_preview_from_file(fpath),
                    "createdAt": created_at,
                    "updatedAt": created_at,
                }
                existing = by_thread_id.get(tid)
                if not existing or int(existing.get("createdAt") or 0) < created_at:
                    by_thread_id[tid] = item
            except Exception as e:
                logger.debug(f"[list_codex_session_meta_threads_by_cwd] 跳过文件 {fpath}：{e}")
                continue

    result = list(by_thread_id.values())
    result.sort(
        key=lambda item: (
            int(item.get("createdAt") or 0),
            int(item.get("updatedAt") or 0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return result[:limit]


def query_codex_active_thread_ids(workspace_path: str) -> set[str]:
    import sqlite3

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    if not os.path.exists(db_path):
        return set()

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id, source FROM threads WHERE cwd = ? AND archived = 0",
            (workspace_path,)
        ).fetchall()
        conn.close()
        return {
            row[0]
            for row in rows
            if not _is_codex_subagent_source(row[1] or "")
        }
    except Exception:
        return set()


def find_session_file(thread_id: str, sessions_dir: Optional[str] = None) -> Optional[str]:
    if sessions_dir is None:
        sessions_dir = os.path.expanduser("~/.codex/sessions")
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
) -> list[dict]:
    import sqlite3

    db_path = os.path.expanduser("~/.codex/state_5.sqlite")
    if not os.path.exists(db_path):
        return []

    try:
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

        result = []
        for r in rows:
            if _is_codex_subagent_source(r["source"] or ""):
                continue
            result.append({
                "id": r["id"],
                "preview": r["title"] or None,
                "createdAt": r["created_at"] or 0,
                "updatedAt": r["updated_at"] or 0,
            })
            if len(result) >= limit:
                break
        return result

    except Exception:
        return []


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
