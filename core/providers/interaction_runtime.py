from __future__ import annotations


def question_is_pending(state, provider_id, session_id, question_id):
    activity = state.message_bus.session_activity(provider_id, session_id) or {}
    return bool(question_id) and (
        activity.get("status") == "needs_attention"
        and activity.get("attentionKind") == "question"
        and activity.get("requestId") == question_id
        and not activity.get("mirroredOnly")
    )


def discard_question(state, pending_question):
    key = (pending_question.tool_name, pending_question.session_id, pending_question.question_id)
    pending_question.awaiting_text = False
    for message_id, question in list(state.pending_questions.items()):
        if (question.tool_name, question.session_id, question.question_id) == key:
            question.awaiting_text = False
            state.pending_questions.pop(message_id, None)
    group = state.pending_question_groups.get(key[2])
    if group and group.session_id == key[1]:
        state.pending_question_groups.pop(key[2], None)


def require_pending_question(state, pending_question):
    key = (pending_question.tool_name, pending_question.session_id, pending_question.question_id)
    if not question_is_pending(state, *key):
        discard_question(state, pending_question)
        raise LookupError("问题已回答或已失效，请查看当前 Session 状态。")
    return key


async def submit_question_reply(state, adapter, reply_question, pending_question, answers, *, source="telegram"):
    from core.messages.publishing import publish_question_answered

    key = require_pending_question(state, pending_question)
    if key in state.question_replies_in_flight:
        raise RuntimeError("问题正在提交，请勿重复回答。")
    state.question_replies_in_flight.add(key)
    try:
        await reply_question(adapter, pending_question, answers)
        publish_question_answered(state, pending_question, answers, source=source)
        discard_question(state, pending_question)
    except LookupError:
        discard_question(state, pending_question)
        raise
    finally:
        state.question_replies_in_flight.discard(key)


async def reply_question_via_adapter(adapter, pending_question, answers: list[list[str]]) -> None:
    await adapter.reply_question(pending_question.question_id, answers)
