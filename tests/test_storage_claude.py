import json

from plugins.providers.builtin.claude.python import storage_runtime as storage_module


def _write_claude_project_session(path, *, session_id: str, cwd: str, timestamp: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "parentUuid": None,
                        "type": "user",
                        "uuid": f"{session_id}-user",
                        "timestamp": timestamp,
                        "cwd": cwd,
                        "sessionId": session_id,
                        "message": {"role": "user", "content": "继续"},
                    }
                ),
                json.dumps(
                    {
                        "type": "last-prompt",
                        "lastPrompt": "继续",
                        "sessionId": session_id,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_claude_project_rows(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_claude_session(path, *, session_id: str, cwd: str, started_at: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": 1000,
                "sessionId": session_id,
                "cwd": cwd,
                "startedAt": started_at,
                "kind": "interactive",
                "entrypoint": "cli",
            }
        ),
        encoding="utf-8",
    )


def _write_claude_history(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_scan_claude_session_cwds_groups_by_project(tmp_path):
    sessions_dir = tmp_path / "sessions"
    _write_claude_session(
        sessions_dir / "1001.json",
        session_id="ses-a",
        cwd="/Users/wxy/Projects/onlineWorker",
        started_at=2000,
    )
    _write_claude_session(
        sessions_dir / "1002.json",
        session_id="ses-b",
        cwd="/Users/wxy/Projects/onlineWorker",
        started_at=3000,
    )
    _write_claude_session(
        sessions_dir / "1003.json",
        session_id="ses-c",
        cwd="/Users/wxy/Projects/ncmplayerengine",
        started_at=1000,
    )

    result = storage_module.scan_claude_session_cwds(
        str(sessions_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert [item["path"] for item in result] == [
        "/Users/wxy/Projects/onlineWorker",
        "/Users/wxy/Projects/ncmplayerengine",
    ]
    assert result[0]["name"] == "onlineWorker"
    assert result[0]["thread_count"] == 2
    assert result[1]["thread_count"] == 1


def test_list_claude_threads_by_cwd_uses_started_at_and_history_preview(tmp_path):
    sessions_dir = tmp_path / "sessions"
    history_path = tmp_path / "history.jsonl"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_session(
        sessions_dir / "1001.json",
        session_id="ses-old",
        cwd=cwd,
        started_at=1000,
    )
    _write_claude_session(
        sessions_dir / "1002.json",
        session_id="ses-new",
        cwd=cwd,
        started_at=2000,
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "/status",
                "timestamp": 2100,
                "project": cwd,
                "sessionId": "ses-new",
            },
            {
                "display": "实现 claude baseline",
                "timestamp": 2200,
                "project": cwd,
                "sessionId": "ses-new",
            },
            {
                "display": "旧会话第一条消息",
                "timestamp": 1100,
                "project": cwd,
                "sessionId": "ses-old",
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(sessions_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-new", "ses-old"]
    assert result[0]["preview"] == "实现 claude baseline"
    assert result[0]["createdAt"] == 2000
    assert result[0]["updatedAt"] == 2200
    assert result[1]["preview"] == "旧会话第一条消息"
    assert result[1]["createdAt"] == 1000
    assert result[1]["updatedAt"] == 1100


def test_read_claude_thread_history_returns_recent_user_messages_only(tmp_path):
    history_path = tmp_path / "history.jsonl"
    _write_claude_history(
        history_path,
        [
            {
                "display": "/status",
                "timestamp": 1000,
                "project": "/Users/wxy/Projects/onlineWorker",
                "sessionId": "ses-a",
            },
            {
                "display": "第一条有效消息",
                "timestamp": 1100,
                "project": "/Users/wxy/Projects/onlineWorker",
                "sessionId": "ses-a",
            },
            {
                "display": "第二条有效消息",
                "timestamp": 1200,
                "project": "/Users/wxy/Projects/onlineWorker",
                "sessionId": "ses-a",
            },
            {
                "display": "其他会话",
                "timestamp": 1300,
                "project": "/Users/wxy/Projects/onlineWorker",
                "sessionId": "ses-b",
            },
        ],
    )

    result = storage_module.read_claude_thread_history(
        "ses-a",
        history_path=str(history_path),
        limit=10,
    )

    assert result == [
        {"role": "user", "text": "第一条有效消息", "timestamp": 1100},
        {"role": "user", "text": "第二条有效消息", "timestamp": 1200},
    ]


def test_list_claude_threads_by_cwd_filters_history_only_resume_noise(tmp_path):
    history_path = tmp_path / "history.jsonl"
    cwd = "/Users/wxy/Projects/ncmplayerengine"
    _write_claude_history(
        history_path,
        [
            {
                "display": "/resume",
                "timestamp": 1775969524323,
                "project": cwd,
                "sessionId": "ses-noise",
            },
            {
                "display": "继续 engine 改造",
                "timestamp": 1775969524999,
                "project": cwd,
                "sessionId": "ses-real",
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(tmp_path / "empty-projects"),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-real"]
    assert result[0]["preview"] == "继续 engine 改造"


def test_read_claude_thread_history_reads_project_jsonl_user_and_assistant_messages(tmp_path):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "history.jsonl"
    session_id = "ses-a"
    cwd = "/Users/wxy/Projects/onlineWorker"
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / f"{session_id}.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": f"{session_id}-user-1",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": [{"type": "text", "text": "第一条用户消息"}]},
            },
            {
                "parentUuid": f"{session_id}-user-1",
                "type": "assistant",
                "uuid": f"{session_id}-assistant-1",
                "timestamp": "2026-04-07T09:31:20.002Z",
                "sessionId": session_id,
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "第一条 AI 回复"},
                        {"type": "tool_use", "name": "bash"},
                    ],
                },
            },
            {
                "parentUuid": f"{session_id}-assistant-1",
                "type": "user",
                "uuid": f"{session_id}-user-2",
                "timestamp": "2026-04-07T09:31:25.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": "第二条用户消息"},
            },
            {
                "parentUuid": f"{session_id}-user-2",
                "type": "assistant",
                "uuid": f"{session_id}-assistant-sidechain",
                "timestamp": "2026-04-07T09:31:26.002Z",
                "sessionId": session_id,
                "isSidechain": True,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "subagent reply"}],
                },
            },
            {
                "parentUuid": f"{session_id}-user-2",
                "type": "assistant",
                "uuid": f"{session_id}-assistant-2",
                "timestamp": "2026-04-07T09:31:28.002Z",
                "sessionId": session_id,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "第二条 AI 回复"}],
                },
            },
        ],
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "第一条用户消息",
                "timestamp": 1775523600000,
                "project": cwd,
                "sessionId": session_id,
            }
        ],
    )

    result = storage_module.read_claude_thread_history(
        session_id,
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
        limit=10,
    )

    assert result == [
        {"role": "user", "text": "第一条用户消息", "timestamp": 1775554278002},
        {"role": "assistant", "text": "第一条 AI 回复", "timestamp": 1775554280002},
        {"role": "user", "text": "第二条用户消息", "timestamp": 1775554285002},
        {"role": "assistant", "text": "第二条 AI 回复", "timestamp": 1775554288002},
    ]


