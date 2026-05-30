use rusqlite::{Connection, OpenFlags};
use serde_json::Value;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Mutex as StdMutex, OnceLock};
use std::time::{Duration, SystemTime};

use super::super::claude::{
    build_claude_history_index, default_claude_history_path, default_claude_projects_dir,
    load_claude_project_sessions_from_dir, read_claude_project_session_preview,
    should_skip_claude_session_from_workspace_list,
};
use super::super::session_state::{load_local_thread_overlays, LocalThreadOverlay};
use super::RecentActivitySummary;

pub(super) const RECENT_ACTIVITY_CACHE_TTL: Duration = Duration::from_secs(15);

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
    codex_db: Option<PathBuf>,
}

#[derive(Clone, Debug)]
struct RecentActivityCacheEntry {
    cached_at: SystemTime,
    summary: Option<RecentActivitySummary>,
}

#[derive(Default)]
pub(super) struct ClaudeActivityIndex {
    sessions: HashMap<String, super::super::claude::ClaudeStoredSession>,
    history: HashMap<String, super::super::claude::ClaudeHistoryInfo>,
}

fn normalize_activity_timestamp(raw: i64) -> i64 {
    if raw > 1_000_000_000_000 {
        raw
    } else {
        raw.saturating_mul(1000)
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
        workspace_path: workspace.path.clone(),
        tool: workspace.tool.clone(),
        session_id: latest_session_id?,
        preview: latest_preview,
        updated_at: latest_updated_at,
        active_thread_count,
    })
}

pub(super) fn read_claude_workspace_activity(
    workspace: &WorkspaceSnapshot,
    overlays: &HashMap<String, LocalThreadOverlay>,
    index: &ClaudeActivityIndex,
) -> Option<WorkspaceActivityCandidate> {
    let mut session_ids = index.sessions.keys().cloned().collect::<Vec<_>>();
    for session_id in index.history.keys() {
        if !index.sessions.contains_key(session_id) {
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

        let stored = index.sessions.get(&session_id);
        let history = index.history.get(&session_id);
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
            workspace_path: workspace.path.clone(),
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

pub(super) fn build_claude_activity_index(
    projects_dir: Option<&Path>,
    history_path: Option<&Path>,
) -> ClaudeActivityIndex {
    let default_projects_dir = default_claude_projects_dir();
    let projects_dir = projects_dir.or(default_projects_dir.as_deref());
    let sessions = projects_dir
        .map(load_claude_project_sessions_from_dir)
        .unwrap_or_default()
        .into_iter()
        .map(|session| (session.id.clone(), session))
        .collect::<HashMap<_, _>>();

    ClaudeActivityIndex {
        sessions,
        history: build_claude_history_index(history_path),
    }
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

pub(super) fn read_recent_activity_summary(data_dir: &Path) -> Option<RecentActivitySummary> {
    let codex_db = codex_db_path();
    read_recent_activity_summary_cached_with_now(data_dir, codex_db.as_deref(), SystemTime::now())
}

fn recent_activity_cache(
) -> &'static StdMutex<HashMap<RecentActivityCacheKey, RecentActivityCacheEntry>> {
    static CACHE: OnceLock<StdMutex<HashMap<RecentActivityCacheKey, RecentActivityCacheEntry>>> =
        OnceLock::new();
    CACHE.get_or_init(|| StdMutex::new(HashMap::new()))
}

pub(super) fn read_recent_activity_summary_cached_with_now(
    data_dir: &Path,
    codex_db: Option<&Path>,
    now: SystemTime,
) -> Option<RecentActivitySummary> {
    let cache_key = RecentActivityCacheKey {
        data_dir: data_dir.to_path_buf(),
        codex_db: codex_db.map(Path::to_path_buf),
    };
    if let Ok(cache) = recent_activity_cache().lock() {
        if let Some(entry) = cache.get(&cache_key) {
            let fresh = now
                .duration_since(entry.cached_at)
                .map(|age| age < RECENT_ACTIVITY_CACHE_TTL)
                .unwrap_or(false);
            if fresh {
                return entry.summary.clone();
            }
        }
    }

    let summary = read_recent_activity_summary_from_paths(data_dir, codex_db);
    if let Ok(mut cache) = recent_activity_cache().lock() {
        cache.insert(
            cache_key,
            RecentActivityCacheEntry {
                cached_at: now,
                summary: summary.clone(),
            },
        );
    }
    summary
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
    let claude_index = if workspaces.values().any(|workspace| {
        workspace
            .get("tool")
            .and_then(Value::as_str)
            .map(|tool| tool == "claude")
            .unwrap_or(false)
    }) {
        Some(build_claude_activity_index(
            None,
            default_claude_history_path().as_deref(),
        ))
    } else {
        None
    };

    let latest = workspaces
        .iter()
        .filter_map(|(workspace_id, workspace)| parse_workspace_snapshot(workspace_id, workspace))
        .filter_map(|workspace| match workspace.tool.as_str() {
            "codex" => read_codex_workspace_activity(&workspace, codex_db, &codex_overlays),
            "claude" => claude_index.as_ref().and_then(|index| {
                read_claude_workspace_activity(&workspace, &claude_overlays, index)
            }),
            _ => None,
        })
        .max_by_key(|candidate| candidate.updated_at);

    latest
        .map(build_recent_activity_summary_from_candidate)
        .or_else(|| read_recent_activity_summary_from_state(&parsed, workspaces))
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
