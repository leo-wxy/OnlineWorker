import asyncio
import json
import logging
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosedError

from plugins.providers.builtin.codex.python.adapter import CodexAdapter


def _fake_create_task(coro, name=None):
    coro.close()
    return MagicMock()


@pytest.mark.asyncio
@pytest.mark.parametrize("other_status", ["idle", "active", "systemError", "unknown"])
async def test_idle_release_checks_every_loaded_thread(other_status):
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._supports_idle_restart = True
    restart = AsyncMock(return_value=("unix:///tmp/ow-test.sock", MagicMock()))
    adapter.configure_idle_restart(restart)
    adapter.connect = AsyncMock()
    adapter._authoritative_live_sessions.update({"done-thread", "other-thread"})
    adapter._call = AsyncMock(side_effect=[
        {"data": ["done-thread", "other-thread"], "nextCursor": None},
        {"thread": {"status": {"type": "idle"}}},
        {"thread": {"status": {"type": other_status}}},
    ])

    await adapter._release_idle_backend()

    if other_status == "idle":
        restart.assert_awaited_once()
        adapter.connect.assert_awaited_once()
        assert not adapter.has_authoritative_live_session("done-thread")
        assert adapter._released_threads == {"done-thread", "other-thread"}
    else:
        restart.assert_not_awaited()
        assert adapter.has_authoritative_live_session("done-thread")


@pytest.mark.asyncio
async def test_idle_release_aborts_if_a_send_starts_during_idle_probe():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._supports_idle_restart = True
    restart = AsyncMock()
    adapter.configure_idle_restart(restart)

    async def probe(method, params):
        if method == "thread/loaded/list":
            return {"data": ["done-thread"]}
        adapter._activity_sequence += 1
        return {"thread": {"status": {"type": "idle"}}}

    adapter._call = AsyncMock(side_effect=probe)
    await adapter._release_idle_backend()
    restart.assert_not_awaited()
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_send_waits_for_idle_restart_and_resumes_released_thread():
    adapter = CodexAdapter()
    adapter._connected = False
    adapter._released_threads.add("done-thread")
    release = asyncio.Event()
    calls = []

    async def restart():
        await release.wait()
        adapter._connected = True

    async def send_raw(payload):
        request = json.loads(payload)
        calls.append(request["method"])
        await adapter._dispatch(json.dumps({"id": request["id"], "result": {"ok": True}}))

    adapter._send_raw = send_raw
    adapter._idle_restart_task = asyncio.create_task(restart())
    send = asyncio.create_task(adapter.send_user_message("ws", "done-thread", "continue"))
    await asyncio.sleep(0)
    assert adapter.connected
    assert not calls
    release.set()
    await asyncio.wait_for(send, timeout=1)
    assert calls == ["thread/resume", "turn/start"]
    assert "done-thread" not in adapter._released_threads


@pytest.mark.asyncio
async def test_idle_release_waits_for_final_callback_and_ignores_hook_events(monkeypatch):
    monkeypatch.setattr("plugins.providers.builtin.codex.python.adapter.IDLE_RELEASE_DELAY_SECONDS", 0)
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._supports_idle_restart = True
    adapter.configure_idle_restart(AsyncMock())
    adapter._release_idle_backend = AsyncMock()
    callback_started = asyncio.Event()
    release = asyncio.Event()

    async def callback(method, envelope):
        callback_started.set()
        await release.wait()

    adapter.on_event(callback)
    await adapter._dispatch(json.dumps({
        "method": "turn/completed",
        "params": {"threadId": "done-thread", "turn": {"id": "done-turn"}},
    }))
    await callback_started.wait()
    adapter._release_idle_backend.assert_not_awaited()
    release.set()
    await adapter._event_queue.join()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    adapter._release_idle_backend.assert_awaited_once()
    adapter._released_threads.add("done-thread")
    adapter._handoff_released_sessions()
    duplicate = await adapter.ingest_external_hook_payload({
        "hook_event_name": "AgentTurnComplete", "session_id": "done-thread",
        "turn_id": "done-turn", "last_assistant_message": "already sent", "source": "codex_notify",
    })
    assert duplicate.get("deduped") is True
    assert duplicate["emitted"] == 0
    await adapter._emit_external_hook_event("ws", "turn/completed", {"_mirroredOnly": True})
    adapter._release_idle_backend.assert_awaited_once()
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_idle_release_keeps_unresolved_server_requests_until_native_resolution():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._supports_idle_restart = True
    restart = AsyncMock(return_value=("unix:///tmp/ow-test.sock", MagicMock()))
    adapter.configure_idle_restart(restart)
    adapter.connect = AsyncMock()
    adapter._call = AsyncMock(side_effect=[
        {"data": ["done-thread"]}, {"thread": {"status": {"type": "idle"}}},
    ])
    await adapter._dispatch(json.dumps({"id": 7, "method": "item/tool/requestUserInput", "params": {}}))
    await adapter._release_idle_backend()
    adapter._call.assert_not_awaited()
    restart.assert_not_awaited()
    await adapter._dispatch(json.dumps({"method": "serverRequest/resolved", "params": {"requestId": 7}}))
    await adapter._release_idle_backend()
    restart.assert_awaited_once()


