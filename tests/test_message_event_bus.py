from types import SimpleNamespace

import pytest

from core.messages import MessageEventBus, create_message_event
from core.messages.session_bridge import message_event_from_session_event
from core.messages.publishing import (
    publish_approval_answered,
    publish_notification_activity,
    publish_question_answered,
    publish_session_archived,
    publish_user_message_accepted,
    publish_user_message_submitted,
)
from core.notifications.events import NotificationEvent
from core.providers.session_events import SessionEvent
from core.user_messages.contracts import UserMessageSendRequest


def test_message_event_bus_publishes_in_order_and_updates_projection():
    bus = MessageEventBus()
    seen = []
    bus.subscribe(lambda event: seen.append(event.kind))

    bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            source="telegram",
            payload={"text": "implement feature"},
            dedupe_key="user:thread-a:1",
            created_at=10,
        )
    )
    bus.publish(
        create_message_event(
            "message.assistant.final",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            workspace_path="/tmp/project",
            session_id="thread-a",
            turn_id="turn-a",
            source="provider_event",
            payload={"text": "done"},
            dedupe_key="assistant:thread-a:turn-a",
            created_at=20,
        )
    )

    assert seen == ["message.user.accepted", "message.assistant.final"]
    activity = bus.session_activity("codex", "thread-a")
    assert activity["providerId"] == "codex"
    assert activity["workspacePath"] == "/tmp/project"
    assert activity["status"] == "completed"
    assert activity["lastUserMessage"] == "implement feature"
    assert activity["lastFinalMessage"] == "done"
    assert activity["lastEventKind"] == "message.assistant.final"


def test_completed_projection_ignores_late_user_accepted_status_regression():
    bus = MessageEventBus()
    session_id = "thread-a"

    bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id=session_id,
            source="app",
            payload={"text": "write a file and reply OK"},
            created_at=10,
        )
    )
    bus.publish(
        create_message_event(
            "message.assistant.final",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id=session_id,
            turn_id="turn-a",
            source="provider_event",
            payload={"text": "OK"},
            created_at=20,
        )
    )
    bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            workspace_path="/tmp/project",
            session_id=session_id,
            source="late_sync",
            payload={"text": "write a file and reply OK"},
            created_at=30,
        )
    )

    activity = bus.session_activity("claude", session_id)
    assert activity["status"] == "completed"
    assert activity["lastUserMessage"] == "write a file and reply OK"
    assert activity["lastFinalMessage"] == "OK"
    assert activity["lastEventKind"] == "message.user.accepted"


def test_message_event_bus_dedupes_by_key_before_projection_update():
    bus = MessageEventBus()
    first = create_message_event(
        "message.user.accepted",
        provider_id="codex",
        session_id="thread-a",
        payload={"text": "first"},
        dedupe_key="same",
        created_at=10,
    )
    duplicate = create_message_event(
        "message.user.accepted",
        provider_id="codex",
        session_id="thread-a",
        payload={"text": "second"},
        dedupe_key="same",
        created_at=20,
    )

    assert bus.publish(first) is True
    assert bus.publish(duplicate) is False

    activity = bus.session_activity("codex", "thread-a")
    assert activity["lastUserMessage"] == "first"
    assert activity["updatedAt"] == 10
    assert len(bus.recent_events()) == 1


def test_message_user_submitted_records_input_without_marking_running():
    bus = MessageEventBus()

    bus.publish(
        create_message_event(
            "message.user.submitted",
            provider_id="codex",
            session_id="thread-a",
            payload={"text": "please run tests"},
            created_at=10,
        )
    )

    activity = bus.session_activity("codex", "thread-a")
    assert activity["lastUserMessage"] == "please run tests"
    assert activity["status"] == "idle"
    assert activity["lastEventKind"] == "message.user.submitted"


