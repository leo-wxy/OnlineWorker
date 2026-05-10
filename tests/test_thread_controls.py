from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import (
    AppState,
    PendingCommandWrapper,
    PendingCommandWrapperOption,
    StreamingTurn,
)
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo

GROUP_CHAT_ID = -100123456789


def _build_state(*, tool: str, control_mode: str = "app") -> AppState:
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/example/Projects/onlineWorker",
        tool=tool,
        topic_id=50,
        daemon_workspace_id=f"{tool}:onlineWorker",
    )
    storage.workspaces[f"{tool}:onlineWorker"] = ws
    storage.active_workspace = f"{tool}:onlineWorker"

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=GROUP_CHAT_ID,
        log_level="INFO",
        tools=[
            ToolConfig(
                name=tool,
                enabled=True,
                codex_bin=tool,
                protocol="ws" if tool == "codex" else "http",
                app_server_port=4722 if tool == "codex" else None,
                control_mode=control_mode if tool == "codex" else "app",
            )
        ],
        delete_archived_topics=True,
    )
    return AppState(storage=storage, config=cfg)


@pytest.mark.asyncio
async def test_thread_topic_slash_message_passthrough_to_codex():
    from bot.handlers.message import make_message_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "/help"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "/help")


@pytest.mark.asyncio
async def test_thread_topic_slash_message_passthrough_to_codex():
    from bot.handlers.message import make_message_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "/model"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "/model")


@pytest.mark.asyncio
async def test_thread_topic_message_revives_stale_archived_thread_when_source_active(monkeypatch):
    from bot.handlers.message import make_message_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=True, is_active=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "继续"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {"tid-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.message.save_storage",
        lambda storage: None,
    )

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "继续")


@pytest.mark.asyncio
async def test_thread_topic_message_uses_registry_message_hooks_for_custom_provider(monkeypatch):
    from bot.handlers.message import make_message_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    state.set_adapter("custom", adapter)

    custom_send = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.message.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                supports_photo=False,
                ensure_connected=AsyncMock(return_value=adapter),
                handle_local_owner=AsyncMock(return_value=False),
                prepare_send=AsyncMock(return_value=True),
                send=custom_send,
            )
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "hello custom"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    custom_send.assert_awaited_once()
    args = custom_send.await_args.args
    assert args[0] is state
    assert args[2] == ws
    assert args[3].thread_id == "custom-1"


@pytest.mark.asyncio
async def test_thread_topic_message_uses_provider_local_owner_hook_for_custom_provider(monkeypatch):
    from bot.handlers.message import make_message_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    state.set_adapter("custom", adapter)

    handle_local_owner = AsyncMock(return_value=True)
    ensure_connected = AsyncMock(return_value=adapter)
    prepare_send = AsyncMock(return_value=True)
    send = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.message.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            message_hooks=SimpleNamespace(
                supports_photo=False,
                handle_local_owner=handle_local_owner,
                ensure_connected=ensure_connected,
                prepare_send=prepare_send,
                send=send,
            )
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.text = "hello local owner"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_message_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    handle_local_owner.assert_awaited_once()
    ensure_connected.assert_not_awaited()
    prepare_send.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_thread_handler_uses_provider_thread_hooks_for_custom_provider(monkeypatch):
    from bot.handlers.thread import make_new_thread_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "custom-new"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("custom", adapter)

    activate_new_thread = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.thread.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                resolve_adapter=lambda state, ws: adapter,
                validate_new_thread=lambda state, ws, initial_text: None,
                activate_new_thread=activate_new_thread,
            )
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=100))
    ctx.bot.send_message = AsyncMock()

    handler = make_new_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    activate_new_thread.assert_awaited_once()
    args = activate_new_thread.await_args.args
    assert args[0] is state
    assert args[1] is adapter
    assert args[2] is ws
    assert args[3] == "custom:onlineWorker"
    assert args[4] == "custom-new"
    assert args[5] is None
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_thread_handler_sends_thread_control_buttons():
    from bot.handlers.thread import make_new_thread_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "tid-new"})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.args = ["请检查当前配置"]
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=100))
    ctx.bot.send_message = AsyncMock()

    handler = make_new_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    thread_calls = [
        call.kwargs
        for call in ctx.bot.send_message.await_args_list
        if call.kwargs.get("message_thread_id") == 100
    ]
    assert thread_calls
    control_call = next(kwargs for kwargs in thread_calls if kwargs.get("reply_markup") is not None)
    button_texts = [
        button.text
        for row in control_call["reply_markup"].inline_keyboard
        for button in row
    ]
    assert "帮助" in button_texts
    assert "历史" in button_texts
    assert "中断" in button_texts
    assert "归档" in button_texts


