use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

use chrono::{Local, NaiveDateTime, TimeZone};

use super::config::ensure_data_dir;
use super::service::{ensure_service_running_if_needed, snapshot_service_status, BotState};

#[path = "dashboard_types.rs"]
mod dashboard_types;
#[path = "dashboard/provider_status.rs"]
mod provider_status;
#[path = "dashboard/recent_activity.rs"]
mod recent_activity;
pub use self::dashboard_types::*;
use provider_status::{
    build_provider_statuses, has_subservice_problem, is_hidden_provider, read_provider_snapshots,
};
#[cfg(test)]
use provider_status::{
    read_provider_runtime_status_via_owner_bridge_with_timeout, resolve_builtin_provider_snapshots,
    ProviderConfigSnapshot,
};
use recent_activity::read_recent_activity_summary;
#[cfg(test)]
use recent_activity::{
    build_claude_activity_index, extract_thread_summary, read_claude_workspace_activity,
    read_recent_activity_summary_cached_with_now, WorkspaceSnapshot, RECENT_ACTIVITY_CACHE_TTL,
};

const REQUIRED_ENV_KEYS: &[&str] = &["TELEGRAM_TOKEN", "ALLOWED_USER_ID", "GROUP_CHAT_ID"];
const TELEGRAM_POLLING_STALE_AFTER_SECS: u64 = 90;
const TELEGRAM_LOG_SCAN_BYTES: u64 = 256 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct TelegramPollingDiagnostic {
    connected: Option<bool>,
    detail: Option<String>,
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
    let provider_configs = read_provider_snapshots(&dir)?;
    let providers = build_provider_statuses(
        provider_configs,
        &dir,
        service.running,
        managed_service_running,
        last_started_at,
        now,
    );

    let telegram = if service.running {
        read_telegram_polling_diagnostic(&dir, now)
    } else {
        TelegramPollingDiagnostic {
            connected: Some(false),
            detail: Some("Bot process is not running".to_string()),
        }
    };

    Ok(build_dashboard_state(DashboardComputationInput {
        config_ready,
        missing_config_fields,
        service_running: service.running,
        service_pid: service.pid,
        providers,
        telegram_connected: telegram.connected,
        telegram_detail: telegram.detail,
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

    if input.service_running {
        for provider in visible_providers.iter().filter(|provider| {
            provider.managed && provider.autostart && has_subservice_problem(&provider.health)
        }) {
            alerts.push(Alert {
                level: AlertLevel::Warning,
                code: "provider_degraded".to_string(),
                title: format!("{} status degraded", provider.id),
                detail: provider.detail.clone().unwrap_or_else(|| {
                    format!(
                        "{} runtime looks unavailable from the app diagnostics view",
                        provider.id
                    )
                }),
                action: Some("Open Logs".to_string()),
                action_code: Some("open_logs".to_string()),
                missing_fields: Vec::new(),
            });
        }
    }

    if input.service_running && telegram == ConnectionStatus::Disconnected {
        alerts.push(Alert {
            level: AlertLevel::Warning,
            code: "telegram_unavailable".to_string(),
            title: "Telegram connection unavailable".to_string(),
            detail: input.telegram_detail.clone().unwrap_or_else(|| {
                "Bot process is up, but Telegram connectivity is reported as disconnected"
                    .to_string()
            }),
            action: Some("Open Setup".to_string()),
            action_code: Some("open_setup".to_string()),
            missing_fields: Vec::new(),
        });
    }

    let overall = if !input.config_ready {
        SystemHealth::Misconfigured
    } else if !input.service_running {
        SystemHealth::Stopped
    } else if visible_providers.iter().any(|provider| {
        provider.managed && provider.autostart && has_subservice_problem(&provider.health)
    }) || telegram == ConnectionStatus::Disconnected
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
        alerts,
        recent_activity: input.recent_activity,
        generated_at_epoch: SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs(),
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

fn read_tail(path: &Path, max_bytes: u64) -> Result<String, String> {
    let mut file =
        File::open(path).map_err(|e| format!("Cannot open {}: {}", path.display(), e))?;
    let len = file
        .metadata()
        .map_err(|e| format!("Cannot stat {}: {}", path.display(), e))?
        .len();
    let start = len.saturating_sub(max_bytes);
    file.seek(SeekFrom::Start(start))
        .map_err(|e| format!("Cannot seek {}: {}", path.display(), e))?;
    let mut buf = Vec::new();
    file.read_to_end(&mut buf)
        .map_err(|e| format!("Cannot read {}: {}", path.display(), e))?;
    Ok(String::from_utf8_lossy(&buf).into_owned())
}

fn is_telegram_polling_success_line(line: &str) -> bool {
    line.contains("api.telegram.org")
        && line.contains("/getUpdates")
        && line.contains("\"HTTP/1.1 200 OK\"")
}

fn is_telegram_polling_error_line(line: &str) -> bool {
    line.contains("[ptb-error]")
        || line.contains("telegram.error.NetworkError")
        || line.contains("telegram.error.TimedOut")
        || line.contains("httpx.ConnectError")
        || (line.contains("api.telegram.org")
            && line.contains("/getUpdates")
            && !line.contains("\"HTTP/1.1 200 OK\""))
}

fn parse_log_timestamp(line: &str) -> Option<SystemTime> {
    let raw = line.get(0..23).or_else(|| line.get(0..19))?;
    let format = if raw.len() >= 23 {
        "%Y-%m-%d %H:%M:%S,%3f"
    } else {
        "%Y-%m-%d %H:%M:%S"
    };
    let naive = NaiveDateTime::parse_from_str(raw, format).ok()?;
    let local = Local.from_local_datetime(&naive).single()?;
    let timestamp = local.timestamp();
    let nanos = local.timestamp_subsec_nanos();
    if timestamp >= 0 {
        Some(
            UNIX_EPOCH + Duration::from_secs(timestamp as u64) + Duration::from_nanos(nanos.into()),
        )
    } else {
        UNIX_EPOCH
            .checked_sub(Duration::from_secs(timestamp.unsigned_abs()))
            .and_then(|time| time.checked_add(Duration::from_nanos(nanos.into())))
    }
}

fn redact_telegram_token(line: &str) -> String {
    let Some(start) = line.find("/bot") else {
        return line.to_string();
    };
    let token_start = start + "/bot".len();
    let token_end = line[token_start..]
        .find('/')
        .map(|offset| token_start + offset)
        .unwrap_or(line.len());
    let mut redacted = String::with_capacity(line.len());
    redacted.push_str(&line[..token_start]);
    redacted.push_str("[redacted]");
    redacted.push_str(&line[token_end..]);
    redacted
}

fn diagnose_telegram_polling_from_log(raw: &str, now: SystemTime) -> TelegramPollingDiagnostic {
    let mut current_timestamp: Option<SystemTime> = None;
    let mut last_polling_event: Option<(bool, SystemTime, String)> = None;

    for line in raw.lines() {
        if let Some(timestamp) = parse_log_timestamp(line) {
            current_timestamp = Some(timestamp);
        }
        if is_telegram_polling_success_line(line) {
            let ts = current_timestamp.unwrap_or(now);
            last_polling_event = Some((true, ts, line.to_string()));
        } else if is_telegram_polling_error_line(line) {
            let ts = current_timestamp.unwrap_or(now);
            last_polling_event = Some((false, ts, line.to_string()));
        }
    }

    if let Some((ok, timestamp, line)) = last_polling_event {
        let age = now.duration_since(timestamp).unwrap_or_default().as_secs();
        if ok && age <= TELEGRAM_POLLING_STALE_AFTER_SECS {
            return TelegramPollingDiagnostic {
                connected: Some(true),
                detail: Some(format!("Last Telegram getUpdates success {}s ago", age)),
            };
        }
        if ok {
            return TelegramPollingDiagnostic {
                connected: Some(false),
                detail: Some(format!(
                    "Telegram getUpdates has no recent successful response for {}s",
                    age
                )),
            };
        }
        return TelegramPollingDiagnostic {
            connected: Some(false),
            detail: Some(format!(
                "Recent Telegram polling error: {}",
                redact_telegram_token(&line)
            )),
        };
    }

    TelegramPollingDiagnostic {
        connected: None,
        detail: Some("No Telegram polling result has been observed yet".to_string()),
    }
}

fn read_telegram_polling_diagnostic(data_dir: &Path, now: SystemTime) -> TelegramPollingDiagnostic {
    let log_path = data_dir.join("onlineworker.log");
    if !log_path.exists() {
        return TelegramPollingDiagnostic {
            connected: None,
            detail: Some("onlineworker.log is not available yet".to_string()),
        };
    }
    match read_tail(&log_path, TELEGRAM_LOG_SCAN_BYTES) {
        Ok(raw) => diagnose_telegram_polling_from_log(&raw, now),
        Err(error) => TelegramPollingDiagnostic {
            connected: None,
            detail: Some(error),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::{
        build_claude_activity_index, build_dashboard_state, build_provider_statuses,
        diagnose_telegram_polling_from_log, extract_thread_summary, read_claude_workspace_activity,
        read_env_key, read_provider_runtime_status_via_owner_bridge_with_timeout,
        read_recent_activity_summary, read_recent_activity_summary_cached_with_now,
        redact_telegram_token, resolve_builtin_provider_snapshots, AlertLevel,
        DashboardComputationInput, ProviderConfigSnapshot, ProviderDashboardStatus,
        RecentActivitySummary, ServiceHealth, SystemHealth, TelegramPollingDiagnostic,
        WorkspaceSnapshot, RECENT_ACTIVITY_CACHE_TTL,
    };
    use serde_json::json;
    use std::collections::HashMap;
    use std::fs;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::net::UnixListener;
    use std::thread;
    use std::time::{Duration, SystemTime};

    fn local_log_time(now: SystemTime, delta: Duration) -> String {
        let timestamp = now.checked_sub(delta).unwrap_or(now);
        let datetime: chrono::DateTime<chrono::Local> = timestamp.into();
        datetime.format("%Y-%m-%d %H:%M:%S,%3f").to_string()
    }

    #[test]
    fn build_dashboard_state_marks_missing_required_config_as_misconfigured() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: false,
            missing_config_fields: vec!["TELEGRAM_TOKEN".into()],
            service_running: false,
            service_pid: None,
            providers: vec![],
            telegram_connected: None,
            telegram_detail: None,
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
            telegram_detail: None,
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
                icon: None,
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
            telegram_detail: None,
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Degraded);
        assert_eq!(state.providers[0].health, ServiceHealth::Degraded);
        assert_eq!(state.bot.process, ServiceHealth::Healthy);
    }

    #[test]
    fn build_dashboard_state_marks_degraded_when_telegram_is_disconnected() {
        let state = build_dashboard_state(DashboardComputationInput {
            config_ready: true,
            missing_config_fields: vec![],
            service_running: true,
            service_pid: Some(4321),
            providers: vec![],
            telegram_connected: Some(false),
            telegram_detail: Some("Recent Telegram polling error: connection refused".into()),
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Degraded);
        assert_eq!(state.bot.telegram, super::ConnectionStatus::Disconnected);
        assert_eq!(state.alerts.len(), 1);
        assert_eq!(state.alerts[0].code, "telegram_unavailable");
        assert_eq!(
            state.alerts[0].detail,
            "Recent Telegram polling error: connection refused"
        );
    }

    #[test]
    fn telegram_polling_diagnostic_marks_recent_get_updates_success_connected() {
        let now = SystemTime::now();
        let raw = format!(
            "{} [INFO] httpx: HTTP Request: POST https://api.telegram.org/botsecret-token/getUpdates \"HTTP/1.1 200 OK\"",
            local_log_time(now, Duration::from_secs(12))
        );

        assert_eq!(
            diagnose_telegram_polling_from_log(&raw, now),
            TelegramPollingDiagnostic {
                connected: Some(true),
                detail: Some("Last Telegram getUpdates success 12s ago".into()),
            }
        );
    }

    #[test]
    fn telegram_polling_diagnostic_marks_stale_success_disconnected() {
        let now = SystemTime::now();
        let raw = format!(
            "{} [INFO] httpx: HTTP Request: POST https://api.telegram.org/botsecret-token/getUpdates \"HTTP/1.1 200 OK\"",
            local_log_time(now, Duration::from_secs(120))
        );
        let diagnostic = diagnose_telegram_polling_from_log(&raw, now);

        assert_eq!(diagnostic.connected, Some(false));
        assert!(diagnostic
            .detail
            .as_deref()
            .unwrap_or_default()
            .contains("no recent successful response"));
    }

    #[test]
    fn telegram_polling_diagnostic_marks_recent_error_disconnected_and_redacts_token() {
        let now = SystemTime::now();
        let raw = format!(
            "{} [ERROR] __main__: [ptb-error] update_type=None error=httpx.ConnectError: All connection attempts failed\n\
             {} [INFO] httpx: HTTP Request: POST https://api.telegram.org/bot8533277450:SECRET/getUpdates \"HTTP/1.1 500 ERROR\"",
            local_log_time(now, Duration::from_secs(10)),
            local_log_time(now, Duration::from_secs(10))
        );
        let diagnostic = diagnose_telegram_polling_from_log(&raw, now);

        assert_eq!(diagnostic.connected, Some(false));
        let detail = diagnostic.detail.unwrap_or_default();
        assert!(detail.contains("Recent Telegram polling error"));
        assert!(!detail.contains("8533277450:SECRET"));
        assert!(detail.contains("/bot[redacted]/getUpdates"));
    }

    #[test]
    fn telegram_token_redaction_leaves_non_telegram_lines_unchanged() {
        assert_eq!(redact_telegram_token("plain error"), "plain error");
        assert_eq!(
            redact_telegram_token("https://api.telegram.org/botabc:def/getUpdates"),
            "https://api.telegram.org/bot[redacted]/getUpdates"
        );
    }

    #[test]
    fn build_provider_statuses_marks_missing_cli_as_stopped() {
        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "codex".into(),
                icon: None,
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
        );

        assert_eq!(providers[0].health, ServiceHealth::Stopped);
        assert_eq!(
            providers[0].detail.as_deref(),
            Some("CLI not found in PATH: /definitely/missing/onlineworker-test-codex")
        );
    }

    #[test]
    fn build_provider_statuses_accepts_cli_command_line_with_arguments() {
        let temp_dir = std::env::temp_dir().join(format!(
            "ow-dashboard-cli-command-line-{}",
            std::process::id()
        ));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let cli = temp_dir.join("raven");
        fs::write(&cli, "#!/bin/sh\nexit 0\n").expect("write cli");
        let mut permissions = fs::metadata(&cli).expect("cli metadata").permissions();
        permissions.set_mode(0o755);
        fs::set_permissions(&cli, permissions).expect("chmod cli");

        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "claude".into(),
                icon: None,
                visible: true,
                managed: true,
                autostart: true,
                transport: "stdio".into(),
                live_transport: "owner_bridge".into(),
                port: None,
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some(format!("{} cc", cli.display())),
            }],
            &temp_dir,
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
        );

        assert_ne!(providers[0].health, ServiceHealth::Stopped);
        assert_ne!(
            providers[0].detail.as_deref(),
            Some(format!("CLI not found in PATH: {} cc", cli.display()).as_str())
        );

        let _ = fs::remove_file(cli);
        let _ = fs::remove_dir_all(temp_dir);
    }

    #[test]
    fn build_provider_statuses_reads_overlay_provider_health_from_owner_bridge() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-dashboard-status-{}", std::process::id()));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
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
                icon: None,
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
    fn build_provider_statuses_reads_codex_health_from_owner_bridge() {
        let temp_dir =
            std::path::PathBuf::from("/tmp").join(format!("ow-cdx-status-{}", std::process::id()));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "runtime_status");
            assert_eq!(payload["provider_id"], "codex");

            let response = serde_json::json!({
                "ok": true,
                "health": "degraded",
                "detail": "• codex：连接不可用",
                "lines": ["• codex：连接不可用"],
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "codex".into(),
                icon: None,
                visible: true,
                managed: true,
                autostart: true,
                transport: "stdio".into(),
                live_transport: "owner_bridge".into(),
                port: None,
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some("/bin/sh".into()),
            }],
            &temp_dir,
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
        );

        assert_eq!(providers[0].health, ServiceHealth::Degraded);
        assert_eq!(providers[0].detail.as_deref(), Some("• codex：连接不可用"));

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn build_provider_statuses_reads_claude_health_from_owner_bridge() {
        let temp_dir = std::path::PathBuf::from("/tmp")
            .join(format!("ow-dashboard-claude-status-{}", std::process::id()));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "runtime_status");
            assert_eq!(payload["provider_id"], "claude");

            let response = serde_json::json!({
                "ok": true,
                "health": "healthy",
                "detail": "• claude CLI：✅ 已连接",
                "lines": ["• claude CLI：✅ 已连接"],
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "claude".into(),
                icon: None,
                visible: true,
                managed: true,
                autostart: true,
                transport: "stdio".into(),
                live_transport: "stdio".into(),
                port: None,
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some("claude".into()),
            }],
            &temp_dir,
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
        );

        assert_eq!(providers[0].health, ServiceHealth::Healthy);
        assert_eq!(
            providers[0].detail.as_deref(),
            Some("• claude CLI：✅ 已连接")
        );

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn provider_status_does_not_fall_back_to_cli_when_owner_bridge_times_out() {
        let temp_dir = std::path::PathBuf::from("/tmp").join(format!(
            "ow-dashboard-claude-timeout-{}",
            std::process::id()
        ));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (_stream, _) = listener.accept().expect("accept owner bridge socket");
            thread::sleep(Duration::from_millis(250));
        });

        let providers = build_provider_statuses(
            vec![ProviderConfigSnapshot {
                id: "runtime-tool".into(),
                icon: None,
                visible: true,
                managed: true,
                autostart: true,
                transport: "stdio".into(),
                live_transport: "stdio".into(),
                port: None,
                app_server_url: None,
                control_mode: Some("app".into()),
                bin: Some("/definitely/missing/onlineworker-test-runtime-tool".into()),
            }],
            &temp_dir,
            true,
            true,
            Some(SystemTime::UNIX_EPOCH),
            SystemTime::UNIX_EPOCH + Duration::from_secs(60),
        );

        assert_eq!(providers[0].health, ServiceHealth::Unknown);
        assert!(providers[0]
            .detail
            .as_deref()
            .unwrap_or_default()
            .contains("runtime-tool runtime status unavailable"));

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_runtime_status_read_respects_short_timeout() {
        let temp_dir = std::path::PathBuf::from("/tmp").join(format!(
            "ow-dashboard-status-timeout-{}",
            std::process::id()
        ));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (_stream, _) = listener.accept().expect("accept owner bridge socket");
            thread::sleep(Duration::from_millis(250));
        });

        let result = read_provider_runtime_status_via_owner_bridge_with_timeout(
            &temp_dir,
            "claude",
            Duration::from_millis(20),
        );

        assert!(result.is_err());

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
                    icon: None,
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
                    icon: None,
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
            telegram_detail: None,
            recent_activity: Some(RecentActivitySummary {
                active_workspace_id: Some("codex:onlineWorker".into()),
                active_workspace_name: Some("onlineWorker".into()),
                active_workspace_path: Some("/Users/example/Projects/onlineWorker".into()),
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
                    icon: None,
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
                    icon: None,
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
            telegram_detail: None,
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
                    icon: None,
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
                    icon: None,
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
            telegram_detail: None,
            recent_activity: None,
        });

        assert_eq!(state.overall, SystemHealth::Degraded);
        assert!(state
            .alerts
            .iter()
            .any(|alert| alert.code == "provider_degraded"
                && alert.title == "claude status degraded"));
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
    fn read_recent_activity_summary_cache_reuses_recent_snapshot_until_ttl() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-dashboard-cache-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        let state_path = dir.join("onlineworker_state.json");

        let write_preview = |preview: &str| {
            let payload = json!({
                "active_workspace": "codex:onlineWorker",
                "workspaces": {
                    "codex:onlineWorker": {
                        "name": "onlineWorker",
                        "tool": "codex",
                        "threads": {
                            "t1": {"preview": preview, "archived": false, "is_active": true}
                        }
                    }
                }
            });
            std::fs::write(&state_path, serde_json::to_string(&payload).unwrap()).unwrap();
        };

        let base = std::time::UNIX_EPOCH + Duration::from_secs(1_800_000_000);
        write_preview("first snapshot");
        let first = read_recent_activity_summary_cached_with_now(&dir, None, base)
            .expect("first recent activity");
        assert_eq!(
            first.highlighted_thread_preview.as_deref(),
            Some("first snapshot")
        );

        write_preview("second snapshot");
        let cached = read_recent_activity_summary_cached_with_now(
            &dir,
            None,
            base + Duration::from_secs(RECENT_ACTIVITY_CACHE_TTL.as_secs() / 2),
        )
        .expect("cached recent activity");
        assert_eq!(
            cached.highlighted_thread_preview.as_deref(),
            Some("first snapshot")
        );

        let refreshed = read_recent_activity_summary_cached_with_now(
            &dir,
            None,
            base + RECENT_ACTIVITY_CACHE_TTL + Duration::from_secs(1),
        )
        .expect("refreshed recent activity");
        assert_eq!(
            refreshed.highlighted_thread_preview.as_deref(),
            Some("second snapshot")
        );

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

        let index = build_claude_activity_index(Some(&projects_dir), Some(&history_path));
        let candidate = read_claude_workspace_activity(
            &WorkspaceSnapshot {
                id: "claude:onlineWorker".into(),
                name: Some("onlineWorker".into()),
                tool: "claude".into(),
                path: workspace_path.into(),
            },
            &HashMap::new(),
            &index,
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

        let index = build_claude_activity_index(Some(&projects_dir), Some(&history_path));
        let candidate = read_claude_workspace_activity(
            &WorkspaceSnapshot {
                id: "claude:onlineWorker".into(),
                name: Some("onlineWorker".into()),
                tool: "claude".into(),
                path: workspace_path.into(),
            },
            &HashMap::new(),
            &index,
        )
        .expect("claude activity");

        assert_eq!(candidate.session_id, "ses-real");
        assert_eq!(candidate.preview.as_deref(), Some("现在可以了么？"));
        assert_eq!(candidate.active_thread_count, 1);

        let _ = std::fs::remove_dir_all(dir);
    }
}
