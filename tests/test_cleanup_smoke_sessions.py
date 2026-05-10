from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.cleanup_smoke_sessions import cleanup_smoke_sessions, is_claude_smoke_file, is_codex_smoke_file


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detects_codex_smoke_file(tmp_path):
    path = tmp_path / "rollout.jsonl"
    _write(
        path,
        '{"type":"session_meta","payload":{"id":"tid-1","cwd":"/Users/example/Projects/onlineWorker"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"This is an OnlineWorker fixed-session smoke test for provider codex. Reply with exactly this text and no extra words: ONLINEWORKER_SMOKE_MESSAGE_OK"}]}}\n',
    )

    assert is_codex_smoke_file(path) is True


def test_detects_claude_smoke_file(tmp_path):
    path = tmp_path / "session.jsonl"
    _write(
        path,
        '{"type":"queue-operation","content":"This is an OnlineWorker fixed-session permission smoke test for provider claude. Use the Bash/shell tool exactly once to run the following command, then reply with exactly ONLINEWORKER_SMOKE_PERMISSION_OK and no extra words"}\n',
    )

    assert is_claude_smoke_file(path) is True


def test_cleanup_smoke_sessions_archives_codex_and_deletes_files(tmp_path):
    codex_db = tmp_path / "state_5.sqlite"
    codex_sessions = tmp_path / ".codex" / "sessions"
    codex_archived_sessions = tmp_path / ".codex" / "archived_sessions"
    claude_projects = tmp_path / ".claude" / "projects"

    conn = sqlite3.connect(codex_db)
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            cwd TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO threads (id, title, cwd, archived) VALUES (?, ?, ?, ?)",
        (
            "019e0200-c038-72c0-aeeb-73be4dbb26f0",
            "This is an OnlineWorker fixed-session smoke test for provider codex. Reply...",
            "/Users/example/Projects/onlineWorker",
            0,
        ),
    )
    conn.commit()
    conn.close()

    codex_file = codex_sessions / "2026" / "05" / "07" / "rollout-2026-05-07T18-34-24-019e0200-c038-72c0-aeeb-73be4dbb26f0.jsonl"
    _write(
        codex_file,
        '{"type":"session_meta","payload":{"id":"019e0200-c038-72c0-aeeb-73be4dbb26f0","cwd":"/Users/example/Projects/onlineWorker"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"This is an OnlineWorker fixed-session smoke test for provider codex. Reply with exactly this text and no extra words: ONLINEWORKER_SMOKE_MESSAGE_OK"}]}}\n',
    )
    codex_archived_file = codex_archived_sessions / "2026" / "05" / "07" / "rollout-2026-05-07T18-40-00-019e0200-c038-72c0-aeeb-73be4dbb26f0.jsonl"
    _write(
        codex_archived_file,
        '{"type":"session_meta","payload":{"id":"019e0200-c038-72c0-aeeb-73be4dbb26f0","cwd":"/Users/example/Projects/onlineWorker"}}\n'
        '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ONLINEWORKER_SMOKE_MESSAGE_OK"}]}}\n',
    )

    claude_file = claude_projects / "-Users-example-Projects-onlineWorker" / "56988ad5-9300-538c-b357-63f8950ebb44.jsonl"
    _write(
        claude_file,
        '{"type":"queue-operation","content":"This is an OnlineWorker fixed-session permission smoke test for provider claude. Use the Bash/shell tool exactly once to run the following command, then reply with exactly ONLINEWORKER_SMOKE_PERMISSION_OK and no extra words"}\n',
    )

    summary = cleanup_smoke_sessions(
        codex_db_path=codex_db,
        codex_sessions_dir=codex_sessions,
        codex_archived_sessions_dir=codex_archived_sessions,
        claude_projects_dir=claude_projects,
        dry_run=False,
    )

    assert summary.codex_threads_archived == 1
    assert summary.codex_session_files_deleted == 2
    assert summary.claude_session_files_deleted == 1
    assert codex_file.exists() is False
    assert codex_archived_file.exists() is False
    assert claude_file.exists() is False

    conn = sqlite3.connect(codex_db)
    archived = conn.execute(
        "SELECT archived FROM threads WHERE id = ?",
        ("019e0200-c038-72c0-aeeb-73be4dbb26f0",),
    ).fetchone()
    conn.close()
    assert archived == (1,)


def test_cleanup_smoke_sessions_dry_run_keeps_data(tmp_path):
    codex_db = tmp_path / "state_5.sqlite"
    codex_sessions = tmp_path / ".codex" / "sessions"
    codex_archived_sessions = tmp_path / ".codex" / "archived_sessions"
    claude_projects = tmp_path / ".claude" / "projects"

    conn = sqlite3.connect(codex_db)
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            cwd TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "INSERT INTO threads (id, title, cwd, archived) VALUES (?, ?, ?, ?)",
        ("tid-dry", "This is an OnlineWorker fixed-session smoke test", "/tmp/workspace", 0),
    )
    conn.commit()
    conn.close()

    codex_file = codex_sessions / "2026" / "05" / "10" / "rollout-2026-05-10T09-00-00-tid-dry.jsonl"
    _write(
        codex_file,
        '{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"This is an OnlineWorker fixed-session smoke test for provider codex. Reply with exactly this text and no extra words: ONLINEWORKER_SMOKE_MESSAGE_OK"}]}}\n',
    )
    codex_archived_file = codex_archived_sessions / "2026" / "05" / "10" / "rollout-2026-05-10T09-01-00-tid-dry.jsonl"
    _write(
        codex_archived_file,
        '{"type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ONLINEWORKER_SMOKE_MESSAGE_OK"}]}}\n',
    )

    summary = cleanup_smoke_sessions(
        codex_db_path=codex_db,
        codex_sessions_dir=codex_sessions,
        codex_archived_sessions_dir=codex_archived_sessions,
        claude_projects_dir=claude_projects,
        dry_run=True,
    )

    assert summary.codex_threads_archived == 1
    assert summary.codex_session_files_deleted == 2
    assert codex_file.exists() is True
    assert codex_archived_file.exists() is True

    conn = sqlite3.connect(codex_db)
    archived = conn.execute("SELECT archived FROM threads WHERE id = ?", ("tid-dry",)).fetchone()
    conn.close()
    assert archived == (0,)
