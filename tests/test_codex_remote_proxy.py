import json
from types import SimpleNamespace

import pytest

from config import Config, MessageHookConfig, MessageHooksConfig
from core.state import AppState
from plugins.providers.builtin.codex.python.remote_proxy import rewrite_codex_remote_client_message


@pytest.mark.asyncio
async def test_codex_remote_proxy_rewrites_turn_start_text_via_gateway():
    state = AppState()
    raw = json.dumps(
        {
            "id": 7,
            "method": "turn/start",
            "params": {
                "threadId": "tid-1",
                "cwd": "/Users/example/repo",
                "input": [
                    {"type": "text", "text": "你妈的，这什么傻逼问题", "text_elements": []},
                    {"type": "localImage", "path": "/tmp/a.png"},
                ],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed = await rewrite_codex_remote_client_message(state, raw)

    payload = json.loads(rewritten)
    assert changed is True
    assert payload["params"]["input"] == [
        {"type": "text", "text": "这是什么问题", "text_elements": []},
        {"type": "localImage", "path": "/tmp/a.png"},
    ]


@pytest.mark.asyncio
async def test_codex_remote_proxy_respects_disabled_message_hooks():
    state = AppState(
        config=SimpleNamespace(
            message_hooks=SimpleNamespace(enabled=False),
        )
    )
    raw = json.dumps(
        {
            "id": 7,
            "method": "turn/start",
            "params": {
                "threadId": "tid-1",
                "input": [{"type": "text", "text": "你妈的"}],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed = await rewrite_codex_remote_client_message(state, raw)

    assert rewritten == raw
    assert changed is False


@pytest.mark.asyncio
async def test_codex_remote_proxy_skips_text_with_ui_spans():
    state = AppState()
    raw = json.dumps(
        {
            "id": 7,
            "method": "turn/start",
            "params": {
                "threadId": "tid-1",
                "input": [
                    {
                        "type": "text",
                        "text": "你妈的 看 @README.md",
                        "text_elements": [
                            {
                                "byteRange": {"start": 10, "end": 20},
                                "placeholder": "@README.md",
                            }
                        ],
                    }
                ],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed = await rewrite_codex_remote_client_message(state, raw)

    assert rewritten == raw
    assert changed is False


@pytest.mark.asyncio
async def test_codex_remote_proxy_handles_turn_steer_text():
    state = AppState()
    raw = json.dumps(
        {
            "id": 8,
            "method": "turn/steer",
            "params": {
                "threadId": "tid-1",
                "expectedTurnId": "turn-1",
                "input": [{"type": "text", "text": "妈的，继续"}],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed = await rewrite_codex_remote_client_message(state, raw)

    assert changed is True
    assert json.loads(rewritten)["params"]["input"][0]["text"] == "继续"


@pytest.mark.asyncio
async def test_codex_remote_proxy_config_can_disable_builtin_normalizer():
    state = AppState(
        config=Config(
            telegram_token="token",
            allowed_user_id=1,
            group_chat_id=2,
            log_level="INFO",
            tools=[],
            message_hooks=MessageHooksConfig(
                enabled=True,
                builtin={
                    "abusive_language_normalization": MessageHookConfig(
                        enabled=True,
                        mode="off",
                    )
                },
            ),
        )
    )
    raw = json.dumps(
        {
            "id": 7,
            "method": "turn/start",
            "params": {
                "threadId": "tid-1",
                "input": [{"type": "text", "text": "这什么傻逼问题"}],
            },
        },
        ensure_ascii=False,
    )

    rewritten, changed = await rewrite_codex_remote_client_message(state, raw)

    assert rewritten == raw
    assert changed is False
