from core.providers.interactions import ProviderApprovalRequest
from plugins.providers.builtin.codex.python.interactions import (
    SERVER_REQUEST_METHODS,
    parse_approval_request,
)


def test_codex_parse_approval_request_uses_fixed_core_shape():
    request = parse_approval_request(
        {
            "request_id": "req-from-payload",
            "threadId": "thread-1",
            "command": "ps -axo pid,ppid,etime,command",
            "reason": "inspect processes",
            "toolName": "shell",
            "availableDecisions": [
                {
                    "acceptWithExecpolicyAmendment": {
                        "execpolicy_amendment": [{"rule": "allow-ps"}],
                    }
                }
            ],
            "_always_patterns": ["ps -axo *"],
        },
        request_id="req-fallback",
        provider_id="codex",
        approval_source="app_server",
    )

    assert request == ProviderApprovalRequest(
        request_id="req-from-payload",
        thread_id="thread-1",
        command="ps -axo pid,ppid,etime,command",
        reason="inspect processes",
        tool_name="shell",
        proposed_amendment=[{"rule": "allow-ps"}],
        amendment_decision={
            "acceptWithExecpolicyAmendment": {
                "execpolicy_amendment": [{"rule": "allow-ps"}],
            }
        },
        tool_type="codex",
        always_patterns=["ps -axo *"],
        approval_source="app_server",
    )


def test_codex_parse_approval_request_supports_server_request_fallbacks():
    request = parse_approval_request(
        {
            "threadId": "thread-1",
            "command": "git add --dry-run README.md",
            "justification": "verify permission forwarding",
            "proposedExecpolicyAmendment": ["git add --dry-run README.md"],
        },
        request_id=177,
        provider_id="codex",
        default_thread_id="thread-fallback",
    )

    assert request.request_id == 177
    assert request.thread_id == "thread-1"
    assert request.command == "git add --dry-run README.md"
    assert request.reason == "verify permission forwarding"
    assert request.tool_name == ""
    assert request.proposed_amendment == ["git add --dry-run README.md"]
    assert request.amendment_decision == {}
    assert request.tool_type == "codex"
    assert request.always_patterns == []
    assert request.approval_source == "app_server"


def test_codex_parse_approval_request_supports_legacy_exec_command_shape():
    request = parse_approval_request(
        {
            "conversationId": "thread-legacy",
            "command": ["/bin/zsh", "-lc", "ps -axo pid,command"],
            "cwd": "/Users/example/Projects/sample-repo",
            "reason": "inspect processes",
        },
        request_id=178,
        provider_id="codex",
        approval_source="execCommandApproval",
    )

    assert request.request_id == 178
    assert request.thread_id == "thread-legacy"
    assert request.command == "/bin/zsh -lc 'ps -axo pid,command'"
    assert request.reason == "inspect processes"
    assert request.tool_type == "codex"
    assert request.approval_source == "execCommandApproval"


def test_codex_parse_approval_request_supports_permissions_shape():
    request = parse_approval_request(
        {
            "threadId": "thread-permissions",
            "cwd": "/Users/example/Projects/sample-repo",
            "reason": "need Downloads write access",
            "permissions": {
                "network": None,
                "fileSystem": {"additionalRoots": ["/Users/example/Downloads"]},
            },
        },
        request_id=179,
        provider_id="codex",
        approval_source="item/permissions/requestApproval",
    )

    assert request.request_id == 179
    assert request.thread_id == "thread-permissions"
    assert request.command == (
        'request permissions: {"fileSystem": {"additionalRoots": ["/Users/example/Downloads"]}}'
    )
    assert request.reason == "need Downloads write access"
    assert request.amendment_decision == {
        "permissions": {"fileSystem": {"additionalRoots": ["/Users/example/Downloads"]}}
    }
    assert request.approval_source == "item/permissions/requestApproval"


def test_codex_server_request_methods_are_registered_by_provider():
    assert "item/commandExecution/requestApproval" in SERVER_REQUEST_METHODS
    assert "item/fileChange/requestApproval" in SERVER_REQUEST_METHODS
    assert "item/permissions/requestApproval" in SERVER_REQUEST_METHODS
    assert "execCommandApproval" in SERVER_REQUEST_METHODS
    assert "applyPatchApproval" in SERVER_REQUEST_METHODS
