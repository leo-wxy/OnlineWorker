use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::fs;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, OnceLock,
};
use std::thread::sleep;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::ipc::Channel;

use super::config::ensure_data_dir;
use super::session_state::load_local_thread_overlays;

// ─── Types ────────────────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct CodexThread {
    pub id: String,
    pub title: String,
    pub cwd: String,
    pub archived: bool,
    pub rollout_path: String,
    pub model_provider: Option<String>,
    pub source: Option<String>,
    pub is_smoke: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CodexTurn {
    pub role: String, // "user" | "assistant"
    pub content: String,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
pub struct CodexThreadCursor {
    pub offset: u64,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CodexThreadReadResult {
    pub turns: Vec<CodexTurn>,
    pub cursor: CodexThreadCursor,
    pub replace: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CodexThreadStreamEvent {
    pub kind: String,
    pub semantic_kind: Option<String>,
    pub turn: Option<CodexTurn>,
    pub cursor: CodexThreadCursor,
    pub reason: Option<String>,
    pub error: Option<String>,
    pub session_tab_visible_at: Option<u64>,
}

static CODEX_THREAD_STREAM_GENERATION: OnceLock<Arc<AtomicU64>> = OnceLock::new();

// ─── Helpers ──────────────────────────────────────────────────────────────────

fn unix_time_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}

fn codex_db_path() -> Option<std::path::PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let p = std::path::PathBuf::from(&home).join(".codex/state_5.sqlite");
    if p.exists() {
        Some(p)
    } else {
        None
    }
}

fn codex_sessions_dir() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let p = PathBuf::from(&home).join(".codex/sessions");
    if p.exists() {
        Some(p)
    } else {
        None
    }
}

fn codex_thread_stream_generation() -> Arc<AtomicU64> {
    CODEX_THREAD_STREAM_GENERATION
        .get_or_init(|| Arc::new(AtomicU64::new(0)))
        .clone()
}

fn is_codex_subagent_source(source: &str) -> bool {
    if source.is_empty() || source == "vscode" {
        return false;
    }

    let Ok(parsed) = serde_json::from_str::<serde_json::Value>(source) else {
        return false;
    };

    parsed
        .as_object()
        .map(|obj| obj.contains_key("subagent"))
        .unwrap_or(false)
}

fn is_codex_subagent_source_value(source: &Value) -> bool {
    match source {
        Value::String(text) => is_codex_subagent_source(text),
        Value::Object(obj) => obj.contains_key("subagent"),
        _ => false,
    }
}

fn collect_codex_session_files(dir: &Path, out: &mut Vec<PathBuf>) {
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
            collect_codex_session_files(&path, out);
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            out.push(path);
        }
    }
}

fn extract_codex_thread_id_from_filename(path: &Path) -> Option<String> {
    let stem = path.file_stem()?.to_str()?;
    let parts = stem.split('-').collect::<Vec<_>>();
    if parts.len() < 6 {
        return None;
    }
    Some(parts[parts.len().saturating_sub(5)..].join("-"))
}

fn read_codex_first_user_preview(rollout_path: &Path) -> Option<String> {
    let file = fs::File::open(rollout_path).ok()?;
    let reader = BufReader::new(file);

    for line in reader.lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(parsed) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };

        match parsed
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or_default()
        {
            "response_item" => {
                let payload = parsed.get("payload").and_then(Value::as_object)?;
                if payload.get("role").and_then(Value::as_str) != Some("user") {
                    continue;
                }
                let Some(content) = payload.get("content").and_then(Value::as_array) else {
                    continue;
                };
                for item in content {
                    if item.get("type").and_then(Value::as_str) != Some("input_text") {
                        continue;
                    }
                    let text = item
                        .get("text")
                        .and_then(Value::as_str)
                        .map(str::trim)
                        .unwrap_or_default();
                    if text.is_empty() || text.starts_with('#') || text.starts_with('<') {
                        continue;
                    }
                    return Some(text.to_string());
                }
            }
            "event_msg" => {
                let payload = parsed.get("payload").and_then(Value::as_object)?;
                if payload.get("type").and_then(Value::as_str) != Some("user_message") {
                    continue;
                }
                let text = payload
                    .get("message")
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .unwrap_or_default();
                if text.is_empty() || text.starts_with('#') || text.starts_with('<') {
                    continue;
                }
                return Some(text.to_string());
            }
            _ => {}
        }
    }

    None
}

#[derive(Debug)]
struct CodexThreadCandidate {
    thread: CodexThread,
    created_at: i64,
    updated_at: i64,
}

fn file_mtime_ms(path: &Path) -> i64 {
    fs::metadata(path)
        .ok()
        .and_then(|meta| meta.modified().ok())
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or(0)
}

fn is_codex_smoke_preview(text: &str) -> bool {
    text.trim_start()
        .starts_with("This is an OnlineWorker fixed-session")
}

fn codex_jsonl_candidate_from_path(
    path: &Path,
    overlays: &std::collections::HashMap<String, super::session_state::LocalThreadOverlay>,
) -> Option<CodexThreadCandidate> {
    let file = fs::File::open(path).ok()?;
    let mut reader = BufReader::new(file);
    let mut first_line = String::new();
    if reader.read_line(&mut first_line).ok()? == 0 {
        return None;
    }

    let meta = serde_json::from_str::<Value>(first_line.trim()).ok()?;
    if meta.get("type").and_then(Value::as_str) != Some("session_meta") {
        return None;
    }

    let payload = meta.get("payload").and_then(Value::as_object)?;
    if is_codex_subagent_source_value(payload.get("source").unwrap_or(&Value::Null)) {
        return None;
    }

    let thread_id = payload
        .get("id")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
        .or_else(|| {
            meta.get("id")
                .and_then(Value::as_str)
                .map(ToOwned::to_owned)
        })
        .or_else(|| extract_codex_thread_id_from_filename(path))?;

    let cwd = payload
        .get("cwd")
        .and_then(Value::as_str)
        .or_else(|| meta.get("cwd").and_then(Value::as_str))
        .unwrap_or_default()
        .to_string();
    if cwd.is_empty() {
        return None;
    }

    let mtime_ms = file_mtime_ms(path);
    let model_provider = payload
        .get("model_provider")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned);
    let source = payload
        .get("source")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned);
    let mut thread = CodexThread {
        id: thread_id.clone(),
        title: read_codex_first_user_preview(path).unwrap_or_default(),
        cwd,
        archived: false,
        rollout_path: path.to_string_lossy().to_string(),
        model_provider,
        source,
        is_smoke: false,
    };
    thread.is_smoke = is_codex_smoke_preview(&thread.title);

    if let Some(overlay) = overlays.get(&thread_id) {
        if !overlay.workspace_path.is_empty() {
            thread.cwd = overlay.workspace_path.clone();
        }
        if thread.title.trim().is_empty() {
            if let Some(preview) = &overlay.preview {
                thread.title = preview.clone();
            }
        }
        thread.archived = overlay.archived;
    }
    Some(CodexThreadCandidate {
        thread,
        created_at: mtime_ms,
        updated_at: mtime_ms,
    })
}

