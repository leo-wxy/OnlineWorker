use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;

use super::claude::default_claude_projects_dir;
use super::config::ensure_data_dir;
use super::provider_bridge_common::{
    provider_bridge_env, provider_owner_bridge_socket_path, require_runtime_provider,
};

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

#[derive(Debug, Clone, Copy, Default, PartialEq)]
struct RawUsage {
    input_tokens: u64,
    cached_input_tokens: u64,
    output_tokens: u64,
    total_tokens: u64,
}

#[derive(Debug, Clone, Default)]
struct UsageAccumulator {
    input_tokens: u64,
    output_tokens: u64,
    cache_creation_tokens: u64,
    cache_read_tokens: u64,
    total_tokens: u64,
    total_cost_usd: f64,
    has_cost: bool,
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

fn build_summary(
    provider_id: &str,
    buckets: BTreeMap<String, UsageAccumulator>,
) -> ProviderUsageSummary {
    let mut days = buckets
        .into_iter()
        .map(|(date, bucket)| ProviderUsageDay {
            date,
            input_tokens: bucket.input_tokens,
            output_tokens: bucket.output_tokens,
            cache_creation_tokens: bucket.cache_creation_tokens,
            cache_read_tokens: bucket.cache_read_tokens,
            total_tokens: bucket.total_tokens,
            total_cost_usd: if bucket.has_cost {
                Some(bucket.total_cost_usd)
            } else {
                None
            },
        })
        .collect::<Vec<_>>();
    days.sort_by(|left, right| right.date.cmp(&left.date));
    ProviderUsageSummary {
        provider_id: provider_id.to_string(),
        days,
        updated_at_epoch: unix_time_seconds(),
        unsupported_reason: None,
    }
}

fn collect_jsonl_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };

    let mut paths = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort();

    for path in paths {
        if path.is_dir() {
            collect_jsonl_files(&path, out);
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            out.push(path);
        }
    }
}

fn default_codex_sessions_dir() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let path = PathBuf::from(home).join(".codex/sessions");
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

fn date_from_timestamp(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.len() < 10 {
        return None;
    }
    let candidate = &trimmed[..10];
    if candidate
        .chars()
        .enumerate()
        .all(|(index, ch)| match index {
            4 | 7 => ch == '-',
            _ => ch.is_ascii_digit(),
        })
    {
        Some(candidate.to_string())
    } else {
        None
    }
}

fn is_date_in_range(date: &str, start_date: &str, end_date: &str) -> bool {
    date >= start_date && date <= end_date
}

fn ensure_u64(value: Option<&Value>) -> u64 {
    value.and_then(Value::as_u64).unwrap_or(0)
}

fn ensure_f64(value: Option<&Value>) -> Option<f64> {
    value.and_then(Value::as_f64)
}

fn normalize_codex_raw_usage(value: Option<&Value>) -> Option<RawUsage> {
    let record = value?.as_object()?;
    let input_tokens = ensure_u64(record.get("input_tokens"));
    let cached_input_tokens = ensure_u64(
        record
            .get("cached_input_tokens")
            .or_else(|| record.get("cache_read_input_tokens")),
    );
    let output_tokens = ensure_u64(record.get("output_tokens"));
    let total_tokens = ensure_u64(record.get("total_tokens"));

    Some(RawUsage {
        input_tokens,
        cached_input_tokens,
        output_tokens,
        total_tokens: if total_tokens > 0 {
            total_tokens
        } else {
            input_tokens + output_tokens
        },
    })
}

fn subtract_codex_usage(current: RawUsage, previous: Option<RawUsage>) -> RawUsage {
    RawUsage {
        input_tokens: current
            .input_tokens
            .saturating_sub(previous.map(|value| value.input_tokens).unwrap_or(0)),
        cached_input_tokens: current
            .cached_input_tokens
            .saturating_sub(previous.map(|value| value.cached_input_tokens).unwrap_or(0)),
        output_tokens: current
            .output_tokens
            .saturating_sub(previous.map(|value| value.output_tokens).unwrap_or(0)),
        total_tokens: current
            .total_tokens
            .saturating_sub(previous.map(|value| value.total_tokens).unwrap_or(0)),
    }
}

fn is_zero_usage(raw: RawUsage) -> bool {
    raw.input_tokens == 0
        && raw.cached_input_tokens == 0
        && raw.output_tokens == 0
        && raw.total_tokens == 0
}

