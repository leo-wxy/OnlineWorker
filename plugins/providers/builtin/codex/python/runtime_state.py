from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from core.provider_runtime_state import ProviderInterruptionState, ProviderRunState, ProviderRuntimeState

logger = logging.getLogger(__name__)

TOOL_NAME = "codex"


def get_runtime(state) -> ProviderRuntimeState:
    return state.get_provider_runtime(TOOL_NAME)


def get_hook_bridge(state):
    return get_runtime(state).hook_bridge


def set_hook_bridge(state, bridge) -> None:
    get_runtime(state).hook_bridge = bridge


def get_owner_bridge(state):
    return get_runtime(state).owner_bridge


def set_owner_bridge(state, bridge) -> None:
    get_runtime(state).owner_bridge = bridge


def get_tui_host(state):
    return get_runtime(state).host


def set_tui_host(state, host) -> None:
    get_runtime(state).host = host


def get_tui_host_lock(state) -> asyncio.Lock:
    return get_runtime(state).host_lock


def get_tui_thread_idle_event(state, thread_id: str) -> asyncio.Event:
    return state.get_provider_tui_thread_idle_event(TOOL_NAME, thread_id)


def mark_tui_turn_started(state, thread_id: str) -> None:
    state.mark_provider_tui_turn_started(TOOL_NAME, thread_id)


def mark_tui_turn_completed(state, thread_id: str) -> None:
    state.mark_provider_tui_turn_completed(TOOL_NAME, thread_id)


def mark_send_started(state, thread_id: str) -> float:
    return state.mark_provider_send_started(TOOL_NAME, thread_id)


def start_run(
    state,
    *,
    workspace_id: str,
    thread_id: str,
    turn_id: str,
) -> ProviderRunState:
    return state.start_provider_run(
        TOOL_NAME,
        workspace_id=workspace_id,
        thread_id=thread_id,
        turn_id=turn_id,
    )


def get_current_run(state, thread_id: str) -> Optional[ProviderRunState]:
    return state.get_provider_current_run(TOOL_NAME, thread_id)


def mark_run(
    state,
    *,
    thread_id: str,
    status: Optional[str] = None,
    final_reply_synced_to_tg: Optional[bool] = None,
    first_progress_at: Optional[bool] = None,
    session_tab_visible_at: Optional[bool] = None,
) -> Optional[ProviderRunState]:
    return state.mark_provider_run(
        TOOL_NAME,
        thread_id=thread_id,
        status=status,
        final_reply_synced_to_tg=final_reply_synced_to_tg,
        first_progress_at=first_progress_at,
        session_tab_visible_at=session_tab_visible_at,
    )


def add_interruption(
    state,
    *,
    thread_id: str,
    interruption_id: str,
) -> Optional[ProviderInterruptionState]:
    return state.add_provider_interruption(
        TOOL_NAME,
        thread_id=thread_id,
        interruption_id=interruption_id,
    )


def resolve_interruption(
    state,
    interruption_id: str,
    *,
    status: str,
    tg_message_id: Optional[int] = None,
) -> Optional[ProviderInterruptionState]:
    return state.resolve_provider_interruption(
        TOOL_NAME,
        interruption_id,
        status=status,
        tg_message_id=tg_message_id,
    )


def get_interruption(state, interruption_id: str) -> Optional[ProviderInterruptionState]:
    return get_runtime(state).interruptions.get(interruption_id)


def has_interruption(state, interruption_id: str) -> bool:
    return interruption_id in get_runtime(state).interruptions
