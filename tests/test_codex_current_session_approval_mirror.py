import json
from pathlib import Path

import pytest


def _tool_call_line(params: dict, *, thread_id: str = "019e48fc-3935-7780-ae26-a7418cbcf036") -> str:
    return (
        "2026-05-25T09:42:10.518422Z  INFO session_loop"
        "{thread_id=019e48fc-3935-7780-ae26-a7418cbcf036}: "
        f"codex_core::stream_events_utils: ToolCall: exec_command {json.dumps(params)} "
        f"thread_id={thread_id}"
    )


def test_codex_current_session_approval_line_builds_mirror_request():
    from plugins.providers.builtin.codex.python.current_session_approval_mirror import (
        build_current_session_approval_request,
    )

    line = _tool_call_line(
        {
            "cmd": "/bin/zsh -lc 'printf OW_CURRENT_SESSION_APPROVAL_VERIFY_1779679999'",
            "workdir": "/Users/wxy/Projects/onlineworker-combined",
            "sandbox_permissions": "require_escalated",
            "justification": "触发当前会话审批链路验证",
            "prefix_rule": ["/bin/zsh", "-lc", "printf OW_CURRENT_SESSION_APPROVAL_VERIFY_1779679999"],
        }
    )

    request = build_current_session_approval_request(line)

    assert request is not None
    assert request["type"] == "mirror_approval"
    assert request["provider_id"] == "codex"
    assert request["thread_id"] == "019e48fc-3935-7780-ae26-a7418cbcf036"
    assert request["workspace_dir"] == "/Users/wxy/Projects/onlineworker-combined"
    assert request["owned_tui_host"] is False
    assert request["source"] == "codex_current_session_log"
    assert request["notice_suffix"] == "此请求已在当前 Codex 会话中弹出，请在 Codex CLI/Desktop 中完成审批。"

    payload = request["payload"]
    assert payload["hook_event_name"] == "ExecApprovalRequest"
    assert payload["threadId"] == request["thread_id"]
    assert payload["cwd"] == request["workspace_dir"]
    assert payload["tool_name"] == "exec_command"
    assert payload["command"] == "/bin/zsh -lc 'printf OW_CURRENT_SESSION_APPROVAL_VERIFY_1779679999'"
    assert payload["reason"] == "触发当前会话审批链路验证"
    assert payload["sandbox_permissions"] == "require_escalated"
    assert payload["prefix_rule"] == [
        "/bin/zsh",
        "-lc",
        "printf OW_CURRENT_SESSION_APPROVAL_VERIFY_1779679999",
    ]
    assert payload["request_id"].startswith("codex-current-session:")


def test_codex_current_session_approval_line_ignores_non_escalated_calls():
    from plugins.providers.builtin.codex.python.current_session_approval_mirror import (
        build_current_session_approval_request,
    )

    line = _tool_call_line(
        {
            "cmd": "pwd",
            "workdir": "/Users/wxy/Projects/onlineworker-combined",
        }
    )

    assert build_current_session_approval_request(line) is None


def test_codex_current_session_approval_line_marks_owned_tui_host_when_active(tmp_path):
    from plugins.providers.builtin.codex.python.current_session_approval_mirror import (
        build_current_session_approval_request,
    )
    from plugins.providers.builtin.codex.python.tui_host_protocol import host_status_path

    status_path = Path(host_status_path(str(tmp_path)))
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(
            {
                "online": True,
                "active_thread_id": "tid-current",
                "socket_path": str(tmp_path / "codex_tui_host.sock"),
            }
        ),
        encoding="utf-8",
    )
    line = _tool_call_line(
        {
            "cmd": "/bin/zsh -lc 'ps -axo pid,command'",
            "workdir": "/tmp/project",
            "sandbox_permissions": "require_escalated",
            "justification": "inspect processes",
        },
        thread_id="tid-current",
    )

    request = build_current_session_approval_request(line, data_dir=str(tmp_path))

    assert request is not None
    assert request["owned_tui_host"] is True
    assert request["notice_suffix"] == "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"


@pytest.mark.asyncio
async def test_codex_current_session_approval_sync_sends_new_log_entries(tmp_path):
    from plugins.providers.builtin.codex.python.current_session_approval_mirror import (
        sync_current_session_approval_mirror_once,
    )

    log_path = tmp_path / "codex-tui.log"
    log_path.write_text(
        "\n".join(
            [
                _tool_call_line({"cmd": "pwd", "workdir": "/tmp/project"}),
                _tool_call_line(
                    {
                        "cmd": "/bin/zsh -lc 'printf approval'",
                        "workdir": "/tmp/project",
                        "sandbox_permissions": "require_escalated",
                        "justification": "approval needed",
                    },
                    thread_id="tid-current",
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    sent = []

    async def fake_sender(data_dir: str | None, request: dict) -> bool:
        sent.append((data_dir, request))
        return True

    offset = await sync_current_session_approval_mirror_once(
        data_dir="/tmp/onlineworker",
        log_path=str(log_path),
        offset=0,
        seen_request_ids=set(),
        sender=fake_sender,
    )

    assert offset == log_path.stat().st_size
    assert len(sent) == 1
    assert sent[0][0] == "/tmp/onlineworker"
    assert sent[0][1]["thread_id"] == "tid-current"
    assert sent[0][1]["payload"]["command"] == "/bin/zsh -lc 'printf approval'"
