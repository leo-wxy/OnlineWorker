# tests/test_storage.py
import json
import sqlite3
import pytest
from core.storage import (
    AppStorage,
    WorkspaceInfo,
    ThreadInfo,
    load_storage,
    save_storage,
)
from plugins.providers.builtin.codex.python.storage_runtime import (
    list_codex_threads_by_cwd,
    query_codex_active_thread_ids,
    read_codex_turn_terminal_message,
    read_codex_turn_terminal_outcome,
    read_thread_history,
)


def test_load_storage_file_not_exists(tmp_path):
    """文件不存在时返回空 AppStorage。"""
    storage = load_storage(str(tmp_path / "nonexistent.json"))
    assert storage.workspaces == {}
    assert storage.active_workspace is None


def test_save_and_load_roundtrip(tmp_path):
    """保存后再加载，数据一致。"""
    path = str(tmp_path / "state.json")
    ws = WorkspaceInfo(name="proj-a", path="/tmp/proj-a", topic_id=9001)
    storage = AppStorage(
        workspaces={"proj-a": ws},
        active_workspace="proj-a",
    )
    save_storage(storage, path)

    loaded = load_storage(path)
    assert "proj-a" in loaded.workspaces
    assert loaded.workspaces["proj-a"].path == "/tmp/proj-a"
    assert loaded.workspaces["proj-a"].topic_id == 9001
    assert loaded.active_workspace == "proj-a"


def test_save_and_load_with_threads(tmp_path):
    """含 threads 的 workspace 能正确保存/加载。"""
    path = str(tmp_path / "state.json")
    t = ThreadInfo(
        thread_id="tid-001",
        topic_id=42,
        preview="hello",
        archived=False,
        last_tg_user_message_id=7001,
    )
    ws = WorkspaceInfo(name="proj-b", path="/tmp/proj-b", threads={"tid-001": t})
    storage = AppStorage(workspaces={"proj-b": ws}, active_workspace="proj-b")
    save_storage(storage, path)

    loaded = load_storage(path)
    assert "proj-b" in loaded.workspaces
    loaded_ws = loaded.workspaces["proj-b"]
    assert "tid-001" in loaded_ws.threads
    t2 = loaded_ws.threads["tid-001"]
    assert t2.topic_id == 42
    assert t2.preview == "hello"
    assert t2.archived is False
    assert t2.last_tg_user_message_id == 7001


def test_save_atomic_via_tmp(tmp_path):
    """原子写入：写完后 .tmp 文件不存在。"""
    path = str(tmp_path / "state.json")
    save_storage(AppStorage(), path)
    import os
    assert not os.path.exists(path + ".tmp")
    assert os.path.exists(path)


def test_load_storage_multiple_workspaces(tmp_path):
    """多 workspace 场景。"""
    path = str(tmp_path / "state.json")
    data = {
        "workspaces": {
            "a": {"name": "a", "path": "/a", "topic_id": 1, "daemon_workspace_id": None, "threads": {}},
            "b": {"name": "b", "path": "/b", "topic_id": 2, "daemon_workspace_id": None, "threads": {}},
        },
        "active_workspace": "b",
    }
    with open(path, "w") as f:
        json.dump(data, f)

    storage = load_storage(path)
    assert len(storage.workspaces) == 2
    assert storage.workspaces["a"].topic_id == 1
    assert storage.workspaces["b"].path == "/b"
    assert storage.active_workspace == "b"


def test_load_storage_missing_tool_infers_provider_from_prefixed_key(tmp_path):
    """旧状态缺 tool 时，从 provider 前缀推断；无前缀时保持未知。"""
    path = str(tmp_path / "state.json")
    data = {
        "workspaces": {
            "claude:repo": {
                "name": "repo",
                "path": "/repo",
                "topic_id": 1,
                "daemon_workspace_id": None,
                "threads": {},
            },
            "legacy": {
                "name": "legacy",
                "path": "/legacy",
                "topic_id": 2,
                "daemon_workspace_id": None,
                "threads": {},
            },
        },
        "active_workspace": "claude:repo",
    }
    with open(path, "w") as f:
        json.dump(data, f)

    storage = load_storage(path)

    assert storage.workspaces["claude:repo"].tool == "claude"
    assert storage.workspaces["legacy"].tool == ""


def test_workspace_info_no_topic_id(tmp_path):
    """topic_id 为 None 时也能正常保存/加载。"""
    path = str(tmp_path / "state.json")
    ws = WorkspaceInfo(name="no-topic", path="/tmp/no-topic")
    storage = AppStorage(workspaces={"no-topic": ws})
    save_storage(storage, path)

    loaded = load_storage(path)
    assert loaded.workspaces["no-topic"].topic_id is None


