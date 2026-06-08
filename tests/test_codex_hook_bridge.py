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
                                            "command": "/usr/local/bin/legacy-codex-hook --source codex",
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
                                    "command": "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --codex-hook-bridge --data-dir '/Users/example/Library/Application Support/OnlineWorker'",
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
        "/usr/local/bin/legacy-codex-hook --source codex"
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
                                    "command": "/usr/local/bin/legacy-codex-hook --source codex",
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
        "/usr/local/bin/legacy-codex-hook --source codex"
    )


def test_codex_hook_bridge_once_returns_empty_response(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        type("_Stdin", (), {"buffer": BytesIO(b'{"hook_event_name":"PermissionRequest"}')})(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert capsys.readouterr().out == "{}"


def test_codex_hook_bridge_leaves_user_prompt_submit_pass_through_without_permission_mirror(
    monkeypatch,
    capsys,
):
    from plugins.providers.builtin.codex.python.hook_bridge import (
        CODEX_USER_PROMPT_SUBMIT_HOOK_NAME,
    )

    def fail_permission_mirror(data_dir, payload):
        raise AssertionError("UserPromptSubmit must not use PermissionRequest mirror")

    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.mirror_codex_permission_request",
        fail_permission_mirror,
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
                            "hook_event_name": "UserPromptSubmit",
                            "prompt": "这什么傻逼问题",
                        }
                    ).encode("utf-8")
                )
            },
        )(),
    )

    assert CODEX_USER_PROMPT_SUBMIT_HOOK_NAME == "UserPromptSubmit"
    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert capsys.readouterr().out == "{}"


def test_install_codex_permission_mirror_hook_does_not_add_new_hook(tmp_path):
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
                                    "command": "/usr/local/bin/legacy-codex-hook --source codex",
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
        "/Users/example/Library/Application Support/OnlineWorker",
        hooks_path=hooks_path,
    )

    assert changed is False
    settings = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == (
        "/usr/local/bin/legacy-codex-hook --source codex"
    )
    assert "PermissionRequest" not in settings["hooks"]


def test_install_codex_permission_mirror_hook_preserves_non_onlineworker_permission_hooks(tmp_path):
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
                                    "command": "/usr/local/bin/legacy-codex-hook --source codex",
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
        "/Users/example/Library/Application Support/OnlineWorker",
        hooks_path=hooks_path,
    )

    assert changed is False
    permission_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]["PermissionRequest"]
    first_hook = permission_hooks[0]["hooks"][0]
    assert first_hook["command"] == "/usr/local/bin/legacy-codex-hook --source codex"


def test_install_codex_permission_mirror_hook_removes_duplicate_onlineworker_hooks(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    command = (
        "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot "
        "--codex-hook-bridge --data-dir '/Users/example/Library/Application Support/OnlineWorker'"
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
        "/Users/example/Library/Application Support/OnlineWorker",
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
    assert onlineworker_hooks == []
    assert permission_hooks == [
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
