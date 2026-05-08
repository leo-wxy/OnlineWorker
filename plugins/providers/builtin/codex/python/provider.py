from __future__ import annotations

import os
from typing import Optional

from core.providers.contracts import (
    ProviderCapabilities,
    ProviderCommandHooks,
    ProviderDescriptor,
    ProviderFactsHooks,
    ProviderInteractionHooks,
    ProviderLifecycleHooks,
    ProviderManifestCapabilities,
    ProviderMessageHooks,
    ProviderMetadata,
    ProviderProcessMetadata,
    ProviderRuntimeHooks,
    ProviderSessionEventHooks,
    ProviderThreadHooks,
    ProviderTransportMetadata,
    ProviderWorkspaceHooks,
)
from plugins.providers.builtin.codex.python import runtime
from plugins.providers.builtin.codex.python import storage_runtime
from plugins.providers.builtin.codex.python.semantic_events import parse_codex_app_server_semantic_event


def _scan_workspaces(*, sessions_dir: Optional[str] = None):
    return storage_runtime.scan_codex_session_cwds(sessions_dir)


def _list_threads(workspace_path: str, limit: int = 20):
    return storage_runtime.list_codex_threads_by_cwd(workspace_path, limit=limit)


def _list_subagent_thread_ids(thread_ids: list[str]) -> set[str]:
    return storage_runtime.list_codex_subagent_thread_ids(thread_ids)


def _query_active_thread_ids(workspace_path: str):
    return storage_runtime.query_codex_active_thread_ids(workspace_path)


def _read_thread_history(thread_id: str, *, limit: int = 10, sessions_dir: Optional[str] = None):
    effective_sessions_dir = sessions_dir or os.path.expanduser("~/.codex/sessions")
    return storage_runtime.read_thread_history(
        thread_id,
        sessions_dir=effective_sessions_dir,
        limit=limit,
    )


def create_provider_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        name="codex",
        metadata=ProviderMetadata(
            id="codex",
            runtime_id="codex",
            label="Codex",
            description="OpenAI Codex CLI sessions",
            visible=True,
            managed=True,
            autostart=True,
            bin="codex",
            transport=ProviderTransportMetadata(
                owner="stdio",
                live="owner_bridge",
                type="stdio",
            ),
            capabilities=ProviderManifestCapabilities(
                sessions=True,
                send=True,
                approvals=True,
                commands=True,
                command_wrappers=("model", "review"),
                control_modes=("app", "tui", "hybrid"),
            ),
            process=ProviderProcessMetadata(
                cleanup_matchers=("codex.*app-server", "codex-aar"),
            ),
        ),
        facts=ProviderFactsHooks(
            scan_workspaces=_scan_workspaces,
            list_threads=_list_threads,
            read_thread_history=_read_thread_history,
            query_active_thread_ids=_query_active_thread_ids,
            list_subagent_thread_ids=_list_subagent_thread_ids,
        ),
        capabilities=ProviderCapabilities(
            command_wrappers=("model", "review"),
            control_modes=("app", "tui", "hybrid"),
        ),
        message_hooks=ProviderMessageHooks(
            ensure_connected=runtime.ensure_connected,
            prepare_send=runtime.prepare_send,
            send=runtime.send_message,
            handle_local_owner=runtime.handle_local_owner,
            supports_photo=False,
        ),
        interactions=ProviderInteractionHooks(
            build_approval_reply=runtime.build_approval_reply,
        ),
        command_hooks=ProviderCommandHooks(
            build_thread_command_wrapper=runtime.build_model_wrapper,
            refresh_thread_command_wrapper=runtime.refresh_model_wrapper,
            apply_thread_command_wrapper_selection=runtime.apply_model_wrapper_selection,
        ),
        workspace_hooks=ProviderWorkspaceHooks(
            normalize_server_threads=runtime.normalize_server_threads,
            list_local_threads=runtime.list_local_threads,
        ),
        thread_hooks=ProviderThreadHooks(
            resolve_adapter=runtime.resolve_thread_adapter,
            validate_new_thread=runtime.validate_new_thread,
            activate_new_thread=runtime.activate_new_thread,
            archive_thread=runtime.archive_thread,
            interrupt_thread=runtime.interrupt_thread,
        ),
        lifecycle_hooks=ProviderLifecycleHooks(
            on_connected=runtime.setup_connection,
            resolve_reconnect_topic_id=runtime.resolve_reconnect_topic_id,
        ),
        runtime_hooks=ProviderRuntimeHooks(
            start=runtime.start_runtime,
            shutdown=runtime.shutdown_runtime,
        ),
        session_event_hooks=ProviderSessionEventHooks(
            parse_semantic_event=parse_codex_app_server_semantic_event,
        ),
        status_builder=runtime.build_status_lines,
    )
