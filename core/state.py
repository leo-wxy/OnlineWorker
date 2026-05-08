# core/state.py
import asyncio
import logging
from dataclasses import dataclass, field
import time
from types import SimpleNamespace
from typing import Any, Optional
from core.providers.registry import get_provider
from core.provider_runtime_state import (
    ProviderInterruptionState,
    ProviderRunState,
    ProviderRuntimeState,
    ProviderWatchState,
)
from core.storage import AppStorage, WorkspaceInfo, ThreadInfo

logger = logging.getLogger(__name__)

@dataclass
class PendingConfirmation:
    """等待用户确认的消息。"""
    original_text: str
    message_id: int


@dataclass
class PendingApproval:
    """等待用户授权的沙盒权限请求。"""
    request_id: Any            # server request id（回复时用，可能是 int 或 str）
    workspace_id: str          # daemon workspace UUID
    thread_id: str             # provider thread/session id
    cmd: str                   # 要执行的命令（展示给用户）
    justification: str         # provider 给出的理由
    tool_name: str = ""        # 请求权限的工具名
    proposed_amendment: list = field(default_factory=list)   # execpolicy_amendment 前缀列表（展示用）
    # availableDecisions 里完整的 acceptWithExecpolicyAmendment dict
    # 形如：{"acceptWithExecpolicyAmendment": {"execpolicy_amendment": [...]}}
    # Allow Always 按钮需要把这整个 dict 作为 decision 发回 daemon
    amendment_decision: dict = field(default_factory=dict)
    # provider 名称，用于选择正确的 reply 格式
    tool_type: str = ""
    # 审批请求来源：app_server | hook_bridge
    approval_source: str = "app_server"


@dataclass
class PendingQuestion:
    """等待用户回答的 provider question（单个 sub-question）。"""
    question_id: str           # provider question ID（如 que_xxx）
    session_id: str            # provider session/thread ID
    workspace_id: str          # daemon workspace UUID
    header: str                # 问题标题
    question_text: str         # 问题完整文本
    options: list              # [{label, description}, ...]
    multiple: bool = False     # 是否支持多选
    custom: bool = True        # 是否允许自定义输入（默认 True，与 question tool 一致）
    # 多选模式下已选中的 option index 集合
    selected: set = field(default_factory=set)
    # 自定义输入等待状态
    awaiting_text: bool = False  # True 时 message handler 截获文字回复
    # 所属的 question group（多 sub-question 时共享）
    group: "PendingQuestionGroup | None" = None
    # 该 sub-question 在 group 中的索引
    sub_index: int = 0
    # 此 sub-question 的答案（已回答则非 None）
    answer: "list[str] | None" = None
    # TG 消息发送的 topic_id（用于 awaiting_text 时匹配 topic）
    topic_id: int | None = None
    # callback_data 中的时间戳（用于匹配）
    cb_ts: int = 0
    # provider 名称，避免上层写死具体实现
    tool_name: str = ""


@dataclass
class PendingQuestionGroup:
    """管理同一个 question_id 下的多个 sub-question。"""
    question_id: str           # provider question ID
    session_id: str
    workspace_id: str
    total: int                 # sub-question 总数
    # sub_index → TG msg_id 映射
    msg_ids: dict[int, int] = field(default_factory=dict)
    # sub_index → 已收集的答案
    answers: dict[int, list[str]] = field(default_factory=dict)

    @property
    def all_answered(self) -> bool:
        return len(self.answers) == self.total

    def collect_answers(self) -> list[list[str]]:
        """按 sub_index 顺序返回所有答案。"""
        return [self.answers.get(i, []) for i in range(self.total)]


@dataclass
class PendingCommandWrapperOption:
    """等待用户选择的通用命令 wrapper 选项。"""
    label: str
    value: str
    action: str
    description: str = ""


@dataclass
class PendingCommandWrapper:
    """等待用户在 TG 中继续操作的命令 wrapper。"""
    command_name: str
    workspace_id: str
    thread_id: str
    topic_id: int | None
    tool_name: str
    prompt_text: str
    interaction_type: str = "enum"
    options: list[PendingCommandWrapperOption] = field(default_factory=list)
    current_step: str = ""
    awaiting_text: bool = False
    text_value: str | None = None
    panel_message_id: int | None = None
    current_model: str | None = None
    current_effort: str | None = None
    selected_model: str | None = None
    selected_effort: str | None = None
    model_options: list[PendingCommandWrapperOption] = field(default_factory=list)
    effort_options: list[PendingCommandWrapperOption] = field(default_factory=list)


