import json
from io import BytesIO

from plugins.providers.builtin.codex.python.hook_bridge import (
    default_codex_hook_response,
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
