import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from config import Config, ToolConfig
from core.state import AppState
from core.storage import AppStorage, ThreadInfo, WorkspaceInfo

GROUP_CHAT_ID = -100123456789


def _build_state(
    *,
    tool: str,
    control_mode: str = "app",
    protocol: str | None = None,
    live_transport: str | None = None,
) -> AppState:
    storage = AppStorage()
    storage.global_topic_ids[tool] = 10
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
                bin=tool,
                protocol=protocol or ("stdio" if tool == "codex" else "http"),
                live_transport=live_transport or ("stdio" if tool == "codex" else "http"),
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

    adapter.resume_thread.assert_not_awaited()
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
    adapter.resume_thread.assert_not_awaited()
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
async def test_slash_router_handles_token_usage_locally_in_agent_topic(monkeypatch):
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(
        thread_id="custom-1",
        topic_id=100,
        archived=False,
        preview="existing preview",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("custom", adapter)

    calls = []

    def fake_usage_summary(plugin_id, source_id, start_date, end_date):
        calls.append((plugin_id, source_id, start_date, end_date))
        return {
            "pluginId": plugin_id,
            "sourceId": source_id,
            "startDate": start_date,
            "endDate": end_date,
            "days": [
                {
                    "date": "2026-05-28",
                    "totalTokens": 1234,
                    "inputTokens": 100,
                    "outputTokens": 200,
                    "cacheCreationTokens": 30,
                    "cacheReadTokens": 40,
                    "totalCostUsd": 0.12,
                }
            ],
        }

    monkeypatch.setattr("bot.handlers.common.get_provider_usage_source", lambda provider_id: ("ccusage", provider_id))
    monkeypatch.setattr("bot.handlers.common.get_usage_source_summary", fake_usage_summary)
    monkeypatch.setattr(
        "bot.handlers.common._token_usage_today",
        lambda: date(2026, 5, 28),
    )
    monkeypatch.setattr(
        "bot.handlers.slash.classify_provider",
        lambda name, cfg: "available" if name == "custom" else "unknown_provider",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 506
    update.effective_message.text = "/token_usage"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 10

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    assert calls == [("ccusage", "custom", "2026-05-22", "2026-05-28")]
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()
    sent = ctx.bot.send_message.await_args.kwargs
    assert sent["message_thread_id"] == 10
    assert "custom 用量" in sent["text"]
    assert "2026-05-22 ~ 2026-05-28" in sent["text"]
    assert "总 token：1,234" in sent["text"]
    assert "输入：100" in sent["text"]
    assert "输出：200" in sent["text"]
    assert "成本：$0.120000" in sent["text"]


@pytest.mark.asyncio
async def test_slash_router_rejects_token_usage_in_thread_topic(monkeypatch):
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="custom")
    ws = state.storage.workspaces["custom:onlineWorker"]
    ws.threads["custom-1"] = ThreadInfo(
        thread_id="custom-1",
        topic_id=100,
        archived=False,
        preview="existing preview",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("custom", adapter)

    usage_summary = MagicMock()
    monkeypatch.setattr("bot.handlers.common.get_provider_usage_source", lambda provider_id: ("ccusage", provider_id))
    monkeypatch.setattr("bot.handlers.common.get_usage_source_summary", usage_summary)
    monkeypatch.setattr(
        "bot.handlers.slash.classify_provider",
        lambda name, cfg: "available" if name == "custom" else "unknown_provider",
    )

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 507
    update.effective_message.text = "/token_usage"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    usage_summary.assert_not_called()
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.send_message.assert_awaited_once()
    sent = ctx.bot.send_message.await_args.kwargs
    assert sent["message_thread_id"] == 100
    assert "/token_usage" in sent["text"]
    assert "agent topic" in sent["text"].lower()


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

    adapter.resume_thread.assert_not_awaited()
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


@pytest.mark.asyncio
async def test_list_threads_excludes_inactive_codex_state_only_placeholders(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.path = "/Users/example/Projects/sample-project"
    ws.threads["app:codex:placeholder"] = ThreadInfo(
        thread_id="app:codex:placeholder",
        topic_id=None,
        preview="新建会话",
        archived=False,
        is_active=False,
        source="app",
    )
    ws.threads["draft:codex:1783173401561"] = ThreadInfo(
        thread_id="draft:codex:1783173401561",
        topic_id=None,
        preview=None,
        archived=False,
        is_active=False,
        source="app",
    )
    ws.threads["tid-real-1"] = ThreadInfo(
        thread_id="tid-real-1",
        topic_id=101,
        preview="真实会话 1",
        archived=False,
        is_active=True,
        source="provider",
    )

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, workspace_path, limit=20: [
            {"id": "tid-real-1", "preview": "真实会话 1", "createdAt": 300, "updatedAt": 300},
            {"id": "tid-real-2", "preview": "真实会话 2", "createdAt": 200, "updatedAt": 200},
            {"id": "tid-real-3", "preview": "真实会话 3", "createdAt": 100, "updatedAt": 100},
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_local_threads",
        lambda tool_name, workspace_path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.thread.reconcile_workspace_threads_with_source",
        lambda state_arg, ws_arg: ({"tid-real-1", "tid-real-2", "tid-real-3"}, False),
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_subagent_thread_ids",
        lambda tool_name, thread_ids: set(),
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=901))

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    sent = ctx.bot.send_message.await_args.kwargs["text"]
    assert "真实会话 1" in sent
    assert "真实会话 2" in sent
    assert "真实会话 3" in sent
    assert "新建会话" not in sent
    assert "1783173401561" not in sent
    reply_markup = ctx.bot.send_message.await_args.kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["✅ 真实会话 1", "📌 真实会话 2", "📌 真实会话 3"]


@pytest.mark.asyncio
async def test_list_threads_excludes_inactive_claude_state_only_placeholders(monkeypatch):
    from bot.handlers.thread import make_list_thread_handler

    state = _build_state(tool="claude")
    ws = state.storage.workspaces["claude:onlineWorker"]
    ws.path = "/Users/example/Projects/sample-project"
    ws.threads["app:claude:placeholder"] = ThreadInfo(
        thread_id="app:claude:placeholder",
        topic_id=None,
        preview="新建会话",
        archived=False,
        is_active=False,
        source="app",
    )
    ws.threads["tid-real-1"] = ThreadInfo(
        thread_id="tid-real-1",
        topic_id=101,
        preview="真实会话 1",
        archived=False,
        is_active=True,
        source="provider",
    )

    monkeypatch.setattr(
        "bot.handlers.thread.list_provider_threads",
        lambda tool_name, workspace_path, limit=20: [
            {"id": "tid-real-1", "preview": "真实会话 1", "createdAt": 300, "updatedAt": 300},
            {"id": "tid-real-2", "preview": "真实会话 2", "createdAt": 200, "updatedAt": 200},
        ],
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_local_threads",
        lambda tool_name, workspace_path, limit=20: [],
    )
    monkeypatch.setattr(
        "bot.handlers.thread.reconcile_workspace_threads_with_source",
        lambda state_arg, ws_arg: ({"tid-real-1", "tid-real-2"}, False),
    )
    monkeypatch.setattr(
        "bot.handlers.thread._list_provider_subagent_thread_ids",
        lambda tool_name, thread_ids: set(),
    )

    update = MagicMock()
    update.effective_message = MagicMock()
    update.effective_message.message_thread_id = 50

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=901))

    handler = make_list_thread_handler(state, GROUP_CHAT_ID)
    await handler(update, ctx)

    sent = ctx.bot.send_message.await_args.kwargs["text"]
    assert "真实会话 1" in sent
    assert "真实会话 2" in sent
    assert "新建会话" not in sent
    reply_markup = ctx.bot.send_message.await_args.kwargs["reply_markup"]
    button_texts = [button.text for row in reply_markup.inline_keyboard for button in row]
    assert button_texts == ["✅ 真实会话 1", "📌 真实会话 2"]


