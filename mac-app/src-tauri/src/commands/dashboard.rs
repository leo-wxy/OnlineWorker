use rusqlite::{Connection, OpenFlags};
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

use super::claude::{
    build_claude_history_index, default_claude_history_path, default_claude_projects_dir,
    load_claude_project_sessions_from_dir, read_claude_project_session_preview,
    should_skip_claude_session_from_workspace_list,
};
use super::config::ensure_data_dir;
use super::config_provider::{provider_metadata_from_raw, ProviderMetadata};
use super::service::{
    ensure_service_running_if_needed, read_codex_mirror_status, snapshot_service_status, BotState,
};
use super::session_state::{load_local_thread_overlays, LocalThreadOverlay};

#[path = "dashboard_types.rs"]
mod dashboard_types;
pub use self::dashboard_types::*;

const REQUIRED_ENV_KEYS: &[&str] = &["TELEGRAM_TOKEN", "ALLOWED_USER_ID", "GROUP_CHAT_ID"];
const CODEX_MIRROR_STALE_SECONDS: f64 = 15.0;

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
    codex_bin: Option<String>,
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
    codex_bin: Option<String>,
    owner_transport: Option<String>,
    live_transport: Option<String>,
    protocol: Option<String>,
    app_server_port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct ProviderConfigSnapshot {
    id: String,
    visible: bool,
    managed: bool,
    autostart: bool,
    transport: String,
    live_transport: String,
    port: Option<u16>,
    app_server_url: Option<String>,
    control_mode: Option<String>,
    bin: Option<String>,
}

#[derive(Clone, Debug)]
struct WorkspaceSnapshot {
    id: String,
    name: Option<String>,
    tool: String,
    path: String,
}

