use serde::Deserialize;
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::Command;
use std::time::{Duration, SystemTime};

use super::super::config_provider::{
    default_live_transport, infer_legacy_transport, provider_default_metadata,
    provider_metadata_from_raw, public_default_provider_ids, uses_shared_app_server_transport,
    ProviderIconEntry, ProviderMetadata, ProviderTuiHostEntry,
};
use super::super::provider_bridge_common::provider_owner_bridge_socket_path;
use super::{ProviderDashboardStatus, ServiceHealth};

#[derive(Deserialize, Default)]
struct DashboardConfigDocument {
    providers: Option<HashMap<String, RawProviderConfig>>,
    tools: Option<Vec<LegacyToolConfig>>,
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct RawProviderConfig {
    managed: Option<bool>,
    autostart: Option<bool>,
    bin: Option<String>,
    owner_transport: Option<String>,
    live_transport: Option<String>,
    transport: Option<RawTransportConfig>,
    protocol: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
}

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct RawTransportConfig {
    #[serde(rename = "type")]
    kind: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
}

#[derive(Deserialize, Default)]
struct LegacyToolConfig {
    name: String,
    enabled: Option<bool>,
    bin: Option<String>,
    owner_transport: Option<String>,
    live_transport: Option<String>,
    protocol: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) struct ProviderConfigSnapshot {
    pub(super) id: String,
    pub(super) icon: Option<ProviderIconEntry>,
    pub(super) visible: bool,
    pub(super) managed: bool,
    pub(super) autostart: bool,
    pub(super) transport: String,
    pub(super) live_transport: String,
    pub(super) port: Option<u16>,
    pub(super) app_server_url: Option<String>,
    pub(super) control_mode: Option<String>,
    pub(super) bin: Option<String>,
    pub(super) tui_host: ProviderTuiHostEntry,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct OwnerBridgeRuntimeStatusResponse {
    ok: bool,
    health: Option<ServiceHealth>,
    detail: Option<String>,
}

fn default_provider_snapshot(id: &str) -> ProviderConfigSnapshot {
    provider_snapshot_from_metadata(provider_default_metadata(id))
}

fn provider_snapshot_from_metadata(provider: ProviderMetadata) -> ProviderConfigSnapshot {
    ProviderConfigSnapshot {
        id: provider.id,
        icon: provider.icon,
        visible: provider.visible,
        managed: provider.managed,
        autostart: provider.autostart,
        transport: provider.transport.owner,
        live_transport: provider.live_transport,
        port: provider.transport.app_server_port,
        app_server_url: provider.transport.app_server_url,
        control_mode: provider.control_mode,
        bin: provider.bin,
        tui_host: provider.tui_host,
    }
}

fn normalize_transport(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim().to_lowercase();
        match trimmed.as_str() {
            "stdio" | "ws" | "unix" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn normalize_live_transport(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim().to_lowercase();
        match trimmed.as_str() {
            "owner_bridge" | "shared_ws" | "shared_unix" | "stdio" | "ws" | "unix" | "http" => {
                Some(trimmed)
            }
            _ => None,
        }
    })
}

pub(super) fn resolve_builtin_provider_snapshots(raw: Option<&str>) -> Vec<ProviderConfigSnapshot> {
    if let Ok(metadata) = provider_metadata_from_raw(raw.unwrap_or(""), None) {
        return metadata
            .into_iter()
            .map(provider_snapshot_from_metadata)
            .filter(|provider| provider.visible)
            .collect();
    }

    let mut resolved = HashMap::new();
    let parsed: DashboardConfigDocument = raw
        .and_then(|content| serde_yaml::from_str(content).ok())
        .unwrap_or_default();

    if let Some(providers) = parsed.providers {
        for (id, provider) in providers {
            let mut snapshot = default_provider_snapshot(&id);
            snapshot.managed = provider.managed.unwrap_or(snapshot.managed);
            snapshot.autostart =
                provider.autostart.unwrap_or(snapshot.autostart) && snapshot.managed;
            snapshot.bin = provider.bin.or(snapshot.bin);
            let transport = provider.transport.unwrap_or_default();
            snapshot.transport = normalize_transport(
                provider
                    .owner_transport
                    .or(transport.kind)
                    .or(provider.protocol),
            )
            .unwrap_or(snapshot.transport);
            snapshot.port = transport
                .app_server_port
                .or(provider.app_server_port)
                .or(snapshot.port);
            snapshot.app_server_url = transport
                .app_server_url
                .or(provider.app_server_url)
                .or(snapshot.app_server_url);
            snapshot.control_mode = provider.control_mode.or(snapshot.control_mode);
            if uses_shared_app_server_transport(&id) && snapshot.transport == "stdio" {
                snapshot.port = None;
                snapshot.app_server_url = None;
            } else if uses_shared_app_server_transport(&id) && snapshot.transport == "unix" {
                snapshot.port = None;
            }
            snapshot.live_transport = normalize_live_transport(provider.live_transport)
                .unwrap_or_else(|| {
                    default_live_transport(
                        &id,
                        &snapshot.transport,
                        snapshot.control_mode.as_deref(),
                    )
                });
            resolved.insert(id, snapshot);
        }
    } else if let Some(tools) = parsed.tools {
        for tool in tools {
            if tool.name.trim().is_empty() {
                continue;
            }
            let mut snapshot = default_provider_snapshot(&tool.name);
            let managed = tool.enabled.unwrap_or(true);
            snapshot.managed = managed;
            snapshot.autostart = managed;
            snapshot.bin = tool.bin.or(snapshot.bin);
            let mut transport = infer_legacy_transport(
                &tool.name,
                tool.protocol.as_deref(),
                tool.app_server_url.as_deref(),
                tool.app_server_port,
            );
            let mut port = tool.app_server_port.or(snapshot.port);
            if let Some(owner_transport) = normalize_transport(tool.owner_transport) {
                transport = owner_transport;
            } else if uses_shared_app_server_transport(&tool.name)
                && tool.protocol.as_deref() == Some("ws")
                && tool.app_server_url.as_deref().unwrap_or("").is_empty()
                && tool.app_server_port.unwrap_or(0) == 4722
                && tool.control_mode.as_deref().unwrap_or("").is_empty()
            {
                transport = "unix".to_string();
                port = None;
            }
            snapshot.transport = transport;
            snapshot.port = port;
            snapshot.app_server_url = tool.app_server_url.or(snapshot.app_server_url);
            snapshot.control_mode = tool.control_mode.or(snapshot.control_mode);
            if uses_shared_app_server_transport(&tool.name) && snapshot.transport == "stdio" {
                snapshot.port = None;
                snapshot.app_server_url = None;
            } else if uses_shared_app_server_transport(&tool.name) && snapshot.transport == "unix" {
                snapshot.port = None;
            }
            snapshot.live_transport =
                normalize_live_transport(tool.live_transport).unwrap_or_else(|| {
                    default_live_transport(
                        &tool.name,
                        &snapshot.transport,
                        snapshot.control_mode.as_deref(),
                    )
                });
            resolved.insert(tool.name, snapshot);
        }
    }

    let mut ordered = Vec::new();
    for builtin in public_default_provider_ids() {
        if let Some(snapshot) = resolved.remove(&builtin) {
            if snapshot.visible {
                ordered.push(snapshot);
            }
        }
    }
    let mut extras: Vec<_> = resolved.into_values().collect();
    extras.retain(|provider| provider.visible);
    extras.sort_by(|a, b| a.id.cmp(&b.id));
    ordered.extend(extras);
    ordered
}

pub(super) fn read_provider_snapshots(
    data_dir: &Path,
) -> Result<Vec<ProviderConfigSnapshot>, String> {
    let config_path = data_dir.join("config.yaml");
    if !config_path.exists() {
        return Ok(resolve_builtin_provider_snapshots(None));
    }
    let raw = std::fs::read_to_string(&config_path)
        .map_err(|e| format!("Cannot read config.yaml for dashboard providers: {}", e))?;
    Ok(resolve_builtin_provider_snapshots(Some(&raw)))
}

fn provider_stopped_detail(provider: &ProviderConfigSnapshot) -> Option<String> {
    if !provider.managed {
        Some("Provider is not managed by the app".to_string())
    } else if !provider.autostart {
        Some("Autostart disabled".to_string())
    } else {
        None
    }
}

fn provider_missing_cli_detail(provider: &ProviderConfigSnapshot) -> Option<String> {
    let bin = provider.bin.as_deref()?;
    if check_cli_available_sync(bin) {
        None
    } else {
        Some(format!("CLI not found in PATH: {bin}"))
    }
}

const PROVIDER_OWNER_BRIDGE_STATUS_TIMEOUT: Duration = Duration::from_millis(1200);

fn read_provider_runtime_status_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
) -> Result<(ServiceHealth, Option<String>), String> {
    read_provider_runtime_status_via_owner_bridge_with_timeout(
        data_dir,
        provider_id,
        PROVIDER_OWNER_BRIDGE_STATUS_TIMEOUT,
    )
}

pub(super) fn read_provider_runtime_status_via_owner_bridge_with_timeout(
    data_dir: &Path,
    provider_id: &str,
    timeout: Duration,
) -> Result<(ServiceHealth, Option<String>), String> {
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }

    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;
    socket
        .set_read_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge read timeout failed: {e}"))?;
    socket
        .set_write_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge write timeout failed: {e}"))?;
    let payload = serde_json::json!({
        "type": "runtime_status",
        "provider_id": provider_id,
    });
    let raw_request = format!("{}\n", payload);
    socket
        .write_all(raw_request.as_bytes())
        .map_err(|e| format!("write provider owner bridge request failed: {e}"))?;
    socket
        .shutdown(Shutdown::Write)
        .map_err(|e| format!("shutdown provider owner bridge write failed: {e}"))?;