fn summarize_codex_usage_from_paths(
    paths: &[PathBuf],
    start_date: &str,
    end_date: &str,
) -> Result<Vec<ProviderUsageDay>, String> {
    let mut files = Vec::new();
    for path in paths {
        collect_jsonl_files(path, &mut files);
    }
    files.sort();

    let mut buckets = BTreeMap::<String, UsageAccumulator>::new();

    for file_path in files {
        let file = fs::File::open(&file_path).map_err(|error| {
            format!(
                "Cannot read codex usage file {}: {error}",
                file_path.display()
            )
        })?;
        let reader = BufReader::new(file);
        let mut previous_totals: Option<RawUsage> = None;
        let mut previous_seen_total_usage: Option<RawUsage> = None;

        for line in reader.lines() {
            let line = match line {
                Ok(value) => value,
                Err(_) => continue,
            };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let Ok(parsed) = serde_json::from_str::<Value>(trimmed) else {
                continue;
            };
            if parsed.get("type").and_then(Value::as_str) != Some("event_msg") {
                continue;
            }
            let Some(payload) = parsed.get("payload").and_then(Value::as_object) else {
                continue;
            };
            if payload.get("type").and_then(Value::as_str) != Some("token_count") {
                continue;
            }
            let Some(date) = parsed
                .get("timestamp")
                .and_then(Value::as_str)
                .and_then(date_from_timestamp)
            else {
                continue;
            };
            if !is_date_in_range(&date, start_date, end_date) {
                continue;
            }
            let info = payload.get("info");
            let last_usage =
                normalize_codex_raw_usage(info.and_then(|value| value.get("last_token_usage")));
            let total_usage =
                normalize_codex_raw_usage(info.and_then(|value| value.get("total_token_usage")));

            if let Some(total) = total_usage {
                if previous_seen_total_usage == Some(total) {
                    continue;
                }
                previous_seen_total_usage = Some(total);
            }

            let raw = if let Some(last) = last_usage {
                last
            } else if let Some(total) = total_usage {
                subtract_codex_usage(total, previous_totals)
            } else {
                continue;
            };

            if let Some(total) = total_usage {
                previous_totals = Some(total);
            }

            if is_zero_usage(raw) {
                continue;
            }

            let bucket = buckets.entry(date).or_default();
            bucket.input_tokens += raw.input_tokens;
            bucket.output_tokens += raw.output_tokens;
            bucket.cache_read_tokens += raw.cached_input_tokens;
            bucket.total_tokens += if raw.total_tokens > 0 {
                raw.total_tokens
            } else {
                raw.input_tokens + raw.output_tokens
            };
        }
    }

    Ok(build_summary("codex", buckets).days)
}

fn create_unique_hash(parsed: &Value) -> Option<String> {
    let message_id = parsed.get("message")?.get("id")?.as_str()?;
    let request_id = parsed.get("requestId")?.as_str()?;
    Some(format!("{message_id}:{request_id}"))
}

