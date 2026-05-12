# core/lifecycle.py
"""
Lifecycle management: application startup, provider runtime hook dispatch, shutdown.

Extracted from main.py closures for testability and clarity.
"""
import asyncio
import logging
from typing import Optional

from telegram.ext import Application

from config import Config
from core.provider_owner_bridge import (
    ensure_provider_owner_bridge_started,
    stop_provider_owner_bridge,
)
from core.providers.registry import get_provider
from core.providers.facts import list_provider_threads, query_provider_active_thread_ids
from core.state import AppState
from core.storage import (
    AppStorage, ThreadInfo, save_storage,
)
from bot.handlers.common import (
    _send_to_group,
    reconcile_workspace_threads_with_source,
)
from bot.utils import TopicNotFoundError
from bot.handlers.workspace import (
    _replay_thread_history,
)

logger = logging.getLogger(__name__)

class LifecycleManager:
    """Manages adapter connections, reconnection loops, and shutdown."""

    def __init__(
        self,
        state: AppState,
        storage: AppStorage,
        group_chat_id: int,
        cfg: Config,
    ):
        self.state = state
        self.storage = storage
        self.gid = group_chat_id
        self.cfg = cfg
        if self.state.config is None:
            self.state.config = cfg
        self._reconnect_tasks: dict[str, Optional[asyncio.Task]] = {}
        self._reconnect_inflight: set[str] = set()
        self._process_monitor_started = False
        self._tui_sync_tasks: dict[str, Optional[asyncio.Task]] = {}
        self._tui_mirror_tasks: dict[str, Optional[asyncio.Task]] = {}
        self._stale_recovery_tasks: dict[str, dict[str, asyncio.Task]] = {}

    # ------------------------------------------------------------------
    # post_init / post_shutdown (assigned to Application callbacks)
    # ------------------------------------------------------------------

    async def post_init(self, application: Application) -> None:
        bot = application.bot

        # 1. Create global Topics for each enabled tool
        for tool in self.cfg.enabled_tools:
            existing = self.state.get_global_topic_id(tool.name)
            if existing is not None:
                # 验证 topic 是否仍然存在
                try:
                    await _send_to_group(
                        bot, self.gid,
                        f"onlineWorker 已启动。\n发送 /workspace 查看和打开 workspace。",
                        topic_id=existing,
                    )
                    logger.info(f"[{tool.name}] 全局 Topic 已存在：{existing}")
                    continue
                except TopicNotFoundError:
                    logger.warning(f"[{tool.name}] 全局 Topic {existing} 已不存在，重建中…")
                    # 清掉旧 id，下面走创建流程
                    self.state.set_global_topic_id(tool.name, None)  # type: ignore[arg-type]
            try:
                topic = await bot.create_forum_topic(chat_id=self.gid, name=tool.name)
                self.state.set_global_topic_id(tool.name, topic.message_thread_id)
                save_storage(self.storage)
                logger.info(f"[{tool.name}] 全局 Topic 已创建：{topic.message_thread_id}")
                await bot.send_message(
                    chat_id=self.gid,
                    message_thread_id=topic.message_thread_id,
                    text=f"onlineWorker 已启动。\n发送 /workspace 查看和打开 workspace。",
                )
            except Exception as e:
                logger.error(f"[{tool.name}] 创建全局 Topic 失败：{e}")

        await ensure_provider_owner_bridge_started(self.state)

        # 2. Start enabled providers via registry
        startup_tasks = self._build_startup_tasks(bot)
        if startup_tasks:
            await asyncio.gather(*startup_tasks)

        # 5. Cleanup archived threads (delete/close topics for externally archived threads)
        await self._cleanup_archived_threads(bot)
        await self._cleanup_subagent_threads(bot)
        await self._run_provider_after_startup_hooks(bot)

    async def post_shutdown(self, application: Application) -> None:
        await self._cancel_reconnect_tasks()
        await self._shutdown_enabled_providers()
        await stop_provider_owner_bridge(self.state)
        try:
            save_storage(self.storage)
        except Exception as e:
            logger.warning(f"post_shutdown 保存 storage 失败：{e}")

    # ------------------------------------------------------------------
    # Provider connection setup (shared by first-connect and reconnect)
    # ------------------------------------------------------------------

    async def _run_startup_task(self, tool_name: str, startup_coro) -> None:
        """Run one tool startup task without aborting other tools on failure."""
        try:
            await startup_coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"{tool_name} 启动失败：{e}，继续初始化其他工具", exc_info=True)

    def _build_startup_tasks(self, bot) -> list[asyncio.Task]:
        tasks: list[asyncio.Task] = []
        for tool_cfg in self.cfg.enabled_tools:
            if not getattr(tool_cfg, "autostart", True):
                logger.info("%s 已托管，但 autostart=false，跳过启动", tool_cfg.name)
                continue

            descriptor = get_provider(tool_cfg.name)
            runtime_hooks = getattr(descriptor, "runtime_hooks", None) if descriptor is not None else None
            startup_callable = (
                getattr(runtime_hooks, "start", None)
                if runtime_hooks is not None
                else None
            )
            startup_method_name = (
                getattr(descriptor, "startup_method_name", None)
                if descriptor is not None
                else None
            )
            startup_method = (
                startup_callable
                if callable(startup_callable)
                else getattr(self, startup_method_name, None) if startup_method_name else None
            )
            if startup_method is None:
                logger.info("%s 未注册启动 hook，跳过运行时启动", tool_cfg.name)
                continue
            startup_coro = (
                startup_method(self, bot, tool_cfg)
                if startup_method is startup_callable
                else startup_method(bot, tool_cfg)
            )

            tasks.append(
                asyncio.create_task(
                    self._run_startup_task(tool_cfg.name, startup_coro),
                    name=f"startup-{tool_cfg.name}",
                )
            )
        return tasks

    def _provider_names_for_lifecycle_hooks(self) -> list[str]:
        provider_names: list[str] = []
        for tool_cfg in self.cfg.tools:
            if tool_cfg.name not in provider_names:
                provider_names.append(tool_cfg.name)
        for name in self.state.registered_adapter_names():
            if name not in provider_names:
                provider_names.append(name)
        return provider_names

    async def _run_provider_after_startup_hooks(self, bot) -> None:
        for provider_name in self._provider_names_for_lifecycle_hooks():
            descriptor = get_provider(provider_name)
            lifecycle_hooks = (
                getattr(descriptor, "lifecycle_hooks", None)
                if descriptor is not None
                else None
            )
            after_startup = (
                getattr(lifecycle_hooks, "after_startup", None)
                if lifecycle_hooks is not None
                else None
            )
            if not callable(after_startup):
                continue
            try:
                await after_startup(self, bot)
            except Exception as e:
                logger.warning("%s after_startup hook 失败：%s", provider_name, e)

    async def _shutdown_enabled_providers(self) -> None:
        for provider_name in self._provider_names_for_lifecycle_hooks():
            descriptor = get_provider(provider_name)
            runtime_hooks = getattr(descriptor, "runtime_hooks", None) if descriptor is not None else None
            shutdown_callable = (
                getattr(runtime_hooks, "shutdown", None)
                if runtime_hooks is not None
                else None
            )
            shutdown_method_name = (
                getattr(descriptor, "shutdown_method_name", None)
                if descriptor is not None
                else None
            )
            shutdown_method = (
                shutdown_callable
                if callable(shutdown_callable)
                else getattr(self, shutdown_method_name, None) if shutdown_method_name else None
            )
            if shutdown_method is None:
                continue
            try:
                if shutdown_method is shutdown_callable:
                    await shutdown_method(self)
                else:
                    await shutdown_method()
            except Exception as e:
                logger.warning("%s shutdown 失败：%s", provider_name, e)

    async def _cancel_reconnect_tasks(self) -> None:
        pending: list[asyncio.Task] = []
        for provider_name, task in list(self._reconnect_tasks.items()):
            self.set_reconnect_inflight(provider_name, False)
            self.set_reconnect_task(provider_name, None)
            if task is None or task.done():
                continue
            task.cancel()
            pending.append(task)

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _setup_provider_connection(self, provider_name: str, bot, adapter, **kwargs) -> None:
        provider = get_provider(provider_name)
        lifecycle_hooks = (
            getattr(provider, "lifecycle_hooks", None)
            if provider is not None
            else None
        )
        on_connected = (
            getattr(lifecycle_hooks, "on_connected", None)
            if lifecycle_hooks is not None
            else None
        )
        if callable(on_connected):
            await on_connected(self, bot, adapter, **kwargs)

    def _resolve_provider_reconnect_topic_id(self, provider_name: str):
        provider = get_provider(provider_name)
        lifecycle_hooks = (
            getattr(provider, "lifecycle_hooks", None)
            if provider is not None
            else None
        )
        resolve_reconnect_topic_id = (
            getattr(lifecycle_hooks, "resolve_reconnect_topic_id", None)
            if lifecycle_hooks is not None
            else None
        )
        if callable(resolve_reconnect_topic_id):
            return resolve_reconnect_topic_id(self, provider_name)
        return self.state.get_global_topic_id(provider_name)

    def get_reconnect_task(self, provider_name: str) -> Optional[asyncio.Task]:
        return self._reconnect_tasks.get(provider_name)

    def set_reconnect_task(self, provider_name: str, task: Optional[asyncio.Task]) -> None:
        if task is None:
            self._reconnect_tasks.pop(provider_name, None)
        else:
            self._reconnect_tasks[provider_name] = task

    def is_reconnect_inflight(self, provider_name: str) -> bool:
        return provider_name in self._reconnect_inflight

    def set_reconnect_inflight(self, provider_name: str, inflight: bool) -> None:
        if inflight:
            self._reconnect_inflight.add(provider_name)
        else:
            self._reconnect_inflight.discard(provider_name)

    def get_tui_sync_task(self, provider_name: str) -> Optional[asyncio.Task]:
        return self._tui_sync_tasks.get(provider_name)

    def set_tui_sync_task(self, provider_name: str, task: Optional[asyncio.Task]) -> None:
        if task is None:
            self._tui_sync_tasks.pop(provider_name, None)
        else:
            self._tui_sync_tasks[provider_name] = task

    def get_tui_mirror_task(self, provider_name: str) -> Optional[asyncio.Task]:
        return self._tui_mirror_tasks.get(provider_name)

    def set_tui_mirror_task(self, provider_name: str, task: Optional[asyncio.Task]) -> None:
        if task is None:
            self._tui_mirror_tasks.pop(provider_name, None)
        else:
            self._tui_mirror_tasks[provider_name] = task

    def get_stale_recovery_tasks(self, provider_name: str) -> dict[str, asyncio.Task]:
        return self._stale_recovery_tasks.setdefault(provider_name, {})

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _ensure_thread_topics(self, bot, ws_info) -> None:
        """Create Telegram Topics for active threads that don't have one yet.

        Follows the on-demand policy: only active (non-archived in source tool)
        threads get topics automatically. Inactive threads must be opened via
        inline button in the workspace overview.
        """
        tool_name = ws_info.tool

        # Refresh active status from source DB
        active_ids = query_provider_active_thread_ids(tool_name, ws_info.path)
        reconcile_workspace_threads_with_source(
            self.state,
            ws_info,
            active_ids=active_ids,
        )

        db_threads = list_provider_threads(tool_name, ws_info.path, limit=100)
        db_threads_map = {t["id"]: t for t in db_threads}
        for thread_id, thread_info in ws_info.threads.items():
            if thread_id in db_threads_map:
                db_preview = db_threads_map[thread_id].get("preview")
                if db_preview and not thread_info.preview:
                    thread_info.preview = db_preview
                    logger.debug(f"更新 thread {thread_id[:12]}… preview: {db_preview[:50]}")

        for thread_id, thread_info in ws_info.threads.items():
            if thread_info.topic_id is not None or thread_info.archived:
                continue
            if not thread_info.is_active:
                continue  # on-demand only
            try:
                prefix = f"[{tool_name}/{ws_info.name}] "
                body = (
                    thread_info.preview
                    if thread_info.preview
                    else f"thread-{thread_id[-8:]}"
                )
                topic_name = (prefix + body)[:128]
                topic = await bot.create_forum_topic(chat_id=self.gid, name=topic_name)
                thread_info.topic_id = topic.message_thread_id
                logger.info(
                    f"为 thread {thread_id[:12]}… 创建了 Topic {thread_info.topic_id}"
                )
                save_storage(self.storage)
                replay_cursor = await _replay_thread_history(
                    bot=bot,
                    group_chat_id=self.gid,
                    topic_id=thread_info.topic_id,
                    thread_id=thread_id,
                    sessions_dir=None,
                    tool_name=tool_name,
                )
                if replay_cursor and thread_info.history_sync_cursor != replay_cursor:
                    thread_info.history_sync_cursor = replay_cursor
                    save_storage(self.storage)
            except Exception as e:
                logger.warning(
                    f"为 thread {thread_id[:12]}… 创建 Topic 失败：{e}"
                )

    async def _cleanup_archived_threads(self, bot) -> None:
        """
        启动时清理已归档的 threads：
        1. 查询 provider 事实源，找出已归档的 thread_id
        2. 更新本地状态标记为 archived
        3. 根据配置删除或关闭对应的 Telegram topic
        """
        action = "删除" if self.cfg.delete_archived_topics else "关闭"

        cleaned_count = 0
        state_changed = False
        for ws_name, ws_info in self.storage.workspaces.items():
            tool_name = ws_info.tool

            # 查询源工具中活跃的 thread IDs
            try:
                active_ids = query_provider_active_thread_ids(tool_name, ws_info.path)
            except ValueError:
                logger.debug(f"[cleanup] 跳过未知工具：{tool_name}")
                continue

            _, repaired = reconcile_workspace_threads_with_source(
                self.state,
                ws_info,
                active_ids=active_ids,
                persist=False,
            )
            state_changed = state_changed or repaired

            # 找出在本地已有 topic 但在源工具中已归档的 threads
            for thread_id, thread_info in list(ws_info.threads.items()):
                # 跳过已经标记为 archived 的（之前通过 /archive 命令处理过）
                if thread_info.archived:
                    continue

                # 检查是否在源工具中已归档
                if thread_id not in active_ids and thread_info.topic_id:
                    logger.info(
                        f"[cleanup] 检测到外部归档的 thread：{tool_name}/{ws_name}/{thread_id[:12]}… "
                        f"topic={thread_info.topic_id}"
                    )

                    # 更新本地状态
                    thread_info.archived = True
                    thread_info.is_active = False

                    if await self._cleanup_thread_topic(
                        bot,
                        thread_info,
                        log_prefix="[cleanup]",
                    ):
                        cleaned_count += 1
                        state_changed = True

        if state_changed:
            save_storage(self.storage)
        if cleaned_count > 0:
            logger.info(f"[cleanup] 共{action}了 {cleaned_count} 个已归档 thread 的 topic")
        else:
            logger.info("[cleanup] 无需清理已归档的 topics")

    async def _cleanup_thread_topic(self, bot, thread_info: ThreadInfo, *, log_prefix: str) -> bool:
        """按配置删除或关闭 thread 对应的 Telegram topic。"""
        if thread_info.topic_id is None:
            return False

        delete_topics = self.cfg.delete_archived_topics
        action = "删除" if delete_topics else "关闭"
        topic_id = thread_info.topic_id

        try:
            if delete_topics:
                await bot.delete_forum_topic(
                    chat_id=self.gid,
                    message_thread_id=topic_id,
                )
                thread_info.topic_id = None
            else:
                await bot.close_forum_topic(
                    chat_id=self.gid,
                    message_thread_id=topic_id,
                )
            logger.info(f"{log_prefix} 已{action} topic {topic_id}")
            return True
        except Exception as e:
            logger.warning(f"{log_prefix} {action} topic {topic_id} 失败：{e}")
            return False

    async def _cleanup_subagent_threads(self, bot) -> None:
        """
        启动时清理支持 subagent 探测的 provider 历史 subagent thread：
        1. 只扫描声明了 subagent detector 的 provider workspace
        2. 将 subagent thread 标记为 archived=False -> True, is_active=False
        3. 根据配置删除或关闭对应 topic
        """
        action = "删除" if self.cfg.delete_archived_topics else "关闭"
        cleaned_count = 0

        for ws_name, ws_info in self.storage.workspaces.items():
            provider = get_provider(ws_info.tool)
            facts = provider.facts if provider is not None else None
            list_subagent_thread_ids = (
                getattr(facts, "list_subagent_thread_ids", None)
                if facts is not None
                else None
            )
            if not callable(list_subagent_thread_ids):
                continue

            subagent_ids = list_subagent_thread_ids(list(ws_info.threads.keys()))
            if not subagent_ids:
                continue

            for thread_id, thread_info in ws_info.threads.items():
                if thread_id not in subagent_ids:
                    continue
                if thread_info.archived:
                    continue

                logger.info(
                    f"[subagent-cleanup] 检测到 {ws_info.tool} subagent thread："
                    f"{ws_name}/{thread_id[:12]}… topic={thread_info.topic_id}"
                )
                thread_info.archived = True
                thread_info.is_active = False

                if thread_info.topic_id is None:
                    cleaned_count += 1
                    continue

                if await self._cleanup_thread_topic(
                    bot,
                    thread_info,
                    log_prefix="[subagent-cleanup]",
                ):
                    cleaned_count += 1

        if cleaned_count > 0:
            save_storage(self.storage)
            logger.info(f"[subagent-cleanup] 共{action}了/归档了 {cleaned_count} 个 provider subagent thread")
        else:
            logger.info("[subagent-cleanup] 无需清理 provider subagent threads")