@pytest.mark.asyncio
async def test_slash_router_new_from_thread_topic_creates_separate_provider_thread(monkeypatch):
    from bot.handlers import thread as thread_module
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["current-thread"] = ThreadInfo(
        thread_id="current-thread",
        topic_id=100,
        archived=False,
        preview="current session",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "new-thread-1"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    send_thread_control_panel = AsyncMock()
    monkeypatch.setattr(
        thread_module,
        "send_thread_control_panel",
        send_thread_control_panel,
    )
    monkeypatch.setattr(thread_module, "save_storage", lambda storage: None)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 508
    update.effective_message.text = "/new Explain this project"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=200))
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=920))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.start_thread.assert_awaited_once_with("codex:onlineWorker")
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_awaited_once_with(
        "codex:onlineWorker",
        "new-thread-1",
        "Explain this project",
    )
    assert adapter.send_user_message.await_args.args[1] != "current-thread"

    ctx.bot.create_forum_topic.assert_awaited_once()
    assert ws.threads["new-thread-1"].topic_id == 200
    assert ws.threads["new-thread-1"].preview == "Explain this project"

    confirmation_topics = [
        call.kwargs.get("message_thread_id")
        for call in ctx.bot.send_message.await_args_list
        if "新 thread 已创建，请切到新 Topic 继续" in call.kwargs.get("text", "")
    ]
    assert confirmation_topics == [100]

    send_thread_control_panel.assert_awaited_once()
    panel_call = send_thread_control_panel.await_args
    assert panel_call.args[4].thread_id == "new-thread-1"
    assert panel_call.kwargs["topic_id"] == 200