@dataclass
class StreamingTurn:
    """正在流式输出的 turn 状态。"""
    message_id: int            # 当前承载内容的 telegram message_id（初始为占位消息，第一个 delta 后切换为新消息）
    topic_id: int              # 所在 topic
    turn_id: Optional[str] = None  # 当前运行中的 turn id（用于新消息到达时中断旧 turn）
    buffer: str = ""           # 累积的文本 buffer
    last_edit_time: float = 0  # 上次 edit 的时间戳（time.monotonic()）
    throttle_task: Optional[asyncio.Task] = None  # asyncio.Task（延迟 edit 任务）
    completed: bool = False    # 是否已收到 turn/completed
    placeholder_deleted: bool = False  # 占位消息是否已删除并切换为新消息
    # 按 item_id 收集已完成的 shell 命令摘要（用于 turn 结束时的总结）
    shell_summaries: list = field(default_factory=list)


def _new_set_event() -> asyncio.Event:
    event = asyncio.Event()
    event.set()
    return event


@dataclass
class AppState:
    """全局应用状态（运行时，不持久化）。"""
    storage: Optional[AppStorage] = None
    app_server_proc: Any = None
    pending_confirmation: Optional[PendingConfirmation] = None
    provider_runtime_state: dict[str, ProviderRuntimeState] = field(default_factory=dict)
    # key: telegram message_id（按钮消息的 message_id）→ PendingApproval
    pending_approvals: dict[int, PendingApproval] = field(default_factory=dict)
    # key: telegram message_id → PendingQuestion
    pending_questions: dict[int, PendingQuestion] = field(default_factory=dict)
    # key: wrapper_id（通常复用触发命令的 telegram message_id）→ PendingCommandWrapper
    pending_command_wrappers: dict[int, PendingCommandWrapper] = field(default_factory=dict)
    # key: question_id → PendingQuestionGroup（多 sub-question 共享）
    pending_question_groups: dict[str, PendingQuestionGroup] = field(default_factory=dict)
    # key: thread_id → StreamingTurn（正在流式输出的 turn）
    streaming_turns: dict[str, StreamingTurn] = field(default_factory=dict)
    # key: thread_id → 最近一次触发该 turn 的 Telegram 用户消息 ID
    thread_last_tg_user_message_ids: dict[str, int] = field(default_factory=dict)
    # 多工具 adapter：tool_name → adapter 实例
    adapters: dict = field(default_factory=dict)
    # 多工具进程：tool_name → provider process/runtime handle
    tool_processes: dict = field(default_factory=dict)
    # 配置对象引用（用于访问 delete_archived_topics 等配置）
    config: Optional["Config"] = None

    # ------------------------------------------------------------------
    # adapter 连接状态
    # ------------------------------------------------------------------

    def get_adapter(self, tool_name: str):
        """按工具名获取 adapter，不存在返回 None。"""
        return self.adapters.get(tool_name)

    def set_adapter(self, tool_name: str, adapter) -> None:
        """设置指定工具的 adapter。"""
        if adapter is None:
            self.adapters.pop(tool_name, None)
        else:
            self.adapters[tool_name] = adapter

    def is_adapter_connected(self, tool_name: str) -> bool:
        adapter = self.get_adapter(tool_name)
        return adapter is not None and getattr(adapter, "connected", False)

    def registered_adapter_names(self) -> list[str]:
        return list(self.adapters.keys())

    def iter_adapters(self):
        return self.adapters.items()

    def get_provider_runtime(self, tool_name: str) -> ProviderRuntimeState:
        return self.provider_runtime_state.setdefault(tool_name, ProviderRuntimeState())

    def get_tool_for_workspace(self, workspace_id: str) -> Optional[str]:
        """按 storage key 或 provider 前缀解析 workspace 所属工具。"""
        if not workspace_id:
            return None
        if self.storage and workspace_id in self.storage.workspaces:
            return self.storage.workspaces[workspace_id].tool
        prefix, _, _ = workspace_id.partition(":")
        if prefix and get_provider(prefix) is not None:
            return prefix
        return None

    def get_adapter_for_workspace(self, workspace_id: str):
        """按 workspace 标识解析工具类型，返回对应 adapter。"""
        tool_name = self.get_tool_for_workspace(workspace_id)
        if tool_name is None:
            return None

        provider = get_provider(tool_name)
        thread_hooks = provider.thread_hooks if provider is not None else None
        resolve_adapter = getattr(thread_hooks, "resolve_adapter", None) if thread_hooks is not None else None
        if callable(resolve_adapter):
            ws = self.storage.workspaces.get(workspace_id) if self.storage else None
            if ws is None:
                _, _, ws_name = workspace_id.partition(":")
                ws = SimpleNamespace(
                    tool=tool_name,
                    name=ws_name or workspace_id,
                    path="",
                    daemon_workspace_id=workspace_id,
                )
            adapter = resolve_adapter(self, ws)
            if adapter is not None:
                return adapter

        return self.adapters.get(tool_name)

    def any_adapter_connected(self) -> bool:
        """是否有任何一个 adapter 处于连接状态。"""
        return any(a is not None and getattr(a, "connected", False) for a in self.adapters.values())

    # ------------------------------------------------------------------
    # 全局工具 Topic
    # ------------------------------------------------------------------

    def get_global_topic_id(self, tool: str) -> Optional[int]:
        """获取指定工具的全局 Topic ID。"""
        if not self.storage:
            return None
        return self.storage.global_topic_ids.get(tool)

    def set_global_topic_id(self, tool: str, topic_id: int) -> None:
        if self.storage:
            self.storage.global_topic_ids[tool] = topic_id

    def is_global_topic(self, topic_id: Optional[int]) -> bool:
        """判断 topic_id 是否是某个工具的全局控制台 Topic。"""
        if not self.storage or topic_id is None:
            return False
        return topic_id in self.storage.global_topic_ids.values()

    def get_tool_by_global_topic(self, topic_id: Optional[int]) -> Optional[str]:
        """根据全局 Topic ID 反查工具名，不匹配返回 None。"""
        if not self.storage or topic_id is None:
            return None
        for tool_name, tid in self.storage.global_topic_ids.items():
            if tid == topic_id:
                return tool_name
        return None

    def find_workspace_by_topic_id(self, topic_id: int) -> Optional["WorkspaceInfo"]:
        """按 workspace 管理 Topic ID 查找 workspace。"""
        if not self.storage:
            return None
        for ws in self.storage.workspaces.values():
            if ws.topic_id == topic_id:
                return ws
        return None

    # ------------------------------------------------------------------
    # 活跃 workspace
    # ------------------------------------------------------------------

    def get_active_workspace(self) -> Optional[WorkspaceInfo]:
        if not self.storage or not self.storage.active_workspace:
            return None
        return self.storage.workspaces.get(self.storage.active_workspace)

    def get_active_workspace_for_tool(self, tool: str) -> Optional[WorkspaceInfo]:
        """仅当当前 active workspace 属于指定工具时返回。"""
        ws = self.get_active_workspace()
        if ws is None or ws.tool != tool:
            return None
        return ws

    def get_active_workspace_id(self) -> Optional[str]:
        """活跃 workspace 的 daemon UUID。"""
        ws = self.get_active_workspace()
        return ws.daemon_workspace_id if ws else None

    def get_active_workspace_topic_id(self) -> Optional[int]:
        """活跃 workspace 的管理 Topic ID。"""
        ws = self.get_active_workspace()
        return ws.topic_id if ws else None

    def get_active_workspace_topic_id_for_tool(self, tool: str) -> Optional[int]:
        """仅当当前 active workspace 属于指定工具时返回其管理 Topic ID。"""
        ws = self.get_active_workspace_for_tool(tool)
        return ws.topic_id if ws else None

    # ------------------------------------------------------------------
    # 按 daemon_workspace_id 查 workspace
    # ------------------------------------------------------------------

    def find_workspace_by_daemon_id(self, daemon_workspace_id: str) -> Optional[WorkspaceInfo]:
        if not self.storage:
            return None
        for ws in self.storage.workspaces.values():
            if ws.daemon_workspace_id == daemon_workspace_id:
                return ws
        return None

    # ------------------------------------------------------------------
    # 按 Telegram topic_id 查 thread（在所有 workspace 中搜索）
    # ------------------------------------------------------------------

    def find_thread_by_id_global(self, thread_id: str) -> Optional[tuple[WorkspaceInfo, ThreadInfo]]:
        """按 thread_id 在所有 workspace 中查找，返回 (WorkspaceInfo, ThreadInfo) 或 None。"""
        if not self.storage:
            return None
        for ws in self.storage.workspaces.values():
            t = ws.threads.get(thread_id)
            if t:
                return ws, t
        return None

    def find_thread_by_topic_id(self, topic_id: int) -> Optional[tuple[WorkspaceInfo, ThreadInfo]]:
        """返回 (WorkspaceInfo, ThreadInfo) 或 None。"""
        if not self.storage:
            return None
        for ws in self.storage.workspaces.values():
            for t in ws.threads.values():
                if t.topic_id == topic_id:
                    return ws, t
        return None

    def find_thread_by_id(self, workspace: WorkspaceInfo, thread_id: str) -> Optional[ThreadInfo]:
        return workspace.threads.get(thread_id)

    # ------------------------------------------------------------------
    # provider runtime turn gate
    # ------------------------------------------------------------------

    def get_provider_tui_thread_idle_event(self, tool_name: str, thread_id: str) -> asyncio.Event:
        return self.get_provider_runtime(tool_name).thread_idle_events.setdefault(thread_id, _new_set_event())

    def mark_provider_tui_turn_started(self, tool_name: str, thread_id: str) -> None:
        runtime = self.get_provider_runtime(tool_name)
        runtime.active_threads.add(thread_id)
        runtime.thread_idle_events.setdefault(thread_id, _new_set_event()).clear()

    def mark_provider_tui_turn_completed(self, tool_name: str, thread_id: str) -> None:
        runtime = self.get_provider_runtime(tool_name)
        runtime.active_threads.discard(thread_id)
        runtime.thread_idle_events.setdefault(thread_id, _new_set_event()).set()

    # ------------------------------------------------------------------
    # provider run ledger
    # ------------------------------------------------------------------

    def mark_provider_send_started(self, tool_name: str, thread_id: str) -> float:
        runtime = self.get_provider_runtime(tool_name)
        now = time.time()
        runtime.thread_pending_send_started_at[thread_id] = now
        logger.info(
            "%s-run event=send_started thread_id=%s send_started_at=%.6f",
            tool_name,
            thread_id,
            now,
        )
        return now

    def start_provider_run(
        self,
        tool_name: str,
        *,
        workspace_id: str,
        thread_id: str,
        turn_id: str,
    ) -> ProviderRunState:
        runtime = self.get_provider_runtime(tool_name)
        now = time.time()
        run_id = str(turn_id or f"{thread_id}:{int(now * 1000)}")
        send_started_at = runtime.thread_pending_send_started_at.pop(thread_id, 0.0)
        run = ProviderRunState(
            run_id=run_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            turn_id=turn_id,
            status="started",
            last_visible_event_seq=1,
            created_at=now,
            updated_at=now,
            send_started_at=send_started_at,
            bridge_accepted_at=now,
        )
        runtime.runs[run_id] = run
        runtime.thread_current_runs[thread_id] = run_id
        logger.info(
            "%s-run event=started run_id=%s thread_id=%s workspace_id=%s "
            "turn_id=%s send_started_at=%.6f bridge_accepted_at=%.6f",
            tool_name,
            run.run_id,
            run.thread_id,
            run.workspace_id,
            run.turn_id,
            run.send_started_at,
            run.bridge_accepted_at,
        )
        return run

    def get_provider_current_run(self, tool_name: str, thread_id: str) -> Optional[ProviderRunState]:
        runtime = self.get_provider_runtime(tool_name)
        run_id = runtime.thread_current_runs.get(thread_id)
        if not run_id:
            return None
        return runtime.runs.get(run_id)

    def mark_provider_run(
        self,
        tool_name: str,
        *,
        thread_id: str,
        status: Optional[str] = None,
        final_reply_synced_to_tg: Optional[bool] = None,
        first_progress_at: Optional[bool] = None,
        session_tab_visible_at: Optional[bool] = None,
    ) -> Optional[ProviderRunState]:
        run = self.get_provider_current_run(tool_name, thread_id)
        if run is None:
            return None
        now = time.time()
        changed = False
        if status and run.status != status:
            run.status = status
            changed = True
        if status and status == "completed" and run.final_reply_at <= 0:
            run.final_reply_at = now
            changed = True
        if final_reply_synced_to_tg is not None:
            if run.final_reply_synced_to_tg != final_reply_synced_to_tg:
                run.final_reply_synced_to_tg = final_reply_synced_to_tg
                changed = True
            if final_reply_synced_to_tg and run.final_reply_at <= 0:
                run.final_reply_at = now
                changed = True
            if final_reply_synced_to_tg and run.tg_synced_at <= 0:
                run.tg_synced_at = now
                changed = True
        if first_progress_at and run.first_progress_at <= 0:
            run.first_progress_at = now
            changed = True
        if session_tab_visible_at and run.session_tab_visible_at <= 0:
            run.session_tab_visible_at = now
            changed = True
        if not changed:
            return run
        run.last_visible_event_seq += 1
        run.updated_at = now
        logger.info(
            "%s-run event=updated run_id=%s thread_id=%s workspace_id=%s "
            "status=%s final_reply_synced_to_tg=%s first_progress_at=%.6f "
            "final_reply_at=%.6f tg_synced_at=%.6f",
            tool_name,
            run.run_id,
            run.thread_id,
            run.workspace_id,
            run.status,
            run.final_reply_synced_to_tg,
            run.first_progress_at,
            run.final_reply_at,
            run.tg_synced_at,
        )
        return run

    def add_provider_interruption(
        self,
        tool_name: str,
        *,
        thread_id: str,
        interruption_id: str,
    ) -> Optional[ProviderInterruptionState]:
        runtime = self.get_provider_runtime(tool_name)
        run = self.get_provider_current_run(tool_name, thread_id)
        if run is None:
            return None
        now = time.time()
        interruption = ProviderInterruptionState(
            interruption_id=interruption_id,
            run_id=run.run_id,
            workspace_id=run.workspace_id,
            thread_id=thread_id,
            status="requested",
            created_at=now,
            updated_at=now,
        )
        runtime.interruptions[interruption_id] = interruption
        run.active_interruption_ids.add(interruption_id)
        if run.approval_requested_at <= 0:
            run.approval_requested_at = now
        run.last_visible_event_seq += 1
        run.updated_at = now
        return interruption

    def resolve_provider_interruption(
        self,
        tool_name: str,
        interruption_id: str,
        *,
        status: str,
        tg_message_id: Optional[int] = None,
    ) -> Optional[ProviderInterruptionState]:
        runtime = self.get_provider_runtime(tool_name)
        interruption = runtime.interruptions.get(interruption_id)
        if interruption is None:
            return None
        now = time.time()
        interruption.status = status
        interruption.tg_message_id = tg_message_id
        interruption.updated_at = now
        run = runtime.runs.get(interruption.run_id)
        if run is not None:
            run.active_interruption_ids.discard(interruption_id)
            if run.approval_resolved_at <= 0:
                run.approval_resolved_at = now
            run.last_visible_event_seq += 1
            run.updated_at = now
        return interruption

    # ------------------------------------------------------------------
    # 确认流程
    # ------------------------------------------------------------------

    def is_waiting_confirmation(self) -> bool:
        return self.pending_confirmation is not None

    def set_pending(self, text: str, message_id: int) -> None:
        self.pending_confirmation = PendingConfirmation(
            original_text=text,
            message_id=message_id,
        )

    def clear_pending(self) -> None:
        self.pending_confirmation = None

    # ------------------------------------------------------------------
    # question 辅助方法
    # ------------------------------------------------------------------

    def find_awaiting_text_question(self, topic_id: int) -> tuple[int, "PendingQuestion"] | None:
        """在指定 topic 中查找正在等待文字输入的 question，返回 (msg_id, pq) 或 None。"""
        for msg_id, pq in self.pending_questions.items():
            if pq.awaiting_text and pq.topic_id == topic_id:
                return msg_id, pq
        return None

    def find_awaiting_text_command_wrapper(
        self,
        topic_id: int,
    ) -> tuple[int, PendingCommandWrapper] | None:
        """在指定 topic 中查找正在等待文字输入的命令面板。"""
        for wrapper_id, pending in self.pending_command_wrappers.items():
            if pending.awaiting_text and pending.topic_id == topic_id:
                return wrapper_id, pending
        return None
