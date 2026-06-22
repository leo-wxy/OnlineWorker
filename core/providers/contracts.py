from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ProviderAttachment:
    kind: str
    path: str
    name: str = ""
    mime_type: str = ""
    source: str = ""


@dataclass(frozen=True)
class ProviderFactsHooks:
    scan_workspaces: Callable
    list_threads: Callable
    read_thread_history: Callable
    query_active_thread_ids: Callable
    list_sessions: Optional[Callable] = None
    query_running_thread_ids: Optional[Callable] = None
    list_subagent_thread_ids: Optional[Callable] = None
    include_state_only_thread: Optional[Callable] = None
    thread_list_is_authoritative: bool = False
    preserve_archived_threads: bool = False


@dataclass(frozen=True)
class ProviderMessageHooks:
    ensure_connected: Callable
    prepare_send: Callable
    send: Callable
    handle_local_owner: Optional[Callable] = None
    try_route_owner_bridge_send: Optional[Callable] = None
    supports_photo: bool = False
    supports_files: bool = False


@dataclass(frozen=True)
class ProviderUsageHooks:
    get_summary: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderInteractionHooks:
    build_approval_reply: Optional[Callable] = None
    reply_question: Optional[Callable] = None
    parse_approval_request: Optional[Callable] = None
    parse_question_request: Optional[Callable] = None
    handle_approval_callback: Optional[Callable] = None
    server_request_methods: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderCapabilities:
    command_wrappers: tuple[str, ...] = ()
    control_modes: tuple[str, ...] = ("app",)
    deferred_startup: bool = False


@dataclass(frozen=True)
class ProviderTransportMetadata:
    owner: str = ""
    live: str = ""
    type: str = ""
    app_server_port: int = 0
    app_server_url: str = ""


@dataclass(frozen=True)
class ProviderManifestCapabilities:
    sessions: bool = False
    send: bool = False
    approvals: bool = False
    questions: bool = False
    photos: bool = False
    files: bool = False
    usage: bool = False
    commands: bool = False
    launch_methods: bool = False
    command_wrappers: tuple[str, ...] = ()
    control_modes: tuple[str, ...] = ("app",)
    message_rewrite: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderProcessMetadata:
    cleanup_matchers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderHealthMetadata:
    url: str = ""


@dataclass(frozen=True)
class ProviderMetadata:
    id: str
    label: str
    description: str = ""
    visible: bool = True
    runtime_id: str = ""
    managed: bool = True
    autostart: bool = True
    bin: str = ""
    transport: ProviderTransportMetadata = field(default_factory=ProviderTransportMetadata)
    capabilities: ProviderManifestCapabilities = field(default_factory=ProviderManifestCapabilities)
    process: ProviderProcessMetadata = field(default_factory=ProviderProcessMetadata)
    health: ProviderHealthMetadata = field(default_factory=ProviderHealthMetadata)

    def __post_init__(self) -> None:
        if not self.runtime_id:
            object.__setattr__(self, "runtime_id", self.id)


@dataclass(frozen=True)
class ProviderConfigNormalizationResult:
    raw: dict[str, Any]
    persist: bool = False


@dataclass(frozen=True)
class ProviderDocumentNormalizationResult:
    document: dict[str, Any]
    persist: bool = False


@dataclass(frozen=True)
class ProviderCommandHooks:
    build_thread_command_wrapper: Optional[Callable] = None
    refresh_thread_command_wrapper: Optional[Callable] = None
    apply_thread_command_wrapper_selection: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderWorkspaceHooks:
    normalize_server_threads: Optional[Callable] = None
    on_workspace_opened: Optional[Callable] = None
    list_local_threads: Optional[Callable] = None
    sync_existing_thread_history: Optional[Callable] = None
    prefer_provider_thread_overview: bool = False
    thread_control_intro_extra: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderThreadHooks:
    resolve_adapter: Optional[Callable] = None
    new_imported_thread_source: Optional[Callable] = None
    validate_new_thread: Optional[Callable] = None
    activate_new_thread: Optional[Callable] = None
    archive_thread: Optional[Callable] = None
    interrupt_thread: Optional[Callable] = None
    interrupt_supported: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderLifecycleHooks:
    on_connected: Optional[Callable] = None
    resolve_reconnect_topic_id: Optional[Callable] = None
    after_startup: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderRuntimeHooks:
    start: Optional[Callable] = None
    shutdown: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderSessionEventHooks:
    parse_semantic_event: Optional[Callable] = None
    should_materialize_unbound_thread_topic: Optional[Callable] = None
    completed_agent_message_is_final_by_default: bool = True


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    facts: ProviderFactsHooks
    capabilities: ProviderCapabilities = ProviderCapabilities()
    metadata: Optional[ProviderMetadata] = None
    message_hooks: Optional[ProviderMessageHooks] = None
    usage_hooks: Optional[ProviderUsageHooks] = None
    interactions: Optional[ProviderInteractionHooks] = None
    command_hooks: Optional[ProviderCommandHooks] = None
    workspace_hooks: Optional[ProviderWorkspaceHooks] = None
    thread_hooks: Optional[ProviderThreadHooks] = None
    lifecycle_hooks: Optional[ProviderLifecycleHooks] = None
    runtime_hooks: Optional[ProviderRuntimeHooks] = None
    session_event_hooks: Optional[ProviderSessionEventHooks] = None
    startup_method_name: Optional[str] = None
    shutdown_method_name: Optional[str] = None
    status_builder: Optional[Callable] = None
