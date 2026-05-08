from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class ProviderFactsHooks:
    scan_workspaces: Callable
    list_threads: Callable
    read_thread_history: Callable
    query_active_thread_ids: Callable
    list_subagent_thread_ids: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderMessageHooks:
    ensure_connected: Callable
    prepare_send: Callable
    send: Callable
    handle_local_owner: Optional[Callable] = None
    supports_photo: bool = False


@dataclass(frozen=True)
class ProviderInteractionHooks:
    build_approval_reply: Optional[Callable] = None
    reply_question: Optional[Callable] = None


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
    commands: bool = False
    command_wrappers: tuple[str, ...] = ()
    control_modes: tuple[str, ...] = ("app",)


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
class ProviderCommandHooks:
    build_thread_command_wrapper: Optional[Callable] = None
    refresh_thread_command_wrapper: Optional[Callable] = None
    apply_thread_command_wrapper_selection: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderWorkspaceHooks:
    normalize_server_threads: Optional[Callable] = None
    on_workspace_opened: Optional[Callable] = None
    list_local_threads: Optional[Callable] = None


@dataclass(frozen=True)
class ProviderThreadHooks:
    resolve_adapter: Optional[Callable] = None
    validate_new_thread: Optional[Callable] = None
    activate_new_thread: Optional[Callable] = None
    archive_thread: Optional[Callable] = None
    interrupt_thread: Optional[Callable] = None


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


@dataclass(frozen=True)
class ProviderDescriptor:
    name: str
    facts: ProviderFactsHooks
    capabilities: ProviderCapabilities = ProviderCapabilities()
    metadata: Optional[ProviderMetadata] = None
    message_hooks: Optional[ProviderMessageHooks] = None
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
