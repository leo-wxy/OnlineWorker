import asyncio
import json
import os
import time
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


class SlowStreamingProcess:
    def __init__(self, stdout_lines: list[str], release_event: asyncio.Event, returncode: int = 0):
        self.returncode = returncode
        self.stdout = FakeStreamReader(stdout_lines)
        self.stderr = FakeStreamReader([])
        self._release_event = release_event

    async def wait(self):
        await self._release_event.wait()
        return self.returncode


@pytest.fixture(autouse=True)
def clear_claude_auth_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)


def register_existing_workspace(adapter, workspace_id: str, tmp_path, name: str = "onlineWorker"):
    workspace = tmp_path / name
    workspace.mkdir(parents=True, exist_ok=True)
    adapter.register_workspace_cwd(workspace_id, str(workspace))
    return workspace


def test_resolve_claude_bin_preserves_bare_command_for_path_resolution():
    from plugins.providers.builtin.claude.python.adapter import (
        resolve_claude_bin,
        resolve_claude_command_prefix,
    )

    assert resolve_claude_bin("claude") == "claude"
    assert resolve_claude_command_prefix("claude") == ["claude"]


def test_resolve_claude_bin_preserves_explicit_path():
    from plugins.providers.builtin.claude.python.adapter import resolve_claude_bin

    assert resolve_claude_bin("/custom/bin/claude") == "/custom/bin/claude"


def test_claude_adapter_build_send_argv_preserves_launcher_prefix():
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="ow-claude-launcher claude")

    assert adapter._build_send_argv("ses-1", "继续") == [
        "ow-claude-launcher",
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--session-id",
        "ses-1",
        "继续",
    ]


