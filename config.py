# config.py
import os
import sys
import yaml
import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from dotenv import dotenv_values

from core.ai.config import (
    load_ai_config,
)
from core.ai.contracts import AiConfig, AiScenarioConfig, AiServiceConfig
from core.providers.contracts import (
    ProviderConfigNormalizationResult,
    ProviderDocumentNormalizationResult,
)
from core.providers.overlay import iter_overlay_manifest_paths, load_overlay_provider_raws, manifest_to_provider_raw

DEFAULT_CONFIG_PATH = "config.yaml"

# ---------------------------------------------------------------------------
# Data-dir support: when set, all file paths resolve relative to this dir.
# Without --data-dir, everything stays CWD-relative (backward compatible).
# ---------------------------------------------------------------------------
_data_dir: str | None = None
_dotenv_loaded: bool = False  # track whether CWD .env has been loaded
# 当前 App surface 已正式暴露内建 provider，运行时链路不再额外隐藏 provider。
HIDDEN_PROVIDER_IDS = frozenset()
BUILTIN_PROVIDER_PLUGIN_DIR = Path(__file__).resolve().parent / "plugins" / "providers" / "builtin"
OWNED_ENV_KEYS = frozenset(
    {
        "TELEGRAM_TOKEN",
        "TELEGRAM_PROXY_URL",
        "TELEGRAM_TRUST_ENV",
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


def _bool_config_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class ToolConfig:
    """单个 CLI 工具的配置。"""
    name: str                        # provider id / CLI 工具名
    enabled: bool = True
    visible: bool = True
    runtime_id: str = ""
    label: str = ""
    description: str = ""
    managed: bool | None = None
    autostart: bool = True
    app_server_port: int = 0         # 0 = 动态端口（app-server 自选），>0 = 固定端口
    app_server_url: str = ""         # 若设置，优先连接外部 app-server
    bin: str = ""                    # provider CLI 可执行文件路径（用于启动 runtime / app-server）
    protocol: str = "ws"             # 协议类型："stdio" / "ws" / "unix" / "http"
    owner_transport: str = ""        # owner 主链实际使用的 transport
    live_transport: str = ""         # live 辅助链路语义："owner_bridge" / "shared_ws" / "shared_unix" / 其他 provider 原生 transport
    control_mode: str = "app"        # 交互主控模式："app" / "tui" / "hybrid"
    capabilities: dict[str, Any] = field(default_factory=dict)
    process: dict[str, Any] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    auth: dict[str, str] = field(default_factory=dict)
    external_cli: dict[str, Any] = field(default_factory=dict)
    launch_methods: list[dict[str, str]] = field(default_factory=list)
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
        raw_bin = str(self.bin or "").strip()
        resolved_bin = raw_bin or str(self.name or "").strip() or "codex"
        self.bin = os.path.expanduser(resolved_bin)
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
        if "auth_token" in self.external_cli and "auth_token" not in self.auth:
            self.auth["auth_token"] = str(self.external_cli.get("auth_token") or "").strip()
        if "upstream_base_url" in self.external_cli and "base_url" not in self.auth:
            self.auth["base_url"] = str(self.external_cli.get("upstream_base_url") or "").strip()
        if "model" in self.external_cli and "model" not in self.auth:
            self.auth["model"] = str(self.external_cli.get("model") or "").strip()
        self.launch_methods = _normalize_launch_methods(self.launch_methods)

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
    telegram_proxy_url: str = ""
    telegram_trust_env: bool = True
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


def _normalize_launch_methods(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []

    methods: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if isinstance(item, str):
            command = item.strip()
            method_id = f"method_{index + 1}"
            label = command
        elif isinstance(item, dict):
            command = str(item.get("bin") or item.get("command") or "").strip()
            method_id = str(item.get("id") or item.get("name") or f"method_{index + 1}").strip()
            label = str(item.get("label") or item.get("name") or method_id or command).strip()
        else:
            continue

        if not command:
            continue
        if not method_id:
            method_id = f"method_{index + 1}"
        original_method_id = method_id
        suffix = 2
        while method_id in seen:
            method_id = f"{original_method_id}_{suffix}"
            suffix += 1
        seen.add(method_id)
        methods.append(
            {
                "id": method_id,
                "label": label or method_id,
                "bin": command,
            }
        )
    return methods


_load_ai_config = load_ai_config


def _default_provider_blueprint(name: str) -> dict[str, Any]:
    plugin_blueprint = _load_builtin_provider_plugin_blueprint(name)
    if plugin_blueprint is not None:
        return plugin_blueprint

    return {
        "visible": True,
        "runtime_id": name,
        "label": name,
        "description": "",
        "managed": False,
        "autostart": False,
        "bin": name,
        "protocol": "stdio",
        "app_server_port": 0,
        "app_server_url": "",
        "control_mode": "app",
        "capabilities": {},
        "process": {},
        "health": {},
        "auth": {},
        "external_cli": {},
        "launch_methods": [],
        "message_hooks": None,
    }


def _ensure_manifest_import_path(manifest_path: Path) -> None:
    overlay_root = manifest_path.parent.parent
    overlay_root_str = str(overlay_root)
    if overlay_root_str not in sys.path:
        sys.path.insert(0, overlay_root_str)


def _provider_manifest_paths() -> dict[str, Path]:
    manifests: dict[str, Path] = {}
    for plugin_path in sorted(BUILTIN_PROVIDER_PLUGIN_DIR.glob("*/plugin.yaml")):
        try:
            with plugin_path.open("r", encoding="utf-8") as f:
                plugin_data = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not isinstance(plugin_data, dict) or plugin_data.get("kind") != "provider":
            continue
        provider_id = str(plugin_data.get("id") or "").strip()
        if provider_id:
            manifests[provider_id] = plugin_path
    for plugin_path in iter_overlay_manifest_paths():
        try:
            with plugin_path.open("r", encoding="utf-8") as f:
                plugin_data = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not isinstance(plugin_data, dict) or plugin_data.get("kind") != "provider":
            continue
        provider_id = str(plugin_data.get("id") or "").strip()
        if provider_id:
            manifests[provider_id] = plugin_path
    return manifests


def _load_provider_config_normalizer(provider_id: str):
    return _load_provider_manifest_entrypoint(provider_id, "python_config_normalizer")


def _load_provider_manifest_entrypoint(provider_id: str, entrypoint_key: str):
    normalized_provider_id = str(provider_id or "").strip()
    if not normalized_provider_id:
        return None
    manifest_path = _provider_manifest_paths().get(normalized_provider_id)
    if manifest_path is None:
        return None
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}
    entrypoint = ((manifest.get("entrypoints") or {}).get(entrypoint_key) or "").strip()
    if not entrypoint:
        return None
    module_name, separator, factory_name = entrypoint.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError(
            f"Provider manifest entrypoint {entrypoint_key!r} must use module:function syntax: {entrypoint}"
        )
    _ensure_manifest_import_path(manifest_path)
    module = importlib.import_module(module_name)
    return getattr(module, factory_name)


def _normalize_provider_raw(
    tool_name: str,
    raw: dict[str, Any],
    *,
    legacy: bool,
) -> tuple[dict[str, Any], bool]:
    normalizer = _load_provider_config_normalizer(tool_name)
    if normalizer is None:
        sanitized_raw, changed = _sanitize_provider_cleanup_matchers(raw)
        return sanitized_raw, changed
    result = normalizer(raw, defaults=_default_provider_blueprint(tool_name), legacy=legacy)
    if isinstance(result, ProviderConfigNormalizationResult):
        normalized_raw = result.raw if isinstance(result.raw, dict) else {}
        sanitized_raw, cleanup_changed = _sanitize_provider_cleanup_matchers(normalized_raw)
        return sanitized_raw, bool(result.persist) or cleanup_changed
    if isinstance(result, dict):
        sanitized_raw, changed = _sanitize_provider_cleanup_matchers(result)
        return sanitized_raw, changed
    raise TypeError(f"Provider config normalizer for {tool_name!r} must return dict or ProviderConfigNormalizationResult")


def _normalize_config_document(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    normalized_document = data
    for provider_id in _provider_manifest_paths():
        normalizer = _load_provider_manifest_entrypoint(provider_id, "python_document_normalizer")
        if normalizer is None:
            continue
        result = normalizer(normalized_document)
        if isinstance(result, ProviderDocumentNormalizationResult):
            normalized_document = result.document if isinstance(result.document, dict) else {}
            changed = changed or bool(result.persist)
            continue
        if isinstance(result, dict):
            normalized_document = result
            continue
        raise TypeError(
            f"Provider document normalizer for {provider_id!r} must return dict or ProviderDocumentNormalizationResult"
        )
    return normalized_document, changed


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
        "bin": metadata.bin,
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
            "launch_methods": bool(getattr(metadata.capabilities, "launch_methods", False)),
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
        "launch_methods": provider_raw.get("launch_methods") if isinstance(provider_raw.get("launch_methods"), list) else [],
        "message_hooks": provider_raw.get("message_hooks") if isinstance(provider_raw.get("message_hooks"), dict) else None,
    }


def _builtin_provider_plugin_defaults() -> list[tuple[int, str, str, dict[str, Any]]]:
    defaults: list[tuple[int, str, str, dict[str, Any]]] = []
    if not BUILTIN_PROVIDER_PLUGIN_DIR.exists():
        return defaults

    for plugin_path in sorted(BUILTIN_PROVIDER_PLUGIN_DIR.glob("*/plugin.yaml")):
        with plugin_path.open("r", encoding="utf-8") as f:
            plugin_data = yaml.safe_load(f) or {}
        if not isinstance(plugin_data, dict) or plugin_data.get("kind") != "provider":
            continue

        provider_id = str(plugin_data.get("id") or "").strip()
        if not provider_id:
            continue

        blueprint = _load_builtin_provider_plugin_blueprint(provider_id)
        if blueprint is None:
            continue

        try:
            order = int(plugin_data.get("order") or sys.maxsize)
        except (TypeError, ValueError):
            order = sys.maxsize
        visibility = str(plugin_data.get("visibility") or "private").strip().lower()
        defaults.append((order, provider_id, visibility, blueprint))

    defaults.sort(key=lambda item: (item[0], item[1]))
    return defaults


def _public_default_provider_ids() -> list[str]:
    return [
        provider_id
        for _, provider_id, visibility, _ in _builtin_provider_plugin_defaults()
        if visibility == "public"
    ]


def _public_default_provider_raw() -> dict[str, dict[str, Any]]:
    return {
        provider_id: blueprint
        for _, provider_id, visibility, blueprint in _builtin_provider_plugin_defaults()
        if visibility == "public"
    }


def _backfill_missing_public_providers(
    providers: dict[str, ToolConfig],
    *,
    include_managed_defaults: bool,
) -> None:
    for provider_name, provider_raw in _public_default_provider_raw().items():
        if provider_name in providers:
            continue
        if not include_managed_defaults and bool(provider_raw.get("managed", False)):
            continue
        providers[provider_name] = _build_tool_config(provider_name, provider_raw, legacy=False)


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


def _has_onlineworker_cleanup_marker(matcher: str) -> bool:
    normalized = str(matcher or "").strip().lower()
    return (
        "onlineworker" in normalized
        or "--ow-" in normalized
        or "--data-dir" in normalized
    )


def _sanitize_provider_cleanup_matchers(raw: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    process = raw.get("process")
    if not isinstance(process, dict):
        return raw, False

    cleanup_matchers = process.get("cleanup_matchers")
    if not isinstance(cleanup_matchers, list):
        cleanup_matchers = process.get("cleanupMatchers")
    if not isinstance(cleanup_matchers, list):
        return raw, False

    sanitized: list[str] = []
    changed = False
    seen: set[str] = set()
    for matcher in cleanup_matchers:
        value = str(matcher or "").strip()
        if not value:
            changed = True
            continue
        normalized = value.lower()
        if "app-server" in normalized and not _has_onlineworker_cleanup_marker(normalized):
            changed = True
            continue
        if normalized.endswith("-aar") and not _has_onlineworker_cleanup_marker(normalized):
            changed = True
            continue
        if value in seen:
            changed = True
            continue
        seen.add(value)
        sanitized.append(value)

    current_normalized = [str(item or "").strip() for item in cleanup_matchers if str(item or "").strip()]
    if sanitized != current_normalized or "cleanupMatchers" in process or "cleanup_matchers" not in process:
        changed = True

    next_process = dict(process)
    if sanitized:
        next_process["cleanup_matchers"] = sanitized
    else:
        next_process.pop("cleanup_matchers", None)
    next_process.pop("cleanupMatchers", None)

    next_raw = dict(raw)
    next_raw["process"] = next_process
    return next_raw, changed


def _resolve_protocol(
    explicit_protocol: str,
    app_server_url: str,
    default_protocol: str,
) -> str:
    if explicit_protocol:
        return explicit_protocol
    if app_server_url.startswith("ws://") or app_server_url.startswith("wss://"):
        return "ws"
    if app_server_url.startswith("unix://"):
        return "unix"
    if app_server_url.startswith("http://") or app_server_url.startswith("https://"):
        return "http"
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
    defaults = _default_provider_blueprint(tool_name)
    configured = _normalize_transport_name(
        defaults.get("owner_transport") or defaults.get("protocol")
    )
    return configured or "ws"


def _default_live_transport(
    tool_name: str,
    *,
    owner_transport: str,
    control_mode: str,
) -> str:
    defaults = _default_provider_blueprint(tool_name)
    configured_live_transport = _normalize_live_transport_name(defaults.get("live_transport"))
    normalized_provider_raw, _ = _normalize_provider_raw(
        tool_name,
        {
            "owner_transport": owner_transport,
            "control_mode": control_mode,
            "live_transport": "",
        },
        legacy=False,
    )
    normalized_live_transport = _normalize_live_transport_name(
        normalized_provider_raw.get("live_transport")
    )
    if normalized_live_transport:
        return normalized_live_transport
    return configured_live_transport or owner_transport or _default_owner_transport(tool_name)


def _build_tool_config(tool_name: str, raw: dict[str, Any], *, legacy: bool) -> ToolConfig:
    defaults = _default_provider_blueprint(tool_name)
    if legacy:
        managed = bool(raw.get("enabled", True))
        autostart = managed
        bin_value = raw.get("bin") or defaults["bin"]
        transport = {}
    else:
        managed = bool(raw.get("enabled", raw.get("managed", defaults["managed"])))
        autostart = bool(raw.get("autostart", defaults["autostart"]))
        bin_value = raw.get("bin") or defaults["bin"]
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
    explicit_owner_transport = _normalize_transport_name(
        raw.get("owner_transport") or transport.get("owner")
    )
    protocol = _resolve_protocol(
        explicit_protocol=explicit_protocol,
        app_server_url=app_server_url,
        default_protocol=str(defaults["protocol"]),
    )
    if explicit_owner_transport:
        protocol = explicit_owner_transport

    explicit_control_mode = str(raw.get("control_mode") or "").strip()
    app_server_port = raw_port
    if protocol == "stdio":
        app_server_port = 0
        app_server_url = ""
    elif protocol == "unix":
        app_server_port = 0

    if explicit_control_mode in ("app", "tui", "hybrid"):
        control_mode = explicit_control_mode
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
    raw_message_hooks = raw.get("message_hooks")
    if not isinstance(raw_message_hooks, dict):
        raw_message_hooks = defaults.get("message_hooks")
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
        bin=str(bin_value or defaults["bin"]),
        protocol=protocol,
        owner_transport=protocol,
        live_transport=live_transport,
        control_mode=control_mode,
        capabilities=raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else defaults["capabilities"],
        process=raw.get("process") if isinstance(raw.get("process"), dict) else defaults["process"],
        health=raw.get("health") if isinstance(raw.get("health"), dict) else defaults["health"],
        auth=auth,
        external_cli=raw.get("external_cli") if isinstance(raw.get("external_cli"), dict) else defaults["external_cli"],
        launch_methods=raw.get("launch_methods") if isinstance(raw.get("launch_methods"), list) else defaults["launch_methods"],
        message_hooks=_message_hooks_from_raw(raw_message_hooks),
    )


def _build_provider_configs_from_document(data: dict[str, Any]) -> tuple[
    dict[str, ToolConfig],
    dict[str, Any],
    bool,
]:
    providers: dict[str, ToolConfig] = {}
    raw_providers = data.get("providers")
    provider_document_changed = False
    normalized_raw_providers: dict[str, Any] = {}

    if isinstance(raw_providers, dict) and raw_providers:
        for provider_name, provider_raw in raw_providers.items():
            normalized_name = str(provider_name or "").strip()
            if not normalized_name:
                continue
            normalized_raw, changed = _normalize_provider_raw(
                normalized_name,
                provider_raw if isinstance(provider_raw, dict) else {},
                legacy=False,
            )
            normalized_raw_providers[normalized_name] = normalized_raw
            provider_document_changed = provider_document_changed or changed
        provider_raw_map = _public_default_provider_raw()
        provider_raw_map = _merge_provider_raw(provider_raw_map, _load_provider_overlay())
        provider_raw_map = _merge_provider_raw(provider_raw_map, normalized_raw_providers)
        for provider_name, provider_raw in provider_raw_map.items():
            if not provider_name:
                continue
            normalized_provider_raw, _ = _normalize_provider_raw(
                str(provider_name),
                provider_raw if isinstance(provider_raw, dict) else {},
                legacy=False,
            )
            providers[provider_name] = _build_tool_config(
                str(provider_name),
                normalized_provider_raw,
                legacy=False,
            )
    else:
        for raw_tool in data.get("tools", []):
            tool_name = str(raw_tool.get("name") or "").strip()
            if not tool_name:
                continue
            normalized_raw, _ = _normalize_provider_raw(
                tool_name,
                raw_tool if isinstance(raw_tool, dict) else {},
                legacy=True,
            )
            providers[tool_name] = _build_tool_config(tool_name, normalized_raw, legacy=True)
        if not providers:
            provider_raw_map = _public_default_provider_raw()
            provider_raw_map = _merge_provider_raw(provider_raw_map, _load_provider_overlay())
            for provider_name, provider_raw in provider_raw_map.items():
                normalized_provider_raw, _ = _normalize_provider_raw(
                    provider_name,
                    provider_raw if isinstance(provider_raw, dict) else {},
                    legacy=False,
                )
                providers[provider_name] = _build_tool_config(provider_name, normalized_provider_raw, legacy=False)
        else:
            overlay_raw = _load_provider_overlay()
            if overlay_raw:
                provider_raw_map = _merge_provider_raw({}, overlay_raw)
                for provider_name, provider_raw in provider_raw_map.items():
                    normalized_provider_raw, _ = _normalize_provider_raw(
                        provider_name,
                        provider_raw if isinstance(provider_raw, dict) else {},
                        legacy=False,
                    )
                    providers[provider_name] = _build_tool_config(provider_name, normalized_provider_raw, legacy=False)

    if isinstance(raw_providers, dict) and raw_providers:
        _backfill_missing_public_providers(providers, include_managed_defaults=True)
    elif providers:
        _backfill_missing_public_providers(providers, include_managed_defaults=False)
    else:
        _backfill_missing_public_providers(providers, include_managed_defaults=True)

    return providers, normalized_raw_providers, provider_document_changed


def _ordered_tools_from_providers(providers: dict[str, ToolConfig]) -> list[ToolConfig]:
    ordered_names = []
    for name in _public_default_provider_ids():
        if name in providers:
            ordered_names.append(name)
    for name in providers.keys():
        if name not in ordered_names:
            ordered_names.append(name)
    return [providers[name] for name in ordered_names]


def load_provider_runtime_config(provider_id: str, *, data_dir: str | None = None) -> Config:
    """Load provider runtime config without requiring Telegram credentials."""
    if data_dir is not None:
        config_path = os.path.join(data_dir, "config.yaml")
        env_path = os.path.join(data_dir, ".env")
        _load_owned_env(env_path, override=True)
    else:
        config_path = DEFAULT_CONFIG_PATH

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        data = {}
    data, _document_changed = _normalize_config_document(data)
    schema_version = int(data.get("schema_version") or (2 if "providers" in data else 1))
    providers, _normalized_raw_providers, _provider_document_changed = _build_provider_configs_from_document(data)

    normalized_provider_id = str(provider_id or "").strip()
    if normalized_provider_id and normalized_provider_id in providers:
        providers = {normalized_provider_id: providers[normalized_provider_id]}

    return Config(
        telegram_token="",
        allowed_user_id=0,
        group_chat_id=0,
        log_level=(data.get("logging", {}) if isinstance(data.get("logging"), dict) else {}).get("level", "INFO"),
        tools=_ordered_tools_from_providers(providers),
        providers=providers,
        data_dir=data_dir,
        schema_version=schema_version,
        message_hooks=_load_message_hooks(data),
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
    if not isinstance(data, dict):
        data = {}
    data, document_changed = _normalize_config_document(data)

    log = data.get("logging", {})
    telegram_config = data.get("telegram", {})
    telegram_config = telegram_config if isinstance(telegram_config, dict) else {}
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

    telegram_proxy_url = str(
        os.environ.get("TELEGRAM_PROXY_URL")
        or telegram_config.get("proxy_url")
        or telegram_config.get("proxy")
        or ""
    ).strip()
    telegram_trust_env_raw = (
        os.environ.get("TELEGRAM_TRUST_ENV")
        if "TELEGRAM_TRUST_ENV" in os.environ
        else telegram_config.get("trust_env")
    )
    telegram_trust_env = _bool_config_value(
        telegram_trust_env_raw,
        default=True,
    )

    raw_providers = data.get("providers")
    providers, normalized_raw_providers, provider_document_changed = _build_provider_configs_from_document(data)
    tools = _ordered_tools_from_providers(providers)
    if data_dir is not None:
        should_persist = False
        if isinstance(raw_providers, dict) and raw_providers and provider_document_changed:
            data["providers"] = normalized_raw_providers
            should_persist = True
        if document_changed:
            should_persist = True
        if should_persist:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    return Config(
        telegram_token=telegram_token,
        allowed_user_id=allowed_user_id,
        group_chat_id=group_chat_id,
        telegram_proxy_url=telegram_proxy_url,
        telegram_trust_env=telegram_trust_env,
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
