import json
import tomllib
from io import BytesIO
from unittest.mock import AsyncMock, Mock

from plugins.providers.builtin.codex.python.hook_bridge import (
    ONLINEWORKER_CODEX_HOOK_MARKER,
    ONLINEWORKER_CODEX_NOTIFY_MARKER,
    default_codex_hook_response,
    install_onlineworker_codex_hooks,
    install_onlineworker_codex_notify,
    run_codex_notify_bridge_once,
    run_codex_hook_bridge_once,
)


def test_default_codex_permission_hook_response_passes_through_to_codex():
    assert default_codex_hook_response({"hook_event_name": "PermissionRequest"}) == {}


def test_codex_hook_bridge_once_returns_empty_response(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        type("_Stdin", (), {"buffer": BytesIO(b'{"hook_event_name":"PermissionRequest"}')})(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert capsys.readouterr().out == "{}"


def test_install_onlineworker_codex_hooks_preserves_existing_entries(tmp_path):
    hooks_path = tmp_path / "hooks.json"
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PermissionRequest": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --codex-hook-bridge --data-dir /tmp/onlineworker",
                                    "timeout": 86400,
                                }
                            ]
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/existing-stop-hook",
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = install_onlineworker_codex_hooks(
        "/tmp/onlineworker",
        hooks_path=str(hooks_path),
    )

    assert result["state"] == "installed"
    assert result["installedEvents"] == ["SessionStart", "UserPromptSubmit", "Stop"]
    payload = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert payload["hooks"]["Stop"][0]["hooks"][0]["command"] == "/usr/local/bin/existing-stop-hook"
    for event_name in ("SessionStart", "UserPromptSubmit", "Stop"):
        onlineworker_entries = [
            entry
            for entry in payload["hooks"][event_name]
            if any(
                ONLINEWORKER_CODEX_HOOK_MARKER in str(handler.get("command") or "")
                for handler in entry.get("hooks", [])
                if isinstance(handler, dict)
            )
        ]
        assert len(onlineworker_entries) == 1
        assert "--codex-hook-bridge" in onlineworker_entries[0]["hooks"][0]["command"]
        assert onlineworker_entries[0]["hooks"][0]["timeout"] == 86400

    second = install_onlineworker_codex_hooks(
        "/tmp/onlineworker",
        hooks_path=str(hooks_path),
    )
    assert second["changed"] is False


def test_codex_hook_bridge_relays_desktop_stop_event(monkeypatch, capsys):
    relay = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.relay_codex_hook_payload",
        relay,
    )
    payload = {
        "hook_event_name": "Stop",
        "session_id": "desktop-session",
        "turn_id": "desktop-turn",
        "cwd": "/Users/example/Projects/demo",
        "last_assistant_message": "Desktop 任务已经完成。",
    }
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "_Stdin",
            (),
            {"buffer": BytesIO(json.dumps(payload).encode("utf-8"))},
        )(),
    )

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    relay.assert_awaited_once_with("/tmp/onlineworker", payload)
    assert capsys.readouterr().out == "{}"


def test_install_onlineworker_codex_notify_preserves_forwarder_and_removes_event_hooks(tmp_path):
    config_path = tmp_path / "config.toml"
    hooks_path = tmp_path / "hooks.json"
    forward_path = tmp_path / "codex_notify_forward.json"
    config_path.write_text(
        """model = \"gpt-5.5\"
notify = [
  \"/Applications/Existing.app/Contents/MacOS/existing-notify\",
  \"turn-ended\",
]

[desktop]
localeOverride = \"zh-CN\"
""",
        encoding="utf-8",
    )
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --codex-hook-bridge",
                                }
                            ]
                        },
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/local/bin/keep-stop-hook",
                                }
                            ]
                        },
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --codex-hook-bridge",
                                }
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = install_onlineworker_codex_notify(
        "/tmp/onlineworker",
        config_path=str(config_path),
        hooks_path=str(hooks_path),
        forward_path=str(forward_path),
    )

    assert result["state"] == "installed"
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert ONLINEWORKER_CODEX_NOTIFY_MARKER in parsed["notify"]
    assert json.loads(forward_path.read_text(encoding="utf-8")) == {
        "argv": [
            "/Applications/Existing.app/Contents/MacOS/existing-notify",
            "turn-ended",
        ]
    }
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
    assert hooks["UserPromptSubmit"] == []
    assert hooks["Stop"][0]["hooks"][0]["command"] == "/usr/local/bin/keep-stop-hook"

    second = install_onlineworker_codex_notify(
        "/tmp/onlineworker",
        config_path=str(config_path),
        hooks_path=str(hooks_path),
        forward_path=str(forward_path),
    )
    assert second["changed"] is False
    assert json.loads(forward_path.read_text(encoding="utf-8"))["argv"][0].endswith(
        "existing-notify"
    )


def test_codex_notify_bridge_relays_agent_turn_complete_and_forwards_existing_handler(
    monkeypatch,
):
    relay = AsyncMock(return_value={"ok": True})
    forward = Mock()
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.relay_codex_hook_payload",
        relay,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.forward_codex_notify_payload",
        forward,
    )
    raw_payload = json.dumps(
        {
            "type": "agent-turn-complete",
            "thread-id": "desktop-session",
            "turn-id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "input-messages": ["检查摘要链路"],
            "last-assistant-message": "摘要链路检查完成。",
        },
        ensure_ascii=False,
    )

    assert run_codex_notify_bridge_once("/tmp/onlineworker", raw_payload) == 0
    relay.assert_awaited_once_with(
        "/tmp/onlineworker",
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "input_messages": ["检查摘要链路"],
            "last_assistant_message": "摘要链路检查完成。",
            "source": "codex_notify",
        },
    )
    forward.assert_called_once_with("/tmp/onlineworker", raw_payload)


def test_codex_hook_bridge_leaves_user_prompt_submit_pass_through_without_permission_mirror(
    monkeypatch,
    capsys,
):
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

    assert run_codex_hook_bridge_once("/tmp/onlineworker") == 0
    assert capsys.readouterr().out == "{}"
