from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter
from plugins.providers.builtin.claude.python.hook_bridge import (
    ONLINEWORKER_CLAUDE_HOOK_MARKER,
    build_claude_hook_command,
    default_claude_hook_response,
    install_onlineworker_claude_hooks,
    relay_claude_hook_payload,
    uninstall_onlineworker_claude_hooks,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_transcript(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_install_onlineworker_claude_hooks_creates_missing_settings_file(tmp_path: Path):
    data_dir = tmp_path / "data"
    settings_path = tmp_path / "claude" / "settings.json"

    result = install_onlineworker_claude_hooks(
        str(data_dir),
        settings_path=str(settings_path),
    )

    assert result["state"] == "installed"
    assert result["changed"] is True
    with settings_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    assert payload["hooks"]["PreToolUse"][0]["matcher"] == ""
    assert payload["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 5
    assert payload["hooks"]["PermissionRequest"][0]["hooks"][0]["timeout"] == 5
    assert "--claude-hook-managed" not in payload["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert payload["hooks"]["SessionStart"][0]["onlineworkerMarker"] == ONLINEWORKER_CLAUDE_HOOK_MARKER
    assert payload["hooks"]["UserPromptSubmit"][0]["hooks"][0]["timeout"] == 5


def test_claude_hook_command_marks_only_managed_settings_as_blocking(tmp_path: Path):
    external_command = build_claude_hook_command(str(tmp_path), managed_interactions=False)
    managed_command = build_claude_hook_command(str(tmp_path), managed_interactions=True)

    assert "claude_hook_relay.py" in external_command
    assert "--claude-hook-bridge" not in external_command
    assert "--claude-hook-managed" not in external_command
    assert "--claude-hook-bridge" in managed_command
    assert "--claude-hook-managed" in managed_command


def test_default_claude_hook_response_never_decides_cli_permissions():
    assert default_claude_hook_response({"hook_event_name": "PermissionRequest"}) == {}
    assert default_claude_hook_response({"hook_event_name": "PreToolUse", "tool_name": "Bash"}) == {}
    assert default_claude_hook_response({"hook_event_name": "PreToolUse", "tool_name": "Read"}) == {}
    assert default_claude_hook_response({"hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion"}) == {}


def test_install_and_uninstall_onlineworker_claude_hooks_preserve_unrelated_entries(tmp_path: Path):
    data_dir = tmp_path / "data"
    settings_path = tmp_path / "claude" / "settings.json"
    original_payload = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/usr/local/bin/legacy-claude-hook.sh",
                            "timeout": 5,
                        }
                    ],
                }
            ],
            "Notification": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'/Applications/LegacyHelper.app/Contents/Resources/LegacyHelper.bundle/legacy-claude-hook.sh' notification",
                            "timeout": 10,
                        }
                    ],
                }
            ],
        }
    }
    _write_json(settings_path, original_payload)

    first = install_onlineworker_claude_hooks(
        str(data_dir),
        settings_path=str(settings_path),
    )
    second = install_onlineworker_claude_hooks(
        str(data_dir),
        settings_path=str(settings_path),
    )

    assert first["state"] == "installed"
    assert second["state"] == "installed"
    assert second["changed"] is False

    with settings_path.open("r", encoding="utf-8") as f:
        installed_payload = json.load(f)
    assert installed_payload["hooks"]["SessionStart"][0] == original_payload["hooks"]["SessionStart"][0]
    assert installed_payload["hooks"]["Notification"][0] == original_payload["hooks"]["Notification"][0]
    assert installed_payload["hooks"]["SessionStart"][-1]["onlineworkerMarker"] == ONLINEWORKER_CLAUDE_HOOK_MARKER
    assert installed_payload["hooks"]["Notification"][-1]["onlineworkerMarker"] == ONLINEWORKER_CLAUDE_HOOK_MARKER

    uninstall = uninstall_onlineworker_claude_hooks(settings_path=str(settings_path))
    assert uninstall["state"] == "disabled"
    assert uninstall["changed"] is True

    with settings_path.open("r", encoding="utf-8") as f:
        removed_payload = json.load(f)
    assert removed_payload == original_payload


def test_install_onlineworker_claude_hooks_returns_install_failed_for_malformed_settings(tmp_path: Path):
    data_dir = tmp_path / "data"
    settings_path = tmp_path / "claude" / "settings.json"
    broken_text = '{"hooks": {"SessionStart": ['
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(broken_text, encoding="utf-8")

    result = install_onlineworker_claude_hooks(
        str(data_dir),
        settings_path=str(settings_path),
    )

    assert result["state"] == "install_failed"
    assert "无法解析" in result["detail"]
    assert settings_path.read_text(encoding="utf-8") == broken_text


