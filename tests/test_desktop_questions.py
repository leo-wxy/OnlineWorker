import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.messages.events import create_message_event
from core.messages.session_bridge import message_event_from_session_event
from core.provider_owner_bridge import ProviderOwnerBridge
from core.providers.interaction_runtime import reply_question_via_adapter, submit_question_reply
from core.providers.session_events import SessionEvent
from core.state import AppState, PendingQuestion, PendingQuestionGroup


def request_question(state, index=0, total=1, *, question_id="sample-question", mirrored=False):
    event = message_event_from_session_event(SessionEvent(
        provider="claude", workspace_id="claude:/tmp/sample-workspace", thread_id="sample-session",
        turn_id="sample-turn", kind="question_requested", raw_method="question/asked",
        payload={"questionId": question_id, "header": "Language", "question": "Choose a language",
                 "options": [{"label": "Python", "description": "Scripts"}, {"label": "Rust"}],
                 "multiple": index == 1, "custom": index == 1, "subIndex": index, "subTotal": total,
                 "_mirroredOnly": mirrored},
    ))
    state.message_bus.publish(event)


def setup_question(monkeypatch, tmp_path):
    state = AppState()
    adapter = SimpleNamespace(connected=True, reply_question=AsyncMock())
    state.set_adapter("claude", adapter)
    monkeypatch.setattr("core.provider_owner_bridge.get_provider", lambda *_: SimpleNamespace(
        interactions=SimpleNamespace(reply_question=reply_question_via_adapter)))
    return state, adapter, ProviderOwnerBridge(state, data_dir=str(tmp_path))


def reply_request(answers=None, **overrides):
    return {"provider_id": "claude", "session_id": "sample-session", "question_id": "sample-question",
            "answers": answers if answers is not None else [["Python"]], **overrides}


@pytest.mark.asyncio
async def test_desktop_submits_group_without_telegram_and_bus_clears_attention(monkeypatch, tmp_path):
    state, adapter, bridge = setup_question(monkeypatch, tmp_path)
    request_question(state, 1, 2)
    request_question(state, 0, 2)
    activity = state.message_bus.session_activity("claude", "sample-session")
    assert [question["subIndex"] for question in activity["questions"]] == [0, 1]
    assert activity["questions"][0]["options"][0]["description"] == "Scripts"
    state.message_bus.publish(create_message_event("item.completed", provider_id="claude",
                             session_id="sample-session", turn_id="sample-turn"))
    assert state.message_bus.session_activity("claude", "sample-session")["status"] == "needs_attention"
    assert await bridge._handle_reply_question(reply_request([["Python"], ["Rust", "Custom"]])) == {"ok": True}
    adapter.reply_question.assert_awaited_once_with("sample-question", [["Python"], ["Rust", "Custom"]])
    activity = state.message_bus.session_activity("claude", "sample-session")
    assert activity["status"] == "running"
    assert activity["questions"] == []
    assert state.message_bus.recent_events()[-1]["source"] == "desktop_app"
    assert not (await bridge._handle_reply_question(reply_request()))["ok"]
    assert adapter.reply_question.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["empty", "invalid_option", "multiple", "incomplete", "wrong_session", "mirrored"])
async def test_desktop_rejects_invalid_or_uncontrolled_question(monkeypatch, tmp_path, case):
    state, adapter, bridge = setup_question(monkeypatch, tmp_path)
    request_question(state, total=2 if case == "incomplete" else 1, mirrored=case == "mirrored")
    answers = {"empty": [[]], "invalid_option": [["Other"]], "multiple": [["Python", "Rust"]]}.get(case)
    request = reply_request(answers)
    if case == "wrong_session":
        request["session_id"] = "other-session"
    assert not (await bridge._handle_reply_question(request))["ok"]
    adapter.reply_question.assert_not_awaited()