def test_scan_claude_session_cwds_reads_project_jsonl_store_by_default(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    projects_dir = tmp_path / "projects"
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-a.jsonl",
        session_id="ses-a",
        cwd="/Users/wxy/Projects/onlineWorker",
        timestamp="2026-04-07T09:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-b.jsonl",
        session_id="ses-b",
        cwd="/Users/wxy/Projects/onlineWorker",
        timestamp="2026-04-07T10:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-ncmplayerengine" / "ses-c.jsonl",
        session_id="ses-c",
        cwd="/Users/wxy/Projects/ncmplayerengine",
        timestamp="2026-04-06T09:31:18.002Z",
    )
    monkeypatch.setattr(storage_module, "CLAUDE_SESSIONS_DIR", str(sessions_dir))
    monkeypatch.setattr(storage_module, "CLAUDE_PROJECTS_DIR", str(projects_dir))

    result = storage_module.scan_claude_session_cwds(
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert [item["path"] for item in result] == [
        "/Users/wxy/Projects/onlineWorker",
        "/Users/wxy/Projects/ncmplayerengine",
    ]
    assert result[0]["thread_count"] == 2
    assert result[1]["thread_count"] == 1


def test_list_claude_threads_by_cwd_reads_project_jsonl_store(tmp_path):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "history.jsonl"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-old.jsonl",
        session_id="ses-old",
        cwd=cwd,
        timestamp="2026-04-07T09:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-new.jsonl",
        session_id="ses-new",
        cwd=cwd,
        timestamp="2026-04-07T10:31:18.002Z",
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "旧会话第一条消息",
                "timestamp": 1775520000000,
                "project": cwd,
                "sessionId": "ses-old",
            },
            {
                "display": "新会话第一条消息",
                "timestamp": 1775523600000,
                "project": cwd,
                "sessionId": "ses-new",
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-new", "ses-old"]
    assert result[0]["preview"] == "新会话第一条消息"
    assert result[1]["preview"] == "旧会话第一条消息"


def test_list_claude_threads_by_cwd_prefers_session_file_matching_workspace_slug_when_duplicate_session_ids_exist(
    tmp_path,
):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "empty-history.jsonl"
    cwd = "/Users/wxy/Projects/onlineWorker"
    session_id = "11111111-1111-4111-8111-111111111111"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / f"{session_id}.jsonl",
        [
            {
                "type": "user",
                "uuid": f"{session_id}-user-real",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": "真实 onlineWorker 会话"},
            }
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-private-tmp-ow-claude-smoke" / f"{session_id}.jsonl",
        [
            {
                "type": "user",
                "uuid": f"{session_id}-user-smoke",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": "Reply with exactly OK"},
            }
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == [session_id]
    assert result[0]["preview"] == "真实 onlineWorker 会话"


def test_query_claude_active_session_ids_reads_project_jsonl_store(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-a.jsonl",
        session_id="ses-a",
        cwd=cwd,
        timestamp="2026-04-07T09:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-b.jsonl",
        session_id="ses-b",
        cwd=cwd,
        timestamp="2026-04-07T10:31:18.002Z",
    )

    result = storage_module.query_claude_active_session_ids(
        cwd,
        sessions_dir=str(projects_dir),
    )

    assert result == {"ses-a", "ses-b"}


def test_list_claude_threads_by_cwd_filters_single_turn_login_failed_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-login-failed.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-login-failed-user",
                "timestamp": "2026-04-12T11:47:36.917Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "message": {"role": "user", "content": "Reply with exactly OK"},
            },
            {
                "parentUuid": "ses-login-failed-user",
                "type": "assistant",
                "uuid": "ses-login-failed-assistant",
                "timestamp": "2026-04-12T11:47:37.020Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Not logged in · Please run /login"},
                    ],
                },
                "error": "authentication_failed",
                "isApiErrorMessage": True,
            },
            {
                "type": "last-prompt",
                "lastPrompt": "Reply with exactly OK",
                "sessionId": "ses-login-failed",
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-real.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-real-user",
                "timestamp": "2026-04-12T11:48:36.917Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "message": {"role": "user", "content": "继续修 claude thread"},
            },
            {
                "parentUuid": "ses-real-user",
                "type": "assistant",
                "uuid": "ses-real-assistant",
                "timestamp": "2026-04-12T11:48:40.020Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "已继续处理。"},
                    ],
                },
            },
            {
                "type": "last-prompt",
                "lastPrompt": "继续修 claude thread",
                "sessionId": "ses-real",
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-real"]
    assert result[0]["preview"] == "继续修 claude thread"


def test_query_claude_active_session_ids_filters_single_turn_login_failed_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-login-failed.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-login-failed-user",
                "timestamp": "2026-04-12T11:47:36.917Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "message": {"role": "user", "content": "who are you"},
            },
            {
                "parentUuid": "ses-login-failed-user",
                "type": "assistant",
                "uuid": "ses-login-failed-assistant",
                "timestamp": "2026-04-12T11:47:37.020Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Not logged in · Please run /login"},
                    ],
                },
                "error": "authentication_failed",
                "isApiErrorMessage": True,
            },
        ],
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-real.jsonl",
        session_id="ses-real",
        cwd=cwd,
        timestamp="2026-04-12T11:48:36.917Z",
    )

    result = storage_module.query_claude_active_session_ids(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert result == {"ses-real"}


def test_list_claude_threads_by_cwd_filters_plain_cli_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-cli.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-cli-user",
                "timestamp": "2026-04-07T09:33:42.791Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {"role": "user", "content": "who are you"},
            },
            {
                "parentUuid": "ses-cli-user",
                "type": "assistant",
                "uuid": "ses-cli-assistant",
                "timestamp": "2026-04-07T09:33:55.866Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I'm Claude"}],
                },
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-sdk.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-sdk-user",
                "timestamp": "2026-04-16T02:30:22.087Z",
                "cwd": cwd,
                "sessionId": "ses-sdk",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "现在可以了么？"},
            },
            {
                "parentUuid": "ses-sdk-user",
                "type": "assistant",
                "uuid": "ses-sdk-assistant",
                "timestamp": "2026-04-16T02:30:27.397Z",
                "cwd": cwd,
                "sessionId": "ses-sdk",
                "entrypoint": "sdk-cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "可以了！"}],
                },
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-sdk"]
    assert result[0]["preview"] == "现在可以了么？"


