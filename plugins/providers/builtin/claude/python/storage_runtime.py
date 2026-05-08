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
                }
            )
    return result


def _load_claude_sessions(sessions_dir: Optional[str] = None) -> list[dict]:
    stores: list[str] = []
    if sessions_dir is None:
        stores = [
            os.path.expanduser(CLAUDE_SESSIONS_DIR),
            os.path.expanduser(CLAUDE_PROJECTS_DIR),
        ]
    else:
        stores = [os.path.expanduser(sessions_dir)]

    deduped: dict[str, dict] = {}
    for store in stores:
        for row in _load_legacy_claude_sessions_from_dir(store):
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
        for row in _load_claude_project_sessions_from_dir(store):
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
    for row in _load_claude_sessions(sessions_dir):
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


def _read_claude_project_session_preview(session_file: Optional[str]) -> Optional[str]:
    for row in _iter_claude_project_rows(session_file):
        if row.get("isSidechain") is True:
            continue
        if row.get("type") not in ("user", "last-prompt"):
            continue
        text = _extract_claude_row_text(row)
        if text and not _is_claude_display_command(text):
            return text
    return None


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


def _should_skip_claude_session_from_workspace_list(session_file: Optional[str]) -> bool:
    session_file_cwd = _read_claude_project_session_cwd(session_file)
    if session_file_cwd and _is_claude_noise_workspace_path(session_file_cwd):
        return True

    entrypoints = _collect_claude_session_entrypoints(session_file)
    if entrypoints and "sdk-cli" not in entrypoints and entrypoints == {"cli"}:
        return True

    turns = _read_claude_project_turns(session_file)
    if not turns:
        return False

    user_turns = [turn for turn in turns if turn.get("role") == "user"]
    assistant_turns = [turn for turn in turns if turn.get("role") == "assistant"]
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
    session_rows = _load_claude_sessions(sessions_dir)
    history_index = _build_claude_history_index(history_path)
    if not session_rows and not history_index:
        return []

    session_by_id = {row["id"]: row for row in session_rows}
    all_session_ids = set(session_by_id.keys()) | set(history_index.keys())

    cwd_stats: dict[str, dict] = {}
    for session_id in all_session_ids:
        row = session_by_id.get(session_id)
        history_info = history_index.get(session_id, {})
        cwd = _normalize_claude_project_path(history_info.get("project")) or (
            row["cwd"] if row else ""
        )
        if not cwd:
            continue
        if _is_claude_noise_workspace_path(cwd):
            continue
        if row is None and not history_info.get("preview"):
            continue
        if row and _should_skip_claude_session_from_workspace_list(row.get("sessionFile")):
            continue
        created_at = int((row or {}).get("createdAt") or 0) or int(history_info.get("updatedAt") or 0)
        updated_at = int(history_info.get("updatedAt") or 0) or created_at
        stat = cwd_stats.setdefault(
            cwd,
            {
                "path": cwd,
                "name": os.path.basename(cwd),
                "thread_count": 0,
                "_latest_created_at": 0,
            },
        )
        stat["thread_count"] += 1
        stat["_latest_created_at"] = max(
            stat["_latest_created_at"],
            created_at,
            updated_at,
        )

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
    session_rows = _load_claude_sessions(sessions_dir)
    history_index = _build_claude_history_index(history_path)
    session_by_id = {row["id"]: row for row in session_rows}
    all_session_ids = set(session_by_id.keys()) | set(history_index.keys())

    result: list[dict] = []
    for session_id in all_session_ids:
        row = session_by_id.get(session_id)
        history_info = history_index.get(session_id, {})
        logical_cwd = _normalize_claude_project_path(history_info.get("project")) or (
            row["cwd"] if row else ""
        )
        if logical_cwd != cwd:
            continue
        if _is_claude_noise_workspace_path(logical_cwd):
            continue
        if row and _should_skip_claude_session_from_workspace_list(row.get("sessionFile")):
            continue
        preview = history_info.get("preview")
        if not preview and row and row.get("sessionFile"):
            preview = _read_claude_project_session_preview(row.get("sessionFile"))
        if row is None and not preview:
            continue
        created_at = int((row or {}).get("createdAt") or 0) or int(history_info.get("updatedAt") or 0)
        updated_at = int(history_info.get("updatedAt") or 0) or created_at
        result.append(
            {
                "id": session_id,
                "preview": preview,
                "createdAt": created_at,
                "updatedAt": updated_at,
            }
        )

    result.sort(
        key=lambda item: (
            int(item.get("createdAt") or 0),
            int(item.get("updatedAt") or 0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return result[:limit]


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
    history_index = _build_claude_history_index(history_path)
    return {
        row["id"]
        for row in _load_claude_sessions(sessions_dir)
        if (
            _normalize_claude_project_path(history_index.get(row["id"], {}).get("project"))
            or row["cwd"]
        )
        == workspace_path
        and not _is_claude_noise_workspace_path(
            _normalize_claude_project_path(history_index.get(row["id"], {}).get("project"))
            or row["cwd"]
        )
        and not _should_skip_claude_session_from_workspace_list(row.get("sessionFile"))
    }