@pytest.mark.asyncio
async def test_idle_restart_failure_notifies_regular_recovery_once():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter._supports_idle_restart = True
    adapter.configure_idle_restart(AsyncMock(side_effect=RuntimeError("restart failed")))
    adapter._call = AsyncMock(side_effect=[
        {"data": ["done-thread"]}, {"thread": {"status": {"type": "idle"}}},
    ])
    disconnected = MagicMock()
    adapter.on_disconnect(disconnected)
    with pytest.raises(RuntimeError, match="restart failed"):
        await adapter._release_idle_backend()
    adapter._notify_disconnect_callbacks_once()
    disconnected.assert_called_once()
    assert not adapter.connected


@pytest.mark.asyncio
async def test_real_codex_hook_event_marks_installed_definition_verified():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.configure_external_event_bridge("/tmp/onlineworker")
    adapter.on_event(callback)

    with patch(
        "plugins.providers.builtin.codex.python.hook_bridge.mark_onlineworker_codex_hooks_verified",
        return_value={
            "state": "verified",
            "trustPath": "/tmp/onlineworker/codex_hook_trust.json",
            "detail": "",
        },
    ) as mark_verified:
        result = await adapter.ingest_external_hook_payload(
            {
                "hook_event_name": "SessionStart",
                "session_id": "desktop-session",
                "cwd": "/Users/example/Projects/demo",
            }
        )

    assert result["accepted"] is True
    mark_verified.assert_called_once_with("/tmp/onlineworker")
    assert adapter.external_event_status["trustState"] == "verified"


