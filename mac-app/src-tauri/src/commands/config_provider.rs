use base64::Engine;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use super::config::app_support_dir_name;

#[path = "config_provider/ai_config_store.rs"]
mod ai_config_store;
pub(super) use ai_config_store::set_ai_config_in_document;
use ai_config_store::{ai_metadata_from_document, normalize_ai_document};

const BUILTIN_CODEX_PLUGIN_MANIFEST: &str =
    include_str!("../../../../plugins/providers/builtin/codex/plugin.yaml");
const BUILTIN_CLAUDE_PLUGIN_MANIFEST: &str =
    include_str!("../../../../plugins/providers/builtin/claude/plugin.yaml");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST: &str =
    include_str!("../../../../plugins/notifications/builtin/telegram/plugin.yaml");
const BUILTIN_CODEX_PLUGIN_ICON: &str =
    include_str!("../../../../plugins/providers/builtin/codex/icon.svg");
const BUILTIN_CLAUDE_PLUGIN_ICON: &str =
    include_str!("../../../../plugins/providers/builtin/claude/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_ICON: &str =
    include_str!("../../../../plugins/notifications/builtin/telegram/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_ZH: &str =
    include_str!("../../../../plugins/notifications/builtin/telegram/guides/setup.zh-CN.html");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_EN: &str =
    include_str!("../../../../plugins/notifications/builtin/telegram/guides/setup.en-US.html");
const PROVIDER_OVERLAY_ENV: &str = "ONLINEWORKER_PROVIDER_OVERLAY";
const NOTIFICATION_OVERLAY_ENV: &str = "ONLINEWORKER_NOTIFICATION_OVERLAY";

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
    #[serde(default, alias = "launcher_wraps_claude")]
    pub(crate) launcher_wraps_claude: bool,
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

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
struct NotificationSettingsManifest {
    fields: Option<Vec<NotificationSettingsField>>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct NotificationSetupGuide {
    #[serde(rename = "type", default)]
    pub(crate) kind: String,
    #[serde(default)]
    pub(crate) assets: BTreeMap<String, String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug)]
struct NotificationSetupGuideManifest {
    #[serde(rename = "type", default)]
    kind: String,
    #[serde(default)]
    assets: BTreeMap<String, String>,
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
    #[serde(alias = "codexBin", skip_serializing_if = "Option::is_none")]
    codex_bin: Option<String>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) capabilities: Option<ProviderCapabilitiesEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) message_hooks: Option<BTreeMap<String, ProviderMessageHookEntry>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) install: Option<ProviderInstallEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) process: Option<ProviderProcessEntry>,
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
    #[serde(default, alias = "command_wrappers")]
    pub(crate) command_wrappers: Vec<String>,
    #[serde(default, alias = "control_modes")]
    pub(crate) control_modes: Vec<String>,
    #[serde(default, alias = "message_rewrite")]
    pub(crate) message_rewrite: ProviderMessageRewriteCapabilities,
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
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderInstallEntry {
    #[serde(default)]
    pub(crate) cli_names: Vec<String>,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct ProviderProcessEntry {
    #[serde(default, alias = "cleanup_matchers")]
    pub(crate) cleanup_matchers: Vec<String>,
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
    pub(crate) managed: bool,
    pub(crate) autostart: bool,
    pub(crate) bin: Option<String>,
    pub(crate) transport: ProviderTransportMetadata,
    pub(crate) live_transport: String,
    pub(crate) control_mode: Option<String>,
    pub(crate) capabilities: ProviderCapabilitiesEntry,
    pub(crate) message_hooks: ProviderMessageHooksMetadata,
    pub(crate) external_cli: ProviderExternalCliConfig,
    pub(crate) install: ProviderInstallEntry,
    pub(crate) process: ProviderProcessEntry,
    pub(crate) icon: Option<ProviderIconEntry>,
}

fn normalize_transport_kind(raw: Option<&str>) -> Option<String> {
    raw.and_then(|value| {
        let trimmed = value.trim().to_lowercase();
        match trimmed.as_str() {
            "stdio" | "ws" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn normalize_live_transport_kind(raw: Option<&str>) -> Option<String> {
    raw.and_then(|value| {
        let trimmed = value.trim().to_lowercase();
        match trimmed.as_str() {
            "owner_bridge" | "shared_ws" | "stdio" | "ws" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn default_owner_transport(provider_id: &str) -> String {
    default_provider_config(provider_id)
        .owner_transport
        .unwrap_or_else(|| "stdio".to_string())
}

fn default_live_transport(
    provider_id: &str,
    owner_transport: &str,
    _control_mode: Option<&str>,
) -> String {
    let defaults = default_provider_config(provider_id);
    if defaults.owner_transport.as_deref() == Some(owner_transport) {
        if let Some(live_transport) = defaults.live_transport {
            return live_transport;
        }
    }
    owner_transport.to_string()
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
    codex_bin: Option<String>,
    protocol: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
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
    process: Option<ProviderProcessEntry>,
}

#[derive(Clone, Debug)]
struct ProviderPluginDefault {
    id: String,
    visibility: String,
    order: u32,
    config: ProviderConfigEntry,
}

#[derive(Clone, Debug)]
struct ProviderPluginManifestSource {
    source: String,
    path: PathBuf,
}

#[derive(Clone, Debug)]
struct NotificationPluginDefault {
    id: String,
    label: String,
    description: String,
    default_enabled: bool,
    builtin: bool,
    order: u32,
    settings_fields: Vec<NotificationSettingsField>,
    icon: Option<ProviderIconEntry>,
    setup_guide: Option<NotificationSetupGuide>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct NotificationPluginManifest {
    id: String,
    kind: Option<String>,
    order: Option<u32>,
    label: Option<String>,
    description: Option<String>,
    default_enabled: Option<bool>,
    icon: Option<ProviderIconEntry>,
    #[serde(skip)]
    manifest_path: Option<PathBuf>,
    settings: Option<NotificationSettingsManifest>,
    setup_guide: Option<NotificationSetupGuideManifest>,
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
    vec![
        ProviderPluginManifestSource {
            source: BUILTIN_CLAUDE_PLUGIN_MANIFEST.to_string(),
            path: plugin_root
                .join("builtin")
                .join("claude")
                .join("plugin.yaml"),
        },
        ProviderPluginManifestSource {
            source: BUILTIN_CODEX_PLUGIN_MANIFEST.to_string(),
            path: plugin_root
                .join("builtin")
                .join("codex")
                .join("plugin.yaml"),
        },
    ]
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
        source: BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST.to_string(),
        path: plugin_root
            .join("builtin")
            .join("telegram")
            .join("plugin.yaml"),
    }]
}

fn notification_plugin_default_list() -> Vec<NotificationPluginDefault> {
    let mut defaults = Vec::new();
    for manifest_source in notification_plugin_manifest_sources_with_paths() {
        let Ok(mut manifest) =
            serde_yaml::from_str::<NotificationPluginManifest>(&manifest_source.source)
        else {
            continue;
        };
        manifest.manifest_path = Some(manifest_source.path.clone());
        if manifest.kind.as_deref() != Some("notification") {
            continue;
        }
        let notification_id = manifest.id.trim().to_string();
        if notification_id.is_empty() {
            continue;
        }
        let builtin = manifest_source
            .path
            .components()
            .any(|component| component.as_os_str() == "builtin");
        defaults.push(NotificationPluginDefault {
            id: notification_id.clone(),
            label: manifest.label.unwrap_or_else(|| notification_id.clone()),
            description: manifest.description.unwrap_or_default(),
            default_enabled: manifest.default_enabled.unwrap_or(true),
            builtin,
            order: manifest.order.unwrap_or(u32::MAX),
            settings_fields: normalize_notification_settings_fields(
                manifest
                    .settings
                    .and_then(|settings| settings.fields)
                    .unwrap_or_default(),
            ),
            icon: resolve_notification_icon(
                manifest.icon,
                manifest.manifest_path.as_deref(),
                &notification_id,
            ),
            setup_guide: resolve_notification_setup_guide(
                manifest.setup_guide,
                manifest.manifest_path.as_deref(),
                &notification_id,
            ),
        });
    }
    defaults.sort_by(|left, right| {
        left.order
            .cmp(&right.order)
            .then_with(|| left.id.cmp(&right.id))
    });
    defaults
}

fn normalize_notification_settings_fields(
    fields: Vec<NotificationSettingsField>,
) -> Vec<NotificationSettingsField> {
    fields
        .into_iter()
        .filter_map(|mut field| {
            field.key = field.key.trim().to_string();
            if field.key.is_empty() {
                return None;
            }
            field.label = if field.label.trim().is_empty() {
                field.key.clone()
            } else {
                field.label.trim().to_string()
            };
            field.kind = normalize_notification_field_type(&field.kind);
            field.description = field.description.trim().to_string();
            for option in field.options.iter_mut() {
                option.value = option.value.trim().to_string();
                if option.label.trim().is_empty() {
                    option.label = option.value.clone();
                } else {
                    option.label = option.label.trim().to_string();
                }
            }
            Some(field)
        })
        .collect()
}

fn normalize_notification_field_type(kind: &str) -> String {
    match kind.trim() {
        "string" | "number" | "boolean" | "select" | "secret" => kind.trim().to_string(),
        _ => "string".to_string(),
    }
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
                builtin_provider_icon_svg(provider_id).map(|svg| svg.as_bytes().to_vec())
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

fn builtin_provider_icon_svg(provider_id: &str) -> Option<&'static str> {
    match provider_id {
        "codex" => Some(BUILTIN_CODEX_PLUGIN_ICON),
        "claude" => Some(BUILTIN_CLAUDE_PLUGIN_ICON),
        _ => None,
    }
}

fn resolve_notification_icon(
    icon: Option<ProviderIconEntry>,
    manifest_path: Option<&Path>,
    notification_id: &str,
) -> Option<ProviderIconEntry> {
    let mut icon = resolve_provider_icon(icon, manifest_path, notification_id)?;
    if icon.url.trim().is_empty() && icon.path.trim() == "icon.svg" {
        if let Some(svg) = builtin_notification_icon_svg(notification_id) {
            let encoded = base64::engine::general_purpose::STANDARD.encode(svg);
            icon.url = format!("data:image/svg+xml;base64,{encoded}");
            icon.generated_url = true;
        }
    }
    Some(icon)
}

fn builtin_notification_icon_svg(notification_id: &str) -> Option<&'static str> {
    match notification_id {
        "telegram" => Some(BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_ICON),
        _ => None,
    }
}

fn resolve_notification_setup_guide(
    guide: Option<NotificationSetupGuideManifest>,
    manifest_path: Option<&Path>,
    notification_id: &str,
) -> Option<NotificationSetupGuide> {
    let guide = guide?;
    if guide.kind.trim() != "html" {
        return None;
    }
    let mut assets = BTreeMap::new();
    for (locale, asset_path) in guide.assets {
        let locale = locale.trim().to_string();
        if locale.is_empty() {
            continue;
        }
        if let Some(html) =
            read_notification_guide_asset(notification_id, manifest_path, asset_path.trim())
        {
            assets.insert(locale, html);
        }
    }
    if assets.is_empty() {
        None
    } else {
        Some(NotificationSetupGuide {
            kind: "html".to_string(),
            assets,
        })
    }
}

fn read_notification_guide_asset(
    notification_id: &str,
    manifest_path: Option<&Path>,
    asset_path: &str,
) -> Option<String> {
    if !is_safe_relative_asset_path(asset_path) {
        return None;
    }
    let file_asset = manifest_path.and_then(Path::parent).and_then(|dir| {
        let base = dir.canonicalize().ok()?;
        let target = dir.join(asset_path).canonicalize().ok()?;
        if !target.starts_with(&base) || !target.is_file() {
            return None;
        }
        fs::read_to_string(target).ok()
    });
    file_asset.or_else(|| {
        builtin_notification_guide_html(notification_id, asset_path).map(str::to_string)
    })
}

fn is_safe_relative_asset_path(asset_path: &str) -> bool {
    let path = Path::new(asset_path);
    !asset_path.trim().is_empty()
        && path.is_relative()
        && path.components().all(|component| {
            matches!(
                component,
                std::path::Component::Normal(_) | std::path::Component::CurDir
            )
        })
}

fn builtin_notification_guide_html(
    notification_id: &str,
    asset_path: &str,
) -> Option<&'static str> {
    match (notification_id, asset_path) {
        ("telegram", "guides/setup.zh-CN.html") => Some(BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_ZH),
        ("telegram", "guides/setup.en-US.html") => Some(BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_EN),
        _ => None,
    }
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
            message_hooks: None,
            install: Some(ProviderInstallEntry {
                cli_names: vec![install_cli_name],
            }),
            process: Some(provider.process.unwrap_or_default()),
            icon: resolve_provider_icon(
                manifest.icon,
                manifest.manifest_path.as_deref(),
                &provider_id,
            ),
            ..ProviderConfigEntry::default()
        },
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
        install: Some(ProviderInstallEntry {
            cli_names: vec![provider_id.to_string()],
        }),
        process: Some(ProviderProcessEntry::default()),
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
        if url.starts_with("ws://") || url.starts_with("wss://") {
            return "ws".to_string();
        }
        if url.starts_with("http://") || url.starts_with("https://") {
            return "http".to_string();
        }
    }
    let default_transport = default_owner_transport(tool_name);
    if raw_port.unwrap_or(0) > 0 && default_transport == "stdio" {
        "ws".to_string()
    } else {
        default_transport
    }
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
        .or(provider.codex_bin.take())
        .or(defaults.bin);
    let control_mode = provider.control_mode.take().or(defaults.control_mode);
    provider.auth = if provider_id == "claude" {
        None
    } else {
        provider.auth.take().or(defaults.auth)
    };

    let mut transport = provider.transport.take().unwrap_or_default();
    let default_transport = defaults.transport.unwrap_or_default();
    let owner_transport = normalize_transport_kind(provider.owner_transport.as_deref())
        .or_else(|| normalize_transport_kind(transport.kind.as_deref()))
        .or_else(|| normalize_transport_kind(provider.protocol.as_deref()))
        .or_else(|| normalize_transport_kind(default_transport.kind.as_deref()))
        .unwrap_or_else(|| default_owner_transport(provider_id));

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
    }

    let live_transport = normalize_live_transport_kind(provider.live_transport.as_deref())
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
    provider.install = provider.install.take().or(defaults.install);
    provider.process = provider.process.take().or(defaults.process);
    provider.icon = merge_provider_icon(provider.icon.take(), defaults.icon);
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
            Some(capabilities)
        }
        (Some(capabilities), None) => Some(capabilities),
        (None, Some(default_capabilities)) => Some(default_capabilities),
        (None, None) => None,
    }
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
    rewrite
}

fn legacy_tool_to_provider(tool: LegacyToolConfig) -> ProviderConfigEntry {
    let mut provider = default_provider_config(&tool.name);
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
    if default_owner_transport(&tool.name) == "stdio"
        && explicit_protocol.as_deref() == Some("ws")
        && app_server_url.as_deref().unwrap_or("").is_empty()
        && raw_port.unwrap_or(0) == 4722
        && explicit_control_mode
            .as_deref()
            .map(str::trim)
            .unwrap_or("")
            .is_empty()
    {
        owner_transport = "stdio".to_string();
        port = None;
    }
    if !managed {
        autostart = false;
    }
    if owner_transport == "stdio" {
        port = None;
    }

    let control_mode = tool.control_mode.or(provider.control_mode);
    let live_transport =
        default_live_transport(&tool.name, &owner_transport, control_mode.as_deref());

    provider.managed = Some(managed);
    provider.autostart = Some(autostart);
    provider.bin = tool.codex_bin.or(provider.bin);
    provider.control_mode = control_mode;
    provider.owner_transport = Some(owner_transport.clone());
    provider.live_transport = Some(live_transport);
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

fn normalize_notification_document(doc: &mut ProviderConfigDocument) {
    let notifications = doc
        .notifications
        .get_or_insert_with(NotificationConfigDocument::default);
    let channels = notifications.channels.get_or_insert_with(BTreeMap::new);

    for default in notification_plugin_default_list() {
        let channel = channels
            .entry(default.id.clone())
            .or_insert_with(NotificationChannelConfigEntry::default);
        channel.enabled = Some(channel.enabled.unwrap_or(default.default_enabled));
        channel.label.get_or_insert_with(|| default.label.clone());
        channel
            .description
            .get_or_insert_with(|| default.description.clone());
        channel.config.get_or_insert_with(BTreeMap::new);
    }

    for (channel_id, channel) in channels.iter_mut() {
        channel.enabled = Some(channel.enabled.unwrap_or(false));
        channel.label.get_or_insert_with(|| channel_id.to_string());
        channel.description.get_or_insert_with(String::new);
        channel.config.get_or_insert_with(BTreeMap::new);
    }
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
        install: provider.install.clone().unwrap_or_default(),
        process: provider.process.clone().unwrap_or_default(),
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
        launcher_wraps_claude: config
            .get("launcher_wraps_claude")
            .and_then(value_as_bool)
            .or_else(|| config.get("launcherWrapsClaude").and_then(value_as_bool))
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

pub(crate) fn notification_channel_metadata_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<Vec<NotificationChannelMetadata>, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    let channels = doc
        .notifications
        .and_then(|notifications| notifications.channels)
        .unwrap_or_default();

    let mut ordered = Vec::new();
    let plugin_defaults = notification_plugin_default_list();
    for default in &plugin_defaults {
        if let Some(channel) = channels.get(&default.id) {
            ordered.push(notification_channel_metadata_from_entry(
                &default.id,
                channel,
                &default.label,
                &default.description,
                default.builtin,
                default.settings_fields.clone(),
                default.icon.clone(),
                default.setup_guide.clone(),
            ));
        }
    }

    for (channel_id, channel) in channels {
        if plugin_defaults
            .iter()
            .any(|default| default.id == channel_id)
        {
            continue;
        }
        let label = channel.label.as_deref().unwrap_or(&channel_id);
        let description = channel.description.as_deref().unwrap_or("");
        ordered.push(notification_channel_metadata_from_entry(
            &channel_id,
            &channel,
            label,
            description,
            false,
            Vec::new(),
            None,
            None,
        ));
    }

    Ok(ordered)
}

pub(crate) fn ai_config_metadata_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<AiConfigMetadata, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    Ok(ai_metadata_from_document(doc))
}

fn notification_channel_metadata_from_entry(
    channel_id: &str,
    channel: &NotificationChannelConfigEntry,
    default_label: &str,
    default_description: &str,
    builtin: bool,
    settings_fields: Vec<NotificationSettingsField>,
    icon: Option<ProviderIconEntry>,
    setup_guide: Option<NotificationSetupGuide>,
) -> NotificationChannelMetadata {
    NotificationChannelMetadata {
        id: channel_id.to_string(),
        label: channel
            .label
            .clone()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| default_label.to_string()),
        description: channel
            .description
            .clone()
            .unwrap_or_else(|| default_description.to_string()),
        enabled: channel.enabled.unwrap_or(false),
        builtin,
        config: channel.config.clone().unwrap_or_default(),
        settings_fields,
        icon,
        setup_guide,
    }
}