@pytest.mark.asyncio
async def test_thread_control_interrupt_uses_provider_thread_hooks_for_custom_provider(monkeypatch):
    from bot.handlers.thread import handle_thread_control_callback

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.turn_interrupt = AsyncMock(return_value={})
    state.set_adapter("custom", adapter)
    state.streaming_turns["custom-1"] = StreamingTurn(
        message_id=5001,
        topic_id=100,
        turn_id="turn-custom-1",
    )

    interrupt_thread = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.thread.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                resolve_adapter=lambda state, ws: adapter,
                interrupt_thread=interrupt_thread,
            )
        ) if name == "custom" else None,
    )

    query = MagicMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    bot = MagicMock()
    bot.send_message = AsyncMock()

    handled = await handle_thread_control_callback(
        state,
        bot,
        GROUP_CHAT_ID,
        query,
        "interrupt",
    )

    assert handled is True
    interrupt_thread.assert_awaited_once()
    args = interrupt_thread.await_args.args
    assert args[0] is state
    assert args[1] is ws
    assert args[2].thread_id == "custom-1"
    assert args[3] is adapter
    assert args[4] == "turn-custom-1"
    adapter.turn_interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_thread_control_interrupt_callback_uses_adapter_turn_interrupt():
    from bot.handlers.message import make_callback_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.turn_interrupt = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)
    state.streaming_turns["tid-1"] = StreamingTurn(
        message_id=5001,
        topic_id=100,
        turn_id="turn-1",
    )

    query = MagicMock()
    query.data = "threadctl:interrupt"
    query.answer = AsyncMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    update = MagicMock()
    update.callback_query = query

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.turn_interrupt.assert_awaited_once_with("codex:onlineWorker", "tid-1", "turn-1")
    ctx.bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_model_wrapper_callback_select_model_advances_without_applying():
    from bot.handlers.message import make_callback_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.set_thread_model_config = AsyncMock(return_value={"thread": {"id": "tid-1"}})
    state.set_adapter("codex", adapter)
    state.pending_command_wrappers[700] = PendingCommandWrapper(
        command_name="model",
        workspace_id="codex:onlineWorker",
        thread_id="tid-1",
        topic_id=100,
        tool_name="codex",
        prompt_text="step 1",
        current_step="select_model",
        selected_model="gpt-5.4",
        selected_effort="medium",
        model_options=[
            PendingCommandWrapperOption(
                label="GPT-5.4",
                value="gpt-5.4",
                action="set_model",
            ),
            PendingCommandWrapperOption(
                label="GPT-5.5",
                value="gpt-5.5",
                action="set_model",
            ),
        ],
        effort_options=[
            PendingCommandWrapperOption(
                label="medium",
                value="medium",
                action="set_effort",
            ),
            PendingCommandWrapperOption(
                label="high",
                value="high",
                action="set_effort",
            ),
        ],
        options=[
            PendingCommandWrapperOption(
                label="GPT-5.5",
                value="gpt-5.5",
                action="set_model",
            )
        ],
    )

    query = MagicMock()
    query.data = "cmdw_sel:700:9999999999:0"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    update = MagicMock()
    update.callback_query = query

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.set_thread_model_config.assert_not_awaited()
    pending = state.pending_command_wrappers[700]
    assert pending.current_step == "select_effort"
    assert pending.selected_model == "gpt-5.5"
    assert any(option.action == "set_effort" for option in pending.options)
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_model_wrapper_callback_uses_provider_command_hook_for_custom_provider(monkeypatch):
    from bot.handlers.message import make_callback_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    apply_wrapper = AsyncMock(return_value="✅ custom wrapper applied")
    pending = PendingCommandWrapper(
        command_name="model",
        workspace_id="custom:onlineWorker",
        thread_id="custom-1",
        topic_id=100,
        tool_name="custom",
        prompt_text="custom panel",
        current_step="confirm",
        options=[
            PendingCommandWrapperOption(
                label="应用",
                value="apply",
                action="apply",
            )
        ],
        model_options=[],
        effort_options=[],
    )
    state.pending_command_wrappers[700] = pending

    monkeypatch.setattr(
        "bot.interaction_specs.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            capabilities=SimpleNamespace(command_wrappers=("model",)),
            command_hooks=SimpleNamespace(
                apply_thread_command_wrapper_selection=apply_wrapper,
            ),
        ) if name == "custom" else None,
    )

    query = MagicMock()
    query.data = "cmdw_sel:700:9999999999:0"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    update = MagicMock()
    update.callback_query = query

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    apply_wrapper.assert_awaited_once_with(state, pending, 0)
    query.edit_message_text.assert_awaited_once_with("✅ custom wrapper applied")