@pytest.mark.asyncio
async def test_external_hook_suppresses_subagent_session_and_later_notify(tmp_path):
    transcript_path = tmp_path / "subagent.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {
                    "id": "subagent-session",
                    "source": {"subagent": {"thread_spawn": {}}},
                    "thread_source": "subagent",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    started = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "SessionStart",
            "session_id": "subagent-session",
            "transcript_path": str(transcript_path),
        }
    )
    completed = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "subagent-session",
            "turn_id": "subagent-turn",
            "last_assistant_message": "内部结果",
            "source": "codex_notify",
        }
    )

    assert started == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "non_user_visible_session",
    }
    assert completed == started
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_hook_suppresses_codex_memories_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    result = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "SessionStart",
            "session_id": "memory-session",
            "cwd": str(tmp_path / ".codex" / "memories"),
        }
    )

    assert result == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "non_user_visible_session",
    }
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_notify_suppresses_subagent_found_in_codex_state():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    with patch(
        "plugins.providers.builtin.codex.python.storage_runtime.list_codex_subagent_thread_ids",
        return_value={"subagent-session"},
    ):
        completed = await adapter.ingest_external_hook_payload(
            {
                "hook_event_name": "AgentTurnComplete",
                "session_id": "subagent-session",
                "turn_id": "subagent-turn",
                "last_assistant_message": "内部结果",
                "source": "codex_notify",
            }
        )

    assert completed == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "non_user_visible_session",
    }
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_external_hook_defers_start_and_suppresses_internal_notify_prompt():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    started = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "SessionStart",
            "session_id": "internal-session",
            "cwd": "/Users/example/Projects/demo",
        }
    )
    completed = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "internal-session",
            "turn_id": "internal-turn",
            "input_messages": [
                "You write the one-line activity update displayed beneath an existing Codex task title. Fill the structured summary field."
            ],
            "last_assistant_message": "内部结果",
        }
    )

    assert started == {"accepted": True, "emitted": 0}
    assert completed == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "non_user_visible_session",
    }
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_app_server_event_marks_session_as_authoritative_live_source():
    adapter = CodexAdapter()

    await adapter._dispatch(
        json.dumps(
            {
                "method": "turn/started",
                "params": {
                    "threadId": "owned-session",
                    "turn": {"id": "owned-turn"},
                },
            }
        )
    )

    assert adapter.has_authoritative_live_session("owned-session") is True
    callback = AsyncMock()
    adapter.on_event(callback)
    result = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "Stop",
            "session_id": "owned-session",
            "turn_id": "owned-turn",
        }
    )
    assert result == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "authoritative_live_source",
    }
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_app_server_hides_codex_memories_workspace_before_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = CodexAdapter()
    callback = AsyncMock()
    adapter.on_event(callback)

    await adapter._dispatch(
        json.dumps(
            {
                "method": "turn/started",
                "params": {
                    "threadId": "memory-session",
                    "cwd": str(tmp_path / ".codex" / "memories"),
                    "turn": {"id": "memory-turn"},
                },
            }
        )
    )

    assert "memory-session" in adapter._hidden_live_sessions
    assert adapter.has_authoritative_live_session("memory-session") is False
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_desktop_stop_hook_enters_message_event_bus():
    from core.messages.bus import MessageEventBus
    from core.messages.publishing import publish_session_message_event
    from core.providers.session_events import normalize_session_event

    bus = MessageEventBus()
    state = MagicMock(message_bus=bus)
    adapter = CodexAdapter()
    adapter.register_workspace_cwd(
        "codex:demo",
        "/Users/example/Projects/demo",
    )

    async def publish_event(method, params):
        event = normalize_session_event(method, params)
        assert event is not None
        publish_session_message_event(state, event)

    adapter.on_event(publish_event)

    result = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "Stop",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "last_assistant_message": "Desktop 任务已经完成。",
        }
    )

    assert result["accepted"] is True
    assert [event["kind"] for event in bus.recent_events()] == [
        "message.assistant.final",
        "turn.completed",
    ]
    final_event = bus.recent_events()[0]
    assert final_event["provider_id"] == "codex"
    assert final_event["workspace_id"] == "codex:demo"
    assert final_event["session_id"] == "desktop-session"
    assert final_event["turn_id"] == "desktop-turn"
    assert final_event["payload"]["text"] == "Desktop 任务已经完成。"


@pytest.mark.asyncio
async def test_desktop_notify_turn_enters_message_event_bus_as_single_ordered_sequence():
    from core.messages.bus import MessageEventBus
    from core.messages.publishing import publish_session_message_event
    from core.providers.session_events import normalize_session_event

    bus = MessageEventBus()
    state = MagicMock(message_bus=bus)
    adapter = CodexAdapter()
    adapter.register_workspace_cwd(
        "codex:demo",
        "/Users/example/Projects/demo",
    )

    async def publish_event(method, params):
        event = normalize_session_event(method, params)
        assert event is not None
        publish_session_message_event(state, event)

    adapter.on_event(publish_event)

    result = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "input_messages": ["检查摘要链路"],
            "last_assistant_message": "摘要链路检查完成。",
            "source": "codex_notify",
        }
    )

    assert result == {"accepted": True, "emitted": 5}
    assert [event["kind"] for event in bus.recent_events()] == [
        "session.created",
        "message.user.submitted",
        "turn.started",
        "message.assistant.final",
        "turn.completed",
    ]
    final_event = bus.recent_events()[3]
    assert final_event["workspace_id"] == "codex:demo"
    assert final_event["session_id"] == "desktop-session"
    assert final_event["turn_id"] == "desktop-turn"
    assert final_event["payload"]["text"] == "摘要链路检查完成。"

    duplicate = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "input_messages": ["检查摘要链路"],
            "last_assistant_message": "摘要链路检查完成。",
            "source": "codex_notify",
        }
    )
    assert duplicate == {"accepted": True, "emitted": 0, "deduped": True}
    assert len(bus.recent_events()) == 5