@pytest.mark.asyncio
async def test_reply_failure_keeps_question_and_allows_retry(monkeypatch, tmp_path):
    state, adapter, bridge = setup_question(monkeypatch, tmp_path)
    request_question(state)
    pending = PendingQuestion("sample-question", "sample-session", "claude:/tmp/sample-workspace",
                              "Language", "Choose", [], tool_name="claude")
    state.pending_questions[123] = pending
    adapter.reply_question.side_effect = RuntimeError("provider unavailable")
    assert not (await bridge._handle_reply_question(reply_request()))["ok"]
    assert state.pending_questions[123] is pending
    assert state.message_bus.session_activity("claude", "sample-session")["questions"]
    assert not state.question_replies_in_flight
    adapter.reply_question.side_effect = None
    assert (await bridge._handle_reply_question(reply_request()))["ok"]
    assert not state.pending_questions


@pytest.mark.asyncio
async def test_desktop_and_telegram_cannot_reply_to_same_question_twice(monkeypatch, tmp_path):
    state, adapter, bridge = setup_question(monkeypatch, tmp_path)
    request_question(state)
    entered, release = asyncio.Event(), asyncio.Event()
    async def delayed_reply(*_):
        entered.set()
        await release.wait()
    adapter.reply_question.side_effect = delayed_reply
    first = asyncio.create_task(bridge._handle_reply_question(reply_request()))
    await entered.wait()
    pending = SimpleNamespace(tool_name="claude", session_id="sample-session", question_id="sample-question")
    try:
        with pytest.raises(RuntimeError, match="正在提交"):
            await submit_question_reply(state, adapter, reply_question_via_adapter, pending, [["Rust"]])
    finally:
        release.set()
    assert (await first)["ok"]
    adapter.reply_question.assert_awaited_once()


def test_old_question_answer_cannot_clear_new_question():
    state = AppState()
    request_question(state)
    request_question(state, question_id="new-question")
    state.message_bus.publish(create_message_event("question.answered", provider_id="claude",
                             session_id="sample-session", payload={"questionId": "sample-question"}))
    activity = state.message_bus.session_activity("claude", "sample-session")
    assert activity["requestId"] == "new-question"
    assert activity["status"] == "needs_attention"


@pytest.mark.asyncio
@pytest.mark.parametrize("grouped", [False, True])
async def test_telegram_callback_failure_keeps_pending_and_buttons_for_retry(monkeypatch, tmp_path, grouped):
    from bot.handlers.message import make_callback_handler

    state, adapter, _ = setup_question(monkeypatch, tmp_path)
    request_question(state, 0, 2 if grouped else 1)
    if grouped:
        request_question(state, 1, 2)
    group = PendingQuestionGroup("sample-question", "sample-session", "claude:/tmp/sample-workspace", 2,
                                 answers={1: ["Rust"]}) if grouped else None
    pending = PendingQuestion("sample-question", "sample-session", "claude:/tmp/sample-workspace",
                              "Language", "Choose", [{"label": "Python"}], tool_name="claude", group=group)
    state.pending_questions[123] = pending
    if group:
        state.pending_question_groups[group.question_id] = group
    adapter.reply_question.side_effect = RuntimeError("provider unavailable")
    query = MagicMock(data=f"q_ans:123:{int(time.time())}:0")
    query.answer, query.edit_message_text = AsyncMock(), AsyncMock()
    handler = make_callback_handler(state, 1234567890)
    await handler(SimpleNamespace(callback_query=query), MagicMock())
    assert state.pending_questions[123] is pending
    query.edit_message_text.assert_not_awaited()
    if group:
        assert state.pending_question_groups[group.question_id] is group
    adapter.reply_question.side_effect = None
    await handler(SimpleNamespace(callback_query=query), MagicMock())
    assert not state.pending_questions
    assert not state.pending_question_groups
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_telegram_question_delivery_skips_unbound_and_already_answered_requests(monkeypatch):
    from bot.events import send_question_to_telegram
    from core.providers.interactions import create_provider_question_request

    state, bot = AppState(), MagicMock()
    request_question(state)
    info = create_provider_question_request(question_id="sample-question", thread_id="sample-session",
                                           question="Choose", tool_type="claude")
    send = AsyncMock(return_value=SimpleNamespace(message_id=123))
    monkeypatch.setattr("bot.events._send_to_group", send)
    bot.edit_message_text, bot.edit_message_reply_markup = AsyncMock(), AsyncMock()
    await send_question_to_telegram(state, bot, 1234567890, None, "claude:/tmp/sample-workspace", info)
    send.assert_not_awaited()
    async def answered_during_send(*args, **kwargs):
        state.message_bus.publish(create_message_event("question.answered", provider_id="claude",
                                 session_id="sample-session", payload={"questionId": "sample-question"}))
        return SimpleNamespace(message_id=123)
    send.side_effect = answered_during_send
    await send_question_to_telegram(state, bot, 1234567890, 123, "claude:/tmp/sample-workspace", info)
    assert not state.pending_questions
    bot.edit_message_reply_markup.assert_not_awaited()
    await send_question_to_telegram(state, bot, 1234567890, 123, "claude:/tmp/sample-workspace", info)
    assert send.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["session.hidden", "session.archived", "turn.failed"])
