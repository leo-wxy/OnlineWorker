import asyncio
import json
import os
from unittest.mock import AsyncMock

import pytest


class FakeAuthProcess:
    def __init__(self, payload: str, returncode: int = 0):
        self.returncode = returncode
        self._payload = payload

    async def communicate(self):
        return (self._payload, "")


class FakeMainProcess:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.stdout = FakeStreamReader([])
        self.stderr = FakeStreamReader([])

    async def communicate(self):
        return (self._stdout, self._stderr)

    async def wait(self):
        return self.returncode


class FakeStreamReader:
    def __init__(self, lines: list[str]):
        self._lines = [line.encode("utf-8") for line in lines]
        self._index = 0

    async def readline(self):
        if self._index >= len(self._lines):
            return b""
        value = self._lines[self._index]
        self._index += 1
        return value

    async def read(self):
        if self._index >= len(self._lines):
            return b""
        remaining = b"".join(self._lines[self._index :])
        self._index = len(self._lines)
        return remaining


class FakeStreamingProcess:
    def __init__(self, stdout_lines: list[str], stderr_lines: list[str] | None = None, returncode: int = 0):
        self.returncode = returncode
        self.stdout = FakeStreamReader(stdout_lines)
        self.stderr = FakeStreamReader(stderr_lines or [])

    async def wait(self):
        return self.returncode


@pytest.fixture(autouse=True)
def clear_claude_auth_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)


def test_resolve_claude_bin_prefers_homebrew_binary_over_stale_local(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import resolve_claude_bin

    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.PREFERRED_CLAUDE_BINARIES", ("/opt/homebrew/bin/claude",))
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.path.isfile", lambda path: path in {
        "/opt/homebrew/bin/claude",
        "/Users/example/.local/bin/claude",
    })
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.access", lambda path, mode: True)
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.shutil.which", lambda name: "/Users/example/.local/bin/claude")

    assert resolve_claude_bin("claude") == "/opt/homebrew/bin/claude"


def test_resolve_claude_bin_preserves_explicit_path(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import resolve_claude_bin

    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.shutil.which", lambda name: "/opt/homebrew/bin/claude")

    assert resolve_claude_bin("/custom/bin/claude") == "/custom/bin/claude"


def test_resolve_preferred_node_bin_dir_prefers_latest_supported_nvm(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import resolve_preferred_node_bin_dir

    node18 = "/Users/example/.nvm/versions/node/v18.20.4/bin/node"
    node20 = "/Users/example/.nvm/versions/node/v20.20.1/bin/node"
    node22 = "/Users/example/.nvm/versions/node/v22.1.0/bin/node"

    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.glob.glob", lambda pattern: [node18, node20, node22])
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.os.path.isfile",
        lambda path: path in {node18, node20, node22},
    )
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.access", lambda path, mode: True)
    monkeypatch.setenv("NVM_BIN", "/Users/example/.nvm/versions/node/v18.20.4/bin")

    assert resolve_preferred_node_bin_dir() == "/Users/example/.nvm/versions/node/v22.1.0/bin"


def test_resolve_preferred_node_bin_dir_falls_back_to_current_nvm_bin(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import resolve_preferred_node_bin_dir

    current_nvm_bin = "/Users/example/.nvm/versions/node/v18.20.4/bin"
    current_node = f"{current_nvm_bin}/node"

    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.glob.glob", lambda pattern: [])
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.path.isfile", lambda path: path == current_node)
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.access", lambda path, mode: True)
    monkeypatch.setenv("NVM_BIN", current_nvm_bin)

    assert resolve_preferred_node_bin_dir() == current_nvm_bin


def test_inspect_claude_thread_busy_state_detects_recent_tool_activity():
    from plugins.providers.builtin.claude.python.adapter import inspect_claude_thread_busy_state

    now_ms = 1_776_048_270_000
    rows = [
        {
            "type": "queue-operation",
            "timestamp": "2026-04-13T02:43:50.088Z",
            "cwd": "/Users/example/Projects/sample-project",
            "entrypoint": "sdk-cli",
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-13T02:43:55.088Z",
            "cwd": "/Users/example/Projects/sample-project/Demo/Android",
            "entrypoint": "sdk-cli",
            "message": {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "name": "Bash"}],
            },
        },
    ]

    from unittest.mock import patch

    with patch("plugins.providers.builtin.claude.python.adapter._iter_claude_project_rows", return_value=iter(rows)):
        result = inspect_claude_thread_busy_state(
            session_file="/tmp/ses.jsonl",
            now_ms=now_ms,
            recent_window_ms=10 * 60 * 1000,
            sample_limit=10,
        )

    assert result["busy"] is True
    assert "assistant_tool_use" in result["signals"]
    assert "queue" in result["signals"]
    assert "Claude thread 仍在忙碌中" in result["message"]


