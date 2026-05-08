import asyncio
import logging
import os
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from config import Config, ToolConfig
from core.lifecycle import LifecycleManager
from plugins.providers.builtin.codex.python.process import AppServerProcess
from plugins.providers.builtin.codex.python import runtime as codex_runtime
from plugins.providers.builtin.claude.python import runtime as claude_runtime
from core.state import AppState, StreamingTurn
from plugins.providers.builtin.codex.python import runtime_state as codex_state
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo


class _FakeStream:
    def __init__(self, *, lines=None, read_data=b"", on_eof=None):
        self._lines = list(lines or [])
        self._read_data = read_data
        self._on_eof = on_eof

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        if self._on_eof is not None:
            self._on_eof()
        return b""

    async def read(self):
        return self._read_data


class _FakeProcess:
    def __init__(self, *, stdout_lines=None, stderr_data=b"", wait_code=1):
        self.returncode = None
        self._wait_code = wait_code
        self.stdout = _FakeStream(lines=stdout_lines, on_eof=self._mark_exited)
        self.stderr = _FakeStream(read_data=stderr_data)

    async def wait(self):
        self.returncode = self._wait_code
        return self._wait_code

    def _mark_exited(self):
        if self.returncode is None:
            self.returncode = self._wait_code


def _fake_create_task(coro, name=None):
    coro.close()
    return MagicMock()


@pytest.mark.asyncio
async def test_post_init_starts_codex_and_overlay_provider_concurrently():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            ),
            ToolConfig(
                name="overlay-tool",
                enabled=True,
                codex_bin="overlay-tool",
                app_server_port=4096,
                protocol="http",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    call_order = []

    async def fake_start_codex(self, bot, tool_cfg):
        call_order.append("codex:start")
        await asyncio.sleep(0)
        call_order.append("codex:end")

    async def fake_start_overlay_tool(self, bot, tool_cfg):
        call_order.append("overlay-tool:start")
        await asyncio.sleep(0)
        call_order.append("overlay-tool:end")

    def fake_get_provider(name):
        if name == "codex":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=codex_runtime.start_runtime),
            )
        if name == "overlay-tool":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=fake_start_overlay_tool),
            )
        return None

    with patch("core.lifecycle.save_storage"), patch(
        "plugins.providers.builtin.codex.python.runtime.start_runtime",
        new=fake_start_codex,
    ), patch(
        "core.lifecycle.get_provider",
        side_effect=fake_get_provider,
    ), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    assert set(call_order[:2]) == {"codex:start", "overlay-tool:start"}
    assert call_order.index("codex:start") < call_order.index("overlay-tool:end")
    assert call_order.index("overlay-tool:start") < call_order.index("codex:end")


@pytest.mark.asyncio
async def test_post_init_continues_starting_overlay_provider_when_codex_startup_fails():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            ),
            ToolConfig(
                name="overlay-tool",
                enabled=True,
                codex_bin="overlay-tool",
                app_server_port=4096,
                protocol="http",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    overlay_started = AsyncMock()

    async def failing_start_codex(self, bot, tool_cfg):
        raise RuntimeError("codex boom")

    def fake_get_provider(name):
        if name == "codex":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=codex_runtime.start_runtime),
            )
        if name == "overlay-tool":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=overlay_started),
            )
        return None

    with patch("core.lifecycle.save_storage"), patch(
        "plugins.providers.builtin.codex.python.runtime.start_runtime",
        new=failing_start_codex,
    ), patch(
        "core.lifecycle.get_provider",
        side_effect=fake_get_provider,
    ), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    overlay_started.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_init_only_autostarts_managed_providers():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                managed=True,
                autostart=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            ),
            ToolConfig(
                name="overlay-tool",
                enabled=True,
                managed=True,
                autostart=False,
                codex_bin="overlay-tool",
                app_server_port=4096,
                protocol="http",
            ),
            ToolConfig(
                name="claude",
                enabled=False,
                managed=False,
                autostart=False,
                codex_bin="claude",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(
        side_effect=[
            SimpleNamespace(message_thread_id=3101),
            SimpleNamespace(message_thread_id=3102),
        ]
    )
    bot.send_message = AsyncMock()

    codex_started = AsyncMock()
    overlay_started = AsyncMock()
    claude_started = AsyncMock()

    def fake_get_provider(name):
        if name == "codex":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=codex_runtime.start_runtime),
            )
        if name == "overlay-tool":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=overlay_started),
            )
        if name == "claude":
            return SimpleNamespace(
                runtime_hooks=SimpleNamespace(start=claude_runtime.start_runtime),
            )
        return None

    with patch("core.lifecycle.save_storage"), patch(
        "plugins.providers.builtin.codex.python.runtime.start_runtime",
        new=codex_started,
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.start_runtime",
        new=claude_started,
    ), patch(
        "core.lifecycle.get_provider",
        side_effect=fake_get_provider,
    ), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch.object(
        LifecycleManager,
        "_cleanup_subagent_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    codex_started.assert_awaited_once()
    overlay_started.assert_not_awaited()
    claude_started.assert_not_awaited()

    created_topic_names = [call.kwargs["name"] for call in bot.create_forum_topic.await_args_list]
    assert created_topic_names == ["codex", "overlay-tool"]


@pytest.mark.asyncio
async def test_post_init_starts_claude_when_provider_is_managed_and_enabled():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    claude_started = AsyncMock()

    with patch("core.lifecycle.save_storage"), patch(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            runtime_hooks=SimpleNamespace(start=claude_runtime.start_runtime),
        ) if name == "claude" else None,
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.start_runtime",
        new=claude_started,
    ), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch.object(
        LifecycleManager,
        "_cleanup_subagent_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    claude_started.assert_awaited_once()


@pytest.mark.asyncio
async def test_post_init_syncs_existing_claude_topics_after_startup():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    claude_started = AsyncMock()
    sync_mock = AsyncMock()

    with patch("core.lifecycle.save_storage"), patch(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            runtime_hooks=SimpleNamespace(start=claude_runtime.start_runtime),
            lifecycle_hooks=SimpleNamespace(after_startup=claude_runtime.sync_existing_topics_after_startup),
        ) if name == "claude" else None,
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.start_runtime",
        new=claude_started,
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.sync_existing_topics_after_startup",
        new=sync_mock,
    ), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch.object(
        LifecycleManager,
        "_cleanup_subagent_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    sync_mock.assert_awaited_once_with(manager, bot)


@pytest.mark.asyncio
async def test_start_claude_starts_hook_bridge_when_data_dir_available():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
            ),
        ],
        data_dir="/tmp/onlineworker-claude-test",
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)
    tool_cfg = cfg.get_tool("claude")
    assert tool_cfg is not None

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    adapter.start_hook_bridge = AsyncMock()
    adapter.refresh_auth_status = AsyncMock(return_value={"loggedIn": True})

    with patch(
        "plugins.providers.builtin.claude.python.runtime.resolve_claude_bin",
        return_value="/opt/homebrew/bin/claude",
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.ClaudeAdapter",
        return_value=adapter,
    ), patch(
        "plugins.providers.builtin.claude.python.runtime.setup_connection",
        new=AsyncMock(),
    ) as setup_mock:
        await claude_runtime.start_runtime(manager, bot=MagicMock(), tool_cfg=tool_cfg)

    adapter.connect.assert_awaited_once()
    adapter.start_hook_bridge.assert_awaited_once_with("/tmp/onlineworker-claude-test")
    adapter.refresh_auth_status.assert_awaited_once()
    setup_mock.assert_awaited_once()
    assert state.get_adapter("claude") is adapter


