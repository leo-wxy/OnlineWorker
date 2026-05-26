import json

from scripts.probe_codex_remote_proxy import rewrite_codex_client_message


def test_rewrite_codex_turn_start_text_input():
    raw = json.dumps(
        {
            "id": 7,
            "method": "turn/start",
            "params": {
                "threadId": "tid-1",
                "input": [
                    {"type": "text", "text": "这什么傻逼问题"},
                    {"type": "localImage", "path": "/tmp/a.png"},
                ],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed, changes = rewrite_codex_client_message(raw)

    payload = json.loads(rewritten)
    assert changed is True
    assert changes == [
        {
            "method": "turn/start",
            "before": "这什么傻逼问题",
            "after": "这是什么问题",
        }
    ]
    assert payload["params"]["input"] == [
        {"type": "text", "text": "这是什么问题"},
        {"type": "localImage", "path": "/tmp/a.png"},
    ]


def test_rewrite_codex_turn_steer_text_input():
    raw = json.dumps(
        {
            "id": 8,
            "method": "turn/steer",
            "params": {
                "threadId": "tid-1",
                "expectedTurnId": "turn-1",
                "input": [{"type": "text", "text": "你妈的 解释一下"}],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed, changes = rewrite_codex_client_message(raw)

    assert changed is True
    assert changes[0]["after"] == "解释一下"
    assert json.loads(rewritten)["params"]["input"][0]["text"] == "解释一下"


def test_rewrite_codex_message_ignores_non_turn_methods():
    raw = json.dumps(
        {
            "id": 2,
            "method": "thread/start",
            "params": {"cwd": "/tmp", "input": [{"type": "text", "text": "傻逼"}]},
        },
        ensure_ascii=False,
    )

    rewritten, changed, changes = rewrite_codex_client_message(raw)

    assert rewritten == raw
    assert changed is False
    assert changes == []


def test_rewrite_codex_message_keeps_invalid_json_unchanged():
    raw = "not json"

    rewritten, changed, changes = rewrite_codex_client_message(raw)

    assert rewritten == raw
    assert changed is False
    assert changes == []