@pytest.mark.asyncio
async def test_external_event_ingress_installs_hook_primary_and_notify_fallback(monkeypatch):
    hook_install = MagicMock(
        return_value={
            "state": "installed",
            "hooksPath": "/tmp/hooks.json",
            "installedEvents": ["SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"],
            "detail": "",
            "changed": True,
        }
    )
    notify_install = MagicMock(
        return_value={
            "state": "installed",
            "configPath": "/tmp/config.toml",
            "forwardPath": "/tmp/codex_notify_forward.json",
            "detail": "",
            "changed": True,
        }
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.install_onlineworker_codex_hooks",
        hook_install,
    )
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.hook_bridge.install_onlineworker_codex_notify",
        notify_install,
    )
    adapter = CodexAdapter()
    adapter.configure_external_event_bridge("/tmp/onlineworker")

    result = await adapter.install_external_event_ingress()

    hook_install.assert_called_once_with("/tmp/onlineworker")
    notify_install.assert_called_once_with("/tmp/onlineworker")
    assert result["state"] == "installed"
    assert result["installedEvents"] == [
        "SessionStart",
        "UserPromptSubmit",
        "Stop",
        "SessionEnd",
    ]
    assert result["notifyState"] == "installed"


@pytest.mark.asyncio
async def test_hook_start_and_notify_completion_share_one_turn_sequence():
    callback = AsyncMock()
    rollout = MagicMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)
    adapter._desktop_rollout_ingress = rollout

    started = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "prompt": "检查主链去重",
        }
    )
    completed = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "AgentTurnComplete",
            "session_id": "desktop-session",
            "turn_id": "desktop-turn",
            "cwd": "/Users/example/Projects/demo",
            "input_messages": ["检查主链去重"],
            "last_assistant_message": "主链去重完成。",
            "source": "codex_notify",
        }
    )

    assert started == {"accepted": True, "emitted": 3}
    assert completed == {"accepted": True, "emitted": 2}
    assert callback.await_count == 5
    assert [item.args for item in rollout.record_primary_event.call_args_list] == [
        ("desktop-session", "desktop-turn", "started"),
        ("desktop-session", "desktop-turn", "completed"),
    ]


@pytest.mark.asyncio
async def test_source_claim_concurrent_external_prefers_hook():
    events = []
    rollout = MagicMock()
    adapter = CodexAdapter()
    adapter._desktop_rollout_ingress = rollout

    async def collect(_method, envelope):
        events.append(envelope["message"])

    adapter.on_event(collect)
    base = {
        "hook_event_name": "AgentTurnComplete",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "cwd": "/Users/example/Projects/demo",
    }

    rollout_result, notify_result, hook_result = await asyncio.gather(
        adapter.ingest_external_hook_payload({
            **base,
            "source": "codex_rollout",
            "input_messages": ["rollout prompt"],
            "last_assistant_message": "rollout final",
        }),
        adapter.ingest_external_hook_payload({
            **base,
            "source": "codex_notify",
            "input_messages": ["notify prompt"],
            "last_assistant_message": "notify final",
        }),
        adapter.ingest_external_hook_payload({
            **base,
            "source": "codex_hook",
            "input_messages": ["hook prompt"],
            "last_assistant_message": "hook final",
        }),
    )

    assert rollout_result.get("suppressed") == "source_claimed"
    assert notify_result.get("suppressed") == "source_claimed"
    assert hook_result == {"accepted": True, "emitted": 5}
    assert [event["method"] for event in events] == [
        "session.created",
        "message.user.submitted",
        "turn/started",
        "item/completed",
        "turn/completed",
    ]
    assert events[-2]["params"]["item"]["text"] == "hook final"
    assert [item.args for item in rollout.record_primary_event.call_args_list] == [
        ("claim-session", "claim-turn", "completed"),
        ("claim-session", "claim-turn", "started"),
    ]


@pytest.mark.asyncio
async def test_source_claim_app_server_preempts_pending_external():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)
    external = asyncio.create_task(adapter.ingest_external_hook_payload({
        "hook_event_name": "AgentTurnComplete",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "source": "codex_notify",
        "last_assistant_message": "notify final",
    }))
    await asyncio.sleep(0)

    await adapter._dispatch(json.dumps({
        "method": "turn/completed",
        "params": {
            "threadId": "claim-session",
            "turn": {"id": "claim-turn"},
        },
    }))
    result = await external
    await adapter._event_queue.join()

    assert result == {
        "accepted": True,
        "emitted": 0,
        "suppressed": "authoritative_live_source",
    }
    callback.assert_awaited_once()
    assert callback.await_args.args[1]["message"]["method"] == "turn/completed"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_source_claim_committed_external_blocks_late_app_server():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    result = await adapter.ingest_external_hook_payload({
        "hook_event_name": "AgentTurnComplete",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "source": "codex_rollout",
        "last_assistant_message": "rollout final",
    })
    calls_before = callback.await_count
    await adapter._dispatch(json.dumps({
        "method": "turn/completed",
        "params": {
            "threadId": "claim-session",
            "turn": {"id": "claim-turn"},
        },
    }))

    assert result == {"accepted": True, "emitted": 4}
    assert callback.await_count == calls_before
    assert adapter._event_queue.empty()


