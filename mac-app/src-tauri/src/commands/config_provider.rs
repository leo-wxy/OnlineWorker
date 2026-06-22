use base64::Engine;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use super::config::app_support_dir_name;

#[path = "config_provider/ai_config_store.rs"]
mod ai_config_store;
#[path = "config_provider/notification_metadata.rs"]
mod notification_metadata;
#[path = "config_provider/provider_assets.rs"]
mod provider_assets;
pub(super) use ai_config_store::set_ai_config_in_document;
use ai_config_store::{ai_metadata_from_document, normalize_ai_document};
use notification_metadata::normalize_notification_document;
pub(crate) use notification_metadata::notification_channel_metadata_from_raw;

const PROVIDER_OVERLAY_ENV: &str = "ONLINEWORKER_PROVIDER_OVERLAY";
const NOTIFICATION_OVERLAY_ENV: &str = "ONLINEWORKER_NOTIFICATION_OVERLAY";
const TRANSPORT_POLICY_SHARED_APP_SERVER: &str = "shared_app_server";

fn default_true() -> bool {
    true
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct ProviderConfigDocument {
    #[serde(skip_serializing_if = "Option::is_none")]
    schema_version: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) providers: Option<BTreeMap<String, ProviderConfigEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    tools: Option<Vec<LegacyToolConfig>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    logging: Option<serde_yaml::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    telegram: Option<serde_yaml::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) notifications: Option<NotificationConfigDocument>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) ai: Option<AiConfigDocument>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct ProviderMessageHookEntry {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) enabled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) config: Option<BTreeMap<String, serde_yaml::Value>>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderMessageHookStatus {
    pub(crate) enabled: bool,
    pub(crate) mode: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderMessageHooksMetadata {
    pub(crate) abusive_language_normalization: ProviderMessageHookStatus,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderExternalCliConfig {
    #[serde(
        default,
        alias = "upstream_base_url",
        skip_serializing_if = "Option::is_none"
    )]
    pub(crate) upstream_base_url: Option<String>,
    #[serde(
        default,
        alias = "auth_token",
        skip_serializing_if = "Option::is_none"
    )]
    pub(crate) auth_token: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) model: Option<String>,
    #[serde(
        default,
        alias = "launcher_wraps_claude",
        alias = "launcherWrapsClaude",
        alias = "launches_managed_child_cli",
        alias = "launchesManagedChildCli"
    )]
    pub(crate) launches_managed_child_cli: bool,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderLaunchMethodConfig {
    #[serde(default)]
    pub(crate) id: String,
    #[serde(default)]
    pub(crate) label: String,
    #[serde(default)]
    pub(crate) bin: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct NotificationConfigDocument {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) channels: Option<BTreeMap<String, NotificationChannelConfigEntry>>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct NotificationChannelConfigEntry {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) enabled: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) config: Option<BTreeMap<String, serde_yaml::Value>>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct AiConfigDocument {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) services: Option<Vec<AiServiceConfigEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) scenarios: Option<BTreeMap<String, AiScenarioConfigEntry>>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AiServiceConfigEntry {
    #[serde(default)]
    pub(crate) id: String,
    #[serde(default)]
    pub(crate) name: String,
    #[serde(default)]
    pub(crate) protocol: String,
    #[serde(default, alias = "base_url")]
    pub(crate) base_url: String,
    #[serde(default)]
    pub(crate) endpoint: String,
    #[serde(default, alias = "api_key")]
    pub(crate) api_key: String,
    #[serde(default, alias = "api_key_env")]
    pub(crate) api_key_env: String,
    #[serde(default)]
    pub(crate) models: Vec<String>,
    #[serde(default, alias = "default_model")]
    pub(crate) default_model: String,
    #[serde(default, alias = "timeout_seconds")]
    pub(crate) timeout_seconds: u32,
    #[serde(default = "default_true")]
    pub(crate) enabled: bool,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AiScenarioConfigEntry {
    #[serde(default)]
    pub(crate) enabled: bool,
    #[serde(default, alias = "service_id")]
    pub(crate) service_id: String,
    #[serde(default)]
    pub(crate) model: String,
    #[serde(default, alias = "output_schema")]
    pub(crate) output_schema: String,
    #[serde(default)]
    pub(crate) fallback: String,
    #[serde(default)]
    pub(crate) limits: BTreeMap<String, u32>,
    #[serde(default, alias = "prompt_template")]
    pub(crate) prompt_template: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AiServiceMetadata {
    pub(crate) id: String,
    pub(crate) name: String,
    pub(crate) label: String,
    pub(crate) description: String,
    pub(crate) owner_provider_id: String,
    pub(crate) plugin_owned: bool,
    pub(crate) protocol: String,
    pub(crate) base_url: String,
    pub(crate) endpoint: String,
    pub(crate) api_key: String,
    pub(crate) api_key_env: String,
    pub(crate) models: Vec<String>,
    pub(crate) default_model: String,
    pub(crate) timeout_seconds: u32,
    pub(crate) enabled: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AiScenarioMetadata {
    pub(crate) id: String,
    pub(crate) enabled: bool,
    pub(crate) service_id: String,
    pub(crate) model: String,
    pub(crate) output_schema: String,
    pub(crate) fallback: String,
    pub(crate) limits: BTreeMap<String, u32>,
    pub(crate) prompt_template: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct AiConfigMetadata {
    pub(crate) services: Vec<AiServiceMetadata>,
    pub(crate) scenarios: Vec<AiScenarioMetadata>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NotificationSettingsOption {
    #[serde(default)]
    pub(crate) value: String,
    #[serde(default)]
    pub(crate) label: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NotificationSettingsField {
    #[serde(default)]
    pub(crate) key: String,
    #[serde(default)]
    pub(crate) label: String,
    #[serde(rename = "type", default)]
    pub(crate) kind: String,
    #[serde(default)]
    pub(crate) required: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) default: Option<serde_yaml::Value>,
    #[serde(default)]
    pub(crate) description: String,
    #[serde(default)]
    pub(crate) options: Vec<NotificationSettingsOption>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NotificationSetupGuide {
    #[serde(rename = "type", default)]
    pub(crate) kind: String,
    #[serde(default)]
    pub(crate) assets: BTreeMap<String, String>,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NotificationChannelMetadata {
    pub(crate) id: String,
    pub(crate) label: String,
    pub(crate) description: String,
    pub(crate) enabled: bool,
    pub(crate) builtin: bool,
    pub(crate) config: BTreeMap<String, serde_yaml::Value>,
    pub(crate) settings_fields: Vec<NotificationSettingsField>,
    pub(crate) icon: Option<ProviderIconEntry>,
    pub(crate) setup_guide: Option<NotificationSetupGuide>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct ProviderConfigEntry {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) visible: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) description: Option<String>,
    #[serde(alias = "runtimeId", skip_serializing_if = "Option::is_none")]
    pub(crate) runtime_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) managed: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(super) autostart: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    bin: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    transport: Option<ProviderTransportEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    protocol: Option<String>,
    #[serde(alias = "ownerTransport", skip_serializing_if = "Option::is_none")]
    owner_transport: Option<String>,
    #[serde(alias = "liveTransport", skip_serializing_if = "Option::is_none")]
    live_transport: Option<String>,
    #[serde(alias = "appServerPort", skip_serializing_if = "Option::is_none")]
    app_server_port: Option<u16>,
    #[serde(alias = "appServerUrl", skip_serializing_if = "Option::is_none")]
    app_server_url: Option<String>,
    #[serde(alias = "controlMode", skip_serializing_if = "Option::is_none")]
    control_mode: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    auth: Option<BTreeMap<String, String>>,
    #[serde(alias = "externalCli", skip_serializing_if = "Option::is_none")]
    external_cli: Option<BTreeMap<String, serde_yaml::Value>>,
    #[serde(alias = "launchMethods", skip_serializing_if = "Option::is_none")]
    launch_methods: Option<Vec<ProviderLaunchMethodConfig>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) capabilities: Option<ProviderCapabilitiesEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) message_hooks: Option<BTreeMap<String, ProviderMessageHookEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) install: Option<ProviderInstallEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) process: Option<ProviderProcessEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) discovery: Option<ProviderDiscoveryEntry>,
    #[serde(alias = "tuiHost", skip_serializing_if = "Option::is_none")]
    pub(crate) tui_host: Option<ProviderTuiHostEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) icon: Option<ProviderIconEntry>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderCapabilitiesEntry {
    #[serde(default)]
    pub(crate) sessions: bool,
    #[serde(default)]
    pub(crate) send: bool,
    #[serde(default)]
    pub(crate) commands: bool,
    #[serde(default)]
    pub(crate) approvals: bool,
    #[serde(default)]
    pub(crate) questions: bool,
    #[serde(default)]
    pub(crate) photos: bool,
    #[serde(default)]
    pub(crate) files: bool,
    #[serde(default)]
    pub(crate) usage: bool,
    #[serde(default, alias = "launch_methods")]
    pub(crate) launch_methods: bool,
    #[serde(default, alias = "command_wrappers")]
    pub(crate) command_wrappers: Vec<String>,
    #[serde(default, alias = "control_modes")]
    pub(crate) control_modes: Vec<String>,
    #[serde(default, alias = "message_rewrite")]
    pub(crate) message_rewrite: ProviderMessageRewriteCapabilities,
    #[serde(default, alias = "session_access")]
    pub(crate) session_access: ProviderSessionAccessCapabilities,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderSessionAccessCapabilities {
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) list: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) read: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) send: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) stream: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderMessageRewriteCapabilities {
    #[serde(default, alias = "app_send")]
    pub(crate) app_send: bool,
    #[serde(default)]
    pub(crate) telegram: bool,
    #[serde(
        default,
        alias = "external_cli",
        skip_serializing_if = "Option::is_none"
    )]
    pub(crate) external_cli: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) wrapper: Option<String>,
    #[serde(
        default,
        alias = "proxy_alias",
        skip_serializing_if = "Option::is_none"
    )]
    pub(crate) proxy_alias: Option<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderInstallEntry {
    #[serde(default)]
    pub(crate) cli_names: Vec<String>,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) label: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) method: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) command: String,
    #[serde(default, alias = "docs_url", skip_serializing_if = "String::is_empty")]
    pub(crate) docs_url: String,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderProcessEntry {
    #[serde(default, alias = "cleanup_matchers")]
    pub(crate) cleanup_matchers: Vec<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderDiscoveryEntry {
    #[serde(default, alias = "command_roots")]
    pub(crate) command_roots: Vec<String>,
    #[serde(default, alias = "skill_roots")]
    pub(crate) skill_roots: Vec<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderTuiHostEntry {
    #[serde(default, alias = "sidecar_args")]
    pub(crate) sidecar_args: Vec<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderIconEntry {
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) path: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) url: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub(crate) source: String,
    #[serde(skip)]
    pub(crate) generated_url: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderTransportMetadata {
    pub(crate) owner: String,
    pub(crate) live: String,
    #[serde(rename = "type")]
    pub(crate) kind: String,
    pub(crate) app_server_port: Option<u16>,
    pub(crate) app_server_url: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderMetadata {
    pub(crate) id: String,
    pub(crate) runtime_id: String,
    pub(crate) label: String,
    pub(crate) description: String,
    pub(crate) visible: bool,
    pub(crate) visibility: String,
    pub(crate) managed: bool,
    pub(crate) autostart: bool,
    pub(crate) bin: Option<String>,
    pub(crate) transport: ProviderTransportMetadata,
    pub(crate) live_transport: String,
    pub(crate) control_mode: Option<String>,
    pub(crate) capabilities: ProviderCapabilitiesEntry,
    pub(crate) message_hooks: ProviderMessageHooksMetadata,
    pub(crate) external_cli: ProviderExternalCliConfig,
    pub(crate) launch_methods: Vec<ProviderLaunchMethodConfig>,
    pub(crate) install: ProviderInstallEntry,
    pub(crate) process: ProviderProcessEntry,
    pub(crate) discovery: ProviderDiscoveryEntry,
    pub(crate) tui_host: ProviderTuiHostEntry,
    pub(crate) icon: Option<ProviderIconEntry>,
}

fn normalize_transport_kind(raw: Option<&str>) -> Option<String> {
    raw.and_then(|value| {
        let trimmed = value.trim().to_lowercase();
        match trimmed.as_str() {
            "stdio" | "ws" | "unix" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn normalize_live_transport_kind(raw: Option<&str>) -> Option<String> {
    raw.and_then(|value| {
        let trimmed = value.trim().to_lowercase();
        match trimmed.as_str() {
            "owner_bridge" | "shared_ws" | "shared_unix" | "stdio" | "ws" | "unix" | "http" => {
                Some(trimmed)
            }
            _ => None,
        }
    })
}

fn default_owner_transport(provider_id: &str) -> String {
    default_provider_config(provider_id)
        .owner_transport
        .unwrap_or_else(|| "stdio".to_string())
}

fn default_provider_compatibility(provider_id: &str) -> ProviderCompatibilityEntry {
    provider_plugin_defaults()
        .remove(provider_id)
        .map(|default| default.compatibility)
        .unwrap_or_default()
}

fn transport_policy(provider_id: &str) -> String {
    default_provider_compatibility(provider_id)
        .transport_policy
        .unwrap_or_default()
}

fn uses_shared_app_server_transport(provider_id: &str) -> bool {
    transport_policy(provider_id) == TRANSPORT_POLICY_SHARED_APP_SERVER
}

fn default_live_transport(
    provider_id: &str,
    owner_transport: &str,
    control_mode: Option<&str>,
) -> String {
    if uses_shared_app_server_transport(provider_id) {
        if owner_transport == "ws" && matches!(control_mode, Some("app" | "hybrid")) {
            return "shared_ws".to_string();
        }
        if owner_transport == "unix" && matches!(control_mode, Some("app" | "hybrid")) {
            return "shared_unix".to_string();
        }
        if owner_transport == "stdio" {
            return "owner_bridge".to_string();
        }
    }
    let defaults = default_provider_config(provider_id);
    if defaults.owner_transport.as_deref() == Some(owner_transport) {
        if let Some(live_transport) = defaults.live_transport {
            return live_transport;
        }
    }
    owner_transport.to_string()
}

pub(crate) fn provider_default_live_transport(
    provider_id: &str,
    owner_transport: &str,
    control_mode: Option<&str>,
) -> String {
    default_live_transport(provider_id, owner_transport, control_mode)
}

pub(crate) fn provider_uses_shared_app_server_transport(provider_id: &str) -> bool {
    uses_shared_app_server_transport(provider_id)
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
pub(crate) struct ProviderTransportEntry {
    #[serde(rename = "type", skip_serializing_if = "Option::is_none")]
    kind: Option<String>,
    #[serde(
        alias = "appServerPort",
        alias = "app_server_port",
        skip_serializing_if = "Option::is_none"
    )]
    app_server_port: Option<u16>,
    #[serde(
        alias = "appServerUrl",
        alias = "app_server_url",
        skip_serializing_if = "Option::is_none"
    )]
    app_server_url: Option<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
struct LegacyToolConfig {
    name: String,
    enabled: Option<bool>,
    bin: Option<String>,
    protocol: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
    #[serde(alias = "launchMethods")]
    launch_methods: Option<Vec<ProviderLaunchMethodConfig>>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) struct ProviderRuntimePolicy {
    pub managed: bool,
    pub autostart: bool,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct ProviderPluginManifest {
    id: String,
    kind: Option<String>,
    visibility: Option<String>,
    runtime_id: Option<String>,
    order: Option<u32>,
    label: Option<String>,
    description: Option<String>,
    default_visible: Option<bool>,
    icon: Option<ProviderIconEntry>,
    #[serde(skip)]
    manifest_path: Option<PathBuf>,
    provider: Option<ProviderPluginConfig>,
    ai: Option<ProviderPluginAiConfig>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct ProviderPluginConfig {
    visible: Option<bool>,
    runtime_id: Option<String>,
    managed: Option<bool>,
    autostart: Option<bool>,
    bin: Option<String>,
    owner_transport: Option<String>,
    live_transport: Option<String>,
    control_mode: Option<String>,
    transport: Option<ProviderTransportEntry>,
    auth: Option<BTreeMap<String, String>>,
    capabilities: Option<ProviderCapabilitiesEntry>,
    message_hooks: Option<BTreeMap<String, ProviderMessageHookEntry>>,
    install: Option<ProviderInstallEntry>,
    process: Option<ProviderProcessEntry>,
    discovery: Option<ProviderDiscoveryEntry>,
    tui_host: Option<ProviderTuiHostEntry>,
    compatibility: Option<ProviderCompatibilityEntry>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct ProviderPluginAiConfig {
    #[serde(default)]
    services: Vec<ProviderPluginAiService>,
}

#[derive(Deserialize, Default, Clone, Debug)]
#[serde(rename_all = "camelCase")]
struct ProviderPluginAiService {
    id: String,
    name: Option<String>,
    label: Option<String>,
    description: Option<String>,
    protocol: Option<String>,
    #[serde(alias = "base_url")]
    base_url: Option<String>,
    endpoint: Option<String>,
    #[serde(alias = "api_key_env")]
    api_key_env: Option<String>,
    #[serde(default)]
    models: Vec<String>,
    #[serde(alias = "default_model")]
    default_model: Option<String>,
    #[serde(alias = "timeout_seconds")]
    timeout_seconds: Option<u32>,
    enabled: Option<bool>,
    #[serde(alias = "default_for_scenarios")]
    default_for_scenarios: Option<bool>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct ProviderCompatibilityEntry {
    transport_policy: Option<String>,
    auth_policy: Option<String>,
}

#[derive(Clone, Debug)]
struct ProviderPluginDefault {
    id: String,
    visibility: String,
    order: u32,
    config: ProviderConfigEntry,
    compatibility: ProviderCompatibilityEntry,
}

#[derive(Clone, Debug)]
struct ProviderPluginManifestSource {
    source: String,
    path: PathBuf,
}

#[derive(Clone, Debug)]
pub(super) struct ProviderAiServiceDefault {
    pub(super) id: String,
    pub(super) owner_provider_id: String,
    pub(super) label: String,
    pub(super) description: String,
    pub(super) plugin_owned: bool,
    pub(super) default_for_scenarios: bool,
    pub(super) config: AiServiceConfigEntry,
    order: u32,
    service_index: usize,
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")))
        .to_path_buf()
}

fn manifest_source_from_path(path: PathBuf) -> Option<ProviderPluginManifestSource> {
    fs::read_to_string(&path)
        .ok()
        .map(|source| ProviderPluginManifestSource { source, path })
}

fn read_manifest_files_from_group(group_dir: &Path) -> Vec<ProviderPluginManifestSource> {
    let Ok(entries) = fs::read_dir(group_dir) else {
        return Vec::new();
    };
    let mut paths = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path().join("plugin.yaml"))
        .filter(|path| path.exists())
        .collect::<Vec<_>>();
    paths.sort();
    paths
        .into_iter()
        .filter_map(manifest_source_from_path)
        .collect()
}

fn read_manifest_files_from_overlay_path(overlay_path: &Path) -> Vec<ProviderPluginManifestSource> {
    if overlay_path.is_file() {
        return manifest_source_from_path(overlay_path.to_path_buf())
            .map(|source| vec![source])
            .unwrap_or_default();
    }
    let Ok(entries) = fs::read_dir(overlay_path) else {
        return Vec::new();
    };
    let mut manifests = Vec::new();
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        if path.is_dir() {
            manifests.extend(read_manifest_files_from_overlay_path(&path));
            continue;
        }
        if path.file_name().and_then(|name| name.to_str()) == Some("plugin.yaml") {
            if let Some(source) = manifest_source_from_path(path) {
                manifests.push(source);
            }
        }
    }
    manifests
}

fn read_manifest_files_from_overlay_env(env_key: &str) -> Vec<ProviderPluginManifestSource> {
    let Some(raw) = read_overlay_env_spec(env_key) else {
        return Vec::new();
    };
    env::split_paths(&raw)
        .flat_map(|path| read_manifest_files_from_overlay_path(&path))
        .collect()
}

fn read_manifest_files_from_process_env(env_key: &str) -> Vec<ProviderPluginManifestSource> {
    let Some(raw) = read_process_env_value(env_key) else {
        return Vec::new();
    };
    env::split_paths(&raw)
        .flat_map(|path| read_manifest_files_from_overlay_path(&path))
        .collect()
}

fn app_support_env_path() -> PathBuf {
    let home = env::var("HOME").unwrap_or_else(|_| "/Users/unknown".to_string());
    PathBuf::from(home)
        .join("Library/Application Support")
        .join(app_support_dir_name())
        .join(".env")
}

fn trimmed_env_value(value: String) -> Option<String> {
    let trimmed = value.trim().to_string();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

#[cfg(test)]
thread_local! {
    static TEST_PROCESS_ENV_OVERRIDES: std::cell::RefCell<BTreeMap<String, Option<String>>> =
        std::cell::RefCell::new(BTreeMap::new());
}

#[cfg(test)]
fn set_test_process_env_override(env_key: &str, value: Option<String>) {
    TEST_PROCESS_ENV_OVERRIDES.with(|overrides| {
        overrides.borrow_mut().insert(env_key.to_string(), value);
    });
}

fn read_process_env_value(env_key: &str) -> Option<String> {
    #[cfg(test)]
    if let Some(value) =
        TEST_PROCESS_ENV_OVERRIDES.with(|overrides| overrides.borrow().get(env_key).cloned())
    {
        return value.and_then(trimmed_env_value);
    }

    env::var(env_key).ok().and_then(trimmed_env_value)
}

#[cfg(test)]
fn overlay_env_spec_from_env_raw(raw: &str) -> Option<String> {
    overlay_env_spec_from_env_raw_for_key(raw, PROVIDER_OVERLAY_ENV)
}

fn overlay_env_spec_from_env_raw_for_key(raw: &str, env_key: &str) -> Option<String> {
    read_env_key(raw, env_key).and_then(trimmed_env_value)
}

fn read_overlay_env_spec_from_app_env(env_key: &str) -> Option<String> {
    let raw = fs::read_to_string(app_support_env_path()).ok()?;
    overlay_env_spec_from_env_raw_for_key(&raw, env_key)
}

fn read_overlay_env_spec(env_key: &str) -> Option<String> {
    let from_process = read_process_env_value(env_key);
    if env_key == NOTIFICATION_OVERLAY_ENV {
        return from_process;
    }
    from_process.or_else(|| read_overlay_env_spec_from_app_env(env_key))
}

fn provider_plugin_manifest_sources_with_paths() -> Vec<ProviderPluginManifestSource> {
    let plugin_root = workspace_root().join("plugins").join("providers");
    let mut sources = Vec::new();
    sources.extend(read_manifest_files_from_group(&plugin_root.join("builtin")));
    sources.extend(read_manifest_files_from_overlay_env(PROVIDER_OVERLAY_ENV));
    if !sources.is_empty() {
        return sources;
    }
    provider_assets::builtin_provider_assets()
        .iter()
        .filter_map(|asset| {
            let id = asset.id()?;
            Some(ProviderPluginManifestSource {
            source: asset.manifest.to_string(),
            path: plugin_root
                .join("builtin")
                    .join(id)
                .join("plugin.yaml"),
            })
        })
        .collect()
}

pub(crate) fn provider_plugin_manifest_sources() -> Vec<String> {
    provider_plugin_manifest_sources_with_paths()
        .into_iter()
        .map(|manifest| manifest.source)
        .collect()
}

fn notification_plugin_manifest_sources_with_paths() -> Vec<ProviderPluginManifestSource> {
    let plugin_root = workspace_root().join("plugins").join("notifications");
    let mut sources = Vec::new();
    sources.extend(read_manifest_files_from_group(&plugin_root.join("builtin")));
    sources.extend(read_manifest_files_from_process_env(
        NOTIFICATION_OVERLAY_ENV,
    ));
    if !sources.is_empty() {
        return sources;
    }
    vec![ProviderPluginManifestSource {
        source: provider_assets::builtin_notification_manifest("telegram")
            .unwrap_or_default()
            .to_string(),
        path: plugin_root
            .join("builtin")
            .join("telegram")
            .join("plugin.yaml"),
    }]
}

fn resolve_provider_icon(
    mut icon: Option<ProviderIconEntry>,
    manifest_path: Option<&Path>,
    provider_id: &str,
) -> Option<ProviderIconEntry> {
    let mut icon = icon.take()?;
    if icon.url.trim().is_empty() && !icon.path.trim().is_empty() {
        let file_bytes = manifest_path
            .and_then(Path::parent)
            .map(|dir| dir.join(icon.path.trim()))
            .filter(|path| path.is_file())
            .and_then(|path| fs::read(path).ok());
        let fallback_bytes = file_bytes.or_else(|| {
            if icon.path.trim() == "icon.svg" {
                provider_assets::builtin_provider_icon_svg(provider_id)
                    .map(|svg| svg.as_bytes().to_vec())
            } else {
                None
            }
        });
        if let Some(svg) = fallback_bytes {
            let encoded = base64::engine::general_purpose::STANDARD.encode(svg);
            icon.url = format!("data:image/svg+xml;base64,{encoded}");
            icon.generated_url = true;
        }
    }
    Some(icon)
}

fn plugin_manifest_to_default(manifest: ProviderPluginManifest) -> Option<ProviderPluginDefault> {
    if manifest.kind.as_deref() != Some("provider") {
        return None;
    }
    let provider_id = manifest.id.trim().to_string();
    if provider_id.is_empty() {
        return None;
    }

    let provider = manifest.provider.unwrap_or_default();
    let compatibility = provider.compatibility.clone().unwrap_or_default();
    let mut transport = provider.transport.unwrap_or_default();
    let owner_transport = normalize_transport_kind(provider.owner_transport.as_deref())
        .or_else(|| normalize_transport_kind(transport.kind.as_deref()))
        .unwrap_or_else(|| "stdio".to_string());
    transport.kind = Some(owner_transport.clone());
    let live_transport = normalize_live_transport_kind(provider.live_transport.as_deref())
        .unwrap_or_else(|| owner_transport.clone());
    let bin = provider.bin.unwrap_or_else(|| provider_id.clone());
    let install_cli_name = bin
        .rsplit('/')
        .next()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(&provider_id)
        .to_string();

    Some(ProviderPluginDefault {
        id: provider_id.clone(),
        visibility: manifest.visibility.unwrap_or_else(|| "private".to_string()),
        order: manifest.order.unwrap_or(u32::MAX),
        config: ProviderConfigEntry {
            visible: Some(
                provider
                    .visible
                    .unwrap_or(manifest.default_visible.unwrap_or(true)),
            ),
            label: Some(manifest.label.unwrap_or_else(|| provider_id.clone())),
            description: Some(manifest.description.unwrap_or_default()),
            runtime_id: Some(
                provider
                    .runtime_id
                    .or(manifest.runtime_id)
                    .unwrap_or_else(|| provider_id.clone()),
            ),
            managed: Some(provider.managed.unwrap_or(false)),
            autostart: Some(provider.autostart.unwrap_or(false)),
            bin: Some(bin),
            transport: Some(transport),
            owner_transport: Some(owner_transport),
            live_transport: Some(live_transport),
            control_mode: provider.control_mode.or_else(|| Some("app".to_string())),
            auth: provider.auth,
            capabilities: Some(provider.capabilities.unwrap_or_default()),
            message_hooks: provider.message_hooks,
            launch_methods: None,
            install: Some({
                let mut install = provider.install.unwrap_or_default();
                if install.cli_names.is_empty() {
                    install.cli_names = vec![install_cli_name];
                }
                install
            }),
            process: Some(provider.process.unwrap_or_default()),
            discovery: Some(provider.discovery.unwrap_or_default()),
            tui_host: Some(provider.tui_host.unwrap_or_default()),
            icon: resolve_provider_icon(
                manifest.icon,
                manifest.manifest_path.as_deref(),
                &provider_id,
            ),
            ..ProviderConfigEntry::default()
        },
        compatibility,
    })
}

fn provider_plugin_default_list() -> Vec<ProviderPluginDefault> {
    let mut defaults = Vec::new();
    for manifest_source in provider_plugin_manifest_sources_with_paths() {
        let Ok(mut manifest) =
            serde_yaml::from_str::<ProviderPluginManifest>(&manifest_source.source)
        else {
            continue;
        };
        manifest.manifest_path = Some(manifest_source.path);
        if let Some(default) = plugin_manifest_to_default(manifest) {
            defaults.push(default);
        }
    }
    defaults.sort_by(|left, right| {
        left.order
            .cmp(&right.order)
            .then_with(|| left.id.cmp(&right.id))
    });
    defaults
}

fn provider_ai_service_default_list() -> Vec<ProviderAiServiceDefault> {
    let mut defaults = Vec::new();
    for manifest_source in provider_plugin_manifest_sources_with_paths() {
        let Ok(mut manifest) =
            serde_yaml::from_str::<ProviderPluginManifest>(&manifest_source.source)
        else {
            continue;
        };
        manifest.manifest_path = Some(manifest_source.path);
        if manifest.kind.as_deref() != Some("provider") {
            continue;
        }
        let provider_id = manifest.id.trim().to_string();
        if provider_id.is_empty() {
            continue;
        }
        let order = manifest.order.unwrap_or(u32::MAX);
        let ai = manifest.ai.unwrap_or_default();
        for (service_index, service) in ai.services.into_iter().enumerate() {
            let service_id = service.id.trim().to_string();
            if service_id.is_empty() {
                continue;
            }
            let models = service
                .models
                .into_iter()
                .map(|model| model.trim().to_string())
                .filter(|model| !model.is_empty())
                .collect::<Vec<_>>();
            let default_model = service
                .default_model
                .unwrap_or_default()
                .trim()
                .to_string();
            let label = service
                .label
                .unwrap_or_else(|| service.name.clone().unwrap_or_else(|| service_id.clone()))
                .trim()
                .to_string();
            let name = service
                .name
                .unwrap_or_else(|| service_id.clone())
                .trim()
                .to_string();
            defaults.push(ProviderAiServiceDefault {
                id: service_id.clone(),
                owner_provider_id: provider_id.clone(),
                label,
                description: service.description.unwrap_or_default().trim().to_string(),
                plugin_owned: true,
                default_for_scenarios: service.default_for_scenarios.unwrap_or(false),
                config: AiServiceConfigEntry {
                    id: service_id,
                    name,
                    protocol: service
                        .protocol
                        .unwrap_or_else(|| "openai_compatible_chat".to_string())
                        .trim()
                        .to_string(),
                    base_url: service.base_url.unwrap_or_default().trim().trim_end_matches('/').to_string(),
                    endpoint: service.endpoint.unwrap_or_default().trim().to_string(),
                    api_key: String::new(),
                    api_key_env: service.api_key_env.unwrap_or_default().trim().to_string(),
                    models,
                    default_model,
                    timeout_seconds: service.timeout_seconds.unwrap_or(20),
                    enabled: service.enabled.unwrap_or(false),
                },
                order,
                service_index,
            });
        }
    }
    defaults.sort_by(|left, right| {
        left.order
            .cmp(&right.order)
            .then_with(|| left.service_index.cmp(&right.service_index))
            .then_with(|| left.id.cmp(&right.id))
    });
    defaults
}

pub(super) fn provider_ai_service_defaults() -> Vec<ProviderAiServiceDefault> {
    provider_ai_service_default_list()
}

fn provider_plugin_defaults() -> BTreeMap<String, ProviderPluginDefault> {
    provider_plugin_default_list()
        .into_iter()
        .map(|default| (default.id.clone(), default))
        .collect()
}

pub(crate) fn public_default_provider_ids() -> Vec<String> {
    provider_plugin_default_list()
        .into_iter()
        .filter(|default| default.visibility == "public")
        .map(|default| default.id)
        .collect()
}

fn hidden_provider_ids() -> Vec<String> {
    provider_plugin_default_list()
        .into_iter()
        .filter(|default| !default.config.visible.unwrap_or(true))
        .map(|default| default.id)
        .collect()
}

fn generic_provider_config(provider_id: &str) -> ProviderConfigEntry {
    ProviderConfigEntry {
        visible: Some(true),
        label: Some(provider_id.to_string()),
        description: Some(String::new()),
        runtime_id: Some(provider_id.to_string()),
        managed: Some(false),
        autostart: Some(false),
        bin: Some(provider_id.to_string()),
        transport: Some(ProviderTransportEntry {
            kind: Some("stdio".to_string()),
            app_server_port: None,
            app_server_url: None,
        }),
        owner_transport: Some("stdio".to_string()),
        live_transport: Some("stdio".to_string()),
        control_mode: Some("app".to_string()),
        capabilities: Some(ProviderCapabilitiesEntry::default()),
        message_hooks: None,
        launch_methods: None,
        install: Some(ProviderInstallEntry {
            cli_names: vec![provider_id.to_string()],
            ..ProviderInstallEntry::default()
        }),
        process: Some(ProviderProcessEntry::default()),
        discovery: Some(ProviderDiscoveryEntry::default()),
        tui_host: Some(ProviderTuiHostEntry::default()),
        ..ProviderConfigEntry::default()
    }
}

fn default_provider_config(provider_id: &str) -> ProviderConfigEntry {
    provider_plugin_defaults()
        .remove(provider_id)
        .map(|default| default.config)
        .unwrap_or_else(|| generic_provider_config(provider_id))
}

fn disabled_provider_config(provider_id: &str) -> ProviderConfigEntry {
    let mut provider = default_provider_config(provider_id);
    provider.managed = Some(false);
    provider.autostart = Some(false);
    provider
}

fn infer_legacy_transport(
    tool_name: &str,
    explicit_protocol: Option<&str>,
    app_server_url: Option<&str>,
    raw_port: Option<u16>,
) -> String {
    if let Some(protocol) = explicit_protocol.filter(|value| !value.trim().is_empty()) {
        return protocol.trim().to_string();
    }
    if let Some(url) = app_server_url {
        if url.starts_with("unix://") {
            return "unix".to_string();
        }
        if url.starts_with("ws://") || url.starts_with("wss://") {
            return "ws".to_string();
        }
        if url.starts_with("http://") || url.starts_with("https://") {
            return "http".to_string();
        }
    }
    let default_transport = default_owner_transport(tool_name);
    if raw_port.unwrap_or(0) > 0 && (default_transport == "stdio" || uses_shared_app_server_transport(tool_name)) {
        "ws".to_string()
    } else {
        default_transport
    }
}

pub(crate) fn infer_provider_legacy_transport(
    tool_name: &str,
    explicit_protocol: Option<&str>,
    app_server_url: Option<&str>,
    raw_port: Option<u16>,
) -> String {
    infer_legacy_transport(tool_name, explicit_protocol, app_server_url, raw_port)
}

fn read_env_key(raw: &str, key: &str) -> Option<String> {
    raw.lines().find_map(|line| {
        let (line_key, value) = line.split_once('=')?;
        if line_key.trim() == key {
            Some(value.to_string())
        } else {
            None
        }
    })
}

fn normalize_provider_entry(provider_id: &str, provider: &mut ProviderConfigEntry) {
    let defaults = default_provider_config(provider_id);
    let compatibility = default_provider_compatibility(provider_id);
    let managed = provider.managed.or(defaults.managed).unwrap_or(false);
    let autostart = provider.autostart.or(defaults.autostart).unwrap_or(false) && managed;

    provider.managed = Some(managed);
    provider.autostart = Some(autostart);
    provider.visible = provider.visible.or(defaults.visible);
    provider.label = provider.label.take().or(defaults.label);
    provider.description = provider.description.take().or(defaults.description);
    provider.runtime_id = provider
        .runtime_id
        .take()
        .or(defaults.runtime_id)
        .or_else(|| Some(provider_id.to_string()));
    provider.bin = provider
        .bin
        .take()
        .or(defaults.bin);
    let control_mode = provider.control_mode.take().or(defaults.control_mode);
    provider.auth = if compatibility.auth_policy.as_deref() == Some("external_cli_only") {
        None
    } else {
        provider.auth.take().or(defaults.auth)
    };

    let mut transport = provider.transport.take().unwrap_or_default();
    let default_transport = defaults.transport.unwrap_or_default();
    let explicit_control_mode = provider
        .control_mode
        .as_deref()
        .map(str::trim)
        .unwrap_or("")
        .to_string();
    let explicit_protocol = normalize_transport_kind(provider.protocol.as_deref());
    let legacy_app_server_url = transport
        .app_server_url
        .clone()
        .or(provider.app_server_url.clone())
        .unwrap_or_default();
    let legacy_app_server_port = transport.app_server_port.or(provider.app_server_port);
    let owner_transport = normalize_transport_kind(provider.owner_transport.as_deref())
        .or_else(|| normalize_transport_kind(transport.kind.as_deref()))
        .or_else(|| normalize_transport_kind(provider.protocol.as_deref()))
        .or_else(|| normalize_transport_kind(default_transport.kind.as_deref()))
        .unwrap_or_else(|| default_owner_transport(provider_id));
    let mut owner_transport = owner_transport;
    let mut migrated_stdio_default = false;
    if compatibility.transport_policy.as_deref() == Some(TRANSPORT_POLICY_SHARED_APP_SERVER) {
        if explicit_protocol.as_deref() == Some("ws")
            && legacy_app_server_url.trim().is_empty()
            && legacy_app_server_port.unwrap_or(0) == 4722
            && explicit_control_mode.is_empty()
        {
            owner_transport = "unix".to_string();
            migrated_stdio_default = true;
        } else if owner_transport == "stdio" && legacy_app_server_url.trim().is_empty() {
            owner_transport = "unix".to_string();
            migrated_stdio_default = true;
        }
    }

    transport.kind = Some(owner_transport.clone());
    transport.app_server_port = transport
        .app_server_port
        .or(provider.app_server_port.take())
        .or(default_transport.app_server_port);
    transport.app_server_url = transport
        .app_server_url
        .take()
        .or(provider.app_server_url.take())
        .or(default_transport.app_server_url);

    if owner_transport == "stdio" {
        transport.app_server_port = None;
        transport.app_server_url = None;
    } else if owner_transport == "unix" {
        transport.app_server_port = None;
    }

    let mut explicit_live_transport =
        normalize_live_transport_kind(provider.live_transport.as_deref());
    if migrated_stdio_default
        && matches!(
            explicit_live_transport.as_deref(),
            Some("stdio" | "owner_bridge")
        )
    {
        explicit_live_transport = None;
    }
    let live_transport = explicit_live_transport
        .unwrap_or_else(|| {
            default_live_transport(provider_id, &owner_transport, control_mode.as_deref())
        });

    provider.control_mode = control_mode;
    provider.owner_transport = Some(owner_transport);
    provider.live_transport = Some(live_transport);
    provider.protocol = None;
    provider.transport = Some(transport);
    provider.capabilities =
        merge_provider_capabilities(provider.capabilities.take(), defaults.capabilities);
    provider.message_hooks = provider.message_hooks.take().or(defaults.message_hooks);
    provider.launch_methods = normalize_launch_methods(provider.launch_methods.take());
    provider.install = provider.install.take().or(defaults.install);
    provider.process = normalize_provider_process(provider.process.take().or(defaults.process));
    provider.discovery = provider.discovery.take().or(defaults.discovery);
    provider.tui_host = provider.tui_host.take().or(defaults.tui_host);
    provider.icon = merge_provider_icon(provider.icon.take(), defaults.icon);
}

fn normalize_provider_process(
    process: Option<ProviderProcessEntry>,
) -> Option<ProviderProcessEntry> {
    let process = process?;
    let mut cleanup_matchers = Vec::new();
    for matcher in process.cleanup_matchers {
        let matcher = matcher.trim();
        if matcher.is_empty() || is_unsafe_provider_cleanup_matcher(matcher) {
            continue;
        }
        if !cleanup_matchers
            .iter()
            .any(|existing: &String| existing == matcher)
        {
            cleanup_matchers.push(matcher.to_string());
        }
    }
    Some(ProviderProcessEntry { cleanup_matchers })
}

fn provider_cleanup_has_onlineworker_marker(matcher: &str) -> bool {
    let normalized = matcher.to_ascii_lowercase();
    normalized.contains("onlineworker")
        || normalized.contains("--ow-")
        || normalized.contains("--data-dir")
}

fn is_unsafe_provider_cleanup_matcher(matcher: &str) -> bool {
    let normalized = matcher.to_ascii_lowercase();
    (normalized.contains("app-server") || normalized.ends_with("-aar"))
        && !provider_cleanup_has_onlineworker_marker(&normalized)
}

fn normalize_launch_methods(
    methods: Option<Vec<ProviderLaunchMethodConfig>>,
) -> Option<Vec<ProviderLaunchMethodConfig>> {
    let mut normalized = Vec::new();
    let mut seen = BTreeSet::new();
    for (index, method) in methods.unwrap_or_default().into_iter().enumerate() {
        let bin = method.bin.trim().to_string();
        if bin.is_empty() {
            continue;
        }
        let mut id = if method.id.trim().is_empty() {
            format!("method_{}", index + 1)
        } else {
            method.id.trim().to_string()
        };
        let original_id = id.clone();
        let mut suffix = 2;
        while seen.contains(&id) {
            id = format!("{}_{}", original_id, suffix);
            suffix += 1;
        }
        seen.insert(id.clone());
        let label = if method.label.trim().is_empty() {
            id.clone()
        } else {
            method.label.trim().to_string()
        };
        normalized.push(ProviderLaunchMethodConfig { id, label, bin });
    }
    if normalized.is_empty() {
        None
    } else {
        Some(normalized)
    }
}

fn merge_provider_icon(
    icon: Option<ProviderIconEntry>,
    default_icon: Option<ProviderIconEntry>,
) -> Option<ProviderIconEntry> {
    match (icon, default_icon) {
        (Some(mut icon), Some(default_icon)) => {
            if icon.path.trim().is_empty() {
                icon.path = default_icon.path;
            }
            if icon.url.trim().is_empty() {
                icon.url = default_icon.url;
                icon.generated_url = default_icon.generated_url;
            }
            if icon.source.trim().is_empty() {
                icon.source = default_icon.source;
            }
            Some(icon)
        }
        (Some(icon), None) => Some(icon),
        (None, default_icon) => default_icon,
    }
}

fn merge_provider_capabilities(
    capabilities: Option<ProviderCapabilitiesEntry>,
    default_capabilities: Option<ProviderCapabilitiesEntry>,
) -> Option<ProviderCapabilitiesEntry> {
    match (capabilities, default_capabilities) {
        (Some(mut capabilities), Some(default_capabilities)) => {
            capabilities.usage = capabilities.usage || default_capabilities.usage;
            capabilities.launch_methods =
                capabilities.launch_methods || default_capabilities.launch_methods;
            if capabilities.command_wrappers.is_empty() {
                capabilities.command_wrappers = default_capabilities.command_wrappers;
            }
            if capabilities.control_modes.is_empty() {
                capabilities.control_modes = default_capabilities.control_modes;
            }
            capabilities.message_rewrite = merge_provider_message_rewrite(
                capabilities.message_rewrite,
                default_capabilities.message_rewrite,
            );
            capabilities.session_access = merge_provider_session_access(
                capabilities.session_access,
                default_capabilities.session_access,
            );
            Some(capabilities)
        }
        (Some(capabilities), None) => Some(capabilities),
        (None, Some(default_capabilities)) => Some(default_capabilities),
        (None, None) => None,
    }
}

fn merge_provider_session_access(
    mut access: ProviderSessionAccessCapabilities,
    default_access: ProviderSessionAccessCapabilities,
) -> ProviderSessionAccessCapabilities {
    if access.list.trim().is_empty() {
        access.list = default_access.list;
    }
    if access.read.trim().is_empty() {
        access.read = default_access.read;
    }
    if access.send.trim().is_empty() {
        access.send = default_access.send;
    }
    if access.stream.trim().is_empty() {
        access.stream = default_access.stream;
    }
    access
}

fn merge_provider_message_rewrite(
    mut rewrite: ProviderMessageRewriteCapabilities,
    default_rewrite: ProviderMessageRewriteCapabilities,
) -> ProviderMessageRewriteCapabilities {
    rewrite.app_send = rewrite.app_send || default_rewrite.app_send;
    rewrite.telegram = rewrite.telegram || default_rewrite.telegram;
    if rewrite
        .external_cli
        .as_deref()
        .unwrap_or("")
        .trim()
        .is_empty()
    {
        rewrite.external_cli = default_rewrite.external_cli;
    }
    if rewrite.wrapper.as_deref().unwrap_or("").trim().is_empty() {
        rewrite.wrapper = default_rewrite.wrapper;
    }
    if rewrite.proxy_alias.as_deref().unwrap_or("").trim().is_empty() {
        rewrite.proxy_alias = default_rewrite.proxy_alias;
    }
    rewrite
}

fn legacy_tool_to_provider(tool: LegacyToolConfig) -> ProviderConfigEntry {
    let mut provider = default_provider_config(&tool.name);
    let compatibility = default_provider_compatibility(&tool.name);
    let managed = tool.enabled.unwrap_or(true);
    let mut autostart = managed;
    let explicit_protocol = tool.protocol.clone();
    let explicit_control_mode = tool.control_mode.clone();
    let app_server_url = tool.app_server_url.clone();
    let raw_port = tool.app_server_port;
    let mut owner_transport = infer_legacy_transport(
        &tool.name,
        explicit_protocol.as_deref(),
        app_server_url.as_deref(),
        raw_port,
    );
    let mut port = tool.app_server_port.or(provider
        .transport
        .as_ref()
        .and_then(|transport| transport.app_server_port));
    if compatibility.transport_policy.as_deref() == Some(TRANSPORT_POLICY_SHARED_APP_SERVER)
        && explicit_protocol.as_deref() == Some("ws")
        && app_server_url.as_deref().unwrap_or("").is_empty()
        && raw_port.unwrap_or(0) == 4722
        && explicit_control_mode
            .as_deref()
            .map(str::trim)
            .unwrap_or("")
            .is_empty()
    {
        owner_transport = "unix".to_string();
        port = None;
    } else if compatibility.transport_policy.as_deref() == Some(TRANSPORT_POLICY_SHARED_APP_SERVER)
        && owner_transport == "stdio"
        && app_server_url.as_deref().unwrap_or("").is_empty()
    {
        owner_transport = "unix".to_string();
        port = None;
    }
    if !managed {
        autostart = false;
    }
    if owner_transport == "stdio" {
        port = None;
    } else if owner_transport == "unix" {
        port = None;
    }

    let control_mode = tool.control_mode.or(provider.control_mode);
    let live_transport =
        default_live_transport(&tool.name, &owner_transport, control_mode.as_deref());

    provider.managed = Some(managed);
    provider.autostart = Some(autostart);
    provider.bin = tool.bin.or(provider.bin);
    provider.control_mode = control_mode;
    provider.owner_transport = Some(owner_transport.clone());
    provider.live_transport = Some(live_transport);
    provider.launch_methods = normalize_launch_methods(tool.launch_methods);
    provider.transport = Some(ProviderTransportEntry {
        kind: Some(owner_transport),
        app_server_port: port,
        app_server_url: if provider.control_mode.as_deref() == Some("app") && port.is_none() {
            None
        } else {
            app_server_url
        },
    });
    provider
}

pub(super) fn normalize_provider_document_with_env(
    raw: &str,
    _env_raw: Option<&str>,
) -> Result<ProviderConfigDocument, String> {
    let mut doc: ProviderConfigDocument = if raw.trim().is_empty() {
        ProviderConfigDocument::default()
    } else {
        serde_yaml::from_str(raw).map_err(|e| format!("Cannot parse config.yaml: {}", e))?
    };
    if doc.providers.is_none() {
        let mut providers = BTreeMap::new();
        if let Some(tools) = doc.tools.take() {
            for tool in tools {
                if tool.name.trim().is_empty() {
                    continue;
                }
                providers.insert(tool.name.clone(), legacy_tool_to_provider(tool));
            }
        }
        doc.providers = Some(providers);
    }

    let providers = doc.providers.get_or_insert_with(BTreeMap::new);
    for (provider_id, provider) in providers.iter_mut() {
        normalize_provider_entry(provider_id, provider);
    }
    for builtin in public_default_provider_ids() {
        providers
            .entry(builtin.clone())
            .or_insert_with(|| default_provider_config(&builtin));
    }
    for builtin in public_default_provider_ids() {
        if let Some(provider) = providers.get_mut(&builtin) {
            normalize_provider_entry(&builtin, provider);
        }
    }

    doc.schema_version = Some(2);
    doc.tools = None;
    normalize_notification_document(&mut doc);
    normalize_ai_document(&mut doc);
    Ok(doc)
}

fn provider_metadata_from_entry(
    provider_id: &str,
    provider: &ProviderConfigEntry,
) -> ProviderMetadata {
    let transport = provider.transport.clone().unwrap_or_default();
    let owner = provider
        .owner_transport
        .clone()
        .or(transport.kind.clone())
        .unwrap_or_else(|| default_owner_transport(provider_id));
    ProviderMetadata {
        id: provider_id.to_string(),
        runtime_id: provider
            .runtime_id
            .clone()
            .unwrap_or_else(|| provider_id.to_string()),
        label: provider
            .label
            .clone()
            .unwrap_or_else(|| provider_id.to_string()),
        description: provider.description.clone().unwrap_or_default(),
        visible: provider.visible.unwrap_or(true),
        visibility: provider_plugin_defaults()
            .get(provider_id)
            .map(|default| default.visibility.clone())
            .unwrap_or_else(|| "private".to_string()),
        managed: provider.managed.unwrap_or(false),
        autostart: provider.autostart.unwrap_or(false),
        bin: provider.bin.clone(),
        live_transport: provider.live_transport.clone().unwrap_or_else(|| {
            default_live_transport(provider_id, &owner, provider.control_mode.as_deref())
        }),
        control_mode: provider.control_mode.clone(),
        capabilities: provider.capabilities.clone().unwrap_or_default(),
        message_hooks: provider_message_hooks_metadata(provider),
        external_cli: provider_external_cli_config(provider),
        launch_methods: provider.launch_methods.clone().unwrap_or_default(),
        install: provider.install.clone().unwrap_or_default(),
        process: provider.process.clone().unwrap_or_default(),
        discovery: provider.discovery.clone().unwrap_or_default(),
        tui_host: provider.tui_host.clone().unwrap_or_default(),
        icon: provider.icon.clone(),
        transport: ProviderTransportMetadata {
            owner: owner.clone(),
            live: provider.live_transport.clone().unwrap_or_else(|| {
                default_live_transport(provider_id, &owner, provider.control_mode.as_deref())
            }),
            kind: owner,
            app_server_port: transport.app_server_port,
            app_server_url: transport.app_server_url,
        },
    }
}

pub(crate) fn provider_default_metadata(provider_id: &str) -> ProviderMetadata {
    provider_metadata_from_entry(provider_id, &default_provider_config(provider_id))
}

fn value_as_string(value: &serde_yaml::Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn value_as_bool(value: &serde_yaml::Value) -> Option<bool> {
    value.as_bool().or_else(|| {
        value.as_str().and_then(|raw| {
            let normalized = raw.trim().to_lowercase();
            match normalized.as_str() {
                "true" | "1" | "yes" | "on" => Some(true),
                "false" | "0" | "no" | "off" => Some(false),
                _ => None,
            }
        })
    })
}

fn provider_external_cli_config(provider: &ProviderConfigEntry) -> ProviderExternalCliConfig {
    let Some(config) = provider.external_cli.as_ref() else {
        return ProviderExternalCliConfig::default();
    };
    ProviderExternalCliConfig {
        upstream_base_url: config
            .get("upstream_base_url")
            .and_then(value_as_string)
            .or_else(|| config.get("upstreamBaseUrl").and_then(value_as_string)),
        auth_token: config
            .get("auth_token")
            .and_then(value_as_string)
            .or_else(|| config.get("authToken").and_then(value_as_string)),
        model: config
            .get("model")
            .and_then(value_as_string),
        launches_managed_child_cli: config
            .get("launcher_wraps_claude")
            .and_then(value_as_bool)
            .or_else(|| config.get("launcherWrapsClaude").and_then(value_as_bool))
            .or_else(|| config.get("launches_managed_child_cli").and_then(value_as_bool))
            .or_else(|| config.get("launchesManagedChildCli").and_then(value_as_bool))
            .unwrap_or(false),
    }
}

fn provider_message_hooks_metadata(provider: &ProviderConfigEntry) -> ProviderMessageHooksMetadata {
    let hook = provider
        .message_hooks
        .as_ref()
        .and_then(|hooks| hooks.get("abusive_language_normalization"));
    ProviderMessageHooksMetadata {
        abusive_language_normalization: ProviderMessageHookStatus {
            enabled: hook.and_then(|entry| entry.enabled).unwrap_or(true),
            mode: hook
                .and_then(|entry| entry.mode.clone())
                .filter(|value| !value.trim().is_empty())
                .unwrap_or_else(|| "conservative".to_string()),
        },
    }
}

pub(crate) fn provider_metadata_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<Vec<ProviderMetadata>, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    let mut providers = doc.providers.unwrap_or_default();
    for provider_id in hidden_provider_ids() {
        providers
            .entry(provider_id.clone())
            .or_insert_with(|| default_provider_config(&provider_id));
    }
    let mut ordered = Vec::new();
    for provider_id in public_default_provider_ids() {
        if let Some(provider) = providers.remove(&provider_id) {
            ordered.push(provider_metadata_from_entry(&provider_id, &provider));
        }
    }
    for provider_id in hidden_provider_ids() {
        if let Some(provider) = providers.remove(&provider_id) {
            ordered.push(provider_metadata_from_entry(&provider_id, &provider));
        }
    }
    ordered.extend(
        providers
            .into_iter()
            .map(|(provider_id, provider)| provider_metadata_from_entry(&provider_id, &provider)),
    );
    Ok(ordered)
}

pub(crate) fn visible_provider_ids_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<Vec<String>, String> {
    Ok(provider_metadata_from_raw(raw, env_raw)?
        .into_iter()
        .filter(|provider| provider.visible)
        .map(|provider| provider.id)
        .collect())
}

pub(crate) fn ai_config_metadata_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<AiConfigMetadata, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    Ok(ai_metadata_from_document(doc))
}

pub(super) fn serialize_config_document_for_persistence(
    mut doc: ProviderConfigDocument,
    _raw: &str,
) -> Result<String, String> {
    prune_runtime_icon_urls(&mut doc);
    serde_yaml::to_string(&doc).map_err(|e| format!("Cannot serialize config.yaml: {}", e))
}

pub(super) fn build_default_user_config_with_env(env_raw: Option<&str>) -> Result<String, String> {
    serialize_normalized_config_with_env("", env_raw)
}

fn prune_runtime_icon_urls(doc: &mut ProviderConfigDocument) {
    let Some(providers) = doc.providers.as_mut() else {
        return;
    };
    for provider in providers.values_mut() {
        if let Some(icon) = provider.icon.as_mut() {
            if icon.generated_url {
                icon.url.clear();
                icon.generated_url = false;
            }
        }
    }
}

pub(super) fn serialize_normalized_config_with_env(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<String, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    serialize_config_document_for_persistence(doc, raw)
}

pub(super) fn normalize_config_for_display(raw: &str, env_raw: Option<&str>) -> String {
    let mut doc = match normalize_provider_document_with_env(raw, env_raw) {
        Ok(doc) => doc,
        Err(_) => return raw.to_string(),
    };
    prune_runtime_icon_urls(&mut doc);
    serde_yaml::to_string(&doc).unwrap_or_else(|_| raw.to_string())
}

#[cfg(test)]
pub(super) fn normalize_provider_document(raw: &str) -> Result<ProviderConfigDocument, String> {
    normalize_provider_document_with_env(raw, None)
}

pub(super) fn set_provider_flags_in_document(
    doc: &mut ProviderConfigDocument,
    provider_id: &str,
    managed: bool,
    autostart: bool,
) {
    let providers = doc.providers.get_or_insert_with(BTreeMap::new);
    let provider = providers
        .entry(provider_id.to_string())
        .or_insert_with(|| disabled_provider_config(provider_id));
    provider.managed = Some(managed);
    provider.autostart = Some(managed && autostart);
    normalize_provider_entry(provider_id, provider);
    doc.schema_version = Some(2);
    doc.tools = None;
}

pub(super) fn set_provider_message_hook_enabled_in_document(
    doc: &mut ProviderConfigDocument,
    provider_id: &str,
    hook_name: &str,
    enabled: bool,
) {
    let normalized_provider_id = provider_id.trim();
    let normalized_hook_name = hook_name.trim();
    if normalized_provider_id.is_empty() || normalized_hook_name.is_empty() {
        return;
    }

    let providers = doc.providers.get_or_insert_with(BTreeMap::new);
    let provider = providers
        .entry(normalized_provider_id.to_string())
        .or_insert_with(|| disabled_provider_config(normalized_provider_id));
    let hooks = provider.message_hooks.get_or_insert_with(BTreeMap::new);
    let hook = hooks
        .entry(normalized_hook_name.to_string())
        .or_insert_with(ProviderMessageHookEntry::default);
    hook.enabled = Some(enabled);
    hook.mode.get_or_insert_with(|| "conservative".to_string());
    normalize_provider_entry(normalized_provider_id, provider);
    doc.schema_version = Some(2);
    doc.tools = None;
}

pub(super) fn set_provider_cli_config_in_document(
    doc: &mut ProviderConfigDocument,
    provider_id: &str,
    bin: Option<String>,
    external_cli: ProviderExternalCliConfig,
    launch_methods: Option<Vec<ProviderLaunchMethodConfig>>,
) {
    let normalized_provider_id = provider_id.trim();
    if normalized_provider_id.is_empty() {
        return;
    }

    let providers = doc.providers.get_or_insert_with(BTreeMap::new);
    let provider = providers
        .entry(normalized_provider_id.to_string())
        .or_insert_with(|| disabled_provider_config(normalized_provider_id));

    if let Some(bin) = bin.map(|value| value.trim().to_string()) {
        if !bin.is_empty() {
            provider.bin = Some(bin);
        }
    }

    let mut config = provider.external_cli.take().unwrap_or_default();
    config.remove("upstreamBaseUrl");
    config.remove("authToken");
    config.remove("launcherWrapsClaude");
    config.remove("launchesManagedChildCli");

    match external_cli
        .upstream_base_url
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        Some(upstream_base_url) => {
            config.insert(
                "upstream_base_url".to_string(),
                serde_yaml::Value::String(upstream_base_url),
            );
        }
        None => {
            config.remove("upstream_base_url");
        }
    }

    match external_cli
        .auth_token
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        Some(auth_token) => {
            config.insert(
                "auth_token".to_string(),
                serde_yaml::Value::String(auth_token),
            );
        }
        None => {
            config.remove("auth_token");
        }
    }

    match external_cli
        .model
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        Some(model) => {
            config.insert(
                "model".to_string(),
                serde_yaml::Value::String(model),
            );
        }
        None => {
            config.remove("model");
        }
    }

    if external_cli.launches_managed_child_cli {
        config.insert(
            "launches_managed_child_cli".to_string(),
            serde_yaml::Value::Bool(true),
        );
    } else {
        config.remove("launcher_wraps_claude");
        config.remove("launches_managed_child_cli");
    }

    if config.is_empty() {
        provider.external_cli = None;
    } else {
        provider.external_cli = Some(config);
    }

    if let Some(launch_methods) = launch_methods {
        provider.launch_methods = normalize_launch_methods(Some(launch_methods));
    }

    normalize_provider_entry(normalized_provider_id, provider);
    doc.schema_version = Some(2);
    doc.tools = None;
}

pub(super) fn set_notification_channel_enabled_in_document(
    doc: &mut ProviderConfigDocument,
    channel_id: &str,
    enabled: bool,
) {
    let normalized_id = channel_id.trim();
    if normalized_id.is_empty() {
        return;
    }

    normalize_notification_document(doc);
    let notifications = doc
        .notifications
        .get_or_insert_with(NotificationConfigDocument::default);
    let channels = notifications.channels.get_or_insert_with(BTreeMap::new);
    let channel = channels
        .entry(normalized_id.to_string())
        .or_insert_with(NotificationChannelConfigEntry::default);
    channel.enabled = Some(enabled);
    normalize_notification_document(doc);
    doc.schema_version = Some(2);
    doc.tools = None;
}

pub(super) fn set_notification_channel_config_in_document(
    doc: &mut ProviderConfigDocument,
    channel_id: &str,
    config: BTreeMap<String, serde_yaml::Value>,
) {
    let normalized_id = channel_id.trim();
    if normalized_id.is_empty() {
        return;
    }

    normalize_notification_document(doc);
    let notifications = doc
        .notifications
        .get_or_insert_with(NotificationConfigDocument::default);
    let channels = notifications.channels.get_or_insert_with(BTreeMap::new);
    let channel = channels
        .entry(normalized_id.to_string())
        .or_insert_with(NotificationChannelConfigEntry::default);
    channel.config = Some(config);
    normalize_notification_document(doc);
    doc.schema_version = Some(2);
    doc.tools = None;
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;
    use std::fs;

    use super::{
        build_default_user_config_with_env, normalize_config_for_display,
        normalize_provider_document, normalize_provider_document_with_env,
        notification_channel_metadata_from_raw, overlay_env_spec_from_env_raw,
        provider_ai_service_defaults, provider_assets, provider_default_metadata, provider_metadata_from_raw,
        public_default_provider_ids, read_manifest_files_from_overlay_path,
        serialize_normalized_config_with_env, set_ai_config_in_document,
        set_notification_channel_config_in_document, set_notification_channel_enabled_in_document,
        set_provider_cli_config_in_document, set_provider_flags_in_document,
        set_provider_message_hook_enabled_in_document, set_test_process_env_override,
        AiScenarioConfigEntry, AiServiceConfigEntry, ProviderExternalCliConfig,
        ProviderLaunchMethodConfig, NOTIFICATION_OVERLAY_ENV, PROVIDER_OVERLAY_ENV,
    };

    fn shared_unix_provider_id_for_test() -> String {
        public_default_provider_ids()
            .into_iter()
            .find(|provider_id| {
                let metadata = provider_default_metadata(provider_id);
                metadata.transport.owner == "unix" && metadata.live_transport == "shared_unix"
            })
            .expect("shared unix provider")
    }

    #[test]
    fn normalize_provider_document_migrates_legacy_default_ws_to_unix_and_backfills_public_defaults() {
        let provider_id = shared_unix_provider_id_for_test();
        let raw = format!(
            r#"
tools:
  - name: {provider_id}
    enabled: true
    bin: "{provider_id}"
    protocol: "ws"
    app_server_port: 4722
"#
        );

        let doc = normalize_provider_document(&raw).expect("normalized config");
        assert_eq!(doc.schema_version, Some(2));

        let providers = doc.providers.expect("providers");
        let provider = providers.get(&provider_id).expect("provider");
        assert_eq!(provider.managed, Some(true));
        assert_eq!(provider.autostart, Some(true));
        assert_eq!(provider.bin.as_deref(), Some(provider_id.as_str()));
        let transport = provider.transport.as_ref().expect("provider transport");
        assert_eq!(transport.kind.as_deref(), Some("unix"));
        assert_eq!(transport.app_server_port, None);
        assert_eq!(provider.owner_transport.as_deref(), Some("unix"));
        assert_eq!(provider.live_transport.as_deref(), Some("shared_unix"));

        for public_provider_id in public_default_provider_ids() {
            assert!(providers.contains_key(&public_provider_id));
        }
    }

    #[test]
    fn normalize_provider_document_migrates_legacy_launch_methods() {
        let raw = r#"
tools:
  - name: custom
    enabled: true
    bin: "custom"
    protocol: "stdio"
    launch_methods:
      - id: native
        label: Native
        bin: custom
      - id: launcher
        label: Launcher
        bin: /usr/local/bin/custom-launcher
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        let launch_methods = custom.launch_methods.as_ref().expect("launch methods");

        assert_eq!(launch_methods.len(), 2);
        assert_eq!(launch_methods[0].id, "native");
        assert_eq!(launch_methods[0].label, "Native");
        assert_eq!(launch_methods[0].bin, "custom");
        assert_eq!(launch_methods[1].id, "launcher");
        assert_eq!(launch_methods[1].label, "Launcher");
        assert_eq!(launch_methods[1].bin, "/usr/local/bin/custom-launcher");
    }

    #[test]
    fn normalize_provider_document_removes_unsafe_cleanup_matchers() {
        let raw = r#"
schema_version: 2
providers:
  codex:
    managed: true
    process:
      cleanupMatchers:
        - codex.*app-server
        - codex-aar
        - onlineworker-bot --ow-codex
        - custom-provider.*serve
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let codex = providers.get("codex").expect("codex provider");
        let process = codex.process.as_ref().expect("provider process");

        assert_eq!(
            process.cleanup_matchers,
            vec![
                "onlineworker-bot --ow-codex".to_string(),
                "custom-provider.*serve".to_string(),
            ]
        );
    }

    #[test]
    fn normalize_provider_document_preserves_custom_unix_shared_transport() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    autostart: true
    bin: "custom"
    transport:
      type: "unix"
      app_server_url: "unix://"
    owner_transport: "unix"
    live_transport: "shared_unix"
    control_mode: "app"
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        let transport = custom.transport.as_ref().expect("custom transport");

        assert_eq!(transport.kind.as_deref(), Some("unix"));
        assert_eq!(transport.app_server_url.as_deref(), Some("unix://"));
        assert_eq!(custom.owner_transport.as_deref(), Some("unix"));
        assert_eq!(custom.live_transport.as_deref(), Some("shared_unix"));
    }

    #[test]
    fn normalize_provider_document_backfills_default_notification_channel() {
        let doc = normalize_provider_document("").expect("normalized config");

        let channels = doc
            .notifications
            .expect("notifications")
            .channels
            .expect("channels");
        let telegram = channels.get("telegram").expect("telegram channel");
        assert_eq!(telegram.enabled, Some(true));
        assert_eq!(telegram.label.as_deref(), Some("Telegram"));
        assert!(telegram.config.as_ref().expect("config").is_empty());
    }

    #[test]
    fn set_notification_channel_enabled_updates_existing_channel() {
        let raw = r#"
schema_version: 2
notifications:
  channels:
    telegram:
      enabled: true
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_notification_channel_enabled_in_document(&mut doc, "telegram", false);

        let channels = doc
            .notifications
            .expect("notifications")
            .channels
            .expect("channels");
        let telegram = channels.get("telegram").expect("telegram channel");
        assert_eq!(telegram.enabled, Some(false));
    }

    #[test]
    fn set_notification_channel_config_updates_plugin_config() {
        let mut doc = normalize_provider_document("").expect("normalized config");
        let mut config = BTreeMap::new();
        config.insert(
            "recipient_user_id".to_string(),
            serde_yaml::Value::String("123456789".to_string()),
        );

        set_notification_channel_config_in_document(&mut doc, "telegram", config);

        let channels = doc
            .notifications
            .expect("notifications")
            .channels
            .expect("channels");
        let telegram = channels.get("telegram").expect("telegram channel");
        assert_eq!(
            telegram
                .config
                .as_ref()
                .and_then(|config| config.get("recipient_user_id"))
                .and_then(|value| value.as_str()),
            Some("123456789")
        );
    }

    #[test]
    fn notification_channel_metadata_lists_builtin_then_custom_channels() {
        let raw = r#"
schema_version: 2
notifications:
  channels:
    wechat:
      enabled: true
      label: WeChat
      description: Custom WeChat notifier
"#;

        let metadata =
            notification_channel_metadata_from_raw(raw, None).expect("notification metadata");

        assert_eq!(metadata[0].id, "telegram");
        assert!(metadata[0].builtin);
        assert_eq!(metadata[0].settings_fields[0].key, "bot_token");
        assert_eq!(metadata[0].settings_fields[0].kind, "secret");
        assert_eq!(metadata[0].settings_fields[1].key, "recipient_user_id");
        assert_eq!(
            metadata[0]
                .setup_guide
                .as_ref()
                .expect("telegram guide")
                .kind,
            "html"
        );
        assert!(metadata[0]
            .setup_guide
            .as_ref()
            .expect("telegram guide")
            .assets
            .get("zh")
            .expect("zh guide")
            .contains("BotFather"));
        assert!(metadata[0]
            .setup_guide
            .as_ref()
            .expect("telegram guide")
            .assets
            .get("en")
            .expect("en guide")
            .contains("BotFather"));
        assert!(metadata[0]
            .icon
            .as_ref()
            .expect("telegram icon")
            .url
            .starts_with("data:image/svg+xml;base64,"));
        let wechat = metadata
            .iter()
            .find(|channel| channel.id == "wechat")
            .expect("wechat channel");
        assert_eq!(wechat.label, "WeChat");
        assert_eq!(wechat.description, "Custom WeChat notifier");
        assert!(wechat.enabled);
        assert!(!wechat.builtin);
    }

    #[test]
    fn set_ai_config_keeps_services_and_scenarios_separate() {
        let mut doc = normalize_provider_document("").expect("normalized config");
        let services = vec![AiServiceConfigEntry {
            id: "openai_default".to_string(),
            name: "OpenAI".to_string(),
            protocol: "openai_compatible_chat".to_string(),
            base_url: "https://api.openai.com/v1/".to_string(),
            endpoint: String::new(),
            api_key: "sk-test".to_string(),
            api_key_env: "OPENAI_API_KEY".to_string(),
            models: vec!["gpt-5.4".to_string()],
            default_model: "gpt-5.4".to_string(),
            timeout_seconds: 20,
            enabled: true,
        }];
        let mut scenarios = BTreeMap::new();
        scenarios.insert(
            "notification_summary".to_string(),
            AiScenarioConfigEntry {
                enabled: true,
                service_id: "openai_default".to_string(),
                model: "gpt-5.4".to_string(),
                output_schema: "notification_summary_v1".to_string(),
                fallback: "local_notification_summary_rules".to_string(),
                limits: BTreeMap::new(),
                prompt_template: "Return JSON for {{final_message}}".to_string(),
            },
        );

        set_ai_config_in_document(&mut doc, services, scenarios);

        let ai = doc.ai.expect("ai config");
        let service = ai
            .services
            .expect("services")
            .into_iter()
            .find(|service| service.id == "openai_default")
            .expect("openai service");
        assert_eq!(service.base_url, "https://api.openai.com/v1");
        assert_eq!(service.api_key_env, "OPENAI_API_KEY");
        let mut scenarios = ai.scenarios.expect("scenarios");
        let scenario = scenarios
            .remove("notification_summary")
            .expect("notification summary");
        assert_eq!(scenario.service_id, "openai_default");
        assert_eq!(
            scenario.prompt_template,
            "Return JSON for {{final_message}}"
        );
        assert_eq!(scenario.limits.get("preview_title"), Some(&16));
        assert_eq!(scenario.limits.get("summary"), None);
    }

    #[test]
    fn provider_ai_service_defaults_come_from_builtin_manifests() {
        let services = provider_ai_service_defaults();

        assert_eq!(services.len(), 2);
        assert!(services
            .iter()
            .all(|service| !service.owner_provider_id.trim().is_empty()));
        assert!(services
            .iter()
            .all(|service| !service.config.api_key_env.trim().is_empty()));
        assert_eq!(
            services
                .iter()
                .filter(|service| service.default_for_scenarios)
                .count(),
            1
        );
    }

    #[test]
    fn provider_install_metadata_comes_from_builtin_manifests() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");

        for provider in providers.iter().filter(|provider| provider.visible) {
            assert!(!provider.install.cli_names.is_empty());
            assert!(!provider.install.label.trim().is_empty());
            assert_eq!(provider.install.method, "npm");
            assert!(!provider.install.command.trim().is_empty());
            assert!(!provider.install.docs_url.trim().is_empty());
        }
    }

    #[test]
    fn normalize_ai_document_backfills_scenario_service_id() {
        let raw = r#"
schema_version: 2
ai:
  services:
    - id: openai_default
      name: OpenAI
      models:
        - gpt-5.4
      default_model: gpt-5.4
  scenarios:
    notification_summary:
      enabled: true
      service_id: ""
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        let scenario = doc
            .ai
            .expect("ai config")
            .scenarios
            .expect("scenarios")
            .remove("notification_summary")
            .expect("notification summary");

        assert_eq!(scenario.service_id, "openai_default");
    }

    #[test]
    fn normalize_ai_document_migrates_legacy_notification_summary_prompt() {
        let raw = r#"
schema_version: 2
ai:
  services:
    - id: openai_default
      name: OpenAI
      models:
        - gpt-5.4
      default_model: gpt-5.4
  scenarios:
    notification_summary:
      enabled: true
      service_id: openai_default
      output_schema: notification_summary_v1
      fallback: local_notification_summary_rules
      limits:
        preview_title: 16
      prompt_template: |
        You summarize OnlineWorker task completion notifications.
        Return compact JSON with preview_title and summary.
        preview_title identifies the completed task.
        summary explains the completed result.

        Current task:
        {{task_summary}}

        Final assistant message:
        {{final_message}}
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        let scenario = doc
            .ai
            .expect("ai config")
            .scenarios
            .expect("scenarios")
            .remove("notification_summary")
            .expect("notification summary");

        assert!(scenario
            .prompt_template
            .contains("complete short Chinese title"));
        assert!(!scenario.prompt_template.contains("Return compact JSON"));
    }

    #[test]
    fn notification_channel_metadata_reads_overlay_notification_plugin() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-notification-plugins-{}",
            std::process::id()
        ));
        let plugin_dir = dir.join("wechat");
        fs::create_dir_all(&plugin_dir).expect("create plugin dir");
        fs::write(
            plugin_dir.join("plugin.yaml"),
            r#"
schema_version: 1
id: wechat
kind: notification
label: WeChat
description: Custom WeChat notifier
default_enabled: false
entrypoints:
  python_descriptor: wechat.python.channel:create_notification_descriptor
"#,
        )
        .expect("write plugin manifest");
        set_test_process_env_override(
            NOTIFICATION_OVERLAY_ENV,
            Some(dir.to_string_lossy().to_string()),
        );

        let metadata = notification_channel_metadata_from_raw("", None).expect("metadata");

        set_test_process_env_override(NOTIFICATION_OVERLAY_ENV, None);
        let _ = fs::remove_dir_all(&dir);

        let wechat = metadata
            .iter()
            .find(|channel| channel.id == "wechat")
            .expect("wechat channel");
        assert_eq!(wechat.label, "WeChat");
        assert_eq!(wechat.description, "Custom WeChat notifier");
        assert!(!wechat.enabled);
        assert!(!wechat.builtin);
    }

    #[test]
    fn overlay_env_spec_from_env_raw_reads_trimmed_app_env_value() {
        let raw = r#"
TELEGRAM_TOKEN=token
ONLINEWORKER_PROVIDER_OVERLAY=  /tmp/private-overlay:/tmp/other-overlay
"#;

        assert_eq!(
            overlay_env_spec_from_env_raw(raw).as_deref(),
            Some("/tmp/private-overlay:/tmp/other-overlay")
        );
    }

    #[test]
    fn notification_overlay_env_spec_reads_process_env() {
        set_test_process_env_override(
            NOTIFICATION_OVERLAY_ENV,
            Some("/tmp/notification-overlay".to_string()),
        );

        assert_eq!(
            super::read_overlay_env_spec(NOTIFICATION_OVERLAY_ENV).as_deref(),
            Some("/tmp/notification-overlay")
        );

        set_test_process_env_override(NOTIFICATION_OVERLAY_ENV, None);
    }

    #[test]
    fn overlay_env_spec_from_env_raw_ignores_blank_value() {
        let raw = "ONLINEWORKER_PROVIDER_OVERLAY=   \n";

        assert_eq!(overlay_env_spec_from_env_raw(raw), None);
    }

    #[test]
    fn read_manifest_files_from_overlay_path_recurses_provider_plugins_directory() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-plugins-{}",
            std::process::id()
        ));
        let plugin_dir = dir.join("overlay-tool");
        fs::create_dir_all(&plugin_dir).expect("create plugin dir");
        fs::write(
            plugin_dir.join("plugin.yaml"),
            "schema_version: 1\nid: overlay-tool\nkind: provider\n",
        )
        .expect("write plugin manifest");

        let manifests = read_manifest_files_from_overlay_path(&dir);
        assert_eq!(manifests.len(), 1);
        assert!(manifests[0].source.contains("id: overlay-tool"));
        assert_eq!(manifests[0].path, plugin_dir.join("plugin.yaml"));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn set_provider_flags_enforces_managed_false_implies_autostart_false() {
        let raw = r#"
schema_version: 2
providers:
  custom:
managed: true
autostart: true
bin: "custom"
transport:
  type: "http"
  app_server_port: 4096
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_flags_in_document(&mut doc, "custom", false, true);

        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        assert_eq!(custom.managed, Some(false));
        assert_eq!(custom.autostart, Some(false));
    }

    #[test]
    fn set_provider_flags_preserves_unix_shared_transport_after_legacy_migration() {
        let provider_id = shared_unix_provider_id_for_test();
        let raw = format!(
            r#"
tools:
  - name: {provider_id}
    enabled: true
    bin: "{provider_id}"
    protocol: "ws"
    app_server_port: 4722
"#
        );

        let mut doc = normalize_provider_document(&raw).expect("normalized config");
        set_provider_flags_in_document(&mut doc, &provider_id, true, true);

        let providers = doc.providers.expect("providers");
        let provider = providers.get(&provider_id).expect("provider");
        let transport = provider.transport.as_ref().expect("provider transport");
        assert_eq!(transport.kind.as_deref(), Some("unix"));
        assert_eq!(transport.app_server_port, None);
        assert_eq!(transport.app_server_url.as_deref(), None);
        assert_eq!(provider.owner_transport.as_deref(), Some("unix"));
        assert_eq!(provider.live_transport.as_deref(), Some("shared_unix"));
    }

    #[test]
    fn provider_metadata_exposes_provider_message_hook_status_and_coverage() {
        let raw = r#"
schema_version: 2
providers:
  custom-a:
    managed: true
    message_hooks:
      abusive_language_normalization:
        enabled: true
  custom-b:
    managed: true
    message_hooks:
      abusive_language_normalization:
        enabled: false
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let custom_a = providers
            .iter()
            .find(|provider| provider.id == "custom-a")
            .expect("custom-a");
        let custom_b = providers
            .iter()
            .find(|provider| provider.id == "custom-b")
            .expect("custom-b");

        assert!(custom_a.message_hooks.abusive_language_normalization.enabled);
        assert!(!custom_b.message_hooks.abusive_language_normalization.enabled);
    }

    #[test]
    fn provider_metadata_exposes_provider_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "company-launcher start"
    external_cli:
      upstream_base_url: "https://upstream.example.test/provider"
      model: "deepseek-v4-pro[1m]"
      launches_managed_child_cli: true
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let custom = providers
            .iter()
            .find(|provider| provider.id == "custom")
            .expect("custom");

        assert_eq!(custom.bin.as_deref(), Some("company-launcher start"));
        assert_eq!(
            custom.external_cli.upstream_base_url.as_deref(),
            Some("https://upstream.example.test/provider")
        );
        assert_eq!(custom.external_cli.model.as_deref(), Some("deepseek-v4-pro[1m]"));
        assert!(custom.external_cli.launches_managed_child_cli);
    }

    #[test]
    fn set_provider_cli_config_updates_provider_bin_and_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "custom"
    external_cli:
      private_key: "keep"
      upstreamBaseUrl: "https://old.example.test"
      launchesManagedChildCli: false
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_cli_config_in_document(
            &mut doc,
            "custom",
            Some("company-launcher start".to_string()),
            ProviderExternalCliConfig {
                upstream_base_url: Some("https://upstream.example.test/provider".to_string()),
                auth_token: Some("sk-test-token".to_string()),
                model: Some("deepseek-v4-pro[1m]".to_string()),
                launches_managed_child_cli: true,
            },
            None,
        );

        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        assert_eq!(custom.bin.as_deref(), Some("company-launcher start"));

        let external_cli = custom.external_cli.as_ref().expect("external cli");
        assert_eq!(
            external_cli
                .get("upstream_base_url")
                .and_then(|value| value.as_str()),
            Some("https://upstream.example.test/provider")
        );
        assert_eq!(
            external_cli
                .get("auth_token")
                .and_then(|value| value.as_str()),
            Some("sk-test-token")
        );
        assert_eq!(
            external_cli
                .get("model")
                .and_then(|value| value.as_str()),
            Some("deepseek-v4-pro[1m]")
        );
        assert_eq!(
            external_cli
                .get("launches_managed_child_cli")
                .and_then(|value| value.as_bool()),
            Some(true)
        );
        assert_eq!(
            external_cli
                .get("private_key")
                .and_then(|value| value.as_str()),
            Some("keep")
        );
        assert!(external_cli.get("upstreamBaseUrl").is_none());
        assert!(external_cli.get("authToken").is_none());
        assert!(external_cli.get("launcherWrapsClaude").is_none());
    }

    #[test]
    fn provider_metadata_exposes_provider_launch_methods() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "custom"
    launch_methods:
      - id: native
        label: Native
        bin: "custom"
      - id: launcher
        label: Launcher
        bin: "/Users/example/bin/custom-launcher custom"
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let custom = providers
            .iter()
            .find(|provider| provider.id == "custom")
            .expect("custom");

        assert_eq!(custom.launch_methods.len(), 2);
        assert_eq!(custom.launch_methods[0].id, "native");
        assert_eq!(custom.launch_methods[0].label, "Native");
        assert_eq!(custom.launch_methods[0].bin, "custom");
        assert_eq!(custom.launch_methods[1].id, "launcher");
        assert_eq!(
            custom.launch_methods[1].bin,
            "/Users/example/bin/custom-launcher custom"
        );
    }

    #[test]
    fn set_provider_cli_config_updates_provider_launch_methods() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "custom"
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_cli_config_in_document(
            &mut doc,
            "custom",
            Some("custom".to_string()),
            ProviderExternalCliConfig::default(),
            Some(vec![
                ProviderLaunchMethodConfig {
                    id: "native".to_string(),
                    label: "Native".to_string(),
                    bin: "custom".to_string(),
                },
                ProviderLaunchMethodConfig {
                    id: "launcher".to_string(),
                    label: "Launcher".to_string(),
                    bin: "/Users/example/bin/custom-launcher custom".to_string(),
                },
            ]),
        );

        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        let launch_methods = custom.launch_methods.as_ref().expect("launch methods");

        assert_eq!(launch_methods.len(), 2);
        assert_eq!(launch_methods[0].id, "native");
        assert_eq!(launch_methods[0].bin, "custom");
        assert_eq!(launch_methods[1].id, "launcher");
        assert_eq!(
            launch_methods[1].bin,
            "/Users/example/bin/custom-launcher custom"
        );
    }

    #[test]
    fn set_provider_cli_config_with_launch_methods_does_not_create_empty_external_cli() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "custom"
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_cli_config_in_document(
            &mut doc,
            "custom",
            Some("custom".to_string()),
            ProviderExternalCliConfig::default(),
            Some(vec![ProviderLaunchMethodConfig {
                id: "primary".to_string(),
                label: "Primary".to_string(),
                bin: "custom".to_string(),
            }]),
        );

        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");

        assert!(custom.external_cli.is_none());
        assert_eq!(custom.bin.as_deref(), Some("custom"));
        assert_eq!(
            custom
                .launch_methods
                .as_ref()
                .expect("launch methods")
                .first()
                .map(|method| method.bin.as_str()),
            Some("custom")
        );
    }

    #[test]
    fn set_provider_message_hook_enabled_updates_provider_config() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_message_hook_enabled_in_document(
            &mut doc,
            "custom",
            "abusive_language_normalization",
            false,
        );

        let providers = doc.providers.expect("providers");
        let custom = providers.get("custom").expect("custom");
        let message_hooks = custom.message_hooks.as_ref().expect("message hooks");
        let hook = message_hooks
            .get("abusive_language_normalization")
            .expect("normalizer hook");
        assert_eq!(hook.enabled, Some(false));
    }

    #[test]
    fn normalize_provider_document_does_not_backfill_claude_auth_from_legacy_env() {
        let raw = r#"
tools:
  - name: codex
enabled: true
bin: "codex"
"#;
        let env_raw = "ANTHROPIC_API_KEY=dummy\nANTHROPIC_AUTH_TOKEN=token-123\nANTHROPIC_BASE_URL=https://runtime.example.test/langbase\nANTHROPIC_MODEL=claude-opus-4-6\n";

        let doc =
            normalize_provider_document_with_env(raw, Some(env_raw)).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let claude = providers.get("claude").expect("claude");
        assert!(claude.auth.as_ref().map(BTreeMap::is_empty).unwrap_or(true));
    }

    #[test]
    fn normalize_provider_document_removes_legacy_claude_auth_fields() {
        let raw = r#"
schema_version: 2
providers:
  claude:
    managed: false
    autostart: false
    auth:
      key: ""
      auth_token: ""
      base_url: "   "
      model: ""
"#;
        let env_raw = "ANTHROPIC_API_KEY=dummy\nANTHROPIC_AUTH_TOKEN=token-123\nANTHROPIC_BASE_URL=https://runtime.example.test/langbase\nANTHROPIC_MODEL=claude-opus-4-6\n";

        let doc =
            normalize_provider_document_with_env(raw, Some(env_raw)).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let claude = providers.get("claude").expect("claude");
        assert!(claude.auth.as_ref().map(BTreeMap::is_empty).unwrap_or(true));
    }

    #[test]
    fn normalize_config_for_display_renders_legacy_tools_as_provider_schema() {
        let provider_id = "custom";
        let raw = r#"
tools:
  - name: custom
    enabled: true
    bin: "custom"
    protocol: "ws"
    app_server_port: 4722

logging:
  level: "INFO"
"#;

        let rendered = normalize_config_for_display(raw, None);
        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");

        assert!(doc.get("tools").is_none());
        assert_eq!(
            doc.get("schema_version").and_then(|value| value.as_i64()),
            Some(2)
        );
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get(provider_id))
                .and_then(|provider| provider.get("owner_transport"))
                .and_then(|value| value.as_str()),
            Some("ws")
        );
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get(provider_id))
                .and_then(|provider| provider.get("live_transport"))
                .and_then(|value| value.as_str()),
            Some("ws")
        );
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get(provider_id))
                .and_then(|provider| provider.get("transport"))
                .and_then(|transport| transport.get("type"))
                .and_then(|value| value.as_str()),
            Some("ws")
        );
        assert_eq!(
            doc.get("logging")
                .and_then(|logging| logging.get("level"))
                .and_then(|value| value.as_str()),
            Some("INFO")
        );
    }

    #[test]
    fn serialize_normalized_config_with_env_rejects_invalid_yaml() {
        let raw = "tools:\n  - name: custom\n    enabled: [";

        let error =
            serialize_normalized_config_with_env(raw, None).expect_err("invalid yaml should fail");

        assert!(error.contains("Cannot parse config.yaml"));
    }

    #[test]
    fn normalize_config_for_display_backfills_visible_public_providers() {
        let raw = r#"
tools:
  - name: custom
enabled: true
bin: "custom"
"#;

        let rendered = normalize_config_for_display(raw, None);
        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");

        for provider_id in public_default_provider_ids() {
            assert!(doc
                .get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .is_some());
        }
    }

    #[test]
    fn serialize_normalized_config_keeps_readable_defaults_without_icon_data_urls() {
        let rendered = serialize_normalized_config_with_env("", None).expect("rendered yaml");

        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");

        assert_eq!(
            doc.get("schema_version").and_then(|value| value.as_i64()),
            Some(2)
        );
        assert!(doc.get("providers").is_some());
        assert!(doc.get("notifications").is_some());
        assert!(doc.get("ai").is_some());
        assert!(!rendered.contains("data:image/svg+xml;base64,"));
    }

    #[test]
    fn serialize_normalized_config_preserves_default_ai_and_notification_state() {
        let rendered = build_default_user_config_with_env(None).expect("rendered yaml");
        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");

        assert_eq!(
            doc.get("schema_version").and_then(|value| value.as_i64()),
            Some(2)
        );
        assert!(doc.get("providers").is_some());
        assert!(doc.get("notifications").is_some());
        assert!(doc.get("ai").is_some());
        for provider_id in public_default_provider_ids() {
            let metadata = provider_default_metadata(&provider_id);
            assert_eq!(
                doc.get("providers")
                    .and_then(|providers| providers.get(&provider_id))
                    .and_then(|provider| provider.get("owner_transport"))
                    .and_then(|value| value.as_str()),
                Some(metadata.transport.owner.as_str())
            );
        }
    }

    #[test]
    fn serialize_normalized_config_keeps_full_ai_service_fields() {
        let raw = r#"
schema_version: 2
ai:
  services:
    - id: openai_default
      name: OpenAI
      protocol: openai_compatible_chat
      base_url: https://api.openai.com/v1
      models:
        - gpt-5.4
      default_model: gpt-5.4
      timeout_seconds: 20
      enabled: true
  scenarios:
    notification_summary:
      enabled: false
      service_id: openai_default
      output_schema: notification_summary_v1
      fallback: local_notification_summary_rules
      limits:
        preview_title: 16
"#;

        let rendered = serialize_normalized_config_with_env(raw, None).expect("rendered yaml");
        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");
        let services = doc
            .get("ai")
            .and_then(|ai| ai.get("services"))
            .and_then(|services| services.as_sequence())
            .expect("services");
        let openai = services
            .iter()
            .find(|service| {
                service.get("id").and_then(|value| value.as_str()) == Some("openai_default")
            })
            .expect("openai_default service");

        assert!(services.len() >= 2);
        assert_eq!(
            openai.get("enabled").and_then(|value| value.as_bool()),
            Some(true)
        );
        assert_eq!(
            openai.get("name").and_then(|value| value.as_str()),
            Some("OpenAI")
        );
        assert!(doc.get("ai").and_then(|ai| ai.get("scenarios")).is_some());
    }

    #[test]
    fn serialize_normalized_config_preserves_explicit_icon_urls() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    autostart: false
    bin: "custom"
    icon:
      url: "https://example.test/custom.svg"
