use serde::Serialize;
use serde_json::Value;
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::claude::default_claude_projects_dir;
use super::config::read_provider_metadata_from_disk;
use super::config_provider::ProviderMetadata;

#[derive(Debug, Clone, Serialize, PartialEq)]
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

#[derive(Debug, Clone, Serialize, PartialEq)]
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

fn provider_not_enabled_message(provider_id: &str) -> String {
    format!("Provider '{}' is not enabled", provider_id.trim())
}

fn summary_with_reason(provider_id: &str, reason: impl Into<String>) -> ProviderUsageSummary {
    ProviderUsageSummary {
        provider_id: provider_id.to_string(),
        days: Vec::new(),
        updated_at_epoch: unix_time_seconds(),
        unsupported_reason: Some(reason.into()),
    }
}

fn build_summary(provider_id: &str, buckets: BTreeMap<String, UsageAccumulator>) -> ProviderUsageSummary {
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

fn require_runtime_provider(provider_id: &str) -> Result<ProviderMetadata, String> {
    let normalized = provider_id.trim();
    if normalized.is_empty() {
        return Err(provider_not_enabled_message("unknown"));
    }

    read_provider_metadata_from_disk()?
        .into_iter()
        .find(|provider| provider.id == normalized)
        .ok_or_else(|| provider_not_enabled_message(normalized))
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

fn collect_direct_jsonl_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };

    let mut paths = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort();

    for path in paths {
        if path.is_file() && path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
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
    if candidate.chars().enumerate().all(|(index, ch)| match index {
        4 | 7 => ch == '-',
        _ => ch.is_ascii_digit(),
    }) {
        Some(candidate.to_string())
    } else {
        None
    }
}

fn is_date_in_range(date: &str, start_date: &str, end_date: &str) -> bool {
    date >= start_date && date <= end_date
}

fn parse_date_key(date: &str) -> Option<(i32, u32, u32)> {
    let mut parts = date.split('-');
    let year = parts.next()?.parse::<i32>().ok()?;
    let month = parts.next()?.parse::<u32>().ok()?;
    let day = parts.next()?.parse::<u32>().ok()?;
    Some((year, month, day))
}

fn days_in_month(year: i32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 => {
            if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 {
                29
            } else {
                28
            }
        }
        _ => 30,
    }
}

fn next_date(date: &str) -> Option<String> {
    let (mut year, mut month, mut day) = parse_date_key(date)?;
    day += 1;
    if day > days_in_month(year, month) {
        day = 1;
        month += 1;
        if month > 12 {
            month = 1;
            year += 1;
        }
    }
    Some(format!("{year:04}-{month:02}-{day:02}"))
}

fn collect_codex_jsonl_files_for_range(root: &Path, start_date: &str, end_date: &str) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let mut current = start_date.to_string();

    loop {
        let Some((year, month, day)) = parse_date_key(&current) else {
            break;
        };
        let dir = root
            .join(format!("{year:04}"))
            .join(format!("{month:02}"))
            .join(format!("{day:02}"));
        if dir.exists() {
            collect_direct_jsonl_files(&dir, &mut files);
        }
        if current == end_date {
            break;
        }
        let Some(next) = next_date(&current) else {
            break;
        };
        current = next;
    }

    files.sort();
    files
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
        files.extend(collect_codex_jsonl_files_for_range(path, start_date, end_date));
    }
    files.sort();

    let mut buckets = BTreeMap::<String, UsageAccumulator>::new();

    for file_path in files {
        let file = fs::File::open(&file_path)
            .map_err(|error| format!("Cannot read codex usage file {}: {error}", file_path.display()))?;
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
            let last_usage = normalize_codex_raw_usage(info.and_then(|value| value.get("last_token_usage")));
            let total_usage = normalize_codex_raw_usage(info.and_then(|value| value.get("total_token_usage")));

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
        let file = fs::File::open(&file_path)
            .map_err(|error| format!("Cannot read claude usage file {}: {error}", file_path.display()))?;
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
            let Some(usage) = parsed.get("message").and_then(|value| value.get("usage")).and_then(Value::as_object) else {
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

#[tauri::command]
pub fn get_provider_usage_summary(
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
            return Ok(summary_with_reason(
                &provider.id,
                format!("Provider runtime '{other}' has no usage implementation"),
            ));
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

        let days =
            summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
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

        let days =
            summarize_claude_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
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

        let days =
            summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
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

        let days =
            summarize_codex_usage_from_paths(&[root.clone()], "2026-05-11", "2026-05-11")
                .expect("summary");
        assert_eq!(days.len(), 1);
        assert_eq!(days[0].input_tokens, 160);
        assert_eq!(days[0].cache_read_tokens, 20);
        assert_eq!(days[0].output_tokens, 70);
        assert_eq!(days[0].total_tokens, 230);

        let _ = fs::remove_dir_all(root);
    }
}