#[derive(Clone, Debug)]
struct WorkspaceActivityCandidate {
    workspace_id: String,
    workspace_name: Option<String>,
    tool: String,
    session_id: String,
    preview: Option<String>,
    updated_at: i64,
    active_thread_count: u32,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct OwnerBridgeRuntimeStatusResponse {
    ok: bool,
    health: Option<ServiceHealth>,
    detail: Option<String>,
}

fn default_provider_snapshot(id: &str) -> ProviderConfigSnapshot {
    match id {
        "codex" => ProviderConfigSnapshot {
            id: "codex".to_string(),
            visible: true,
            managed: true,
            autostart: true,
            transport: "stdio".to_string(),
            live_transport: "owner_bridge".to_string(),
            port: None,
            app_server_url: None,
            control_mode: Some("app".to_string()),
            bin: Some("codex".to_string()),
        },
        "claude" => ProviderConfigSnapshot {
            id: "claude".to_string(),
            visible: true,
            managed: false,
            autostart: false,
            transport: "stdio".to_string(),
            live_transport: "stdio".to_string(),
            port: None,
            app_server_url: None,
            control_mode: Some("app".to_string()),
            bin: Some("claude".to_string()),
        },
        other => ProviderConfigSnapshot {
            id: other.to_string(),
            visible: true,
            managed: false,
            autostart: false,
            transport: "stdio".to_string(),
            live_transport: "stdio".to_string(),
            port: None,
            app_server_url: None,
            control_mode: Some("app".to_string()),
            bin: Some(other.to_string()),
        },
    }
}

fn provider_snapshot_from_metadata(provider: ProviderMetadata) -> ProviderConfigSnapshot {
    ProviderConfigSnapshot {
        id: provider.id,
        visible: provider.visible,
        managed: provider.managed,
        autostart: provider.autostart,
        transport: provider.transport.owner,
        live_transport: provider.live_transport,
        port: provider.transport.app_server_port,
        app_server_url: provider.transport.app_server_url,
        control_mode: provider.control_mode,
        bin: provider.bin,
    }
}

fn is_hidden_provider(id: &str) -> bool {
    let _ = id;
    false
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
    match tool_name {
        "codex" => {
            if raw_port.unwrap_or(0) > 0 {
                "ws".to_string()
            } else {
                "stdio".to_string()
            }
        }
        "claude" => "stdio".to_string(),
        _ => "stdio".to_string(),
    }
}

fn normalize_transport(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim().to_lowercase();
        match trimmed.as_str() {
            "stdio" | "ws" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn normalize_live_transport(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim().to_lowercase();
        match trimmed.as_str() {
            "owner_bridge" | "shared_ws" | "stdio" | "ws" | "http" => Some(trimmed),
            _ => None,
        }
    })
}

fn default_live_transport(
    tool_name: &str,
    owner_transport: &str,
    control_mode: Option<&str>,
) -> String {
    if tool_name == "codex" {
        if owner_transport == "ws" && matches!(control_mode, Some("app" | "hybrid")) {
            return "shared_ws".to_string();
        }
        return "owner_bridge".to_string();
    }
    owner_transport.to_string()
}

fn resolve_builtin_provider_snapshots(raw: Option<&str>) -> Vec<ProviderConfigSnapshot> {
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
            if is_hidden_provider(&id) {
                continue;
            }
            let mut snapshot = default_provider_snapshot(&id);
            snapshot.managed = provider.managed.unwrap_or(snapshot.managed);
            snapshot.autostart =
                provider.autostart.unwrap_or(snapshot.autostart) && snapshot.managed;
            snapshot.bin = provider.bin.or(provider.codex_bin).or(snapshot.bin);
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
            if id == "codex" && snapshot.transport == "stdio" {
                snapshot.port = None;
                snapshot.app_server_url = None;
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
            if is_hidden_provider(&tool.name) {
                continue;
            }
            let mut snapshot = default_provider_snapshot(&tool.name);
            let managed = tool.enabled.unwrap_or(true);
            snapshot.managed = managed;
            snapshot.autostart = managed;
            snapshot.bin = tool.codex_bin.or(snapshot.bin);
            let mut transport = infer_legacy_transport(
                &tool.name,
                tool.protocol.as_deref(),
                tool.app_server_url.as_deref(),
                tool.app_server_port,
            );
            let mut port = tool.app_server_port.or(snapshot.port);
            if let Some(owner_transport) = normalize_transport(tool.owner_transport) {
                transport = owner_transport;
            } else if tool.name == "codex"
                && tool.protocol.as_deref() == Some("ws")
                && tool.app_server_url.as_deref().unwrap_or("").is_empty()
                && tool.app_server_port.unwrap_or(0) == 4722
                && tool.control_mode.as_deref().unwrap_or("").is_empty()
            {
                transport = "stdio".to_string();
                port = None;
            }
            snapshot.transport = transport;
            snapshot.port = port;
            snapshot.app_server_url = tool.app_server_url.or(snapshot.app_server_url);
            snapshot.control_mode = tool.control_mode.or(snapshot.control_mode);
            if tool.name == "codex" && snapshot.transport == "stdio" {
                snapshot.port = None;
                snapshot.app_server_url = None;
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
    for builtin in ["codex", "claude"] {
        if let Some(snapshot) = resolved.remove(builtin) {
            if snapshot.visible {
                ordered.push(snapshot);
            }
        }
    }
    let mut extras: Vec<_> = resolved.into_values().collect();
    extras.retain(|provider| provider.visible && !is_hidden_provider(&provider.id));
    extras.sort_by(|a, b| a.id.cmp(&b.id));
    ordered.extend(extras);
    ordered
}

fn read_provider_snapshots(data_dir: &Path) -> Result<Vec<ProviderConfigSnapshot>, String> {
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

fn provider_owner_bridge_socket_path(data_dir: &Path) -> PathBuf {
    data_dir.join("provider_owner_bridge.sock")
}

fn read_provider_runtime_status_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
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

fn build_provider_statuses(
    configs: Vec<ProviderConfigSnapshot>,
    data_dir: &Path,
    service_running: bool,
    _managed_service_running: bool,
    _last_started_at: Option<SystemTime>,
    _now: SystemTime,
    mirror_status: Option<&super::service::CodexMirrorStatus>,
) -> Vec<ProviderDashboardStatus> {
    configs
        .into_iter()
        .map(|provider| {
            let (health, detail) = if !provider.managed || !provider.autostart {
                (ServiceHealth::Stopped, provider_stopped_detail(&provider))
            } else if let Some(detail) = provider_missing_cli_detail(&provider) {
                (ServiceHealth::Stopped, Some(detail))
            } else {
                match provider.id.as_str() {
                    "codex" => (derive_codex_health(service_running, mirror_status), None),
                    "claude" => derive_claude_health(service_running, &provider, data_dir),
                    _ => {
                        if !service_running {
                            (ServiceHealth::Stopped, None)
                        } else {
                            read_provider_runtime_status_via_owner_bridge(data_dir, &provider.id)
                                .unwrap_or((ServiceHealth::Unknown, None))
                        }
                    }
                }
            };

            ProviderDashboardStatus {
                id: provider.id,
                managed: provider.managed,
                autostart: provider.autostart,
                health,
                port: provider.port,
                detail,
                transport: Some(provider.transport),
                live_transport: Some(provider.live_transport),
                control_mode: provider.control_mode,
                bin: provider.bin,
            }
        })
        .collect()
}

fn normalize_activity_timestamp(raw: i64) -> i64 {
    if raw > 1_000_000_000_000 {
        raw
    } else {
        raw.saturating_mul(1000)
    }
}

#[tauri::command]
pub async fn get_dashboard_state(
    app: tauri::AppHandle,
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<DashboardState, String> {
    let _ = ensure_service_running_if_needed(&app, state.inner()).await?;
    compute_dashboard_state(state.inner()).await
}

pub(crate) async fn compute_dashboard_state(
    state: &Arc<Mutex<BotState>>,
) -> Result<DashboardState, String> {
    let dir = ensure_data_dir()?;
    let service = snapshot_service_status(state).await?;
    let now = SystemTime::now();
    let (managed_service_running, last_started_at) = {
        let bot = state.lock().await;
        (bot.running, bot.last_started_at)
    };
    let (config_ready, missing_config_fields) = read_config_readiness(&dir)?;
    let mirror_status = read_codex_mirror_status().await.ok().flatten();
    let provider_configs = read_provider_snapshots(&dir)?;
    let providers = build_provider_statuses(
        provider_configs,
        &dir,
        service.running,
        managed_service_running,
        last_started_at,
        now,
        mirror_status.as_ref(),
    );

    Ok(build_dashboard_state(DashboardComputationInput {
        config_ready,
        missing_config_fields,
        service_running: service.running,
        service_pid: service.pid,
        providers,
        telegram_connected: if service.running { None } else { Some(false) },
        recent_activity: read_recent_activity_summary(&dir),
    }))
}

pub(crate) fn build_dashboard_state(input: DashboardComputationInput) -> DashboardState {
    let visible_providers: Vec<ProviderDashboardStatus> = input
        .providers
        .into_iter()
        .filter(|provider| !is_hidden_provider(&provider.id) && provider.managed)
        .collect();
    let telegram = match input.telegram_connected {
        Some(true) => ConnectionStatus::Connected,
        Some(false) => ConnectionStatus::Disconnected,
        None => ConnectionStatus::Unknown,
    };

    let bot_process = if input.service_running {
        ServiceHealth::Healthy
    } else {
        ServiceHealth::Stopped
    };
    let codex = provider_tool_status(&visible_providers, "codex");

    let mut alerts = Vec::new();

    if !input.config_ready {
        let detail = if input.missing_config_fields.is_empty() {
            "Missing required app configuration files".to_string()
        } else {
            format!(
                "Missing required settings: {}",
                input.missing_config_fields.join(", ")
            )
        };
        alerts.push(Alert {
            level: AlertLevel::Error,
            code: "configuration_incomplete".to_string(),
            title: "Configuration incomplete".to_string(),
            detail,
            action: Some("Open Setup".to_string()),
            action_code: Some("open_setup".to_string()),
            missing_fields: input.missing_config_fields.clone(),
        });
    }

    if input.service_running && active_provider_problem(&visible_providers, "codex") {
        alerts.push(Alert {
            level: AlertLevel::Warning,
            code: "codex_degraded".to_string(),
            title: "codex status degraded".to_string(),
            detail: "Codex runtime looks stale or unavailable from the app diagnostics view"
                .to_string(),
            action: Some("Open Logs".to_string()),
            action_code: Some("open_logs".to_string()),
            missing_fields: Vec::new(),
        });
    }

    if input.service_running && active_provider_problem(&visible_providers, "claude") {
        alerts.push(Alert {
            level: AlertLevel::Warning,
            code: "claude_degraded".to_string(),
            title: "claude status degraded".to_string(),
            detail: "Claude CLI is unavailable or not authenticated from the app diagnostics view"
                .to_string(),
            action: Some("Open Setup".to_string()),
            action_code: Some("open_setup".to_string()),
            missing_fields: Vec::new(),
        });
    }

    if input.service_running && telegram == ConnectionStatus::Disconnected {
        alerts.push(Alert {
            level: AlertLevel::Warning,
            code: "telegram_unavailable".to_string(),
            title: "Telegram connection unavailable".to_string(),
            detail: "Bot process is up, but Telegram connectivity is reported as disconnected"
                .to_string(),
            action: Some("Open Setup".to_string()),
            action_code: Some("open_setup".to_string()),
            missing_fields: Vec::new(),
        });
    }

    let overall = if !input.config_ready {
        SystemHealth::Misconfigured
    } else if !input.service_running {
        SystemHealth::Stopped
    } else if active_provider_problem(&visible_providers, "codex")
        || active_provider_problem(&visible_providers, "claude")
        || telegram == ConnectionStatus::Disconnected
    {
        SystemHealth::Degraded
    } else {
        SystemHealth::Healthy
    };

    DashboardState {
        overall,
        bot: BotDashboardStatus {
            process: bot_process,
            telegram,
            pid: input.service_pid,
            last_heartbeat: None,
        },
        providers: visible_providers,
        codex,
        alerts,
        recent_activity: input.recent_activity,
        generated_at_epoch: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
    }
}

fn has_subservice_problem(health: &ServiceHealth) -> bool {
    matches!(health, ServiceHealth::Degraded | ServiceHealth::Stopped)
}

fn provider_tool_status(providers: &[ProviderDashboardStatus], id: &str) -> ToolDashboardStatus {
    providers
        .iter()
        .find(|provider| provider.id == id)
        .map(|provider| ToolDashboardStatus {
            health: provider.health.clone(),
            port: provider.port,
            detail: provider.detail.clone(),
        })
        .unwrap_or(ToolDashboardStatus {
            health: ServiceHealth::Unknown,
            port: None,
            detail: None,
        })
}

fn active_provider_problem(providers: &[ProviderDashboardStatus], id: &str) -> bool {
    providers
        .iter()
        .find(|provider| provider.id == id)
        .map(|provider| {
            provider.managed && provider.autostart && has_subservice_problem(&provider.health)
        })
        .unwrap_or(false)
}

fn derive_codex_health(
    service_running: bool,
    mirror_status: Option<&super::service::CodexMirrorStatus>,
) -> ServiceHealth {
    if !service_running {
        return ServiceHealth::Stopped;
    }

    if let Some(mirror) = mirror_status {
        let now_epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let age = now_epoch - mirror.generated_at_epoch;
        if age > CODEX_MIRROR_STALE_SECONDS {
            ServiceHealth::Degraded
        } else {
            ServiceHealth::Healthy
        }
    } else {
        // App-owned codex runtime can be healthy even without legacy mirror snapshots.
        ServiceHealth::Healthy
    }
}

fn read_config_readiness(data_dir: &Path) -> Result<(bool, Vec<String>), String> {
    let config_path = data_dir.join("config.yaml");
    let env_path = data_dir.join(".env");
    let mut missing = Vec::new();

    if !config_path.exists() {
        missing.push("config.yaml".to_string());
    }

    let env_raw = if env_path.exists() {
        std::fs::read_to_string(&env_path)
            .map_err(|e| format!("Cannot read .env for dashboard state: {}", e))?
    } else {
        String::new()
    };

    for key in REQUIRED_ENV_KEYS {
        let value = read_env_key(&env_raw, key);
        if value.as_deref().map(str::trim).unwrap_or("").is_empty() {
            missing.push((*key).to_string());
        }
    }

    Ok((missing.is_empty(), missing))
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

fn read_dashboard_env_raw(data_dir: &Path) -> String {
    fs::read_to_string(data_dir.join(".env")).unwrap_or_default()
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

fn check_cli_available_sync(bin: &str) -> bool {
    let resolved = resolve_cli_bin(bin);
    if resolved.starts_with('/') {
        return Path::new(&resolved).exists();
    }

    Command::new("which")
        .arg(&resolved)
        .env("PATH", dashboard_rich_path())
        .output()
        .map(|output| output.status.success())
        .unwrap_or(false)
}

fn claude_env_auth_ready(env_raw: &str) -> bool {
    let api_key = read_env_key(env_raw, "ANTHROPIC_API_KEY").unwrap_or_default();
    let base_url = read_env_key(env_raw, "ANTHROPIC_BASE_URL").unwrap_or_default();
    !api_key.trim().is_empty() || !base_url.trim().is_empty()
}

fn parse_claude_auth_status_payload(payload: &str) -> Option<bool> {
    let trimmed = payload.trim();
    if trimmed.is_empty() {
        return None;
    }

    if let Ok(parsed) = serde_json::from_str::<Value>(trimmed) {
        return parsed.get("loggedIn").and_then(Value::as_bool);
    }

    let lowered = trimmed.to_lowercase();
    if lowered.contains("not logged in") {
        return Some(false);
    }
    if lowered.contains("logged in") {
        return Some(true);
    }
    None
}

fn read_claude_auth_status(bin: &str) -> Option<bool> {
    let resolved = resolve_cli_bin(bin);
    let output = Command::new(&resolved)
        .arg("auth")
        .arg("status")
        .env("PATH", dashboard_rich_path())
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    parse_claude_auth_status_payload(if stdout.trim().is_empty() {
        &stderr
    } else {
        &stdout
    })
}

fn derive_claude_health(
    service_running: bool,
    provider: &ProviderConfigSnapshot,
    data_dir: &Path,
) -> (ServiceHealth, Option<String>) {
    if !service_running {
        return (ServiceHealth::Stopped, None);
    }

    let bin = provider.bin.as_deref().unwrap_or("claude");
    if !check_cli_available_sync(bin) {
        return (
            ServiceHealth::Degraded,
            Some(format!("Claude CLI not found in PATH: {bin}")),
        );
    }

    let env_raw = read_dashboard_env_raw(data_dir);
    if claude_env_auth_ready(&env_raw) {
        return (ServiceHealth::Healthy, None);
    }

    match read_claude_auth_status(bin) {
        Some(true) => (ServiceHealth::Healthy, None),
        Some(false) => (
            ServiceHealth::Degraded,
            Some("Claude CLI not authenticated".to_string()),
        ),
        None => (
            ServiceHealth::Unknown,
            Some("Claude auth status unavailable".to_string()),
        ),
    }
}

fn codex_db_path() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let path = PathBuf::from(home).join(".codex/state_5.sqlite");
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

fn is_codex_subagent_source(source: &str) -> bool {
    if source.is_empty() || source == "vscode" {
        return false;
    }

    let Ok(parsed) = serde_json::from_str::<Value>(source) else {
        return false;
    };

    parsed
        .as_object()
        .map(|obj| obj.contains_key("subagent"))
        .unwrap_or(false)
}

fn trimmed_opt(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn parse_workspace_snapshot(workspace_id: &str, workspace: &Value) -> Option<WorkspaceSnapshot> {
    let tool = workspace.get("tool").and_then(Value::as_str)?.to_string();
    let path = workspace.get("path").and_then(Value::as_str)?.to_string();
    Some(WorkspaceSnapshot {
        id: workspace_id.to_string(),
        name: workspace
            .get("name")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        tool,
        path,
    })
}

fn read_codex_workspace_activity(
    workspace: &WorkspaceSnapshot,
    db_path: Option<&Path>,
    overlays: &HashMap<String, LocalThreadOverlay>,
) -> Option<WorkspaceActivityCandidate> {
    let db_path = db_path?;
    let conn = Connection::open_with_flags(db_path, OpenFlags::SQLITE_OPEN_READ_ONLY).ok()?;
    let mut stmt = conn
        .prepare(
            "SELECT id, title, updated_at, source
             FROM threads
             WHERE cwd = ?1
               AND archived = 0
             ORDER BY updated_at DESC
             LIMIT 200",
        )
        .ok()?;

    let rows = stmt
        .query_map([workspace.path.as_str()], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, Option<String>>(3)?.unwrap_or_default(),
            ))
        })
        .ok()?;

    let mut active_thread_count = 0_u32;
    let mut latest_session_id = None;
    let mut latest_preview = None;
    let mut latest_updated_at = 0_i64;

    for row in rows {
        let Ok((thread_id, title, updated_at, source)) = row else {
            continue;
        };
        if is_codex_subagent_source(&source) {
            continue;
        }
        if overlays
            .get(&thread_id)
            .map(|overlay| overlay.archived)
            .unwrap_or(false)
        {
            continue;
        }

        active_thread_count = active_thread_count.saturating_add(1);
        if latest_session_id.is_none() {
            latest_session_id = Some(thread_id.clone());
            latest_preview = trimmed_opt(&title).or_else(|| {
                overlays
                    .get(&thread_id)
                    .and_then(|overlay| overlay.preview.clone())
            });
            latest_updated_at = normalize_activity_timestamp(updated_at);
        }
    }

    Some(WorkspaceActivityCandidate {
        workspace_id: workspace.id.clone(),
        workspace_name: workspace.name.clone(),
        tool: workspace.tool.clone(),
        session_id: latest_session_id?,
        preview: latest_preview,
        updated_at: latest_updated_at,
        active_thread_count,
    })
}

fn read_claude_workspace_activity(
    workspace: &WorkspaceSnapshot,
    overlays: &HashMap<String, LocalThreadOverlay>,
    projects_dir: Option<&Path>,
    history_path: Option<&Path>,
) -> Option<WorkspaceActivityCandidate> {
    let default_projects_dir = default_claude_projects_dir();
    let projects_dir = projects_dir.or(default_projects_dir.as_deref())?;
    let stored_sessions = load_claude_project_sessions_from_dir(projects_dir);
    let history_index = build_claude_history_index(history_path);

    let session_by_id = stored_sessions
        .into_iter()
        .map(|session| (session.id.clone(), session))
        .collect::<HashMap<_, _>>();

    let mut session_ids = session_by_id.keys().cloned().collect::<Vec<_>>();
    for session_id in history_index.keys() {
        if !session_by_id.contains_key(session_id) {
            session_ids.push(session_id.clone());
        }
    }

    let mut active_thread_count = 0_u32;
    let mut latest: Option<WorkspaceActivityCandidate> = None;

    for session_id in session_ids {
        if overlays
            .get(&session_id)
            .map(|overlay| overlay.archived)
            .unwrap_or(false)
        {
            continue;
        }

        let stored = session_by_id.get(&session_id);
        let history = history_index.get(&session_id);
        if stored
            .and_then(|item| item.session_file.as_deref())
            .map(should_skip_claude_session_from_workspace_list)
            .unwrap_or(false)
        {
            continue;
        }
        let logical_cwd = history
            .and_then(|item| item.project.as_deref())
            .or_else(|| stored.map(|item| item.cwd.as_str()));
        if logical_cwd != Some(workspace.path.as_str()) {
            continue;
        }

        let preview = history
            .and_then(|item| item.preview.clone())
            .or_else(|| {
                stored
                    .and_then(|item| item.session_file.as_deref())
                    .and_then(read_claude_project_session_preview)
            })
            .or_else(|| {
                overlays
                    .get(&session_id)
                    .and_then(|overlay| overlay.preview.clone())
            });
        if preview.is_none() {
            continue;
        }

        active_thread_count = active_thread_count.saturating_add(1);
        let updated_at = history
            .map(|item| item.updated_at)
            .unwrap_or_default()
            .max(stored.map(|item| item.updated_at).unwrap_or_default())
            .max(stored.map(|item| item.created_at).unwrap_or_default());
        let candidate = WorkspaceActivityCandidate {
            workspace_id: workspace.id.clone(),
            workspace_name: workspace.name.clone(),
            tool: workspace.tool.clone(),
            session_id: session_id.clone(),
            preview,
            updated_at,
            active_thread_count,
        };

        if latest
            .as_ref()
            .map(|existing| candidate.updated_at > existing.updated_at)
            .unwrap_or(true)
        {
            latest = Some(candidate);
        }
    }

    latest.map(|mut candidate| {
        candidate.active_thread_count = active_thread_count;
        candidate
    })
}

fn build_recent_activity_summary_from_candidate(
    candidate: WorkspaceActivityCandidate,
) -> RecentActivitySummary {
    RecentActivitySummary {
        active_workspace_id: Some(candidate.workspace_id),
        active_workspace_name: candidate.workspace_name,
        active_tool: Some(candidate.tool.clone()),
        active_session_id: Some(candidate.session_id),
        active_session_tool: Some(candidate.tool),
        highlighted_thread_preview: candidate.preview,
        active_thread_count: candidate.active_thread_count,
    }
}

fn read_recent_activity_summary_from_state(
    parsed: &Value,
    workspaces: &serde_json::Map<String, Value>,
) -> Option<RecentActivitySummary> {
    let active_workspace_id = parsed
        .get("active_workspace")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .filter(|id| workspaces.contains_key(id));

    let selected_workspace = active_workspace_id
        .as_ref()
        .and_then(|id| workspaces.get(id))
        .or_else(|| workspaces.values().next())?;

    let active_workspace_name = selected_workspace
        .get("name")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);
    let active_tool = selected_workspace
        .get("tool")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned);

    let (active_session_id, highlighted_thread_preview, active_thread_count) = selected_workspace
        .get("threads")
        .and_then(Value::as_object)
        .map(extract_thread_summary)
        .unwrap_or((None, None, 0));

    Some(RecentActivitySummary {
        active_workspace_id,
        active_workspace_name,
        active_tool: active_tool.clone(),
        active_session_id,
        active_session_tool: active_tool,
        highlighted_thread_preview,
        active_thread_count,
    })
}

fn read_recent_activity_summary(data_dir: &Path) -> Option<RecentActivitySummary> {
    let codex_db = codex_db_path();
    read_recent_activity_summary_from_paths(data_dir, codex_db.as_deref())
}

fn read_recent_activity_summary_from_paths(
    data_dir: &Path,
    codex_db: Option<&Path>,
) -> Option<RecentActivitySummary> {
    let path = data_dir.join("onlineworker_state.json");
    let raw = std::fs::read_to_string(&path).ok()?;
    let parsed: Value = serde_json::from_str(&raw).ok()?;
    let workspaces = parsed.get("workspaces")?.as_object()?;
    let codex_overlays = load_local_thread_overlays(&path, "codex");
    let claude_overlays = load_local_thread_overlays(&path, "claude");

    let latest = workspaces
        .iter()
        .filter_map(|(workspace_id, workspace)| parse_workspace_snapshot(workspace_id, workspace))
        .filter_map(|workspace| match workspace.tool.as_str() {
            "codex" => read_codex_workspace_activity(&workspace, codex_db, &codex_overlays),
            "claude" => read_claude_workspace_activity(
                &workspace,
                &claude_overlays,
                default_claude_projects_dir().as_deref(),
                default_claude_history_path().as_deref(),
            ),
            _ => None,
        })
        .max_by_key(|candidate| candidate.updated_at);

    latest
        .map(build_recent_activity_summary_from_candidate)
        .or_else(|| read_recent_activity_summary_from_state(&parsed, workspaces))
}

fn extract_thread_summary(
    threads: &serde_json::Map<String, Value>,
) -> (Option<String>, Option<String>, u32) {
    let mut active_session_id = None;
    let mut active_preview = None;
    let mut fallback_preview = None;
    let mut active_thread_count = 0_u32;

    for (thread_id, thread) in threads {
        let is_active = thread
            .get("is_active")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let archived = thread
            .get("archived")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let preview = thread
            .get("preview")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|text| !text.is_empty())
            .map(ToOwned::to_owned);

        if is_active && !archived {
            active_thread_count += 1;
            if active_session_id.is_none() {
                active_session_id = Some(thread_id.clone());
            }
            if active_preview.is_none() && preview.is_some() {
                active_preview = preview.clone();
            }
        }

        if fallback_preview.is_none() && preview.is_some() && !archived {
            fallback_preview = preview;
        }
    }

    (
        active_session_id,
        active_preview.or(fallback_preview),
        active_thread_count,
    )
}

#[cfg(test)]
mod tests {
    use super::{
        build_dashboard_state, build_provider_statuses, extract_thread_summary,
        read_claude_workspace_activity, read_env_key, read_recent_activity_summary,
        resolve_builtin_provider_snapshots, AlertLevel, DashboardComputationInput,
        ProviderConfigSnapshot, ProviderDashboardStatus, RecentActivitySummary, ServiceHealth,
        SystemHealth, WorkspaceSnapshot,
    };
    use serde_json::json;
    use std::fs;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::collections::HashMap;
    use std::thread;
    use std::time::{Duration, SystemTime};

    #[test]
    fn build_dashboard_state_marks_missing_required_config_as_misconfigured() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: false,
            missing_config_fields: vec!["TELEGRAM_TOKEN".into()],
            service_running: false,
            service_pid: None,
            providers: vec![],
            telegram_connected: None,
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Misconfigured);
        assert_eq!(state.alerts.len(), 1);
        assert_eq!(state.alerts[0].level, AlertLevel::Error);
    }