@pytest.mark.asyncio
async def test_setup_claude_connection_hides_stale_threads_from_authoritative_facts(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="claude",
        topic_id=4101,
        daemon_workspace_id="claude:onlineWorker",
    )
    ws.threads["ses-1"] = ThreadInfo(
        thread_id="ses-1",
        topic_id=None,
        preview="继续 phase16",
        archived=False,
        is_active=True,
    )
    ws.threads["stale-old"] = ThreadInfo(
        thread_id="stale-old",
        topic_id=None,
        preview="who are you",
        archived=False,
        is_active=True,
    )
    storage.workspaces["claude:onlineWorker"] = ws
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()

    monkeypatch.setattr(
        "plugins.providers.builtin.claude.python.runtime._sync_provider_threads_from_facts",
        lambda manager_obj, provider_name, ws_info, limit, log_prefix, source_for_new="unknown": False,
    )
    monkeypatch.setattr(
        "bot.handlers.common.list_provider_threads",
        lambda tool_name, path, limit=200: [
            {
                "id": "ses-1",
                "preview": "继续 phase16",
                "createdAt": 2000,
                "updatedAt": 2100,
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(
        "bot.handlers.common.query_provider_active_thread_ids",
        lambda tool_name, path: {"ses-1"},
        raising=False,
    )
    monkeypatch.setattr("core.lifecycle.save_storage", lambda storage_obj: None)

    await claude_runtime.setup_connection(manager, MagicMock(), adapter)

    adapter.register_workspace_cwd.assert_called_once_with(
        "claude:onlineWorker",
        "/Users/wxy/Projects/onlineWorker",
    )
    assert ws.threads["ses-1"].archived is False
    assert ws.threads["ses-1"].is_active is True
    assert "stale-old" not in ws.threads


@pytest.mark.asyncio
async def test_post_init_uses_registry_start_hook_for_custom_provider(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    custom_started = AsyncMock()
    monkeypatch.setattr(manager, "_start_custom", custom_started, raising=False)
    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(startup_method_name="_start_custom") if name == "custom" else None,
    )

    with patch("core.lifecycle.save_storage"), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch.object(
        LifecycleManager,
        "_cleanup_subagent_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    custom_started.assert_awaited_once_with(bot, cfg.get_tool("custom"))


@pytest.mark.asyncio
async def test_post_init_prefers_descriptor_runtime_start_hook(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    runtime_start = AsyncMock()
    fallback_start = AsyncMock(side_effect=AssertionError("legacy startup fallback should not run"))
    monkeypatch.setattr(manager, "_start_custom", fallback_start, raising=False)
    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            runtime_hooks=SimpleNamespace(start=runtime_start),
            startup_method_name="_start_custom",
        ) if name == "custom" else None,
    )

    with patch("core.lifecycle.save_storage"), patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch.object(
        LifecycleManager,
        "_cleanup_subagent_threads",
        new=AsyncMock(),
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    runtime_start.assert_awaited_once_with(manager, bot, cfg.get_tool("custom"))
    fallback_start.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_shutdown_uses_registry_shutdown_hook_for_custom_provider(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    custom_shutdown = AsyncMock()
    monkeypatch.setattr(manager, "_shutdown_custom", custom_shutdown, raising=False)
    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(shutdown_method_name="_shutdown_custom") if name == "custom" else None,
    )

    with patch("core.lifecycle.save_storage"):
        await manager.post_shutdown(SimpleNamespace())

    custom_shutdown.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_post_shutdown_prefers_descriptor_runtime_shutdown_hook(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    runtime_shutdown = AsyncMock()
    fallback_shutdown = AsyncMock(side_effect=AssertionError("legacy shutdown fallback should not run"))
    monkeypatch.setattr(manager, "_shutdown_custom", fallback_shutdown, raising=False)
    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            runtime_hooks=SimpleNamespace(shutdown=runtime_shutdown),
            shutdown_method_name="_shutdown_custom",
        ) if name == "custom" else None,
    )

    with patch("core.lifecycle.save_storage"):
        await manager.post_shutdown(SimpleNamespace())

    runtime_shutdown.assert_awaited_once_with(manager)
    fallback_shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_shutdown_does_not_force_codex_when_not_present(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    custom_shutdown = AsyncMock()
    codex_shutdown = AsyncMock()
    monkeypatch.setattr(manager, "_shutdown_custom", custom_shutdown, raising=False)
    monkeypatch.setattr(manager, "_shutdown_codex", codex_shutdown, raising=False)
    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(shutdown_method_name="_shutdown_custom") if name == "custom"
        else SimpleNamespace(shutdown_method_name="_shutdown_codex") if name == "codex"
        else None,
    )

    with patch("core.lifecycle.save_storage"):
        await manager.post_shutdown(SimpleNamespace())

    custom_shutdown.assert_awaited_once_with()
    codex_shutdown.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_provider_connection_uses_registry_lifecycle_hook_for_custom_provider(monkeypatch):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    adapter = MagicMock()
    custom_connected = AsyncMock()

    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            lifecycle_hooks=SimpleNamespace(
                on_connected=custom_connected,
            )
        ) if name == "custom" else None,
    )

    await manager._setup_provider_connection(
        "custom",
        bot,
        adapter,
        reason="post-init",
    )

    custom_connected.assert_awaited_once_with(
        manager,
        bot,
        adapter,
        reason="post-init",
    )


@pytest.mark.asyncio
async def test_post_init_passes_codex_stdio_protocol_to_app_server_process():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="stdio",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    proc = MagicMock()
    proc.start = AsyncMock(return_value="stdio://")
    tui_mirror_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess", return_value=proc) as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=False)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
        return_value=tui_mirror_task,
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_called_once_with(
        codex_bin="codex",
        port=4722,
        protocol="stdio",
    )
    connect_mock.assert_awaited_once_with(manager, bot, proc, "stdio://")
    assert manager.get_tui_mirror_task("codex") is tui_mirror_task
    assert codex_state.get_runtime(state).mirror_task is tui_mirror_task


@pytest.mark.asyncio
async def test_post_init_prefers_external_codex_ws_server_without_spawning_process():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                app_server_url="ws://127.0.0.1:4722",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()
    tui_sync_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
        return_value=tui_sync_task,
    ) as sync_mock, patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
    ) as mirror_mock:
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_awaited_once_with(manager, bot, None, "ws://127.0.0.1:4722")
    sync_mock.assert_called_once_with(state, bot, cfg.group_chat_id)
    mirror_mock.assert_not_called()
    assert manager.get_tui_sync_task("codex") is tui_sync_task
    assert manager.get_tui_mirror_task("codex") is None
    assert codex_state.get_runtime(state).mirror_task is None