def test_list_claude_threads_by_cwd_filters_single_turn_smoke_prompt_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/ncmplayerengine"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-ncmplayerengine" / "ses-smoke.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-smoke-user",
                "timestamp": "2026-04-17T07:00:08.431Z",
                "cwd": cwd,
                "sessionId": "ses-smoke",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "请只回复 OK"},
            },
            {
                "parentUuid": "ses-smoke-user",
                "type": "assistant",
                "uuid": "ses-smoke-assistant",
                "timestamp": "2026-04-17T07:00:09.431Z",
                "cwd": cwd,
                "sessionId": "ses-smoke",
                "entrypoint": "sdk-cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "OK"}],
                },
            },
            {
                "type": "last-prompt",
                "lastPrompt": "请只回复 OK",
                "sessionId": "ses-smoke",
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-ncmplayerengine" / "ses-real.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-real-user",
                "timestamp": "2026-04-17T07:10:08.431Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续处理播放器问题"},
            },
            {
                "parentUuid": "ses-real-user",
                "type": "assistant",
                "uuid": "ses-real-assistant",
                "timestamp": "2026-04-17T07:10:09.431Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "继续处理。"}],
                },
            },
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-real"]


def test_query_claude_active_session_ids_filters_plain_cli_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-cli.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-cli-user",
                "timestamp": "2026-04-07T09:33:42.791Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {"role": "user", "content": "who are you"},
            },
            {
                "parentUuid": "ses-cli-user",
                "type": "assistant",
                "uuid": "ses-cli-assistant",
                "timestamp": "2026-04-07T09:33:55.866Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I'm Claude"}],
                },
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-sdk.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-sdk-user",
                "timestamp": "2026-04-16T02:30:22.087Z",
                "cwd": cwd,
                "sessionId": "ses-sdk",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续处理"},
            }
        ],
    )

    result = storage_module.query_claude_active_session_ids(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert result == {"ses-sdk"}


def test_scan_claude_session_cwds_filters_noise_workspace_paths(tmp_path):
    projects_dir = tmp_path / "projects"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker--worktrees-phase16-claude-app-surface" / "ses-worktree.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-worktree-user",
                "timestamp": "2026-04-17T07:00:08.431Z",
                "cwd": "/Users/wxy/Projects/onlineWorker/.worktrees/phase16-claude-app-surface",
                "sessionId": "ses-worktree",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "请只回复 OK"},
            },
            {
                "parentUuid": "ses-worktree-user",
                "type": "assistant",
                "uuid": "ses-worktree-assistant",
                "timestamp": "2026-04-17T07:00:09.431Z",
                "cwd": "/Users/wxy/Projects/onlineWorker/.worktrees/phase16-claude-app-surface",
                "sessionId": "ses-worktree",
                "entrypoint": "sdk-cli",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "OK"}]},
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-ncmplayerengine" / "ses-real.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-real-user",
                "timestamp": "2026-04-17T07:10:08.431Z",
                "cwd": "/Users/wxy/Projects/ncmplayerengine",
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续处理播放器问题"},
            }
        ],
    )

    result = storage_module.scan_claude_session_cwds(
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert [item["path"] for item in result] == ["/Users/wxy/Projects/ncmplayerengine"]


def test_scan_claude_session_cwds_includes_history_only_projects(tmp_path):
    history_path = tmp_path / "history.jsonl"
    _write_claude_history(
        history_path,
        [
            {
                "display": "历史工作区 A",
                "timestamp": 1775520000000,
                "project": "/Users/wxy/Projects/music4/music_app/module_source/music_base_audio_lib",
                "sessionId": "ses-a",
            },
            {
                "display": "历史工作区 B",
                "timestamp": 1775523600000,
                "project": "/Users/wxy/Desktop/claude-code-plugin",
                "sessionId": "ses-b",
            },
        ],
    )

    result = storage_module.scan_claude_session_cwds(
        sessions_dir=str(tmp_path / "empty-sessions"),
        history_path=str(history_path),
    )

    assert [item["path"] for item in result] == [
        "/Users/wxy/Desktop/claude-code-plugin",
        "/Users/wxy/Projects/music4/music_app/module_source/music_base_audio_lib",
    ]
    assert result[0]["thread_count"] == 1
    assert result[1]["thread_count"] == 1


def test_scan_claude_session_cwds_filters_workspace_noise_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-cli.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-cli-user",
                "timestamp": "2026-04-07T09:33:42.791Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {"role": "user", "content": "who are you"},
            }
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-login-failed.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-login-failed-user",
                "timestamp": "2026-04-12T11:47:36.917Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "Reply with exactly OK"},
            },
            {
                "parentUuid": "ses-login-failed-user",
                "type": "assistant",
                "uuid": "ses-login-failed-assistant",
                "timestamp": "2026-04-12T11:47:37.020Z",
                "cwd": cwd,
                "sessionId": "ses-login-failed",
                "entrypoint": "sdk-cli",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Not logged in · Please run /login"},
                    ],
                },
                "error": "authentication_failed",
                "isApiErrorMessage": True,
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-real.jsonl",
        [
            {
                "parentUuid": None,
                "type": "user",
                "uuid": "ses-real-user",
                "timestamp": "2026-04-16T02:30:22.087Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "现在可以了么？"},
            },
            {
                "parentUuid": "ses-real-user",
                "type": "assistant",
                "uuid": "ses-real-assistant",
                "timestamp": "2026-04-16T02:30:27.397Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "可以了！"}],
                },
            },
        ],
    )

    result = storage_module.scan_claude_session_cwds(
        sessions_dir=str(projects_dir),
        history_path=str(tmp_path / "empty-history.jsonl"),
    )

    assert result == [
        {
            "path": "/Users/wxy/Projects/onlineWorker",
            "name": "onlineWorker",
            "thread_count": 1,
        }
    ]