def test_source_claim_capacity_rejects_external_and_invalidates_evicted_token():
    adapter = CodexAdapter()
    oldest_key = ("session-0", "turn-0", "completed")
    oldest_candidate = None
    for index in range(500):
        accepted, candidate = adapter._reserve_ingress_source_claim(
            f"session-{index}", f"turn-{index}", "completed", "codex_notify",
        )
        assert accepted is True
        if index == 0:
            oldest_candidate = candidate

    accepted, candidate = adapter._reserve_ingress_source_claim(
        "overflow", "overflow", "completed", "codex_hook",
    )
    assert accepted is False
    assert candidate is None
    assert len(adapter._ingress_source_claims) == 500

    assert adapter._commit_app_server_ingress_source_claim(
        "app-session", "app-turn", "completed",
    ) is True
    assert oldest_key not in adapter._ingress_source_claims
    assert len(adapter._ingress_source_claims) == 500

    accepted, replacement = adapter._reserve_ingress_source_claim(
        "session-0", "turn-0", "completed", "codex_hook",
    )
    assert accepted is True
    assert replacement is not oldest_candidate
    assert adapter._commit_ingress_source_claim(oldest_key, oldest_candidate) is False
    assert adapter._ingress_source_claims[oldest_key] is replacement


@pytest.mark.asyncio
async def test_source_claim_callback_failure_keeps_owner_and_loser_has_no_side_effects():
    callback = AsyncMock(side_effect=RuntimeError("callback failed"))
    rollout = MagicMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)
    adapter._desktop_rollout_ingress = rollout
    base = {
        "hook_event_name": "AgentTurnComplete",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "last_assistant_message": "final",
    }

    with pytest.raises(RuntimeError, match="callback failed"):
        await adapter.ingest_external_hook_payload({**base, "source": "codex_notify"})
    recorded_before = list(rollout.record_primary_event.call_args_list)
    calls_before = callback.await_count
    loser = await adapter.ingest_external_hook_payload({**base, "source": "codex_hook"})

    assert loser.get("suppressed") == "source_claimed"
    assert callback.await_count == calls_before
    assert rollout.record_primary_event.call_args_list == recorded_before


@pytest.mark.asyncio
async def test_source_claim_spoof_does_not_change_raw_visibility_or_trust():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.configure_external_event_bridge("/tmp/onlineworker")
    adapter.on_event(callback)

    assert adapter._external_ingress_source({"source": "codex_app_server"}) == "codex_hook"
    assert adapter._external_ingress_source({"source": "unknown"}) == "codex_hook"
    assert adapter._external_ingress_source({"source": ""}) == "codex_hook"
    assert adapter._external_ingress_source({"source": "CoDeX_NoTiFy"}) == "codex_notify"

    with patch(
        "plugins.providers.builtin.codex.python.hook_bridge.mark_onlineworker_codex_hooks_verified",
    ) as mark_verified:
        await adapter.ingest_external_hook_payload({
            "hook_event_name": "SessionStart",
            "session_id": "spoof-session",
            "source": "codex_app_server",
        })
    mark_verified.assert_not_called()

    hidden = await adapter.ingest_external_hook_payload({
        "hook_event_name": "AgentTurnComplete",
        "session_id": "subagent-session",
        "turn_id": "subagent-turn",
        "source": {"subagent": {"thread_spawn": {}}},
        "last_assistant_message": "internal",
    })
    assert hidden.get("suppressed") == "non_user_visible_session"
    callback.assert_not_awaited()


def test_source_claim_app_server_category_mapping_is_exact():
    adapter = CodexAdapter()

    assert adapter._app_server_ingress_claim(
        "turn/started", {"turn": {"id": "turn-1"}},
    ) == ("turn-1", "started")
    assert adapter._app_server_ingress_claim(
        "item/agentMessage/delta", {"turnId": "turn-1"},
    ) == ("turn-1", "commentary")
    assert adapter._app_server_ingress_claim(
        "item/completed",
        {"turnId": "turn-1", "item": {"type": "agentMessage", "phase": "commentary"}},
    ) == ("turn-1", "commentary")
    assert adapter._app_server_ingress_claim(
        "item/completed",
        {"turnId": "turn-1", "item": {"type": "agentMessage", "phase": "final_answer"}},
    ) == ("turn-1", "completed")
    assert adapter._app_server_ingress_claim(
        "turn/completed", {"turn": {"id": "turn-1"}},
    ) == ("turn-1", "completed")
    assert adapter._app_server_ingress_claim(
        "item/completed", {"turnId": "turn-1", "item": {"type": "commandExecution"}},
    ) is None
    assert adapter._app_server_ingress_claim("turn/completed", {}) is None


