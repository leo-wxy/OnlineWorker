use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use super::config::ensure_data_dir;
use super::provider_bridge_common::{provider_owner_bridge_socket_path, require_runtime_provider};

const PROVIDER_USAGE_REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(6);

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
        .set_read_timeout(Some(PROVIDER_USAGE_REQUEST_TIMEOUT))
        .map_err(|e| format!("set provider owner bridge read timeout failed: {e}"))?;
    socket
        .set_write_timeout(Some(PROVIDER_USAGE_REQUEST_TIMEOUT))
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

#[tauri::command]
pub async fn get_provider_usage_summary(
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
    provider_usage_summary_via_owner_bridge(&data_dir, &provider.id, &start_date, &end_date)
}

#[cfg(test)]
mod tests {
    use super::{provider_usage_summary_via_owner_bridge, summary_with_reason};
    use crate::commands::provider_bridge_common::provider_owner_bridge_socket_path;
    use std::fs;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::thread;

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

    #[test]
    fn provider_usage_summary_uses_owner_bridge_socket() {
        let temp_dir = std::env::temp_dir().join(format!("ow-usage-pob-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = provider_owner_bridge_socket_path(&temp_dir);
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
            let request_json: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse request");
            assert_eq!(
                request_json,
                serde_json::json!({
                    "type": "usage_summary",
                    "provider_id": "codex",
                    "start_date": "2026-05-10",
                    "end_date": "2026-05-11",
                })
            );
            writeln!(
                stream,
                "{}",
                serde_json::json!({
                    "ok": true,
                    "summary": {
                        "providerId": "codex",
                        "updatedAtEpoch": 1770000000u64,
                        "days": [
                            {
                                "date": "2026-05-11",
                                "inputTokens": 10u64,
                                "outputTokens": 5u64,
                                "cacheCreationTokens": 2u64,
                                "cacheReadTokens": 3u64,
                                "totalTokens": 20u64,
                                "totalCostUsd": 0.25
                            }
                        ]
                    }
                })
            )
            .expect("write owner bridge response");
        });

        let summary =
            provider_usage_summary_via_owner_bridge(&temp_dir, "codex", "2026-05-10", "2026-05-11")
                .expect("usage summary");

        server.join().expect("owner bridge thread");
        assert_eq!(summary.provider_id, "codex");
        assert_eq!(summary.updated_at_epoch, 1_770_000_000);
        assert_eq!(summary.days.len(), 1);
        assert_eq!(summary.days[0].date, "2026-05-11");
        assert_eq!(summary.days[0].input_tokens, 10);
        assert_eq!(summary.days[0].output_tokens, 5);
        assert_eq!(summary.days[0].cache_creation_tokens, 2);
        assert_eq!(summary.days[0].cache_read_tokens, 3);
        assert_eq!(summary.days[0].total_tokens, 20);
        assert_eq!(summary.days[0].total_cost_usd, Some(0.25));
        let _ = fs::remove_dir_all(temp_dir);
    }
}