fn list_codex_threads_from_paths(
    db_path: &std::path::Path,
    state_path: Option<&std::path::Path>,
    sessions_dir: Option<&std::path::Path>,
) -> Result<Vec<CodexThread>, String> {
    let conn = Connection::open_with_flags(db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .map_err(|e| e.to_string())?;
    let overlays = state_path
        .map(|path| load_local_thread_overlays(path, "codex"))
        .unwrap_or_default();

    let mut stmt = conn
        .prepare(
            "SELECT id, title, cwd, archived, rollout_path, source, model_provider, created_at, updated_at
             FROM threads
             ORDER BY updated_at DESC
             LIMIT 600",
        )
        .map_err(|e| e.to_string())?;

    let rows = stmt
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, i64>(3)? != 0,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?.unwrap_or_default(),
                row.get::<_, Option<String>>(6)?,
                row.get::<_, i64>(7)?,
                row.get::<_, i64>(8)?,
            ))
        })
        .map_err(|e| e.to_string())?;

    let mut candidates = Vec::new();
    let mut seen_ids = std::collections::HashSet::new();
    for r in rows {
        let (id, title, cwd, archived, rollout_path, source, model_provider, created_at, updated_at) =
            r.map_err(|e| e.to_string())?;
        if is_codex_subagent_source(&source) {
            continue;
        }
        let mut thread = CodexThread {
            id: id.clone(),
            title,
            cwd,
            archived,
            rollout_path,
            model_provider: model_provider
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty()),
            source: Some(source.clone()).filter(|value| !value.trim().is_empty()),
            is_smoke: false,
        };
        thread.is_smoke = is_codex_smoke_preview(&thread.title);
        if let Some(overlay) = overlays.get(&thread.id) {
            if !overlay.workspace_path.is_empty() {
                thread.cwd = overlay.workspace_path.clone();
            }
            if thread.title.trim().is_empty() {
                if let Some(preview) = &overlay.preview {
                    thread.title = preview.clone();
                }
            }
            thread.archived = thread.archived || overlay.archived;
        }
        seen_ids.insert(id);
        candidates.push(CodexThreadCandidate {
            thread,
            created_at,
            updated_at,
        });
    }

    if let Some(dir) = sessions_dir {
        let mut session_files = Vec::new();
        collect_codex_session_files(dir, &mut session_files);
        for path in session_files {
            let Some(candidate) = codex_jsonl_candidate_from_path(&path, &overlays) else {
                continue;
            };
            if seen_ids.contains(&candidate.thread.id) {
                continue;
            }
            seen_ids.insert(candidate.thread.id.clone());
            candidates.push(candidate);
        }
    }

    candidates.sort_by(|left, right| {
        right
            .created_at
            .cmp(&left.created_at)
            .then_with(|| right.updated_at.cmp(&left.updated_at))
            .then_with(|| right.thread.id.cmp(&left.thread.id))
    });

    Ok(candidates
        .into_iter()
        .map(|candidate| candidate.thread)
        .take(200)
        .collect())
}

#[cfg(test)]
fn build_codex_rpc_request(id: u64, method: &str, params: Value) -> Value {
    json!({
        "id": id,
        "method": method,
        "params": params,
    })
}

#[cfg(test)]
fn codex_rpc_error_text(response: &Value) -> Option<String> {
    let error = response.get("error")?;
    if let Some(message) = error.get("message").and_then(Value::as_str) {
        return Some(message.to_string());
    }
    Some(error.to_string())
}

#[cfg(test)]
fn is_codex_unmaterialized_error(text: &str) -> bool {
    let lowered = text.to_lowercase();
    lowered.contains("not materialized yet") || lowered.contains("no rollout found for thread id")
}

fn codex_owner_bridge_socket_path(data_dir: &Path) -> PathBuf {
    data_dir.join("codex_owner_bridge.sock")
}

fn send_codex_thread_message_via_owner_bridge(
    data_dir: &Path,
    thread_id: &str,
    text: &str,
    cwd: Option<&str>,
) -> Result<bool, String> {
    let socket_path = codex_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Ok(false);
    }

    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect codex owner bridge failed: {e}"))?;

    let mut payload = json!({
        "type": "send_message",
        "thread_id": thread_id,
        "text": text,
    });
    if let Some(cwd) = cwd.map(str::trim).filter(|cwd| !cwd.is_empty()) {
        payload["cwd"] = Value::String(cwd.to_string());
    }

    let raw_request = format!("{}\n", payload);
    socket
        .write_all(raw_request.as_bytes())
        .map_err(|e| format!("write codex owner bridge request failed: {e}"))?;
    socket
        .shutdown(Shutdown::Write)
        .map_err(|e| format!("shutdown codex owner bridge write failed: {e}"))?;

    let mut response_line = String::new();
    let mut reader = BufReader::new(socket);
    reader
        .read_line(&mut response_line)
        .map_err(|e| format!("read codex owner bridge response failed: {e}"))?;

    let response = serde_json::from_str::<Value>(response_line.trim())
        .map_err(|e| format!("parse codex owner bridge response failed: {e}"))?;
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        return Ok(true);
    }

    Err(response
        .get("error")
        .and_then(Value::as_str)
        .unwrap_or("codex owner bridge request failed")
        .to_string())
}

fn send_codex_thread_message_via_owner_bridge_with_retry(
    data_dir: &Path,
    thread_id: &str,
    text: &str,
    cwd: Option<&str>,
    timeout: Duration,
) -> Result<(), String> {
    let started_at = Instant::now();
    let poll_interval = Duration::from_millis(100);
    let socket_path = codex_owner_bridge_socket_path(data_dir);
    let mut last_error = format!("codex owner bridge not ready: {}", socket_path.display());

    loop {
        match send_codex_thread_message_via_owner_bridge(data_dir, thread_id, text, cwd) {
            Ok(true) => return Ok(()),
            Ok(false) => {
                last_error = format!("codex owner bridge not ready: {}", socket_path.display());
            }
            Err(error) => {
                last_error = error;
            }
        }

        if started_at.elapsed() >= timeout {
            return Err(last_error);
        }

        sleep(poll_interval);
    }
}

