import json
from io import BytesIO

from plugins.providers.builtin.codex.python.hook_bridge import (
    default_codex_hook_response,
    install_codex_permission_mirror_hook,
    run_codex_hook_bridge_once,
)
from plugins.providers.builtin.codex.python.hook_cleanup import (
    cleanup_onlineworker_codex_permission_hooks,
)


def test_default_codex_permission_hook_response_passes_through_to_codex():
    assert default_codex_hook_response({"hook_event_name": "PermissionRequest"}) == {}


def test_cleanup_removes_only_onlineworker_permission_hooks(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/wxy/.codeisland/codeisland-bridge --source codex",
                                    "timeout": 5,
                                }
                            ]
                        }
                    ],
                    "PermissionRequest": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --codex-hook-bridge --data-dir '/Users/wxy/Library/Application Support/OnlineWorker'",
                                    "timeout": 86400,
                                },
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/other-permission-hook",
                                    "timeout": 10,
                                },
                            ],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    assert cleanup_onlineworker_codex_permission_hooks(hooks_path) is True

    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == (
        "/Users/wxy/.codeisland/codeisland-bridge --source codex"
    )
    assert settings["hooks"]["PermissionRequest"] == [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "/usr/local/bin/other-permission-hook",
                    "timeout": 10,
                }
            ],
        }
    ]


def test_cleanup_removes_empty_permission_request_section(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PermissionRequest": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "onlineworker-bot --codex-hook-bridge",
                                    "timeout": 86400,
                                }
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/wxy/.codeisland/codeisland-bridge --source codex",
                                    "timeout": 5,
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    assert cleanup_onlineworker_codex_permission_hooks(hooks_path) is True

    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert "PermissionRequest" not in settings["hooks"]
    assert settings["hooks"]["Stop"][0]["hooks"][0]["command"] == (
        "/Users/wxy/.codeisland/codeisland-bridge --source codex"
    )


def test_codex_hook_bridge_once_returns_empty_response(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        type("_Stdin", (), {"buffer": BytesIO(b'{"hook_event_name":"PermissionRequest"}')})(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert capsys.readouterr().out == "{}"


def test_install_codex_permission_mirror_hook_preserves_existing_hooks(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/wxy/.codeisland/codeisland-bridge --source codex",
                                    "timeout": 5,
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    changed = install_codex_permission_mirror_hook(
        "/Users/wxy/Library/Application Support/OnlineWorker",
        hooks_path=hooks_path,
    )

    assert changed is True
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == (
        "/Users/wxy/.codeisland/codeisland-bridge --source codex"
    )
    permission_hooks = settings["hooks"]["PermissionRequest"]
    assert len(permission_hooks) == 1
    installed = permission_hooks[0]["hooks"][0]
    assert installed["type"] == "command"
    assert "--codex-hook-bridge" in installed["command"]
    assert "--data-dir" in installed["command"]
    assert installed["timeout"] == 86400


def test_install_codex_permission_mirror_hook_runs_before_existing_permission_hooks(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PermissionRequest": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/wxy/.codeisland/codeisland-bridge --source codex",
                                    "timeout": 86400,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    changed = install_codex_permission_mirror_hook(
        "/Users/wxy/Library/Application Support/OnlineWorker",
        hooks_path=hooks_path,
    )

    assert changed is True
    permission_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]
    first_hook = permission_hooks[0]["hooks"][0]
    second_hook = permission_hooks[1]["hooks"][0]
    assert "--codex-hook-bridge" in first_hook["command"]
    assert "/Users/wxy/.codeisland/codeisland-bridge --source codex" == second_hook["command"]


def test_install_codex_permission_mirror_hook_removes_duplicate_onlineworker_hooks(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    command = (
        "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot "
        "--codex-hook-bridge --data-dir '/Users/wxy/Library/Application Support/OnlineWorker'"
    )
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PermissionRequest": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command,
                                    "timeout": 5,
                                }
                            ],
                        },
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": command,
                                    "timeout": 5,
                                },
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/other-permission-hook",
                                    "timeout": 10,
                                },
                            ],
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    changed = install_codex_permission_mirror_hook(
        "/Users/wxy/Library/Application Support/OnlineWorker",
        hooks_path=hooks_path,
    )

    assert changed is True
    permission_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]
    onlineworker_hooks = [
        hook
        for entry in permission_hooks
        for hook in entry["hooks"]
        if "--codex-hook-bridge" in hook["command"]
    ]
    assert len(onlineworker_hooks) == 1
    assert permission_hooks[1]["hooks"][0]["command"] == "/usr/local/bin/other-permission-hook"