fn summarize_claude_usage_from_paths(
    paths: &[PathBuf],
    start_date: &str,
    end_date: &str,
) -> Result<Vec<ProviderUsageDay>, String> {
    let mut files = Vec::new();
    for path in paths {
        collect_jsonl_files(path, &mut files);
    }
    files.sort();

    let mut buckets = BTreeMap::<String, UsageAccumulator>::new();
    let mut processed_hashes = HashSet::<String>::new();

    for file_path in files {
        let file = fs::File::open(&file_path).map_err(|error| {
            format!(
                "Cannot read claude usage file {}: {error}",
                file_path.display()
            )
        })?;
        let reader = BufReader::new(file);

        for line in reader.lines() {
            let line = match line {
                Ok(value) => value,
                Err(_) => continue,
            };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let Ok(parsed) = serde_json::from_str::<Value>(trimmed) else {
                continue;
            };
            let Some(date) = parsed
                .get("timestamp")
                .and_then(Value::as_str)
                .and_then(date_from_timestamp)
            else {
                continue;
            };
            if !is_date_in_range(&date, start_date, end_date) {
                continue;
            }
            let Some(usage) = parsed
                .get("message")
                .and_then(|value| value.get("usage"))
                .and_then(Value::as_object)
            else {
                continue;
            };

            if let Some(unique_hash) = create_unique_hash(&parsed) {
                if processed_hashes.contains(&unique_hash) {
                    continue;
                }
                processed_hashes.insert(unique_hash);
            }

            let input_tokens = ensure_u64(usage.get("input_tokens"));
            let output_tokens = ensure_u64(usage.get("output_tokens"));
            let cache_creation_tokens = ensure_u64(usage.get("cache_creation_input_tokens"));
            let cache_read_tokens = ensure_u64(usage.get("cache_read_input_tokens"));
            let total_tokens =
                input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens;

            if total_tokens == 0 {
                continue;
            }

            let bucket = buckets.entry(date).or_default();
            bucket.input_tokens += input_tokens;
            bucket.output_tokens += output_tokens;
            bucket.cache_creation_tokens += cache_creation_tokens;
            bucket.cache_read_tokens += cache_read_tokens;
            bucket.total_tokens += total_tokens;
            if let Some(cost) = ensure_f64(parsed.get("costUSD")) {
                bucket.total_cost_usd += cost;
                bucket.has_cost = true;
            }
        }
    }

    Ok(build_summary("claude", buckets).days)
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
    let sidecar = app
        .shell()
        .sidecar("onlineworker-bot")
        .map_err(|error| format!("Sidecar not found: {}", error))?;

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

    let mut sidecar = sidecar.args(args);
    for (key, value) in provider_bridge_env(&data_dir) {
        sidecar = sidecar.env(&key, value);
    }

    let output = sidecar
        .output()
        .await
        .map_err(|error| format!("provider usage bridge failed: {}", error))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        let detail = if !stderr.is_empty() {
            stderr
        } else if !stdout.is_empty() {
            stdout
        } else {
            format!("exit status {:?}", output.status.code())
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

    let days = match provider.runtime_id.as_str() {
        "codex" => {
            let Some(path) = default_codex_sessions_dir() else {
                return Ok(summary_with_reason(
                    &provider.id,
                    "Codex sessions directory not found",
                ));
            };
            summarize_codex_usage_from_paths(&[path], &start_date, &end_date)?
        }
        "claude" => {
            let Some(path) = default_claude_projects_dir() else {
                return Ok(summary_with_reason(
                    &provider.id,
                    "Claude projects directory not found",
                ));
            };
            summarize_claude_usage_from_paths(&[path], &start_date, &end_date)?
        }
        other => {
            if provider.capabilities.usage {
                let data_dir = ensure_data_dir()?;
                match provider_usage_summary_via_owner_bridge(
                    &data_dir,
                    &provider.id,
                    &start_date,
                    &end_date,
                ) {
                    Ok(summary) => return Ok(summary),
                    Err(_) => {
                        return run_provider_usage_bridge(
                            &app,
                            &provider.id,
                            &start_date,
                            &end_date,
                        )
                        .await;
                    }
                }
            } else {
                return Ok(summary_with_reason(
                    &provider.id,
                    format!("Provider runtime '{other}' has no usage implementation"),
                ));
            }
        }
    };

    Ok(ProviderUsageSummary {
        provider_id: provider.id,
        days,
        updated_at_epoch: unix_time_seconds(),
        unsupported_reason: None,
    })
}

#[cfg(test)]
mod tests {
    use super::{summarize_claude_usage_from_paths, summarize_codex_usage_from_paths};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_dir(name: &str) -> PathBuf {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("onlineworker-provider-usage-{name}-{stamp}"));
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    #[test]
    fn codex_usage_summary_aggregates_last_and_total_usage_by_day() {
        let root = unique_temp_dir("codex");
        let day_dir = root.join("2026").join("05").join("11");
        fs::create_dir_all(&day_dir).expect("create day dir");
        let file = day_dir.join("rollout.jsonl");
        fs::write(
            &file,
            concat!(
                "{\"type\":\"session_meta\",\"payload\":{\"id\":\"t1\"}}\n",
                "{\"timestamp\":\"2026-05-11T01:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150},\"total_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150}}}}\n",
                "{\"timestamp\":\"2026-05-11T03:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":160,\"cached_input_tokens\":20,\"output_tokens\":70,\"total_tokens\":230}}}}\n"
            ),
        )
        .expect("write file");

        let days = summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
            .expect("summary");
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, "2026-05-11");
        assert_eq!(days[0].input_tokens, 160);
        assert_eq!(days[0].cache_read_tokens, 20);
        assert_eq!(days[0].output_tokens, 70);
        assert_eq!(days[0].total_tokens, 230);
        assert_eq!(days[0].cache_creation_tokens, 0);
        assert_eq!(days[0].total_cost_usd, None);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn codex_usage_summary_reads_long_running_session_from_creation_day_directory() {
        let root = unique_temp_dir("codex-long-running");
        let creation_day_dir = root.join("2026").join("05").join("12");
        fs::create_dir_all(&creation_day_dir).expect("create creation day dir");
        let file = creation_day_dir.join("rollout.jsonl");
        fs::write(
            &file,
            concat!(
                "{\"timestamp\":\"2026-05-12T07:14:08.000Z\",\"type\":\"session_meta\",\"payload\":{\"id\":\"t1\"}}\n",
                "{\"timestamp\":\"2026-05-20T11:44:52.682Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":{\"input_tokens\":189292,\"cached_input_tokens\":167808,\"output_tokens\":37,\"total_tokens\":189329},\"total_token_usage\":{\"input_tokens\":114981193,\"cached_input_tokens\":106463488,\"output_tokens\":484228,\"total_tokens\":115465421}}}}\n"
            ),
        )
        .expect("write file");

        let days = summarize_codex_usage_from_paths(&[root.clone()], "2026-05-14", "2026-05-20")
            .expect("summary");

        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, "2026-05-20");
        assert_eq!(days[0].input_tokens, 189292);
        assert_eq!(days[0].cache_read_tokens, 167808);
        assert_eq!(days[0].output_tokens, 37);
        assert_eq!(days[0].total_tokens, 189329);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn claude_usage_summary_deduplicates_message_and_request_pairs() {
        let root = unique_temp_dir("claude");
        let project_dir = root.join("project-a");
        fs::create_dir_all(&project_dir).expect("create project dir");
        let file = project_dir.join("session.jsonl");
        fs::write(
            &file,
            concat!(
                "{\"timestamp\":\"2026-05-11T10:00:00.000Z\",\"requestId\":\"req-1\",\"message\":{\"id\":\"msg-1\",\"usage\":{\"input_tokens\":100,\"output_tokens\":50,\"cache_creation_input_tokens\":20,\"cache_read_input_tokens\":10}},\"costUSD\":0.12}\n",
                "{\"timestamp\":\"2026-05-11T10:00:01.000Z\",\"requestId\":\"req-1\",\"message\":{\"id\":\"msg-1\",\"usage\":{\"input_tokens\":100,\"output_tokens\":50,\"cache_creation_input_tokens\":20,\"cache_read_input_tokens\":10}},\"costUSD\":0.12}\n",
                "{\"timestamp\":\"2026-05-11T11:00:00.000Z\",\"requestId\":\"req-2\",\"message\":{\"id\":\"msg-2\",\"usage\":{\"input_tokens\":40,\"output_tokens\":10}},\"costUSD\":0.08}\n"
            ),
        )
        .expect("write file");

        let days = summarize_claude_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
            .expect("summary");
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, "2026-05-11");
        assert_eq!(days[0].input_tokens, 140);
        assert_eq!(days[0].output_tokens, 60);
        assert_eq!(days[0].cache_creation_tokens, 20);
        assert_eq!(days[0].cache_read_tokens, 10);
        assert_eq!(days[0].total_tokens, 230);
        assert_eq!(days[0].total_cost_usd, Some(0.2));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn usage_summary_filters_out_dates_outside_requested_window() {
        let root = unique_temp_dir("codex-range");
        let day_dir = root.join("2026").join("05").join("11");
        fs::create_dir_all(&day_dir).expect("create day dir");
        let file = day_dir.join("rollout.jsonl");
        fs::write(
            &file,
            concat!(
                "{\"timestamp\":\"2026-05-10T01:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":{\"input_tokens\":12,\"output_tokens\":3,\"total_tokens\":15}}}}\n",
                "{\"timestamp\":\"2026-05-11T01:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"last_token_usage\":{\"input_tokens\":20,\"output_tokens\":5,\"total_tokens\":25}}}}\n"
            ),
        )
        .expect("write file");

        let days = summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
            .expect("summary");
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].date, "2026-05-11");
        assert_eq!(days[0].total_tokens, 25);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn codex_usage_summary_does_not_double_count_duplicate_token_count_events() {
        let root = unique_temp_dir("codex-dup");
        let day_dir = root.join("2026").join("05").join("11");
        fs::create_dir_all(&day_dir).expect("create day dir");
        let file = day_dir.join("rollout.jsonl");
        fs::write(
            &file,
            concat!(
                "{\"timestamp\":\"2026-05-11T01:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150},\"last_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150}}}}\n",
                "{\"timestamp\":\"2026-05-11T01:00:01.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150},\"last_token_usage\":{\"input_tokens\":100,\"cached_input_tokens\":10,\"output_tokens\":50,\"total_tokens\":150}}}}\n",
                "{\"timestamp\":\"2026-05-11T01:00:10.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":160,\"cached_input_tokens\":20,\"output_tokens\":70,\"total_tokens\":230},\"last_token_usage\":{\"input_tokens\":60,\"cached_input_tokens\":10,\"output_tokens\":20,\"total_tokens\":80}}}}\n",
                "{\"timestamp\":\"2026-05-11T01:00:11.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"token_count\",\"info\":{\"total_token_usage\":{\"input_tokens\":160,\"cached_input_tokens\":20,\"output_tokens\":70,\"total_tokens\":230},\"last_token_usage\":{\"input_tokens\":60,\"cached_input_tokens\":10,\"output_tokens\":20,\"total_tokens\":80}}}}\n"
            ),
        )
        .expect("write file");

        let days = summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
            .expect("summary");
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].input_tokens, 160);
        assert_eq!(days[0].cache_read_tokens, 20);
        assert_eq!(days[0].output_tokens, 70);
        assert_eq!(days[0].total_tokens, 230);

        let _ = fs::remove_dir_all(root);
    }
}