fn send_codex_thread_message_blocking(
    thread_id: &str,
    text: &str,
    cwd: Option<&str>,
) -> Result<(), String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("message is empty".to_string());
    }

    let data_dir = ensure_data_dir()?;
    send_codex_thread_message_via_owner_bridge_with_retry(
        &data_dir,
        thread_id,
        trimmed,
        cwd,
        Duration::from_secs(8),
    )
}

// ─── Commands ─────────────────────────────────────────────────────────────────

#[tauri::command]
pub fn list_codex_threads() -> Result<Vec<CodexThread>, String> {
    let db_path = codex_db_path().ok_or("codex database not found (~/.codex/state_5.sqlite)")?;
    let state_path = ensure_data_dir()?.join("onlineworker_state.json");
    let sessions_dir = codex_sessions_dir();
    list_codex_threads_from_paths(&db_path, Some(&state_path), sessions_dir.as_deref())
}

#[derive(Debug, Deserialize)]
struct RolloutLine {
    #[serde(rename = "type")]
    line_type: String,
    payload: serde_json::Value,
}

fn normalize_codex_turn_text(text: &str) -> Option<String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn is_codex_control_user_message(role: &str, content: &str) -> bool {
    if role != "user" {
        return false;
    }

    let trimmed = content.trim_start();
    trimmed.starts_with("<turn_aborted>")
        || trimmed.starts_with("# AGENTS.md instructions for ")
        || trimmed.starts_with("<environment_context>")
        || trimmed.starts_with("<skill>")
}

fn push_codex_turn(turns: &mut Vec<CodexTurn>, role: &str, content: String) {
    let Some(content) = normalize_codex_turn_text(&content) else {
        return;
    };
    if is_codex_control_user_message(role, &content) {
        return;
    }

    if turns
        .last()
        .map(|last| last.role == role && last.content == content)
        .unwrap_or(false)
    {
        return;
    }

    turns.push(CodexTurn {
        role: role.to_string(),
        content,
    });
}

fn extract_codex_text_value(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.to_string()),
        Value::Object(obj) => obj
            .get("value")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned)
            .or_else(|| {
                obj.get("text")
                    .and_then(Value::as_str)
                    .map(ToOwned::to_owned)
            }),
        _ => None,
    }
}

fn extract_codex_response_item_text(payload: &Value) -> Option<(String, String)> {
    if payload.get("type").and_then(Value::as_str) != Some("message") {
        return None;
    }

    let role = payload.get("role").and_then(Value::as_str)?;
    if role != "user" && role != "assistant" {
        return None;
    }

    let content = payload.get("content").and_then(Value::as_array)?;
    let text_parts = content
        .iter()
        .filter_map(|item| {
            let item_type = item.get("type").and_then(Value::as_str).unwrap_or_default();
            if !item_type.ends_with("text") {
                return None;
            }
            extract_codex_text_value(item.get("text").unwrap_or(&Value::Null))
        })
        .filter_map(|text| normalize_codex_turn_text(&text))
        .collect::<Vec<_>>();

    if text_parts.is_empty() {
        return None;
    }

    Some((role.to_string(), text_parts.join("\n")))
}

fn build_codex_stream_turn_event(
    kind: &str,
    semantic_kind: Option<&str>,
    role: &str,
    content: String,
    cursor: CodexThreadCursor,
) -> Option<CodexThreadStreamEvent> {
    let normalized = normalize_codex_turn_text(&content)?;
    if is_codex_control_user_message(role, &normalized) {
        return None;
    }

    Some(CodexThreadStreamEvent {
        kind: kind.to_string(),
        semantic_kind: semantic_kind.map(ToOwned::to_owned),
        turn: Some(CodexTurn {
            role: role.to_string(),
            content: normalized,
        }),
        cursor,
        reason: None,
        error: None,
        session_tab_visible_at: Some(unix_time_millis()),
    })
}

fn build_codex_stream_error_event(
    cursor: CodexThreadCursor,
    error: impl Into<String>,
) -> CodexThreadStreamEvent {
    CodexThreadStreamEvent {
        kind: "error".to_string(),
        semantic_kind: None,
        turn: None,
        cursor,
        reason: None,
        error: Some(error.into()),
        session_tab_visible_at: Some(unix_time_millis()),
    }
}

fn build_codex_stream_marker_event(
    kind: &str,
    semantic_kind: Option<&str>,
    cursor: CodexThreadCursor,
) -> CodexThreadStreamEvent {
    CodexThreadStreamEvent {
        kind: kind.to_string(),
        semantic_kind: semantic_kind.map(ToOwned::to_owned),
        turn: None,
        cursor,
        reason: None,
        error: None,
        session_tab_visible_at: Some(unix_time_millis()),
    }
}