fn explicit_provider_ids_from_raw(raw: &str) -> BTreeSet<String> {
    let Ok(doc) = serde_yaml::from_str::<ProviderConfigDocument>(raw) else {
        return BTreeSet::new();
    };

    let mut provider_ids = BTreeSet::new();
    if let Some(providers) = doc.providers {
        provider_ids.extend(providers.into_keys());
    }
    if let Some(tools) = doc.tools {
        provider_ids.extend(
            tools
                .into_iter()
                .map(|tool| tool.name.trim().to_string())
                .filter(|name| !name.is_empty()),
        );
    }
    provider_ids
}

fn prune_implicit_hidden_providers(doc: &mut ProviderConfigDocument, raw: &str) {
    let explicit_ids = explicit_provider_ids_from_raw(raw);
    let Some(providers) = doc.providers.as_mut() else {
        return;
    };

    for provider_id in hidden_provider_ids() {
        if !explicit_ids.contains(&provider_id) {
            providers.remove(&provider_id);
        }
    }

    if providers.is_empty() {
        doc.providers = None;
    }
}

pub(super) fn serialize_config_document_for_persistence(
    mut doc: ProviderConfigDocument,
    raw: &str,
) -> Result<String, String> {
    prune_implicit_hidden_providers(&mut doc, raw);
    prune_runtime_icon_urls(&mut doc);
    serde_yaml::to_string(&doc).map_err(|e| format!("Cannot serialize config.yaml: {}", e))
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
    serialize_normalized_config_with_env(raw, env_raw).unwrap_or_else(|_| raw.to_string())
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

    let config = provider.external_cli.get_or_insert_with(BTreeMap::new);
    config.remove("upstreamBaseUrl");
    config.remove("launcherWrapsClaude");

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

    config.insert(
        "launcher_wraps_claude".to_string(),
        serde_yaml::Value::Bool(external_cli.launcher_wraps_claude),
    );

    if config.is_empty() {
        provider.external_cli = None;
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
        normalize_config_for_display, normalize_provider_document,
        normalize_provider_document_with_env, notification_channel_metadata_from_raw,
        overlay_env_spec_from_env_raw, provider_metadata_from_raw,
        read_manifest_files_from_overlay_path, serialize_normalized_config_with_env,
        set_ai_config_in_document, set_notification_channel_config_in_document,
        set_notification_channel_enabled_in_document, set_provider_cli_config_in_document,
        set_provider_flags_in_document, set_provider_message_hook_enabled_in_document,
        set_test_process_env_override, AiScenarioConfigEntry, AiServiceConfigEntry,
        ProviderCapabilitiesEntry, ProviderExternalCliConfig, NOTIFICATION_OVERLAY_ENV,
    };

    #[test]
    fn normalize_provider_document_migrates_legacy_tools_and_backfills_claude() {
        let raw = r#"
tools:
  - name: codex
enabled: true
codex_bin: "codex"
protocol: "ws"
app_server_port: 4722
"#;

        let doc = normalize_provider_document(raw).expect("normalized config");
        assert_eq!(doc.schema_version, Some(2));

        let providers = doc.providers.expect("providers");
        let codex = providers.get("codex").expect("codex");
        assert_eq!(codex.managed, Some(true));
        assert_eq!(codex.autostart, Some(true));
        assert_eq!(codex.bin.as_deref(), Some("codex"));
        let transport = codex.transport.as_ref().expect("codex transport");
        assert_eq!(transport.kind.as_deref(), Some("stdio"));
        assert_eq!(transport.app_server_port, None);
        assert_eq!(codex.owner_transport.as_deref(), Some("stdio"));
        assert_eq!(codex.live_transport.as_deref(), Some("owner_bridge"));

        let claude = providers.get("claude").expect("claude");
        assert_eq!(claude.managed, Some(false));
        assert_eq!(claude.autostart, Some(false));
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
        assert_eq!(metadata[1].id, "wechat");
        assert_eq!(metadata[1].label, "WeChat");
        assert_eq!(metadata[1].description, "Custom WeChat notifier");
        assert!(metadata[1].enabled);
        assert!(!metadata[1].builtin);
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
    fn set_provider_flags_preserves_codex_stdio_owner_bridge_after_legacy_migration() {
        let raw = r#"
tools:
  - name: codex
enabled: true
codex_bin: "codex"
protocol: "ws"
app_server_port: 4722
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_flags_in_document(&mut doc, "codex", true, true);

        let providers = doc.providers.expect("providers");
        let codex = providers.get("codex").expect("codex");
        let transport = codex.transport.as_ref().expect("codex transport");
        assert_eq!(transport.kind.as_deref(), Some("stdio"));
        assert_eq!(transport.app_server_port, None);
        assert_eq!(transport.app_server_url.as_deref(), None);
        assert_eq!(codex.owner_transport.as_deref(), Some("stdio"));
        assert_eq!(codex.live_transport.as_deref(), Some("owner_bridge"));
    }

    #[test]
    fn provider_metadata_exposes_provider_message_hook_status_and_coverage() {
        let raw = r#"
schema_version: 2
providers:
  codex:
    managed: true
    message_hooks:
      abusive_language_normalization:
        enabled: true
  claude:
    managed: true
    message_hooks:
      abusive_language_normalization:
        enabled: false
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");
        let claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude");

        assert!(codex.message_hooks.abusive_language_normalization.enabled);
        assert_eq!(
            codex.capabilities.message_rewrite.external_cli.as_deref(),
            Some("remote_proxy")
        );
        assert_eq!(
            codex.capabilities.message_rewrite.wrapper.as_deref(),
            Some("ow-codex")
        );
        assert!(!claude.message_hooks.abusive_language_normalization.enabled);
        assert_eq!(
            claude.capabilities.message_rewrite.external_cli.as_deref(),
            Some("http_proxy")
        );
        assert_eq!(
            claude.capabilities.message_rewrite.wrapper.as_deref(),
            Some("ow-claude")
        );
    }

    #[test]
    fn provider_metadata_exposes_provider_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  claude:
    managed: true
    bin: "company-launcher start"
    external_cli:
      upstream_base_url: "https://upstream.example.test/anthropic"
      launcher_wraps_claude: true
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude");

        assert_eq!(claude.bin.as_deref(), Some("company-launcher start"));
        assert_eq!(
            claude.external_cli.upstream_base_url.as_deref(),
            Some("https://upstream.example.test/anthropic")
        );
        assert!(claude.external_cli.launcher_wraps_claude);
    }

    #[test]
    fn set_provider_cli_config_updates_provider_bin_and_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  claude:
    managed: true
    bin: "claude"
    external_cli:
      private_key: "keep"
      upstreamBaseUrl: "https://old.example.test"
      launcherWrapsClaude: false
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_cli_config_in_document(
            &mut doc,
            "claude",
            Some("company-launcher start".to_string()),
            ProviderExternalCliConfig {
                upstream_base_url: Some("https://upstream.example.test/anthropic".to_string()),
                launcher_wraps_claude: true,
            },
        );

        let providers = doc.providers.expect("providers");
        let claude = providers.get("claude").expect("claude");
        assert_eq!(claude.bin.as_deref(), Some("company-launcher start"));

        let external_cli = claude.external_cli.as_ref().expect("external cli");
        assert_eq!(
            external_cli
                .get("upstream_base_url")
                .and_then(|value| value.as_str()),
            Some("https://upstream.example.test/anthropic")
        );
        assert_eq!(
            external_cli
                .get("launcher_wraps_claude")
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
        assert!(external_cli.get("launcherWrapsClaude").is_none());
    }

    #[test]
    fn set_provider_message_hook_enabled_updates_provider_config() {
        let raw = r#"
schema_version: 2
providers:
  codex:
    managed: true
"#;

        let mut doc = normalize_provider_document(raw).expect("normalized config");
        set_provider_message_hook_enabled_in_document(
            &mut doc,
            "codex",
            "abusive_language_normalization",
            false,
        );

        let providers = doc.providers.expect("providers");
        let codex = providers.get("codex").expect("codex");
        let message_hooks = codex.message_hooks.as_ref().expect("message hooks");
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
codex_bin: "codex"
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
        let raw = r#"
tools:
  - name: codex
enabled: true
codex_bin: "codex"
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
                .and_then(|providers| providers.get("codex"))
                .and_then(|codex| codex.get("owner_transport"))
                .and_then(|value| value.as_str()),
            Some("stdio")
        );
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get("codex"))
                .and_then(|codex| codex.get("live_transport"))
                .and_then(|value| value.as_str()),
            Some("owner_bridge")
        );
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get("codex"))
                .and_then(|codex| codex.get("transport"))
                .and_then(|transport| transport.get("type"))
                .and_then(|value| value.as_str()),
            Some("stdio")
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
        let raw = "tools:\n  - name: codex\n    enabled: [";

        let error =
            serialize_normalized_config_with_env(raw, None).expect_err("invalid yaml should fail");

        assert!(error.contains("Cannot parse config.yaml"));
    }

    #[test]
    fn normalize_config_for_display_backfills_visible_claude_provider() {
        let raw = r#"
tools:
  - name: codex
enabled: true
codex_bin: "codex"
"#;

        let rendered = normalize_config_for_display(raw, None);
        let doc: serde_yaml::Value = serde_yaml::from_str(&rendered).expect("rendered yaml");

        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get("claude"))
                .and_then(|provider| provider.get("bin"))
                .and_then(|value| value.as_str()),
            Some("claude")
        );
    }

    #[test]
    fn serialize_normalized_config_omits_generated_icon_data_urls() {
        let rendered = serialize_normalized_config_with_env("", None).expect("rendered yaml");

        assert!(rendered.contains("icon:"));
        assert!(rendered.contains("path: icon.svg"));
        assert!(rendered.contains("source: https://simpleicons.org/icons/openai.svg"));
        assert!(!rendered.contains("data:image/svg+xml;base64,"));
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
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");

        assert_eq!(codex.runtime_id, "codex");
    }

    #[test]
    fn provider_metadata_exposes_manifest_icon_data_urls() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");
        let claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude");

        let codex_icon = codex.icon.as_ref().expect("codex icon");
        assert_eq!(codex_icon.path, "icon.svg");
        assert!(codex_icon.url.starts_with("data:image/svg+xml;base64,"));
        assert!(codex_icon.source.contains("simpleicons"));

        let claude_icon = claude.icon.as_ref().expect("claude icon");
        assert_eq!(claude_icon.path, "icon.svg");
        assert!(claude_icon.url.starts_with("data:image/svg+xml;base64,"));
        assert!(claude_icon.source.contains("simpleicons"));
    }

    #[test]
    fn provider_metadata_exposes_manifest_capabilities() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");
        let claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude");

        assert_eq!(
            codex.capabilities,
            ProviderCapabilitiesEntry {
                sessions: true,
                send: true,
                commands: true,
                approvals: true,
                questions: false,
                photos: true,
                files: true,
                usage: true,
                command_wrappers: vec!["model".to_string(), "review".to_string()],
                control_modes: vec!["app".to_string(), "tui".to_string(), "hybrid".to_string()],
                message_rewrite: super::ProviderMessageRewriteCapabilities {
                    app_send: true,
                    telegram: true,
                    external_cli: Some("remote_proxy".to_string()),
                    wrapper: Some("ow-codex".to_string()),
                },
            }
        );
        assert_eq!(
            claude.capabilities,
            ProviderCapabilitiesEntry {
                sessions: true,
                send: true,
                commands: true,
                approvals: true,
                questions: true,
                photos: true,
                files: true,
                usage: true,
                command_wrappers: Vec::new(),
                control_modes: vec!["app".to_string()],
                message_rewrite: super::ProviderMessageRewriteCapabilities {
                    app_send: true,
                    telegram: true,
                    external_cli: Some("http_proxy".to_string()),
                    wrapper: Some("ow-claude".to_string()),
                },
            }
        );
    }

    #[test]
    fn provider_metadata_backfills_new_message_rewrite_fields_for_existing_config() {
        let raw = r#"
schema_version: 2
providers:
  codex:
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
"#;

        let providers = provider_metadata_from_raw(raw, None).expect("metadata");
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");

        assert!(codex.capabilities.message_rewrite.app_send);
        assert!(codex.capabilities.message_rewrite.telegram);
        assert_eq!(
            codex.capabilities.message_rewrite.external_cli.as_deref(),
            Some("remote_proxy")
        );
        assert_eq!(
            codex.capabilities.message_rewrite.wrapper.as_deref(),
            Some("ow-codex")
        );
    }

    #[test]
    fn normalize_provider_document_preserves_provider_external_cli_settings() {
        let raw = r#"
schema_version: 2
providers:
  claude:
    managed: true
    bin: "company-launcher start"
    external_cli:
      upstream_base_url: "https://upstream.example.test/anthropic"
      launcher_wraps_claude: true
"#;

        let rendered = serialize_normalized_config_with_env(raw, None).expect("rendered yaml");

        assert!(rendered.contains("external_cli:"));
        assert!(rendered.contains("upstream_base_url: https://upstream.example.test/anthropic"));
        assert!(rendered.contains("launcher_wraps_claude: true"));
    }

    #[test]
    fn config_provider_defaults_are_not_static_provider_matches() {
        let source = include_str!("config_provider.rs");

        assert!(!source.contains(&format!("\"{}\" => ProviderConfigEntry", "codex")));
        assert!(!source.contains(&format!("\"{}\" => ProviderConfigEntry", "claude")));
        assert!(!source.contains("\"codex\" => ProviderConfigEntry"));
        assert!(!source.contains("\"claude\" => ProviderConfigEntry"));
        assert!(!source.contains(&format!(
            "const {}: &[&str] = &[\"codex\", \"claude\"]",
            "PUBLIC_DEFAULT_PROVIDER_IDS"
        )));
    }
}
