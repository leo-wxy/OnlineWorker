# tests/test_question_enhanced.py
"""
测试 question 增强功能：多选、自定义输入、多 sub-question。
"""
import time
from types import SimpleNamespace
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.state import AppState, PendingApproval, PendingQuestion, PendingQuestionGroup
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo
from bot.keyboards import (
    build_question_keyboard,
    parse_question_callback,
    QUESTION_TTL_SECONDS,
)

GROUP_CHAT_ID = -100123456789

SAMPLE_OPTIONS = [
    {"label": "Python", "description": "General purpose"},
    {"label": "TypeScript", "description": "Frontend/backend"},
    {"label": "Rust", "description": "Systems programming"},
]


# ── keyboards tests ──────────────────────────────────────────────────────

class TestBuildQuestionKeyboard:
    def test_single_select_basic(self):
        """单选模式：每个选项一行 q_ans 按钮"""
        kb = build_question_keyboard(100, SAMPLE_OPTIONS, multiple=False, custom=False)
        rows = kb.inline_keyboard
        assert len(rows) == 3  # 3 选项，无 custom 按钮
        for i, row in enumerate(rows):
            assert len(row) == 1
            assert row[0].text == SAMPLE_OPTIONS[i]["label"]
            assert row[0].callback_data.startswith(f"q_ans:100:")

    def test_single_select_with_custom(self):
        """单选 + 自定义输入：3 选项 + 1 自定义按钮"""
        kb = build_question_keyboard(100, SAMPLE_OPTIONS, multiple=False, custom=True)
        rows = kb.inline_keyboard
        assert len(rows) == 4  # 3 + custom
        last_row = rows[-1]
        assert "自定义" in last_row[0].text
        assert last_row[0].callback_data.startswith("q_cus:100:")

    def test_multiple_select_basic(self):
        """多选模式：toggle 按钮 + 确认提交"""
        kb = build_question_keyboard(100, SAMPLE_OPTIONS, multiple=True, custom=False)
        rows = kb.inline_keyboard
        # 3 toggle + 1 submit
        assert len(rows) == 4
        for i in range(3):
            assert rows[i][0].callback_data.startswith(f"q_tog:100:")
            assert "⬜" in rows[i][0].text
        assert rows[3][0].callback_data.startswith("q_sub:100:")

    def test_multiple_select_with_selected(self):
        """多选模式：已选中的显示 ✅"""
        kb = build_question_keyboard(
            100, SAMPLE_OPTIONS,
            multiple=True, custom=False,
            selected={0, 2},
        )
        rows = kb.inline_keyboard
        assert "✅" in rows[0][0].text   # index 0 selected
        assert "⬜" in rows[1][0].text   # index 1 not selected
        assert "✅" in rows[2][0].text   # index 2 selected
        # submit 显示已选数量
        assert "2" in rows[3][0].text

    def test_multiple_with_custom(self):
        """多选 + 自定义：3 toggle + custom + submit"""
        kb = build_question_keyboard(
            100, SAMPLE_OPTIONS,
            multiple=True, custom=True,
        )
        rows = kb.inline_keyboard
        # 3 toggle + custom + submit = 5 rows
        assert len(rows) == 5
        custom_row = rows[3]
        assert custom_row[0].callback_data.startswith("q_cus:100:")
        submit_row = rows[4]
        assert submit_row[0].callback_data.startswith("q_sub:100:")

    def test_empty_options_with_custom(self):
        """无选项但有自定义输入按钮"""
        kb = build_question_keyboard(100, [], multiple=False, custom=True)
        rows = kb.inline_keyboard
        assert len(rows) == 1  # 仅 custom 按钮
        assert "自定义" in rows[0][0].text