def test_projection_replaces_session_id_title_placeholder_with_user_message():
    bus = MessageEventBus()

    bus.publish(
        create_message_event(
            "turn.started",
            provider_id="codex",
            session_id="019e92cb-9559-7eb0-be3e-ab23f37f7b27",
            created_at=10,
        )
    )
    bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="codex",
            session_id="019e92cb-9559-7eb0-be3e-ab23f37f7b27",
            payload={"text": "修复 TaskBoard 卡片标题"},
            created_at=20,
        )
    )

    activity = bus.session_activity("codex", "019e92cb-9559-7eb0-be3e-ab23f37f7b27")
    assert activity["title"] == "修复 TaskBoard 卡片标题"
    assert activity["lastUserMessage"] == "修复 TaskBoard 卡片标题"


def test_projection_keeps_assistant_delta_out_of_title():
    bus = MessageEventBus()
    session_id = "019e92cb-9559-7eb0-be3e-ab23f37f7b27"

    bus.publish(
        create_message_event(
            "message.assistant.delta",
            provider_id="codex",
            session_id=session_id,
            payload={"delta": "正在检查事件总线活动流"},
            created_at=10,
        )
    )

    activity = bus.session_activity("codex", session_id)
    assert activity["title"] == ""
    assert activity["lastAssistantMessage"] == "正在检查事件总线活动流"


def test_message_event_bus_isolates_subscriber_failures():
    bus = MessageEventBus()
    seen = []

    def failing(_event):
        raise RuntimeError("subscriber failed")

    bus.subscribe(failing)
    bus.subscribe(lambda event: seen.append(event.kind))

    assert bus.publish(create_message_event("turn.started", provider_id="codex", session_id="thread-a")) is True
    assert seen == ["turn.started"]


def test_message_event_payload_redacts_sensitive_fields():
    event = create_message_event(
        "message.user.accepted",
        provider_id="claude",
        session_id="session-a",
        payload={
            "text": "hello",
            "api_key": "secret",
            "nested": {"authorization": "Bearer secret"},
        },
    )

    assert event.payload["text"] == "hello"
    assert event.payload["api_key"] == "[redacted]"
    assert event.payload["nested"]["authorization"] == "[redacted]"


def test_user_message_publish_helpers_emit_submitted_then_accepted():
    state = SimpleNamespace(message_bus=MessageEventBus())
    request = UserMessageSendRequest(
        source="telegram",
        provider_id="codex",
        workspace_id="codex:/tmp/project",
        thread_id="thread-a",
        text="run tests",
        attachments=[{"kind": "image", "path": "/tmp/secret.png", "name": "screenshot.png"}],
        metadata={"telegram_message_id": 321},
    )

    assert publish_user_message_submitted(
        state,
        request,
        text="run tests",
        workspace_path="/tmp/project",
        event_id="tg:321",
    ) is True
    assert publish_user_message_accepted(
        state,
        request,
        text="run tests",
        workspace_path="/tmp/project",
        event_id="tg:321",
    ) is True

    events = state.message_bus.recent_events()
    assert [event["kind"] for event in events] == [
        "message.user.submitted",
        "message.user.accepted",
    ]
    assert events[0]["source"] == "telegram"
    assert events[1]["payload"]["attachments"] == [
        {
            "kind": "image",
            "name": "screenshot.png",
            "mimeType": "",
            "sizeBytes": 0,
        }
    ]
    activity = state.message_bus.session_activity("codex", "thread-a")
    assert activity["status"] == "running"
    assert activity["lastUserMessage"] == "run tests"


