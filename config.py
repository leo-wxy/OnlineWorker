# config.py
import os
import sys
import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from dotenv import dotenv_values

from core.ai.config import (
    build_ai_scenario_config,
    build_ai_service_config,
    default_ai_service_raw,
    iter_ai_scenario_raws,
    iter_ai_service_raws,
    load_ai_config,
    positive_int_value,
)
from core.ai.contracts import AiConfig, AiScenarioConfig, AiServiceConfig
from core.providers.overlay import load_overlay_provider_raws, manifest_to_provider_raw

DEFAULT_CONFIG_PATH = "config.yaml"

# ---------------------------------------------------------------------------
# Data-dir support: when set, all file paths resolve relative to this dir.
# Without --data-dir, everything stays CWD-relative (backward compatible).
# ---------------------------------------------------------------------------
_data_dir: str | None = None
_dotenv_loaded: bool = False  # track whether CWD .env has been loaded
# 当前 App surface 已正式暴露 claude，运行时链路不再额外隐藏 provider。
HIDDEN_PROVIDER_IDS = frozenset()
BUILTIN_PROVIDER_PLUGIN_DIR = Path(__file__).resolve().parent / "plugins" / "providers" / "builtin"
OWNED_ENV_KEYS = frozenset(
    {
        "TELEGRAM_TOKEN",
        "ALLOWED_USER_ID",
        "GROUP_CHAT_ID",
    }
)
OWNED_ENV_PREFIXES = ("ONLINEWORKER_",)
EXCLUDED_OWNED_ENV_KEYS = frozenset(
    {
        "ONLINEWORKER_NOTIFICATION_OVERLAY",
    }
)


def _is_owned_env_key(key: str) -> bool:
    normalized = str(key or "").strip()
    if normalized in EXCLUDED_OWNED_ENV_KEYS:
        return False
    return normalized in OWNED_ENV_KEYS or normalized.startswith(OWNED_ENV_PREFIXES)


def _load_owned_env(env_path: str, *, override: bool) -> None:
    values = dotenv_values(env_path)
    for key, value in values.items():
        if not key or value is None or not _is_owned_env_key(key):
            continue
        if override or key not in os.environ:
            os.environ[key] = str(value)


def get_data_dir() -> str | None:
    """Return the data directory, or None if using CWD defaults."""
    return _data_dir


def default_data_dir() -> str:
    """Return the stable default data dir for the current platform."""
    home = Path.home()
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "OnlineWorker")
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(home / "AppData" / "Roaming")
        return str(Path(appdata) / "OnlineWorker")
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return str(Path(xdg_data_home) / "OnlineWorker")


def set_data_dir(path: str) -> None:
    """Set the data directory. Called from main.py after parsing --data-dir."""
    global _data_dir
    _data_dir = path
    os.makedirs(path, exist_ok=True)


def is_provider_exposed(name: str) -> bool:
    """当前验收窗口内是否对用户暴露该 provider。"""
    normalized = str(name or "").strip()
    return bool(normalized) and normalized not in HIDDEN_PROVIDER_IDS


@dataclass
class ToolConfig:
    """单个 CLI 工具的配置。"""
    name: str                        # 工具名，如 "codex" / "opencode"
    enabled: bool = True
    visible: bool = True
    runtime_id: str = ""
    label: str = ""
    description: str = ""
    managed: bool | None = None
    autostart: bool = True
    app_server_port: int = 0         # 0 = 动态端口（app-server 自选），>0 = 固定端口
    app_server_url: str = ""         # 若设置，优先连接外部 app-server
    codex_bin: str = "codex"         # codex 可执行文件路径（用于启动 app-server）
    protocol: str = "ws"             # 协议类型："stdio" / "ws" / "unix" / "http"
    owner_transport: str = ""        # owner 主链实际使用的 transport
    live_transport: str = ""         # live 辅助链路语义："owner_bridge" / "shared_ws" / "shared_unix" / 其他 provider 原生 transport
    control_mode: str = "app"        # 交互主控模式："app" / "tui" / "hybrid"
    capabilities: dict[str, Any] = field(default_factory=dict)
    process: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, str] = field(default_factory=dict)
    external_cli: dict[str, Any] = field(default_factory=dict)
    message_hooks: "MessageHooksConfig | None" = None

    def __post_init__(self) -> None:
        managed = self.enabled if self.managed is None else bool(self.managed)
        self.managed = managed
        # 兼容旧代码：enabled 仍代表“参与 TG/runtime 主链”
        self.enabled = managed
        self.visible = bool(self.visible)
        self.runtime_id = str(self.runtime_id or self.name).strip()
        self.label = str(self.label or self.name).strip()
        self.description = str(self.description or "").strip()
        self.autostart = bool(self.autostart) and managed
        self.codex_bin = os.path.expanduser(self.codex_bin or "codex")
        self.owner_transport = _normalize_transport_name(self.owner_transport or self.protocol or "")
        if not self.owner_transport:
            self.owner_transport = _default_owner_transport(self.name)
        self.protocol = self.owner_transport
        self.live_transport = _normalize_live_transport_name(self.live_transport or "")
        if not self.live_transport:
            self.live_transport = _default_live_transport(
                self.name,
                owner_transport=self.owner_transport,
                control_mode=self.control_mode,
            )
        self.auth = {
            str(k): str(v or "").strip()
            for k, v in (self.auth or {}).items()
            if k is not None
        }
        self.external_cli = dict(self.external_cli or {})


