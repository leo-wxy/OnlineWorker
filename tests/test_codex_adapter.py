import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosedError

from plugins.providers.builtin.codex.python.adapter import CodexAdapter


def _fake_create_task(coro, name=None):
    coro.close()
    return MagicMock()


@pytest.mark.asyncio
async def test_connect_disables_websocket_message_size_limit_for_large_resume_payloads():
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value='{"id": 1, "result": {"userAgent": "test", "codexHome": "/tmp", "platformFamily": "unix", "platformOs": "macos"}}'
    )

    adapter = CodexAdapter()

    with patch(
        "plugins.providers.builtin.codex.python.adapter.websockets.connect",
        new=AsyncMock(return_value=ws),
    ) as connect_mock, patch(
        "plugins.providers.builtin.codex.python.adapter.asyncio.create_task",
        side_effect=_fake_create_task,
    ):
        await adapter.connect("ws://127.0.0.1:4722")

    connect_mock.assert_awaited_once_with(
        "ws://127.0.0.1:4722",
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
    )


@pytest.mark.asyncio
async def test_connect_uses_stdio_process_when_url_is_stdio():
    stdout = AsyncMock()
    stdout.read = AsyncMock(
        return_value=b'{"id":1,"result":{"userAgent":"test","codexHome":"/tmp","platformFamily":"unix","platformOs":"macos"}}\n'
    )
    stdin = MagicMock()
    stdin.drain = AsyncMock()
    proc = MagicMock(stdin=stdin, stdout=stdout)

    adapter = CodexAdapter()

    with patch(
        "plugins.providers.builtin.codex.python.adapter.websockets.connect",
        new=AsyncMock(),
    ) as connect_mock, patch(
        "plugins.providers.builtin.codex.python.adapter.asyncio.create_task",
        side_effect=_fake_create_task,
    ):
        await adapter.connect("stdio://", process=proc)

    connect_mock.assert_not_awaited()
    stdin.write.assert_called_once()
    payload = stdin.write.call_args.args[0]
    assert b'"method": "initialize"' in payload or b'"method":"initialize"' in payload
    assert payload.endswith(b"\n")


@pytest.mark.asyncio
async def test_recv_raw_stdio_handles_large_single_line_messages():
    large_json = ('{"id":2,"result":{"thread":"' + ('x' * 70000) + '"}}\n').encode()
    stdout = MagicMock()
    stdout.read = AsyncMock(side_effect=[large_json[:50000], large_json[50000:]])

    adapter = CodexAdapter()
    adapter._transport = "stdio"
    adapter._stdio_stdout = stdout

    raw = await adapter._recv_raw()

    assert raw.startswith('{"id":2')
    assert len(raw) == len(large_json) - 1


