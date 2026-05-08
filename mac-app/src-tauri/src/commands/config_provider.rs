use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

const BUILTIN_CODEX_PLUGIN_MANIFEST: &str =
    include_str!("../../../../plugins/providers/builtin/codex/plugin.yaml");
const BUILTIN_CLAUDE_PLUGIN_MANIFEST: &str =
    include_str!("../../../../plugins/providers/builtin/claude/plugin.yaml");

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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) capabilities: Option<ProviderCapabilitiesEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) install: Option<ProviderInstallEntry>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub(crate) process: Option<ProviderProcessEntry>,
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
    #[serde(default, alias = "command_wrappers")]
    pub(crate) command_wrappers: Vec<String>,
    #[serde(default, alias = "control_modes")]
    pub(crate) control_modes: Vec<String>,
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
    pub(crate) install: ProviderInstallEntry,
    pub(crate) process: ProviderProcessEntry,
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
    auth_env: Option<BTreeMap<String, String>>,
    capabilities: Option<ProviderCapabilitiesEntry>,
    process: Option<ProviderProcessEntry>,
}

#[derive(Clone, Debug)]
struct ProviderPluginDefault {
    id: String,
    visibility: String,
    order: u32,
    auth_env: BTreeMap<String, String>,
    config: ProviderConfigEntry,
}

fn workspace_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")))
        .to_path_buf()
}

fn read_manifest_files_from_group(group_dir: &Path) -> Vec<String> {
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
        .filter_map(|path| fs::read_to_string(path).ok())
        .collect()
}

fn read_manifest_files_from_overlay_path(overlay_path: &Path) -> Vec<String> {
    if overlay_path.is_file() {
        return fs::read_to_string(overlay_path)
            .ok()
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
            if let Ok(source) = fs::read_to_string(path) {
                manifests.push(source);
            }
        }
    }
    manifests
}

fn read_manifest_files_from_overlay_env() -> Vec<String> {
    let Ok(raw) = env::var("ONLINEWORKER_PROVIDER_OVERLAY") else {
        return Vec::new();
    };
    env::split_paths(&raw)
        .flat_map(|path| read_manifest_files_from_overlay_path(&path))
        .collect()
}

pub(crate) fn provider_plugin_manifest_sources() -> Vec<String> {
    let plugin_root = workspace_root().join("plugins").join("providers");
    let mut sources = Vec::new();
    sources.extend(read_manifest_files_from_group(&plugin_root.join("builtin")));
    sources.extend(read_manifest_files_from_overlay_env());
    if !sources.is_empty() {
        return sources;
    }
    vec![
        BUILTIN_CLAUDE_PLUGIN_MANIFEST.to_string(),
        BUILTIN_CODEX_PLUGIN_MANIFEST.to_string(),
    ]
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
        auth_env: provider.auth_env.unwrap_or_default(),
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
            install: Some(ProviderInstallEntry {
                cli_names: vec![install_cli_name],
            }),
            process: Some(provider.process.unwrap_or_default()),
            ..ProviderConfigEntry::default()
        },
    })
}