fn parse_codex_stream_events(line: &str, cursor: CodexThreadCursor) -> Vec<CodexThreadStreamEvent> {
    let line = line.trim();
    if line.is_empty() {
        return Vec::new();
    }

    let parsed: RolloutLine = match serde_json::from_str(line) {
        Ok(value) => value,
        Err(_) => return Vec::new(),
    };

    match parsed.line_type.as_str() {
        "response_item" => {
            let payload_type = parsed
                .payload
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or_default();
            match payload_type {
                "function_call" => {
                    return vec![build_codex_stream_marker_event(
                        "tool_started",
                        Some("tool_started"),
                        cursor,
                    )];
                }
                "function_call_output" => {
                    return vec![build_codex_stream_marker_event(
                        "tool_completed",
                        Some("tool_completed"),
                        cursor,
                    )];
                }
                _ => {}
            }

            if let Some((role, content)) = extract_codex_response_item_text(&parsed.payload) {
                let phase = parsed
                    .payload
                    .get("phase")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let kind = if role == "assistant" {
                    if phase == "commentary" {
                        "assistant_progress"
                    } else {
                        "assistant_completed"
                    }
                } else {
                    "user_message"
                };
                let semantic_kind = if role == "assistant" {
                    if phase == "commentary" {
                        Some("assistant_progress")
                    } else {
                        Some("turn_completed")
                    }
                } else {
                    None
                };
                return build_codex_stream_turn_event(kind, semantic_kind, &role, content, cursor)
                    .into_iter()
                    .collect();
            }
        }
        "event_msg" => {
            let payload_type = parsed
                .payload
                .get("type")
                .and_then(Value::as_str)
                .unwrap_or_default();
            match payload_type {
                "task_started" => {
                    return vec![build_codex_stream_marker_event(
                        "run_started",
                        Some("run_started"),
                        cursor,
                    )];
                }
                "task_complete" => {
                    return vec![build_codex_stream_marker_event(
                        "turn_completed",
                        Some("turn_completed"),
                        cursor,
                    )];
                }
                "user_message" => {
                    if let Some(msg) = parsed.payload.get("message").and_then(Value::as_str) {
                        return build_codex_stream_turn_event(
                            "user_message",
                            None,
                            "user",
                            msg.to_string(),
                            cursor,
                        )
                        .into_iter()
                        .collect();
                    }
                }
                "agent_message" => {
                    if let Some(msg) = parsed.payload.get("message").and_then(Value::as_str) {
                        let phase = parsed
                            .payload
                            .get("phase")
                            .and_then(Value::as_str)
                            .unwrap_or_default();
                        return build_codex_stream_turn_event(
                            if phase == "commentary" {
                                "assistant_progress"
                            } else {
                                "assistant_completed"
                            },
                            if phase == "commentary" {
                                Some("assistant_progress")
                            } else {
                                Some("turn_completed")
                            },
                            "assistant",
                            msg.to_string(),
                            cursor,
                        )
                        .into_iter()
                        .collect();
                    }
                }
                "turn_aborted" => {
                    let reason = parsed
                        .payload
                        .get("reason")
                        .and_then(Value::as_str)
                        .map(ToOwned::to_owned);
                    return vec![CodexThreadStreamEvent {
                        kind: "turn_aborted".to_string(),
                        semantic_kind: Some("turn_aborted".to_string()),
                        turn: None,
                        cursor,
                        reason,
                        error: None,
                        session_tab_visible_at: Some(unix_time_millis()),
                    }];
                }
                _ => {}
            }
        }
        _ => {}
    }

    Vec::new()
}

fn parse_codex_rollout_line(line: &str, turns: &mut Vec<CodexTurn>) {
    let line = line.trim();
    if line.is_empty() {
        return;
    }
    let parsed: RolloutLine = match serde_json::from_str(line) {
        Ok(v) => v,
        Err(_) => return,
    };

    match parsed.line_type.as_str() {
        "response_item" => {
            if let Some((role, content)) = extract_codex_response_item_text(&parsed.payload) {
                push_codex_turn(turns, &role, content);
            }
        }
        "event_msg" => {
            let payload_type = parsed
                .payload
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("");

            match payload_type {
                "user_message" => {
                    if let Some(msg) = parsed.payload.get("message").and_then(|v| v.as_str()) {
                        push_codex_turn(turns, "user", msg.to_string());
                    }
                }
                "agent_message" => {
                    if let Some(msg) = parsed.payload.get("message").and_then(|v| v.as_str()) {
                        push_codex_turn(turns, "assistant", msg.to_string());
                    }
                }
                _ => {}
            }
        }
        _ => {}
    }
}

fn read_codex_thread_state_from_path(rollout_path: &Path) -> Result<CodexThreadReadResult, String> {
    let file = fs::File::open(rollout_path)
        .map_err(|e| format!("Cannot read {}: {e}", rollout_path.display()))?;
    let cursor = CodexThreadCursor {
        offset: file
            .metadata()
            .map_err(|e| format!("Cannot stat {}: {e}", rollout_path.display()))?
            .len(),
    };

    let reader = BufReader::new(file);
    let mut turns = Vec::new();

    for line in reader.lines() {
        let Ok(line) = line else {
            continue;
        };
        parse_codex_rollout_line(&line, &mut turns);
    }

    Ok(CodexThreadReadResult {
        turns,
        cursor,
        replace: true,
    })
}

fn parse_codex_rollout_chunk(chunk: &str) -> (Vec<CodexTurn>, usize) {
    let mut turns = Vec::new();
    let mut consumed_bytes = 0usize;

    for segment in chunk.split_inclusive('\n') {
        let trimmed = segment.trim();
        if trimmed.is_empty() {
            consumed_bytes += segment.len();
            continue;
        }

        if serde_json::from_str::<RolloutLine>(trimmed).is_err() {
            if segment.ends_with('\n') {
                consumed_bytes += segment.len();
                continue;
            }
            break;
        }

        parse_codex_rollout_line(trimmed, &mut turns);
        consumed_bytes += segment.len();
    }

    (turns, consumed_bytes)
}

fn read_codex_thread_updates_from_path(
    rollout_path: &Path,
    cursor: CodexThreadCursor,
) -> Result<CodexThreadReadResult, String> {
    let mut file = fs::File::open(rollout_path)
        .map_err(|e| format!("Cannot read {}: {e}", rollout_path.display()))?;
    let file_len = file
        .metadata()
        .map_err(|e| format!("Cannot stat {}: {e}", rollout_path.display()))?
        .len();

    if file_len < cursor.offset {
        return read_codex_thread_state_from_path(rollout_path);
    }

    if file_len == cursor.offset {
        return Ok(CodexThreadReadResult {
            turns: Vec::new(),
            cursor,
            replace: false,
        });
    }

    file.seek(SeekFrom::Start(cursor.offset))
        .map_err(|e| format!("Cannot seek {}: {e}", rollout_path.display()))?;

    let mut chunk = String::new();
    file.read_to_string(&mut chunk)
        .map_err(|e| format!("Cannot read {}: {e}", rollout_path.display()))?;

    let (turns, consumed_bytes) = parse_codex_rollout_chunk(&chunk);

    Ok(CodexThreadReadResult {
        turns,
        cursor: CodexThreadCursor {
            offset: cursor.offset + consumed_bytes as u64,
        },
        replace: false,
    })
}

#[tauri::command]
pub fn read_codex_thread_state(rollout_path: String) -> Result<CodexThreadReadResult, String> {
    read_codex_thread_state_from_path(Path::new(&rollout_path))
}

#[tauri::command]
pub fn read_codex_thread_updates(
    rollout_path: String,
    cursor: CodexThreadCursor,
) -> Result<CodexThreadReadResult, String> {
    read_codex_thread_updates_from_path(Path::new(&rollout_path), cursor)
}

#[tauri::command]
pub fn read_codex_thread(rollout_path: String) -> Result<Vec<CodexTurn>, String> {
    read_codex_thread_state_from_path(Path::new(&rollout_path)).map(|result| result.turns)
}

