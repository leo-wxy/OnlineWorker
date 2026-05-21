import json
from io import BytesIO

from plugins.providers.builtin.codex.python.hook_bridge import (
    default_codex_hook_response,
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
