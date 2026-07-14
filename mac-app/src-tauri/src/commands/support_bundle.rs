use serde::{Deserialize, Serialize};
use serde_yaml::Value;
use std::path::{Component, Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use tauri::AppHandle;
use tokio::sync::Mutex;
use tokio::task::JoinSet;

use super::config::{data_dir, read_provider_metadata_from_disk};
use super::dashboard::{compute_dashboard_state, ServiceHealth};
use super::provider_usage::{
    get_provider_plugin_load_failures, get_usage_source_catalog, get_usage_source_summary,
    ProviderPluginLoadFailure, UsageSourceCatalogEntry, UsageSourceSummary,
};
use super::service::{snapshot_service_status, BotState};

const SUPPORT_LOG_MAX_BYTES: usize = 2 * 1024 * 1024;
const DIAGNOSTIC_PROBE_TIMEOUT: Duration = Duration::from_secs(6);
const REDACTED: &str = "[REDACTED]";
const CONFIG_VALUE: &str = "[VALUE]";

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticCheck {
    pub id: String,
    pub label: String,
    pub status: String,
    pub summary: String,
    pub detail: Option<String>,
    pub remediation: Option<String>,
    pub duration_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DiagnosticReport {
    pub generated_at: String,
    pub overall: String,
    pub checks: Vec<DiagnosticCheck>,
}

#[derive(Clone, Debug)]
struct DiagnosticInputs {
    app_version: String,
    app_path: PathBuf,
    data_dir: PathBuf,
    bot_running: bool,
    bot_pid: Option<u32>,
    provider_ids: Vec<String>,
}

fn diagnostic_check(
    id: &str,
    label: &str,
    status: &str,
    summary: impl Into<String>,
    detail: Option<String>,
    remediation: Option<String>,
    started_at: Instant,
) -> DiagnosticCheck {
    DiagnosticCheck {
        id: id.into(),
        label: label.into(),
        status: status.into(),
        summary: summary.into(),
        detail,
        remediation,
        duration_ms: started_at.elapsed().as_millis() as u64,
    }
}

fn provider_plugin_load_check(
    result: Result<Vec<ProviderPluginLoadFailure>, String>,
    started_at: Instant,
) -> DiagnosticCheck {
    match result {
        Ok(failures) if failures.is_empty() => diagnostic_check(
            "provider_plugin_load",
            "Provider plugin loading",
            "pass",
            "All provider plugins loaded",
            None,
            None,
            started_at,
        ),
        Ok(failures) => {
            let detail = failures
                .iter()
                .map(|failure| {
                    format!(
                        "{} | {} | {} | {}",
                        if failure.provider_id.is_empty() {
                            "unknown"
                        } else {
                            &failure.provider_id
                        },
                        if failure.entrypoint.is_empty() {
                            "<unavailable>"
                        } else {
                            &failure.entrypoint
                        },
                        failure.error,
                        failure.manifest_path,
                    )
                })
                .collect::<Vec<_>>()
                .join("\n");
            diagnostic_check(
                "provider_plugin_load",
                "Provider plugin loading",
                "fail",
                format!("{} provider plugin(s) failed to load", failures.len()),
                Some(detail),
                Some("Update or disable the incompatible provider plugin.".into()),
                started_at,
            )
        }
        Err(error) => diagnostic_check(
            "provider_plugin_load",
            "Provider plugin loading",
            "warning",
            "Provider plugin load failures could not be queried",
            Some(error),
            Some("Review the runtime log and owner bridge state.".into()),
            started_at,
        ),
    }
}

fn usage_catalog_check(
    result: &Result<Vec<UsageSourceCatalogEntry>, String>,
    started_at: Instant,
) -> DiagnosticCheck {
    match result {
        Ok(sources) if sources.is_empty() => diagnostic_check(
            "usage_catalog",
            "Usage catalog",
            "warning",
            "Usage catalog returned no sources",
            None,
            Some("Check packaged usage plugins and their manifests.".into()),
            started_at,
        ),
        Ok(sources) => diagnostic_check(
            "usage_catalog",
            "Usage catalog",
            "pass",
            format!("{} usage source(s) discovered", sources.len()),
            None,
            None,
            started_at,
        ),
        Err(error) => diagnostic_check(
            "usage_catalog",
            "Usage catalog",
            "fail",
            "Usage catalog request failed",
            Some(error.clone()),
            Some("Review usage plugin loading and owner bridge logs.".into()),
            started_at,
        ),
    }
}

fn usage_summary_check(
    source: &UsageSourceCatalogEntry,
    result: Result<UsageSourceSummary, String>,
    started_at: Instant,
) -> DiagnosticCheck {
    let label = format!("{} usage", source.label);
    let id = format!("usage:{}:{}", source.plugin_id, source.source_id);
    match result {
        Ok(summary) if summary.unsupported_reason.is_some() => diagnostic_check(
            &id,
            &label,
            "warning",
            "Usage source is unsupported",
            summary.unsupported_reason,
            None,
            started_at,
        ),
        Ok(summary) => diagnostic_check(
            &id,
            &label,
            "pass",
            format!("Usage query returned {} day(s)", summary.days.len()),
            source
                .provider_id
                .as_ref()
                .map(|provider_id| format!("Provider: {provider_id}")),
            None,
            started_at,
        ),
        Err(error) => diagnostic_check(
            &id,
            &label,
            "fail",
            "Usage query failed",
            Some(error),
            Some("Review the usage plugin, sidecar, and owner bridge logs.".into()),
            started_at,
        ),
    }
}

fn collect_diagnostic_report(inputs: &DiagnosticInputs) -> DiagnosticReport {
    let mut checks = Vec::with_capacity(7);

    let started_at = Instant::now();
    checks.push(diagnostic_check(
        "app",
        "OnlineWorker",
        if inputs.app_version.trim().is_empty() {
            "fail"
        } else {
            "pass"
        },
        format!("Version {}", inputs.app_version),
        Some(format!("Installed path: {}", inputs.app_path.display())),
        None,
        started_at,
    ));

    let started_at = Instant::now();
    checks.push(diagnostic_check(
        "service",
        "Managed service",
        if inputs.bot_running {
            "pass"
        } else {
            "warning"
        },
        if inputs.bot_running {
            format!(
                "Bot is running{}",
                inputs
                    .bot_pid
                    .map(|pid| format!(" (pid {pid})"))
                    .unwrap_or_default()
            )
        } else {
            "Bot is stopped".into()
        },
        None,
        (!inputs.bot_running).then(|| "Start the service from Dashboard.".into()),
        started_at,
    ));

    let started_at = Instant::now();
    let config_path = inputs.data_dir.join("config.yaml");
    let config_result = std::fs::read_to_string(&config_path)
        .map_err(|error| format!("read failed: {error}"))
        .and_then(|raw| {
            serde_yaml::from_str::<Value>(&raw)
                .map(|_| ())
                .map_err(|error| format!("parse failed: {error}"))
        });
    checks.push(match config_result {
        Ok(()) => diagnostic_check(
            "config",
            "Configuration",
            "pass",
            "Configuration is readable",
            Some(config_path.display().to_string()),
            None,
            started_at,
        ),
        Err(error) => diagnostic_check(
            "config",
            "Configuration",
            "fail",
            "Configuration is unavailable or invalid",
            Some(error),
            Some("Open Settings and save a valid configuration.".into()),
            started_at,
        ),
    });

    let started_at = Instant::now();
    checks.push(diagnostic_check(
        "plugins",
        "Provider plugins",
        if inputs.provider_ids.is_empty() {
            "warning"
        } else {
            "pass"
        },
        format!("{} provider(s) discovered", inputs.provider_ids.len()),
        (!inputs.provider_ids.is_empty()).then(|| inputs.provider_ids.join(", ")),
        inputs
            .provider_ids
            .is_empty()
            .then(|| "Check the packaged provider plugin directory.".into()),
        started_at,
    ));

    let started_at = Instant::now();
    let owner_bridge_path = inputs.data_dir.join("provider_owner_bridge.sock");
    checks.push(diagnostic_check(
        "owner_bridge",
        "Provider owner bridge",
        if owner_bridge_path.exists() {
            "pass"
        } else {
            "warning"
        },
        if owner_bridge_path.exists() {
            "Owner bridge socket is present"
        } else {
            "Owner bridge socket is missing"
        },
        Some(owner_bridge_path.display().to_string()),
        (!owner_bridge_path.exists()).then(|| "Start or restart the managed service.".into()),
        started_at,
    ));

    let started_at = Instant::now();
    checks.push(diagnostic_check(
        "providers",
        "Provider runtime",
        if inputs.bot_running && !inputs.provider_ids.is_empty() {
            "pass"
        } else {
            "warning"
        },
        if inputs.bot_running {
            "Provider runtime baseline is available"
        } else {
            "Provider runtime cannot be queried while the bot is stopped"
        },
        None,
        (!inputs.bot_running).then(|| "Start the service before provider readiness checks.".into()),
        started_at,
    ));

    let started_at = Instant::now();
    let log_path = inputs.data_dir.join("onlineworker.log");
    checks.push(diagnostic_check(
        "recent_log",
        "Recent runtime log",
        if log_path.is_file() {
            "pass"
        } else {
            "warning"
        },
        if log_path.is_file() {
            "Runtime log is available"
        } else {
            "Runtime log is not available"
        },
        Some(log_path.display().to_string()),
        None,
        started_at,
    ));

    let overall = if checks.iter().any(|check| check.status == "fail") {
        "fail"
    } else if checks.iter().any(|check| check.status == "warning") {
        "warning"
    } else {
        "pass"
    };
    DiagnosticReport {
        generated_at: chrono::Utc::now().to_rfc3339(),
        overall: overall.into(),
        checks,
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct SupportArtifact {
    name: String,
    content: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SupportBundleExportResult {
    pub path: String,
    pub file_size: u64,
    pub generated_at: String,
}

fn is_sensitive_key(key: &str) -> bool {
    let normalized = key
        .trim()
        .trim_matches(|character: char| character == '"' || character == '\'')
        .to_ascii_lowercase();
    [
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "authorization",
        "cookie",
        "credential",
    ]
    .iter()
    .any(|candidate| normalized.contains(candidate))
}

fn redact_telegram_bot_urls(input: &str) -> String {
    let marker = "api.telegram.org/bot";
    let mut remaining = input;
    let mut redacted = String::with_capacity(input.len());
    while let Some(index) = remaining.find(marker) {
        let token_start = index + marker.len();
        redacted.push_str(&remaining[..token_start]);
        let token_end = remaining[token_start..]
            .find('/')
            .map(|offset| token_start + offset)
            .unwrap_or(remaining.len());
        redacted.push_str(REDACTED);
        remaining = &remaining[token_end..];
    }
    redacted.push_str(remaining);
    redacted
}

fn redact_tokens_with_prefix(input: &str, prefix: &str) -> String {
    let mut remaining = input;
    let mut redacted = String::with_capacity(input.len());
    while let Some(index) = remaining.find(prefix) {
        redacted.push_str(&remaining[..index]);
        let token_end = remaining[index..]
            .char_indices()
            .skip(prefix.chars().count())
            .find(|(_, character)| {
                character.is_whitespace()
                    || matches!(*character, '"' | '\'' | ',' | ';' | ')' | ']' | '}')
            })
            .map(|(offset, _)| index + offset)
            .unwrap_or(remaining.len());
        if token_end.saturating_sub(index) >= prefix.len() + 6 {
            redacted.push_str(REDACTED);
            remaining = &remaining[token_end..];
        } else {
            redacted.push_str(prefix);
            remaining = &remaining[index + prefix.len()..];
        }
    }
    redacted.push_str(remaining);
    redacted
}

fn redact_sensitive_line(line: &str) -> String {
    let trimmed = line.trim_start();
    let indentation = &line[..line.len().saturating_sub(trimmed.len())];
    for separator in [':', '='] {
        if let Some((key, _)) = trimmed.split_once(separator) {
            if is_sensitive_key(key) {
                return format!("{indentation}{}{separator} {REDACTED}", key.trim_end());
            }
        }
    }
    if trimmed.to_ascii_lowercase().starts_with("authorization ") {
        return format!("{indentation}Authorization: {REDACTED}");
    }
    line.to_string()
}

fn redact_text(raw: &str, home: Option<&str>) -> String {
    let normalized = match home.filter(|value| !value.is_empty()) {
        Some(home) => raw.replace(home, "~"),
        None => raw.to_string(),
    };
    let mut token_safe = redact_telegram_bot_urls(&normalized);
    for prefix in ["sk-", "xoxb-", "ghp_", "Bearer ", "bearer "] {
        token_safe = redact_tokens_with_prefix(&token_safe, prefix);
    }
    token_safe
        .lines()
        .map(redact_sensitive_line)
        .collect::<Vec<_>>()
        .join("\n")
}

fn environment_redaction_values(env_raw: &str) -> Vec<String> {
    let mut values = env_raw
        .lines()
        .filter_map(|line| {
            let trimmed = line.trim();
            if trimmed.is_empty() || trimmed.starts_with('#') {
                return None;
            }
            let (_, value) = trimmed.split_once('=')?;
            let value = value
                .trim()
                .trim_matches(|character| character == '"' || character == '\'');
            (value.len() >= 4).then(|| value.to_string())
        })
        .collect::<Vec<_>>();
    values.sort_by_key(|value| std::cmp::Reverse(value.len()));
    values.dedup();
    values
}

fn redact_text_with_env(raw: &str, home: Option<&str>, env_raw: &str) -> String {
    let mut redacted = redact_text(raw, home);
    for value in environment_redaction_values(env_raw) {
        redacted = redacted.replace(&value, REDACTED);
    }
    redacted
}

fn sanitize_yaml_value(value: &mut Value) {
    match value {
        Value::Mapping(mapping) => {
            for (key, nested) in mapping.iter_mut() {
                let key_text = key.as_str().unwrap_or_default();
                if is_sensitive_key(key_text) {
                    *nested = Value::String(REDACTED.to_string());
                } else {
                    sanitize_yaml_value(nested);
                }
            }
        }
        Value::Sequence(sequence) => {
            for nested in sequence {
                sanitize_yaml_value(nested);
            }
        }
        Value::String(value) => *value = CONFIG_VALUE.to_string(),
        _ => {}
    }
}

fn sanitize_config(raw: &str, home: Option<&str>) -> String {
    let Ok(mut value) = serde_yaml::from_str::<Value>(raw) else {
        return "configStatus: invalid\n".to_string();
    };
    sanitize_yaml_value(&mut value);
    let serialized =
        serde_yaml::to_string(&value).unwrap_or_else(|_| "configStatus: unavailable\n".to_string());
    redact_text(&serialized, home)
}

fn bounded_tail(raw: &str, max_bytes: usize) -> &str {
    if raw.len() <= max_bytes {
        return raw;
    }
    let mut start = raw.len() - max_bytes;
    while start < raw.len() && !raw.is_char_boundary(start) {
        start += 1;
    }
    &raw[start..]
}

fn report_as_text(report: &DiagnosticReport) -> String {
    let mut lines = vec![
        "OnlineWorker diagnostics".to_string(),
        format!("Generated: {}", report.generated_at),
        format!("Overall: {}", report.overall),
        String::new(),
    ];
    for check in &report.checks {
        lines.push(format!(
            "[{}] {} — {} ({}ms)",
            check.status, check.label, check.summary, check.duration_ms
        ));
        if let Some(remediation) = &check.remediation {
            lines.push(format!("  Remediation: {remediation}"));
        }
    }
    lines.join("\n") + "\n"
}

fn build_support_artifacts(
    report: &DiagnosticReport,
    config_raw: &str,
    log_raw: &str,
    home: Option<&str>,
    env_raw: &str,
) -> Result<Vec<SupportArtifact>, String> {
    let report_json = serde_json::to_string_pretty(report)
        .map_err(|error| format!("serialize diagnostic report: {error}"))?;
    let provider_inventory = serde_json::to_string_pretty(
        &report
            .checks
            .iter()
            .filter(|check| check.id == "plugins" || check.id.starts_with("provider:"))
            .collect::<Vec<_>>(),
    )
    .map_err(|error| format!("serialize provider inventory: {error}"))?;
    let mut artifacts = vec![
        SupportArtifact {
            name: "diagnostic-report.txt".into(),
            content: redact_text_with_env(&report_as_text(report), home, env_raw),
        },
        SupportArtifact {
            name: "diagnostic-summary.json".into(),
            content: redact_text_with_env(&(report_json + "\n"), home, env_raw),
        },
        SupportArtifact {
            name: "provider-inventory.json".into(),
            content: redact_text_with_env(&(provider_inventory + "\n"), home, env_raw),
        },
        SupportArtifact {
            name: "config-sanitized.yaml".into(),
            content: redact_text_with_env(&sanitize_config(config_raw, home), None, env_raw),
        },
        SupportArtifact {
            name: "logs/onlineworker-recent.log".into(),
            content: redact_text_with_env(
                bounded_tail(log_raw, SUPPORT_LOG_MAX_BYTES),
                home,
                env_raw,
            ),
        },
    ];
    let manifest = serde_json::json!({
        "formatVersion": 1,
        "generatedAt": report.generated_at,
        "files": artifacts
            .iter()
            .map(|artifact| serde_json::json!({
                "path": artifact.name,
                "bytes": artifact.content.len(),
            }))
            .collect::<Vec<_>>(),
    });
    artifacts.push(SupportArtifact {
        name: "manifest.json".into(),
        content: serde_json::to_string_pretty(&manifest)
            .map_err(|error| format!("serialize support manifest: {error}"))?
            + "\n",
    });
    Ok(artifacts)
}

fn normalize_export_path(path: PathBuf) -> Result<PathBuf, String> {
    if !path.is_absolute() {
        return Err("support bundle path must be absolute".into());
    }
    let mut normalized = path;
    if normalized
        .extension()
        .and_then(|value| value.to_str())
        .map(|value| !value.eq_ignore_ascii_case("zip"))
        .unwrap_or(true)
    {
        normalized.set_extension("zip");
    }
    Ok(normalized)
}

fn write_support_artifacts(root: &Path, artifacts: &[SupportArtifact]) -> Result<(), String> {
    std::fs::create_dir_all(root)
        .map_err(|error| format!("create support staging directory: {error}"))?;
    for artifact in artifacts {
        let relative = Path::new(&artifact.name);
        if relative.is_absolute()
            || relative.components().any(|component| {
                matches!(
                    component,
                    Component::ParentDir | Component::RootDir | Component::Prefix(_)
                )
            })
        {
            return Err(format!("invalid support artifact path: {}", artifact.name));
        }
        let target = root.join(relative);
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)
                .map_err(|error| format!("create support artifact directory: {error}"))?;
        }
        std::fs::write(&target, artifact.content.as_bytes())
            .map_err(|error| format!("write support artifact {}: {error}", artifact.name))?;
    }
    Ok(())
}

fn refresh_overall(report: &mut DiagnosticReport) {
    report.overall = if report.checks.iter().any(|check| check.status == "fail") {
        "fail"
    } else if report.checks.iter().any(|check| check.status == "warning") {
        "warning"
    } else {
        "pass"
    }
    .into();
}

async fn collect_runtime_diagnostics(
    app: &AppHandle,
    state: &Arc<Mutex<BotState>>,
) -> DiagnosticReport {
    let service =
        snapshot_service_status(state)
            .await
            .unwrap_or_else(|_| super::service::ServiceStatus {
                running: false,
                pid: None,
            });
    let providers = read_provider_metadata_from_disk().unwrap_or_default();
    let provider_ids = providers
        .iter()
        .filter(|provider| provider.visible)
        .map(|provider| provider.id.clone())
        .collect::<Vec<_>>();
    let mut report = collect_diagnostic_report(&DiagnosticInputs {
        app_version: app.package_info().version.to_string(),
        app_path: std::env::current_exe().unwrap_or_default(),
        data_dir: data_dir(),
        bot_running: service.running,
        bot_pid: service.pid,
        provider_ids,
    });

    let started_at = Instant::now();
    match tokio::time::timeout(Duration::from_secs(4), compute_dashboard_state(app, state)).await {
        Ok(Ok(dashboard)) => {
            for provider in dashboard.providers {
                let (status, summary) = match provider.health {
                    ServiceHealth::Healthy => ("pass", "Provider runtime is healthy"),
                    ServiceHealth::Stopped => ("warning", "Provider runtime is stopped"),
                    ServiceHealth::Degraded => ("fail", "Provider runtime is degraded"),
                    ServiceHealth::Unknown => ("warning", "Provider runtime is unknown"),
                };
                report.checks.push(diagnostic_check(
                    &format!("provider:{}", provider.id),
                    &format!("{} provider", provider.id),
                    status,
                    summary,
                    provider.detail,
                    (status != "pass").then(|| "Review provider Settings and runtime logs.".into()),
                    started_at,
                ));
            }
        }
        Ok(Err(error)) => report.checks.push(diagnostic_check(
            "runtime_status",
            "Runtime health",
            "fail",
            "Runtime health could not be collected",
            Some(error),
            Some("Review the runtime log and restart manually if needed.".into()),
            started_at,
        )),
        Err(_) => report.checks.push(diagnostic_check(
            "runtime_status",
            "Runtime health",
            "fail",
            "Runtime health check timed out",
            None,
            Some("Review the runtime log and owner bridge state.".into()),
            started_at,
        )),
    }

    let started_at = Instant::now();
    let plugin_load_result = match tokio::time::timeout(
        DIAGNOSTIC_PROBE_TIMEOUT,
        get_provider_plugin_load_failures(),
    )
    .await
    {
        Ok(result) => result,
        Err(_) => Err("Provider plugin load query timed out".into()),
    };
    report
        .checks
        .push(provider_plugin_load_check(plugin_load_result, started_at));

    let started_at = Instant::now();
    let catalog_result = match tokio::time::timeout(
        DIAGNOSTIC_PROBE_TIMEOUT,
        get_usage_source_catalog(app.clone()),
    )
    .await
    {
        Ok(result) => result,
        Err(_) => Err("Usage catalog request timed out".into()),
    };
    report
        .checks
        .push(usage_catalog_check(&catalog_result, started_at));

    if let Ok(catalog) = catalog_result {
        let associated_sources = catalog
            .into_iter()
            .filter(|source| source.provider_id.is_some())
            .collect::<Vec<_>>();
        if associated_sources.is_empty() {
            report.checks.push(diagnostic_check(
                "usage_provider_sources",
                "Provider usage sources",
                "warning",
                "No provider-associated usage sources were found",
                None,
                Some("Check provider usage plugin/source associations.".into()),
                Instant::now(),
            ));
        } else {
            let end_date = chrono::Local::now().date_naive();
            let start_date = end_date - chrono::Duration::days(6);
            let start_date = start_date.format("%Y-%m-%d").to_string();
            let end_date = end_date.format("%Y-%m-%d").to_string();
            let mut tasks = JoinSet::new();
            for source in associated_sources {
                let app = app.clone();
                let start_date = start_date.clone();
                let end_date = end_date.clone();
                tasks.spawn(async move {
                    let started_at = Instant::now();
                    let result = match tokio::time::timeout(
                        DIAGNOSTIC_PROBE_TIMEOUT,
                        get_usage_source_summary(
                            app,
                            source.plugin_id.clone(),
                            source.source_id.clone(),
                            start_date,
                            end_date,
                            Some("local".into()),
                            Some(true),
                        ),
                    )
                    .await
                    {
                        Ok(result) => result,
                        Err(_) => Err("Usage summary request timed out".into()),
                    };
                    (
                        source.order,
                        usage_summary_check(&source, result, started_at),
                    )
                });
            }

            let mut usage_checks = Vec::new();
            while let Some(result) = tasks.join_next().await {
                match result {
                    Ok(check) => usage_checks.push(check),
                    Err(error) => report.checks.push(diagnostic_check(
                        "usage_runtime",
                        "Usage runtime",
                        "fail",
                        "Usage diagnostic task failed",
                        Some(error.to_string()),
                        Some("Review the runtime log and retry diagnostics.".into()),
                        Instant::now(),
                    )),
                }
            }
            usage_checks.sort_by_key(|(order, _)| *order);
            report
                .checks
                .extend(usage_checks.into_iter().map(|(_, check)| check));
        }
    }

    refresh_overall(&mut report);
    report
}

fn support_bundle_save_script(default_name: &str) -> String {
    format!(
        "tell application \"Finder\"\nactivate\nset targetFile to choose file name with prompt \"Save OnlineWorker Support Bundle\" default name \"{default_name}\"\nreturn POSIX path of targetFile\nend tell"
    )
}

fn is_user_cancelled_osascript(stderr: &str) -> bool {
    stderr.contains("(-128)") || stderr.to_ascii_lowercase().contains("user canceled")
}

fn choose_support_bundle_path(default_name: &str) -> Result<Option<PathBuf>, String> {
    let script = support_bundle_save_script(default_name);
    let output = Command::new("osascript")
        .args(["-e", &script])
        .output()
        .map_err(|error| format!("open support bundle save dialog: {error}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if is_user_cancelled_osascript(&stderr) {
            return Ok(None);
        }
        return Err(format!("support bundle save dialog failed: {stderr}"));
    }
    let raw = String::from_utf8(output.stdout)
        .map_err(|error| format!("read support bundle save path: {error}"))?;
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    normalize_export_path(PathBuf::from(trimmed)).map(Some)
}

fn archive_support_artifacts(target: &Path, artifacts: &[SupportArtifact]) -> Result<u64, String> {
    if target.exists() {
        return Err("support bundle target already exists; choose a new file name".into());
    }
    let staging =
        std::env::temp_dir().join(format!("onlineworker-support-{}", uuid::Uuid::new_v4()));
    let result = (|| {
        write_support_artifacts(&staging, artifacts)?;
        let output = Command::new("ditto")
            .args(["-c", "-k", "--norsrc", "--noextattr", "--noqtn", "--noacl"])
            .arg(&staging)
            .arg(target)
            .output()
            .map_err(|error| format!("create support bundle zip: {error}"))?;
        if !output.status.success() {
            return Err(format!(
                "create support bundle zip failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ));
        }
        std::fs::metadata(target)
            .map(|metadata| metadata.len())
            .map_err(|error| format!("read support bundle metadata: {error}"))
    })();
    let _ = std::fs::remove_dir_all(&staging);
    result
}

#[tauri::command]
pub async fn run_support_diagnostics(
    app: AppHandle,
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<DiagnosticReport, String> {
    Ok(collect_runtime_diagnostics(&app, state.inner()).await)
}

#[tauri::command]
pub async fn export_support_bundle(
    app: AppHandle,
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<Option<SupportBundleExportResult>, String> {
    let default_name = format!(
        "OnlineWorker-support-{}.zip",
        chrono::Local::now().format("%Y%m%d-%H%M%S")
    );
    let target =
        tauri::async_runtime::spawn_blocking(move || choose_support_bundle_path(&default_name))
            .await
            .map_err(|error| format!("join support save dialog: {error}"))??;
    let Some(target) = target else {
        return Ok(None);
    };

    let report = collect_runtime_diagnostics(&app, state.inner()).await;
    let dir = data_dir();
    let config_raw = std::fs::read_to_string(dir.join("config.yaml")).unwrap_or_default();
    let env_raw = std::fs::read_to_string(dir.join(".env")).unwrap_or_default();
    let log_raw = std::fs::read_to_string(dir.join("onlineworker.log")).unwrap_or_default();
    let home = std::env::var("HOME").ok();
    let artifacts =
        build_support_artifacts(&report, &config_raw, &log_raw, home.as_deref(), &env_raw)?;
    let target_for_archive = target.clone();
    let file_size = tauri::async_runtime::spawn_blocking(move || {
        archive_support_artifacts(&target_for_archive, &artifacts)
    })
    .await
    .map_err(|error| format!("join support bundle export: {error}"))??;

    Ok(Some(SupportBundleExportResult {
        path: target.display().to_string(),
        file_size,
        generated_at: chrono::Utc::now().to_rfc3339(),
    }))
}

#[tauri::command]
pub async fn reveal_support_bundle(path: String) -> Result<(), String> {
    let target = normalize_export_path(PathBuf::from(path.trim()))?;
    if !target.is_file() {
        return Err("support bundle does not exist".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let output = Command::new("open")
            .arg("-R")
            .arg(&target)
            .output()
            .map_err(|error| format!("reveal support bundle: {error}"))?;
        if output.status.success() {
            Ok(())
        } else {
            Err(format!(
                "reveal support bundle failed: {}",
                String::from_utf8_lossy(&output.stderr)
            ))
        }
    })
    .await
    .map_err(|error| format!("join support bundle reveal: {error}"))?
}

#[cfg(test)]
mod tests {
    use super::{
        archive_support_artifacts, build_support_artifacts, collect_diagnostic_report,
        is_user_cancelled_osascript, normalize_export_path, provider_plugin_load_check,
        redact_text, redact_text_with_env, support_bundle_save_script, usage_catalog_check,
        usage_summary_check, write_support_artifacts, DiagnosticCheck, DiagnosticInputs,
        DiagnosticReport, SupportArtifact,
    };
    use crate::commands::provider_usage::{
        ProviderPluginLoadFailure, UsageSourceCatalogEntry, UsageSourceSummary,
    };
    use std::path::PathBuf;
    use std::process::Command;
    use std::time::Instant;

    fn usage_source() -> UsageSourceCatalogEntry {
        UsageSourceCatalogEntry {
            plugin_id: "ccusage".into(),
            source_id: "codex".into(),
            provider_id: Some("codex".into()),
            label: "Codex".into(),
            description: String::new(),
            order: 1,
            icon: serde_json::Value::Null,
        }
    }

    #[test]
    fn plugin_load_diagnostic_reports_failure_context() {
        let check = provider_plugin_load_check(
            Ok(vec![ProviderPluginLoadFailure {
                provider_id: "codemaker".into(),
                manifest_path: "/tmp/codemaker/plugin.yaml".into(),
                entrypoint: "codemaker.python.provider:create_provider_descriptor".into(),
                error: "ImportError: removed contract".into(),
            }]),
            Instant::now(),
        );

        assert_eq!(check.status, "fail");
        assert!(check
            .detail
            .as_deref()
            .unwrap_or_default()
            .contains("ImportError"));
        assert!(check
            .detail
            .as_deref()
            .unwrap_or_default()
            .contains("codemaker"));
    }

    #[test]
    fn usage_diagnostics_distinguish_empty_data_from_query_failure() {
        let source = usage_source();
        let catalog = Ok(vec![source.clone()]);
        let catalog_check = usage_catalog_check(&catalog, Instant::now());
        let empty_check = usage_summary_check(
            &source,
            Ok(UsageSourceSummary {
                plugin_id: "ccusage".into(),
                source_id: "codex".into(),
                days: vec![],
                updated_at_epoch: 0,
                unsupported_reason: None,
            }),
            Instant::now(),
        );
        let failed_check =
            usage_summary_check(&source, Err("source unavailable".into()), Instant::now());

        assert_eq!(catalog_check.status, "pass");
        assert_eq!(empty_check.status, "pass");
        assert_eq!(empty_check.summary, "Usage query returned 0 day(s)");
        assert_eq!(failed_check.status, "fail");
        assert_eq!(failed_check.detail.as_deref(), Some("source unavailable"));
    }

    #[test]
    fn support_bundle_save_dialog_activates_before_opening() {
        let script = support_bundle_save_script("OnlineWorker-support-test.zip");

        assert!(script.starts_with("tell application \"Finder\"\nactivate\n"));
        assert!(script.contains("choose file name"));
        assert!(script.ends_with("\nend tell"));
    }

    #[test]
    fn support_bundle_save_dialog_recognizes_localized_cancellation() {
        assert!(is_user_cancelled_osascript(
            "execution error: User canceled. (-128)"
        ));
        assert!(is_user_cancelled_osascript(
            "execution error: 用户已取消。 (-128)"
        ));
        assert!(!is_user_cancelled_osascript(
            "execution error: Not authorized. (-1743)"
        ));
    }

    #[test]
    fn support_bundle_redacts_installed_environment_values_from_logs() {
        let redacted = redact_text_with_env(
            "allowed user 123456 and group -100789\n",
            None,
            "ALLOWED_USER_ID=123456\nGROUP_CHAT_ID=-100789\nSHORT=ok\n",
        );

        assert!(!redacted.contains("123456"));
        assert!(!redacted.contains("-100789"));
        assert!(redacted.contains("[REDACTED]"));
    }

    #[test]
    fn archived_support_bundle_contains_only_generated_entries() {
        let target = std::env::temp_dir().join(format!(
            "ow-support-archive-{}-{}.zip",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        let artifacts = vec![
            SupportArtifact {
                name: "diagnostic-report.txt".into(),
                content: "diagnostic\n".into(),
            },
            SupportArtifact {
                name: "logs/onlineworker-recent.log".into(),
                content: "log\n".into(),
            },
        ];

        archive_support_artifacts(&target, &artifacts).expect("archive support artifacts");
        let output = Command::new("unzip")
            .args(["-Z1"])
            .arg(&target)
            .output()
            .expect("list support archive");
        assert!(output.status.success());
        let entries = String::from_utf8(output.stdout).expect("utf8 archive entries");
        let mut entries = entries.lines().collect::<Vec<_>>();
        entries.sort_unstable();
        std::fs::remove_file(target).expect("remove support archive fixture");
        assert_eq!(
            entries,
            vec![
                "diagnostic-report.txt",
                "logs/",
                "logs/onlineworker-recent.log"
            ]
        );
    }

    #[test]
    fn diagnostics_return_partial_results_when_runtime_inputs_are_unavailable() {
        let root = std::env::temp_dir().join(format!(
            "ow-support-diagnostics-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&root).expect("create diagnostics fixture");
        std::fs::write(root.join("config.yaml"), "providers: [invalid")
            .expect("write invalid config");
        let inputs = DiagnosticInputs {
            app_version: "1.8.0".into(),
            app_path: PathBuf::from("/Applications/OnlineWorker.app"),
            data_dir: root.clone(),
            bot_running: false,
            bot_pid: None,
            provider_ids: vec!["codex".into(), "claude".into()],
        };

        let report = collect_diagnostic_report(&inputs);

        assert_eq!(report.checks.len(), 7);
        assert_eq!(report.overall, "fail");
        assert_eq!(report.checks[0].id, "app");
        assert_eq!(report.checks[0].status, "pass");
        assert_eq!(
            report
                .checks
                .iter()
                .find(|check| check.id == "service")
                .map(|check| check.status.as_str()),
            Some("warning")
        );
        assert_eq!(
            report
                .checks
                .iter()
                .find(|check| check.id == "config")
                .map(|check| check.status.as_str()),
            Some("fail")
        );
        assert!(report
            .checks
            .iter()
            .any(|check| { check.id == "owner_bridge" && check.status == "warning" }));
        assert!(report
            .checks
            .iter()
            .any(|check| check.id == "recent_log" && check.status == "warning"));

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn redaction_removes_credentials_bot_urls_and_home_paths() {
        let raw = concat!(
            "api_key: sk-secret-value\n",
            "Authorization: Bearer bearer-secret\n",
            "https://api.telegram.org/bot123456:ABC-SECRET/getMe\n",
            "request failed with sk-live-1234567890\n",
            "/Users/alice/Projects/private\n",
        );

        let redacted = redact_text(raw, Some("/Users/alice"));

        assert!(!redacted.contains("sk-secret-value"));
        assert!(!redacted.contains("bearer-secret"));
        assert!(!redacted.contains("123456:ABC-SECRET"));
        assert!(!redacted.contains("sk-live-1234567890"));
        assert!(!redacted.contains("/Users/alice"));
        assert!(redacted.contains("[REDACTED]"));
        assert!(redacted.contains("~"));
    }

    #[test]
    fn generated_artifacts_are_bounded_and_never_include_raw_sources() {
        let report = DiagnosticReport {
            generated_at: "2026-07-11T00:00:00Z".into(),
            overall: "warning".into(),
            checks: vec![DiagnosticCheck {
                id: "bot".into(),
                label: "Bot".into(),
                status: "warning".into(),
                summary: "Bot stopped".into(),
                detail: None,
                remediation: Some("Start the service".into()),
                duration_ms: 1,
            }],
        };
        let config = concat!(
            "telegram_token: top-secret\n",
            "providers:\n",
            "  codex:\n",
            "    enabled: true\n",
            "    bin: provider --token inline-secret\n",
        );
        let log = format!("{}token=top-secret", "x".repeat(3 * 1024 * 1024));

        let artifacts = build_support_artifacts(
            &report,
            config,
            &log,
            Some("/Users/alice"),
            "ALLOWED_USER_ID=123456\n",
        )
        .expect("build generated support artifacts");
        let names = artifacts
            .iter()
            .map(|item| item.name.as_str())
            .collect::<Vec<_>>();

        assert_eq!(
            names,
            vec![
                "diagnostic-report.txt",
                "diagnostic-summary.json",
                "provider-inventory.json",
                "config-sanitized.yaml",
                "logs/onlineworker-recent.log",
                "manifest.json",
            ]
        );
        assert!(artifacts.iter().all(|item| item.name != ".env"));
        assert!(artifacts.iter().all(|item| item.name != "config.yaml"));
        assert!(artifacts
            .iter()
            .all(|item| !item.content.contains("top-secret")));
        assert!(artifacts
            .iter()
            .all(|item| !item.content.contains("inline-secret")));
        let log_artifact = artifacts
            .iter()
            .find(|item| item.name.ends_with("onlineworker-recent.log"))
            .expect("bounded log artifact");
        assert!(log_artifact.content.len() <= 2 * 1024 * 1024 + 128);
    }

    #[test]
    fn export_path_and_staging_writer_are_bounded_to_generated_files() {
        let root = std::env::temp_dir().join(format!(
            "ow-support-staging-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        let target = normalize_export_path(root.join("OnlineWorker-support"))
            .expect("normalize absolute export path");
        assert_eq!(
            target.extension().and_then(|value| value.to_str()),
            Some("zip")
        );
        assert!(normalize_export_path(PathBuf::from("relative.zip")).is_err());

        let report = DiagnosticReport {
            generated_at: "2026-07-11T00:00:00Z".into(),
            overall: "pass".into(),
            checks: vec![],
        };
        let artifacts = build_support_artifacts(&report, "providers: {}\n", "ready\n", None, "")
            .expect("build artifacts");
        let staging = root.join("staging");
        write_support_artifacts(&staging, &artifacts).expect("write generated artifacts");

        assert!(staging.join("diagnostic-report.txt").is_file());
        assert!(staging.join("logs/onlineworker-recent.log").is_file());
        assert!(!staging.join(".env").exists());
        assert!(!staging.join("config.yaml").exists());

        let _ = std::fs::remove_dir_all(root);
    }
}
