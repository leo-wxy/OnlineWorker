use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum SystemHealth {
    Healthy,
    Degraded,
    Misconfigured,
    Stopped,
    Unknown,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ServiceHealth {
    Healthy,
    Degraded,
    Stopped,
    Unknown,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum ConnectionStatus {
    Connected,
    Disconnected,
    Unknown,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum AlertLevel {
    Warning,
    Error,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct Alert {
    pub level: AlertLevel,
    pub code: String,
    pub title: String,
    pub detail: String,
    pub action: Option<String>,
    pub action_code: Option<String>,
    #[serde(default)]
    pub missing_fields: Vec<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct BotDashboardStatus {
    pub process: ServiceHealth,
    pub telegram: ConnectionStatus,
    pub pid: Option<u32>,
    pub last_heartbeat: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ToolDashboardStatus {
    pub health: ServiceHealth,
    pub port: Option<u16>,
    pub detail: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderDashboardStatus {
    pub id: String,
    pub managed: bool,
    pub autostart: bool,
    pub health: ServiceHealth,
    pub port: Option<u16>,
    pub detail: Option<String>,
    pub transport: Option<String>,
    pub live_transport: Option<String>,
    pub control_mode: Option<String>,
    pub bin: Option<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct RecentActivitySummary {
    pub active_workspace_id: Option<String>,
    pub active_workspace_name: Option<String>,
    pub active_tool: Option<String>,
    pub active_session_id: Option<String>,
    pub active_session_tool: Option<String>,
    pub highlighted_thread_preview: Option<String>,
    pub active_thread_count: u32,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DashboardState {
    pub overall: SystemHealth,
    pub bot: BotDashboardStatus,
    pub providers: Vec<ProviderDashboardStatus>,
    pub codex: ToolDashboardStatus,
    pub alerts: Vec<Alert>,
    pub recent_activity: Option<RecentActivitySummary>,
    pub generated_at_epoch: u64,
}

#[derive(Clone, Debug)]
pub struct DashboardComputationInput {
    pub config_ready: bool,
    pub missing_config_fields: Vec<String>,
    pub service_running: bool,
    pub service_pid: Option<u32>,
    pub providers: Vec<ProviderDashboardStatus>,
    pub telegram_connected: Option<bool>,
    pub recent_activity: Option<RecentActivitySummary>,
}