@pytest.mark.asyncio
async def test_post_init_can_disable_codex_shared_live_sync_even_when_owner_uses_ws():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                owner_transport="ws",
                live_transport="owner_bridge",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    tui_mirror_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=True)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
    ) as sync_mock, patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
        return_value=tui_mirror_task,
    ) as mirror_mock:
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_awaited_once_with(manager, bot, None, "ws://127.0.0.1:4722")
    sync_mock.assert_not_called()
    mirror_mock.assert_called_once_with(state, bot, cfg.group_chat_id)
    assert manager.get_tui_sync_task("codex") is None
    assert manager.get_tui_mirror_task("codex") is tui_mirror_task
    assert codex_state.get_runtime(state).mirror_task is tui_mirror_task


@pytest.mark.asyncio
async def test_post_init_prefers_existing_codex_ws_service_without_spawning_process():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()
    tui_sync_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=True)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
        return_value=tui_sync_task,
    ) as sync_mock, patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
    ) as mirror_mock:
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_awaited_once_with(manager, bot, None, "ws://127.0.0.1:4722")
    sync_mock.assert_called_once_with(state, bot, cfg.group_chat_id)
    mirror_mock.assert_not_called()
    assert manager.get_tui_sync_task("codex") is tui_sync_task
    assert manager.get_tui_mirror_task("codex") is None
    assert codex_state.get_runtime(state).mirror_task is None


@pytest.mark.asyncio
async def test_post_init_in_tui_control_mode_starts_local_runtime_without_persistent_observer_adapter():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                control_mode="tui",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    tui_sync_task = MagicMock()
    tui_mirror_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=False)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
        return_value=tui_sync_task,
    ), patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
        return_value=tui_mirror_task,
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_not_awaited()
    assert state.app_server_proc is None
    assert manager.get_tui_sync_task("codex") is tui_sync_task
    assert manager.get_tui_mirror_task("codex") is tui_mirror_task
    assert codex_state.get_runtime(state).mirror_task is tui_mirror_task


@pytest.mark.asyncio
async def test_post_init_in_app_mode_cleans_stale_codex_tui_host_artifacts(tmp_path):
    from plugins.providers.builtin.codex.python.tui_host_protocol import host_socket_path, host_status_path

    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                protocol="stdio",
                control_mode="app",
            )
        ],
        data_dir=str(tmp_path),
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    socket_path = host_socket_path(str(tmp_path))
    status_path = host_status_path(str(tmp_path))
    assert socket_path is not None
    assert status_path is not None
    with open(socket_path, "w", encoding="utf-8") as f:
        f.write("stale")
    with open(status_path, "w", encoding="utf-8") as f:
        f.write("{\"online\": true}")

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    tui_mirror_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
    ) as sync_mock, patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
        return_value=tui_mirror_task,
    ) as mirror_mock:
        proc = MagicMock()
        proc.start = AsyncMock(return_value="stdio://")
        proc_cls.return_value = proc
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_called_once()
    connect_mock.assert_awaited_once_with(manager, bot, proc, "stdio://")
    sync_mock.assert_not_called()
    mirror_mock.assert_called_once_with(state, bot, cfg.group_chat_id)
    assert manager.get_tui_mirror_task("codex") is tui_mirror_task
    assert codex_state.get_runtime(state).mirror_task is tui_mirror_task
    assert not os.path.exists(socket_path)
    assert not os.path.exists(status_path)


@pytest.mark.asyncio
async def test_post_init_in_tui_control_mode_reuses_existing_server_without_persistent_observer_adapter():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                control_mode="tui",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()

    tui_sync_task = MagicMock()
    tui_mirror_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=True)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
        return_value=tui_sync_task,
    ), patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
        return_value=tui_mirror_task,
    ):
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_not_awaited()
    assert state.app_server_proc is None
    assert manager.get_tui_sync_task("codex") is tui_sync_task
    assert manager.get_tui_mirror_task("codex") is tui_mirror_task
    assert codex_state.get_runtime(state).mirror_task is tui_mirror_task


