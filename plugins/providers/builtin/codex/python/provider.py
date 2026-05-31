from __future__ import annotations

import os
from typing import Optional

from core.providers.contracts import (
    ProviderCommandHooks,
    ProviderDescriptor,
    ProviderFactsHooks,
    ProviderInteractionHooks,
    ProviderLifecycleHooks,
    ProviderMessageHooks,
    ProviderRuntimeHooks,
    ProviderSessionEventHooks,
    ProviderThreadHooks,
    ProviderUsageHooks,
    ProviderWorkspaceHooks,
)
from core.providers.manifest import (
    metadata_from_builtin_provider_manifest,
    runtime_capabilities_from_manifest,
)
from plugins.providers.builtin.codex.python import runtime
from plugins.providers.builtin.codex.python import storage_runtime
from plugins.providers.builtin.codex.python import interactions
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
    metadata = metadata_from_builtin_provider_manifest(__file__)
    capabilities = metadata.capabilities
    return ProviderDescriptor(
        name="codex",
        metadata=metadata,
        facts=ProviderFactsHooks(
            scan_workspaces=_scan_workspaces,
            list_threads=_list_threads,
            read_thread_history=_read_thread_history,
            query_active_thread_ids=_query_active_thread_ids,
            list_subagent_thread_ids=_list_subagent_thread_ids,
        ),
        capabilities=runtime_capabilities_from_manifest(capabilities),
        message_hooks=ProviderMessageHooks(
            ensure_connected=runtime.ensure_connected,
            prepare_send=runtime.prepare_send,
            send=runtime.send_message,
            handle_local_owner=runtime.handle_local_owner,
            try_route_owner_bridge_send=runtime.try_route_owner_bridge_send,
            supports_photo=capabilities.photos,
            supports_files=capabilities.files,
        ),
        usage_hooks=ProviderUsageHooks(
            get_summary=storage_runtime.summarize_codex_usage,
        ),
        interactions=ProviderInteractionHooks(
            build_approval_reply=runtime.build_approval_reply,
            parse_approval_request=interactions.parse_approval_request,
            parse_question_request=interactions.parse_question_request,
            server_request_methods=interactions.SERVER_REQUEST_METHODS,
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