@pytest.mark.asyncio
async def test_slash_router_new_from_thread_topic_creates_claude_provider_thread(monkeypatch):
    from bot.handlers import thread as thread_module
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="claude")
    ws = state.storage.workspaces["claude:onlineWorker"]
    ws.threads["current-thread"] = ThreadInfo(
        thread_id="current-thread",
        topic_id=100,
        archived=False,
        preview="current session",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "claude-new-thread-1"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("claude", adapter)

    send_thread_control_panel = AsyncMock()
    monkeypatch.setattr(
        thread_module,
        "send_thread_control_panel",
        send_thread_control_panel,
    )
    monkeypatch.setattr(thread_module, "save_storage", lambda storage: None)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 511
    update.effective_message.text = "/new Explain this project"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=200))
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=923))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.start_thread.assert_awaited_once_with("claude:onlineWorker")
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_awaited_once_with(
        "claude:onlineWorker",
        "claude-new-thread-1",
        "Explain this project",
    )
    assert adapter.send_user_message.await_args.args[1] != "current-thread"

    ctx.bot.create_forum_topic.assert_awaited_once()
    assert ws.threads["claude-new-thread-1"].topic_id == 200
    assert ws.threads["claude-new-thread-1"].preview == "Explain this project"

    send_thread_control_panel.assert_awaited_once()
    panel_call = send_thread_control_panel.await_args
    assert panel_call.args[4].thread_id == "claude-new-thread-1"
    assert panel_call.kwargs["topic_id"] == 200


@pytest.mark.asyncio
async def test_slash_router_new_without_text_rejects_codex_in_source_thread_topic(monkeypatch):
    from bot.handlers import thread as thread_module
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["current-thread"] = ThreadInfo(
        thread_id="current-thread",
        topic_id=100,
        archived=False,
        preview="current session",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "should-not-start"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    monkeypatch.setattr(thread_module, "save_storage", lambda storage: None)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 509
    update.effective_message.text = "/new"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=200))
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=921))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.create_forum_topic.assert_not_awaited()

    ctx.bot.send_message.assert_awaited_once()
    sent = ctx.bot.send_message.await_args.kwargs
    assert sent["message_thread_id"] == 100
    assert "不能创建空 thread" in sent["text"]
    assert "/new <初始消息>" in sent["text"]


@pytest.mark.asyncio
async def test_slash_router_new_without_text_rejects_claude_in_source_thread_topic(monkeypatch):
    from bot.handlers import thread as thread_module
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="claude")
    ws = state.storage.workspaces["claude:onlineWorker"]
    ws.threads["current-thread"] = ThreadInfo(
        thread_id="current-thread",
        topic_id=100,
        archived=False,
        preview="current session",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "should-not-start"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("claude", adapter)

    monkeypatch.setattr(thread_module, "save_storage", lambda storage: None)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 512
    update.effective_message.text = "/new"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=200))
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=924))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    adapter.start_thread.assert_not_awaited()
    adapter.resume_thread.assert_not_awaited()
    adapter.send_user_message.assert_not_awaited()
    ctx.bot.create_forum_topic.assert_not_awaited()

    ctx.bot.send_message.assert_awaited_once()
    sent = ctx.bot.send_message.await_args.kwargs
    assert sent["message_thread_id"] == 100
    assert "不能创建空 thread" in sent["text"]
    assert "/new <初始消息>" in sent["text"]


@pytest.mark.asyncio
async def test_slash_router_new_from_thread_topic_publishes_user_message_events(monkeypatch):
    from bot.handlers import thread as thread_module
    from bot.handlers.slash import make_slash_command_handler

    state = _build_state(tool="codex")
    ws = state.storage.workspaces["codex:onlineWorker"]
    ws.threads["current-thread"] = ThreadInfo(
        thread_id="current-thread",
        topic_id=100,
        archived=False,
        preview="current session",
    )

    adapter = MagicMock()
    adapter.connected = True
    adapter.start_thread = AsyncMock(return_value={"id": "new-thread-1"})
    adapter.resume_thread = AsyncMock(return_value={})
    adapter.send_user_message = AsyncMock(return_value={})
    state.set_adapter("codex", adapter)

    monkeypatch.setattr(thread_module, "send_thread_control_panel", AsyncMock())
    monkeypatch.setattr(thread_module, "save_storage", lambda storage: None)

    update = MagicMock()
    update.effective_user.id = 1
    update.effective_message = MagicMock()
    update.effective_message.message_id = 510
    update.effective_message.text = "/new Explain this project"
    update.effective_message.caption = None
    update.effective_message.photo = None
    update.effective_message.message_thread_id = 100

    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.create_forum_topic = AsyncMock(return_value=MagicMock(message_thread_id=200))
    ctx.bot.send_message = AsyncMock(return_value=MagicMock(message_id=922))
    ctx.args = None

    handler = make_slash_command_handler(state, GROUP_CHAT_ID, state.config)
    await handler(update, ctx)

    assert [event["kind"] for event in state.message_bus.recent_events()] == [
        "message.user.submitted",
        "message.user.accepted",
    ]
    activity = state.message_bus.session_activity("codex", "new-thread-1")
    assert activity["workspacePath"] == "/Users/example/Projects/onlineWorker"
    assert activity["lastUserMessage"] == "Explain this project"