@pytest.mark.asyncio
async def test_post_init_in_hybrid_control_mode_reuses_existing_server_with_persistent_adapter():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                control_mode="hybrid",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=3169))
    bot.send_message = AsyncMock()
    tui_sync_task = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.AppServerProcess") as proc_cls, patch(
        "core.lifecycle.save_storage"
    ), patch("plugins.providers.builtin.codex.python.runtime.probe_url", new=AsyncMock(return_value=True)), patch("plugins.providers.builtin.codex.python.runtime.connect_adapter_with_retry", new=AsyncMock()) as connect_mock, patch.object(
        LifecycleManager,
        "_cleanup_archived_threads",
        new=AsyncMock(),
    ), patch(
        "plugins.providers.builtin.codex.python.tui_bridge.start_codex_tui_sync_loop",
        return_value=tui_sync_task,
    ) as sync_mock, patch(
        "plugins.providers.builtin.codex.python.tui_realtime_mirror.start_codex_tui_realtime_mirror_loop",
    ) as mirror_mock:
        await manager.post_init(SimpleNamespace(bot=bot))

    proc_cls.assert_not_called()
    connect_mock.assert_awaited_once_with(manager, bot, None, "ws://127.0.0.1:4722")
    sync_mock.assert_called_once_with(state, bot, cfg.group_chat_id)
    mirror_mock.assert_not_called()
    assert manager.get_tui_sync_task("codex") is tui_sync_task
    assert manager.get_tui_mirror_task("codex") is None


@pytest.mark.asyncio
async def test_app_server_start_surfaces_real_process_error_after_eof():
    proc = _FakeProcess(
        stdout_lines=[b"Error: Address already in use (os error 48)\n"],
        wait_code=1,
    )

    with patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        server = AppServerProcess(codex_bin="codex", port=4722)
        with pytest.raises(RuntimeError, match="Address already in use"):
            await server.start()


@pytest.mark.asyncio
async def test_app_server_start_uses_stdio_listen_mode():
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = _FakeStream(lines=[b"WARNING: diagnostic stderr\n"])

    create_subprocess = AsyncMock(return_value=proc)

    with patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_subprocess_exec",
        new=create_subprocess,
    ), patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_task",
        side_effect=_fake_create_task,
    ) as create_task_mock:
        server = AppServerProcess(codex_bin="codex", port=4722, protocol="stdio")
        assert await server.start() == "stdio://"

    create_task_mock.assert_called_once()
    assert create_subprocess.await_args.kwargs["stdin"] == asyncio.subprocess.PIPE
    assert create_subprocess.await_args.kwargs["stderr"] == asyncio.subprocess.PIPE


@pytest.mark.asyncio
async def test_app_server_start_uses_ws_listen_mode():
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = _FakeStream(
        lines=[
            b"listening on: ws://127.0.0.1:4722\n",
            b"readyz: http://127.0.0.1:4722/readyz\n",
        ]
    )
    proc.stderr = None

    create_subprocess = AsyncMock(return_value=proc)

    with patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_subprocess_exec",
        new=create_subprocess,
    ), patch(
        "plugins.providers.builtin.codex.python.process.AppServerProcess._poll_readyz",
        new=AsyncMock(),
    ):
        server = AppServerProcess(codex_bin="codex", port=4722, protocol="ws")
        assert await server.start() == "ws://127.0.0.1:4722"

    assert create_subprocess.await_args.args == (
        "codex",
        "app-server",
        "--listen",
        "ws://127.0.0.1:4722",
    )


@pytest.mark.asyncio
async def test_app_server_start_ws_drains_merged_stdout_after_ready():
    proc = MagicMock()
    proc.returncode = None
    proc.stdin = MagicMock()
    proc.stdout = _FakeStream(
        lines=[
            b"listening on: ws://127.0.0.1:4722\n",
            b"readyz: http://127.0.0.1:4722/readyz\n",
            b"diagnostic after ready\n",
        ]
    )
    proc.stderr = None

    create_subprocess = AsyncMock(return_value=proc)

    with patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_subprocess_exec",
        new=create_subprocess,
    ), patch(
        "plugins.providers.builtin.codex.python.process.asyncio.create_task",
        side_effect=_fake_create_task,
    ) as create_task_mock, patch(
        "plugins.providers.builtin.codex.python.process.AppServerProcess._poll_readyz",
        new=AsyncMock(),
    ):
        server = AppServerProcess(codex_bin="codex", port=4722, protocol="ws")
        assert await server.start() == "ws://127.0.0.1:4722"

    create_task_mock.assert_called_once()
    assert create_task_mock.call_args.kwargs["name"] == "app-server-stdout"


@pytest.mark.asyncio
async def test_app_server_diagnostics_snapshot_tracks_recent_output_lines():
    server = AppServerProcess(codex_bin="codex", port=4722, protocol="ws")
    server._proc = MagicMock(pid=12345, returncode=None)
    server.ws_url = "ws://127.0.0.1:4722"
    server.readyz_url = "http://127.0.0.1:4722/readyz"

    await server._drain_stream(
        _FakeStream(
            lines=[
                b"first diagnostic line\n",
                b"second diagnostic line\n",
            ]
        )
    )

    snapshot = server.diagnostics_snapshot()
    assert "pid=12345" in snapshot
    assert "running=True" in snapshot
    assert "first diagnostic line" in snapshot
    assert "second diagnostic line" in snapshot