def test_list_claude_threads_by_cwd_prefers_history_project_over_nested_session_cwd(tmp_path):
    sessions_dir = tmp_path / "sessions"
    history_path = tmp_path / "history.jsonl"

    _write_claude_session(
        sessions_dir / "1001.json",
        session_id="ses-a",
        cwd="/Users/wxy/Projects/ncmplayerengine/Demo/Android",
        started_at=2000,
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "继续 engine 改造",
                "timestamp": 1775523600000,
                "project": "/Users/wxy/Projects/ncmplayerengine",
                "sessionId": "ses-a",
            }
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        "/Users/wxy/Projects/ncmplayerengine",
        sessions_dir=str(sessions_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-a"]
    assert result[0]["preview"] == "继续 engine 改造"


def test_query_claude_active_session_ids_prefers_history_project_over_nested_session_cwd(tmp_path):
    sessions_dir = tmp_path / "sessions"
    history_path = tmp_path / "history.jsonl"

    _write_claude_session(
        sessions_dir / "1001.json",
        session_id="ses-a",
        cwd="/Users/wxy/Projects/ncmplayerengine/Demo/Android",
        started_at=2000,
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "继续 engine 改造",
                "timestamp": 1775523600000,
                "project": "/Users/wxy/Projects/ncmplayerengine",
                "sessionId": "ses-a",
            }
        ],
    )

    result = storage_module.query_claude_active_session_ids(
        "/Users/wxy/Projects/ncmplayerengine",
        sessions_dir=str(sessions_dir),
        history_path=str(history_path),
    )

    assert result == {"ses-a"}


