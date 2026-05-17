from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_codex_adapter_send_user_message_can_include_image_inputs():
    from plugins.providers.builtin.codex.python.adapter import CodexAdapter

    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message(
        "codex:onlineWorker",
        "tid-live",
        "look at this",
        attachments=[
            {
                "kind": "image",
                "path": "/tmp/test-image.png",
            }
        ],
    )

    adapter._call.assert_awaited_once()
    method, params = adapter._call.await_args.args
    assert method == "turn/start"
    assert params["threadId"] == "tid-live"
    assert params["input"][0] == {"type": "text", "text": "look at this"}
    assert params["input"][1] == {
        "type": "localImage",
        "path": "/tmp/test-image.png",
    }