@pytest.mark.asyncio
async def test_claude_adapter_user_prompt_submit_maps_to_session_and_turn_events(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-1",
            "cwd": str(tmp_path),
            "user_prompt": "继续 phase16",
            "transcript_path": str(tmp_path / "ses-1.jsonl"),
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "message.user.submitted",
        "turn/started",
    ]
    assert events[0][1]["workspace_id"] == "claude:onlineWorker"
    assert events[1][1]["message"]["params"]["text"] == "继续 phase16"
    assert events[2][1]["message"]["params"]["turn"]["threadId"] == "ses-1"


@pytest.mark.asyncio
async def test_claude_adapter_user_prompt_submit_accepts_prompt_alias(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-prompt",
            "cwd": str(tmp_path),
            "prompt": "走备用启动器",
            "transcript_path": str(tmp_path / "ses-prompt.jsonl"),
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "message.user.submitted",
        "turn/started",
    ]
    assert events[1][1]["message"]["params"]["text"] == "走备用启动器"


@pytest.mark.asyncio
async def test_claude_adapter_external_permission_request_mirrors_without_taking_over_cli(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-perm",
            "cwd": str(tmp_path),
            "user_prompt": "engine实现情况如何？",
            "transcript_path": str(tmp_path / "ses-perm.jsonl"),
        }
    )
    events.clear()

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "PermissionRequest",
            "session_id": "ses-perm",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": "git remote get-url origin 2>/dev/null",
                "description": "Check git remote URL",
            },
        }
    )

    assert response == {}
    assert len(events) == 1
    assert events[0][1]["message"]["method"] == "item/commandExecution/requestApproval"
    params = events[0][1]["message"]["params"]
    assert params["threadId"] == "ses-perm"
    assert params["command"] == "git remote get-url origin 2>/dev/null"
    assert params["prompt"] == "engine实现情况如何？"
    assert params["_mirroredOnly"] is True
    assert adapter._pending_hook_requests == {}


@pytest.mark.asyncio
async def test_claude_adapter_external_read_pretool_mirrors_without_registered_workspace(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "ses-read",
            "cwd": str(tmp_path),
            "tool_name": "Read",
            "tool_input": {
                "file_path": str(tmp_path / "settings.gradle"),
                "offset": 1,
                "limit": 80,
            },
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "item/commandExecution/requestApproval",
    ]
    assert events[0][1]["workspace_id"] == f"claude:{tmp_path}"
    params = events[1][1]["message"]["params"]
    assert params["_mirroredOnly"] is True
    assert params["command"] == f"Read({tmp_path / 'settings.gradle'} · lines 1-80)"
    assert adapter._pending_hook_requests == {}


@pytest.mark.asyncio
async def test_claude_adapter_external_non_approval_pretool_updates_running_activity(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:repo", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "ses-tool",
            "cwd": str(tmp_path),
            "tool_name": "Glob",
            "tool_input": {
                "pattern": "**/*.gradle",
                "path": str(tmp_path),
            },
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "item/started",
    ]
    params = events[1][1]["message"]["params"]
    assert params["item"]["text"] == "Glob: **/*.gradle"
    assert params["_mirroredOnly"] is True


@pytest.mark.asyncio
async def test_claude_adapter_external_posttool_clears_mirrored_attention(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:repo", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    await adapter.handle_hook_payload(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "ses-bash",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": "echo ok",
            },
        }
    )
    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "ses-bash",
            "cwd": str(tmp_path),
            "tool_name": "Bash",
            "tool_input": {
                "command": "echo ok",
            },
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "item/commandExecution/requestApproval",
        "item/completed",
    ]
    assert events[2][1]["message"]["params"]["item"]["text"] == "$ echo ok"


@pytest.mark.asyncio
async def test_claude_hook_relay_treats_unmanaged_clients_as_external_mirrors(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))
    data_dir = str(tmp_path / "data")
    await adapter.start_hook_bridge(data_dir)

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await asyncio.wait_for(
        relay_claude_hook_payload(
            data_dir,
            {
                "hook_event_name": "PermissionRequest",
                "session_id": "ses-relay",
                "cwd": str(tmp_path),
                "tool_name": "Bash",
                "tool_input": {
                    "command": "pwd",
                    "description": "检查当前目录",
                },
            },
            managed_interactions=False,
        ),
        timeout=1,
    )
    await asyncio.sleep(0.1)
    await adapter.disconnect()

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "session.created",
        "item/commandExecution/requestApproval",
    ]
    assert events[1][1]["message"]["params"]["_mirroredOnly"] is True
    assert adapter._pending_hook_requests == {}


