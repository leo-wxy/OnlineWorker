import asyncio
import json
import os
import stat
import uuid
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import AsyncMock

import pytest
import websockets

from core.state import AppState, PendingApproval
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo
from plugins.providers.builtin.codex.python.remote_proxy import (
    CODEX_REMOTE_PROXY_SOCKET_NAME,
    CodexRemoteMessageProxy,
    UPSTREAM_UNAVAILABLE_CLOSE_CODE,
    _ProxyConnectionContext,
    _ProxyApprovalRace,
    default_codex_remote_proxy_url,
)


def test_codex_remote_proxy_default_unix_url_uses_data_dir(tmp_path):
    assert default_codex_remote_proxy_url(str(tmp_path)) == (
        f"unix://{tmp_path / CODEX_REMOTE_PROXY_SOCKET_NAME}"
    )


def test_codex_remote_proxy_default_unix_url_quotes_spaces():
    data_dir = "/Users/example/Library/Application Support/OnlineWorker"

    assert default_codex_remote_proxy_url(data_dir) == (
        f"unix://{quote(f'{data_dir}/{CODEX_REMOTE_PROXY_SOCKET_NAME}', safe='/')}"
    )


def test_codex_remote_proxy_injects_and_filters_thread_list_cwd():
    proxy = CodexRemoteMessageProxy(
        state=AppState(storage=AppStorage(), config=SimpleNamespace(data_dir="/tmp/onlineworker-test")),
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
    )
    context = _ProxyConnectionContext(
        connection_id="client-1",
        client_cwd="/Users/example/current",
    )

    outbound = proxy._maybe_rewrite_thread_list_request(
        json.dumps({"id": 11, "method": "thread/list", "params": {}}),
        context,
    )

    assert json.loads(outbound) == {
        "id": 11,
        "method": "thread/list",
        "params": {"cwd": "/Users/example/current"},
    }

    response = proxy._maybe_filter_thread_list_response(
        json.dumps(
            {
                "id": 11,
                "result": {
                    "data": [
                        {"id": "same", "cwd": "/Users/example/current"},
                        {"id": "other", "cwd": "/Users/example/other"},
                        {"id": "missing"},
                    ],
                    "nextCursor": None,
                    "backwardsCursor": None,
                },
            }
        ),
        context,
    )

    assert json.loads(response) == {
        "id": 11,
        "result": {
            "data": [{"id": "same", "cwd": "/Users/example/current"}],
            "nextCursor": None,
            "backwardsCursor": None,
        },
    }


def test_codex_remote_proxy_filters_thread_list_empty_when_cwd_unknown():
    proxy = CodexRemoteMessageProxy(
        state=AppState(storage=AppStorage(), config=SimpleNamespace(data_dir="/tmp/onlineworker-test")),
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
    )
    context = _ProxyConnectionContext(connection_id="client-1")

    outbound = proxy._maybe_rewrite_thread_list_request(
        json.dumps({"id": 12, "method": "thread/list", "params": {}}),
        context,
    )
    assert json.loads(outbound) == {"id": 12, "method": "thread/list", "params": {}}

    response = proxy._maybe_filter_thread_list_response(
        json.dumps(
            {
                "id": 12,
                "result": {
                    "data": [
                        {"id": "same", "cwd": "/Users/example/current"},
                        {"id": "other", "cwd": "/Users/example/other"},
                    ],
                    "nextCursor": None,
                    "backwardsCursor": None,
                },
            }
        ),
        context,
    )

    assert json.loads(response)["result"]["data"] == []