@pytest.mark.asyncio
async def test_connect_adapter_with_retry_logs_process_snapshot_on_disconnect(caplog):
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    disconnect_callback = None

    def _capture_disconnect(cb):
        nonlocal disconnect_callback
        disconnect_callback = cb

    adapter.on_disconnect.side_effect = _capture_disconnect

    proc = MagicMock()
    proc.diagnostics_snapshot.return_value = "pid=12345 running=True recent_output=[fatal reset]"

    with patch("plugins.providers.builtin.codex.python.runtime.CodexAdapter", return_value=adapter), patch("plugins.providers.builtin.codex.python.runtime.setup_adapter_connection", new=AsyncMock(),), patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.create_task",
        side_effect=_fake_create_task,
    ), patch("plugins.providers.builtin.codex.python.runtime.schedule_reconnect", return_value=True) as schedule_mock:
        await codex_runtime.connect_adapter_with_retry(manager, bot=MagicMock(), proc=proc, ws_url="ws://127.0.0.1:4722")
        assert disconnect_callback is not None
        with caplog.at_level(logging.WARNING):
            disconnect_callback()

    assert "app-server 连接断开，准备重连" in caplog.text
    assert "fatal reset" in caplog.text
    schedule_mock.assert_called_once()


@pytest.mark.asyncio
async def test_schedule_codex_reconnect_is_single_flight():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        task = MagicMock()
        task.done.return_value = False
        return task

    with patch("plugins.providers.builtin.codex.python.runtime.asyncio.get_event_loop") as get_loop:
        get_loop.return_value.create_task.side_effect = fake_create_task
        first = codex_runtime.schedule_reconnect(manager, MagicMock(), None, "ws://127.0.0.1:4722")
        second = codex_runtime.schedule_reconnect(manager, MagicMock(), None, "ws://127.0.0.1:4722")

    assert first is True
    assert second is False
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_codex_reconnect_loop_routes_notifications_to_codex_global_topic_when_active_workspace_is_other_tool():
    storage = AppStorage()
    storage.global_topic_ids = {"codex": 11, "customprovider": 22}
    storage.workspaces["codex:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=101,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["customprovider:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        topic_id=202,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    storage.active_workspace = "customprovider:onlineWorker"

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    adapter.on_disconnect = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.CodexAdapter", return_value=adapter), patch("plugins.providers.builtin.codex.python.runtime.setup_adapter_connection", new=AsyncMock(),), patch(
        "bot.handlers.common._send_to_group",
        new=AsyncMock(),
    ) as send_mock, patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.sleep",
        new=AsyncMock(),
    ):
        await codex_runtime.reconnect_loop(manager, MagicMock(), None, "ws://127.0.0.1:4722")

    assert [call.kwargs["topic_id"] for call in send_mock.await_args_list] == [11, 11]


@pytest.mark.asyncio
async def test_codex_reconnect_loop_prefers_active_codex_workspace_topic():
    storage = AppStorage()
    storage.global_topic_ids = {"codex": 11, "customprovider": 22}
    storage.workspaces["codex:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        topic_id=101,
        daemon_workspace_id="codex:onlineWorker",
    )
    storage.workspaces["customprovider:onlineWorker"] = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        topic_id=202,
        daemon_workspace_id="customprovider:onlineWorker",
    )
    storage.active_workspace = "codex:onlineWorker"

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    adapter.on_disconnect = MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.CodexAdapter", return_value=adapter), patch("plugins.providers.builtin.codex.python.runtime.setup_adapter_connection", new=AsyncMock(),), patch(
        "bot.handlers.common._send_to_group",
        new=AsyncMock(),
    ) as send_mock, patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.sleep",
        new=AsyncMock(),
    ):
        await codex_runtime.reconnect_loop(manager, MagicMock(), None, "ws://127.0.0.1:4722")

    assert [call.kwargs["topic_id"] for call in send_mock.await_args_list] == [101, 101]


@pytest.mark.asyncio
async def test_codex_reconnect_loop_uses_provider_notify_topic_hook(monkeypatch):
    storage = AppStorage()
    storage.global_topic_ids = {"codex": 11}
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.connect = AsyncMock()
    adapter.on_disconnect = MagicMock()
    resolve_notify_topic_id = MagicMock(return_value=9191)

    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            lifecycle_hooks=SimpleNamespace(
                resolve_reconnect_topic_id=resolve_notify_topic_id,
            )
        ) if name == "codex" else None,
    )

    with patch("plugins.providers.builtin.codex.python.runtime.CodexAdapter", return_value=adapter), patch("plugins.providers.builtin.codex.python.runtime.setup_adapter_connection", new=AsyncMock(),), patch(
        "bot.handlers.common._send_to_group",
        new=AsyncMock(),
    ) as send_mock, patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.sleep",
        new=AsyncMock(),
    ):
        await codex_runtime.reconnect_loop(manager, MagicMock(), None, "ws://127.0.0.1:4722")

    resolve_notify_topic_id.assert_called_once_with(manager, "codex")
    assert [call.kwargs["topic_id"] for call in send_mock.await_args_list] == [9191, 9191]


@pytest.mark.asyncio
async def test_setup_codex_connection_clears_stale_streaming_state():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        buffer="stale buffer",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    adapter.resume_thread = AsyncMock(return_value={})
    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.runtime.schedule_stale_stream_recovery",
        return_value=True,
    ) as schedule_recovery_mock:
        await codex_runtime.setup_adapter_connection(manager, bot=MagicMock(), adapter=adapter)

    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()
    adapter.resume_thread.assert_not_awaited()
    schedule_recovery_mock.assert_called_once()


@pytest.mark.asyncio
async def test_prime_codex_thread_mappings_revives_stale_archived_active_thread(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="stale archived thread",
        archived=True,
        is_active=False,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter._thread_workspace_map = {}

    monkeypatch.setattr(
        "core.providers.facts.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-123"},
    )

    with patch("core.lifecycle.save_storage") as save_storage_mock:
        await codex_runtime.prime_thread_mappings(manager, adapter)

    assert adapter._thread_workspace_map["tid-123"] == "codex:onlineWorker"
    assert ws.threads["tid-123"].archived is False
    assert ws.threads["tid-123"].is_active is True
    save_storage_mock.assert_called_once_with(storage)