@dataclass
class NotificationChannelConfig:
    name: str
    enabled: bool = True
    label: str = ""
    description: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = str(self.name or "").strip()
        self.enabled = bool(self.enabled)
        self.label = str(self.label or self.name).strip()
        self.description = str(self.description or "").strip()
        self.config = {
            str(key): value
            for key, value in (self.config or {}).items()
            if key is not None
        }


@dataclass
class MessageHookConfig:
    enabled: bool = True
    mode: str = "conservative"
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        self.mode = str(self.mode or "conservative").strip()
        self.config = {
            str(key): value
            for key, value in (self.config or {}).items()
            if key is not None
        }


@dataclass
class MessageHooksConfig:
    enabled: bool = True
    builtin: dict[str, MessageHookConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.enabled = bool(self.enabled)
        if "abusive_language_normalization" not in self.builtin:
            self.builtin["abusive_language_normalization"] = MessageHookConfig()


@dataclass
class Config:
    telegram_token: str
    allowed_user_id: int
    group_chat_id: int
    log_level: str
    tools: list = field(default_factory=list)  # list[ToolConfig]
    providers: dict[str, ToolConfig] = field(default_factory=dict)
    data_dir: str | None = None  # --data-dir path, or None for CWD defaults
    delete_archived_topics: bool = True  # 归档 thread 时是否删除 topic（vs 仅关闭）
    schema_version: int = 1  # 1=legacy tools[]; 2=provider-centric
    notification_channels: dict[str, NotificationChannelConfig] = field(default_factory=dict)
    message_hooks: MessageHooksConfig = field(default_factory=MessageHooksConfig)
    ai: AiConfig = field(default_factory=AiConfig)

    def __post_init__(self) -> None:
        if self.providers and not self.tools:
            self.tools = list(self.providers.values())
        elif self.tools and not self.providers:
            self.providers = {tool.name: tool for tool in self.tools}
        elif self.providers and self.tools:
            merged = {tool.name: tool for tool in self.tools}
            merged.update(self.providers)
            self.providers = merged
            seen: set[str] = set()
            normalized_tools: list[ToolConfig] = []
            for tool in self.tools:
                current = self.providers[tool.name]
                if current.name in seen:
                    continue
                seen.add(current.name)
                normalized_tools.append(current)
            for name, tool in self.providers.items():
                if name not in seen:
                    normalized_tools.append(tool)
            self.tools = normalized_tools

    def get_tool(self, name: str) -> Optional[ToolConfig]:
        """按名称查找工具配置，不存在或未启用返回 None。"""
        tool = self.providers.get(name)
        if tool is None:
            return None
        return tool if tool.enabled else None

    def get_provider(self, name: str) -> Optional[ToolConfig]:
        """按名称查找 provider，不区分 managed 状态。"""
        return self.providers.get(name)

    @property
    def enabled_tools(self) -> list:
        """返回所有已启用的工具列表。"""
        return [t for t in self.tools if t.enabled and t.visible and is_provider_exposed(t.name)]

    @property
    def enabled_notification_channels(self) -> list[NotificationChannelConfig]:
        """返回所有已启用的通知渠道。"""
        return [channel for channel in self.notification_channels.values() if channel.enabled]


def _build_notification_channel_config(
    channel_name: str,
    raw: dict[str, Any] | None,
) -> NotificationChannelConfig:
    raw = raw if isinstance(raw, dict) else {}
    config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    return NotificationChannelConfig(
        name=channel_name,
        enabled=bool(raw.get("enabled", True)),
        label=str(raw.get("label") or channel_name),
        description=str(raw.get("description") or ""),
        config=dict(config),
    )


def _load_notification_channels(data: dict[str, Any]) -> dict[str, NotificationChannelConfig]:
    notifications_raw = data.get("notifications")
    channels_raw = {}
    if isinstance(notifications_raw, dict) and isinstance(notifications_raw.get("channels"), dict):
        channels_raw = notifications_raw.get("channels") or {}

    channels: dict[str, NotificationChannelConfig] = {}
    channels["telegram"] = _build_notification_channel_config(
        "telegram",
        channels_raw.get("telegram") if isinstance(channels_raw, dict) else None,
    )
    if isinstance(channels_raw, dict):
        for channel_name, channel_raw in channels_raw.items():
            normalized_name = str(channel_name or "").strip()
            if not normalized_name or normalized_name in channels:
                continue
            channels[normalized_name] = _build_notification_channel_config(
                normalized_name,
                channel_raw if isinstance(channel_raw, dict) else {},
            )
    return channels


def _build_message_hook_config(raw: dict[str, Any] | None) -> MessageHookConfig:
    raw = raw if isinstance(raw, dict) else {}
    config = raw.get("config") if isinstance(raw.get("config"), dict) else {}
    raw_mode = raw.get("mode", "conservative")
    if raw_mode is False:
        mode = "off"
    elif raw_mode is True:
        mode = "conservative"
    else:
        mode = str(raw_mode or "conservative")
    return MessageHookConfig(
        enabled=bool(raw.get("enabled", True)),
        mode=mode,
        config=dict(config),
    )


def _load_message_hooks(data: dict[str, Any]) -> MessageHooksConfig:
    raw = data.get("message_hooks")
    raw = raw if isinstance(raw, dict) else {}
    builtin_raw = raw.get("builtin") if isinstance(raw.get("builtin"), dict) else {}
    builtin = {
        "abusive_language_normalization": _build_message_hook_config(
            builtin_raw.get("abusive_language_normalization")
            if isinstance(builtin_raw, dict)
            else None
        )
    }
    if isinstance(builtin_raw, dict):
        for hook_name, hook_raw in builtin_raw.items():
            normalized_name = str(hook_name or "").strip()
            if not normalized_name or normalized_name in builtin:
                continue
            builtin[normalized_name] = _build_message_hook_config(
                hook_raw if isinstance(hook_raw, dict) else {}
            )
    return MessageHooksConfig(
        enabled=bool(raw.get("enabled", True)),
        builtin=builtin,
    )


def _message_hooks_from_raw(raw: Any) -> MessageHooksConfig | None:
    if not isinstance(raw, dict):
        return None
    if "builtin" in raw:
        return _load_message_hooks({"message_hooks": raw})

    builtin = {
        "abusive_language_normalization": _build_message_hook_config(
            raw.get("abusive_language_normalization")
        )
    }
    for hook_name, hook_raw in raw.items():
        normalized_name = str(hook_name or "").strip()
        if not normalized_name or normalized_name in builtin or normalized_name in {"enabled", "builtin"}:
            continue
        builtin[normalized_name] = _build_message_hook_config(
            hook_raw if isinstance(hook_raw, dict) else {}
        )
    return MessageHooksConfig(
        enabled=bool(raw.get("enabled", True)),
        builtin=builtin,
    )


_positive_int_value = positive_int_value
_build_ai_service_config = build_ai_service_config
_default_ai_service_raw = default_ai_service_raw
_build_ai_scenario_config = build_ai_scenario_config
_iter_ai_service_raws = iter_ai_service_raws
_iter_ai_scenario_raws = iter_ai_scenario_raws
_load_ai_config = load_ai_config


def _default_provider_blueprint(name: str) -> dict[str, Any]:
    plugin_blueprint = _load_builtin_provider_plugin_blueprint(name)
    if plugin_blueprint is not None:
        return plugin_blueprint

    if name == "codex":
        return {
            "visible": True,
            "runtime_id": "codex",
            "label": "Codex",
            "description": "OpenAI Codex CLI sessions",
            "managed": True,
            "autostart": True,
            "codex_bin": "codex",
            "protocol": "stdio",
            "app_server_port": 0,
            "app_server_url": "",
            "control_mode": "app",
            "capabilities": {
                "sessions": True,
                "send": True,
                "approvals": True,
                "questions": False,
                "photos": False,
                "files": False,
                "usage": True,
                "commands": True,
                "command_wrappers": ["model", "review"],
                "control_modes": ["app", "tui", "hybrid"],
            },
            "process": {
                "cleanup_matchers": ["codex.*app-server", "codex-aar"],
            },
            "health": {},
            "auth": {},
            "external_cli": {},
        }
    if name == "claude":
        return {
            "visible": True,
            "runtime_id": "claude",
            "label": "Claude",
            "description": "Anthropic Claude Code CLI sessions",
            "managed": False,
            "autostart": False,
            "codex_bin": "claude",
            "protocol": "stdio",
            "app_server_port": 0,
            "app_server_url": "",
            "control_mode": "app",
            "capabilities": {
                "sessions": True,
                "send": True,
                "approvals": True,
                "questions": True,
                "photos": False,
                "files": False,
                "usage": True,
                "commands": True,
                "command_wrappers": [],
                "control_modes": ["app"],
            },
            "process": {
                "cleanup_matchers": [],
            },
            "health": {},
            "auth": {},
            "external_cli": {},
        }
    return {
        "visible": True,
        "runtime_id": name,
        "label": name,
        "description": "",
        "managed": True,
        "autostart": True,
        "codex_bin": name,
        "protocol": "ws",
        "app_server_port": 0,
        "app_server_url": "",
        "control_mode": "app",
        "capabilities": {},
        "process": {},
        "health": {},
        "auth": {},
        "external_cli": {},
    }


def _load_builtin_provider_plugin_blueprint(name: str) -> dict[str, Any] | None:
    from core.providers.manifest import metadata_from_provider_manifest

    provider_id = str(name or "").strip()
    if not provider_id:
        return None

    plugin_path = BUILTIN_PROVIDER_PLUGIN_DIR / provider_id / "plugin.yaml"
    if not plugin_path.exists():
        return None

    with plugin_path.open("r", encoding="utf-8") as f:
        plugin_data = yaml.safe_load(f) or {}
    if not isinstance(plugin_data, dict):
        return None

    metadata = metadata_from_provider_manifest(plugin_data)
    provider_raw = plugin_data.get("provider")
    if not isinstance(provider_raw, dict):
        provider_raw = {}
    auth = provider_raw.get("auth") or plugin_data.get("auth") or {}
    if not isinstance(auth, dict):
        auth = {}

    return {
        "visible": metadata.visible,
        "runtime_id": metadata.runtime_id,
        "label": metadata.label,
        "description": metadata.description,
        "managed": metadata.managed,
        "autostart": metadata.autostart,
        "codex_bin": metadata.bin,
        "protocol": metadata.transport.owner,
        "app_server_port": metadata.transport.app_server_port,
        "app_server_url": metadata.transport.app_server_url,
        "control_mode": str(provider_raw.get("control_mode") or plugin_data.get("control_mode") or "app"),
        "capabilities": {
            "sessions": metadata.capabilities.sessions,
            "send": metadata.capabilities.send,
            "approvals": metadata.capabilities.approvals,
            "questions": metadata.capabilities.questions,
            "photos": metadata.capabilities.photos,
            "files": metadata.capabilities.files,
            "usage": metadata.capabilities.usage,
            "commands": metadata.capabilities.commands,
            "command_wrappers": list(metadata.capabilities.command_wrappers),
            "control_modes": list(metadata.capabilities.control_modes),
            "message_rewrite": dict(getattr(metadata.capabilities, "message_rewrite", {}) or {}),
        },
        "process": {
            "cleanup_matchers": list(metadata.process.cleanup_matchers),
        },
        "health": {
            "url": metadata.health.url,
        } if metadata.health.url else {},
        "auth": auth,
        "external_cli": provider_raw.get("external_cli") if isinstance(provider_raw.get("external_cli"), dict) else {},
    }


def _public_default_provider_raw() -> dict[str, dict[str, Any]]:
    return {
        "codex": _default_provider_blueprint("codex"),
        "claude": _default_provider_blueprint("claude"),
    }


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_provider_raw(
    providers: dict[str, dict[str, Any]],
    raw_providers: Any,
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_providers, dict):
        return providers
    merged = dict(providers)
    for provider_name, provider_raw in raw_providers.items():
        normalized_name = str(provider_name or "").strip()
        if not normalized_name:
            continue
        existing = merged.get(normalized_name, _default_provider_blueprint(normalized_name))
        override = provider_raw if isinstance(provider_raw, dict) else {}
        merged[normalized_name] = _deep_merge_dict(existing, override)
    return merged


def _load_provider_overlay() -> dict[str, Any]:
    overlay_path = str(os.environ.get("ONLINEWORKER_PROVIDER_OVERLAY") or "").strip()
    if not overlay_path:
        return {}
    merged: dict[str, Any] = {}
    for raw_entry in overlay_path.split(os.pathsep):
        entry = str(raw_entry or "").strip()
        if not entry:
            continue
        expanded_path = os.path.expanduser(entry)
        if os.path.isdir(expanded_path):
            merged = _merge_provider_raw(merged, load_overlay_provider_raws(expanded_path))
            continue
        with open(expanded_path, "r", encoding="utf-8") as f:
            overlay_data = yaml.safe_load(f) or {}
        if not isinstance(overlay_data, dict):
            continue
        if overlay_data.get("kind") == "provider":
            provider_id = str(overlay_data.get("id") or "").strip()
            if provider_id:
                merged[provider_id] = manifest_to_provider_raw(overlay_data)
            continue
        raw_providers = overlay_data.get("providers", overlay_data)
        if isinstance(raw_providers, dict):
            merged = _merge_provider_raw(merged, raw_providers)
    return merged


def _resolve_protocol(
    tool_name: str,
    *,
    explicit_protocol: str,
    app_server_url: str,
    raw_port: int,
    default_protocol: str,
    legacy: bool,
) -> str:
    if explicit_protocol:
        return explicit_protocol
    if app_server_url.startswith("ws://") or app_server_url.startswith("wss://"):
        return "ws"
    if app_server_url.startswith("unix://"):
        return "unix"
    if app_server_url.startswith("http://") or app_server_url.startswith("https://"):
        return "http"
    if tool_name == "codex":
        if legacy:
            return "ws" if raw_port else "stdio"
        return default_protocol
    if tool_name == "claude":
        return "stdio"
    return default_protocol


def _normalize_transport_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"stdio", "ws", "unix", "http"}:
        return normalized
    return ""


