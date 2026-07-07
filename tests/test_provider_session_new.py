from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.state import AppState
from core.storage import AppStorage
from core.storage import ThreadInfo, WorkspaceInfo


def test_extract_started_thread_id_normalizes_supported_shapes():
    from core.providers.thread_result import extract_started_thread_id

    assert extract_started_thread_id({"id": " tid-top "}) == "tid-top"
    assert extract_started_thread_id({"thread": {"id": "tid-nested"}}) == "tid-nested"
    assert extract_started_thread_id({}) == ""
    assert extract_started_thread_id(None) == ""


@pytest.mark.asyncio
async def test_start_real_provider_thread_materializes_new_thread():
    from core.provider_session_new import start_real_provider_thread

    class _FakeAdapter:
        def __init__(self):
            self.start_thread = AsyncMock(return_value={"thread": {"id": "tid-new"}})

    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/workspace",
    )
    adapter = _FakeAdapter()

    started = await start_real_provider_thread(
        adapter,
        ws,
        "overlay-tool:/tmp/workspace",
        provider_id="overlay-tool",
        preview="first message",
        source="provider",
    )

    assert started.thread_id == "tid-new"
    assert started.created_thread is True
    assert started.thread_info is ws.threads["tid-new"]
    assert started.thread_info.preview == "first message"
    assert started.thread_info.archived is False
    assert started.thread_info.is_active is True
    assert started.thread_info.source == "provider"
    adapter.start_thread.assert_awaited_once_with("overlay-tool:/tmp/workspace")


@pytest.mark.asyncio
async def test_start_real_provider_thread_rejects_local_placeholder_thread_id():
    from core.provider_session_new import start_real_provider_thread

    class _FakeAdapter:
        def __init__(self):
            self.start_thread = AsyncMock(return_value={"id": "app:codex:placeholder"})

    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="codex",
        daemon_workspace_id="codex:/tmp/workspace",
    )

    with pytest.raises(RuntimeError, match="本地占位"):
        await start_real_provider_thread(
            _FakeAdapter(),
            ws,
            "codex:/tmp/workspace",
            provider_id="codex",
            preview="first message",
            source="app",
        )


@pytest.mark.asyncio
async def test_start_real_provider_thread_reuses_existing_thread_info():
    from core.provider_session_new import start_real_provider_thread

    class _FakeAdapter:
        def __init__(self):
            self.start_thread = AsyncMock(return_value={"id": "tid-existing"})

    existing = ThreadInfo(
        thread_id="tid-existing",
        preview="keep me",
        archived=True,
        is_active=False,
        source="imported",
    )
    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/workspace",
        threads={"tid-existing": existing},
    )

    started = await start_real_provider_thread(
        _FakeAdapter(),
        ws,
        "overlay-tool:/tmp/workspace",
        provider_id="overlay-tool",
        preview=None,
        source="provider",
    )

    assert started.created_thread is False
    assert started.thread_info is existing
    assert existing.preview == "keep me"
    assert existing.archived is False
    assert existing.is_active is True
    assert existing.source == "imported"


def test_validate_new_provider_thread_request_uses_provider_hook(monkeypatch):
    from core.provider_session_new import validate_new_provider_thread_request

    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="codex",
        daemon_workspace_id="codex:/tmp/workspace",
    )
    seen = {}

    monkeypatch.setattr(
        "core.provider_session_new.get_provider",
        lambda name, cfg=None: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                validate_new_thread=lambda state, ws_info, initial_text: (
                    seen.setdefault("call", (state, ws_info, initial_text)),
                    "blocked",
                )[1]
            ),
        )
        if name == "codex"
        else None,
    )

    error = validate_new_provider_thread_request(
        object(),
        ws,
        text="first message",
        attachments=[],
    )

    assert error == "blocked"
    assert seen["call"][1] is ws
    assert seen["call"][2] == "first message"