class TestParseQuestionCallback:
    def test_parse_q_ans(self):
        ts = int(time.time())
        data = f"q_ans:100:{ts}:2"
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)
        assert action == "q_ans"
        assert msg_id == 100
        assert cb_ts == ts
        assert option_idx == 2
        assert not expired

    def test_parse_q_tog(self):
        ts = int(time.time())
        data = f"q_tog:200:{ts}:1"
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)
        assert action == "q_tog"
        assert msg_id == 200
        assert option_idx == 1
        assert not expired

    def test_parse_q_sub(self):
        ts = int(time.time())
        data = f"q_sub:300:{ts}"
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)
        assert action == "q_sub"
        assert msg_id == 300
        assert option_idx == -1  # no option_index
        assert not expired

    def test_parse_q_cus(self):
        ts = int(time.time())
        data = f"q_cus:400:{ts}"
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)
        assert action == "q_cus"
        assert msg_id == 400
        assert option_idx == -1
        assert not expired

    def test_expired(self):
        old_ts = int(time.time()) - QUESTION_TTL_SECONDS - 10
        data = f"q_ans:100:{old_ts}:0"
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback(data)
        assert expired

    def test_invalid_data(self):
        action, msg_id, cb_ts, option_idx, expired = parse_question_callback("garbage")
        assert action == "unknown"
        assert expired


# ── PendingQuestionGroup tests ────────────────────────────────────────────

class TestPendingQuestionGroup:
    def test_all_answered_false(self):
        group = PendingQuestionGroup(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", total=3,
        )
        assert not group.all_answered
        group.answers[0] = ["Python"]
        assert not group.all_answered

    def test_all_answered_true(self):
        group = PendingQuestionGroup(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", total=2,
        )
        group.answers[0] = ["Python"]
        group.answers[1] = ["TypeScript"]
        assert group.all_answered

    def test_collect_answers_ordered(self):
        group = PendingQuestionGroup(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", total=3,
        )
        group.answers[2] = ["Rust"]
        group.answers[0] = ["Python"]
        group.answers[1] = ["TypeScript", "Go"]
        result = group.collect_answers()
        assert result == [["Python"], ["TypeScript", "Go"], ["Rust"]]

    def test_collect_answers_missing(self):
        """未回答的 sub-question 返回空列表"""
        group = PendingQuestionGroup(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", total=3,
        )
        group.answers[0] = ["Python"]
        result = group.collect_answers()
        assert result == [["Python"], [], []]


# ── AppState question helpers ─────────────────────────────────────────────

class TestAppStateQuestionHelpers:
    def test_find_awaiting_text_question(self):
        state = AppState()
        state.storage = AppStorage()
        pq = PendingQuestion(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", header="Test",
            question_text="What?", options=[],
            awaiting_text=True, topic_id=100,
        )
        state.pending_questions[42] = pq
        result = state.find_awaiting_text_question(100)
        assert result is not None
        assert result[0] == 42
        assert result[1] is pq

    def test_find_awaiting_text_question_wrong_topic(self):
        state = AppState()
        state.storage = AppStorage()
        pq = PendingQuestion(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", header="Test",
            question_text="What?", options=[],
            awaiting_text=True, topic_id=100,
        )
        state.pending_questions[42] = pq
        result = state.find_awaiting_text_question(999)
        assert result is None

    def test_find_awaiting_text_not_awaiting(self):
        state = AppState()
        state.storage = AppStorage()
        pq = PendingQuestion(
            question_id="que_1", session_id="ses_1",
            workspace_id="ws_1", header="Test",
            question_text="What?", options=[],
            awaiting_text=False, topic_id=100,
        )
        state.pending_questions[42] = pq
        result = state.find_awaiting_text_question(100)
        assert result is None


# ── Callback handler tests ────────────────────────────────────────────────

@pytest.fixture
def state():
    st = AppState()
    st.storage = AppStorage()
    return st


@pytest.fixture
def mock_cm_adapter():
    adapter = MagicMock()
    adapter.connected = True
    adapter.reply_question = AsyncMock()
    adapter.reply_server_request = AsyncMock()
    return adapter


