from __future__ import annotations


async def reply_question_via_adapter(adapter, pending_question, answers: list[list[str]]) -> None:
    await adapter.reply_question(pending_question.question_id, answers)
