use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::config::ensure_data_dir;
use super::provider_bridge_common::provider_owner_bridge_socket_path;

const TASK_BOARD_STATE_FILE: &str = "task_board_state.json";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardSessionRef {
    pub provider_id: String,
    pub session_id: String,
    pub updated_at_epoch: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardState {
    pub version: u32,
    pub pinned: Vec<TaskBoardSessionRef>,
    pub hidden: Vec<TaskBoardSessionRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardSessionActivity {
    pub provider_id: String,
    pub workspace_id: String,
    pub workspace_path: String,
    pub session_id: String,
    pub title: String,
    pub status: String,
    pub attention_reason: String,
    pub last_user_message: String,
    pub last_assistant_message: String,
    pub last_final_message: String,
    pub last_event_kind: String,
    pub updated_at: f64,
}

#[derive(Debug, Deserialize)]
struct SessionActivitiesResponse {
    ok: bool,
    #[serde(default)]
    activities: Vec<TaskBoardSessionActivity>,
    #[serde(default)]
    error: Option<String>,
}

impl Default for TaskBoardState {
    fn default() -> Self {
        Self {
            version: 1,
            pinned: Vec::new(),
            hidden: Vec::new(),
        }
    }
}

fn task_board_state_path() -> Result<PathBuf, String> {
    Ok(ensure_data_dir()?.join(TASK_BOARD_STATE_FILE))
}

fn now_epoch_seconds() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}

fn same_session(item: &TaskBoardSessionRef, provider_id: &str, session_id: &str) -> bool {
    item.provider_id == provider_id && item.session_id == session_id
}

fn normalize_ref(provider_id: &str, session_id: &str) -> Result<(String, String), String> {
    let provider_id = provider_id.trim();
    let session_id = session_id.trim();
    if provider_id.is_empty() {
        return Err("provider_id is required".to_string());
    }
    if session_id.is_empty() {
        return Err("session_id is required".to_string());
    }
    Ok((provider_id.to_string(), session_id.to_string()))
}

fn upsert_session_ref(list: &mut Vec<TaskBoardSessionRef>, provider_id: &str, session_id: &str) {
    if let Some(item) = list
        .iter_mut()
        .find(|item| same_session(item, provider_id, session_id))
    {
        item.updated_at_epoch = now_epoch_seconds();
        return;
    }
    list.push(TaskBoardSessionRef {
        provider_id: provider_id.to_string(),
        session_id: session_id.to_string(),
        updated_at_epoch: now_epoch_seconds(),
    });
}

fn remove_session_ref(list: &mut Vec<TaskBoardSessionRef>, provider_id: &str, session_id: &str) {
    list.retain(|item| !same_session(item, provider_id, session_id));
}

pub fn load_task_board_state_from_path(path: &Path) -> TaskBoardState {
    let Ok(raw) = std::fs::read_to_string(path) else {
        return TaskBoardState::default();
    };
    serde_json::from_str::<TaskBoardState>(&raw).unwrap_or_default()
}

fn save_task_board_state_to_path(path: &Path, state: &TaskBoardState) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create task board state dir failed: {e}"))?;
    }
    let payload = serde_json::to_string_pretty(state)
        .map_err(|e| format!("serialize task board state failed: {e}"))?;
    let tmp_path = path.with_extension("json.tmp");
    std::fs::write(&tmp_path, payload)
        .map_err(|e| format!("write task board state tmp failed: {e}"))?;
    std::fs::rename(&tmp_path, path).map_err(|e| format!("replace task board state failed: {e}"))?;
    Ok(())
}

fn mutate_task_board_state<F>(mutate: F) -> Result<TaskBoardState, String>
where
    F: FnOnce(&mut TaskBoardState),
{
    let path = task_board_state_path()?;
    let mut state = load_task_board_state_from_path(&path);
    state.version = 1;
    mutate(&mut state);
    save_task_board_state_to_path(&path, &state)?;
    Ok(state)
}

#[tauri::command]
pub async fn get_task_board_state() -> Result<TaskBoardState, String> {
    Ok(load_task_board_state_from_path(&task_board_state_path()?))
}

#[tauri::command]
pub async fn get_task_board_session_activities() -> Result<Vec<TaskBoardSessionActivity>, String> {
    let data_dir = ensure_data_dir()?;
    let socket_path = provider_owner_bridge_socket_path(&data_dir);
    if !socket_path.exists() {
        return Ok(Vec::new());
    }

    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;
    let payload = serde_json::json!({
        "type": "session_activities",
        "limit": 200,
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

    let response = serde_json::from_str::<SessionActivitiesResponse>(response_line.trim())
        .map_err(|e| format!("parse provider owner bridge response failed: {e}"))?;
    if response.ok {
        Ok(response.activities)
    } else {
        Err(response
            .error
            .unwrap_or_else(|| "provider owner bridge request failed".to_string()))
    }
}

#[tauri::command]
pub async fn pin_task_board_session(
    provider_id: String,
    session_id: String,
) -> Result<TaskBoardState, String> {
    let (provider_id, session_id) = normalize_ref(&provider_id, &session_id)?;
    mutate_task_board_state(|state| {
        remove_session_ref(&mut state.hidden, &provider_id, &session_id);
        upsert_session_ref(&mut state.pinned, &provider_id, &session_id);
    })
}

#[tauri::command]
pub async fn unpin_task_board_session(
    provider_id: String,
    session_id: String,
) -> Result<TaskBoardState, String> {
    let (provider_id, session_id) = normalize_ref(&provider_id, &session_id)?;
    mutate_task_board_state(|state| {
        remove_session_ref(&mut state.pinned, &provider_id, &session_id);
    })
}

#[tauri::command]
pub async fn hide_task_board_session(
    provider_id: String,
    session_id: String,
) -> Result<TaskBoardState, String> {
    let (provider_id, session_id) = normalize_ref(&provider_id, &session_id)?;
    mutate_task_board_state(|state| {
        remove_session_ref(&mut state.pinned, &provider_id, &session_id);
        upsert_session_ref(&mut state.hidden, &provider_id, &session_id);
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_task_board_state_returns_default() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-task-board-missing-{}",
            now_epoch_seconds()
        ));
        let state = load_task_board_state_from_path(&dir.join(TASK_BOARD_STATE_FILE));
        assert_eq!(state, TaskBoardState::default());
    }

    #[test]
    fn pinning_removes_hidden_entry() {
        let mut state = TaskBoardState::default();
        upsert_session_ref(&mut state.hidden, "codex", "thread-a");
        remove_session_ref(&mut state.hidden, "codex", "thread-a");
        upsert_session_ref(&mut state.pinned, "codex", "thread-a");

        assert!(state.hidden.is_empty());
        assert_eq!(state.pinned.len(), 1);
        assert_eq!(state.pinned[0].provider_id, "codex");
        assert_eq!(state.pinned[0].session_id, "thread-a");
    }
}
