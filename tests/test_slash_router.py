import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo

GROUP_CHAT_ID = -100123456789


def _build_state(*, tool: str, control_mode: str = "app") -> AppState:
    storage = AppStorage()
    storage.global_topic_ids[tool] = 10
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
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
async def test_slash_router_wraps_bare_model_via_provider_command_hook_for_custom_provider(monkeypatch):
    from bot.handlers.slash import make_slash_command_handler
    from core.state import PendingCommandWrapper, PendingCommandWrapperOption

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(thread_id="custom-1", topic_id=100, archived=False)

    pending = PendingCommandWrapper(
        command_name="model",
        workspace_id="custom:onlineWorker",
        thread_id="custom-1",
        topic_id=100,
        tool_name="custom",
        prompt_text="custom model panel",
        options=[
            PendingCommandWrapperOption(
                label="model-a",
                value="model-a",
                action="set_model",
            )
        ],
        current_step="select_model",
    )
    build_wrapper = AsyncMock(return_value=pending)

    monkeypatch.setattr(
        "bot.interaction_specs.get_provider",
        lambda name, *args, **kwargs: SimpleNamespace(
            capabilities=SimpleNamespace(command_wrappers=("model",)),
            command_hooks=SimpleNamespace(
                build_thread_command_wrapper=build_wrapper,
            ),
        ) if name == "custom" else None,
    )
    monkeypatch.setattr(
        "bot.handlers.slash.classify_provider",
        lambda name, cfg: "available" if name == "custom" else "unknown_provider",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 701
    update.effective_message.text = "/model"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=901))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    build_wrapper.assert_awaited_once()
    ctx.bot.send_message.assert_awaited_once()
    created = state.pending_command_wrappers[701]
    assert created.tool_name == "custom"
    assert created.command_name == "model"


@pytest.mark.asyncio
async def test_slash_router_wraps_bare_model_in_codex_thread():
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    adapter.list_models = AsyncMock(
        return_value=[
            {
                "model": "gpt-5.4",
                "displayName": "GPT-5.4",
                "hidden": False,
                "isDefault": True,
                "supportedReasoningEfforts": [
                    {"reasoningEffort": "medium", "description": "balanced"},
                    {"reasoningEffort": "high", "description": "deeper"},
                ],
            }
        ]
    )
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 700
    update.effective_message.text = "/model"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=900))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.list_models.assert_awaited_once_with(include_hidden=False, limit=20)
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()

    pending = state.pending_command_wrappers[700]
    assert pending.command_name == "model"
    assert pending.tool_name == "codex"
    assert pending.thread_id == "tid-1"
    assert pending.current_step == "select_model"
    assert any(option.action == "set_model" for option in pending.options)
    assert not any(option.action == "set_effort" for option in pending.options)
    assert any(option.action == "next_effort" for option in pending.options)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["codex"])
async def test_slash_router_wraps_bare_review_in_thread(tool: str):
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool=tool)
    ws = state.storage.workspaces[f"{tool}:onlineWorker"]
    thread_id = "tid-1" if tool == "codex" else "ses-1"
    ws.threads[thread_id] = ThreadInfo(thread_id=thread_id, topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter(tool, adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 710
    update.effective_message.text = "/review"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=910))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()

    pending = state.pending_command_wrappers[710]
    assert pending.command_name == "review"
    assert pending.tool_name == tool
    assert pending.thread_id == thread_id
    assert pending.awaiting_text is True
    assert pending.current_step == "await_text"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["codex"])
async def test_slash_router_passes_review_with_args_through(tool: str):
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool=tool)
    ws = state.storage.workspaces[f"{tool}:onlineWorker"]
    thread_id = "tid-1" if tool == "codex" else "ses-1"
    ws.threads[thread_id] = ThreadInfo(thread_id=thread_id, topic_id=100, archived=False)

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter(tool, adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 711
    update.effective_message.text = "/review HEAD~1"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with(f"{tool}:onlineWorker", thread_id)
    adapter.send_user_message.assert_awaited_once_with(
        f"{tool}:onlineWorker",
        thread_id,
        "/review HEAD~1",
    )
    ctx.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_slash_router_passes_permissions_through_without_opening_wrapper():
    from bot.handlers.slash import make_slash_command_handler

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
    update.effective_message.message_id = 703
    update.effective_message.text = "/permissions"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    assert 703 not in state.pending_command_wrappers
    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "/permissions")
    ctx.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_slash_router_rejects_thread_command_in_workspace_topic():
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 503
    update.effective_message.text = "/model"
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    ctx.bot.send_message.assert_awaited()
    sent_text = ctx.bot.send_message.await_args.kwargs["text"]
    assert "/model" in sent_text
    assert "thread topic" in sent_text.lower()


@pytest.mark.asyncio
async def test_slash_router_handles_help_locally_in_thread_topic():
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(
        thread_id="tid-1",
        topic_id=100,
        archived=False,
        preview="existing preview",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 504
    update.effective_message.text = "/help"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()
    sent_text = ctx.bot.send_message.await_args.kwargs["text"]
    assert "Thread Topic 命令" in sent_text


@pytest.mark.asyncio
async def test_slash_router_local_help_does_not_mutate_immutable_message():
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(
        thread_id="tid-1",
        topic_id=100,
        archived=False,
        preview="existing preview",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    class ImmutableMessage:
        def __init__(self):
            object.__setattr__(self, "_text", "/help")
            object.__setattr__(self, "caption", None)
            object.__setattr__(self, "photo", None)
            object.__setattr__(self, "message_id", 505)
            object.__setattr__(self, "message_thread_id", 100)

        @property
        def text(self):
            return self._text

        def __setattr__(self, name, value):
            if name == "text":
                raise AttributeError("Attribute `text` of class `Message` can't be set!")
            object.__setattr__(self, name, value)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = ImmutableMessage()

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()
    sent_text = ctx.bot.send_message.await_args.kwargs["text"]
    assert "Thread Topic 命令" in sent_text


@pytest.mark.asyncio
async def test_slash_router_resolves_registered_telegram_alias_to_original_command(tmp_path, monkeypatch):
    from bot.handlers.slash import make_slash_command_handler

    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    (data_dir / "command_registry.json").write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "id": "skill:gsd-fast",
                        "name": "gsd-fast",
                        "telegramName": "gsd_fast",
                        "source": "skill",
                        "backend": "both",
                        "scope": "thread",
                        "description": "fast path",
                        "enabledForTelegram": True,
                        "publishedToTelegram": True,
                        "status": "active",
                    }
                ],
                "lastRefreshedEpoch": 1,
                "lastPublishedEpoch": 1,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("config._data_dir", str(data_dir), raising=False)

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(
        thread_id="tid-1",
        topic_id=100,
        archived=False,
        preview="existing preview",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 505
    update.effective_message.text = "/gsd_fast"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.resume_thread.assert_awaited_once_with("codex:onlineWorker", "tid-1")
    adapter.send_user_message.assert_awaited_once_with("codex:onlineWorker", "tid-1", "/gsd-fast")
    ctx.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_slash_router_routes_workspace_fallback_command_from_thread_topic(monkeypatch):
    from bot.handlers import slash as slash_module

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["tid-1"] = ThreadInfo(thread_id="tid-1", topic_id=100, archived=False)

    called = []

    async def fake_list_handler(update, context):
        called.append(list(context.args or []))

    monkeypatch.setattr(
        slash_module,
        "make_list_thread_handler",
        lambda state, group_chat_id: fake_list_handler,
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 505
    update.effective_message.text = "/list"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = slash_module.make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    assert called == [[]]
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
