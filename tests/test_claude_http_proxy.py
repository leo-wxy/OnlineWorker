import json
from types import SimpleNamespace

import httpx
import pytest

from config import Config, MessageHookConfig, MessageHooksConfig, ToolConfig
from core.state import AppState


@pytest.mark.asyncio
async def test_claude_http_proxy_keeps_messages_text_block_while_message_rewrite_is_sealed():
    from plugins.providers.builtin.claude.python.http_proxy import rewrite_claude_json_payload

    state = AppState(
        config=Config(
            telegram_token="token",
            allowed_user_id=1,
            group_chat_id=2,
            log_level="INFO",
            providers={
                "claude": ToolConfig(
                    name="claude",
                    enabled=True,
                    message_hooks=MessageHooksConfig(
                        enabled=True,
                        builtin={
                            "abusive_language_normalization": MessageHookConfig(
                                enabled=True,
                            )
                        },
                    ),
                )
            },
        )
    )
    payload = {
        "model": "claude-sonnet-4-5",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "你妈的，这什么傻逼问题"},
                    {"type": "image", "source": {"type": "base64", "data": "abc"}},
                ],
            }
        ],
    }

    rewritten, changed, changes = await rewrite_claude_json_payload(
        state,
        payload,
        source="claude_http_proxy",
    )

    assert changed is False
    assert changes == []
    assert rewritten == payload
    assert rewritten["messages"][0]["content"][0]["text"] == "你妈的，这什么傻逼问题"
    assert rewritten["messages"][0]["content"][1]["type"] == "image"


@pytest.mark.asyncio
async def test_claude_http_proxy_keeps_messages_string_content_while_message_rewrite_is_sealed():
    from plugins.providers.builtin.claude.python.http_proxy import rewrite_claude_json_payload

    state = AppState(
        config=SimpleNamespace(
            providers={
                "claude": SimpleNamespace(
                    message_hooks=SimpleNamespace(
                        enabled=True,
                        builtin={
                            "abusive_language_normalization": SimpleNamespace(
                                enabled=True,
                                mode="conservative",
                            )
                        },
                    )
                )
            },
            get_provider=lambda name: state.config.providers.get(name),
        )
    )
    payload = {
        "messages": [
            {"role": "system", "content": "保持简洁"},
            {"role": "user", "content": "妈的，继续解释"},
        ]
    }

    rewritten, changed, changes = await rewrite_claude_json_payload(
        state,
        payload,
        source="claude_http_proxy",
    )

    assert changed is False
    assert changes == []
    assert rewritten == payload
    assert rewritten["messages"][1]["content"] == "妈的，继续解释"


@pytest.mark.asyncio
async def test_claude_http_proxy_keeps_all_text_blocks_while_message_rewrite_is_sealed():
    from plugins.providers.builtin.claude.python.http_proxy import rewrite_claude_json_payload

    state = AppState(
        config=SimpleNamespace(
            providers={
                "claude": SimpleNamespace(
                    message_hooks=SimpleNamespace(
                        enabled=True,
                        builtin={
                            "abusive_language_normalization": SimpleNamespace(
                                enabled=True,
                                mode="conservative",
                            )
                        },
                    )
                )
            },
            get_provider=lambda name: state.config.providers.get(name),
        )
    )
    system_reminder = "<system-reminder>\n妈的 should remain untouched\n</system-reminder>"
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_reminder},
                    {"type": "text", "text": "你妈的，只回复 OK"},
                ],
            }
        ]
    }

    rewritten, changed, changes = await rewrite_claude_json_payload(
        state,
        payload,
        source="claude_http_proxy",
    )

    assert changed is False
    assert changes == []
    assert rewritten == payload
    assert rewritten["messages"][0]["content"][0]["text"] == system_reminder
    assert rewritten["messages"][0]["content"][1]["text"] == "你妈的，只回复 OK"


@pytest.mark.asyncio
async def test_claude_http_proxy_respects_disabled_provider_hook():
    from plugins.providers.builtin.claude.python.http_proxy import rewrite_claude_json_payload

    state = AppState(
        config=SimpleNamespace(
            providers={
                "claude": SimpleNamespace(
                    message_hooks=SimpleNamespace(
                        enabled=True,
                        builtin={
                            "abusive_language_normalization": SimpleNamespace(
                                enabled=False,
                                mode="conservative",
                            )
                        },
                    )
                )
            },
            get_provider=lambda name: state.config.providers.get(name),
        )
    )
    payload = {"messages": [{"role": "user", "content": "这什么傻逼问题"}]}

    rewritten, changed, changes = await rewrite_claude_json_payload(
        state,
        payload,
        source="claude_http_proxy",
    )

    assert rewritten == payload
    assert changed is False
    assert changes == []