def test_codex_hook_bridge_mirrors_permission_request_and_returns_tg_allow_to_codex(monkeypatch, capsys):
    sent_payloads = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, path):
            self.path = path

        def sendall(self, raw):
            sent_payloads.append(json.loads(raw.decode("utf-8").strip()))

        def recv(self, size):
            return b'{"ok":true,"decision":"allow"}\n'

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.provider_owner_bridge_socket_path",
        lambda data_dir: "/tmp/provider_owner_bridge.sock",
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.socket.socket",
        lambda *args, **kwargs: _FakeSocket(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "_Stdin",
            (),
            {
                "buffer": BytesIO(
                    json.dumps(
                        {
                            "hook_event_name": "PermissionRequest",
                            "threadId": "tid-1",
                            "cwd": "/tmp/workspace",
                            "command": "ps -axo pid,command",
                            "reason": "inspect processes",
                        }
                    ).encode("utf-8")
                )
            },
        )(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert json.loads(capsys.readouterr().out) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }
    assert sent_payloads == [
        {
            "type": "mirror_approval",
            "provider_id": "codex",
            "thread_id": "tid-1",
            "workspace_dir": "/tmp/workspace",
            "owned_tui_host": False,
            "blocking": True,
            "payload": {
                "hook_event_name": "PermissionRequest",
                "threadId": "tid-1",
                "cwd": "/tmp/workspace",
                "command": "ps -axo pid,command",
                "reason": "inspect processes",
                "request_id": "codex-cli-hook:tid-1:62c1b31f665418e68845",
            },
            "source": "codex_cli_hook",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
        }
    ]


def test_codex_hook_bridge_returns_tg_deny_to_codex(monkeypatch, capsys):
    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, path):
            self.path = path

        def sendall(self, raw):
            self.raw = raw

        def recv(self, size):
            return b'{"ok":true,"decision":"deny","message":"TG denied"}\n'

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.provider_owner_bridge_socket_path",
        lambda data_dir: "/tmp/provider_owner_bridge.sock",
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.socket.socket",
        lambda *args, **kwargs: _FakeSocket(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "_Stdin",
            (),
            {
                "buffer": BytesIO(
                    json.dumps(
                        {
                            "hook_event_name": "PermissionRequest",
                            "threadId": "tid-1",
                            "cwd": "/tmp/workspace",
                            "command": "ps -axo pid,command",
                        }
                    ).encode("utf-8")
                )
            },
        )(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert json.loads(capsys.readouterr().out) == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "deny", "message": "TG denied"},
        }
    }


def test_codex_hook_bridge_marks_owned_tui_host_for_interactive_tg(monkeypatch, capsys):
    sent_payloads = []

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, timeout):
            self.timeout = timeout

        def connect(self, path):
            self.path = path

        def sendall(self, raw):
            sent_payloads.append(json.loads(raw.decode("utf-8").strip()))

        def recv(self, size):
            return b'{"ok":true}\n'

    monkeypatch.setenv("ONLINEWORKER_CODEX_TUI_HOST", "1")
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.provider_owner_bridge_socket_path",
        lambda data_dir: "/tmp/provider_owner_bridge.sock",
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.socket.socket",
        lambda *args, **kwargs: _FakeSocket(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "_Stdin",
            (),
            {
                "buffer": BytesIO(
                    json.dumps(
                        {
                            "hook_event_name": "PermissionRequest",
                            "threadId": "tid-1",
                            "cwd": "/tmp/workspace",
                            "command": "ps -axo pid,command",
                        }
                    ).encode("utf-8")
                )
            },
        )(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert json.loads(capsys.readouterr().out) == {}
    assert sent_payloads[0]["owned_tui_host"] is True
    assert sent_payloads[0]["blocking"] is True
    assert sent_payloads[0]["notice_suffix"] == "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。"