#[tauri::command]
pub async fn send_codex_thread_message(
    thread_id: String,
    text: String,
    cwd: Option<String>,
) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        send_codex_thread_message_blocking(&thread_id, &text, cwd.as_deref())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn start_codex_thread_stream(
    rollout_path: String,
    cursor: CodexThreadCursor,
    channel: Channel<CodexThreadStreamEvent>,
) -> Result<(), String> {
    let generation = codex_thread_stream_generation();
    let my_generation = generation.fetch_add(1, Ordering::SeqCst) + 1;
    let path = PathBuf::from(rollout_path);

    tauri::async_runtime::spawn(async move {
        let file = match fs::File::open(&path) {
            Ok(file) => file,
            Err(error) => {
                let _ = channel.send(build_codex_stream_error_event(
                    cursor,
                    format!("Cannot open {}: {error}", path.display()),
                ));
                return;
            }
        };

        let mut reader = BufReader::new(file);
        if let Err(error) = reader.seek(SeekFrom::Start(cursor.offset)) {
            let _ = channel.send(build_codex_stream_error_event(
                cursor,
                format!("Cannot seek {}: {error}", path.display()),
            ));
            return;
        }

        let mut current_cursor = cursor;
        while generation.load(Ordering::SeqCst) == my_generation {
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => {
                    tokio::time::sleep(tokio::time::Duration::from_millis(250)).await;
                }
                Ok(bytes) => {
                    current_cursor.offset += bytes as u64;
                    for event in parse_codex_stream_events(&line, current_cursor) {
                        let _ = channel.send(event);
                    }
                }
                Err(error) => {
                    let _ = channel.send(build_codex_stream_error_event(
                        current_cursor,
                        format!("Cannot read {}: {error}", path.display()),
                    ));
                    break;
                }
            }
        }
    });

    Ok(())
}