def test_claude_http_proxy_redacts_sensitive_headers():
    from plugins.providers.builtin.claude.python.http_proxy import redact_headers

    assert redact_headers(
        {
            "authorization": "Bearer secret",
            "x-api-key": "key",
            "anthropic-version": "2023-06-01",
        }
    ) == {
        "authorization": "[REDACTED]",
        "x-api-key": "[REDACTED]",
        "anthropic-version": "2023-06-01",
    }


def test_claude_http_proxy_summarizes_rewritten_payload_without_secrets():
    from plugins.providers.builtin.claude.python.http_proxy import summarize_claude_payload

    payload = {
        "model": "claude-sonnet-4-5",
        "messages": [{"role": "user", "content": "你妈的，继续解释"}],
        "metadata": {"api_key": "secret"},
    }

    summary = summarize_claude_payload(json.dumps(payload, ensure_ascii=False))

    assert "model=claude-sonnet-4-5" in summary
    assert "messages=1" in summary
    assert "text=你妈的，继续解释" in summary
    assert "secret" not in summary


@pytest.mark.asyncio
async def test_claude_http_proxy_forwards_original_json_while_message_rewrite_is_sealed():
    from plugins.providers.builtin.claude.python.http_proxy import ClaudeHttpProxy

    captured: dict[str, object] = {}

    async def handle_upstream(reader, writer):
        raw = await reader.readuntil(b"\r\n\r\n")
        headers = raw.decode("iso-8859-1")
        content_length = 0
        for line in headers.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
        body = await reader.readexactly(content_length)
        captured["body"] = json.loads(body.decode("utf-8"))
        response = b'{"ok":true}'
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(response)}\r\n".encode("ascii")
            + b"\r\n"
            + response
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await __import__("asyncio").start_server(handle_upstream, "127.0.0.1", 0)
    upstream_socket = next(iter(upstream.sockets))
    upstream_host, upstream_port = upstream_socket.getsockname()[:2]
    upstream_url = f"http://{upstream_host}:{upstream_port}"

    state = AppState(
        config=SimpleNamespace(
            providers={
                "claude": SimpleNamespace(
                    message_hooks=SimpleNamespace(
                        enabled=True,
                        builtin={
                            "abusive_language_normalization": SimpleNamespace(
                                enabled=True,
                                mode="conservative",
                            )
                        },
                    )
                )
            },
            get_provider=lambda name: state.config.providers.get(name),
        )
    )
    proxy = ClaudeHttpProxy(
        state=state,
        upstream_base_url=upstream_url,
        rewrite=True,
    )
    proxy_url = await proxy.start()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{proxy_url}/v1/messages",
                json={"messages": [{"role": "user", "content": "这什么傻逼问题"}]},
            )
        assert response.status_code == 200
        assert captured["body"] == {
            "messages": [{"role": "user", "content": "这什么傻逼问题"}]
        }
    finally:
        await proxy.stop()
        upstream.close()
        await upstream.wait_closed()


@pytest.mark.asyncio
async def test_claude_http_proxy_probe_writes_visible_request_event(capsys):
    from plugins.providers.builtin.claude.python.http_proxy import ClaudeHttpProxy

    async def handle_upstream(reader, writer):
        raw = await reader.readuntil(b"\r\n\r\n")
        headers = raw.decode("iso-8859-1")
        content_length = 0
        for line in headers.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
        if content_length:
            await reader.readexactly(content_length)
        response = b'{"ok":true}'
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            + f"Content-Length: {len(response)}\r\n".encode("ascii")
            + b"\r\n"
            + response
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    upstream = await __import__("asyncio").start_server(handle_upstream, "127.0.0.1", 0)
    upstream_socket = next(iter(upstream.sockets))
    upstream_host, upstream_port = upstream_socket.getsockname()[:2]
    upstream_url = f"http://{upstream_host}:{upstream_port}"

    proxy = ClaudeHttpProxy(
        state=SimpleNamespace(config=SimpleNamespace()),
        upstream_base_url=upstream_url,
        rewrite=False,
        probe=True,
    )
    proxy_url = await proxy.start()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{proxy_url}/v1/messages",
                headers={
                    "authorization": "Bearer secret",
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-sonnet-4-5",
                    "messages": [{"role": "user", "content": "你妈的，继续解释"}],
                },
            )
        assert response.status_code == 200
        stderr = capsys.readouterr().err
        assert "[claude-http-proxy]" in stderr
        assert '"event": "request"' in stderr
        assert '"path": "/v1/messages"' in stderr
        assert '"Authorization": "[REDACTED]"' in stderr
        assert "Bearer secret" not in stderr
        assert "model=claude-sonnet-4-5" in stderr
        assert "text=你妈的，继续解释" in stderr
    finally:
        await proxy.stop()
        upstream.close()
        await upstream.wait_closed()