@pytest.mark.asyncio
async def test_cleanup_subagent_threads_archives_codex_subagents_and_deletes_topics():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-main"] = ThreadInfo(
        thread_id="tid-main",
        topic_id=4001,
        preview="主线程",
        archived=False,
        is_active=True,
    )
    ws.threads["tid-subagent-topic"] = ThreadInfo(
        thread_id="tid-subagent-topic",
        topic_id=5301,
        preview=None,
        archived=False,
        is_active=True,
    )
    ws.threads["tid-subagent-no-topic"] = ThreadInfo(
        thread_id="tid-subagent-no-topic",
        topic_id=None,
        preview=None,
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.delete_forum_topic = AsyncMock()
    bot.close_forum_topic = AsyncMock()

    with patch(
        "core.lifecycle.get_provider",
        return_value=SimpleNamespace(
            facts=SimpleNamespace(
                list_subagent_thread_ids=lambda thread_ids: {
                    "tid-subagent-topic",
                    "tid-subagent-no-topic",
                }
            )
        ),
    ), patch("core.lifecycle.save_storage") as save_storage_mock:
        await manager._cleanup_subagent_threads(bot)

    assert ws.threads["tid-main"].archived is False
    assert ws.threads["tid-main"].topic_id == 4001

    assert ws.threads["tid-subagent-topic"].archived is True
    assert ws.threads["tid-subagent-topic"].is_active is False
    assert ws.threads["tid-subagent-topic"].topic_id is None

    assert ws.threads["tid-subagent-no-topic"].archived is True
    assert ws.threads["tid-subagent-no-topic"].is_active is False
    assert ws.threads["tid-subagent-no-topic"].topic_id is None

    bot.delete_forum_topic.assert_awaited_once_with(
        chat_id=2,
        message_thread_id=5301,
    )
    bot.close_forum_topic.assert_not_called()
    save_storage_mock.assert_called_once_with(storage)


@pytest.mark.asyncio
async def test_cleanup_subagent_threads_skips_non_codex_workspaces():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        daemon_workspace_id="customprovider:onlineWorker",
    )
    ws.threads["ses-subagent-like"] = ThreadInfo(
        thread_id="ses-subagent-like",
        topic_id=5302,
        preview=None,
        archived=False,
        is_active=True,
    )
    storage.workspaces["customprovider:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="customprovider",
                enabled=True,
                codex_bin="customprovider",
                app_server_port=4096,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.delete_forum_topic = AsyncMock()

    with patch(
        "core.lifecycle.get_provider",
        return_value=SimpleNamespace(
            facts=SimpleNamespace(list_subagent_thread_ids=None)
        ),
    ) as provider_mock, patch("core.lifecycle.save_storage") as save_storage_mock:
        await manager._cleanup_subagent_threads(bot)

    provider_mock.assert_called_once_with("customprovider")
    assert ws.threads["ses-subagent-like"].archived is False
    assert ws.threads["ses-subagent-like"].topic_id == 5302
    bot.delete_forum_topic.assert_not_called()
    save_storage_mock.assert_not_called()


@pytest.mark.asyncio
async def test_cleanup_subagent_threads_uses_registry_detector_for_custom_provider(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="customWorker",
        path="/tmp/custom",
        tool="custom",
        daemon_workspace_id="custom:customWorker",
    )
    ws.threads["main-1"] = ThreadInfo(
        thread_id="main-1",
        topic_id=5303,
        preview="主线程",
        archived=False,
        is_active=True,
    )
    ws.threads["child-1"] = ThreadInfo(
        thread_id="child-1",
        topic_id=5304,
        preview=None,
        archived=False,
        is_active=True,
    )
    storage.workspaces["custom:customWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="custom",
                enabled=True,
                codex_bin="custom",
                app_server_port=7777,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.delete_forum_topic = AsyncMock()
    bot.close_forum_topic = AsyncMock()

    detector_calls: list[list[str]] = []

    def _detect_subagents(thread_ids):
        detector_calls.append(list(thread_ids))
        return {"child-1"}

    monkeypatch.setattr(
        "core.lifecycle.get_provider",
        lambda name: SimpleNamespace(
            facts=SimpleNamespace(list_subagent_thread_ids=_detect_subagents)
        ) if name == "custom" else None,
    )

    with patch("core.lifecycle.save_storage") as save_storage_mock:
        await manager._cleanup_subagent_threads(bot)

    assert detector_calls == [["main-1", "child-1"]]
    assert ws.threads["main-1"].archived is False
    assert ws.threads["child-1"].archived is True
    assert ws.threads["child-1"].is_active is False
    assert ws.threads["child-1"].topic_id is None
    bot.delete_forum_topic.assert_awaited_once_with(chat_id=2, message_thread_id=5304)
    save_storage_mock.assert_called_once_with(storage)


@pytest.mark.asyncio
async def test_ensure_thread_topics_replays_history_via_provider_defaults_for_codex():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-new"] = ThreadInfo(
        thread_id="tid-new",
        topic_id=None,
        preview=None,
        archived=False,
        is_active=False,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=6201))
    replay_mock = AsyncMock(return_value="cursor-1")

    with patch(
        "core.lifecycle.query_provider_active_thread_ids",
        return_value={"tid-new"},
    ), patch(
        "core.lifecycle.list_provider_threads",
        return_value=[{"id": "tid-new", "preview": "new preview"}],
    ), patch(
        "core.lifecycle._replay_thread_history",
        new=replay_mock,
    ), patch("core.lifecycle.save_storage"):
        await manager._ensure_thread_topics(bot, ws)

    replay_mock.assert_awaited_once()
    kwargs = replay_mock.await_args.kwargs
    assert kwargs["tool_name"] == "codex"
    assert kwargs["sessions_dir"] is None
    assert ws.threads["tid-new"].history_sync_cursor == "cursor-1"