@pytest.mark.asyncio
async def test_dispatch_does_not_block_on_slow_event_callback():
    adapter = CodexAdapter()
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_callback(method, payload):
        assert method == "app-server-event"
        started.set()
        await release.wait()

    adapter.on_event(slow_callback)

    raw = json.dumps({
        "method": "turn/started",
        "params": {
            "threadId": "tid-1",
        },
    })

    await asyncio.wait_for(adapter._dispatch(raw), timeout=0.1)
    await asyncio.wait_for(started.wait(), timeout=0.1)

    release.set()
    await asyncio.sleep(0)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_dispatch_does_not_block_on_slow_server_request_callback():
    adapter = CodexAdapter()
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_callback(method, params, request_id):
        assert method == "item/commandExecution/requestApproval"
        assert request_id == 9
        assert params["threadId"] == "tid-approval"
        started.set()
        await release.wait()

    adapter.on_server_request(slow_callback)

    raw = json.dumps({
        "id": 9,
        "method": "item/commandExecution/requestApproval",
        "params": {
            "threadId": "tid-approval",
            "command": "echo hi",
        },
    })

    await asyncio.wait_for(adapter._dispatch(raw), timeout=0.1)
    await asyncio.wait_for(started.wait(), timeout=0.1)

    release.set()
    await asyncio.sleep(0)
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_dispatch_preserves_notification_order():
    adapter = CodexAdapter()
    handled: list[str] = []
    done = asyncio.Event()

    async def callback(method, payload):
        handled.append(payload["message"]["params"]["threadId"])
        if len(handled) == 2:
            done.set()

    adapter.on_event(callback)

    raw1 = json.dumps({
        "method": "turn/started",
        "params": {
            "threadId": "tid-1",
        },
    })
    raw2 = json.dumps({
        "method": "turn/completed",
        "params": {
            "threadId": "tid-2",
        },
    })

    await adapter._dispatch(raw1)
    await adapter._dispatch(raw2)
    await asyncio.wait_for(done.wait(), timeout=0.2)

    assert handled == ["tid-1", "tid-2"]
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_ws_heartbeat_uses_transport_ping_instead_of_rpc_calls():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._transport = "ws"

    ping_waiter = asyncio.Future()
    ping_waiter.set_result(0.01)
    ws = MagicMock()
    ws.ping = AsyncMock(return_value=ping_waiter)
    adapter._ws = ws

    adapter._call = AsyncMock()

    sleep_calls = 0

    async def fake_sleep(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            adapter._connected = False

    with patch("plugins.providers.builtin.codex.python.adapter.asyncio.sleep", side_effect=fake_sleep):
        await adapter._heartbeat_loop()

    ws.ping.assert_awaited_once()
    adapter._call.assert_not_awaited()


@pytest.mark.asyncio
async def test_stdio_heartbeat_keeps_existing_rpc_behavior():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._transport = "stdio"
    adapter._call = AsyncMock(return_value={"data": []})

    sleep_calls = 0

    async def fake_sleep(_seconds):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            adapter._connected = False

    with patch("plugins.providers.builtin.codex.python.adapter.asyncio.sleep", side_effect=fake_sleep):
        await adapter._heartbeat_loop()

    adapter._call.assert_awaited_once_with("thread/list", {"limit": 1})


@pytest.mark.asyncio
async def test_start_thread_passes_registered_workspace_cwd():
    adapter = CodexAdapter()
    adapter._workspace_cwd_map["codex:onlineWorker"] = "/Users/example/Projects/onlineWorker"
    adapter._call = AsyncMock(return_value={"id": "tid-new"})

    result = await adapter.start_thread("codex:onlineWorker")

    adapter._call.assert_awaited_once_with(
        "thread/start",
        {"cwd": "/Users/example/Projects/onlineWorker"},
    )
    assert result == {"id": "tid-new"}
    assert adapter._thread_workspace_map["tid-new"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_start_thread_records_mapping_when_app_server_returns_nested_thread_object():
    adapter = CodexAdapter()
    adapter._workspace_cwd_map["codex:onlineWorker"] = "/Users/example/Projects/onlineWorker"
    adapter._call = AsyncMock(return_value={"thread": {"id": "tid-nested"}})

    result = await adapter.start_thread("codex:onlineWorker")

    adapter._call.assert_awaited_once_with(
        "thread/start",
        {"cwd": "/Users/example/Projects/onlineWorker"},
    )
    assert result == {"thread": {"id": "tid-nested"}}
    assert adapter._thread_workspace_map["tid-nested"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_send_user_message_records_thread_mapping_before_turn_start():
    adapter = CodexAdapter()

    async def fake_call(method, params):
        assert method == "turn/start"
        assert params == {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
        }
        assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"
        return {"ok": True}

    adapter._call = AsyncMock(side_effect=fake_call)

    result = await adapter.send_user_message("codex:onlineWorker", "tid-live", "hello")

    assert result == {"ok": True}
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_send_user_message_can_override_approval_policy():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message(
        "codex:onlineWorker",
        "tid-live",
        "hello",
        approval_policy="untrusted",
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalPolicy": "untrusted",
        },
    )


@pytest.mark.asyncio
async def test_send_user_message_can_override_sandbox_policy():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message(
        "codex:onlineWorker",
        "tid-live",
        "hello",
        sandbox_policy={"type": "readOnly"},
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "sandboxPolicy": {"type": "readOnly"},
        },
    )


@pytest.mark.asyncio
async def test_send_user_message_can_override_approvals_reviewer():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message(
        "codex:onlineWorker",
        "tid-live",
        "hello",
        approvals_reviewer="user",
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "user",
        },
    )


