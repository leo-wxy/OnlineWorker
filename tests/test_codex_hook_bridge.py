import asyncio

import pytest

from plugins.providers.builtin.codex.python.hook_bridge import CodexHookBridge, merge_codex_hook_settings
from core.state import AppState, PendingApproval
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from bot.handlers.message import make_callback_handler


GROUP_CHAT_ID = -100123456789


def test_merge_codex_hook_settings_only_replaces_permission_request():
    existing = {
        "hooks": {
            "Notification": [{"matcher": "", "hooks": [{"type": "command", "command": "old"}]}],
            "PermissionRequest": [{"matcher": "", "hooks": [{"type": "command", "command": "bad"}]}],
        },
        "other": {"keep": True},
    }

    merged = merge_codex_hook_settings(existing, "/tmp/onlineworker --codex-hook-bridge")

    assert merged["other"] == {"keep": True}
    assert merged["hooks"]["Notification"] == existing["hooks"]["Notification"]
    permission_hooks = merged["hooks"]["PermissionRequest"]
    assert permission_hooks[0]["hooks"][0]["command"] == "/tmp/onlineworker --codex-hook-bridge"


def test_merge_codex_hook_settings_removes_duplicate_permission_request_hooks():
    existing = {
        "hooks": {
            "PermissionRequest": [
                {"matcher": "", "hooks": [{"type": "command", "command": "onlineworker"}]},
                {"hooks": [{"type": "command", "command": "/Users/example/.local/bin/codeisland-bridge --source codex"}]},
            ],
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "keep-stop"}]}],
        },
    }

    merged = merge_codex_hook_settings(existing, "ONLINEWORKER")

    assert merged["hooks"]["Stop"] == existing["hooks"]["Stop"]
    assert merged["hooks"]["PermissionRequest"] == [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "ONLINEWORKER",
                    "timeout": 86400,
                }
            ],
        }
    ]


@pytest.mark.asyncio
async def test_codex_hook_bridge_permission_request_emits_approval_and_waits_for_reply(tmp_path):
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
        threads={"ses-1": ThreadInfo(thread_id="ses-1", topic_id=123, archived=False)},
    )
    state = AppState(storage=AppStorage(workspaces={"proj": ws}))
    events = []

    async def emit_event(workspace_id, method, params):
        events.append((workspace_id, method, params))

    bridge = CodexHookBridge(state, data_dir=str(tmp_path), emit_event=emit_event)
    payload = {
        "hook_event_name": "PermissionRequest",
        "session_id": "ses-1",
        "cwd": "/Users/example/Projects/onlineWorker",
        "tool_name": "Bash",
        "tool_input": {
            "command": "pwd",
            "description": "检查目录",
        },
    }

    task = asyncio.create_task(bridge.handle_hook_payload(payload))
    await asyncio.sleep(0)

    assert len(events) == 1
    workspace_id, method, params = events[0]
    assert workspace_id == "codex:onlineWorker"
    assert method == "item/commandExecution/requestApproval"
    assert params["threadId"] == "ses-1"
    assert params["command"] == "pwd"
    assert params["reason"] == "检查目录"
    assert params["_codex_hook_bridge"] is True

    await bridge.reply_server_request(
        params["request_id"],
        {"behavior": "allow", "scope": "session"},
    )
    response = await task

    assert response == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {
                "behavior": "allow",
                "updatedPermissions": [
                    {
                        "type": "addRules",
                        "rules": [{"toolName": "Bash", "ruleContent": "*"}],
                        "behavior": "allow",
                        "destination": "session",
                    }
                ],
            },
        }
    }


class _FakeQuery:
    def __init__(self, data: str):
        self.data = data
        self.edited_text = ""

    async def answer(self, *args, **kwargs):
        return None

    async def edit_message_text(self, text, **kwargs):
        self.edited_text = text


class _FakeUpdate:
    def __init__(self, query):
        self.callback_query = query


class _FakeContext:
    bot = None


@pytest.mark.asyncio
async def test_callback_replies_to_codex_hook_bridge_without_active_adapter(tmp_path):
    state = AppState()
    bridge_replies = []

    class _FakeBridge:
        is_running = True

        async def reply_server_request(self, request_id, result):
            bridge_replies.append((request_id, result))
            return {}

    codex_state.set_hook_bridge(state, _FakeBridge())
    state.pending_approvals[42] = PendingApproval(
        request_id="req-1",
        workspace_id="codex:onlineWorker",
        thread_id="ses-1",
        cmd="pwd",
        justification="检查目录",
        tool_name="Bash",
        tool_type="codex",
        approval_source="hook_bridge",
    )

    query = _FakeQuery("exec_allow_always:42:9999999999")
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(_FakeUpdate(query), _FakeContext())

    assert bridge_replies == [
        ("req-1", {"behavior": "allow", "scope": "session", "tool_name": "Bash"})
    ]
    assert 42 not in state.pending_approvals
    assert "已总是允许" in query.edited_text
