from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProviderWatchState:
    """单个 provider 的实时镜像：单个 thread 的增量读取状态。"""
    workspace_id: str
    topic_id: int
    session_file: Optional[str] = None
    last_offset: int = 0
    last_commentary_text: str = ""
    last_final_text: str = ""
    turn_started_sent: bool = False
    active_until: float = 0.0
    poll_interval_seconds: float = 0.5
    next_poll_at: float = 0.0
    last_poll_at: float = 0.0
    last_activity_at: float = 0.0
    idle_polls: int = 0


@dataclass
class ProviderInterruptionState:
    """一次 provider interruption/approval 的运行时状态。"""
    interruption_id: str
    run_id: str
    workspace_id: str
    thread_id: str
    status: str = "requested"
    tg_message_id: Optional[int] = None
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class ProviderRunState:
    """一次 provider run 的运行时 ledger 条目。"""
    run_id: str
    workspace_id: str
    thread_id: str
    turn_id: str
    status: str = "started"
    active_interruption_ids: set[str] = field(default_factory=set)
    last_visible_event_seq: int = 0
    final_reply_synced_to_tg: bool = False
    created_at: float = 0.0
    updated_at: float = 0.0
    send_started_at: float = 0.0
    bridge_accepted_at: float = 0.0
    first_progress_at: float = 0.0
    approval_requested_at: float = 0.0
    approval_resolved_at: float = 0.0
    final_reply_at: float = 0.0
    tg_synced_at: float = 0.0
    session_tab_visible_at: float = 0.0


@dataclass
class ProviderRuntimeState:
    """单个 provider 的运行时容器。"""
    hook_bridge: Any = None
    owner_bridge: Any = None
    host: Any = None
    host_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mirror_task: Optional[asyncio.Task] = None
    last_diagnostics_write: float = 0.0
    last_synced_assistant: dict[str, str] = field(default_factory=dict)
    runs: dict[str, ProviderRunState] = field(default_factory=dict)
    thread_current_runs: dict[str, str] = field(default_factory=dict)
    thread_pending_send_started_at: dict[str, float] = field(default_factory=dict)
    interruptions: dict[str, ProviderInterruptionState] = field(default_factory=dict)
    watched_threads: dict[str, ProviderWatchState] = field(default_factory=dict)
    thread_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    active_threads: set[str] = field(default_factory=set)
    thread_idle_events: dict[str, asyncio.Event] = field(default_factory=dict)
