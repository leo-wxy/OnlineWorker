use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::AppHandle;

use super::config::ensure_data_dir;
use super::provider_bridge_common::{
    provider_bridge_env, provider_owner_bridge_socket_path, require_runtime_provider,
    run_provider_bridge_sidecar,
};

const PROVIDER_USAGE_BRIDGE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(6);

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderUsageDay {
    pub date: String,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_creation_tokens: u64,
    pub cache_read_tokens: u64,
    pub total_tokens: u64,
    pub total_cost_usd: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderUsageSummary {
    pub provider_id: String,
    pub days: Vec<ProviderUsageDay>,
    pub updated_at_epoch: u64,
    pub unsupported_reason: Option<String>,
}

fn unix_time_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0)
}

fn summary_with_reason(provider_id: &str, reason: impl Into<String>) -> ProviderUsageSummary {
    ProviderUsageSummary {
        provider_id: provider_id.to_string(),
        days: Vec::new(),
        updated_at_epoch: unix_time_seconds(),
        unsupported_reason: Some(reason.into()),
    }
}

fn provider_usage_summary_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    start_date: &str,
    end_date: &str,
) -> Result<ProviderUsageSummary, String> {
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
        .set_read_timeout(Some(PROVIDER_USAGE_BRIDGE_TIMEOUT))
        .map_err(|e| format!("set provider owner bridge read timeout failed: {e}"))?;
    socket
        .set_write_timeout(Some(PROVIDER_USAGE_BRIDGE_TIMEOUT))
        .map_err(|e| format!("set provider owner bridge write timeout failed: {e}"))?;
    let payload = serde_json::json!({
        "type": "usage_summary",
        "provider_id": provider_id,
        "start_date": start_date,
        "end_date": end_date,
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

    let response = serde_json::from_str::<Value>(response_line.trim())
        .map_err(|e| format!("parse provider owner bridge response failed: {e}"))?;
    if response.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("provider owner bridge request failed")
            .to_string());
    }

    serde_json::from_value(
        response
            .get("summary")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({ "providerId": provider_id, "days": [] })),
    )
    .map_err(|e| format!("parse provider owner bridge summary failed: {e}"))
}

async fn run_provider_usage_bridge(
    app: &AppHandle,
    provider_id: &str,
    start_date: &str,
    end_date: &str,
) -> Result<ProviderUsageSummary, String> {
    let data_dir = ensure_data_dir()?;
    let args = vec![
        "--data-dir".to_string(),
        data_dir.to_string_lossy().to_string(),
        "--provider-session-bridge".to_string(),
        "--provider-id".to_string(),
        provider_id.to_string(),
        "--provider-session-op".to_string(),
        "usage".to_string(),
        "--provider-start-date".to_string(),
        start_date.to_string(),
        "--provider-end-date".to_string(),
        end_date.to_string(),
    ];

    let output = run_provider_bridge_sidecar(
        app,
        args,
        provider_bridge_env(&data_dir),
        Some(PROVIDER_USAGE_BRIDGE_TIMEOUT),
        "provider usage bridge",
    )
    .await?;
    if !output.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let detail = if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            format!("exit status {:?}, signal {:?}", output.code, output.signal)
        };
        return Err(detail);
    }

    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("provider usage bridge returned invalid JSON: {}", error))
}

#[tauri::command]
pub async fn get_provider_usage_summary(
    app: AppHandle,
    provider_id: String,
    start_date: String,
    end_date: String,
) -> Result<ProviderUsageSummary, String> {
    let provider = match require_runtime_provider(&provider_id) {
        Ok(value) => value,
        Err(error) => {
            return Ok(summary_with_reason(provider_id.trim(), error));
        }
    };

    if !provider.capabilities.usage {
        return Ok(summary_with_reason(
            &provider.id,
            format!(
                "Provider runtime '{}' has no usage implementation",
                provider.runtime_id
            ),
        ));
    }

    let data_dir = ensure_data_dir()?;
    match provider_usage_summary_via_owner_bridge(&data_dir, &provider.id, &start_date, &end_date)
    {
        Ok(summary) => Ok(summary),
        Err(_) => run_provider_usage_bridge(&app, &provider.id, &start_date, &end_date).await,
    }
}

#[cfg(test)]
mod tests {
    use super::summary_with_reason;

    #[test]
    fn summary_with_reason_marks_summary_as_unsupported() {
        let summary = summary_with_reason("secondary", "owner bridge unavailable");
        assert_eq!(summary.provider_id, "secondary");
        assert!(summary.days.is_empty());
        assert_eq!(
            summary.unsupported_reason.as_deref(),
            Some("owner bridge unavailable")
        );
    }
}
