use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::AppHandle;

use super::config::ensure_data_dir;
use super::provider_bridge_common::{
    provider_bridge_env, provider_owner_bridge_socket_path, run_provider_bridge_sidecar,
};

const USAGE_BRIDGE_TIMEOUT: Duration = Duration::from_secs(40);

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct UsageSourceCatalogEntry {
    pub plugin_id: String,
    pub source_id: String,
    #[serde(default)]
    pub provider_id: Option<String>,
    pub label: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub order: i64,
    #[serde(default)]
    pub icon: Value,
}

#[cfg(test)]
mod tests {
    use super::{owner_usage_catalog, ProviderPluginLoadFailure, UsageSourceCatalogEntry};

    #[test]
    fn usage_source_catalog_preserves_provider_association() {
        let entry: UsageSourceCatalogEntry = serde_json::from_value(serde_json::json!({
            "pluginId": "ccusage",
            "sourceId": "codex",
            "providerId": "codex",
            "label": "Codex"
        }))
        .expect("catalog entry should deserialize");

        assert_eq!(entry.provider_id.as_deref(), Some("codex"));
        assert_eq!(
            serde_json::to_value(entry).expect("catalog entry should serialize")["providerId"],
            "codex"
        );
    }

    #[test]
    fn provider_plugin_load_failure_preserves_diagnostic_context() {
        let failure: ProviderPluginLoadFailure = serde_json::from_value(serde_json::json!({
            "providerId": "overlay-tool",
            "manifestPath": "/tmp/overlay-tool/plugin.yaml",
            "entrypoint": "overlay_tool.python.provider:create_provider_descriptor",
            "error": "ImportError: removed contract"
        }))
        .expect("plugin failure should deserialize");

        assert_eq!(failure.provider_id, "overlay-tool");
        assert!(failure.error.contains("ImportError"));
    }

    #[test]
    fn empty_owner_usage_catalog_uses_fallback() {
        assert_eq!(
            owner_usage_catalog(&serde_json::json!({"ok": true, "sources": []})),
            None
        );
        assert_eq!(
            owner_usage_catalog(
                &serde_json::json!({"ok": true, "sources": [{"sourceId": "codex"}]})
            ),
            Some(serde_json::json!([{"sourceId": "codex"}]))
        );
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct UsageSourceDay {
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
pub struct UsageSourceSummary {
    pub plugin_id: String,
    pub source_id: String,
    pub days: Vec<UsageSourceDay>,
    pub updated_at_epoch: u64,
    pub unsupported_reason: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderPluginLoadFailure {
    #[serde(default)]
    pub provider_id: String,
    pub manifest_path: String,
    #[serde(default)]
    pub entrypoint: String,
    pub error: String,
}

fn owner_bridge_request_sync(
    data_dir: &Path,
    payload: Value,
    timeout: Duration,
) -> Result<Value, String> {
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }
    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|error| format!("connect provider owner bridge failed: {error}"))?;
    socket
        .set_read_timeout(Some(timeout))
        .map_err(|e| e.to_string())?;
    socket
        .set_write_timeout(Some(timeout))
        .map_err(|e| e.to_string())?;
    socket
        .write_all(format!("{payload}\n").as_bytes())
        .map_err(|e| e.to_string())?;
    socket
        .shutdown(Shutdown::Write)
        .map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(socket)
        .read_line(&mut line)
        .map_err(|e| e.to_string())?;
    let response: Value = serde_json::from_str(line.trim()).map_err(|e| e.to_string())?;
    if response.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(response
            .get("error")
            .and_then(Value::as_str)
            .unwrap_or("usage bridge failed")
            .to_string());
    }
    Ok(response)
}

async fn owner_bridge_request(data_dir: PathBuf, payload: Value) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        owner_bridge_request_sync(&data_dir, payload, USAGE_BRIDGE_TIMEOUT)
    })
    .await
    .map_err(|error| format!("join provider owner bridge request: {error}"))?
}

