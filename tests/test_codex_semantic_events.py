from plugins.providers.builtin.codex.python.semantic_events import (
    parse_codex_app_server_semantic_event,
)


def test_codex_commentary_semantics_from_app_server():
    event = parse_codex_app_server_semantic_event(
        "item/agentMessage/delta",
        {
            "threadId": "tid-123",
            "turnId": "turn-1",
            "delta": "我先看一下当前链路。",
        },
    )

    assert event is not None
    assert event.kind == "assistant_progress"


def test_codex_final_answer_semantics_from_app_server():
    event = parse_codex_app_server_semantic_event(
        "item/completed",
        {
            "threadId": "tid-123",
            "turnId": "turn-1",
            "item": {
                "type": "agentMessage",
                "phase": "final_answer",
                "text": "修复已完成。",
            },
        },
    )

    assert event is not None
    assert event.kind == "turn_completed"
    assert event.text == "修复已完成。"


def test_codex_tool_semantics_from_app_server():
    started = parse_codex_app_server_semantic_event(
        "item/started",
        {
            "threadId": "tid-123",
            "turnId": "turn-1",
            "item": {
                "type": "shellCommand",
                "command": "rg --files",
            },
        },
    )
    completed = parse_codex_app_server_semantic_event(
        "item/completed",
        {
            "threadId": "tid-123",
            "turnId": "turn-1",
            "item": {
                "type": "shellCommand",
                "command": "rg --files",
            },
        },
    )

    assert started is not None
    assert completed is not None
    assert started.kind == "tool_started"
    assert completed.kind == "tool_completed"


def test_codex_abort_semantics_from_app_server():
    event = parse_codex_app_server_semantic_event(
        "turn/completed",
        {
            "threadId": "tid-123",
            "turn": {
                "id": "turn-1",
                "status": "aborted",
                "reason": "interrupted",
            },
        },
    )

    assert event is not None
    assert event.kind == "turn_aborted"
    assert event.reason == "interrupted"


def test_codex_capacity_error_turn_completed_is_treated_as_turn_aborted():
    event = parse_codex_app_server_semantic_event(
        "turn/completed",
        {
            "threadId": "tid-123",
            "turn": {
                "id": "turn-1",
                "status": "aborted",
                "reason": "Selected model is at capacity. Please try a different model.",
            },
        },
    )

    assert event is not None
    assert event.kind == "turn_aborted"
    assert event.reason == "Selected model is at capacity. Please try a different model."
