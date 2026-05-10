#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SMOKE_TEXT_MARKERS = (
    "This is an OnlineWorker fixed-session smoke test",
    "This is an OnlineWorker fixed-session permission smoke test",
    "This is an OnlineWorker fixed-session combined smoke test",
    "ONLINEWORKER_SMOKE_MESSAGE_OK",
    "ONLINEWORKER_SMOKE_PERMISSION_OK",
)


def is_smoke_text(text: str) -> bool:
    normalized = (text or "").strip()
    return any(marker in normalized for marker in SMOKE_TEXT_MARKERS)


def is_codex_smoke_file(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if is_smoke_text(line):
                    return True
    except OSError:
        return False
    return False


def is_claude_smoke_file(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                if is_smoke_text(line):
                    return True
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = row.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str) and is_smoke_text(content):
                        return True
                last_prompt = row.get("lastPrompt")
                if isinstance(last_prompt, str) and is_smoke_text(last_prompt):
                    return True
                queued = row.get("content")
                if isinstance(queued, str) and is_smoke_text(queued):
                    return True
    except OSError:
        return False
    return False


def iter_codex_session_files(base_dir: Path) -> Iterable[Path]:
    if not base_dir.is_dir():
        return []
    return sorted(path for path in base_dir.rglob("*.jsonl") if path.is_file())


def iter_claude_session_files(base_dir: Path) -> Iterable[Path]:
    if not base_dir.is_dir():
        return []
    return sorted(path for path in base_dir.rglob("*.jsonl") if path.is_file())


def extract_codex_thread_id(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") != "session_meta":
                    continue
                payload = row.get("payload")
                if isinstance(payload, dict):
                    thread_id = str(payload.get("id") or "").strip()
                    if thread_id:
                        return thread_id
    except OSError:
        return ""
    stem = path.stem
    match = re.match(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)$", stem)
    if match:
        return match.group(1).strip()
    return ""


def archive_codex_threads(db_path: Path, thread_ids: set[str], *, dry_run: bool) -> int:
    if not thread_ids or not db_path.exists():
        return 0
    if dry_run:
        return len(thread_ids)
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany(
            "UPDATE threads SET archived = 1 WHERE id = ?",
            [(thread_id,) for thread_id in sorted(thread_ids)],
        )
        conn.commit()
    finally:
        conn.close()
    return len(thread_ids)


def delete_files(paths: Iterable[Path], *, dry_run: bool) -> int:
    count = 0
    for path in paths:
        count += 1
        if dry_run:
            continue
        path.unlink(missing_ok=True)
    return count


def delete_empty_parent_dirs(path: Path, stop_at: Path) -> None:
    current = path.parent
    while current.exists() and current != stop_at:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def prune_deleted_files(paths: Iterable[Path], *, dry_run: bool, stop_at: Path) -> None:
    if dry_run:
        return
    for path in paths:
        delete_empty_parent_dirs(path, stop_at)


@dataclass
class CleanupSummary:
    codex_threads_archived: int
    codex_session_files_deleted: int
    claude_session_files_deleted: int


def cleanup_smoke_sessions(
    *,
    codex_db_path: Path,
    codex_sessions_dir: Path,
    codex_archived_sessions_dir: Path,
    claude_projects_dir: Path,
    dry_run: bool,
) -> CleanupSummary:
    codex_session_files = [path for path in iter_codex_session_files(codex_sessions_dir) if is_codex_smoke_file(path)]
    codex_archived_files = [
        path for path in iter_codex_session_files(codex_archived_sessions_dir) if is_codex_smoke_file(path)
    ]
    codex_files = [*codex_session_files, *codex_archived_files]
    codex_thread_ids = {extract_codex_thread_id(path) for path in codex_files if extract_codex_thread_id(path)}
    archived = archive_codex_threads(codex_db_path, codex_thread_ids, dry_run=dry_run)
    deleted_codex_session_files = delete_files(codex_session_files, dry_run=dry_run)
    deleted_codex_archived_files = delete_files(codex_archived_files, dry_run=dry_run)
    prune_deleted_files(codex_session_files, dry_run=dry_run, stop_at=codex_sessions_dir)
    prune_deleted_files(codex_archived_files, dry_run=dry_run, stop_at=codex_archived_sessions_dir)

    claude_files = [path for path in iter_claude_session_files(claude_projects_dir) if is_claude_smoke_file(path)]
    deleted_claude_files = delete_files(claude_files, dry_run=dry_run)
    prune_deleted_files(claude_files, dry_run=dry_run, stop_at=claude_projects_dir)

    return CleanupSummary(
        codex_threads_archived=archived,
        codex_session_files_deleted=deleted_codex_session_files + deleted_codex_archived_files,
        claude_session_files_deleted=deleted_claude_files,
    )


def build_parser() -> argparse.ArgumentParser:
    home = Path.home()
    parser = argparse.ArgumentParser(description="Archive/delete OnlineWorker smoke sessions from local Codex/Claude stores.")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be cleaned.")
    parser.add_argument("--codex-db", type=Path, default=home / ".codex" / "state_5.sqlite")
    parser.add_argument("--codex-sessions", type=Path, default=home / ".codex" / "sessions")
    parser.add_argument("--codex-archived-sessions", type=Path, default=home / ".codex" / "archived_sessions")
    parser.add_argument("--claude-projects", type=Path, default=home / ".claude" / "projects")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summary = cleanup_smoke_sessions(
        codex_db_path=args.codex_db,
        codex_sessions_dir=args.codex_sessions,
        codex_archived_sessions_dir=args.codex_archived_sessions,
        claude_projects_dir=args.claude_projects,
        dry_run=bool(args.dry_run),
    )
    print(
        json.dumps(
            {
                "dryRun": bool(args.dry_run),
                "codexThreadsArchived": summary.codex_threads_archived,
                "codexSessionFilesDeleted": summary.codex_session_files_deleted,
                "claudeSessionFilesDeleted": summary.claude_session_files_deleted,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