async fn run_usage_sidecar(
    app: &AppHandle,
    operation: &str,
    extra_args: Vec<String>,
) -> Result<Value, String> {
    let data_dir = ensure_data_dir()?;
    let mut args = vec![
        "--data-dir".to_string(),
        data_dir.to_string_lossy().to_string(),
        "--provider-session-bridge".to_string(),
        "--provider-id".to_string(),
        "usage".to_string(),
        "--provider-session-op".to_string(),
        operation.to_string(),
    ];
    args.extend(extra_args);
    let output = run_provider_bridge_sidecar(
        app,
        args,
        provider_bridge_env(&data_dir),
        Some(USAGE_BRIDGE_TIMEOUT),
        "usage bridge",
    )
    .await?;
    if !output.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("usage bridge returned invalid JSON: {e}"))
}

fn owner_usage_catalog(response: &Value) -> Option<Value> {
    let sources = response.get("sources")?.as_array()?;
    (!sources.is_empty()).then(|| Value::Array(sources.clone()))
}

#[tauri::command]
pub async fn get_usage_source_catalog(
    app: AppHandle,
) -> Result<Vec<UsageSourceCatalogEntry>, String> {
    let data_dir = ensure_data_dir()?;
    let payload = match owner_bridge_request(
        data_dir,
        serde_json::json!({"type": "usage_source_catalog"}),
    )
    .await
    {
        Ok(response) => match owner_usage_catalog(&response) {
            Some(sources) => sources,
            None => run_usage_sidecar(&app, "usage-catalog", vec![]).await?,
        },
        Err(_) => run_usage_sidecar(&app, "usage-catalog", vec![]).await?,
    };
    serde_json::from_value(payload).map_err(|e| format!("parse usage source catalog failed: {e}"))
}

#[tauri::command]
pub async fn get_usage_source_summary(
    app: AppHandle,
    plugin_id: String,
    source_id: String,
    start_date: String,
    end_date: String,
    timezone: Option<String>,
    force_refresh: Option<bool>,
) -> Result<UsageSourceSummary, String> {
    let timezone = timezone.unwrap_or_else(|| "local".to_string());
    let force_refresh = force_refresh.unwrap_or(false);
    let data_dir = ensure_data_dir()?;
    let request = serde_json::json!({
        "type": "usage_source_summary", "plugin_id": plugin_id, "source_id": source_id,
        "start_date": start_date, "end_date": end_date, "timezone": timezone,
        "force_refresh": force_refresh,
    });
    let payload = match owner_bridge_request(data_dir, request).await {
        Ok(response) => response.get("summary").cloned().unwrap_or(Value::Null),
        Err(_) => {
            run_usage_sidecar(
                &app,
                "usage-source",
                vec![
                    "--usage-plugin-id".to_string(),
                    plugin_id,
                    "--usage-source-id".to_string(),
                    source_id,
                    "--provider-start-date".to_string(),
                    start_date,
                    "--provider-end-date".to_string(),
                    end_date,
                    "--usage-timezone".to_string(),
                    timezone,
                    if force_refresh {
                        "--usage-force-refresh".to_string()
                    } else {
                        String::new()
                    },
                ]
                .into_iter()
                .filter(|value| !value.is_empty())
                .collect(),
            )
            .await?
        }
    };
    serde_json::from_value(payload).map_err(|e| format!("parse usage source summary failed: {e}"))
}

pub(crate) async fn get_provider_plugin_load_failures(
) -> Result<Vec<ProviderPluginLoadFailure>, String> {
    let data_dir = ensure_data_dir()?;
    let response = owner_bridge_request(
        data_dir,
        serde_json::json!({"type": "provider_plugin_load_failures"}),
    )
    .await?;
    serde_json::from_value(
        response
            .get("failures")
            .cloned()
            .unwrap_or(Value::Array(vec![])),
    )
    .map_err(|error| format!("parse provider plugin load failures: {error}"))
}