@pytest.mark.asyncio
async def test_source_claim_session_authority_preserves_owned_category_only():
    callback = AsyncMock()
    adapter = CodexAdapter()
    adapter.on_event(callback)

    started = await adapter.ingest_external_hook_payload({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "prompt": "hello",
    })
    await adapter._dispatch(json.dumps({
        "method": "thread/name/updated",
        "params": {"threadId": "claim-session", "name": "Claim session"},
    }))
    await adapter._event_queue.join()
    completed = await adapter.ingest_external_hook_payload({
        "hook_event_name": "Stop",
        "session_id": "claim-session",
        "turn_id": "claim-turn",
        "source": "codex_notify",
        "last_assistant_message": "notify final",
    })

    assert started == {"accepted": True, "emitted": 3}
    assert adapter._ingress_source_claims[
        ("claim-session", "claim-turn", "started")
    ]["source"] == "codex_hook"
    assert completed.get("suppressed") == "authoritative_live_source"
    assert adapter._ingress_source_claims[
        ("claim-session", "claim-turn", "completed")
    ]["source"] == "codex_app_server"
    await adapter.disconnect()


@pytest.mark.asyncio
async def test_session_end_releases_desktop_rollout_watch():
    adapter = CodexAdapter()
    adapter.on_event(AsyncMock())
    rollout = MagicMock()
    adapter._desktop_rollout_ingress = rollout

    result = await adapter.ingest_external_hook_payload(
        {
            "hook_event_name": "SessionEnd",
            "session_id": "desktop-session",
        }
    )

    assert result == {"accepted": True, "emitted": 0}
    rollout.release_session.assert_called_once_with("desktop-session")


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
@pytest.mark.parametrize("version,supported", [("0.149.1", False), ("0.150.0", True), ("unknown", False)])
async def test_connect_uses_unix_socket_for_unix_endpoint(tmp_path, version, supported):
    ws = AsyncMock()
    ws.recv = AsyncMock(
        return_value=json.dumps({"id": 1, "result": {"userAgent": f"Codex/{version}", "codexHome": "/tmp", "platformFamily": "unix", "platformOs": "macos"}})
    )
    socket_path = tmp_path / "codex.sock"
    adapter = CodexAdapter()

    with patch(
        "plugins.providers.builtin.codex.python.adapter.websockets.unix_connect",
        new=AsyncMock(return_value=ws),
    ) as connect_mock, patch(
        "plugins.providers.builtin.codex.python.adapter.websockets.connect",
        new=AsyncMock(),
    ) as ws_connect_mock, patch(
        "plugins.providers.builtin.codex.python.adapter.asyncio.create_task",
        side_effect=_fake_create_task,
    ):
        await adapter.connect(f"unix://{socket_path}")

    ws_connect_mock.assert_not_awaited()
    connect_mock.assert_awaited_once_with(
        path=str(socket_path),
        uri="ws://localhost/",
        max_size=None,
        ping_interval=None,
        ping_timeout=None,
        compression=None,
    )
    assert adapter._transport == "unix"
    assert adapter._supports_idle_restart is supported


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
async def test_start_thread_uses_pending_notification_when_rpc_times_out():
    adapter = CodexAdapter()
    adapter._connected = True
    adapter.register_workspace_cwd("codex:/tmp/project", "/tmp/project")

    async def timeout_call(method, params):
        assert method == "thread/start"
        assert params["cwd"] == "/tmp/project"
        await asyncio.sleep(0)
        adapter._update_thread_workspace_map("thread/started", {"threadId": "real-thread"})
        raise TimeoutError("app-server RPC 超时：method=thread/start")

    adapter._call = timeout_call

    result = await adapter.start_thread("codex:/tmp/project")

    assert result == {"id": "real-thread"}
    assert adapter._thread_workspace_map["real-thread"] == "codex:/tmp/project"