def test_infer_claude_thread_source_from_logs_detects_imported_thread(tmp_path):
    from plugins.providers.builtin.claude.python.storage_runtime import infer_claude_thread_source_from_logs

    log_path = tmp_path / "onlineworker.log"
    log_path.write_text(
        "2026-04-12 21:37:00,839 [INFO] bot.handlers.workspace: "
        "[on-demand] thread 80564e62… → Topic 5457\n",
        encoding="utf-8",
    )

    result = infer_claude_thread_source_from_logs(
        "80564e62-1bc8-4ca6-ad3d-3284be3a25e7",
        5457,
        log_paths=[str(log_path)],
    )

    assert result == "imported"


def test_infer_claude_thread_source_from_logs_detects_app_created_thread(tmp_path):
    from plugins.providers.builtin.claude.python.storage_runtime import infer_claude_thread_source_from_logs

    log_path = tmp_path / "onlineworker.log"
    log_path.write_text(
        "2026-04-09 17:42:31,657 [INFO] bot.handlers.thread: "
        "新建 thread ses_28e6… → Topic 4950\n",
        encoding="utf-8",
    )

    result = infer_claude_thread_source_from_logs(
        "ses_28e6abcdef",
        4950,
        log_paths=[str(log_path)],
    )

    assert result == "app"


