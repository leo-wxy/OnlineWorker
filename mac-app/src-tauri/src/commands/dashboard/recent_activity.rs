use serde_json::Value;
use std::collections::{BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Mutex as StdMutex, OnceLock};
use std::time::{Duration, SystemTime};
use tauri::AppHandle;

use super::super::provider_sessions::load_provider_sessions_with_overlays;
use super::RecentActivitySummary;

pub(super) const RECENT_ACTIVITY_CACHE_TTL: Duration = Duration::from_secs(15);

fn legacy_activity_db_path() -> Option<PathBuf> {
    None
}

#[derive(Clone, Debug)]
pub(super) struct WorkspaceSnapshot {
    pub(super) id: String,
    pub(super) name: Option<String>,
    pub(super) tool: String,
    pub(super) path: String,
}

#[derive(Clone, Debug)]
pub(super) struct WorkspaceActivityCandidate {
    pub(super) workspace_id: String,
    pub(super) workspace_name: Option<String>,
    pub(super) workspace_path: String,
    pub(super) tool: String,
    pub(super) session_id: String,
    pub(super) preview: Option<String>,
    pub(super) updated_at: i64,
    pub(super) active_thread_count: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
struct RecentActivityCacheKey {
    data_dir: PathBuf,
    legacy_activity_db: Option<PathBuf>,
}

#[derive(Clone, Debug)]
struct RecentActivityCacheEntry {
    cached_at: SystemTime,
    summary: Option<RecentActivitySummary>,
}

#[derive(Clone, Debug)]
pub(super) struct ProviderSessionRow {
    pub(super) id: String,
    pub(super) workspace: String,
    pub(super) title: String,
    pub(super) preview: Option<String>,
    pub(super) archived: bool,
    pub(super) provider_active: bool,
    pub(super) updated_at: i64,
    pub(super) created_at: i64,
}

fn normalize_activity_timestamp(raw: i64) -> i64 {
    if raw > 1_000_000_000_000 {
        raw
    } else {
        raw.saturating_mul(1000)
    }
}

fn trimmed_opt(raw: &str) -> Option<String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn workspace_name_from_path(path: &str) -> Option<String> {
    Path::new(path)
        .file_name()
        .and_then(|value| value.to_str())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn provider_workspace_id(tool: &str, workspace_path: &str) -> String {
    format!("{tool}:{workspace_path}")
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

fn parse_provider_session_row(row: &Value) -> Option<ProviderSessionRow> {
    let id = row.get("id").and_then(Value::as_str)?.trim().to_string();
    if id.is_empty() {
        return None;
    }

    let workspace = row
        .get("workspace")
        .or_else(|| row.get("directory"))
        .or_else(|| row.get("cwd"))
        .and_then(Value::as_str)?
        .trim()
        .to_string();
    if workspace.is_empty() {
        return None;
    }

    let preview = row
        .get("preview")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned);
    let title = row
        .get("title")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
        .or_else(|| preview.clone())
        .unwrap_or_else(|| id.clone());
    let updated_at = row
        .get("updatedAt")
        .or_else(|| row.get("updated_at"))
        .or_else(|| row.get("updated_at_epoch"))
        .and_then(Value::as_i64)
        .unwrap_or(0);
    let created_at = row
        .get("createdAt")
        .or_else(|| row.get("created_at"))
        .and_then(Value::as_i64)
        .unwrap_or(0);

    Some(ProviderSessionRow {
        id,
        workspace,
        title,
        preview,
        archived: row
            .get("archived")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        provider_active: row
            .get("providerActive")
            .or_else(|| row.get("provider_active"))
            .and_then(Value::as_bool)
            .unwrap_or(false),
        updated_at,
        created_at,
    })
}

pub(super) fn read_provider_workspace_activity(
    workspace: &WorkspaceSnapshot,
    rows: &[ProviderSessionRow],
) -> Option<WorkspaceActivityCandidate> {
    let mut active_thread_count = 0_u32;
    let mut latest: Option<WorkspaceActivityCandidate> = None;

    for row in rows.iter().filter(|row| row.workspace == workspace.path) {
        if row.archived || !row.provider_active {
            continue;
        }

        active_thread_count = active_thread_count.saturating_add(1);
        let updated_at = normalize_activity_timestamp(row.updated_at.max(row.created_at));
        let candidate = WorkspaceActivityCandidate {
            workspace_id: workspace.id.clone(),
            workspace_name: workspace.name.clone(),
            workspace_path: workspace.path.clone(),
            tool: workspace.tool.clone(),
            session_id: row.id.clone(),
            preview: row.preview.clone().or_else(|| trimmed_opt(&row.title)),
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

fn collect_workspace_snapshots(
    workspaces: &serde_json::Map<String, Value>,
    provider_sessions_by_tool: &HashMap<String, Vec<ProviderSessionRow>>,
) -> Vec<WorkspaceSnapshot> {
    let mut snapshots = Vec::new();
    let mut seen = BTreeSet::new();

    for (workspace_id, workspace) in workspaces {
        let Some(snapshot) = parse_workspace_snapshot(workspace_id, workspace) else {
            continue;
        };
        seen.insert((snapshot.tool.clone(), snapshot.path.clone()));
        snapshots.push(snapshot);
    }

    for (tool, rows) in provider_sessions_by_tool {
        for row in rows {
            let workspace_path = row.workspace.trim();
            if workspace_path.is_empty() {
                continue;
            }
            let seen_key = (tool.clone(), workspace_path.to_string());
            if !seen.insert(seen_key) {
                continue;
            }
            snapshots.push(WorkspaceSnapshot {
                id: provider_workspace_id(tool, workspace_path),
                name: workspace_name_from_path(workspace_path),
                tool: tool.clone(),
                path: workspace_path.to_string(),
            });
        }
    }

    snapshots
}

async fn load_provider_session_rows_for_state(
    app: &AppHandle,
    data_dir: &Path,
) -> HashMap<String, Vec<ProviderSessionRow>> {
    let path = data_dir.join("onlineworker_state.json");
    let raw = match std::fs::read_to_string(&path) {
        Ok(value) => value,
        Err(_) => return HashMap::new(),
    };
    let parsed: Value = match serde_json::from_str(&raw) {
        Ok(value) => value,
        Err(_) => return HashMap::new(),
    };
    let Some(workspaces) = parsed.get("workspaces").and_then(Value::as_object) else {
        return HashMap::new();
    };

    let tools = workspaces
        .values()
        .filter_map(|workspace| workspace.get("tool").and_then(Value::as_str))
        .filter(|tool| !tool.trim().is_empty())
        .map(ToOwned::to_owned)
        .collect::<BTreeSet<_>>();

    let mut by_tool = HashMap::new();
    for tool in tools {
        let Ok(value) = load_provider_sessions_with_overlays(app, &tool, false).await else {
            continue;
        };
        let rows = value
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .filter_map(parse_provider_session_row)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        by_tool.insert(tool, rows);
    }
    by_tool
}

fn build_recent_activity_summary_from_candidate(
    candidate: WorkspaceActivityCandidate,
) -> RecentActivitySummary {
    RecentActivitySummary {
        active_workspace_id: Some(candidate.workspace_id),
        active_workspace_name: candidate.workspace_name,
        active_workspace_path: Some(candidate.workspace_path),
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
        active_workspace_path: selected_workspace
            .get("path")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned),
        active_tool: active_tool.clone(),
        active_session_id,
        active_session_tool: active_tool,
        highlighted_thread_preview,
        active_thread_count,
    })
}

pub(super) async fn read_recent_activity_summary(
    app: &AppHandle,
    data_dir: &Path,
) -> Option<RecentActivitySummary> {
    let legacy_activity_db = legacy_activity_db_path();
    let now = SystemTime::now();
    let cache_key = RecentActivityCacheKey {
        data_dir: data_dir.to_path_buf(),
        legacy_activity_db: legacy_activity_db.clone(),
    };
    if let Some(summary) = cached_recent_activity(&cache_key, now) {
        return summary;
    }

    let provider_sessions_by_tool = load_provider_session_rows_for_state(app, data_dir).await;
    let summary = read_recent_activity_summary_cached_with_now(
        data_dir,
        legacy_activity_db.as_deref(),
        &provider_sessions_by_tool,
        now,
    );
    cache_recent_activity(cache_key, now, summary.clone());
    summary
}

fn recent_activity_cache(
) -> &'static StdMutex<HashMap<RecentActivityCacheKey, RecentActivityCacheEntry>> {
    static CACHE: OnceLock<StdMutex<HashMap<RecentActivityCacheKey, RecentActivityCacheEntry>>> =
        OnceLock::new();
    CACHE.get_or_init(|| StdMutex::new(HashMap::new()))
}

fn cached_recent_activity(
    cache_key: &RecentActivityCacheKey,
    now: SystemTime,
) -> Option<Option<RecentActivitySummary>> {
    if let Ok(cache) = recent_activity_cache().lock() {
        if let Some(entry) = cache.get(&cache_key) {
            let fresh = now
                .duration_since(entry.cached_at)
                .map(|age| age < RECENT_ACTIVITY_CACHE_TTL)
                .unwrap_or(false);
            if fresh {
                return Some(entry.summary.clone());
            }
        }
    }
    None
}

fn cache_recent_activity(
    cache_key: RecentActivityCacheKey,
    now: SystemTime,
    summary: Option<RecentActivitySummary>,
) {
    if let Ok(mut cache) = recent_activity_cache().lock() {
        cache.insert(
            cache_key,
            RecentActivityCacheEntry {
                cached_at: now,
                summary: summary.clone(),
            },
        );
    }
}

pub(super) fn read_recent_activity_summary_cached_with_now(
    data_dir: &Path,
    legacy_activity_db: Option<&Path>,
    provider_sessions_by_tool: &HashMap<String, Vec<ProviderSessionRow>>,
    now: SystemTime,
) -> Option<RecentActivitySummary> {
    let cache_key = RecentActivityCacheKey {
        data_dir: data_dir.to_path_buf(),
        legacy_activity_db: legacy_activity_db.map(Path::to_path_buf),
    };
    if let Some(summary) = cached_recent_activity(&cache_key, now) {
        return summary;
    }

    let summary = read_recent_activity_summary_from_paths_with_provider_sessions(
        data_dir,
        legacy_activity_db,
        provider_sessions_by_tool,
    );
    cache_recent_activity(cache_key, now, summary.clone());
    summary
}

pub(super) fn read_recent_activity_summary_from_paths_with_provider_sessions(
    data_dir: &Path,
    _legacy_activity_db: Option<&Path>,
    provider_sessions_by_tool: &HashMap<String, Vec<ProviderSessionRow>>,
) -> Option<RecentActivitySummary> {
    let path = data_dir.join("onlineworker_state.json");
    let raw = std::fs::read_to_string(&path).ok();
    let parsed = raw
        .as_deref()
        .and_then(|value| serde_json::from_str::<Value>(value).ok());
    let empty_workspaces = serde_json::Map::new();
    let workspaces = parsed
        .as_ref()
        .and_then(|value| value.get("workspaces"))
        .and_then(Value::as_object)
        .unwrap_or(&empty_workspaces);

    let has_provider_rows = provider_sessions_by_tool
        .values()
        .any(|rows| !rows.is_empty());

    let workspace_snapshots = collect_workspace_snapshots(workspaces, provider_sessions_by_tool);

    let latest = workspace_snapshots
        .iter()
        .filter_map(|workspace| {
            provider_sessions_by_tool
                .get(&workspace.tool)
                .and_then(|rows| read_provider_workspace_activity(workspace, rows))
        })
        .max_by_key(|candidate| candidate.updated_at);

    if let Some(candidate) = latest {
        return Some(build_recent_activity_summary_from_candidate(candidate));
    }

    if has_provider_rows {
        return None;
    }

    parsed
        .as_ref()
        .and_then(|value| read_recent_activity_summary_from_state(value, workspaces))
}

pub(super) fn extract_thread_summary(
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