@pytest.mark.asyncio
async def test_sync_existing_claude_topics_syncs_active_threads_with_topic(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="ncmplayerengine",
        path="/Users/wxy/Projects/ncmplayerengine",
        tool="claude",
        daemon_workspace_id="claude:ncmplayerengine",
    )
    ws.threads["ses-1"] = ThreadInfo(
        thread_id="ses-1",
        topic_id=5457,
        preview="继续 claude",
        archived=False,
        is_active=False,
        source="imported",
    )
    ws.threads["ses-archived"] = ThreadInfo(
        thread_id="ses-archived",
        topic_id=5458,
        preview="archived",
        archived=True,
        is_active=False,
        source="imported",
    )
    ws.threads["ses-no-topic"] = ThreadInfo(
        thread_id="ses-no-topic",
        topic_id=None,
        preview="no topic",
        archived=False,
        is_active=False,
        source="imported",
    )
    storage.workspaces["claude:ncmplayerengine"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="claude",
                enabled=True,
                codex_bin="claude",
                protocol="stdio",
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    monkeypatch.setattr(
        "core.providers.facts.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"ses-1", "ses-no-topic"},
    )
    sync_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "bot.handlers.workspace._sync_existing_claude_thread_history",
        sync_mock,
        raising=False,
    )
    monkeypatch.setattr("core.storage.save_storage", lambda storage_obj: None)
    monkeypatch.setattr("bot.handlers.common.save_storage", lambda storage_obj: None)

    await claude_runtime.sync_existing_topics_after_startup(manager, MagicMock())

    sync_mock.assert_awaited_once()
    kwargs = sync_mock.await_args.kwargs
    assert kwargs["topic_id"] == 5457
    assert kwargs["thread_id"] == "ses-1"
    assert kwargs["thread_info"] is ws.threads["ses-1"]
    assert kwargs["storage"] is storage


@pytest.mark.asyncio
async def test_ensure_thread_topics_revives_stale_archived_active_thread(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-stale"] = ThreadInfo(
        thread_id="tid-stale",
        topic_id=None,
        preview="继续处理phase15",
        archived=True,
        is_active=False,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.create_forum_topic = AsyncMock(return_value=SimpleNamespace(message_thread_id=6202))
    replay_mock = AsyncMock()

    monkeypatch.setattr(
        "core.lifecycle.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-stale"},
    )
    monkeypatch.setattr(
        "bot.handlers.common.save_storage",
        lambda storage_obj: None,
    )

    with patch(
        "core.lifecycle.list_provider_threads",
        return_value=[{"id": "tid-stale", "preview": "继续处理phase15"}],
    ), patch(
        "core.lifecycle._replay_thread_history",
        new=replay_mock,
    ), patch("core.lifecycle.save_storage"):
        await manager._ensure_thread_topics(bot, ws)

    bot.create_forum_topic.assert_awaited_once()
    assert ws.threads["tid-stale"].archived is False
    assert ws.threads["tid-stale"].is_active is True
    assert ws.threads["tid-stale"].topic_id == 6202
    replay_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_archived_threads_revives_stale_archived_active_thread(monkeypatch):
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-stale"] = ThreadInfo(
        thread_id="tid-stale",
        topic_id=6203,
        preview="继续处理phase15",
        archived=True,
        is_active=False,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    bot.delete_forum_topic = AsyncMock()
    bot.close_forum_topic = AsyncMock()

    monkeypatch.setattr(
        "core.lifecycle.query_provider_active_thread_ids",
        lambda tool_name, workspace_path: {"tid-stale"},
    )

    with patch("core.lifecycle.save_storage") as save_storage_mock:
        await manager._cleanup_archived_threads(bot)

    assert ws.threads["tid-stale"].archived is False
    assert ws.threads["tid-stale"].is_active is True
    assert ws.threads["tid-stale"].topic_id == 6203
    bot.delete_forum_topic.assert_not_awaited()
    bot.close_forum_topic.assert_not_awaited()
    save_storage_mock.assert_called_once_with(storage)