    let mut response_line = String::new();
    let mut reader = BufReader::new(socket);
    reader
        .read_line(&mut response_line)
        .map_err(|e| format!("read provider owner bridge response failed: {e}"))?;

    let response = serde_json::from_str::<OwnerBridgeRuntimeStatusResponse>(response_line.trim())
        .map_err(|e| format!("parse provider owner bridge response failed: {e}"))?;
    if !response.ok {
        return Err(response
            .detail
            .unwrap_or_else(|| "provider owner bridge request failed".to_string()));
    }

    Ok((
        response.health.unwrap_or(ServiceHealth::Unknown),
        response.detail,
    ))
}

pub(super) fn build_provider_statuses(
    configs: Vec<ProviderConfigSnapshot>,
    data_dir: &Path,
    service_running: bool,
    _managed_service_running: bool,
    _last_started_at: Option<SystemTime>,
    _now: SystemTime,
) -> Vec<ProviderDashboardStatus> {
    configs
        .into_iter()
        .map(|provider| {
            let (health, detail) = if !provider.managed || !provider.autostart {
                (ServiceHealth::Stopped, provider_stopped_detail(&provider))
            } else {
                derive_provider_health(service_running, &provider, data_dir)
            };

            ProviderDashboardStatus {
                id: provider.id,
                icon: provider.icon,
                managed: provider.managed,
                autostart: provider.autostart,
                health,
                port: provider.port,
                detail,
                transport: Some(provider.transport),
                live_transport: Some(provider.live_transport),
                control_mode: provider.control_mode,
                bin: provider.bin,
                tui_host: provider.tui_host,
            }
        })
        .collect()
}