def test_inspect_claude_thread_busy_state_ignores_tool_result_without_other_recent_signals():
    from plugins.providers.builtin.claude.python.adapter import inspect_claude_thread_busy_state

    now_ms = 1_776_322_500_000
    rows = [
        {
            "type": "assistant",
            "timestamp": "2026-04-16T06:42:03.698Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
            "message": {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "name": "Write"}],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-04-16T06:50:40.558Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
            "toolUseResult": (
                "Error: Claude requested permissions to write to "
                "/Users/example/Downloads/hello.txt, but you haven't granted it yet."
            ),
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": (
                            "Claude requested permissions to write to "
                            "/Users/example/Downloads/hello.txt, but you haven't granted it yet."
                        ),
                        "is_error": True,
                    }
                ],
            },
        },
    ]

    from unittest.mock import patch

    with patch("plugins.providers.builtin.claude.python.adapter._iter_claude_project_rows", return_value=iter(rows)):
        result = inspect_claude_thread_busy_state(
            session_file="/tmp/ses.jsonl",
            now_ms=now_ms,
            recent_window_ms=5 * 60 * 1000,
            sample_limit=10,
        )

    assert result["busy"] is False
    assert result["latest_ts"] == 1_776_322_240_558


def test_inspect_claude_thread_busy_state_ignores_recent_activity_after_end_turn_completion():
    from plugins.providers.builtin.claude.python.adapter import inspect_claude_thread_busy_state

    now_ms = 1_776_323_100_000
    rows = [
        {
            "type": "queue-operation",
            "timestamp": "2026-04-16T07:18:23.302Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-16T07:18:29.267Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
            "message": {
                "stop_reason": "tool_use",
                "content": [{"type": "tool_use", "name": "Bash"}],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-04-16T07:18:34.735Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
            "toolUseResult": {
                "stdout": "",
                "stderr": "",
                "interrupted": False,
                "isImage": False,
                "noOutputExpected": False,
            },
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": "(Bash completed with no output)",
                        "is_error": False,
                    }
                ],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-16T07:18:39.163Z",
            "cwd": "/Users/example/Projects/onlineWorker",
            "entrypoint": "sdk-cli",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": "文件已创建！/Users/example/Downloads/hello.txt",
                    }
                ],
            },
        },
    ]

    from unittest.mock import patch

    with patch("plugins.providers.builtin.claude.python.adapter._iter_claude_project_rows", return_value=iter(rows)):
        result = inspect_claude_thread_busy_state(
            session_file="/tmp/ses.jsonl",
            now_ms=now_ms,
            recent_window_ms=5 * 60 * 1000,
            sample_limit=10,
        )

    assert result["busy"] is False
    assert result["latest_ts"] == 1_776_323_919_163


@pytest.mark.asyncio
async def test_claude_adapter_lists_threads_from_local_facts(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.list_claude_threads_by_cwd",
        lambda cwd, limit=20: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
    )

    result = await adapter.list_threads("claude:onlineWorker", limit=20)

    assert result == [
        {
            "id": "ses-1",
            "preview": "继续 phase16",
            "createdAt": 2000,
            "updatedAt": 2100,
        }
    ]