@pytest.fixture
def mock_codex_adapter():
    adapter = MagicMock()
    adapter.connected = True
    adapter.reply_server_request = AsyncMock()
    return adapter


def _make_query_mock(data: str):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    return query


def _make_update_with_query(data: str):
    update = MagicMock()
    query = _make_query_mock(data)
    update.callback_query = query
    return update, query


@pytest.mark.asyncio
async def test_codex_approval_callback_resolves_run_interruption(state, mock_codex_adapter):
    """codex 授权回调成功后应把 interruption 从 run ledger 中解析掉。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("codex", mock_codex_adapter)
    run = codex_state.start_run(state,
        workspace_id="codex:test",
        thread_id="tid-1",
        turn_id="turn-1",
    )
    codex_state.add_interruption(state, thread_id="tid-1", interruption_id="req-1")
    state.pending_approvals[42] = PendingApproval(
        request_id="req-1",
        workspace_id="codex:test",
        thread_id="tid-1",
        cmd="mkdir /tmp/demo",
        justification="need write",
        proposed_amendment=[],
        tool_type="codex",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow:42:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_codex_adapter.reply_server_request.assert_awaited_once()
    assert codex_state.get_runtime(state).interruptions["req-1"].status == "resolved"
    assert codex_state.get_runtime(state).interruptions["req-1"].tg_message_id == 42
    assert "req-1" not in run.active_interruption_ids
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_q_ans_single_select(state, mock_cm_adapter):
    """单选回调：点击立即提交"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="ws_1", header="Language",
        question_text="Pick one", options=SAMPLE_OPTIONS,
        multiple=False, custom=False, topic_id=100,
    )
    state.pending_questions[42] = pq

    update, query = _make_update_with_query(f"q_ans:42:{ts}:1")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_question.assert_called_once_with("que_1", [["TypeScript"]])
    assert 42 not in state.pending_questions


@pytest.mark.asyncio
async def test_q_tog_toggle(state, mock_cm_adapter):
    """多选 toggle：点击选中/取消"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="ws_1", header="Languages",
        question_text="Pick many", options=SAMPLE_OPTIONS,
        multiple=True, custom=False, topic_id=100,
    )
    state.pending_questions[42] = pq

    # 第一次点击 index=0 → 选中
    update, query = _make_update_with_query(f"q_tog:42:{ts}:0")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)
    assert 0 in pq.selected
    mock_cm_adapter.reply_question.assert_not_called()  # 不应提交

    # 第二次点击 index=0 → 取消
    update2, query2 = _make_update_with_query(f"q_tog:42:{ts}:0")
    await handler(update2, ctx)
    assert 0 not in pq.selected


@pytest.mark.asyncio
async def test_q_sub_submit(state, mock_cm_adapter):
    """多选确认提交"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="ws_1", header="Languages",
        question_text="Pick many", options=SAMPLE_OPTIONS,
        multiple=True, custom=False, topic_id=100,
        selected={0, 2},  # Python, Rust
    )
    state.pending_questions[42] = pq

    update, query = _make_update_with_query(f"q_sub:42:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_question.assert_called_once_with("que_1", [["Python", "Rust"]])
    assert 42 not in state.pending_questions


@pytest.mark.asyncio
async def test_q_sub_empty_selection(state, mock_cm_adapter):
    """多选提交但未选任何选项 → 提示"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="ws_1", header="Languages",
        question_text="Pick many", options=SAMPLE_OPTIONS,
        multiple=True, custom=False, topic_id=100,
    )
    state.pending_questions[42] = pq

    update, query = _make_update_with_query(f"q_sub:42:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_question.assert_not_called()
    query.answer.assert_called()  # 应提示用户


@pytest.mark.asyncio
async def test_q_cus_custom_input(state, mock_cm_adapter):
    """自定义输入：点击后进入 awaiting_text 状态"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="ws_1", header="Language",
        question_text="Pick or type", options=SAMPLE_OPTIONS,
        custom=True, topic_id=100,
    )
    state.pending_questions[42] = pq

    update, query = _make_update_with_query(f"q_cus:42:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    assert pq.awaiting_text is True
    mock_cm_adapter.reply_question.assert_not_called()


@pytest.mark.asyncio
async def test_awaiting_text_message_intercept(state, mock_cm_adapter):
    """自定义输入：用户文字回复被截获并提交"""
    from bot.handlers import make_message_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    # 设置 workspace + thread（让 message handler 能找到 topic）
    ws = WorkspaceInfo(
        name="test", path="/tmp/test", daemon_workspace_id="customprovider:test",
        topic_id=50, tool="customprovider",
    )
    ws.threads["ses_1"] = ThreadInfo(thread_id="ses_1", topic_id=100)
    state.storage.workspaces["test"] = ws

    # 设置 awaiting_text question
    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="customprovider:test", header="Language",
        question_text="Pick or type", options=SAMPLE_OPTIONS,
        custom=True, awaiting_text=True, topic_id=100,
    )
    state.pending_questions[42] = pq

    # 模拟用户发消息
    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "Golang"
    update.effective_message.message_id = 999
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_question.assert_called_once_with("que_1", [["Golang"]])
    assert 42 not in state.pending_questions