def test_update_thread_workspace_map_uses_nested_thread_id_and_cwd():
    adapter = CodexAdapter()
    adapter._workspace_cwd_map["codex:onlineWorker"] = "/Users/example/Projects/onlineWorker"

    adapter._update_thread_workspace_map(
        "thread/started",
        {
            "thread": {"id": "tid-from-thread-object"},
            "cwd": "/Users/example/Projects/onlineWorker",
        },
    )

    assert adapter._thread_workspace_map["tid-from-thread-object"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_list_models_calls_app_server_model_list():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(
        return_value={
            "data": [
                {
                    "model": "gpt-5.4",
                    "displayName": "GPT-5.4",
                }
            ]
        }
    )

    result = await adapter.list_models(include_hidden=True, limit=20)

    adapter._call.assert_awaited_once_with(
        "model/list",
        {
            "includeHidden": True,
            "limit": 20,
        },
    )
    assert result == [{"model": "gpt-5.4", "displayName": "GPT-5.4"}]


@pytest.mark.asyncio
async def test_set_thread_model_overrides_uses_turn_start_without_input_text():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"thread": {"id": "tid-1"}})

    result = await adapter.set_thread_model_config(
        "codex:onlineWorker",
        "tid-1",
        model="gpt-5.4",
        reasoning_effort="high",
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-1",
            "input": [],
            "model": "gpt-5.4",
            "effort": "high",
        },
    )
    assert result == {"thread": {"id": "tid-1"}}


@pytest.mark.asyncio
async def test_archive_thread_calls_app_server_archive_method():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"id": "tid-archived"})

    result = await adapter.archive_thread("codex:onlineWorker", "tid-archived")

    adapter._call.assert_awaited_once_with(
        "thread/archive",
        {"threadId": "tid-archived"},
    )
    assert result == {"id": "tid-archived"}


def test_disconnect_diagnostics_include_recent_inbound_and_outbound_context():
    adapter = CodexAdapter()

    adapter._record_protocol_message(
        "outbound",
        json.dumps(
            {
                "id": 8,
                "method": "turn/start",
                "params": {
                    "threadId": "tid-live",
                    "input": [{"type": "text", "text": "hello"}],
                },
            }
        ),
    )
    adapter._record_protocol_message(
        "inbound",
        json.dumps(
            {
                "id": 0,
                "method": "item/commandExecution/requestApproval",
                "params": {
                    "threadId": "tid-live",
                    "turnId": "turn-1",
                    "command": "ps -axo",
                },
            }
        ),
    )

    snapshot = adapter._build_disconnect_diagnostics()

    assert "turn/start" in snapshot
    assert "requestApproval" in snapshot
    assert "tid-live" in snapshot


@pytest.mark.asyncio
async def test_reply_server_request_logs_request_context(caplog):
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._send_raw = AsyncMock()

    with caplog.at_level(logging.INFO):
        await adapter.reply_server_request(
            "codex:onlineWorker",
            7,
            {"decision": "accept"},
        )

    assert "reply_server_request" in caplog.text
    assert "request_id=7" in caplog.text
    assert "workspace_id=codex:onlineWorker" in caplog.text
    assert "accept" in caplog.text


@pytest.mark.asyncio
async def test_call_normalizes_websocket_close_error_and_notifies_disconnect():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._transport = "ws"
    adapter._ws = MagicMock()
    adapter._ws.send = AsyncMock(side_effect=ConnectionClosedError(None, None))

    disconnect_count = 0

    def _on_disconnect():
        nonlocal disconnect_count
        disconnect_count += 1

    adapter.on_disconnect(_on_disconnect)

    with pytest.raises(RuntimeError, match="app-server 连接断开") as exc_info:
        await adapter._call("turn/start", {"threadId": "tid-live", "input": []})

    assert "no close frame received or sent" not in str(exc_info.value)
    assert adapter._connected is False
    assert adapter._pending == {}
    assert disconnect_count == 1