@pytest.mark.asyncio
async def test_expired_thread_notification_after_start_timeout_is_not_mapped(monkeypatch):
    monkeypatch.setattr(
        "plugins.providers.builtin.codex.python.adapter.PENDING_THREAD_START_TTL_SECONDS",
        0.01,
    )
    adapter = CodexAdapter()
    adapter._connected = True
    adapter.register_workspace_cwd("codex:/tmp/project", "/tmp/project")

    async def timeout_call(method, params):
        assert method == "thread/start"
        assert params["cwd"] == "/tmp/project"
        raise TimeoutError("app-server RPC 超时：method=thread/start")

    adapter._call = timeout_call

    with pytest.raises(TimeoutError):
        await adapter.start_thread("codex:/tmp/project")

    await asyncio.sleep(0.02)
    adapter._update_thread_workspace_map("thread/started", {"threadId": "late-thread"})

    assert "late-thread" not in adapter._thread_workspace_map
    assert adapter._pending_thread_starts == []


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
        {
            "cwd": "/Users/example/Projects/onlineWorker",
            "approvalsReviewer": "user",
        },
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
        {
            "cwd": "/Users/example/Projects/onlineWorker",
            "approvalsReviewer": "user",
        },
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
            "approvalsReviewer": "user",
        }
        assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"
        return {"ok": True}

    adapter._call = AsyncMock(side_effect=fake_call)

    result = await adapter.send_user_message("codex:onlineWorker", "tid-live", "hello")

    assert result == {"ok": True}
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_turn_steer_targets_current_turn_with_text_and_image():
    adapter = CodexAdapter()
    adapter._call = AsyncMock(return_value={"turnId": "turn-live"})

    result = await adapter.turn_steer(
        "codex:onlineWorker",
        "tid-live",
        "turn-live",
        "继续，并调整方向",
        attachments=[{"kind": "image", "path": "/tmp/example.png"}],
    )

    adapter._call.assert_awaited_once_with(
        "turn/steer",
        {
            "threadId": "tid-live",
            "expectedTurnId": "turn-live",
            "input": [
                {"type": "text", "text": "继续，并调整方向"},
                {"type": "localImage", "path": "/tmp/example.png"},
            ],
        },
    )
    assert result == {"turnId": "turn-live"}
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_resume_thread_passes_registered_workspace_cwd():
    adapter = CodexAdapter()
    adapter._workspace_cwd_map["codex:onlineWorker"] = "/Users/example/Projects/onlineWorker"
    adapter._call = AsyncMock(return_value={"id": "tid-live"})

    result = await adapter.resume_thread("codex:onlineWorker", "tid-live")

    adapter._call.assert_awaited_once_with(
        "thread/resume",
        {
            "threadId": "tid-live",
            "cwd": "/Users/example/Projects/onlineWorker",
            "approvalsReviewer": "user",
        },
    )
    assert result == {"id": "tid-live"}
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_temporary_workspace_uses_native_session_cwd_but_starts_new_tasks_in_group_root(monkeypatch):
    from plugins.providers.builtin.codex.python import storage_runtime

    root = "/Users/example/Documents/Codex"
    adapter = CodexAdapter()
    adapter.register_workspace_cwd("temporary", root)
    adapter._call = AsyncMock(return_value={"id": "new-task"})
    adapter._load_thread_runtime_policy = lambda _tid: (None, None)
    monkeypatch.setattr(storage_runtime, "list_codex_threads_by_cwd", lambda cwd, limit=20: [
        {"id": "old-task", "source": "vscode", "title": "Existing task"},
        {"id": "new-task", "source": "vscode", "title": "New task"},
    ])

    assert {row["id"] for row in await adapter.list_threads("temporary")} == {"old-task", "new-task"}
    adapter._call.assert_not_awaited()
    await adapter.start_thread("temporary")
    assert adapter._call.await_args.args[1]["cwd"] == root
    await adapter.resume_thread("temporary", "old-task")
    assert "cwd" not in adapter._call.await_args.args[1]
    await adapter.send_user_message("temporary", "old-task", "continue")
    assert "cwd" not in adapter._call.await_args.args[1]


@pytest.mark.asyncio
async def test_send_user_message_passes_registered_workspace_cwd():
    adapter = CodexAdapter()
    adapter._workspace_cwd_map["codex:onlineWorker"] = "/Users/example/Projects/onlineWorker"
    adapter._call = AsyncMock(return_value={"ok": True})

    result = await adapter.send_user_message("codex:onlineWorker", "tid-live", "hello")

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "cwd": "/Users/example/Projects/onlineWorker",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "user",
        },
    )
    assert result == {"ok": True}
    assert adapter._thread_workspace_map["tid-live"] == "codex:onlineWorker"


