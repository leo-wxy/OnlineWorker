import pytest
from plugins.providers.builtin.codex.python.tui_host_runtime import (
    build_codex_resume_command,
    build_codex_tui_child_env,
    CodexTuiHost,
    encode_terminal_input,
    ensure_codex_tui_host_extra_args,
    resolve_host_thread_id,
    validate_thread_binding,
)
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo, load_storage, save_storage


def test_build_codex_resume_command_targets_local_thread_and_cwd_by_default():
    cmd = build_codex_resume_command(
        codex_bin="codex",
        thread_id="019d6220-489a-7050-bf98-8fcf6e5bdfea",
        cwd="/Users/example/Projects/onlineWorker",
        extra_args=["--no-alt-screen"],
    )

    assert cmd == [
        "codex",
        "resume",
        "019d6220-489a-7050-bf98-8fcf6e5bdfea",
        "--cd",
        "/Users/example/Projects/onlineWorker",
        "--no-alt-screen",
    ]


def test_build_codex_resume_command_still_supports_optional_remote_url():
    cmd = build_codex_resume_command(
        codex_bin="codex",
        thread_id="019d6220-489a-7050-bf98-8fcf6e5bdfea",
        cwd="/Users/example/Projects/onlineWorker",
        remote_url="ws://127.0.0.1:4722",
    )

    assert cmd == [
        "codex",
        "resume",
        "019d6220-489a-7050-bf98-8fcf6e5bdfea",
        "--remote",
        "ws://127.0.0.1:4722",
        "--cd",
        "/Users/example/Projects/onlineWorker",
    ]


def test_codex_tui_host_keeps_remote_url_for_shared_app_server(tmp_path):
    from plugins.providers.builtin.codex.python.tui_host_runtime import CodexTuiHost

    host = CodexTuiHost(
        data_dir=str(tmp_path),
        thread_id="tid-1",
        cwd="/Users/example/Projects/onlineWorker",
        remote_url="ws://127.0.0.1:4722",
        codex_bin="codex",
    )

    assert host.remote_url == "ws://127.0.0.1:4722"


def test_codex_tui_host_forces_manual_approval_reviewer_by_default(tmp_path):
    host = CodexTuiHost(
        data_dir=str(tmp_path),
        thread_id="tid-1",
        cwd="/Users/example/Projects/onlineWorker",
        codex_bin="codex",
        extra_args=["--no-alt-screen"],
    )

    assert host.extra_args == [
        "--no-alt-screen",
        "-c",
        'approvals_reviewer="user"',
    ]


def test_codex_tui_host_extra_args_do_not_duplicate_explicit_approval_reviewer():
    assert ensure_codex_tui_host_extra_args(["-c", 'approvals_reviewer="user"']) == [
        "-c",
        'approvals_reviewer="user"',
    ]


def test_build_codex_tui_child_env_marks_owned_thread_and_cwd():
    env = build_codex_tui_child_env(
        base_env={"PATH": "/usr/bin", "PWD": "/tmp/old"},
        cwd="/Users/example/Projects/onlineWorker",
        thread_id="tid-1",
    )

    assert env["PATH"] == "/usr/bin"
    assert env["PWD"] == "/Users/example/Projects/onlineWorker"
    assert env["CODEX_THREAD_ID"] == "tid-1"
    assert env["ONLINEWORKER_CODEX_TUI_HOST"] == "1"


def test_build_codex_tui_child_env_preserves_parent_environment_values():
    env = build_codex_tui_child_env(
        base_env={"PATH": "/usr/bin", "HOME": "/Users/example"},
        cwd="/Users/example/Projects/onlineWorker",
        thread_id="tid-1",
    )

    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/Users/example"


def test_encode_terminal_input_wraps_message_and_enter():
    payload = encode_terminal_input("你好，继续")
    assert payload.startswith(b"\x1b[200~")
    assert payload.endswith(b"\x1b[201~\r")
    assert "你好，继续".encode("utf-8") in payload


def test_validate_thread_binding_rejects_other_thread():
    with pytest.raises(RuntimeError, match="当前 TUI 绑定 thread=tid-1"):
        validate_thread_binding(active_thread_id="tid-1", request_thread_id="tid-2")


def test_resolve_host_thread_id_prefers_explicit_thread_id(tmp_path):
    thread_id = resolve_host_thread_id(
        cwd="/Users/example/Projects/onlineWorker",
        data_dir=str(tmp_path),
        thread_id="tid-explicit",
    )
    assert thread_id == "tid-explicit"


def test_resolve_host_thread_id_rejects_topic_mapping_from_onlineworker_state(tmp_path):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=4586, archived=False)
    storage = AppStorage(workspaces={"codex:onlineWorker": ws})
    save_storage(storage, str(tmp_path / "onlineworker_state.json"))

    with pytest.raises(RuntimeError, match="不再从 onlineworker_state.json 按 topic_id 反查"):
        resolve_host_thread_id(
            cwd="/Users/example/Projects/onlineWorker",
            data_dir=str(tmp_path),
            topic_id=4586,
        )


def test_resolve_host_thread_id_does_not_revive_archived_topic_mapping(tmp_path, monkeypatch):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        topic_id=3230,
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=4586, archived=True, is_active=False)
    storage_path = tmp_path / "onlineworker_state.json"
    save_storage(AppStorage(workspaces={"codex:onlineWorker": ws}), str(storage_path))

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_host_runtime.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-1"},
        raising=False,
    )

    with pytest.raises(RuntimeError, match="不再从 onlineworker_state.json 按 topic_id 反查"):
        resolve_host_thread_id(
            cwd="/Users/example/Projects/onlineWorker",
            data_dir=str(tmp_path),
            topic_id=4586,
        )

    repaired = load_storage(str(storage_path))
    repaired_thread = repaired.workspaces["codex:onlineWorker"].threads["tid-1"]
    assert repaired_thread.archived is True
    assert repaired_thread.is_active is False


def test_resolve_host_thread_id_falls_back_to_latest_thread_for_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.tui_host_runtime.list_codex_threads_by_cwd",
        lambda cwd, limit=20: [{"id": "tid-latest", "preview": "latest", "updatedAt": 123}],
    )

    thread_id = resolve_host_thread_id(
        cwd="/Users/example/Projects/onlineWorker",
        data_dir=str(tmp_path),
    )

    assert thread_id == "tid-latest"