def test_approval_and_question_answers_clear_attention_projection():
    state = SimpleNamespace(
        message_bus=MessageEventBus(),
        get_tool_for_workspace=lambda workspace_id: "codex" if workspace_id else "",
    )
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-a",
            payload={"message": "需要处理授权请求"},
            created_at=10,
        )
    )

    approval = SimpleNamespace(
        tool_type="codex",
        workspace_id="codex:/tmp/project",
        thread_id="thread-a",
        request_id="req-1",
    )
    assert publish_approval_answered(state, approval, action="exec_allow", message_id=123) is True

    question = SimpleNamespace(
        tool_name="codex",
        workspace_id="codex:/tmp/project",
        session_id="thread-a",
        question_id="que-1",
        header="Model",
    )
    state.message_bus.publish(
        create_message_event(
            "question.requested",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-a",
            payload={"message": "Choose a model"},
            created_at=20,
        )
    )
    assert publish_question_answered(state, question, [["opus"]], message_id=456) is True

    events = state.message_bus.recent_events()
    assert [event["kind"] for event in events] == [
        "approval.requested",
        "approval.answered",
        "question.requested",
        "question.answered",
    ]
    assert events[1]["payload"]["decision"] == "exec_allow"
    assert events[3]["payload"]["answers"] == [["opus"]]
    activity = state.message_bus.session_activity("codex", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionReason"] == ""
    assert activity["attentionKind"] == ""
    assert activity["requestId"] == ""
    assert activity["approvalSource"] == ""


def test_approval_answer_keeps_attention_summary_until_new_progress_arrives():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：Check if ncmusbaudio is built in top-level CMakeLists",
                "requestId": "req-1",
            },
            created_at=10,
        )
    )

    approval = SimpleNamespace(
        tool_type="claude",
        workspace_id="claude:/tmp/project",
        thread_id="thread-a",
        request_id="req-1",
    )
    assert publish_approval_answered(state, approval, action="exec_allow", message_id=123) is True

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionReason"] == ""
    assert activity["lastAssistantMessage"] == (
        "需要处理授权请求：Check if ncmusbaudio is built in top-level CMakeLists"
    )


def test_approval_roundtrip_preserves_prompt_context_when_hook_supplies_it():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：pwd",
                "prompt": "engine实现情况如何？",
                "requestId": "req-1",
            },
            created_at=10,
        )
    )

    approval = SimpleNamespace(
        tool_type="claude",
        workspace_id="claude:/tmp/project",
        thread_id="thread-a",
        request_id="req-1",
    )
    assert publish_approval_answered(state, approval, action="exec_allow", message_id=123) is True

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["lastUserMessage"] == "engine实现情况如何？"
    assert activity["lastAssistantMessage"] == ""
    assert activity["title"] == "engine实现情况如何？"


def test_tool_item_projection_refreshes_running_activity_and_clears_attention():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：echo ok",
                "requestId": "req-42",
                "mirroredOnly": True,
            },
            created_at=10,
        )
    )
    state.message_bus.publish(
        create_message_event(
            "shell.command.completed",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "text": "$ echo ok",
                "mirroredOnly": True,
            },
            created_at=20,
        )
    )

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["attentionKind"] == ""
    assert activity["requestId"] == ""
    assert activity["mirroredOnly"] is False
    assert activity["lastAssistantMessage"] == "$ echo ok"


def test_new_user_input_clears_previous_live_summary_until_new_progress_arrives():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={"text": "第一轮问题"},
            created_at=10,
        )
    )
    state.message_bus.publish(
        create_message_event(
            "message.assistant.delta",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={"delta": "第一轮回答"},
            created_at=20,
        )
    )
    state.message_bus.publish(
        create_message_event(
            "message.user.accepted",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={"text": "第二轮问题"},
            created_at=30,
        )
    )

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "running"
    assert activity["lastUserMessage"] == "第二轮问题"
    assert activity["lastAssistantMessage"] == ""
    assert activity["lastFinalMessage"] == ""

    state.message_bus.publish(
        create_message_event(
            "item.started",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={"text": "$ rg module_source"},
            created_at=40,
        )
    )

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["lastUserMessage"] == "第二轮问题"
    assert activity["lastAssistantMessage"] == "$ rg module_source"