#[tauri::command]
pub async fn stop_codex_thread_stream() -> Result<(), String> {
    codex_thread_stream_generation().fetch_add(1, Ordering::SeqCst);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        build_codex_rpc_request, codex_rpc_error_text, is_codex_unmaterialized_error,
        list_codex_threads_from_paths, parse_codex_stream_events, read_codex_thread,
        read_codex_thread_state, read_codex_thread_updates,
        send_codex_thread_message_via_owner_bridge,
        send_codex_thread_message_via_owner_bridge_with_retry, CodexThreadCursor,
    };
    use rusqlite::{params, Connection};
    use serde_json::json;

    #[test]
    fn build_codex_rpc_request_wraps_method_and_params() {
        let request = build_codex_rpc_request(3, "turn/start", json!({"threadId": "tid-1"}));

        assert_eq!(request["id"], 3);
        assert_eq!(request["method"], "turn/start");
        assert_eq!(request["params"]["threadId"], "tid-1");
    }

    #[test]
    fn send_codex_thread_message_uses_owner_bridge_when_socket_exists() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::net::UnixListener;

        let temp_dir = std::path::PathBuf::from(format!(
            "/tmp/ow-codex-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("codex_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut line = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader.read_line(&mut line).expect("read request");
            let request = serde_json::from_str::<serde_json::Value>(line.trim())
                .expect("parse owner bridge request");
            assert_eq!(request["type"], "send_message");
            assert_eq!(request["thread_id"], "tid-1");
            assert_eq!(request["text"], "hello owner");
            assert_eq!(request["cwd"], "/tmp/onlineWorker");

            stream
                .write_all(b"{\"ok\":true,\"accepted\":true}\n")
                .expect("write response");
        });

        let used_bridge = send_codex_thread_message_via_owner_bridge(
            &temp_dir,
            "tid-1",
            "hello owner",
            Some("/tmp/onlineWorker"),
        )
        .expect("send via owner bridge");

        assert!(used_bridge);

        server.join().expect("join server thread");
        let _ = std::fs::remove_file(&socket_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn send_codex_thread_message_surfaces_owner_bridge_errors() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::net::UnixListener;

        let temp_dir = std::path::PathBuf::from(format!(
            "/tmp/ow-codex-err-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("codex_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut line = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader.read_line(&mut line).expect("read request");
            stream
                .write_all(b"{\"ok\":false,\"error\":\"owner adapter unavailable\"}\n")
                .expect("write response");
        });

        let error = send_codex_thread_message_via_owner_bridge(&temp_dir, "tid-1", "hello", None)
            .expect_err("owner bridge should return error");

        assert!(error.contains("owner adapter unavailable"));

        server.join().expect("join server thread");
        let _ = std::fs::remove_file(&socket_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn send_codex_thread_message_waits_for_owner_bridge_socket() {
        use std::io::{BufRead, BufReader, Write};
        use std::os::unix::net::UnixListener;
        use std::time::Duration;

        let temp_dir = std::path::PathBuf::from(format!(
            "/tmp/ow-codex-wait-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("codex_owner_bridge.sock");
        let socket_path_for_server = socket_path.clone();

        let server = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(200));
            let listener =
                UnixListener::bind(&socket_path_for_server).expect("bind owner bridge socket");
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut line = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader.read_line(&mut line).expect("read request");
            let request = serde_json::from_str::<serde_json::Value>(line.trim())
                .expect("parse owner bridge request");
            assert_eq!(request["thread_id"], "tid-wait");
            stream
                .write_all(b"{\"ok\":true,\"accepted\":true}\n")
                .expect("write response");
        });

        send_codex_thread_message_via_owner_bridge_with_retry(
            &temp_dir,
            "tid-wait",
            "hello after wait",
            None,
            Duration::from_secs(1),
        )
        .expect("owner bridge should become ready within timeout");

        server.join().expect("join server thread");
        let _ = std::fs::remove_file(&socket_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn send_codex_thread_message_reports_owner_bridge_timeout_without_fallback() {
        use std::time::Duration;

        let temp_dir = std::path::PathBuf::from(format!(
            "/tmp/ow-codex-timeout-{:x}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");

        let error = send_codex_thread_message_via_owner_bridge_with_retry(
            &temp_dir,
            "tid-timeout",
            "hello timeout",
            None,
            Duration::from_millis(250),
        )
        .expect_err("owner bridge should time out when socket never appears");

        assert!(error.contains("codex owner bridge not ready"));
        assert!(!error.contains("127.0.0.1:4722"));

        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn codex_unmaterialized_error_matches_known_messages() {
        assert!(is_codex_unmaterialized_error(
            "thread is not materialized yet, resume later"
        ));
        assert!(is_codex_unmaterialized_error(
            "no rollout found for thread id abc123"
        ));
        assert!(!is_codex_unmaterialized_error("permission denied"));
    }

    #[test]
    fn codex_rpc_error_text_prefers_message_field() {
        let response = json!({
            "error": {
                "message": "resume failed"
            }
        });

        assert_eq!(
            codex_rpc_error_text(&response).as_deref(),
            Some("resume failed")
        );
    }

    #[test]
    fn list_codex_threads_filters_subagent_rows() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let db_path = temp_dir.join("state_5.sqlite");

        let conn = Connection::open(&db_path).expect("open sqlite");
        conn.execute_batch(
            "
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            );
            ",
        )
        .expect("create threads table");

        conn.execute(
            "
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode, model, reasoning_effort, agent_path
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8,
                ?9, ?10, ?11, ?12, ?13, ?14,
                ?15, ?16, ?17, ?18, ?19, ?20,
                ?21, ?22, ?23, ?24, ?25
            );
            ",
            params![
                "main-thread",
                "/tmp/main.jsonl",
                1_i64,
                100_i64,
                "vscode",
                "openai",
                "/tmp/workspace",
                "Main thread",
                "workspace-write",
                "default",
                0_i64,
                1_i64,
                0_i64,
                None::<i64>,
                None::<String>,
                None::<String>,
                None::<String>,
                "",
                "Main thread",
                None::<String>,
                None::<String>,
                "enabled",
                None::<String>,
                None::<String>,
                None::<String>,
            ],
        )
        .expect("insert main thread");

        conn.execute(
            "
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode, model, reasoning_effort, agent_path
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8,
                ?9, ?10, ?11, ?12, ?13, ?14,
                ?15, ?16, ?17, ?18, ?19, ?20,
                ?21, ?22, ?23, ?24, ?25
            );
            ",
            params![
                "subagent-thread",
                "/tmp/subagent.jsonl",
                2_i64,
                200_i64,
                r#"{"subagent":{"other":"guardian"}}"#,
                "openai",
                "/tmp/workspace",
                "Guardian thread",
                "workspace-write",
                "default",
                0_i64,
                0_i64,
                0_i64,
                None::<i64>,
                None::<String>,
                None::<String>,
                None::<String>,
                "",
                "Guardian thread",
                None::<String>,
                None::<String>,
                "enabled",
                None::<String>,
                None::<String>,
                None::<String>,
            ],
        )
        .expect("insert subagent thread");

        drop(conn);

        let threads =
            list_codex_threads_from_paths(&db_path, None, None).expect("list codex threads");

        assert_eq!(threads.len(), 1);
        assert_eq!(threads[0].id, "main-thread");
        assert_eq!(threads[0].title, "Main thread");

        let _ = std::fs::remove_file(&db_path);
        let _ = std::fs::remove_dir(&temp_dir);
    }

    #[test]
    fn list_codex_threads_overlays_local_archived_state() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-archive-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let db_path = temp_dir.join("state_5.sqlite");
        let state_path = temp_dir.join("onlineworker_state.json");

        let conn = Connection::open(&db_path).expect("open sqlite");
        conn.execute_batch(
            "
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            );
            ",
        )
        .expect("create threads table");

        conn.execute(
            "
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode, model, reasoning_effort, agent_path
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8,
                ?9, ?10, ?11, ?12, ?13, ?14,
                ?15, ?16, ?17, ?18, ?19, ?20,
                ?21, ?22, ?23, ?24, ?25
            );
            ",
            params![
                "main-thread",
                "/tmp/main.jsonl",
                1_i64,
                100_i64,
                "vscode",
                "openai",
                "/Users/example/Projects/onlineWorker",
                "Main thread",
                "workspace-write",
                "default",
                0_i64,
                1_i64,
                0_i64,
                None::<i64>,
                None::<String>,
                None::<String>,
                None::<String>,
                "",
                "Main thread",
                None::<String>,
                None::<String>,
                "enabled",
                None::<String>,
                None::<String>,
                None::<String>,
            ],
        )
        .expect("insert main thread");
        drop(conn);

        std::fs::write(
            &state_path,
            r#"{
              "workspaces": {
                "codex:onlineWorker": {
                  "name": "onlineWorker",
                  "path": "/Users/example/Projects/onlineWorker",
                  "tool": "codex",
                  "threads": {
                    "main-thread": {
                      "preview": "Main thread",
                      "archived": true
                    }
                  }
                }
              }
            }"#,
        )
        .expect("write state file");

        let threads = list_codex_threads_from_paths(&db_path, Some(&state_path), None)
            .expect("list codex threads");

        assert_eq!(threads.len(), 1);
        assert_eq!(threads[0].id, "main-thread");
        assert!(threads[0].archived);

        let _ = std::fs::remove_file(&db_path);
        let _ = std::fs::remove_file(&state_path);
        let _ = std::fs::remove_dir(&temp_dir);
    }

    #[test]
    fn list_codex_threads_includes_jsonl_only_main_thread() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-jsonl-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let sessions_dir = temp_dir.join("sessions");
        let rollout_dir = sessions_dir.join("2026/04/10");
        std::fs::create_dir_all(&rollout_dir).expect("create sessions dir");
        let db_path = temp_dir.join("state_5.sqlite");

        let conn = Connection::open(&db_path).expect("open sqlite");
        conn.execute_batch(
            "
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            );
            ",
        )
        .expect("create threads table");
        conn.execute(
            "
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode, model, reasoning_effort, agent_path
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8,
                ?9, ?10, ?11, ?12, ?13, ?14,
                ?15, ?16, ?17, ?18, ?19, ?20,
                ?21, ?22, ?23, ?24, ?25
            );
            ",
            params![
                "main-thread",
                "/tmp/main.jsonl",
                1_i64,
                100_i64,
                "vscode",
                "openai",
                "/Users/example/Projects/onlineWorker",
                "Main thread",
                "workspace-write",
                "default",
                0_i64,
                1_i64,
                0_i64,
                None::<i64>,
                None::<String>,
                None::<String>,
                None::<String>,
                "",
                "Main thread",
                None::<String>,
                None::<String>,
                "enabled",
                None::<String>,
                None::<String>,
                None::<String>,
            ],
        )
        .expect("insert main thread");
        drop(conn);

        let rollout_path = rollout_dir
            .join("rollout-2026-04-10T17-27-11-019d76b7-8229-7b63-b851-0e8e572b0672.jsonl");
        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-10T09:27:23.213Z\",\"type\":\"session_meta\",\"payload\":{\"id\":\"019d76b7-8229-7b63-b851-0e8e572b0672\",\"timestamp\":\"2026-04-10T09:27:11.147Z\",\"cwd\":\"/Users/example/Projects/onlineWorker\",\"source\":\"cli\"}}\n",
                "{\"timestamp\":\"2026-04-10T09:27:23.214Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"继续处理phase15\"}]}}\n"
            ),
        )
        .expect("write rollout file");

        let threads = list_codex_threads_from_paths(&db_path, None, Some(&sessions_dir))
            .expect("list codex threads");

        assert_eq!(threads.len(), 2);
        assert_eq!(threads[0].id, "019d76b7-8229-7b63-b851-0e8e572b0672");
        assert_eq!(threads[0].title, "继续处理phase15");
        assert_eq!(
            threads[0].rollout_path,
            rollout_path.to_string_lossy().to_string()
        );
        assert_eq!(threads[0].model_provider.as_deref(), None);
        assert_eq!(threads[0].source.as_deref(), Some("cli"));
        assert!(!threads[0].is_smoke);

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_file(&db_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn list_codex_threads_exposes_model_provider_and_source_for_db_rows() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-provider-meta-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let db_path = temp_dir.join("state_5.sqlite");

        let conn = Connection::open(&db_path).expect("open sqlite");
        conn.execute_batch(
            "
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            );
            ",
        )
        .expect("create threads table");

        conn.execute(
            "
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider, cwd, title,
                sandbox_policy, approval_mode, tokens_used, has_user_event, archived, archived_at,
                git_sha, git_branch, git_origin_url, cli_version, first_user_message, agent_nickname,
                agent_role, memory_mode, model, reasoning_effort, agent_path
            ) VALUES (
                ?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8,
                ?9, ?10, ?11, ?12, ?13, ?14,
                ?15, ?16, ?17, ?18, ?19, ?20,
                ?21, ?22, ?23, ?24, ?25
            );
            ",
            params![
                "legacy-thread",
                "/tmp/legacy.jsonl",
                1_i64,
                100_i64,
                "cli",
                "custom",
                "/Users/example/Projects/onlineWorker",
                "which model now use",
                "workspace-write",
                "default",
                0_i64,
                1_i64,
                0_i64,
                None::<i64>,
                None::<String>,
                None::<String>,
                None::<String>,
                "",
                "which model now use",
                None::<String>,
                None::<String>,
                "enabled",
                None::<String>,
                None::<String>,
                None::<String>,
            ],
        )
        .expect("insert thread");
        drop(conn);

        let threads =
            list_codex_threads_from_paths(&db_path, None, None).expect("list codex threads");

        assert_eq!(threads.len(), 1);
        assert_eq!(threads[0].id, "legacy-thread");
        assert_eq!(threads[0].model_provider.as_deref(), Some("custom"));
        assert_eq!(threads[0].source.as_deref(), Some("cli"));
        assert!(!threads[0].is_smoke);

        let _ = std::fs::remove_file(&db_path);
        let _ = std::fs::remove_dir(&temp_dir);
    }

    #[test]
    fn list_codex_threads_marks_smoke_threads() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-smoke-meta-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let sessions_dir = temp_dir.join("sessions");
        let rollout_dir = sessions_dir.join("2026/05/10");
        std::fs::create_dir_all(&rollout_dir).expect("create sessions dir");
        let db_path = temp_dir.join("state_5.sqlite");

        let conn = Connection::open(&db_path).expect("open sqlite");
        conn.execute_batch(
            "
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                has_user_event INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                archived_at INTEGER,
                git_sha TEXT,
                git_branch TEXT,
                git_origin_url TEXT,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                agent_nickname TEXT,
                agent_role TEXT,
                memory_mode TEXT NOT NULL DEFAULT 'enabled',
                model TEXT,
                reasoning_effort TEXT,
                agent_path TEXT
            );
            ",
        )
        .expect("create threads table");
        drop(conn);

        let rollout_path = rollout_dir
            .join("rollout-2026-05-10T09-00-00-019smoke-8229-7b63-b851-0e8e572b0672.jsonl");
        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-05-10T09:00:00.000Z\",\"type\":\"session_meta\",\"payload\":{\"id\":\"019smoke-8229-7b63-b851-0e8e572b0672\",\"cwd\":\"/Users/example/Projects/onlineWorker\",\"source\":\"cli\",\"model_provider\":\"codex\"}}\n",
                "{\"timestamp\":\"2026-05-10T09:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"This is an OnlineWorker fixed-session smoke test for provider codex. Reply with ONLINEWORKER_SMOKE_OK.\"}]}}\n"
            ),
        )
        .expect("write rollout file");

        let threads = list_codex_threads_from_paths(&db_path, None, Some(&sessions_dir))
            .expect("list codex threads");

        assert_eq!(threads.len(), 1);
        assert_eq!(threads[0].model_provider.as_deref(), Some("codex"));
        assert_eq!(threads[0].source.as_deref(), Some("cli"));
        assert!(threads[0].is_smoke);
        assert!(!threads[0].archived);

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_file(&db_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn read_codex_thread_parses_response_item_messages() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-read-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let rollout_path = temp_dir.join("rollout.jsonl");

        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:00.000Z\",\"type\":\"session_meta\",\"payload\":{\"id\":\"thread-1\",\"cwd\":\"/Users/example/Projects/onlineWorker\"}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"developer\",\"content\":[{\"type\":\"input_text\",\"text\":\"ignore developer\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:02.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"继续处理phase15\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"我先定位问题。\"},{\"type\":\"output_text\",\"text\":\"随后补测试。\"}]}}\n"
            ),
        )
        .expect("write rollout");

        let turns = read_codex_thread(rollout_path.to_string_lossy().to_string())
            .expect("read codex thread");

        assert_eq!(turns.len(), 2);
        assert_eq!(turns[0].role, "user");
        assert_eq!(turns[0].content, "继续处理phase15");
        assert_eq!(turns[1].role, "assistant");
        assert_eq!(turns[1].content, "我先定位问题。\n随后补测试。");

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn read_codex_thread_deduplicates_adjacent_duplicate_messages() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-read-dedupe-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let rollout_path = temp_dir.join("rollout.jsonl");

        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:00.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"user_message\",\"message\":\"你好\"}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"你好\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:02.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"agent_message\",\"message\":\"我在。\"}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"我在。\"}]}}\n"
            ),
        )
        .expect("write rollout");

        let turns = read_codex_thread(rollout_path.to_string_lossy().to_string())
            .expect("read codex thread");

        assert_eq!(turns.len(), 2);
        assert_eq!(turns[0].role, "user");
        assert_eq!(turns[0].content, "你好");
        assert_eq!(turns[1].role, "assistant");
        assert_eq!(turns[1].content, "我在。");

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn read_codex_thread_filters_turn_aborted_control_messages() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-read-aborted-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let rollout_path = temp_dir.join("rollout.jsonl");

        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:00.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"你好\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"<turn_aborted>\\nThe user interrupted the previous turn on purpose.\\n</turn_aborted>\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:02.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"我在。\"}]}}\n"
            ),
        )
        .expect("write rollout");

        let turns = read_codex_thread(rollout_path.to_string_lossy().to_string())
            .expect("read codex thread");

        assert_eq!(turns.len(), 2);
        assert_eq!(turns[0].role, "user");
        assert_eq!(turns[0].content, "你好");
        assert_eq!(turns[1].role, "assistant");
        assert_eq!(turns[1].content, "我在。");

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn read_codex_thread_filters_startup_envelope_messages() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-read-envelope-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let rollout_path = temp_dir.join("rollout.jsonl");

        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:00.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"# AGENTS.md instructions for /Users/example/Projects/onlineWorker\\n\\n<INSTRUCTIONS>\\n# Global Agent Instructions\\n\\n- 默认使用中文回答\\n</INSTRUCTIONS>\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"<environment_context>\\n  <cwd>/Users/example/Projects/onlineWorker</cwd>\\n</environment_context>\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:02.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"<skill>\\n<name>ask</name>\\n<path>/Users/example/.git-ai/skills/ask/SKILL.md</path>\\n</skill>\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"继续处理 phase17\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:04.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"我先定位问题。\"}]}}\n"
            ),
        )
        .expect("write rollout");

        let turns = read_codex_thread(rollout_path.to_string_lossy().to_string())
            .expect("read codex thread");

        assert_eq!(turns.len(), 2);
        assert_eq!(turns[0].role, "user");
        assert_eq!(turns[0].content, "继续处理 phase17");
        assert_eq!(turns[1].role, "assistant");
        assert_eq!(turns[1].content, "我先定位问题。");

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn read_codex_thread_updates_only_returns_new_turns_after_offset() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-codex-read-updates-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let rollout_path = temp_dir.join("rollout.jsonl");

        std::fs::write(
            &rollout_path,
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:00.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"继续\"}]}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:01.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"先看代码。\"}],\"phase\":\"commentary\"}}\n"
            ),
        )
        .expect("write initial rollout");

        let initial = read_codex_thread_state(rollout_path.to_string_lossy().to_string())
            .expect("read initial codex thread state");

        assert!(initial.replace);
        assert_eq!(initial.turns.len(), 2);
        assert!(initial.cursor.offset > 0);

        let mut file = std::fs::OpenOptions::new()
            .append(true)
            .open(&rollout_path)
            .expect("open rollout for append");
        use std::io::Write;
        file.write_all(
            concat!(
                "{\"timestamp\":\"2026-04-13T10:00:02.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"接着补测试。\"}],\"phase\":\"commentary\"}}\n",
                "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"修复已完成。\"}],\"phase\":\"final_answer\"}}\n"
            )
            .as_bytes(),
        )
        .expect("append rollout");

        let updates = read_codex_thread_updates(
            rollout_path.to_string_lossy().to_string(),
            CodexThreadCursor {
                offset: initial.cursor.offset,
            },
        )
        .expect("read codex thread updates");

        assert!(!updates.replace);
        assert_eq!(updates.turns.len(), 2);
        assert_eq!(updates.turns[0].content, "接着补测试。");
        assert_eq!(updates.turns[1].content, "修复已完成。");
        assert!(updates.cursor.offset > initial.cursor.offset);

        let _ = std::fs::remove_file(&rollout_path);
        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn parse_codex_stream_events_emits_assistant_completed_for_response_item() {
        let events = parse_codex_stream_events(
            "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"修复已完成。\"}]}}",
            CodexThreadCursor { offset: 128 },
        );

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, "assistant_completed");
        assert_eq!(events[0].semantic_kind.as_deref(), Some("turn_completed"));
        assert_eq!(
            events[0].turn.as_ref().map(|turn| turn.content.as_str()),
            Some("修复已完成。")
        );
        assert_eq!(events[0].cursor.offset, 128);
        assert!(events[0].session_tab_visible_at.unwrap_or(0) > 0);
    }

    #[test]
    fn parse_codex_stream_events_marks_commentary_messages_as_progress() {
        let events = parse_codex_stream_events(
            "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"assistant\",\"phase\":\"commentary\",\"content\":[{\"type\":\"output_text\",\"text\":\"我先排查链路。\"}]}}",
            CodexThreadCursor { offset: 144 },
        );

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, "assistant_progress");
        assert_eq!(
            events[0].semantic_kind.as_deref(),
            Some("assistant_progress")
        );
        assert_eq!(
            events[0].turn.as_ref().map(|turn| turn.content.as_str()),
            Some("我先排查链路。")
        );
        assert_eq!(events[0].cursor.offset, 144);
    }

    #[test]
    fn parse_codex_stream_events_emits_turn_aborted_event() {
        let events = parse_codex_stream_events(
            "{\"timestamp\":\"2026-04-13T10:00:04.000Z\",\"type\":\"event_msg\",\"payload\":{\"type\":\"turn_aborted\",\"reason\":\"interrupted\"}}",
            CodexThreadCursor { offset: 256 },
        );

        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, "turn_aborted");
        assert_eq!(events[0].semantic_kind.as_deref(), Some("turn_aborted"));
        assert_eq!(events[0].reason.as_deref(), Some("interrupted"));
        assert!(events[0].turn.is_none());
        assert_eq!(events[0].cursor.offset, 256);
    }

    #[test]
    fn parse_codex_stream_events_emits_tool_semantics_for_function_call_lines() {
        let started = parse_codex_stream_events(
            "{\"timestamp\":\"2026-04-13T10:00:03.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"function_call\",\"name\":\"exec_command\",\"arguments\":\"{\\\"cmd\\\":\\\"rg --files\\\"}\",\"call_id\":\"call-1\"}}",
            CodexThreadCursor { offset: 320 },
        );
        let completed = parse_codex_stream_events(
            "{\"timestamp\":\"2026-04-13T10:00:04.000Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"function_call_output\",\"call_id\":\"call-1\",\"output\":\"a\\nb\"}}",
            CodexThreadCursor { offset: 384 },
        );

        assert_eq!(started.len(), 1);
        assert_eq!(started[0].kind, "tool_started");
        assert_eq!(started[0].semantic_kind.as_deref(), Some("tool_started"));

        assert_eq!(completed.len(), 1);
        assert_eq!(completed[0].kind, "tool_completed");
        assert_eq!(
            completed[0].semantic_kind.as_deref(),
            Some("tool_completed")
        );
    }
}
