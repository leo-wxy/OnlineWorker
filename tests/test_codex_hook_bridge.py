import json
from io import BytesIO

from plugins.providers.builtin.codex.python.hook_bridge import run_codex_hook_bridge_once


def test_codex_hook_bridge_once_returns_empty_response_for_permission_request(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        type("_Stdin", (), {"buffer": BytesIO(b'{"hook_event_name":"PermissionRequest"}')})(),
    )

    assert run_codex_hook_bridge_once() == 0
    assert capsys.readouterr().out == "{}"


def test_codex_hook_bridge_once_returns_empty_response_for_user_prompt_submit(monkeypatch, capsys):
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

    assert run_codex_hook_bridge_once() == 0
    assert capsys.readouterr().out == "{}"