def test_scan_claude_session_cwds_skips_noise_workspaces_from_project_store(tmp_path):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "history.jsonl"
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-real.jsonl",
        session_id="ses-real",
        cwd="/Users/wxy/Projects/onlineWorker",
        timestamp="2026-04-07T09:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-Users-wxy-Projects-onlineWorker--worktrees-phase16" / "ses-noise.jsonl",
        session_id="ses-noise",
        cwd="/Users/wxy/Projects/onlineWorker/.worktrees/phase16",
        timestamp="2026-04-07T10:31:18.002Z",
    )
    _write_claude_project_session(
        projects_dir / "-private-var-folders-tmp" / "ses-tmp.jsonl",
        session_id="ses-tmp",
        cwd="/private/var/folders/qc/abc/T/tmp.xyz",
        timestamp="2026-04-07T11:31:18.002Z",
    )
    _write_claude_history(
        history_path,
        [
            {
                "display": "继续 onlineWorker 改造",
                "timestamp": 1775520000000,
                "project": "/Users/wxy/Projects/onlineWorker",
                "sessionId": "ses-real",
            }
        ],
    )

    result = storage_module.scan_claude_session_cwds(
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
    )

    assert [item["path"] for item in result] == ["/Users/wxy/Projects/onlineWorker"]