def test_list_codex_threads_by_cwd_filters_subagent_threads(tmp_path, monkeypatch):
    """codex /list 只应返回主线程，不应包含 subagent thread。"""
    db_path = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            cwd TEXT NOT NULL,
            title TEXT NOT NULL,
            sandbox_policy TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            has_user_event INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT NOT NULL DEFAULT '',
            first_user_message TEXT NOT NULL DEFAULT '',
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT NOT NULL DEFAULT 'enabled',
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT
        )
        """
    )
    rows = [
        (
            "main-1", "rollout", 1, 3000, "vscode", "openai",
            "/tmp/workspace", "Main thread", "workspace-write", "default",
            0, 1, 0, None, None, None, None, "", "Main thread", None, None, "enabled", None, None, None,
        ),
        (
            "sub-1", "rollout", 2, 4000,
            json.dumps({"subagent": {"other": "guardian"}}),
            "openai", "/tmp/workspace", "Guardian thread", "workspace-write", "default",
            0, 0, 0, None, None, None, None, "", "Guardian thread", None, None, "enabled", None, None, None,
        ),
        (
            "main-archived", "rollout", 3, 5000, "vscode", "openai",
            "/tmp/workspace", "Archived main", "workspace-write", "default",
            0, 1, 1, None, None, None, None, "", "Archived main", None, None, "enabled", None, None, None,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO threads VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        rows,
    )
    conn.commit()
    conn.close()

    real_expanduser = __import__("os").path.expanduser

    def fake_expanduser(path: str) -> str:
        if path == "~/.codex/state_5.sqlite":
            return str(db_path)
        return real_expanduser(path)

    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.os.path.expanduser", fake_expanduser)

    result = list_codex_threads_by_cwd("/tmp/workspace", limit=20)

    assert [r["id"] for r in result] == ["main-1"]


def test_list_codex_threads_by_cwd_sorts_by_created_at_desc(tmp_path, monkeypatch):
    """codex /list 应按 created_at 倒序，而不是按 updated_at。"""
    db_path = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            rollout_path TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            model_provider TEXT NOT NULL,
            cwd TEXT NOT NULL,
            title TEXT NOT NULL,
            sandbox_policy TEXT NOT NULL,
            approval_mode TEXT NOT NULL,
            tokens_used INTEGER NOT NULL DEFAULT 0,
            has_user_event INTEGER NOT NULL DEFAULT 0,
            archived INTEGER NOT NULL DEFAULT 0,
            archived_at INTEGER,
            git_sha TEXT,
            git_branch TEXT,
            git_origin_url TEXT,
            cli_version TEXT NOT NULL DEFAULT '',
            first_user_message TEXT NOT NULL DEFAULT '',
            agent_nickname TEXT,
            agent_role TEXT,
            memory_mode TEXT NOT NULL DEFAULT 'enabled',
            model TEXT,
            reasoning_effort TEXT,
            agent_path TEXT
        )
        """
    )
    rows = [
        (
            "main-old-created", "rollout", 1000, 9000, "vscode", "openai",
            "/tmp/workspace", "旧创建 thread", "workspace-write", "default",
            0, 1, 0, None, None, None, None, "", "旧创建 thread", None, None, "enabled", None, None, None,
        ),
        (
            "main-new-created", "rollout", 2000, 1000, "vscode", "openai",
            "/tmp/workspace", "新创建 thread", "workspace-write", "default",
            0, 1, 0, None, None, None, None, "", "新创建 thread", None, None, "enabled", None, None, None,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO threads VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        rows,
    )
    conn.commit()
    conn.close()

    real_expanduser = __import__("os").path.expanduser

    def fake_expanduser(path: str) -> str:
        if path == "~/.codex/state_5.sqlite":
            return str(db_path)
        return real_expanduser(path)

    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.os.path.expanduser", fake_expanduser)

    result = list_codex_threads_by_cwd("/tmp/workspace", limit=20)

    assert [r["id"] for r in result] == ["main-new-created", "main-old-created"]
    assert [r["createdAt"] for r in result] == [2000, 1000]


def test_query_codex_active_thread_ids_excludes_subagents(tmp_path, monkeypatch):
    db_path = tmp_path / "state_5.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            cwd TEXT NOT NULL,
            archived INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL
        )
        """
    )
    rows = [
        ("main-active", "/tmp/workspace", 0, "cli"),
        (
            "subagent-active",
            "/tmp/workspace",
            0,
            '{"subagent":{"thread_spawn":{"parent_thread_id":"main-active"}}}',
        ),
        ("main-archived", "/tmp/workspace", 1, "cli"),
    ]
    conn.executemany("INSERT INTO threads VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()

    real_expanduser = __import__("os").path.expanduser

    def fake_expanduser(path: str) -> str:
        if path == "~/.codex/state_5.sqlite":
            return str(db_path)
        return real_expanduser(path)

    monkeypatch.setattr("plugins.providers.builtin.codex.python.storage_runtime.os.path.expanduser", fake_expanduser)

    assert query_codex_active_thread_ids("/tmp/workspace") == {"main-active"}


def test_read_thread_history_preserves_phase_from_session_jsonl(tmp_path):
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "04" / "04"
    day_dir.mkdir(parents=True)
    session_path = day_dir / "rollout-2026-04-04T05-00-00-thread-123.jsonl"

    lines = [
        {
            "timestamp": "2026-04-04T05:00:01Z",
            "type": "response_item",
            "payload": {
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "处理中"}],
            },
        },
        {
            "timestamp": "2026-04-04T05:00:10Z",
            "type": "response_item",
            "payload": {
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "最终回复"}],
            },
        },
    ]

    with open(session_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    history = read_thread_history("thread-123", sessions_dir=str(sessions_dir), limit=10)

    assert history == [
        {
            "role": "assistant",
            "text": "处理中",
            "timestamp": "2026-04-04T05:00:01Z",
            "phase": "commentary",
        },
        {
            "role": "assistant",
            "text": "最终回复",
            "timestamp": "2026-04-04T05:00:10Z",
            "phase": "final_answer",
        },
    ]


def test_read_codex_turn_terminal_message_reads_task_complete_last_agent_message(tmp_path):
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "04" / "10"
    day_dir.mkdir(parents=True)
    session_path = day_dir / "rollout-2026-04-10T03-00-00-thread-456.jsonl"

    lines = [
        {
            "timestamp": "2026-04-10T03:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-old",
                "last_agent_message": "上一轮最终回复",
            },
        },
        {
            "timestamp": "2026-04-10T03:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-456",
                "last_agent_message": "这一轮完整最终回复",
            },
        },
    ]

    with open(session_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    assert (
        read_codex_turn_terminal_message(
            "thread-456",
            sessions_dir=str(sessions_dir),
            turn_id="turn-456",
        )
        == "这一轮完整最终回复"
    )


def test_read_codex_turn_terminal_outcome_reads_turn_aborted_status(tmp_path):
    sessions_dir = tmp_path / "sessions"
    day_dir = sessions_dir / "2026" / "04" / "12"
    day_dir.mkdir(parents=True)
    session_path = day_dir / "rollout-2026-04-12T04-00-00-thread-789.jsonl"

    lines = [
        {
            "timestamp": "2026-04-12T04:16:11Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-old",
                "last_agent_message": "旧 turn 完整回复",
            },
        },
        {
            "timestamp": "2026-04-12T04:17:09Z",
            "type": "event_msg",
            "payload": {
                "type": "turn_aborted",
                "turn_id": "turn-789",
                "reason": "interrupted",
            },
        },
    ]

    with open(session_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    assert read_codex_turn_terminal_outcome(
        "thread-789",
        sessions_dir=str(sessions_dir),
        turn_id="turn-789",
    ) == {
        "status": "aborted",
        "text": "",
        "reason": "interrupted",
    }