def test_session_event_bridge_maps_final_reply_and_attention_requests():
    final_event = message_event_from_session_event(
        SessionEvent(
            provider="codex",
            workspace_id="codex:/tmp/project",
            thread_id="thread-a",
            turn_id="turn-a",
            kind="assistant_completed",
            payload={
                "request_id": "evt-final",
                "item": {"type": "agentMessage"},
            },
            raw_method="item/completed",
            semantic_kind="turn_completed",
            semantic_payload={
                "text": "final answer",
                "phase": "final_answer",
            },
        )
    )
    approval_event = message_event_from_session_event(
        SessionEvent(
            provider="codex",
            workspace_id="codex:/tmp/project",
            thread_id="thread-a",
            turn_id="turn-a",
            kind="approval_requested",
            payload={
                "request_id": "req-1",
                "command": "mkdir /tmp/demo",
            },
            raw_method="item/commandExecution/requestApproval",
        )
    )
    question_event = message_event_from_session_event(
        SessionEvent(
            provider="codex",
            workspace_id="codex:/tmp/project",
            thread_id="thread-a",
            turn_id="turn-a",
            kind="question_requested",
            payload={
                "request_id": "que-1",
                "question": "Choose model",
            },
            raw_method="question/asked",
        )
    )

    assert final_event.kind == "message.assistant.final"
    assert final_event.payload["text"] == "final answer"
    assert final_event.payload["semanticKind"] == "turn_completed"
    assert approval_event.kind == "approval.requested"
    assert approval_event.payload["message"] == "需要处理授权请求：mkdir /tmp/demo"
    assert approval_event.payload["requestId"] == "req-1"
    assert approval_event.payload["approvalSource"] == "item/commandExecution/requestApproval"
    assert question_event.kind == "question.requested"
    assert question_event.payload["message"] == "Choose model"


def test_session_event_bridge_treats_provider_default_completed_agent_message_as_final_reply():
    final_event = message_event_from_session_event(
        SessionEvent(
            provider="claude",
            workspace_id="claude:/tmp/project",
            thread_id="session-a",
            turn_id="turn-a",
            kind="assistant_completed",
            payload={
                "threadId": "session-a",
                "turnId": "turn-a",
                "text": "final answer",
                "item": {"type": "agentMessage"},
            },
            raw_method="item/completed",
        )
    )

    assert final_event.kind == "message.assistant.final"
    assert final_event.payload["text"] == "final answer"


def test_session_event_bridge_respects_provider_override_for_completed_agent_message_finality():
    final_event = message_event_from_session_event(
        SessionEvent(
            provider="codex",
            workspace_id="codex:/tmp/project",
            thread_id="thread-a",
            turn_id="turn-a",
            kind="assistant_completed",
            payload={
                "threadId": "thread-a",
                "turnId": "turn-a",
                "text": "commentary-only",
                "item": {"type": "agentMessage"},
            },
            raw_method="item/completed",
        )
    )

    assert final_event.kind == "message.assistant.delta"
    assert final_event.payload["delta"] == "commentary-only"


def test_approval_projection_exposes_request_identity_for_task_board_actions():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：mkdir /tmp/demo",
                "requestId": "req-42",
                "approvalSource": "item/commandExecution/requestApproval",
            },
            created_at=10,
        )
    )

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "needs_attention"
    assert activity["attentionKind"] == "approval"
    assert activity["requestId"] == "req-42"
    assert activity["approvalSource"] == "item/commandExecution/requestApproval"
    assert activity["mirroredOnly"] is False


def test_mirrored_approval_projection_is_marked_for_attention_without_app_control():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "approval.requested",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-a",
            payload={
                "message": "需要处理授权请求：git remote get-url origin",
                "requestId": "req-42",
                "approvalSource": "item/commandExecution/requestApproval",
                "mirroredOnly": True,
                "prompt": "engine实现情况如何？",
            },
            created_at=10,
        )
    )

    activity = state.message_bus.session_activity("claude", "thread-a")
    assert activity["status"] == "needs_attention"
    assert activity["attentionKind"] == "approval"
    assert activity["requestId"] == "req-42"
    assert activity["mirroredOnly"] is True
    assert activity["title"] == "engine实现情况如何？"
    assert activity["attentionReason"] == "需要处理授权请求：git remote get-url origin"


def test_user_interrupted_turn_is_recent_terminal_not_actionable_failure():
    bus = MessageEventBus()
    bus.publish(
        create_message_event(
            "turn.started",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-interrupted",
            created_at=10,
        )
    )
    bus.publish(
        create_message_event(
            "turn.completed",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-interrupted",
            payload={"status": "interrupted"},
            created_at=20,
        )
    )

    activity = bus.session_activity("codex", "thread-interrupted")
    assert activity["status"] == "completed"
    assert activity["attentionKind"] == "interrupted"
    assert activity["attentionReason"] == "任务已由用户中断"
    assert activity["lastEventKind"] == "turn.completed"


