from plugins.providers.builtin.codex.python.semantic_events import (
    parse_codex_app_server_semantic_event,
    parse_codex_rollout_semantic_event,
)


def test_codex_commentary_semantics_align_between_app_server_and_rollout():
    app_event = parse_codex_app_server_semantic_event(
        "item/agentMessage/delta",
        {
            "threadId": "tid-123",
            "turnId": "turn-1",
            "delta": "我先看一下当前链路。",
        },
    )
    rollout_event = parse_codex_rollout_semantic_event(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "commentary",
                "content": [{"type": "output_text", "text": "我先看一下当前链路。"}],
            },
        }
    )

    assert app_event is not None
    assert rollout_event is not None
    assert app_event.kind == "assistant_progress"
    assert rollout_event.kind == "assistant_progress"


def test_codex_final_answer_semantics_align_between_app_server_and_rollout():
    app_event = parse_codex_app_server_semantic_event(
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
    rollout_event = parse_codex_rollout_semantic_event(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "phase": "final_answer",
                "content": [{"type": "output_text", "text": "修复已完成。"}],
            },
        }
    )

    assert app_event is not None
    assert rollout_event is not None
    assert app_event.kind == "turn_completed"
    assert rollout_event.kind == "turn_completed"
    assert app_event.text == "修复已完成。"
    assert rollout_event.text == "修复已完成。"


def test_codex_tool_semantics_align_between_app_server_and_rollout():
    app_started = parse_codex_app_server_semantic_event(
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
    app_completed = parse_codex_app_server_semantic_event(
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
    rollout_started = parse_codex_rollout_semantic_event(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec_command",
                "arguments": "{\"cmd\":\"rg --files\"}",
                "call_id": "call-1",
            },
        }
    )
    rollout_completed = parse_codex_rollout_semantic_event(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "file_a.py\nfile_b.py",
            },
        }
    )

    assert app_started is not None
    assert app_completed is not None
    assert rollout_started is not None
    assert rollout_completed is not None

    assert app_started.kind == "tool_started"
    assert rollout_started.kind == "tool_started"
    assert app_completed.kind == "tool_completed"
    assert rollout_completed.kind == "tool_completed"


def test_codex_abort_semantics_align_between_app_server_and_rollout():
    app_event = parse_codex_app_server_semantic_event(
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
    rollout_event = parse_codex_rollout_semantic_event(
        {
            "type": "event_msg",
            "payload": {
                "type": "turn_aborted",
                "turn_id": "turn-1",
                "reason": "interrupted",
            },
        }
    )

    assert app_event is not None
    assert rollout_event is not None
    assert app_event.kind == "turn_aborted"
    assert rollout_event.kind == "turn_aborted"
    assert app_event.reason == "interrupted"
    assert rollout_event.reason == "interrupted"