def _normalize_live_transport_name(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"owner_bridge", "shared_ws", "shared_unix", "stdio", "ws", "unix", "http"}:
        return normalized
    return ""


def _default_owner_transport(tool_name: str) -> str:
    if tool_name == "codex":
        return "stdio"
    if tool_name == "claude":
        return "stdio"
    return "ws"


def _default_live_transport(
    tool_name: str,
    *,
    owner_transport: str,
    control_mode: str,
) -> str:
    if tool_name == "codex":
        if owner_transport == "ws" and control_mode in {"app", "hybrid"}:
            return "shared_ws"
        if owner_transport == "unix" and control_mode in {"app", "hybrid"}:
            return "shared_unix"
        return "owner_bridge"
    return owner_transport or _default_owner_transport(tool_name)


def _build_tool_config(tool_name: str, raw: dict[str, Any], *, legacy: bool) -> ToolConfig:
    defaults = _default_provider_blueprint(tool_name)
    if legacy:
        managed = bool(raw.get("enabled", True))
        autostart = managed
        codex_bin = raw.get("codex_bin") or defaults["codex_bin"]
        transport = {}
    else:
        managed = bool(raw.get("enabled", raw.get("managed", defaults["managed"])))
        autostart = bool(raw.get("autostart", defaults["autostart"]))
        codex_bin = raw.get("bin") or raw.get("codex_bin") or defaults["codex_bin"]
        transport = raw.get("transport") or {}
        if not isinstance(transport, dict):
            transport = {}

    app_server_url = (
        transport.get("app_server_url")
        or transport.get("url")
        or raw.get("app_server_url")
        or defaults["app_server_url"]
        or ""
    )
    raw_port = int(
        transport.get("app_server_port", raw.get("app_server_port", defaults["app_server_port"])) or 0
    )
    raw_explicit_protocol = (
        transport.get("type")
        or raw.get("protocol")
        or ""
    )
    explicit_protocol = str(raw_explicit_protocol or "").strip()
    explicit_url_protocol = _resolve_protocol(
        tool_name,
        explicit_protocol="",
        app_server_url=app_server_url,
        raw_port=0,
        default_protocol="",
        legacy=False,
    )
    if (
        tool_name == "codex"
        and explicit_url_protocol
        and not transport.get("type")
        and not raw.get("owner_transport")
        and "protocol" in defaults
        and raw.get("protocol") == defaults.get("protocol")
    ):
        explicit_protocol = ""
    explicit_owner_transport = _normalize_transport_name(
        raw.get("owner_transport") or transport.get("owner")
    )
    protocol = _resolve_protocol(
        tool_name,
        explicit_protocol=explicit_protocol,
        app_server_url=app_server_url,
        raw_port=raw_port,
        default_protocol=str(defaults["protocol"]),
        legacy=legacy,
    )
    if explicit_owner_transport:
        protocol = explicit_owner_transport

    explicit_control_mode = str(raw.get("control_mode") or "").strip()
    app_server_port = raw_port
    if (
        legacy
        and tool_name == "codex"
        and explicit_protocol == "ws"
        and not app_server_url
        and raw_port == 4722
        and not explicit_control_mode
    ):
        protocol = "stdio"
        app_server_port = 0

    if tool_name == "codex" and protocol == "stdio":
        app_server_port = 0
        app_server_url = ""
    elif tool_name == "codex" and protocol == "unix":
        app_server_port = 0

    if explicit_control_mode in ("app", "tui", "hybrid"):
        control_mode = explicit_control_mode
    elif tool_name == "codex" and protocol in {"ws", "unix"}:
        control_mode = "app"
    else:
        control_mode = str(defaults["control_mode"])

    explicit_live_transport = _normalize_live_transport_name(
        raw.get("live_transport") or transport.get("live")
    )
    live_transport = explicit_live_transport or _default_live_transport(
        tool_name,
        owner_transport=protocol,
        control_mode=control_mode,
    )

    auth = {}
    if isinstance(raw.get("auth"), dict):
        auth = {
            str(k): str(v or "").strip()
            for k, v in raw.get("auth", {}).items()
            if k is not None and str(v or "").strip()
        }
    return ToolConfig(
        name=tool_name,
        enabled=managed,
        visible=bool(raw.get("visible", defaults["visible"])),
        runtime_id=str(raw.get("runtime_id") or defaults["runtime_id"]),
        label=str(raw.get("label") or defaults["label"]),
        description=str(raw.get("description") or defaults["description"]),
        managed=managed,
        autostart=autostart,
        app_server_port=app_server_port,
        app_server_url=app_server_url,
        codex_bin=str(codex_bin or defaults["codex_bin"]),
        protocol=protocol,
        owner_transport=protocol,
        live_transport=live_transport,
        control_mode=control_mode,
        capabilities=raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else defaults["capabilities"],
        process=raw.get("process") if isinstance(raw.get("process"), dict) else defaults["process"],
        health=raw.get("health") if isinstance(raw.get("health"), dict) else defaults["health"],
        auth=auth,
        external_cli=raw.get("external_cli") if isinstance(raw.get("external_cli"), dict) else defaults["external_cli"],
        message_hooks=_message_hooks_from_raw(raw.get("message_hooks")),
    )