@pytest.mark.asyncio
async def test_claude_adapter_session_end_emits_final_and_turn_completed_from_transcript(tmp_path: Path):
    transcript_path = tmp_path / "ses-1.jsonl"
    _write_transcript(
        transcript_path,
        [
            {
                "type": "user",
                "timestamp": "2026-06-06T10:00:00Z",
                "cwd": str(tmp_path),
                "message": {"content": "继续 phase16"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-06T10:00:05Z",
                "cwd": str(tmp_path),
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "最终回复",
                        }
                    ]
                },
            },
        ],
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-1",
            "cwd": str(tmp_path),
            "user_prompt": "继续 phase16",
            "transcript_path": str(transcript_path),
        }
    )
    start_turn_id = events[-1][1]["message"]["params"]["turn"]["id"]
    events.clear()

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "SessionEnd",
            "session_id": "ses-1",
            "cwd": str(tmp_path),
            "transcript_path": str(transcript_path),
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "item/completed",
        "turn/completed",
    ]
    assert events[0][1]["message"]["params"]["item"]["text"] == "最终回复"
    assert events[0][1]["message"]["params"]["item"]["turn"]["id"] == start_turn_id
    assert events[1][1]["message"]["params"]["turn"]["id"] == start_turn_id


@pytest.mark.asyncio
async def test_claude_adapter_session_end_completes_turn_when_final_text_unavailable(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-no-final",
            "cwd": str(tmp_path),
            "user_prompt": "只验证结束态",
            "transcript_path": str(tmp_path / "missing.jsonl"),
        }
    )
    start_turn_id = events[-1][1]["message"]["params"]["turn"]["id"]
    events.clear()

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "SessionEnd",
            "session_id": "ses-no-final",
            "cwd": str(tmp_path),
            "transcript_path": str(tmp_path / "missing.jsonl"),
        }
    )

    assert response == {}
    assert [event[1]["message"]["method"] for event in events] == ["turn/completed"]
    assert events[0][1]["message"]["params"]["turn"]["id"] == start_turn_id


@pytest.mark.asyncio
async def test_claude_adapter_terminal_hooks_are_idempotent_across_stop_and_session_end(tmp_path: Path):
    transcript_path = tmp_path / "ses-dup.jsonl"
    _write_transcript(
        transcript_path,
        [
            {
                "type": "user",
                "timestamp": "2026-06-06T10:00:00Z",
                "cwd": str(tmp_path),
                "message": {"content": "继续 phase16"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-06-06T10:00:05Z",
                "cwd": str(tmp_path),
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "最终回复",
                        }
                    ]
                },
            },
        ],
    )

    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-dup",
            "cwd": str(tmp_path),
            "prompt": "继续 phase16",
            "transcript_path": str(transcript_path),
        }
    )
    events.clear()

    stop_response, session_end_response = await asyncio.gather(
        adapter.handle_hook_payload(
            {
                "hook_event_name": "Stop",
                "session_id": "ses-dup",
                "cwd": str(tmp_path),
                "last_assistant_message": "最终回复",
                "transcript_path": str(transcript_path),
            }
        ),
        adapter.handle_hook_payload(
            {
                "hook_event_name": "SessionEnd",
                "session_id": "ses-dup",
                "cwd": str(tmp_path),
                "reason": "other",
                "transcript_path": str(transcript_path),
            }
        ),
    )

    assert stop_response == {}
    assert session_end_response == {}
    assert [event[1]["message"]["method"] for event in events] == [
        "item/completed",
        "turn/completed",
    ]


@pytest.mark.asyncio
async def test_claude_adapter_ignores_lifecycle_hooks_for_managed_active_process(tmp_path: Path):
    adapter = ClaudeAdapter(claude_bin="claude")
    await adapter.connect()
    adapter.register_workspace_cwd("claude:onlineWorker", str(tmp_path))
    adapter._active_processes["ses-1"] = object()

    events = []

    async def on_event(method, params):
        events.append((method, params))

    adapter.on_event(on_event)

    response = await adapter.handle_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ses-1",
            "cwd": str(tmp_path),
            "user_prompt": "继续 phase16",
        }
    )

    assert response == {}
    assert events == []