@pytest.mark.asyncio
async def test_archive_handler_uses_provider_thread_hooks_for_custom_provider(monkeypatch):
    from bot.handlers.thread import make_archive_thread_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.archive_thread = AsyncMock(return_value={})
    state.set_adapter("custom", adapter)

    archive_thread = AsyncMock()
    monkeypatch.setattr(
        "bot.handlers.thread.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            thread_hooks=SimpleNamespace(
                resolve_adapter=lambda state, ws: adapter,
                archive_thread=archive_thread,
            )
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.delete_forum_topic = AsyncMock()

    handler = make_archive_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    archive_thread.assert_awaited_once()
    args = archive_thread.await_args.args
    assert args[0] is state
    assert args[1] is ws
    assert args[2] == "custom-1"
    assert args[3] is adapter
    adapter.archive_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_model_wrapper_callback_applies_selected_model_and_effort_together():
    from bot.handlers.message import make_callback_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.set_thread_model_config = AsyncMock(return_value={"thread": {"id": "tid-1"}})
    state.set_adapter("codex", adapter)
    state.pending_command_wrappers[700] = PendingCommandWrapper(
        command_name="model",
        workspace_id="codex:onlineWorker",
        thread_id="tid-1",
        topic_id=100,
        tool_name="codex",
        prompt_text="model picker",
        current_step="confirm",
        selected_model="gpt-5.4",
        selected_effort="high",
        options=[
            PendingCommandWrapperOption(
                label="应用当前选择",
                value="apply",
                action="apply",
            )
        ],
        model_options=[],
        effort_options=[],
    )

    query = MagicMock()
    query.data = "cmdw_sel:700:9999999999:0"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    update = MagicMock()
    update.callback_query = query

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.set_thread_model_config.assert_awaited_once_with(
        "codex:onlineWorker",
        "tid-1",
        model="gpt-5.4",
        reasoning_effort="high",
    )
    assert 700 not in state.pending_command_wrappers
    query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_review_wrapper_callback_applies_via_existing_thread_send_chain():
    from bot.handlers.message import make_callback_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)
    state.pending_command_wrappers[700] = PendingCommandWrapper(
        command_name="review",
        workspace_id="codex:onlineWorker",
        thread_id="tid-1",
        topic_id=100,
        tool_name="codex",
        prompt_text="review confirm",
        current_step="confirm",
        text_value="HEAD~1",
        options=[
            PendingCommandWrapperOption(
                label="✅ 确认执行",
                value="apply",
                action="apply",
            )
        ],
    )

    query = MagicMock()
    query.data = "cmdw_sel:700:9999999999:0"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock()
    query.message.message_thread_id = 100

    update = MagicMock()
    update.callback_query = query

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_callback_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "tid-1",
        "/review HEAD~1",
    )
    assert 700 not in state.pending_command_wrappers
    query.edit_message_text.assert_awaited_once()
    assert "已发送" in query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_history_handler_uses_provider_defaults_for_codex(monkeypatch):
    from bot.handlers.thread import make_history_handler

    state = _build_state(tool="codex", control_mode="app")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    called = {}

    def _read_history(tool_name, thread_id, *, limit=10, sessions_dir=None):
        called["tool_name"] = tool_name
        called["thread_id"] = thread_id
        called["limit"] = limit
        called["sessions_dir"] = sessions_dir
        return [{"role": "assistant", "text": "done"}]

    monkeypatch.setattr("bot.handlers.thread.read_provider_thread_history", _read_history)

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.args = ["5"]
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_history_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    assert called == {
        "tool_name": "codex",
        "thread_id": "tid-1",
        "limit": 5,
        "sessions_dir": None,
    }


@pytest.mark.asyncio
async def test_list_thread_handler_uses_provider_local_fallback_and_subagent_detector(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["main-1"] = ThreadInfo(thread_id="main-1", topic_id=None, preview="state main", archived=False)
    ws.threads["child-1"] = ThreadInfo(thread_id="child-1", topic_id=None, preview="state child", archived=False)

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.thread.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            facts=SimpleNamespace(
                list_subagent_thread_ids=lambda thread_ids: {"child-1"}
            ),
            workspace_hooks=SimpleNamespace(
                list_local_threads=lambda path, limit=20: [
                    {"id": "local-1", "preview": "local main", "createdAt": 20, "updatedAt": 20},
                    {"id": "child-1", "preview": "local child", "createdAt": 21, "updatedAt": 21},
                ]
            ),
        ) if name == "custom" else None,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    kwargs = ctx.bot.send_message.await_args.kwargs
    assert "state child" not in kwargs["text"]
    assert "local child" not in kwargs["text"]
    assert "state main" in kwargs["text"]
    assert "local main" in kwargs["text"]


@pytest.mark.asyncio
async def test_list_thread_handler_revives_stale_locally_archived_active_thread(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(
        thread_id="tid-1",
        topic_id=None,
        preview="stale preview",
        archived=True,
        is_active=False,
    )

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, path, limit=20: [
            {"id": "tid-1", "preview": "fresh preview", "createdAt": 20, "updatedAt": 20},
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_local_threads",
        lambda tool_name, path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {"tid-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_subagent_thread_ids",
        lambda tool_name, thread_ids: set(),
    )
    monkeypatch.setattr(
        "bot.handlers.thread.query_provider_active_thread_ids",
        lambda tool_name, path: {"tid-1"},
    )
    monkeypatch.setattr(
        "bot.handlers.thread.save_storage",
        lambda storage: None,
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    assert ws.threads["tid-1"].archived is False
    assert ws.threads["tid-1"].is_active is True
    kwargs = ctx.bot.send_message.await_args.kwargs
    assert "fresh preview" in kwargs["text"]