@pytest.mark.asyncio
async def test_send_user_message_loads_thread_policy_when_enabled(monkeypatch, tmp_path):
    db_path = tmp_path / "state_5.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, approval_mode TEXT, sandbox_policy TEXT)"
        )
        conn.execute(
            "INSERT INTO threads (id, approval_mode, sandbox_policy) VALUES (?, ?, ?)",
            (
                "tid-live",
                "on-request",
                json.dumps(
                    {
                        "type": "workspace-write",
                        "network_access": False,
                        "exclude_tmpdir_env_var": False,
                        "exclude_slash_tmp": False,
                    }
                ),
            ),
        )
    monkeypatch.setenv("ONLINEWORKER_CODEX_STATE_DB", str(db_path))

    adapter = CodexAdapter()
    adapter.enable_thread_policy_lookup(True)
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message("codex:onlineWorker", "tid-live", "hello")

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "user",
            "approvalPolicy": "on-request",
            "sandboxPolicy": {
                "type": "workspaceWrite",
                "networkAccess": False,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            },
        },
    )


@pytest.mark.asyncio
async def test_send_user_message_maps_managed_thread_policy_when_enabled(monkeypatch, tmp_path):
    db_path = tmp_path / "state_5.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, approval_mode TEXT, sandbox_policy TEXT)"
        )
        conn.execute(
            "INSERT INTO threads (id, approval_mode, sandbox_policy) VALUES (?, ?, ?)",
            (
                "tid-live",
                "on-request",
                json.dumps(
                    {
                        "type": "managed",
                        "file_system": {
                            "entries": [
                                {"access": "read", "special": ":root"},
                                {"access": "write", "path": "/Users/example/Projects/onlineWorker"},
                            ]
                        },
                        "network": "enabled",
                    }
                ),
            ),
        )
    monkeypatch.setenv("ONLINEWORKER_CODEX_STATE_DB", str(db_path))

    adapter = CodexAdapter()
    adapter.enable_thread_policy_lookup(True)
    adapter._call = AsyncMock(return_value={"ok": True})

    await adapter.send_user_message("codex:onlineWorker", "tid-live", "hello")

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "user",
            "approvalPolicy": "on-request",
            "sandboxPolicy": {
                "type": "workspaceWrite",
                "networkAccess": True,
            },
        },
    )


def test_normalize_sandbox_policy_for_app_server():
    assert CodexAdapter._normalize_sandbox_policy_for_app_server(
        {
            "type": "workspace-write",
            "network_access": False,
            "exclude_tmpdir_env_var": False,
            "exclude_slash_tmp": False,
        }
    ) == {
        "type": "workspaceWrite",
        "networkAccess": False,
        "excludeTmpdirEnvVar": False,
        "excludeSlashTmp": False,
    }
    assert CodexAdapter._normalize_sandbox_policy_for_app_server(
        {
            "type": "managed",
            "file_system": {
                "entries": [
                    {"access": "read", "special": ":root"},
                    {"access": "write", "path": "/Users/example/Projects/onlineWorker"},
                ]
            },
            "network": "enabled",
        }
    ) == {
        "type": "workspaceWrite",
        "networkAccess": True,
    }
    assert CodexAdapter._normalize_sandbox_policy_for_app_server(
        {
            "type": "managed",
            "file_system": {"entries": [{"access": "read", "special": ":root"}]},
            "network": "restricted",
        }
    ) == {
        "type": "readOnly",
        "networkAccess": False,
    }
    assert CodexAdapter._normalize_sandbox_policy_for_app_server("managed") is None
    assert CodexAdapter._normalize_sandbox_policy_for_app_server({"type": "managed-but-unknown"}) is None


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
            "approvalsReviewer": "user",
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
        sandbox_policy={
            "type": "workspace-write",
            "network_access": False,
            "exclude_tmpdir_env_var": False,
            "exclude_slash_tmp": False,
        },
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "user",
            "sandboxPolicy": {
                "type": "workspaceWrite",
                "networkAccess": False,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            },
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
        approvals_reviewer="auto_review",
    )

    adapter._call.assert_awaited_once_with(
        "turn/start",
        {
            "threadId": "tid-live",
            "input": [{"type": "text", "text": "hello"}],
            "approvalsReviewer": "auto_review",
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
    assert adapter._thread_workspace_map["tid-archived"] == "codex:onlineWorker"


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