pub(super) fn has_subservice_problem(health: &ServiceHealth) -> bool {
    matches!(health, ServiceHealth::Degraded | ServiceHealth::Stopped)
}

fn derive_provider_health(
    service_running: bool,
    provider: &ProviderConfigSnapshot,
    data_dir: &Path,
) -> (ServiceHealth, Option<String>) {
    if !service_running {
        return (ServiceHealth::Stopped, None);
    }

    let owner_bridge_ready = provider_owner_bridge_socket_path(data_dir).exists();
    if owner_bridge_ready {
        return match read_provider_runtime_status_via_owner_bridge(data_dir, &provider.id) {
            Ok(status) => status,
            Err(error) => (
                ServiceHealth::Unknown,
                Some(format!(
                    "{} runtime status unavailable: {}",
                    provider.id, error
                )),
            ),
        };
    }

    if let Some(detail) = provider_missing_cli_detail(provider) {
        (ServiceHealth::Stopped, Some(detail))
    } else {
        (ServiceHealth::Unknown, None)
    }
}

fn dashboard_rich_path() -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    )
}

fn resolve_cli_bin(bin: &str) -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    if bin.starts_with("~/") {
        format!("{}{}", home, &bin[1..])
    } else {
        bin.to_string()
    }
}

fn command_program_token(command: &str) -> String {
    let mut token = String::new();
    let mut chars = command.trim_start().chars().peekable();
    let mut quote: Option<char> = None;
    while let Some(ch) = chars.next() {
        if let Some(active_quote) = quote {
            if ch == active_quote {
                quote = None;
            } else if ch == '\\' {
                token.push(chars.next().unwrap_or(ch));
            } else {
                token.push(ch);
            }
            continue;
        }
        match ch {
            '\'' | '"' => quote = Some(ch),
            '\\' => token.push(chars.next().unwrap_or(ch)),
            ch if ch.is_whitespace() => break,
            _ => token.push(ch),
        }
    }
    token
}

fn check_cli_available_sync(bin: &str) -> bool {
    let program = command_program_token(bin);
    if program.is_empty() {
        return false;
    }
    let resolved = resolve_cli_bin(&program);
    if resolved.starts_with('/') {
        let path = Path::new(&resolved);
        return path.exists() && path.is_file();
    }

    Command::new("which")
        .arg(&resolved)
        .env("PATH", dashboard_rich_path())
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}