def load_config(path: str = DEFAULT_CONFIG_PATH, *, data_dir: str | None = None) -> Config:
    """加载配置。

    敏感字段（TELEGRAM_TOKEN、ALLOWED_USER_ID、GROUP_CHAT_ID）
    从环境变量读取（通常由 .env 文件注入）。
    非敏感字段从 config.yaml 读取。

    When *data_dir* is provided, config.yaml and .env are resolved from that
    directory, and ``load_dotenv`` is called explicitly with that path.
    Without *data_dir*, behaviour is identical to previous versions (CWD-based).
    The *path* parameter is kept for backward compatibility with existing callers
    and tests (it takes precedence over *data_dir* for the config file path).
    """
    # Resolve file paths --------------------------------------------------
    if data_dir is not None:
        config_path = os.path.join(data_dir, "config.yaml")
        env_path = os.path.join(data_dir, ".env")
    else:
        config_path = path          # legacy positional arg (backward compat)
        env_path = ".env"           # CWD

    # Load .env explicitly (never at module level) -------------------------
    global _dotenv_loaded
    if data_dir is not None:
        # data-dir mode: always load OnlineWorker-owned .env keys, preserving provider-private runtime env.
        _load_owned_env(env_path, override=True)
    elif not _dotenv_loaded:
        # CWD mode (backward compat): load once, without overriding existing process env.
        _load_owned_env(env_path, override=False)
        _dotenv_loaded = True

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    log = data.get("logging", {})
    telegram_config = data.get("telegram", {})
    schema_version = int(data.get("schema_version") or (2 if "providers" in data else 1))

    # 敏感字段：只从环境变量读取
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    if not telegram_token:
        raise ValueError("TELEGRAM_TOKEN 未配置。请在 .env 文件中设置 TELEGRAM_TOKEN=your_token。")

    allowed_user_id_str = os.environ.get("ALLOWED_USER_ID", "")
    if not allowed_user_id_str:
        raise ValueError("ALLOWED_USER_ID 未配置。请在 .env 文件中设置 ALLOWED_USER_ID=your_user_id。")

    group_chat_id_str = os.environ.get("GROUP_CHAT_ID", "")
    if not group_chat_id_str:
        raise ValueError("GROUP_CHAT_ID 未配置。请在 .env 文件中设置 GROUP_CHAT_ID=your_group_chat_id。")

    try:
        allowed_user_id = int(allowed_user_id_str)
    except ValueError:
        raise ValueError(f"ALLOWED_USER_ID 必须是整数，当前值：{allowed_user_id_str!r}")

    try:
        group_chat_id = int(group_chat_id_str)
    except ValueError:
        raise ValueError(f"GROUP_CHAT_ID 必须是整数，当前值：{group_chat_id_str!r}")

    providers: dict[str, ToolConfig] = {}

    raw_providers = data.get("providers")
    if isinstance(raw_providers, dict) and raw_providers:
        provider_raw_map = _public_default_provider_raw()
        provider_raw_map = _merge_provider_raw(provider_raw_map, _load_provider_overlay())
        provider_raw_map = _merge_provider_raw(provider_raw_map, raw_providers)
        for provider_name, provider_raw in provider_raw_map.items():
            if not provider_name:
                continue
            providers[provider_name] = _build_tool_config(
                str(provider_name),
                provider_raw if isinstance(provider_raw, dict) else {},
                legacy=False,
            )
    else:
        for raw_tool in data.get("tools", []):
            tool_name = str(raw_tool.get("name") or "").strip()
            if not tool_name:
                continue
            providers[tool_name] = _build_tool_config(tool_name, raw_tool, legacy=True)
        if not providers:
            provider_raw_map = _public_default_provider_raw()
            provider_raw_map = _merge_provider_raw(provider_raw_map, _load_provider_overlay())
            for provider_name, provider_raw in provider_raw_map.items():
                providers[provider_name] = _build_tool_config(provider_name, provider_raw, legacy=False)
        else:
            overlay_raw = _load_provider_overlay()
            if overlay_raw:
                provider_raw_map = _merge_provider_raw({}, overlay_raw)
                for provider_name, provider_raw in provider_raw_map.items():
                    providers[provider_name] = _build_tool_config(provider_name, provider_raw, legacy=False)

    if not providers:
        for provider_name, provider_raw in _public_default_provider_raw().items():
            providers[provider_name] = _build_tool_config(provider_name, provider_raw, legacy=False)

    if "claude" not in providers:
        providers["claude"] = _build_tool_config(
            "claude",
            _default_provider_blueprint("claude"),
            legacy=False,
        )

    ordered_names = []
    for name in ("codex", "claude"):
        if name in providers:
            ordered_names.append(name)
    for name in providers.keys():
        if name not in ordered_names:
            ordered_names.append(name)
    tools = [providers[name] for name in ordered_names]

    return Config(
        telegram_token=telegram_token,
        allowed_user_id=allowed_user_id,
        group_chat_id=group_chat_id,
        log_level=log.get("level", "INFO"),
        tools=tools,
        providers=providers,
        data_dir=data_dir,
        delete_archived_topics=telegram_config.get("delete_archived_topics", True),
        schema_version=schema_version,
        notification_channels=_load_notification_channels(data),
        message_hooks=_load_message_hooks(data),
        ai=_load_ai_config(data),
    )