def test_list_claude_threads_by_cwd_skips_smoke_prompt_and_login_failed_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "history.jsonl"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-real.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-real",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续修复"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-04-07T09:31:20.002Z",
                "sessionId": "ses-real",
                "message": {"role": "assistant", "content": "收到"},
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-smoke.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-smoke",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "请只回复 OK"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-04-07T10:31:20.002Z",
                "sessionId": "ses-smoke",
                "message": {"role": "assistant", "content": "OK"},
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-login.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T11:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-login",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "你好"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-04-07T11:31:20.002Z",
                "sessionId": "ses-login",
                "message": {"role": "assistant", "content": "Not logged in · Please run /login"},
            },
        ],
    )
    _write_claude_history(
        history_path,
        [
            {"display": "继续修复", "timestamp": 1775520000000, "project": cwd, "sessionId": "ses-real"},
            {"display": "请只回复 OK", "timestamp": 1775523600000, "project": cwd, "sessionId": "ses-smoke"},
            {"display": "你好", "timestamp": 1775527200000, "project": cwd, "sessionId": "ses-login"},
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-real"]


def test_list_claude_threads_by_cwd_skips_plain_cli_project_sessions(tmp_path):
    projects_dir = tmp_path / "projects"
    history_path = tmp_path / "history.jsonl"
    cwd = "/Users/wxy/Projects/onlineWorker"

    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-sdk.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-sdk",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续 onlineWorker"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-04-07T09:31:20.002Z",
                "sessionId": "ses-sdk",
                "message": {"role": "assistant", "content": "收到"},
            },
        ],
    )
    _write_claude_project_rows(
        projects_dir / "-Users-wxy-Projects-onlineWorker" / "ses-cli.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-cli",
                "entrypoint": "cli",
                "message": {"role": "user", "content": "Who are you"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-04-07T10:31:20.002Z",
                "sessionId": "ses-cli",
                "message": {"role": "assistant", "content": "I am Claude"},
            },
        ],
    )
    _write_claude_history(
        history_path,
        [
            {"display": "继续 onlineWorker", "timestamp": 1775520000000, "project": cwd, "sessionId": "ses-sdk"},
            {"display": "Who are you", "timestamp": 1775523600000, "project": cwd, "sessionId": "ses-cli"},
        ],
    )

    result = storage_module.list_claude_threads_by_cwd(
        cwd,
        sessions_dir=str(projects_dir),
        history_path=str(history_path),
        limit=20,
    )

    assert [item["id"] for item in result] == ["ses-sdk"]


def test_find_claude_project_session_file_prefers_workspace_copy_for_duplicate_session_id(tmp_path):
    projects_dir = tmp_path / "projects"
    session_id = "11111111-1111-4111-8111-111111111111"
    canonical_path = projects_dir / "-Users-wxy-Projects-onlineWorker" / f"{session_id}.jsonl"
    smoke_path = projects_dir / "-private-tmp-ow-claude-smoke" / f"{session_id}.jsonl"

    _write_claude_project_rows(
        canonical_path,
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": "/Users/wxy/Projects/onlineWorker",
                "sessionId": session_id,
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "继续 onlineWorker"},
            }
        ],
    )
    _write_claude_project_rows(
        smoke_path,
        [
            {
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": "/private/tmp/ow-claude-smoke",
                "sessionId": session_id,
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "请只回复 OK"},
            }
        ],
    )

    result = storage_module._find_claude_project_session_file(
        session_id,
        sessions_dir=str(projects_dir),
    )

    assert result == str(canonical_path)
