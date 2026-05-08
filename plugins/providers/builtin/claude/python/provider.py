from __future__ import annotations

from typing import Optional

from core.providers.contracts import (
    ProviderCapabilities,
    ProviderDescriptor,
    ProviderFactsHooks,
    ProviderInteractionHooks,
    ProviderLifecycleHooks,
    ProviderManifestCapabilities,
    ProviderMessageHooks,
    ProviderMetadata,
    ProviderRuntimeHooks,
    ProviderThreadHooks,
    ProviderTransportMetadata,
    ProviderWorkspaceHooks,
)
from core.providers.message_runtime import (
    ensure_default_connected,
    send_default_message,
)
from core.providers.thread_runtime import (
    activate_default_new_thread,
    archive_default_thread,
    interrupt_default_thread,
    resolve_default_thread_adapter,
)
from core.providers.workspace_runtime import default_normalize_server_threads

from plugins.providers.builtin.claude.python import runtime
from plugins.providers.builtin.claude.python import storage_runtime


def _scan_workspaces(*, sessions_dir: Optional[str] = None):
    return storage_runtime.scan_claude_session_cwds(sessions_dir=sessions_dir)


def _list_threads(workspace_path: str, limit: int = 20):
    return storage_runtime.list_claude_threads_by_cwd(workspace_path, limit=limit)


def _query_active_thread_ids(workspace_path: str):
    return storage_runtime.query_claude_active_session_ids(workspace_path)


def _read_thread_history(thread_id: str, *, limit: int = 10, sessions_dir: Optional[str] = None):
    return storage_runtime.read_claude_thread_history(
        thread_id,
        sessions_dir=sessions_dir,
        limit=limit,
    )


def create_provider_descriptor() -> ProviderDescriptor:
    return ProviderDescriptor(
        name="claude",
        metadata=ProviderMetadata(
            id="claude",
            runtime_id="claude",
            label="Claude",
            description="Anthropic Claude Code CLI sessions",
            visible=True,
            managed=False,
            autostart=False,
            bin="claude",
            transport=ProviderTransportMetadata(
                owner="stdio",
                live="stdio",
                type="stdio",
            ),
            capabilities=ProviderManifestCapabilities(
                sessions=True,
                send=True,
                approvals=True,
                questions=True,
                commands=True,
                control_modes=("app",),
            ),
        ),
        facts=ProviderFactsHooks(
            scan_workspaces=_scan_workspaces,
            list_threads=_list_threads,
            read_thread_history=_read_thread_history,
            query_active_thread_ids=_query_active_thread_ids,
        ),
        capabilities=ProviderCapabilities(
            control_modes=("app",),
        ),
        message_hooks=ProviderMessageHooks(
            ensure_connected=ensure_default_connected,
            prepare_send=runtime.prepare_send,
            send=send_default_message,
            supports_photo=False,
        ),
        interactions=ProviderInteractionHooks(
            build_approval_reply=runtime.build_approval_reply,
            reply_question=runtime.reply_question_via_adapter,
        ),
        workspace_hooks=ProviderWorkspaceHooks(
            normalize_server_threads=default_normalize_server_threads,
        ),
        thread_hooks=ProviderThreadHooks(
            resolve_adapter=resolve_default_thread_adapter,
            activate_new_thread=activate_default_new_thread,
            archive_thread=archive_default_thread,
            interrupt_thread=interrupt_default_thread,
        ),
        lifecycle_hooks=ProviderLifecycleHooks(
            on_connected=runtime.setup_connection,
            resolve_reconnect_topic_id=runtime.resolve_default_reconnect_topic_id,
            after_startup=runtime.sync_existing_topics_after_startup,
        ),
        runtime_hooks=ProviderRuntimeHooks(
            start=runtime.start_runtime,
            shutdown=runtime.shutdown_runtime,
        ),
        status_builder=runtime.build_status_lines,
    )