@pytest.mark.asyncio
async def test_codex_remote_proxy_mirrors_approval_while_forwarding_to_cli(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="project",
        path="/tmp/project",
        tool="codex",
        topic_id=700,
        daemon_workspace_id="codex:/tmp/project",
    )
    ws.threads["tid-cli"] = ThreadInfo(thread_id="tid-cli", topic_id=701, archived=False)
    storage.workspaces["codex:/tmp/project"] = ws
    state = AppState(
        storage=storage,
        config=SimpleNamespace(data_dir="/tmp/onlineworker-test"),
    )
    state.telegram_bot = SimpleNamespace()
    state.group_chat_id = -100123

    sent = []

    async def fake_send_approval_to_telegram(
        state_arg,
        bot,
        group_chat_id,
        topic_id,
        workspace_id,
        info,
        *,
        interactive=True,
        notice_suffix="",
    ):
        sent.append(
            {
                "group_chat_id": group_chat_id,
                "topic_id": topic_id,
                "workspace_id": workspace_id,
                "request_id": info.request_id,
                "approval_source": info.approval_source,
                "notice_suffix": notice_suffix,
            }
        )
        state_arg.pending_approvals[42] = PendingApproval(
            request_id=info.request_id,
            workspace_id=workspace_id,
            thread_id=info.thread_id or "",
            cmd=info.command,
            justification=info.reason,
            tool_name=info.tool_name,
            tool_type=info.tool_type,
            approval_source=info.approval_source,
            amendment_decision=info.amendment_decision,
        )

    monkeypatch.setattr(
        "bot.events.send_approval_to_telegram",
        fake_send_approval_to_telegram,
    )

    proxy = CodexRemoteMessageProxy(
        state=state,
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
        approval_timeout_seconds=1,
    )
    upstream_sent = []

    class FakeUpstream:
        async def send(self, message):
            upstream_sent.append(message)

    context = _ProxyConnectionContext(connection_id="client-1")
    proxy._maybe_start_server_request_mirror(
        json.dumps(
            {
                "id": 7,
                "method": "execCommandApproval",
                "params": {
                    "threadId": "tid-cli",
                    "command": ["/bin/zsh", "-lc", "printf ok"],
                    "reason": "test approval",
                },
            }
        ),
        context,
        FakeUpstream(),
    )
    await asyncio.sleep(0)

    assert upstream_sent == []
    assert "7" in context.pending_approval_races
    assert sent == [
        {
            "group_chat_id": -100123,
            "topic_id": 701,
            "workspace_id": "codex:/tmp/project",
            "request_id": "codex_remote_proxy:client-1:7",
            "approval_source": "codex_remote_proxy",
            "notice_suffix": "此请求已在 Codex CLI 中弹出，可在 CLI 或 TG 中处理。",
        }
    ]

    assert proxy._maybe_mark_cli_approval_response(
        json.dumps({"id": 7, "result": {"decision": "approved"}}),
        context,
    ) is False
    assert upstream_sent == []
    assert context.pending_approval_races == {}
    assert not state.pending_approvals
    assert (
        "codex_remote_proxy:client-1:7"
        not in state.get_provider_runtime("codex").pending_approval_decisions
    )


def test_codex_remote_proxy_cleans_tg_mirror_when_app_server_resolves_approval():
    state = AppState(storage=AppStorage(), config=SimpleNamespace(data_dir="/tmp/onlineworker-test"))
    proxy = CodexRemoteMessageProxy(
        state=state,
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
        approval_timeout_seconds=1,
    )
    context = _ProxyConnectionContext(connection_id="client-1")
    pending = state.ensure_pending_approval_decision(
        "codex",
        "codex_remote_proxy:client-1:7",
    )
    state.pending_approvals[42] = PendingApproval(
        request_id="codex_remote_proxy:client-1:7",
        workspace_id="codex:/tmp/project",
        thread_id="tid-cli",
        cmd="/bin/zsh -lc 'printf ok'",
        justification="test approval",
        tool_name="exec",
        tool_type="codex",
        approval_source="codex_remote_proxy",
    )
    race = _ProxyApprovalRace(
        request_id=7,
        request_key="7",
        proxy_request_id="codex_remote_proxy:client-1:7",
        method="execCommandApproval",
        thread_id="tid-cli",
        pending=pending,
    )
    context.pending_approval_races["7"] = race

    handled = proxy._maybe_handle_server_request_resolved(
        json.dumps(
            {
                "method": "serverRequest/resolved",
                "params": {"requestId": 7, "threadId": "tid-cli"},
            }
        ),
        context,
    )

    assert handled is True
    assert race.answered is True
    assert race.answer_source == "app_server_resolved"
    assert pending.event.is_set()
    assert context.pending_approval_races == {}
    assert state.pending_approvals == {}
    assert (
        "codex_remote_proxy:client-1:7"
        not in state.get_provider_runtime("codex").pending_approval_decisions
    )


