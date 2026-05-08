from core.providers.session_events import normalize_session_event


def test_normalize_assistant_delta_event():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "tid-123",
                    "delta": "hello",
                },
            },
        },
    )

    assert event is not None
    assert event.provider == "codex"
    assert event.workspace_id == "codex:onlineWorker"
    assert event.thread_id == "tid-123"
    assert event.kind == "assistant_delta"
    assert event.semantic_kind == "assistant_progress"
    assert event.payload["delta"] == "hello"


def test_normalize_assistant_completed_event():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "item/completed",
                "params": {
                    "threadId": "ses-123",
                    "item": {
                        "type": "agentMessage",
                        "threadId": "ses-123",
                        "phase": "final_answer",
                        "text": "done",
                    },
                },
            },
        },
    )

    assert event is not None
    assert event.provider == "customprovider"
    assert event.kind == "assistant_completed"
    assert event.semantic_kind == ""
    assert event.thread_id == "ses-123"
    assert event.payload["text"] == "done"
    assert event.payload["phase"] == "final_answer"


def test_normalize_turn_completed_aborted_to_turn_aborted():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "turn/completed",
                "params": {
                    "threadId": "tid-123",
                    "turn": {
                        "id": "turn-1",
                        "status": "aborted",
                        "reason": "interrupted",
                    },
                },
            },
        },
    )

    assert event is not None
    assert event.kind == "turn_aborted"
    assert event.semantic_kind == "turn_aborted"
    assert event.turn_id == "turn-1"
    assert event.payload["reason"] == "interrupted"


def test_non_app_server_event_is_ignored():
    assert normalize_session_event("unrelated-event", {"foo": "bar"}) is None


def test_normalize_approval_requested_event():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "codex:onlineWorker",
            "message": {
                "method": "item/commandExecution/requestApproval",
                "id": "req-001",
                "params": {
                    "threadId": "tid-123",
                    "command": "mkdir /tmp/demo",
                    "reason": "need write permission",
                },
            },
        },
    )

    assert event is not None
    assert event.kind == "approval_requested"
    assert event.semantic_kind == "approval_requested"
    assert event.thread_id == "tid-123"
    assert event.payload["request_id"] == "req-001"
    assert event.payload["command"] == "mkdir /tmp/demo"


def test_normalize_question_requested_event():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "question/asked",
                "params": {
                    "threadId": "ses-123",
                    "questionId": "que-001",
                    "header": "Model",
                    "question": "Choose a model",
                    "options": [{"label": "opus", "description": "quality"}],
                },
            },
        },
    )

    assert event is not None
    assert event.kind == "question_requested"
    assert event.provider == "customprovider"
    assert event.thread_id == "ses-123"
    assert event.payload["questionId"] == "que-001"
    assert event.payload["header"] == "Model"


def test_normalize_session_created_event():
    event = normalize_session_event(
        "app-server-event",
        {
            "workspace_id": "customprovider:onlineWorker",
            "message": {
                "method": "session.created",
                "params": {
                    "threadId": "ses-123",
                    "title": "Phase 17",
                },
            },
        },
    )

    assert event is not None
    assert event.kind == "session_created"
    assert event.thread_id == "ses-123"
    assert event.payload["title"] == "Phase 17"