    #[test]
    fn build_dashboard_state_marks_stopped_when_config_ready_but_service_is_not_running() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: false,
            service_pid: None,
            providers: vec![],
            telegram_connected: Some(false),
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Stopped);
        assert_eq!(state.bot.process, ServiceHealth::Stopped);
    }

    #[test]
    fn build_dashboard_state_marks_degraded_when_any_subservice_is_degraded() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: true,
            service_pid: Some(4321),
            providers: vec![ProviderDashboardStatus {
                id: "codex".into(),
                managed: true,
                autostart: true,
                health: ServiceHealth::Degraded,
                port: None,
                detail: None,
                transport: Some("ws".into()),
                live_transport: Some("shared_ws".into()),
                control_mode: Some("app".into()),
                bin: Some("codex".into()),
            }],
            telegram_connected: None,
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Degraded);
        assert_eq!(state.codex.health, ServiceHealth::Degraded);
        assert_eq!(state.bot.process, ServiceHealth::Healthy);
    }

    #[test]
    fn build_provider_statuses_marks_missing_cli_as_stopped() {
        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "codex".into(),
                visible: true,
                managed: true,
                autostart: true,
                transport: "stdio".into(),
                live_transport: "owner_bridge".into(),
                port: None,
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some("/definitely/missing/onlineworker-test-codex".into()),
            }],
            std::path::Path::new("/tmp"),
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
            None,
        );

        assert_eq!(providers[0].health, ServiceHealth::Stopped);
        assert_eq!(
            providers[0].detail.as_deref(),
            Some("CLI not found in PATH: /definitely/missing/onlineworker-test-codex")
        );
    }

    #[test]
    fn build_provider_statuses_reads_overlay_provider_health_from_owner_bridge() {
        let temp_dir = std::env::temp_dir().join(format!("ow-dashboard-status-{}", std::process::id()));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader.read_line(&mut request).expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "runtime_status");
            assert_eq!(payload["provider_id"], "overlay-tool");

            let response = serde_json::json!({
                "ok": true,
                "health": "healthy",
                "detail": "• overlay-tool：✅ 已连接",
                "lines": ["• overlay-tool：✅ 已连接"],
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "overlay-tool".into(),
                visible: true,
                managed: true,
                autostart: true,
                transport: "http".into(),
                live_transport: "http".into(),
                port: Some(4096),
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some("/bin/sh".into()),
            }],
            &temp_dir,
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
            None,
        );

        assert_eq!(providers[0].health, ServiceHealth::Healthy);
        assert_eq!(
            providers[0].detail.as_deref(),
            Some("• overlay-tool：✅ 已连接")
        );

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn build_dashboard_state_marks_healthy_when_runtime_and_subservices_are_ready() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: true,
            service_pid: Some(4321),
            providers: vec![
                ProviderDashboardStatus {
                    id: "codex".into(),
                    managed: true,
                    autostart: true,
                    health: ServiceHealth::Healthy,
                    port: None,
                    detail: None,
                    transport: Some("ws".into()),
                    live_transport: Some("shared_ws".into()),
                    control_mode: Some("app".into()),
                    bin: Some("codex".into()),
                },
                ProviderDashboardStatus {
                    id: "claude".into(),
                    managed: false,
                    autostart: false,
                    health: ServiceHealth::Stopped,
                    port: None,
                    detail: Some("Provider is not managed by the app".into()),
                    transport: Some("stdio".into()),
                    live_transport: Some("stdio".into()),
                    control_mode: Some("app".into()),
                    bin: Some("claude".into()),
                },
            ],
            telegram_connected: Some(true),
            recent_activity: Some(RecentActivitySummary {
                active_workspace_id: Some("codex:onlineWorker".into()),
                active_workspace_name: Some("onlineWorker".into()),
                active_tool: Some("codex".into()),
                active_session_id: Some("ses_demo".into()),
                active_session_tool: Some("codex".into()),
                highlighted_thread_preview: Some("Phase C-2 执行继续".into()),
                active_thread_count: 3,
            }),
        });

        assert_eq!(state.overall, SystemHealth::Healthy);
        assert_eq!(state.bot.pid, Some(4321));
        assert_eq!(state.providers.len(), 1);
        assert_eq!(state.providers[0].id, "codex");
        assert_eq!(
            state
                .recent_activity
                .as_ref()
                .and_then(|activity| activity.highlighted_thread_preview.as_deref()),
            Some("Phase C-2 执行继续")
        );
        assert_eq!(
            state
                .recent_activity
                .as_ref()
                .and_then(|activity| activity.active_session_id.as_deref()),
            Some("ses_demo")
        );
    }

    #[test]
    fn build_dashboard_state_ignores_non_autostart_provider_for_overall_health() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: true,
            service_pid: Some(4321),
            providers: vec![
                ProviderDashboardStatus {
                    id: "codex".into(),
                    managed: true,
                    autostart: true,
                    health: ServiceHealth::Healthy,
                    port: None,
                    detail: None,
                    transport: Some("ws".into()),
                    live_transport: Some("shared_ws".into()),
                    control_mode: Some("app".into()),
                    bin: Some("codex".into()),
                },
                ProviderDashboardStatus {
                    id: "custom".into(),
                    managed: true,
                    autostart: false,
                    health: ServiceHealth::Stopped,
                    port: None,
                    detail: Some("Autostart disabled".into()),
                    transport: Some("stdio".into()),
                    live_transport: Some("stdio".into()),
                    control_mode: Some("app".into()),
                    bin: Some("custom".into()),
                },
            ],
            telegram_connected: Some(true),
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Healthy);
        assert!(state.alerts.is_empty());
    }

    #[test]
    fn build_dashboard_state_marks_degraded_when_claude_is_degraded() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: true,
            service_pid: Some(4321),
            providers: vec![
                ProviderDashboardStatus {
                    id: "codex".into(),
                    managed: true,
                    autostart: true,
                    health: ServiceHealth::Healthy,
                    port: None,
                    detail: None,
                    transport: Some("stdio".into()),
                    live_transport: Some("owner_bridge".into()),
                    control_mode: Some("app".into()),
                    bin: Some("codex".into()),
                },
                ProviderDashboardStatus {
                    id: "claude".into(),
                    managed: true,
                    autostart: true,
                    health: ServiceHealth::Degraded,
                    port: None,
                    detail: Some("Claude CLI not authenticated".into()),
                    transport: Some("stdio".into()),
                    live_transport: Some("stdio".into()),
                    control_mode: Some("app".into()),
                    bin: Some("claude".into()),
                },
            ],
            telegram_connected: Some(true),
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Degraded);
        assert!(state
            .alerts
            .iter()
            .any(|alert| alert.code == "claude_degraded"));
    }

    #[test]
    fn resolve_builtin_provider_snapshots_defaults_codex_to_stdio_owner_bridge() {
        let providers = resolve_builtin_provider_snapshots(None);
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex snapshot");

        assert_eq!(codex.transport, "stdio");
        assert_eq!(codex.live_transport, "owner_bridge");
        assert_eq!(codex.port, None);
    }

    #[test]
    fn resolve_builtin_provider_snapshots_migrates_legacy_codex_default_ws_to_stdio_owner_bridge() {
        let raw = r#"
tools:
  - name: codex
    enabled: true
    codex_bin: "codex"
    protocol: "ws"
    app_server_port: 4722
"#;

        let providers = resolve_builtin_provider_snapshots(Some(raw));
        let codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex snapshot");

        assert_eq!(codex.transport, "stdio");
        assert_eq!(codex.live_transport, "owner_bridge");
        assert_eq!(codex.port, None);
    }

    #[test]
    fn resolve_builtin_provider_snapshots_backfills_claude_and_omits_hidden_overlay_provider() {
        let raw = r#"
schema_version: 2
providers:
  codex:
    managed: true
    autostart: true
    bin: "codex"
    transport:
      type: "stdio"
    owner_transport: "stdio"
    live_transport: "owner_bridge"
    control_mode: "app"
  overlay-tool:
    visible: false
    managed: true
    autostart: true
    bin: "overlay-tool"
    transport:
      type: "http"
      app_server_port: 4096
    owner_transport: "http"
    live_transport: "http"
    control_mode: "app"
"#;

        let providers = resolve_builtin_provider_snapshots(Some(raw));
        let ids: Vec<_> = providers
            .iter()
            .map(|provider| provider.id.as_str())
            .collect();
        assert_eq!(ids, vec!["codex", "claude"]);

        let claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude snapshot");

        assert!(!claude.managed);
        assert!(!claude.autostart);
        assert_eq!(claude.transport, "stdio");
        assert_eq!(claude.live_transport, "stdio");
        assert_eq!(claude.bin.as_deref(), Some("claude"));
    }

    #[test]
    fn read_env_key_returns_matching_value() {
        let raw = "TELEGRAM_TOKEN=abc\nALLOWED_USER_ID=123\n";
        assert_eq!(read_env_key(raw, "ALLOWED_USER_ID").as_deref(), Some("123"));
        assert_eq!(read_env_key(raw, "GROUP_CHAT_ID"), None);
    }

    #[test]
    fn extract_thread_summary_prefers_active_non_archived_preview() {
        let threads = json!({
            "a": {"preview": "old", "archived": false, "is_active": false},
            "b": {"preview": "active one", "archived": false, "is_active": true},
            "c": {"preview": "", "archived": false, "is_active": true}
        });

        let (session_id, preview, active_count) =
            extract_thread_summary(threads.as_object().unwrap());
        assert_eq!(session_id.as_deref(), Some("b"));
        assert_eq!(preview.as_deref(), Some("active one"));
        assert_eq!(active_count, 2);
    }

    #[test]
    fn read_recent_activity_summary_reads_active_workspace_from_state_file() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-dashboard-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let state_path = dir.join("onlineworker_state.json");
        let payload = json!({
            "active_workspace": "codex:onlineWorker",
            "workspaces": {
                "codex:onlineWorker": {
                    "name": "onlineWorker",
                    "tool": "codex",
                    "threads": {
                        "t1": {"preview": "hello dashboard", "archived": false, "is_active": true}
                    }
                }
            }
        });
        std::fs::write(&state_path, serde_json::to_string(&payload).unwrap()).unwrap();

        let summary = read_recent_activity_summary(&dir).expect("recent activity");
        assert_eq!(
            summary.active_workspace_id.as_deref(),
            Some("codex:onlineWorker")
        );
        assert_eq!(
            summary.active_workspace_name.as_deref(),
            Some("onlineWorker")
        );
        assert_eq!(summary.active_session_id.as_deref(), Some("t1"));
        assert_eq!(summary.active_session_tool.as_deref(), Some("codex"));
        assert_eq!(
            summary.highlighted_thread_preview.as_deref(),
            Some("hello dashboard")
        );
        assert_eq!(summary.active_thread_count, 1);

        let _ = std::fs::remove_file(state_path);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn read_claude_workspace_activity_reads_local_session_store() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-dashboard-claude-activity-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let projects_dir = dir.join("projects");
        let history_path = dir.join("history.jsonl");
        let workspace_path = "/Users/example/Projects/onlineWorker";
        let session_file =
            projects_dir.join("-Users-example-Projects-onlineWorker/ses-claude-dashboard.jsonl");

        std::fs::create_dir_all(session_file.parent().expect("session parent")).unwrap();
        let session_rows = [
            json!({
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": workspace_path,
                "sessionId": "ses-claude-dashboard",
                "message": {"role": "user", "content": "继续 Claude dashboard 收口"},
            }),
            json!({
                "type": "assistant",
                "timestamp": "2026-04-07T10:31:19.002Z",
                "cwd": workspace_path,
                "sessionId": "ses-claude-dashboard",
                "message": {"role": "assistant", "content": "先补最近活动测试"},
            }),
        ];
        let session_content = session_rows
            .iter()
            .map(|row| serde_json::to_string(row).expect("session row"))
            .collect::<Vec<_>>()
            .join("\n");
        std::fs::write(&session_file, format!("{session_content}\n")).unwrap();

        let history_rows = [
            json!({
                "display": "/doctor",
                "timestamp": 1_775_603_600_000_i64,
                "project": workspace_path,
                "sessionId": "ses-claude-dashboard",
            }),
            json!({
                "display": "别的工程",
                "timestamp": 1_775_603_700_000_i64,
                "project": "/Users/example/Projects/other",
                "sessionId": "ses-other",
            }),
        ];
        let history_content = history_rows
            .iter()
            .map(|row| serde_json::to_string(row).expect("history row"))
            .collect::<Vec<_>>()
            .join("\n");
        std::fs::write(&history_path, format!("{history_content}\n")).unwrap();

        let candidate = read_claude_workspace_activity(
            &WorkspaceSnapshot {
                id: "claude:onlineWorker".into(),
                name: Some("onlineWorker".into()),
                tool: "claude".into(),
                path: workspace_path.into(),
            },
            &HashMap::new(),
            Some(&projects_dir),
            Some(&history_path),
        )
        .expect("claude activity");

        assert_eq!(candidate.workspace_id, "claude:onlineWorker");
        assert_eq!(candidate.workspace_name.as_deref(), Some("onlineWorker"));
        assert_eq!(candidate.tool, "claude");
        assert_eq!(candidate.session_id, "ses-claude-dashboard");
        assert_eq!(
            candidate.preview.as_deref(),
            Some("继续 Claude dashboard 收口")
        );
        assert_eq!(candidate.updated_at, 1_775_603_600_000_i64);
        assert_eq!(candidate.active_thread_count, 1);

        let _ = std::fs::remove_file(history_path);
        let _ = std::fs::remove_file(session_file);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn read_claude_workspace_activity_filters_noise_sessions() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-dashboard-claude-noise-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let projects_dir = dir.join("projects");
        let history_path = dir.join("history.jsonl");
        let workspace_path = "/Users/example/Projects/onlineWorker";

        std::fs::create_dir_all(&projects_dir).unwrap();
        std::fs::write(&history_path, "").unwrap();

        let cli_file = projects_dir.join("-Users-example-Projects-onlineWorker/ses-cli.jsonl");
        std::fs::create_dir_all(cli_file.parent().expect("cli parent")).unwrap();
        std::fs::write(
            &cli_file,
            format!(
                "{}\n",
                serde_json::to_string(&json!({
                    "type": "user",
                    "timestamp": "2026-04-07T09:33:42.791Z",
                    "cwd": workspace_path,
                    "sessionId": "ses-cli",
                    "entrypoint": "cli",
                    "message": {
                        "role": "user",
                        "content": "<local-command-caveat>Caveat: The messages below were generated by the user while running local commands. DO NOT respond.</local-command-caveat>",
                    },
                }))
                .unwrap()
            ),
        )
        .unwrap();

        let login_failed_file =
            projects_dir.join("-Users-example-Projects-onlineWorker/ses-login-failed.jsonl");
        std::fs::create_dir_all(login_failed_file.parent().expect("login parent")).unwrap();
        std::fs::write(
            &login_failed_file,
            format!(
                "{}\n{}\n",
                serde_json::to_string(&json!({
                    "type": "user",
                    "timestamp": "2026-04-12T11:47:36.917Z",
                    "cwd": workspace_path,
                    "sessionId": "ses-login-failed",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "Reply with exactly OK"},
                }))
                .unwrap(),
                serde_json::to_string(&json!({
                    "type": "assistant",
                    "timestamp": "2026-04-12T11:47:37.020Z",
                    "cwd": workspace_path,
                    "sessionId": "ses-login-failed",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Not logged in · Please run /login"}],
                    },
                }))
                .unwrap()
            ),
        )
        .unwrap();

        let real_file = projects_dir.join("-Users-example-Projects-onlineWorker/ses-real.jsonl");
        std::fs::create_dir_all(real_file.parent().expect("real parent")).unwrap();
        std::fs::write(
            &real_file,
            format!(
                "{}\n{}\n",
                serde_json::to_string(&json!({
                    "type": "user",
                    "timestamp": "2026-04-16T02:30:22.087Z",
                    "cwd": workspace_path,
                    "sessionId": "ses-real",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "现在可以了么？"},
                }))
                .unwrap(),
                serde_json::to_string(&json!({
                    "type": "assistant",
                    "timestamp": "2026-04-16T02:30:27.397Z",
                    "cwd": workspace_path,
                    "sessionId": "ses-real",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "可以了！"}],
                    },
                }))
                .unwrap()
            ),
        )
        .unwrap();

        let candidate = read_claude_workspace_activity(
            &WorkspaceSnapshot {
                id: "claude:onlineWorker".into(),
                name: Some("onlineWorker".into()),
                tool: "claude".into(),
                path: workspace_path.into(),
            },
            &HashMap::new(),
            Some(&projects_dir),
            Some(&history_path),
        )
        .expect("claude activity");

        assert_eq!(candidate.session_id, "ses-real");
        assert_eq!(candidate.preview.as_deref(), Some("现在可以了么？"));
        assert_eq!(candidate.active_thread_count, 1);

        let _ = std::fs::remove_dir_all(dir);
    }
}