"#;

        let rendered = serialize_normalized_config_with_env(raw, None).expect("rendered yaml");

        assert!(rendered.contains("https://example.test/custom.svg"));
    }

    #[test]
    fn provider_metadata_exposes_manifest_runtime_id() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        for provider_id in public_default_provider_ids() {
            let provider = providers
                .iter()
                .find(|provider| provider.id == provider_id)
                .expect("provider");
            assert_eq!(provider.runtime_id, provider.id);
        }
    }

    #[test]
    fn provider_metadata_exposes_manifest_icon_data_urls() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        for provider_id in public_default_provider_ids() {
            let provider = providers
                .iter()
                .find(|provider| provider.id == provider_id)
                .expect("provider");
            let icon = provider.icon.as_ref().expect("provider icon");
            assert_eq!(icon.path, "icon.svg");
            assert!(icon.url.starts_with("data:image/svg+xml;base64,"));
            assert!(icon.source.contains("simpleicons"));
        }
    }

    #[test]
    fn provider_metadata_exposes_manifest_capabilities() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        for provider_id in public_default_provider_ids() {
            let provider = providers
                .iter()
                .find(|provider| provider.id == provider_id)
                .expect("provider");
            assert!(provider.capabilities.sessions);
            assert!(provider.capabilities.send);
            assert!(provider.capabilities.commands);
            assert!(provider.capabilities.files);
            assert_eq!(provider.capabilities.session_access.list, "owner_bridge");
            assert_eq!(provider.capabilities.session_access.read, "owner_bridge");
            assert_eq!(provider.capabilities.session_access.send, "owner_bridge");
        }
    }

    #[test]
    fn provider_metadata_uses_manifest_message_hook_defaults() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let public_providers = public_default_provider_ids();
        assert_eq!(
            providers
                .iter()
                .filter(|provider| public_providers.contains(&provider.id))
                .count(),
            public_providers.len()
        );
    }

    #[test]
    fn provider_metadata_includes_hidden_overlay_provider_in_catalog() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-hidden-provider-catalog-{}",
            std::process::id()
        ));
        let plugin_dir = dir.join("hidden-provider");
        fs::create_dir_all(&plugin_dir).expect("create plugin dir");
        fs::write(
            plugin_dir.join("plugin.yaml"),
            r#"
schema_version: 1
id: hidden-provider
kind: provider
visibility: private
label: Hidden Provider
default_visible: false
provider:
  visible: false
  managed: false
  autostart: false
  bin: hidden-provider
"#,
        )
        .expect("write plugin manifest");
        set_test_process_env_override(
            PROVIDER_OVERLAY_ENV,
            Some(dir.to_string_lossy().to_string()),
        );

        let providers = provider_metadata_from_raw("", None).expect("metadata");

        set_test_process_env_override(PROVIDER_OVERLAY_ENV, None);
        let _ = fs::remove_dir_all(&dir);

        let hidden_provider = providers
            .iter()
            .find(|provider| provider.id == "hidden-provider")
            .expect("hidden provider");
        assert_eq!(hidden_provider.label, "Hidden Provider");
        assert!(!hidden_provider.visible);
        assert!(!hidden_provider.managed);
        assert_eq!(hidden_provider.bin.as_deref(), Some("hidden-provider"));
    }

    #[test]
    fn provider_metadata_backfills_new_message_rewrite_fields_for_existing_config() {
        let provider_id = public_default_provider_ids()
            .into_iter()
            .find(|provider_id| {
                let metadata = provider_default_metadata(provider_id);
                metadata.capabilities.message_rewrite.external_cli.is_some()
                    && metadata.capabilities.message_rewrite.wrapper.is_some()
            })
            .expect("message rewrite provider");
        let raw = format!(
            r#"
schema_version: 2
providers:
  {provider_id}:
    managed: true
    autostart: true
    capabilities:
      sessions: true
      send: true
      commands: true
      approvals: true
      questions: false
      photos: true
      files: true
      commandWrappers:
        - model
        - review
      controlModes:
        - app
        - tui
        - hybrid
      messageRewrite:
        appSend: false
        telegram: false
"#
        );

        let providers = provider_metadata_from_raw(&raw, None).expect("metadata");
        let provider = providers
            .iter()
            .find(|provider| provider.id == provider_id)
            .expect("provider");
        let defaults = provider_default_metadata(&provider_id);

        assert!(provider.capabilities.message_rewrite.app_send);
        assert!(provider.capabilities.message_rewrite.telegram);
        assert_eq!(
            provider.capabilities.message_rewrite.external_cli.as_deref(),
            defaults.capabilities.message_rewrite.external_cli.as_deref()
        );
        assert_eq!(
            provider.capabilities.message_rewrite.wrapper.as_deref(),
            defaults.capabilities.message_rewrite.wrapper.as_deref()
        );
        assert_eq!(provider.capabilities.session_access.read, "owner_bridge");
        assert_eq!(provider.capabilities.session_access.list, "owner_bridge");
        assert_eq!(provider.capabilities.session_access.send, "owner_bridge");
    }

    #[test]
    fn normalize_provider_document_preserves_provider_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  custom:
    managed: true
    bin: "company-launcher start"
    external_cli:
      upstream_base_url: "https://upstream.example.test/provider"
      launches_managed_child_cli: true
"#;

        let rendered = serialize_normalized_config_with_env(raw, None).expect("rendered yaml");

        assert!(rendered.contains("external_cli:"));
        assert!(rendered.contains("upstream_base_url: https://upstream.example.test/provider"));
        assert!(rendered.contains("launches_managed_child_cli: true"));
    }

    #[test]
    fn config_provider_defaults_are_not_static_provider_matches() {
        let source = include_str!("config_provider.rs");

        for provider_id in provider_assets::builtin_provider_assets()
            .iter()
            .filter_map(|asset| asset.id())
        {
            assert!(!source.contains(&format!("\"{}\" => ProviderConfigEntry", provider_id)));
        }
        assert!(!source.contains(&format!("const {}", "PUBLIC_DEFAULT_PROVIDER_IDS")));
    }
}