async def test_invalidated_question_clears_pending_without_provider_reply(kind):
    state = AppState()
    request_question(state)
    pending = PendingQuestion("sample-question", "sample-session", "sample-workspace", "", "Choose", [],
                              tool_name="claude", awaiting_text=True)
    state.pending_questions[123] = pending
    state.message_bus.publish(create_message_event(kind, provider_id="claude", session_id="sample-session"))
    reply = AsyncMock()
    with pytest.raises(LookupError, match="已失效"):
        await submit_question_reply(state, object(), reply, pending, [["Python"]])
    reply.assert_not_awaited()
    assert not state.pending_questions
    assert not pending.awaiting_text


@pytest.mark.asyncio
async def test_ended_question_does_not_keep_intercepting_normal_messages(monkeypatch):
    from bot.handlers.message import make_message_handler

    state = AppState()
    monkeypatch.setattr(state, "is_global_topic", lambda _: False)
    monkeypatch.setattr(state, "find_workspace_by_topic_id", lambda _: None)
    monkeypatch.setattr(state, "find_thread_by_topic_id", lambda _: (SimpleNamespace(), SimpleNamespace()))
    pending = PendingQuestion("sample-question", "sample-session", "sample-workspace", "", "Choose", [],
                              tool_name="claude", awaiting_text=True, topic_id=123)
    state.pending_questions[42] = pending
    state.message_bus.publish(create_message_event("turn.failed", provider_id="claude", session_id="sample-session"))
    send, dispatch = AsyncMock(), AsyncMock()
    monkeypatch.setattr("bot.handlers.message._send_to_group", send)
    monkeypatch.setattr("bot.handlers.message._download_message_attachments", AsyncMock(return_value=[]))
    monkeypatch.setattr("bot.handlers.message._dispatch_thread_message", dispatch)
    update = SimpleNamespace(effective_user=None, effective_message=SimpleNamespace(
        text="sample normal task", photo=[], document=None, caption=None, message_thread_id=123))
    context = SimpleNamespace(bot=SimpleNamespace())
    handler = make_message_handler(state, 1234567890)
    await handler(update, context)
    assert not pending.awaiting_text and not state.pending_questions
    dispatch.assert_not_awaited()
    assert "本条消息未发送" in send.await_args.args[2]
    await handler(update, context)
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("done", [False, True])
async def test_claude_missing_or_finished_question_is_not_retryable(done):
    from plugins.providers.builtin.claude.python.adapter import ClaudeAdapter

    adapter = ClaudeAdapter.__new__(ClaudeAdapter)
    future = asyncio.get_running_loop().create_future()
    future.set_result({})
    adapter._pending_hook_questions = {"sample-question": {"future": future}} if done else {}
    with pytest.raises(LookupError):
        await adapter.reply_question("sample-question", [["Python"]])