@pytest.mark.asyncio
async def test_codex_remote_proxy_passes_approval_through_when_thread_is_unbound(monkeypatch):
    state = AppState(storage=AppStorage(), config=SimpleNamespace(data_dir="/tmp/onlineworker-test"))
    state.telegram_bot = SimpleNamespace()
    state.group_chat_id = -100123

    async def fail_send_approval_to_telegram(*args, **kwargs):
        raise AssertionError("unbound approval should not be sent to TG")

    monkeypatch.setattr(
        "bot.events.send_approval_to_telegram",
        fail_send_approval_to_telegram,
    )
    proxy = CodexRemoteMessageProxy(
        state=state,
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
        approval_timeout_seconds=1,
    )

    context = _ProxyConnectionContext(connection_id="client-1")
    proxy._maybe_start_server_request_mirror(
        json.dumps(
            {
                "id": 7,
                "method": "execCommandApproval",
                "params": {"threadId": "tid-missing"},
            }
        ),
        context,
        SimpleNamespace(send=AsyncMock()),
    )

    assert context.pending_approval_races == {}


@pytest.mark.asyncio
async def test_codex_remote_proxy_relays_unix_client_to_unix_upstream(tmp_path):
    socket_root = f"/tmp/ow-rp-{uuid.uuid4().hex[:8]}"
    os.makedirs(socket_root, exist_ok=True)
    upstream_path = os.path.join(socket_root, "upstream.sock")
    proxy_path = os.path.join(socket_root, "proxy.sock")
    seen = []

    async def upstream_handler(conn):
        message = await conn.recv()
        seen.append(message)
        await conn.send(json.dumps({"id": 1, "result": {"ok": True}}))

    upstream_server = await websockets.unix_serve(
        upstream_handler,
        path=upstream_path,
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
        compression=None,
    )
    proxy = CodexRemoteMessageProxy(
        state=AppState(storage=AppStorage(), config=SimpleNamespace(data_dir=str(tmp_path))),
        upstream_url=f"unix://{upstream_path}",
        listen_url=f"unix://{proxy_path}",
        approval_timeout_seconds=1,
    )

    try:
        assert await proxy.start() == f"unix://{proxy_path}"
        assert stat.S_IMODE(os.stat(socket_root).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(proxy_path).st_mode) == 0o600
        async with websockets.unix_connect(
            path=proxy_path,
            uri="ws://localhost/",
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            compression=None,
        ) as client:
            await client.send(json.dumps({"id": 1, "method": "ping", "params": {}}))
            response = await client.recv()

        assert seen == ['{"id": 1, "method": "ping", "params": {}}']
        assert json.loads(response) == {"id": 1, "result": {"ok": True}}
    finally:
        await proxy.stop()
        upstream_server.close()
        await upstream_server.wait_closed()
        for path in (upstream_path, proxy_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(socket_root)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_codex_remote_proxy_forwards_server_request_resolved_event(tmp_path):
    socket_root = f"/tmp/ow-rp-{uuid.uuid4().hex[:8]}"
    os.makedirs(socket_root, exist_ok=True)
    upstream_path = os.path.join(socket_root, "upstream.sock")
    proxy_path = os.path.join(socket_root, "proxy.sock")
    resolved = json.dumps(
        {
            "method": "serverRequest/resolved",
            "params": {"requestId": 7, "threadId": "tid-cli"},
        }
    )

    async def upstream_handler(conn):
        await conn.send(resolved)
        await conn.close()

    upstream_server = await websockets.unix_serve(
        upstream_handler,
        path=upstream_path,
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
        compression=None,
    )
    proxy = CodexRemoteMessageProxy(
        state=AppState(storage=AppStorage(), config=SimpleNamespace(data_dir=str(tmp_path))),
        upstream_url=f"unix://{upstream_path}",
        listen_url=f"unix://{proxy_path}",
        approval_timeout_seconds=1,
    )

    try:
        await proxy.start()
        async with websockets.unix_connect(
            path=proxy_path,
            uri="ws://localhost/",
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            compression=None,
        ) as client:
            response = await client.recv()

        assert json.loads(response) == json.loads(resolved)
    finally:
        await proxy.stop()
        upstream_server.close()
        await upstream_server.wait_closed()
        for path in (upstream_path, proxy_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(socket_root)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_codex_remote_proxy_closes_client_when_unix_upstream_is_unavailable(tmp_path):
    socket_root = f"/tmp/ow-rp-{uuid.uuid4().hex[:8]}"
    os.makedirs(socket_root, exist_ok=True)
    upstream_path = os.path.join(socket_root, "missing-upstream.sock")
    proxy_path = os.path.join(socket_root, "proxy.sock")
    proxy = CodexRemoteMessageProxy(
        state=AppState(storage=AppStorage(), config=SimpleNamespace(data_dir=str(tmp_path))),
        upstream_url=f"unix://{upstream_path}",
        listen_url=f"unix://{proxy_path}",
        approval_timeout_seconds=1,
    )

    try:
        await proxy.start()
        async with websockets.unix_connect(
            path=str(proxy_path),
            uri="ws://localhost/",
            max_size=None,
            ping_interval=None,
            ping_timeout=None,
            compression=None,
        ) as client:
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
                await client.recv()

        assert exc_info.value.rcvd.code == UPSTREAM_UNAVAILABLE_CLOSE_CODE
    finally:
        await proxy.stop()
        for path in (upstream_path, proxy_path):
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
        try:
            os.rmdir(socket_root)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_codex_remote_proxy_cleans_pending_when_telegram_reply_hits_closed_upstream(monkeypatch):
    state = AppState(storage=AppStorage(), config=SimpleNamespace(data_dir="/tmp/onlineworker-test"))
    state.telegram_bot = SimpleNamespace()
    state.group_chat_id = -100123

    async def fake_send_approval_to_telegram(
        state_arg,
        bot,
        group_chat_id,
        topic_id,
        workspace_id,
        info,
        *,
        interactive=True,
        notice_suffix="",
    ):
        state_arg.pending_approvals[42] = PendingApproval(
            request_id=info.request_id,
            workspace_id=workspace_id,
            thread_id=info.thread_id or "",
            cmd=info.command,
            justification=info.reason,
            tool_name=info.tool_name,
            tool_type=info.tool_type,
            approval_source=info.approval_source,
            amendment_decision=info.amendment_decision,
        )

    monkeypatch.setattr(
        "bot.events.send_approval_to_telegram",
        fake_send_approval_to_telegram,
    )

    proxy = CodexRemoteMessageProxy(
        state=state,
        upstream_url="unix:///tmp/codex-app-server.sock",
        listen_url="unix:///tmp/onlineworker-proxy.sock",
        approval_timeout_seconds=1,
    )
    context = _ProxyConnectionContext(connection_id="client-1")
    pending = state.ensure_pending_approval_decision(
        "codex",
        "codex_remote_proxy:client-1:7",
    )
    race = _ProxyApprovalRace(
        request_id=7,
        request_key="7",
        proxy_request_id="codex_remote_proxy:client-1:7",
        method="execCommandApproval",
        thread_id="tid-cli",
        pending=pending,
    )
    context.pending_approval_races["7"] = race

    class ClosedUpstream:
        async def send(self, message):
            raise OSError("upstream closed")

    async def approve_from_telegram():
        await asyncio.sleep(0)
        pending.decision = "exec_allow"
        pending.event.set()

    asyncio.create_task(approve_from_telegram())

    await proxy._mirror_approval_to_telegram(
        context,
        ClosedUpstream(),
        race,
        workspace_id="codex:/tmp/project",
        topic_id=701,
        group_chat_id=-100123,
        info=SimpleNamespace(
            request_id="codex_remote_proxy:client-1:7",
            thread_id="tid-cli",
            command=["/bin/zsh", "-lc", "printf ok"],
            reason="test approval",
            tool_name="exec",
            tool_type="exec",
            approval_source="codex_remote_proxy",
            amendment_decision=None,
        ),
    )

    assert context.pending_approval_races == {}
    assert not state.pending_approvals
    assert (
        "codex_remote_proxy:client-1:7"
        not in state.get_provider_runtime("codex").pending_approval_decisions
    )