def test_user_interruption_classification_survives_followup_completed_event():
    bus = MessageEventBus()
    bus.publish(
        create_message_event(
            "turn.failed",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-interrupted",
            payload={"status": "aborted", "reason": "interrupted"},
            created_at=20,
        )
    )
    bus.publish(
        create_message_event(
            "turn.completed",
            provider_id="codex",
            workspace_id="codex:/tmp/project",
            session_id="thread-interrupted",
            created_at=21,
        )
    )

    activity = bus.session_activity("codex", "thread-interrupted")
    assert activity["status"] == "completed"
    assert activity["attentionKind"] == "interrupted"
    assert activity["attentionReason"] == "任务已由用户中断"
    assert activity["lastEventKind"] == "turn.completed"


def test_unexpected_cancelled_turn_remains_actionable_failure():
    bus = MessageEventBus()
    bus.publish(
        create_message_event(
            "turn.failed",
            provider_id="claude",
            workspace_id="claude:/tmp/project",
            session_id="thread-failed",
            payload={"status": "cancelled", "reason": "provider process exited"},
            created_at=20,
        )
    )

    activity = bus.session_activity("claude", "thread-failed")
    assert activity["status"] == "failed"
    assert activity["attentionKind"] == "failure"
    assert activity["attentionReason"] == "provider process exited"


def test_session_archived_removes_activity_projection():
    state = SimpleNamespace(message_bus=MessageEventBus())
    state.message_bus.publish(
        create_message_event(
            "turn.started",
            provider_id="external",
            workspace_id="external:/tmp/project",
            workspace_path="/tmp/project",
            session_id="ses-archived",
            created_at=10,
        )
    )

    assert state.message_bus.session_activity("external", "ses-archived") is not None
    assert publish_session_archived(
        state,
        provider_id="external",
        workspace_id="external:/tmp/project",
        workspace_path="/tmp/project",
        session_id="ses-archived",
    ) is True
    assert state.message_bus.session_activity("external", "ses-archived") is None


def test_notification_activity_publish_helpers_are_visible_on_bus():
    state = SimpleNamespace(message_bus=MessageEventBus())
    notification = NotificationEvent(
        status="completed",
        agent_name="Codex",
        task_name="Phase 14",
        message="任务已完成",
        task_id="turn-a",
        agent_id="codex",
        task_summary="建立统一消息事件总线",
    )

    assert publish_notification_activity(state, notification, "notification.requested") is True
    assert publish_notification_activity(
        state,
        notification,
        "notification.emitted",
        channels=("telegram",),
    ) is True

    events = state.message_bus.recent_events()
    assert [event["kind"] for event in events] == [
        "notification.requested",
        "notification.emitted",
    ]
    assert events[0]["source"] == "notification"
    assert events[0]["payload"]["taskSummary"] == "建立统一消息事件总线"
    assert events[1]["payload"]["channels"] == ["telegram"]


@pytest.mark.asyncio
async def test_notification_summary_consumer_uses_final_message_from_bus():
    bus = MessageEventBus()
    bus.publish(
        create_message_event(
            "message.assistant.final",
            provider_id="codex",
            session_id="thread-a",
            turn_id="turn-a",
            payload={"text": "已完成 EventBus consumer 迁移。"},
        )
    )

    async def fake_run_ai_scenario(scenario_id, variables):
        assert scenario_id == "notification_summary"
        assert variables["final_message"] == "已完成 EventBus consumer 迁移。"
        assert variables["task_summary"] == "14-02"
        return SimpleNamespace(
            ok=True,
            data={
                "preview_title": "通知摘要迁移",
                "summary": "notification summary 已从 bus final 事件生成。",
            },
        )

    result = await bus.notification_summary.build_completed_notification(
        final_message=None,
        provider_id="codex",
        session_id="thread-a",
        turn_id="turn-a",
        current_title="Phase 14",
        current_task_summary="14-02",
        agent_name="Codex",
        status="completed",
        run_scenario=fake_run_ai_scenario,
    )

    assert result.task_name_override == "通知摘要迁移"
    assert result.task_summary_override == ""
    assert result.message == "完成摘要：notification summary 已从 bus final 事件生成。"