@pytest.mark.asyncio
async def test_claude_adapter_send_user_message_emits_minimal_turn_events(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    create_process = AsyncMock(
        side_effect=[
            FakeAuthProcess('{"loggedIn": true, "authMethod": "subscription", "apiProvider": "firstParty"}'),
            FakeStreamingProcess(
                stdout_lines=[
                    '{"type":"stream_event","event":{"type":"message_start","message":{"id":"msg_1","content":[]}}}\n',
                    '{"type":"stream_event","event":{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}}\n',
                    '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"最终"}}}\n',
                    '{"type":"stream_event","event":{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"回复"}}}\n',
                    '{"type":"assistant","message":{"id":"msg_1","content":[{"type":"text","text":"最终回复"}]}}\n',
                    '{"type":"result","subtype":"success","is_error":false,"result":"最终回复"}\n',
                ],
            ),
        ]
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert create_process.await_count == 2
    assert result["threadId"] == "ses-1"
    assert result["status"] == "completed"
    assert [event[0] for event in events] == [
        "app-server-event",
        "app-server-event",
        "app-server-event",
        "app-server-event",
        "app-server-event",
    ]
    assert events[0][1]["message"]["method"] == "turn/started"
    assert events[1][1]["message"]["method"] == "item/agentMessage/delta"
    assert events[1][1]["message"]["params"]["delta"] == "最终"
    assert events[2][1]["message"]["method"] == "item/agentMessage/delta"
    assert events[2][1]["message"]["params"]["delta"] == "回复"
    assert events[3][1]["message"]["method"] == "item/completed"
    assert events[3][1]["message"]["params"]["item"]["text"] == "最终回复"
    assert events[4][1]["message"]["method"] == "turn/completed"
    assert events[4][1]["message"]["params"]["turn"]["status"] == "completed"


@pytest.mark.asyncio
async def test_claude_adapter_resumes_existing_session_with_resume_flag(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:ncmplayerengine", "/Users/example/Projects/sample-project")

    create_process = AsyncMock(
        side_effect=[
            FakeAuthProcess('{"loggedIn": true, "authMethod": "proxyEnv"}'),
            FakeMainProcess("最终回复"),
        ]
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter._find_claude_project_session_file",
        lambda session_id: f"/tmp/{session_id}.jsonl",
    )

    result = await adapter.send_user_message(
        "claude:ncmplayerengine",
        "ses-existing",
        "继续",
    )

    assert result["status"] == "completed"
    second_call_args = create_process.await_args_list[1].args
    assert second_call_args[:8] == (
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--resume",
        "ses-existing",
    )


@pytest.mark.asyncio
async def test_claude_adapter_uses_session_id_flag_for_new_session(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    create_process = AsyncMock(
        side_effect=[
            FakeAuthProcess('{"loggedIn": true, "authMethod": "proxyEnv"}'),
            FakeMainProcess("最终回复"),
        ]
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter._find_claude_project_session_file",
        lambda session_id: None,
    )

    result = await adapter.send_user_message(
        "claude:onlineWorker",
        "ses-new",
        "继续",
    )

    assert result["status"] == "completed"
    second_call_args = create_process.await_args_list[1].args
    assert second_call_args[:8] == (
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--session-id",
        "ses-new",
    )


@pytest.mark.asyncio
async def test_claude_adapter_marks_env_auth_as_ready(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3031")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    adapter = ClaudeAdapter(claude_bin="claude")

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is True
    assert status["authMethod"] == "apiKeyEnv"
    assert adapter.auth_ready is True
    assert adapter.auth_method == "apiKeyEnv"


@pytest.mark.asyncio
async def test_claude_adapter_marks_proxy_env_without_api_key_as_ready(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3031")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    adapter = ClaudeAdapter(claude_bin="claude")

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is True
    assert status["authMethod"] == "proxyEnv"
    assert adapter.auth_ready is True
    assert adapter.auth_method == "proxyEnv"


@pytest.mark.asyncio
async def test_claude_adapter_injects_dummy_api_key_for_proxy_env(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3031")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    monkeypatch.setenv("PATH", "/Users/example/.nvm/versions/node/v18.20.4/bin:/opt/homebrew/bin:/usr/bin:/bin")
    monkeypatch.setenv("NVM_BIN", "/Users/example/.nvm/versions/node/v18.20.4/bin")
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-from-app")

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    captured_env = {}
    captured_kwargs = {}

    async def fake_create_process(*args, **kwargs):
        captured_kwargs.update(kwargs)
        captured_env.update(kwargs.get("env") or {})
        return FakeMainProcess("OK")

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        fake_create_process,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.glob.glob",
        lambda pattern: ["/Users/example/.nvm/versions/node/v20.20.1/bin/node"],
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.os.path.isfile",
        lambda path: path in {
            "/Users/example/.nvm/versions/node/v20.20.1/bin/node",
        },
    )
    monkeypatch.setattr("plugins.providers.builtin.claude.python.adapter.os.access", lambda path, mode: True)

    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert result["status"] == "completed"
    assert captured_env["ANTHROPIC_API_KEY"] == "dummy"
    assert captured_env["ANTHROPIC_BASE_URL"] == "http://localhost:3031"
    assert captured_env["ANTHROPIC_MODEL"] == "claude-opus-4-6"
    assert captured_env["NVM_BIN"] == "/Users/example/.nvm/versions/node/v20.20.1/bin"
    assert captured_env["PATH"].startswith("/Users/example/.nvm/versions/node/v20.20.1/bin:")
    assert "CODEX_CI" not in captured_env
    assert "CODEX_THREAD_ID" not in captured_env
    assert captured_kwargs["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_claude_adapter_send_user_message_rejects_when_not_authenticated(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    with pytest.raises(RuntimeError, match="未鉴权"):
        await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    create_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_adapter_permission_request_roundtrip_via_hook_payload():
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "ses-1",
        "cwd": "/Users/example/Projects/onlineWorker",
        "tool_name": "Bash",
        "tool_input": {
            "command": "pwd",
            "description": "检查当前目录",
        },
    }

    response_task = asyncio.create_task(adapter.handle_hook_payload(payload))
    await asyncio.sleep(0)

    assert len(events) == 1
    method, params = events[0]
    assert method == "app-server-event"
    assert params["message"]["method"] == "item/commandExecution/requestApproval"
    event_params = params["message"]["params"]
    assert event_params["threadId"] == "ses-1"
    assert event_params["command"] == "pwd"
    assert event_params["reason"] == "检查当前目录"
    assert event_params["_provider"] == "claude"

    request_id = event_params["request_id"]
    await adapter.reply_server_request(
        "claude:onlineWorker",
        request_id,
        {"behavior": "allow"},
    )
    response = await response_task

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


@pytest.mark.asyncio
async def test_claude_adapter_pretool_allow_always_applies_session_tool_allowlist():
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "ses-1",
        "cwd": "/Users/example/Projects/onlineWorker",
        "tool_name": "Bash",
        "tool_input": {
            "command": "pwd",
            "description": "检查当前目录",
        },
    }

    response_task = asyncio.create_task(adapter.handle_hook_payload(payload))
    await asyncio.sleep(0)

    request_id = events[0][1]["message"]["params"]["request_id"]
    await adapter.reply_server_request(
        "claude:onlineWorker",
        request_id,
        {"behavior": "allow", "scope": "session"},
    )
    response = await response_task

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }

    auto_allowed = await adapter.handle_hook_payload(payload)
    assert auto_allowed == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    assert len(events) == 1


@pytest.mark.asyncio
async def test_claude_adapter_ask_user_question_roundtrip_with_multiselect():
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", "/Users/example/Projects/onlineWorker")

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "ses-1",
        "cwd": "/Users/example/Projects/onlineWorker",
        "tool_name": "AskUserQuestion",
        "tool_input": {
            "questions": [
                {
                    "header": "语言偏好",
                    "question": "你希望我用哪些语言回复？",
                    "options": [
                        {"label": "Python", "description": "通用"},
                        {"label": "Rust", "description": "系统"},
                    ],
                    "multiSelect": True,
                }
            ]
        },
    }

    response_task = asyncio.create_task(adapter.handle_hook_payload(payload))
    await asyncio.sleep(0)

    assert len(events) == 1
    method, params = events[0]
    assert method == "app-server-event"
    assert params["message"]["method"] == "question/asked"
    event_params = params["message"]["params"]
    assert event_params["threadId"] == "ses-1"
    assert event_params["header"] == "语言偏好"
    assert event_params["question"] == "你希望我用哪些语言回复？"
    assert event_params["multiple"] is True
    assert event_params["questionId"]

    await adapter.reply_question(
        event_params["questionId"],
        [["Python", "Rust"]],
    )
    response = await response_task

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "questions": [
                    {
                        "header": "语言偏好",
                        "question": "你希望我用哪些语言回复？",
                        "options": [
                            {"label": "Python", "description": "通用"},
                            {"label": "Rust", "description": "系统"},
                        ],
                        "multiSelect": True,
                    }
                ],
                "answers": {
                    "你希望我用哪些语言回复？": "Python,Rust",
                },
            },
        }
    }