@pytest.mark.asyncio
async def test_awaiting_text_ignores_photo_and_prompts_for_text(state, mock_cm_adapter):
    """自定义输入等待文字时，图片不应被当成答案提交。"""
    from bot.handlers import make_message_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ws = WorkspaceInfo(
        name="test", path="/tmp/test", daemon_workspace_id="customprovider:test",
        topic_id=50, tool="customprovider",
    )
    ws.threads["ses_1"] = ThreadInfo(thread_id="ses_1", topic_id=100)
    state.storage.workspaces["test"] = ws

    pq = PendingQuestion(
        question_id="que_1", session_id="ses_1",
        workspace_id="customprovider:test", header="Language",
        question_text="Pick or type", options=SAMPLE_OPTIONS,
        custom=True, awaiting_text=True, topic_id=100,
    )
    state.pending_questions[42] = pq

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = None
    update.effective_message.caption = "一张图"
    update.effective_message.photo = [MagicMock()]
    update.effective_message.message_id = 999
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_question.assert_not_called()
    assert 42 in state.pending_questions
    ctx.bot.send_message.assert_awaited_once()
    assert "等待文字输入" in ctx.bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_customprovider_approval_callback_replies_via_adapter(state, mock_cm_adapter):
    """customprovider 权限按钮应走 adapter 的远程授权链路。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("customprovider", mock_cm_adapter)
    state.pending_approvals[42] = PendingApproval(
        request_id="per_1",
        workspace_id="customprovider:test",
        thread_id="ses_1",
        cmd="写入文件：/Users/example/Music/demo.txt",
        justification="权限类型：external_directory",
        proposed_amendment=[],
        tool_type="customprovider",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow:42:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_server_request.assert_awaited_once_with(
        "customprovider:test",
        "per_1",
        {"decision": "accept"},
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "已允许" in text


@pytest.mark.asyncio
async def test_customprovider_deny_callback_replies_via_adapter(state, mock_cm_adapter):
    """customprovider 的 deny 应走 adapter 的远程授权链路。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("customprovider", mock_cm_adapter)
    state.pending_approvals[43] = PendingApproval(
        request_id="per_2",
        workspace_id="customprovider:test",
        thread_id="ses_1",
        cmd="写入文件：/Users/example/Music/demo.txt",
        justification="权限类型：external_directory",
        proposed_amendment=[],
        tool_type="customprovider",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_deny:43:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_server_request.assert_awaited_once_with(
        "customprovider:test",
        "per_2",
        {"decision": "decline"},
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "已拒绝" in text


@pytest.mark.asyncio
async def test_customprovider_allow_always_callback_replies_via_adapter(state, mock_cm_adapter):
    """customprovider 的 allow always 必须下发 always，而不是退化成 once。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("customprovider", mock_cm_adapter)
    state.pending_approvals[44] = PendingApproval(
        request_id="per_3",
        workspace_id="customprovider:test",
        thread_id="ses_1",
        cmd="写入文件：/Users/example/Music/demo.txt",
        justification="权限类型：external_directory",
        proposed_amendment=[],
        tool_type="customprovider",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow_always:44:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_cm_adapter.reply_server_request.assert_awaited_once_with(
        "customprovider:test",
        "per_3",
        {"decision": "acceptForSession"},
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "总是允许" in text


@pytest.mark.asyncio
async def test_codex_allow_always_uses_amendment_decision(state, mock_codex_adapter):
    """codex 的 allow always 必须回传 amendment decision。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("codex", mock_codex_adapter)
    state.pending_approvals[45] = PendingApproval(
        request_id="req_1",
        workspace_id="codex:test",
        thread_id="tid_1",
        cmd="rm -rf /tmp/demo",
        justification="需要额外目录访问",
        proposed_amendment=["/tmp/demo"],
        amendment_decision={
            "acceptWithExecpolicyAmendment": {
                "execpolicy_amendment": ["/tmp/demo"],
            }
        },
        tool_type="codex",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow_always:45:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_codex_adapter.reply_server_request.assert_awaited_once_with(
        "codex:test",
        "req_1",
        {
            "acceptWithExecpolicyAmendment": {
                "execpolicy_amendment": ["/tmp/demo"],
            }
        },
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "总是允许" in text


@pytest.mark.asyncio
async def test_codex_allow_always_without_amendment_uses_accept_for_session(state, mock_codex_adapter):
    """codex 的 allow always 在无 amendment 时应走 acceptForSession。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("codex", mock_codex_adapter)
    state.pending_approvals[46] = PendingApproval(
        request_id="req_2",
        workspace_id="codex:test",
        thread_id="tid_2",
        cmd="touch /tmp/demo.txt",
        justification="需要写入额外路径",
        proposed_amendment=[],
        tool_type="codex",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow_always:46:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_codex_adapter.reply_server_request.assert_awaited_once_with(
        "codex:test",
        "req_2",
        {"decision": "acceptForSession"},
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "总是允许" in text


@pytest.mark.asyncio
async def test_codex_deny_uses_decline_instead_of_cancel(state, mock_codex_adapter):
    """codex 的 deny 应让 agent 继续当前 turn，而不是直接 cancel 整轮。"""
    from bot.handlers import make_callback_handler

    state.set_adapter("codex", mock_codex_adapter)
    state.pending_approvals[47] = PendingApproval(
        request_id="req_3",
        workspace_id="codex:test",
        thread_id="tid_3",
        cmd="rm -rf /tmp/demo",
        justification="用户拒绝执行该命令",
        proposed_amendment=[],
        tool_type="codex",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_deny:47:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    mock_codex_adapter.reply_server_request.assert_awaited_once_with(
        "codex:test",
        "req_3",
        {"decision": "decline"},
    )
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "已拒绝" in text


@pytest.mark.asyncio
async def test_claude_allow_callback_uses_provider_hook(state, monkeypatch):
    """Claude 普通 allow 必须回写 hook bridge 期望的 allow 语义。"""
    from bot.handlers import make_callback_handler

    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.reply_server_request = AsyncMock()
    state.set_adapter("claude", claude_adapter)
    state.pending_approvals[48] = PendingApproval(
        request_id="claude_req_allow_1",
        workspace_id="claude:test",
        thread_id="claude-ses-allow-1",
        cmd="pwd",
        justification="检查目录",
        proposed_amendment=[],
        tool_type="claude",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow:48:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    claude_adapter.reply_server_request.assert_awaited_once_with(
        "claude:test",
        "claude_req_allow_1",
        {"behavior": "allow"},
    )
    query.edit_message_text.assert_awaited_once()
    assert "已允许" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_claude_allow_always_callback_uses_provider_hook(state, monkeypatch):
    """Claude 权限批准应回写 hook bridge 期望的 behavior/scope 语义。"""
    from bot.handlers import make_callback_handler

    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.reply_server_request = AsyncMock()
    state.set_adapter("claude", claude_adapter)
    state.pending_approvals[47] = PendingApproval(
        request_id="claude_req_1",
        workspace_id="claude:test",
        thread_id="claude-ses-1",
        cmd="pwd",
        justification="检查目录",
        proposed_amendment=[],
        tool_type="claude",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow_always:47:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    claude_adapter.reply_server_request.assert_awaited_once_with(
        "claude:test",
        "claude_req_1",
        {"behavior": "allow", "scope": "session"},
    )
    query.edit_message_text.assert_awaited_once()
    assert "已总是允许" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_approval_callback_keeps_pending_when_reply_fails(state):
    """远程回包失败时不应提前丢失 pending approval，用户需要能重试。"""
    from bot.handlers import make_callback_handler

    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.reply_server_request = AsyncMock(side_effect=RuntimeError("bridge timeout"))
    state.set_adapter("claude", claude_adapter)
    state.pending_approvals[49] = PendingApproval(
        request_id="claude_req_retry_1",
        workspace_id="claude:test",
        thread_id="claude-ses-retry-1",
        cmd="pwd",
        justification="检查目录",
        proposed_amendment=[],
        tool_type="claude",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow:49:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    assert 49 in state.pending_approvals
    query.edit_message_text.assert_awaited_once()
    assert "回复授权失败" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_approval_callback_still_replies_when_callback_answer_fails(state):
    """TG callback answer 过期/失败时，授权处理仍应继续，不得在入口处中断。"""
    from bot.handlers import make_callback_handler

    claude_adapter = MagicMock()
    claude_adapter.connected = True
    claude_adapter.reply_server_request = AsyncMock()
    state.set_adapter("claude", claude_adapter)
    state.pending_approvals[50] = PendingApproval(
        request_id="claude_req_answer_fail_1",
        workspace_id="claude:test",
        thread_id="claude-ses-answer-fail-1",
        cmd="pwd",
        justification="检查目录",
        proposed_amendment=[],
        tool_type="claude",
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow:50:{ts}")
    query.answer = AsyncMock(side_effect=RuntimeError("Query is too old and response timeout expired"))
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    claude_adapter.reply_server_request.assert_awaited_once_with(
        "claude:test",
        "claude_req_answer_fail_1",
        {"behavior": "allow"},
    )
    query.edit_message_text.assert_awaited_once()
    assert 50 not in state.pending_approvals


@pytest.mark.asyncio
async def test_custom_provider_approval_callback_uses_provider_hook(state, monkeypatch):
    """approval 回复格式应由 provider hook 决定，而不是默认退回 codex 语义。"""
    from bot.handlers import make_callback_handler

    custom_adapter = MagicMock()
    custom_adapter.connected = True
    custom_adapter.reply_server_request = AsyncMock()
    state.set_adapter("custom", custom_adapter)
    state.pending_approvals[46] = PendingApproval(
        request_id="custom_req_1",
        workspace_id="custom:test",
        thread_id="thread_1",
        cmd="custom run",
        justification="provider specific approval",
        proposed_amendment=[],
        tool_type="custom",
    )

    def _build_reply(approval, action):
        assert action == "exec_allow_always"
        return "✅ 已自定义允许", {"reply": "custom-always", "thread": approval.thread_id}

    monkeypatch.setattr(
        "bot.handlers.message.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(build_approval_reply=_build_reply)
        ) if name == "custom" else None,
    )

    ts = int(time.time())
    update, query = _make_update_with_query(f"exec_allow_always:46:{ts}")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    custom_adapter.reply_server_request.assert_awaited_once_with(
        "custom:test",
        "custom_req_1",
        {"reply": "custom-always", "thread": "thread_1"},
    )
    query.edit_message_text.assert_awaited_once()
    assert "已自定义允许" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_multi_sub_question_group(state, mock_cm_adapter):
    """多 sub-question：逐个回答后合并提交"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    ts = int(time.time())
    group = PendingQuestionGroup(
        question_id="que_multi", session_id="ses_1",
        workspace_id="ws_1", total=2,
    )
    group.msg_ids = {0: 42, 1: 43}
    state.pending_question_groups["que_multi"] = group

    pq0 = PendingQuestion(
        question_id="que_multi", session_id="ses_1",
        workspace_id="ws_1", header="Q1", question_text="First?",
        options=[{"label": "A"}, {"label": "B"}],
        group=group, sub_index=0, topic_id=100,
    )
    pq1 = PendingQuestion(
        question_id="que_multi", session_id="ses_1",
        workspace_id="ws_1", header="Q2", question_text="Second?",
        options=[{"label": "X"}, {"label": "Y"}],
        group=group, sub_index=1, topic_id=100,
    )
    state.pending_questions[42] = pq0
    state.pending_questions[43] = pq1

    handler = make_callback_handler(state, GROUP_CHAT_ID)

    # 回答 sub 0
    update1, query1 = _make_update_with_query(f"q_ans:42:{ts}:0")
    await handler(update1, MagicMock())
    assert group.answers[0] == ["A"]
    mock_cm_adapter.reply_question.assert_not_called()  # 还没全答完

    # 回答 sub 1
    update2, query2 = _make_update_with_query(f"q_ans:43:{ts}:1")
    await handler(update2, MagicMock())
    assert group.answers[1] == ["Y"]
    mock_cm_adapter.reply_question.assert_called_once_with("que_multi", [["A"], ["Y"]])
    assert "que_multi" not in state.pending_question_groups


@pytest.mark.asyncio
async def test_expired_question(state, mock_cm_adapter):
    """过期的 question 回调"""
    from bot.handlers import make_callback_handler
    state.set_adapter("customprovider", mock_cm_adapter)

    old_ts = int(time.time()) - QUESTION_TTL_SECONDS - 10
    update, query = _make_update_with_query(f"q_ans:42:{old_ts}:0")
    ctx = MagicMock()
    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    # 应提示过期
    query.answer.assert_called()
    mock_cm_adapter.reply_question.assert_not_called()


@pytest.mark.asyncio
async def test_awaiting_text_routes_via_provider_question_hook(state, monkeypatch):
    """awaiting_text 回复应走 workspace provider，而不是写死 customprovider。"""
    from bot.handlers import make_message_handler

    custom_adapter = MagicMock()
    custom_adapter.connected = True
    custom_adapter.reply_question = AsyncMock()
    state.set_adapter("custom", custom_adapter)

    ws = WorkspaceInfo(
        name="test", path="/tmp/test", daemon_workspace_id="custom:test",
        topic_id=50, tool="custom",
    )
    ws.threads["thr_1"] = ThreadInfo(thread_id="thr_1", topic_id=100)
    state.storage.workspaces["test"] = ws

    pq = PendingQuestion(
        question_id="que_custom",
        session_id="thr_1",
        workspace_id="custom:test",
        tool_name="custom",
        header="Language",
        question_text="Pick or type",
        options=SAMPLE_OPTIONS,
        custom=True,
        awaiting_text=True,
        topic_id=100,
    )
    state.pending_questions[42] = pq

    async def _reply_question(adapter, pending_question, answers):
        await adapter.reply_question(pending_question.question_id, answers)

    monkeypatch.setattr(
        "bot.handlers.message.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            interactions=SimpleNamespace(reply_question=_reply_question)
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.text = "Golang"
    update.effective_message.message_id = 999
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.edit_message_text = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    custom_adapter.reply_question.assert_awaited_once_with("que_custom", [["Golang"]])
    assert 42 not in state.pending_questions