def test_resolve_claude_command_prefix_supports_quoted_launcher_path():
    from plugins.providers.builtin.claude.python.adapter import resolve_claude_command_prefix

    assert resolve_claude_command_prefix('"/Applications/Claude Wrapper/bin/launch" claude') == [
        "/Applications/Claude Wrapper/bin/launch",
        "claude",
    ]


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
async def test_claude_adapter_send_user_message_emits_minimal_turn_events(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    create_process = AsyncMock(
        side_effect=[
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

    assert create_process.await_count == 1
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
async def test_claude_adapter_send_user_message_renders_attachment_paths(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    create_process = AsyncMock(
        return_value=FakeStreamingProcess(
            stdout_lines=[
                '{"type":"result","subtype":"success","is_error":false,"result":"ok"}\n',
            ],
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await adapter.send_user_message(
        "claude:onlineWorker",
        "ses-1",
        "请根据附件回答",
        attachments=[
            {
                "kind": "image",
                "path": "/tmp/ow-attachments/photo.jpg",
                "name": "photo.jpg",
                "mime_type": "image/jpeg",
            },
            {
                "kind": "file",
                "path": "/tmp/ow-attachments/report.pdf",
                "name": "report.pdf",
                "mime_type": "application/pdf",
            },
        ],
    )

    assert result["status"] == "completed"
    prompt = create_process.await_args.args[-1]
    assert "用户附带了以下本地附件" in prompt
    assert "1. 图片" in prompt
    assert "path: /tmp/ow-attachments/photo.jpg" in prompt
    assert "name: photo.jpg" in prompt
    assert "mime_type: image/jpeg" in prompt
    assert "2. 文件" in prompt
    assert "path: /tmp/ow-attachments/report.pdf" in prompt
    assert "name: report.pdf" in prompt
    assert "mime_type: application/pdf" in prompt
    assert "用户消息：" in prompt
    assert "请根据附件回答" in prompt


@pytest.mark.asyncio
async def test_claude_adapter_uses_larger_subprocess_stream_limit_for_send(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    create_process = AsyncMock(
        return_value=FakeStreamingProcess(
            stdout_lines=[
                '{"type":"result","subtype":"success","is_error":false,"result":"ok"}\n',
            ],
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert result["status"] == "completed"
    assert create_process.await_args.kwargs["limit"] >= 1024 * 1024


@pytest.mark.asyncio
async def test_claude_adapter_serializes_sends_for_same_session(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    release_first = asyncio.Event()
    first_spawned = asyncio.Event()
    launches: list[tuple[str, float]] = []

    async def fake_create_process(*args, **kwargs):
        prompt = str(args[-1])
        launches.append((prompt, time.monotonic()))
        if prompt == "first":
            first_spawned.set()
            return SlowStreamingProcess(
                ['{"type":"result","subtype":"success","is_error":false,"result":"first ok"}\n'],
                release_first,
            )
        return FakeStreamingProcess(
            stdout_lines=[
                '{"type":"result","subtype":"success","is_error":false,"result":"second ok"}\n',
            ],
        )

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        fake_create_process,
    )

    first_task = asyncio.create_task(
        adapter.send_user_message("claude:onlineWorker", "ses-1", "first")
    )
    await asyncio.wait_for(first_spawned.wait(), timeout=1)

    second_task = asyncio.create_task(
        adapter.send_user_message("claude:onlineWorker", "ses-1", "second")
    )
    await asyncio.sleep(0.02)

    assert [prompt for prompt, _ in launches] == ["first"]

    release_first.set()
    first_result, second_result = await asyncio.gather(first_task, second_task)

    assert first_result["status"] == "completed"
    assert second_result["status"] == "completed"
    assert [prompt for prompt, _ in launches] == ["first", "second"]
    assert launches[1][1] >= launches[0][1]


@pytest.mark.asyncio
async def test_claude_adapter_resumes_existing_session_with_resume_flag(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.resolve_claude_bin",
        lambda claude_bin: claude_bin,
    )
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:ncmplayerengine", tmp_path, "sample-project")

    create_process = AsyncMock(
        side_effect=[
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
    send_call_args = create_process.await_args.args
    assert send_call_args[:8] == (
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
async def test_claude_adapter_uses_session_id_flag_for_new_session(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.resolve_claude_bin",
        lambda claude_bin: claude_bin,
    )
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    create_process = AsyncMock(
        side_effect=[
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
    send_call_args = create_process.await_args.args
    assert send_call_args[:8] == (
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
async def test_claude_adapter_rejects_missing_workspace_cwd_before_send(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    missing_workspace = tmp_path / "deleted-onlineWorker"
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(missing_workspace))

    async def fail_if_spawned(*args, **kwargs):
        raise AssertionError("send should fail before spawning claude")

    create_process = AsyncMock(side_effect=fail_if_spawned)
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    with pytest.raises(RuntimeError, match="Claude workspace cwd 不存在"):
        await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    create_process.assert_not_awaited()


@pytest.mark.asyncio
async def test_claude_adapter_uses_cli_auth_status_instead_of_provider_auth(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.resolve_claude_bin",
        lambda claude_bin: claude_bin,
    )
    adapter = ClaudeAdapter(
        claude_bin="claude",
        auth={
            "key": "dummy",
            "base_url": "https://config.example.test/langbase",
            "model": "claude-opus-4-6",
        },
    )
    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": true, "authMethod": "subscription", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is True
    assert status["authMethod"] == "subscription"
    assert adapter.auth_ready is True
    assert adapter.auth_method == "subscription"
    create_process.assert_awaited_once()
    assert create_process.await_args.args[:3] == ("claude", "auth", "status")
    assert create_process.await_args.kwargs["stdin"] == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_claude_adapter_does_not_treat_provider_proxy_config_as_auth_ready(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(
        claude_bin="claude",
        auth={
            "base_url": "https://config.example.test/langbase",
            "model": "claude-opus-4-6",
        },
    )
    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is False
    assert status["authMethod"] == "none"
    assert adapter.auth_ready is False
    assert adapter.auth_method == "none"
    create_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_adapter_auth_status_uses_runtime_env_without_cli_login(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://process.example.test/langbase")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "process-model")
    adapter = ClaudeAdapter(claude_bin="claude", auth={"base_url": "https://config.example.test/langbase"})

    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    status = await adapter.refresh_auth_status()

    assert status == {"loggedIn": True, "authMethod": "proxyEnv"}
    create_process.assert_not_awaited()


@pytest.mark.asyncio
async def test_claude_adapter_auth_status_uses_launcher_prefix(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="ow-claude-launcher claude")

    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": true, "authMethod": "oauth_token", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is True
    assert create_process.await_args.args[:4] == ("ow-claude-launcher", "claude", "auth", "status")


@pytest.mark.asyncio
async def test_claude_adapter_preserves_valid_runtime_env_when_sending(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("PATH", "/Users/example/.nvm/versions/node/v18.20.4/bin:/opt/homebrew/bin:/usr/bin:/bin")
    monkeypatch.setenv("NVM_BIN", "/Users/example/.nvm/versions/node/v18.20.4/bin")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://process.example.test/langbase")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "process-model")
    monkeypatch.setenv("CODEX_CI", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-from-app")

    adapter = ClaudeAdapter(
        claude_bin="claude",
        auth={
            "base_url": "https://config.example.test/langbase",
            "model": "claude-opus-4-6",
        },
    )
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

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
    assert "ANTHROPIC_API_KEY" not in captured_env
    assert captured_env["ANTHROPIC_BASE_URL"] == "https://process.example.test/langbase"
    assert captured_env["ANTHROPIC_AUTH_TOKEN"] == "process-token"
    assert captured_env["ANTHROPIC_MODEL"] == "process-model"
    assert captured_env["NVM_BIN"] == "/Users/example/.nvm/versions/node/v20.20.1/bin"
    assert captured_env["PATH"].startswith("/Users/example/.nvm/versions/node/v20.20.1/bin:")
    assert "CODEX_CI" not in captured_env
    assert "CODEX_THREAD_ID" not in captured_env
    assert captured_kwargs["stdin"] == asyncio.subprocess.DEVNULL


def test_claude_adapter_build_env_ignores_onlineworker_config_auth(tmp_path, monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://process.example.test/langbase")
    monkeypatch.setenv("ANTHROPIC_MODEL", "process-model")
    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
providers:
  claude:
    auth:
      base_url: https://langbase.example.test/langbase
      auth_token: token-123
      model: claude-opus-4-6
""",
        encoding="utf-8",
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    adapter._hook_data_dir = str(tmp_path)

    env = adapter._build_claude_env()

    assert env["ANTHROPIC_BASE_URL"] == "https://process.example.test/langbase"
    assert env["ANTHROPIC_MODEL"] == "process-model"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["ANTHROPIC_API_KEY"] == "dummy"


def test_claude_adapter_build_env_uses_process_claude_env(tmp_path, monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://process.example.test/langbase")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "process-token")
    monkeypatch.setenv("ANTHROPIC_MODEL", "process-model")
    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
providers:
  claude:
    auth:
      base_url: ""
      auth_token: ""
      model: ""
""",
        encoding="utf-8",
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    adapter._hook_data_dir = str(tmp_path)

    env = adapter._build_claude_env()

    assert env["ANTHROPIC_BASE_URL"] == "https://process.example.test/langbase"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "process-token"
    assert env["ANTHROPIC_MODEL"] == "process-model"


@pytest.mark.asyncio
async def test_claude_adapter_does_not_treat_current_config_auth_token_as_ready(tmp_path, monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
providers:
  claude:
    auth:
      auth_token: token-123
""",
        encoding="utf-8",
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    adapter._hook_data_dir = str(tmp_path)
    create_process = AsyncMock(
        return_value=FakeAuthProcess(
            '{"loggedIn": false, "authMethod": "none", "apiProvider": "firstParty"}'
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    status = await adapter.refresh_auth_status()

    assert status["loggedIn"] is False
    assert status["authMethod"] == "none"
    assert adapter.auth_ready is False
    assert adapter.auth_method == "none"
    create_process.assert_awaited_once()


def test_claude_adapter_ignores_data_dir_env_file_for_claude_runtime(tmp_path, monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "ANTHROPIC_BASE_URL=https://env.example.test/langbase\n"
        "ANTHROPIC_AUTH_TOKEN=env-token\n"
        "ANTHROPIC_MODEL=env-model\n",
        encoding="utf-8",
    )
    (tmp_path / "config.yaml").write_text(
        """
schema_version: 2
providers:
  claude:
    auth:
      base_url: https://config.example.test/langbase
      auth_token: config-token
      model: config-model
""",
        encoding="utf-8",
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    adapter._hook_data_dir = str(tmp_path)

    env = adapter._build_claude_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_MODEL" not in env


def test_claude_adapter_build_env_ignores_active_claude_process_env(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    env = ClaudeAdapter(claude_bin="claude")._build_claude_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_MODEL" not in env


def test_claude_adapter_does_not_scan_active_claude_process_env(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

    env = ClaudeAdapter(claude_bin="claude")._build_claude_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_MODEL" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_claude_adapter_rejects_stale_localhost_runtime_env(monkeypatch):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:3031")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")

    env = ClaudeAdapter(claude_bin="claude")._build_claude_env()

    assert "ANTHROPIC_BASE_URL" not in env
    assert "ANTHROPIC_MODEL" not in env
    assert "ANTHROPIC_API_KEY" not in env


@pytest.mark.asyncio
async def test_claude_adapter_reports_cli_auth_failure_from_send_error(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    create_process = AsyncMock(
        return_value=FakeStreamingProcess(
            stdout_lines=[],
            stderr_lines=["not logged in"],
            returncode=1,
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert result["status"] == "error"
    assert result["error"] == "not logged in"
    create_process.assert_awaited_once()


@pytest.mark.asyncio
async def test_claude_adapter_does_not_discover_launcher_from_claude_settings(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)

    create_process = AsyncMock(
        return_value=FakeStreamingProcess(
            stdout_lines=[],
            stderr_lines=["not logged in"],
            returncode=1,
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert result["status"] == "error"
    assert result["error"] == "not logged in"
    create_process.assert_awaited_once()
    assert create_process.await_args.args[:2] == ("claude", "-p")


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


@pytest.mark.asyncio
async def test_claude_adapter_starts_hook_bridge_lazily_on_send(monkeypatch, tmp_path):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    register_existing_workspace(adapter, "claude:onlineWorker", tmp_path)
    adapter.configure_hook_bridge(str(tmp_path / "data"))

    create_process = AsyncMock(
        return_value=FakeStreamingProcess(
            stdout_lines=[
                '{"type":"result","subtype":"success","is_error":false,"result":"ok"}\n',
            ],
        )
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.adapter.asyncio.create_subprocess_exec",
        create_process,
    )

    assert adapter.hook_settings_path is None
    result = await adapter.send_user_message("claude:onlineWorker", "ses-1", "继续")

    assert result["status"] == "completed"
    settings_path = adapter.hook_settings_path
    assert settings_path is not None
    send_call_args = create_process.await_args.args
    assert "--settings" in send_call_args
    assert send_call_args[send_call_args.index("--settings") + 1] == settings_path

    await adapter.disconnect()