fn provider_plugin_default_list() -> Vec<ProviderPluginDefault> {
    let mut defaults = Vec::new();
    for source in provider_plugin_manifest_sources() {
        let Ok(manifest) = serde_yaml::from_str::<ProviderPluginManifest>(&source) else {
            continue;
        };
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

fn provider_auth_from_env_raw(
    provider_id: &str,
    env_raw: Option<&str>,
) -> BTreeMap<String, String> {
    let raw = env_raw.unwrap_or("");
    let auth_env = provider_plugin_defaults()
        .remove(provider_id)
        .map(|default| default.auth_env)
        .unwrap_or_default();
    auth_env
        .into_iter()
        .map(|(auth_key, env_key)| (auth_key, read_env_key(raw, &env_key).unwrap_or_default()))
        .collect()
}

fn merge_provider_auth_from_env(
    provider: &mut ProviderConfigEntry,
    env_auth: &BTreeMap<String, String>,
) {
    let auth = provider.auth.get_or_insert_with(BTreeMap::new);
    for key in env_auth.keys() {
        let current = auth.get(key).map(|value| value.trim()).unwrap_or("");
        if current.is_empty() {
            let fallback = env_auth.get(key).map(|value| value.trim()).unwrap_or("");
            if !fallback.is_empty() {
                auth.insert(key.to_string(), fallback.to_string());
            }
        }
    }
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
    provider.auth = provider.auth.take().or(defaults.auth);

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
    provider.capabilities = provider.capabilities.take().or(defaults.capabilities);
    provider.install = provider.install.take().or(defaults.install);
    provider.process = provider.process.take().or(defaults.process);
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
    env_raw: Option<&str>,
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
        let env_auth = provider_auth_from_env_raw(provider_id, env_raw);
        merge_provider_auth_from_env(provider, &env_auth);
    }
    for builtin in public_default_provider_ids() {
        providers
            .entry(builtin.clone())
            .or_insert_with(|| default_provider_config(&builtin));
    }
    for builtin in public_default_provider_ids() {
        if let Some(provider) = providers.get_mut(&builtin) {
            normalize_provider_entry(&builtin, provider);
            let env_auth = provider_auth_from_env_raw(&builtin, env_raw);
            merge_provider_auth_from_env(provider, &env_auth);
        }
    }

    doc.schema_version = Some(2);
    doc.tools = None;
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
        managed: provider.managed.unwrap_or(false),
        autostart: provider.autostart.unwrap_or(false),
        bin: provider.bin.clone(),
        live_transport: provider.live_transport.clone().unwrap_or_else(|| {
            default_live_transport(provider_id, &owner, provider.control_mode.as_deref())
        }),
        control_mode: provider.control_mode.clone(),
        capabilities: provider.capabilities.clone().unwrap_or_default(),
        install: provider.install.clone().unwrap_or_default(),
        process: provider.process.clone().unwrap_or_default(),
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
    serde_yaml::to_string(&doc).map_err(|e| format!("Cannot serialize config.yaml: {}", e))
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

#[cfg(test)]
mod tests {
    use super::{
        normalize_config_for_display, normalize_provider_document,
        normalize_provider_document_with_env, provider_metadata_from_raw,
        serialize_normalized_config_with_env, set_provider_flags_in_document,
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
    fn normalize_provider_document_backfills_claude_auth_from_legacy_env() {
        let raw = r#"
tools:
  - name: codex
enabled: true
codex_bin: "codex"
"#;
        let env_raw = "ANTHROPIC_API_KEY=dummy\nANTHROPIC_BASE_URL=http://localhost:3031\nANTHROPIC_MODEL=claude-opus-4-6\n";

        let doc =
            normalize_provider_document_with_env(raw, Some(env_raw)).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let claude = providers.get("claude").expect("claude");
        let auth = claude.auth.as_ref().expect("claude auth");
        assert_eq!(auth.get("key").map(String::as_str), Some("dummy"));
        assert_eq!(
            auth.get("base_url").map(String::as_str),
            Some("http://localhost:3031")
        );
        assert_eq!(
            auth.get("model").map(String::as_str),
            Some("claude-opus-4-6")
        );
    }

    #[test]
    fn normalize_provider_document_backfills_empty_claude_auth_fields_from_env() {
        let raw = r#"
schema_version: 2
providers:
  claude:
managed: false
autostart: false
auth:
  key: ""
  base_url: "   "
  model: ""
"#;
        let env_raw = "ANTHROPIC_API_KEY=dummy\nANTHROPIC_BASE_URL=http://localhost:3031\nANTHROPIC_MODEL=claude-opus-4-6\n";

        let doc =
            normalize_provider_document_with_env(raw, Some(env_raw)).expect("normalized config");
        let providers = doc.providers.expect("providers");
        let claude = providers.get("claude").expect("claude");
        let auth = claude.auth.as_ref().expect("claude auth");
        assert_eq!(auth.get("key").map(String::as_str), Some("dummy"));
        assert_eq!(
            auth.get("base_url").map(String::as_str),
            Some("http://localhost:3031")
        );
        assert_eq!(
            auth.get("model").map(String::as_str),
            Some("claude-opus-4-6")
        );
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
    fn provider_metadata_exposes_manifest_runtime_id() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex");

        assert_eq!(codex.runtime_id, "codex");
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