@pytest.mark.asyncio
async def test_setup_codex_connection_ignores_non_codex_workspaces():
    storage = AppStorage()
    codex_ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    codex_ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="codex thread",
        archived=False,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = codex_ws

    customprovider_ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="customprovider",
        daemon_workspace_id="customprovider:onlineWorker",
    )
    customprovider_ws.threads["cm-1"] = ThreadInfo(
        thread_id="cm-1",
        topic_id=3161,
        preview="customprovider thread",
        archived=False,
        is_active=True,
    )
    storage.workspaces["customprovider:onlineWorker"] = customprovider_ws

    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            ),
            ToolConfig(
                name="customprovider",
                enabled=True,
                codex_bin="customprovider",
                app_server_port=4096,
            ),
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()

    await codex_runtime.setup_adapter_connection(manager, bot=MagicMock(), adapter=adapter)

    adapter.register_workspace_cwd.assert_called_once_with(
        "codex:onlineWorker",
        "/Users/wxy/Projects/onlineWorker",
    )


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_from_history():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        buffer="当前运行态的 `codex app-server` 端口就是：",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        return_value=[
            {"role": "assistant", "text": "当前运行态的 `codex app-server` 端口就是：\n\n- `ws://127.0.0.1:4722`"}
        ],
    ):
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert "ws://127.0.0.1:4722" in kwargs["text"]
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_after_delayed_history_flush():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        buffer="任务做的进展是",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    history_results = [
        [],
        [{"role": "assistant", "text": "任务做的进展是：\n\n- ws 重连修复已进到新 App 运行态"}],
    ]

    async def _fast_sleep(_delay):
        return None

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        side_effect=history_results,
    ), patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.sleep",
        new=AsyncMock(side_effect=_fast_sleep),
    ):
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert "ws 重连修复" in kwargs["text"]
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_via_background_retry_after_long_delay():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        buffer="现在我确认到的根因是",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    history_results = (
        [[]] * 7
        + [[{"role": "assistant", "text": "现在我确认到的根因是：\n\n- 重连后只恢复了很短的窗口，导致最终回复丢失"}]]
    )

    async def _fast_sleep(_delay):
        return None

    original_create_task = asyncio.create_task
    background_tasks = []

    def _capture_create_task(coro, name=None):
        task = original_create_task(coro, name=name)
        background_tasks.append(task)
        return task

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        side_effect=history_results,
    ), patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.sleep",
        new=AsyncMock(side_effect=_fast_sleep),
    ), patch(
        "plugins.providers.builtin.codex.python.runtime.asyncio.create_task",
        side_effect=_capture_create_task,
    ):
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)
        if background_tasks:
            await asyncio.gather(*background_tasks)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert "最终回复丢失" in kwargs["text"]
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_from_task_complete_last_agent_message():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        turn_id="turn-123",
        buffer="已经回写，并且已经提交。",
    )
    run = codex_state.start_run(state,
        workspace_id="codex:onlineWorker",
        thread_id="tid-123",
        turn_id="turn-123",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_codex_turn_terminal_message",
        return_value=(
            "已经回写，并且已经提交。\n\n"
            "本次验证结果已经写回到 Phase 14 相关文档里。"
        ),
        create=True,
    ) as read_terminal_mock:
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert "Phase 14 相关文档" in kwargs["text"]
    read_terminal_mock.assert_called_once_with("tid-123", turn_id="turn-123")
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    assert run.final_reply_synced_to_tg is True
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_with_markdown_formatting():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        turn_id="turn-123",
        buffer="## 修复中",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_codex_turn_terminal_message",
        return_value="## 修复完成\n\n- Phase 21 App 侧已收口",
        create=True,
    ):
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert kwargs["parse_mode"] == "HTML"
    assert "<b>修复完成</b>" in kwargs["text"]
    assert "• Phase 21 App 侧已收口" in kwargs["text"]
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_recovers_stale_streaming_message_from_same_turn_task_complete_even_when_partial_contains_commentary():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        turn_id="turn-123",
        buffer=(
            "💭 我已经把这轮修复收口到代码、测试和 Phase 14 文档三层证据了。"
            "这轮源码侧修复已经收口，但还不能宣称 App 运行态完全闭环。"
        ),
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    final_text = (
        "这轮源码侧修复已经收口，但还不能宣称 App 运行态完全闭环。"
        "确认下来的根因很具体。"
    )

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_codex_turn_terminal_message",
        return_value=final_text,
    ) as read_terminal_mock:
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert kwargs["text"] == final_text
    read_terminal_mock.assert_called_once_with("tid-123", turn_id="turn-123")
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_setup_codex_connection_marks_stale_streaming_message_as_incomplete_when_turn_aborted():
    storage = AppStorage()
    ws = WorkspaceInfo(
        name="onlineWorker",
        path="/Users/wxy/Projects/onlineWorker",
        tool="codex",
        daemon_workspace_id="codex:onlineWorker",
    )
    ws.threads["tid-123"] = ThreadInfo(
        thread_id="tid-123",
        topic_id=3794,
        preview="ping from test",
        archived=False,
        streaming_msg_id=3820,
        is_active=True,
    )
    storage.workspaces["codex:onlineWorker"] = ws

    state = AppState(storage=storage)
    state.streaming_turns["tid-123"] = StreamingTurn(
        message_id=3822,
        topic_id=3794,
        turn_id="turn-123",
        buffer="我先查一下仓库里 `/model` 这条指令现在有没有真正接到 bot。",
    )

    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    adapter = MagicMock()
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()
    adapter.register_workspace_cwd = MagicMock()
    bot = MagicMock()
    bot.edit_message_text = AsyncMock()

    with patch("core.lifecycle.save_storage") as save_storage_mock, patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_thread_history",
        return_value=[],
    ), patch(
        "plugins.providers.builtin.codex.python.storage_runtime.read_codex_turn_terminal_outcome",
        return_value={"status": "aborted", "text": "", "reason": "interrupted"},
        create=True,
    ) as read_outcome_mock:
        await codex_runtime.setup_adapter_connection(manager, bot=bot, adapter=adapter)

    bot.edit_message_text.assert_awaited_once()
    kwargs = bot.edit_message_text.await_args.kwargs
    assert kwargs["chat_id"] == 2
    assert kwargs["message_id"] == 3822
    assert "以上内容不完整" in kwargs["text"]
    assert "已中断" in kwargs["text"]
    read_outcome_mock.assert_called_once_with("tid-123", turn_id="turn-123")
    assert ws.threads["tid-123"].streaming_msg_id is None
    assert "tid-123" not in state.streaming_turns
    save_storage_mock.assert_called()


@pytest.mark.asyncio
async def test_codex_disconnect_callback_only_starts_one_reconnect_loop():
    storage = AppStorage()
    state = AppState(storage=storage)
    cfg = Config(
        telegram_token="token",
        allowed_user_id=1,
        group_chat_id=2,
        log_level="INFO",
        tools=[
            ToolConfig(
                name="codex",
                enabled=True,
                codex_bin="codex",
                app_server_port=4722,
                protocol="ws",
                app_server_url="ws://127.0.0.1:4722",
            )
        ],
        delete_archived_topics=True,
    )
    manager = LifecycleManager(state, storage, cfg.group_chat_id, cfg)

    bot = MagicMock()
    adapter = MagicMock()
    adapter.connect = AsyncMock()
    disconnect_callbacks: list = []

    def _capture_disconnect(cb):
        disconnect_callbacks.append(cb)

    adapter.on_disconnect = _capture_disconnect
    adapter.on_event = MagicMock()
    adapter.on_server_request = MagicMock()

    created_tasks = []

    def _record_create_task(coro):
        created_tasks.append(coro)
        return MagicMock()

    with patch("plugins.providers.builtin.codex.python.runtime.CodexAdapter", return_value=adapter), patch("plugins.providers.builtin.codex.python.runtime.setup_adapter_connection", new=AsyncMock(),), patch("plugins.providers.builtin.codex.python.runtime.asyncio.get_event_loop") as get_loop:
        loop = MagicMock()
        loop.create_task.side_effect = _record_create_task
        get_loop.return_value = loop

        await codex_runtime.connect_adapter_with_retry(manager, bot, None, "ws://127.0.0.1:4722")
        assert len(disconnect_callbacks) == 1

        disconnect_callbacks[0]()
        disconnect_callbacks[0]()

    assert len(created_tasks) == 1

    for coro in created_tasks:
        coro.close()