def test_validate_new_provider_thread_request_treats_attachment_only_as_non_empty_payload(monkeypatch):
    from core.provider_session_new import validate_new_provider_thread_request

    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="codex",
        daemon_workspace_id="codex:/tmp/workspace",
    )
    seen = {}

    monkeypatch.setattr(
        "core.provider_session_new.get_provider",
        lambda name, cfg=None: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                validate_new_thread=lambda state, ws_info, initial_text: (
                    seen.setdefault("initial_text", initial_text),
                    None,
                )[1]
            ),
        )
        if name == "codex"
        else None,
    )

    error = validate_new_provider_thread_request(
        object(),
        ws,
        text="",
        attachments=[{"kind": "image", "path": "/tmp/image.png"}],
    )

    assert error is None
    assert seen["initial_text"]


@pytest.mark.asyncio
async def test_send_started_provider_thread_message_runs_message_hooks_send(monkeypatch):
    from core.provider_session_new import send_started_provider_thread_message

    state = AppState(storage=AppStorage())
    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/workspace",
        threads={},
    )
    thread = ThreadInfo(
        thread_id="tid-new",
        preview="first message",
        archived=False,
        is_active=True,
        source="provider",
    )
    ws.threads["tid-new"] = thread

    adapter = SimpleNamespace(connected=True)
    called = {}

    async def ensure_connected(state_obj, current_adapter, ws_info, **kwargs):
        called["ensure_connected"] = (state_obj, current_adapter, ws_info.path)
        return current_adapter

    async def send(state_obj, current_adapter, ws_info, thread_info, **kwargs):
        called["send"] = (
            state_obj,
            current_adapter,
            ws_info.daemon_workspace_id,
            thread_info.thread_id,
            kwargs["text"],
            kwargs["attachments"],
        )

    monkeypatch.setattr(
        "core.provider_session_new.get_provider",
        lambda name, cfg=None: SimpleNamespace(
            message_hooks=SimpleNamespace(
                ensure_connected=ensure_connected,
                send=send,
            ),
            thread_hooks=SimpleNamespace(),
        )
        if name == "overlay-tool"
        else None,
    )

    result = await send_started_provider_thread_message(
        state,
        ws,
        thread,
        "overlay-tool:/tmp/workspace",
        provider_id="overlay-tool",
        text="first message",
        attachments=[{"kind": "file", "path": "/tmp/workspace/readme.md"}],
        source="telegram_new_thread",
        adapter=adapter,
    )

    assert result.text == "first message"
    assert result.thread_id == "tid-new"
    assert called["send"][2:] == (
        "overlay-tool:/tmp/workspace",
        "tid-new",
            "first message",
        [{"kind": "file", "path": "/tmp/workspace/readme.md"}],
    )
    assert [event["kind"] for event in state.message_bus.recent_events()] == [
        "message.user.submitted",
        "message.user.accepted",
    ]
    activity = state.message_bus.session_activity("overlay-tool", "tid-new")
    assert activity["workspacePath"] == "/tmp/workspace"
    assert activity["lastUserMessage"] == "first message"


def test_build_provider_session_summary_shapes_provider_backed_session_row():
    from core.provider_session_new import build_provider_session_summary

    ws = WorkspaceInfo(
        name="workspace",
        path="/tmp/workspace",
        tool="overlay-tool",
        daemon_workspace_id="overlay-tool:/tmp/workspace",
    )
    thread = ThreadInfo(
        thread_id="tid-new",
        preview="first message",
        archived=False,
        is_active=True,
        source="provider",
    )

    summary = build_provider_session_summary(
        ws,
        thread,
        preview_text="first message",
        provider_active=True,
        now=123,
    )

    assert summary == {
        "id": "tid-new",
        "title": "first message",
        "preview": "first message",
        "workspace": "/tmp/workspace",
        "archived": False,
        "providerActive": True,
        "updatedAt": 123,
        "createdAt": 123,
        "source": "provider",
    }