@pytest.mark.asyncio
async def test_claude_adapter_start_hook_bridge_writes_settings_and_send_argv(tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    await adapter.start_hook_bridge(str(tmp_path))

    settings_path = adapter.hook_settings_path
    socket_path = adapter.hook_socket_path

    assert settings_path is not None
    assert socket_path is not None
    assert os.path.exists(settings_path)

    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    pretool_hooks = settings["hooks"]["PreToolUse"]
    notification_hooks = settings["hooks"]["Notification"]
    assert pretool_hooks[0]["matcher"] == "Bash|Edit|Write|AskUserQuestion|ExitPlanMode"
    assert pretool_hooks[0]["hooks"][0]["timeout"] == 86400
    assert notification_hooks[0]["hooks"][0]["timeout"] == 86400
    assert "--claude-hook-bridge" in pretool_hooks[0]["hooks"][0]["command"]
    assert str(tmp_path) in pretool_hooks[0]["hooks"][0]["command"]

    argv = adapter._build_send_argv("ses-1", "继续")
    assert "--settings" in argv
    assert "--setting-sources" in argv
    sources_index = argv.index("--setting-sources")
    assert argv[sources_index + 1] == "project,local"
    settings_index = argv.index("--settings")
    assert argv[settings_index + 1] == settings_path

    await adapter.disconnect()
