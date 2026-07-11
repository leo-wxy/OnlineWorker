use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, ErrorKind, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tauri::ipc::Channel;

use super::config::ensure_data_dir;
use super::provider_bridge_common::provider_owner_bridge_socket_path;

const TASK_BOARD_STATE_FILE: &str = "task_board_state.json";
const TASK_BOARD_OWNER_BRIDGE_REQUEST_TIMEOUT: Duration = Duration::from_millis(1200);
const TASK_BOARD_APPROVAL_REPLY_TIMEOUT: Duration = Duration::from_secs(3);
const TASK_BOARD_SESSION_CONTROL_TIMEOUT: Duration = Duration::from_secs(3);
static TASK_BOARD_ACTIVITY_STREAM_NEXT_ID: AtomicU64 = AtomicU64::new(0);
static TASK_BOARD_ACTIVITY_STREAM_ACTIVE_ID: AtomicU64 = AtomicU64::new(0);

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
    #[serde(default)]
    pub attention_kind: String,
    #[serde(default)]
    pub request_id: String,
    #[serde(default)]
    pub approval_source: String,
    #[serde(default)]
    pub mirrored_only: bool,
    #[serde(default)]
    pub can_interrupt: bool,
    #[serde(default)]
    pub can_recover: bool,
    #[serde(default)]
    pub control_reason: String,
    #[serde(default)]
    pub control_mode: String,
    #[serde(default)]
    pub recent_events: Vec<TaskBoardRecentEvent>,
    pub last_user_message: String,
    pub last_assistant_message: String,
    pub last_final_message: String,
    pub last_event_kind: String,
    pub updated_at: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardRecentEvent {
    pub kind: String,
    #[serde(default)]
    pub created_at: f64,
    #[serde(default)]
    pub summary: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardSessionControlResult {
    pub accepted: bool,
    pub action: String,
    pub provider_id: String,
    pub session_id: String,
    pub awaiting_provider_event: bool,
}

#[derive(Debug, Deserialize)]
struct SessionActivitiesResponse {
    ok: bool,
    #[serde(default)]
    activities: Vec<TaskBoardSessionActivity>,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ReplyApprovalResponse {
    ok: bool,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct SessionControlResponse {
    ok: bool,
    #[serde(default)]
    accepted: bool,
    #[serde(default)]
    action: String,
    #[serde(default)]
    provider_id: String,
    #[serde(default)]
    session_id: String,
    #[serde(default)]
    awaiting_provider_event: bool,
    #[serde(default)]
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct TaskBoardActivityStreamEvent {
    pub kind: String,
    #[serde(default)]
    pub activities: Vec<TaskBoardSessionActivity>,
    #[serde(default)]
    pub activity: Option<TaskBoardSessionActivity>,
    #[serde(default)]
    pub provider_id: String,
    #[serde(default)]
    pub session_id: String,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Deserialize)]
struct RawTaskBoardActivityStreamEvent {
    #[serde(default)]
    ok: bool,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    activities: Vec<TaskBoardSessionActivity>,
    #[serde(default)]
    activity: Option<TaskBoardSessionActivity>,
    #[serde(default, rename = "providerId")]
    provider_id: String,
    #[serde(default, rename = "sessionId")]
    session_id: String,
    #[serde(default)]
    error: Option<String>,
}

impl Default for TaskBoardState {
    fn default() -> Self {
        Self {
            version: 1,
            pinned: Vec::new(),
        }
    }
}

fn task_board_state_path() -> Result<PathBuf, String> {
    Ok(ensure_data_dir()?.join(TASK_BOARD_STATE_FILE))
}

fn connect_owner_bridge_socket(
    socket_path: &Path,
    timeout: Duration,
) -> Result<UnixStream, String> {
    let socket = UnixStream::connect(socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;
    socket
        .set_read_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge read timeout failed: {e}"))?;
    socket
        .set_write_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge write timeout failed: {e}"))?;
    Ok(socket)
}

fn read_task_board_session_activities_from_socket_path_with_timeout(
    socket_path: &Path,
    timeout: Duration,
) -> Result<Vec<TaskBoardSessionActivity>, String> {
    let mut socket = connect_owner_bridge_socket(socket_path, timeout)?;
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
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("create task board state dir failed: {e}"))?;
    }
    let payload = serde_json::to_string_pretty(state)
        .map_err(|e| format!("serialize task board state failed: {e}"))?;
    let tmp_path = path.with_extension("json.tmp");
    std::fs::write(&tmp_path, payload)
        .map_err(|e| format!("write task board state tmp failed: {e}"))?;
    std::fs::rename(&tmp_path, path)
        .map_err(|e| format!("replace task board state failed: {e}"))?;
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
    tauri::async_runtime::spawn_blocking(move || {
        read_task_board_session_activities_from_socket_path_with_timeout(
            &socket_path,
            TASK_BOARD_OWNER_BRIDGE_REQUEST_TIMEOUT,
        )
    })
    .await
    .map_err(|error| format!("task board activity blocking task failed: {error}"))?
}

#[tauri::command]
pub async fn reply_task_board_approval(
    provider_id: String,
    workspace_id: String,
    workspace_path: String,
    session_id: String,
    request_id: String,
    action: String,
    approval_source: Option<String>,
    command: Option<String>,
    reason: Option<String>,
) -> Result<(), String> {
    let data_dir = ensure_data_dir()?;
    let socket_path = provider_owner_bridge_socket_path(&data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }

    tauri::async_runtime::spawn_blocking(move || {
        let mut socket =
            connect_owner_bridge_socket(&socket_path, TASK_BOARD_APPROVAL_REPLY_TIMEOUT)?;
        let payload = serde_json::json!({
            "type": "reply_approval",
            "provider_id": provider_id,
            "workspace_id": workspace_id,
            "workspace_dir": workspace_path,
            "workspace_path": workspace_path,
            "session_id": session_id,
            "request_id": request_id,
            "action": action,
            "approval_source": approval_source.unwrap_or_default(),
            "command": command.unwrap_or_default(),
            "reason": reason.unwrap_or_default(),
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

        let response = serde_json::from_str::<ReplyApprovalResponse>(response_line.trim())
            .map_err(|e| format!("parse provider owner bridge response failed: {e}"))?;
        if response.ok {
            Ok(())
        } else {
            Err(response
                .error
                .unwrap_or_else(|| "provider owner bridge approval reply failed".to_string()))
        }
    })
    .await
    .map_err(|error| format!("approval reply blocking task failed: {error}"))?
}

fn control_task_board_session_at_socket_path(
    socket_path: &Path,
    provider_id: &str,
    workspace_id: &str,
    session_id: &str,
    action: &str,
    timeout: Duration,
) -> Result<TaskBoardSessionControlResult, String> {
    let (provider_id, session_id) = normalize_ref(provider_id, session_id)?;
    let action = action.trim().to_lowercase();
    if !matches!(action.as_str(), "interrupt" | "recover") {
        return Err(format!("unsupported session action: {action}"));
    }

    let mut socket = connect_owner_bridge_socket(socket_path, timeout)?;
    let payload = serde_json::json!({
        "type": "session_control",
        "provider_id": provider_id,
        "workspace_id": workspace_id.trim(),
        "session_id": session_id,
        "action": action,
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
    let response = serde_json::from_str::<SessionControlResponse>(response_line.trim())
        .map_err(|e| format!("parse provider owner bridge response failed: {e}"))?;
    if !response.ok {
        return Err(response
            .error
            .unwrap_or_else(|| "provider owner bridge session control failed".to_string()));
    }
    Ok(TaskBoardSessionControlResult {
        accepted: response.accepted,
        action: response.action,
        provider_id: response.provider_id,
        session_id: response.session_id,
        awaiting_provider_event: response.awaiting_provider_event,
    })
}

#[tauri::command]
pub async fn control_task_board_session(
    provider_id: String,
    workspace_id: String,
    session_id: String,
    action: String,
) -> Result<TaskBoardSessionControlResult, String> {
    let data_dir = ensure_data_dir()?;
    let socket_path = provider_owner_bridge_socket_path(&data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }
    tauri::async_runtime::spawn_blocking(move || {
        control_task_board_session_at_socket_path(
            &socket_path,
            &provider_id,
            &workspace_id,
            &session_id,
            &action,
            TASK_BOARD_SESSION_CONTROL_TIMEOUT,
        )
    })
    .await
    .map_err(|error| format!("session control blocking task failed: {error}"))?
}

fn begin_task_board_activity_stream() -> u64 {
    let stream_id = TASK_BOARD_ACTIVITY_STREAM_NEXT_ID.fetch_add(1, Ordering::SeqCst) + 1;
    TASK_BOARD_ACTIVITY_STREAM_ACTIVE_ID.store(stream_id, Ordering::SeqCst);
    stream_id
}

fn task_board_activity_stream_is_active(stream_id: u64) -> bool {
    TASK_BOARD_ACTIVITY_STREAM_ACTIVE_ID.load(Ordering::SeqCst) == stream_id
}

fn stop_task_board_activity_stream_id(stream_id: u64) {
    let _ = TASK_BOARD_ACTIVITY_STREAM_ACTIVE_ID.compare_exchange(
        stream_id,
        0,
        Ordering::SeqCst,
        Ordering::SeqCst,
    );
}

fn parse_task_board_activity_stream_event(line: &str) -> Option<TaskBoardActivityStreamEvent> {
    let raw = serde_json::from_str::<RawTaskBoardActivityStreamEvent>(line.trim()).ok()?;
    if raw.ok && raw.kind == "snapshot" {
        return Some(TaskBoardActivityStreamEvent {
            kind: "snapshot".to_string(),
            activities: raw.activities,
            activity: None,
            provider_id: String::new(),
            session_id: String::new(),
            error: None,
        });
    }
    if raw.ok && raw.kind == "activity" {
        return Some(TaskBoardActivityStreamEvent {
            kind: "activity".to_string(),
            activities: Vec::new(),
            activity: raw.activity,
            provider_id: String::new(),
            session_id: String::new(),
            error: None,
        });
    }
    if raw.ok && raw.kind == "remove" {
        return Some(TaskBoardActivityStreamEvent {
            kind: "remove".to_string(),
            activities: Vec::new(),
            activity: None,
            provider_id: raw.provider_id,
            session_id: raw.session_id,
            error: None,
        });
    }
    Some(TaskBoardActivityStreamEvent {
        kind: "error".to_string(),
        activities: Vec::new(),
        activity: None,
        provider_id: String::new(),
        session_id: String::new(),
        error: raw
            .error
            .or_else(|| Some("provider owner bridge stream failed".to_string())),
    })
}

#[tauri::command]
pub async fn start_task_board_activity_stream(
    channel: Channel<TaskBoardActivityStreamEvent>,
) -> Result<u64, String> {
    let data_dir = ensure_data_dir()?;
    let socket_path = provider_owner_bridge_socket_path(&data_dir);
    let stream_id = begin_task_board_activity_stream();

    tauri::async_runtime::spawn_blocking(move || {
        let reconnect_delay = Duration::from_millis(500);
        while task_board_activity_stream_is_active(stream_id) {
            if !socket_path.exists() {
                let _ = channel.send(TaskBoardActivityStreamEvent {
                    kind: "error".to_string(),
                    activities: Vec::new(),
                    activity: None,
                    provider_id: String::new(),
                    session_id: String::new(),
                    error: Some(format!(
                        "provider owner bridge not ready: {}",
                        socket_path.display()
                    )),
                });
                std::thread::sleep(reconnect_delay);
                continue;
            }

            let mut socket = match UnixStream::connect(&socket_path) {
                Ok(socket) => socket,
                Err(error) => {
                    let _ = channel.send(TaskBoardActivityStreamEvent {
                        kind: "error".to_string(),
                        activities: Vec::new(),
                        activity: None,
                        provider_id: String::new(),
                        session_id: String::new(),
                        error: Some(format!("connect provider owner bridge failed: {error}")),
                    });
                    std::thread::sleep(reconnect_delay);
                    continue;
                }
            };
            let _ = socket.set_read_timeout(Some(Duration::from_secs(1)));
            let payload = serde_json::json!({
                "type": "session_activity_stream",
                "limit": 200,
            });
            let raw_request = format!("{}\n", payload);
            if let Err(error) = socket.write_all(raw_request.as_bytes()) {
                let _ = channel.send(TaskBoardActivityStreamEvent {
                    kind: "error".to_string(),
                    activities: Vec::new(),
                    activity: None,
                    provider_id: String::new(),
                    session_id: String::new(),
                    error: Some(format!(
                        "write provider owner bridge stream request failed: {error}"
                    )),
                });
                std::thread::sleep(reconnect_delay);
                continue;
            }

            let mut reader = BufReader::new(socket);
            while task_board_activity_stream_is_active(stream_id) {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => break,
                    Ok(_) => {
                        if let Some(event) = parse_task_board_activity_stream_event(&line) {
                            let _ = channel.send(event);
                        }
                    }
                    Err(error)
                        if matches!(
                            error.kind(),
                            ErrorKind::WouldBlock | ErrorKind::TimedOut | ErrorKind::Interrupted
                        ) =>
                    {
                        continue;
                    }
                    Err(error) => {
                        let _ = channel.send(TaskBoardActivityStreamEvent {
                            kind: "error".to_string(),
                            activities: Vec::new(),
                            activity: None,
                            provider_id: String::new(),
                            session_id: String::new(),
                            error: Some(format!(
                                "read provider owner bridge stream failed: {error}"
                            )),
                        });
                        break;
                    }
                }
            }

            if task_board_activity_stream_is_active(stream_id) {
                std::thread::sleep(reconnect_delay);
            }
        }
    });

    Ok(stream_id)
}

#[tauri::command]
pub async fn stop_task_board_activity_stream(stream_id: u64) -> Result<(), String> {
    stop_task_board_activity_stream_id(stream_id);
    Ok(())
}

#[tauri::command]
pub async fn pin_task_board_session(
    provider_id: String,
    session_id: String,
) -> Result<TaskBoardState, String> {
    let (provider_id, session_id) = normalize_ref(&provider_id, &session_id)?;
    mutate_task_board_state(|state| {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::io::BufRead;
    use std::io::BufReader;
    use std::os::unix::net::UnixListener;
    use std::thread;

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
    fn pinning_adds_session_ref() {
        let mut state = TaskBoardState::default();
        upsert_session_ref(&mut state.pinned, "primary", "thread-a");

        assert_eq!(state.pinned.len(), 1);
        assert_eq!(state.pinned[0].provider_id, "primary");
        assert_eq!(state.pinned[0].session_id, "thread-a");
    }

    #[test]
    fn parses_task_board_activity_stream_snapshot() {
        let event = parse_task_board_activity_stream_event(
            r#"{"ok":true,"kind":"snapshot","activities":[{"providerId":"primary","workspaceId":"primary:/tmp/project","workspacePath":"/tmp/project","sessionId":"thread-a","title":"Run tests","status":"running","attentionReason":"","lastUserMessage":"Run tests","lastAssistantMessage":"","lastFinalMessage":"","lastEventKind":"message.user.accepted","updatedAt":10.0}]}"#,
        )
        .expect("event");

        assert_eq!(event.kind, "snapshot");
        assert_eq!(event.activities.len(), 1);
        assert_eq!(event.activities[0].last_user_message, "Run tests");
    }

    #[test]
    fn parses_task_board_activity_stream_activity() {
        let event = parse_task_board_activity_stream_event(
            r#"{"ok":true,"kind":"activity","activity":{"providerId":"primary","workspaceId":"primary:/tmp/project","workspacePath":"/tmp/project","sessionId":"thread-a","title":"Run tests","status":"running","attentionReason":"","lastUserMessage":"Run tests","lastAssistantMessage":"working","lastFinalMessage":"","lastEventKind":"message.assistant.delta","updatedAt":20.0}}"#,
        )
        .expect("event");

        assert_eq!(event.kind, "activity");
        assert_eq!(
            event.activity.expect("activity").last_assistant_message,
            "working"
        );
    }

    #[test]
    fn parses_task_board_activity_stream_activity_with_approval_metadata() {
        let event = parse_task_board_activity_stream_event(
            r#"{"ok":true,"kind":"activity","activity":{"providerId":"secondary","workspaceId":"secondary:/tmp/project","workspacePath":"/tmp/project","sessionId":"thread-a","title":"Run tests","status":"needs_attention","attentionReason":"需要处理授权请求","attentionKind":"approval","requestId":"req-1","approvalSource":"item/commandExecution/requestApproval","mirroredOnly":true,"lastUserMessage":"Run tests","lastAssistantMessage":"","lastFinalMessage":"","lastEventKind":"approval.requested","updatedAt":20.0}}"#,
        )
        .expect("event");

        let activity = event.activity.expect("activity");
        assert_eq!(activity.attention_kind, "approval");
        assert_eq!(activity.request_id, "req-1");
        assert_eq!(
            activity.approval_source,
            "item/commandExecution/requestApproval"
        );
        assert!(activity.mirrored_only);
    }

    #[test]
    fn parses_task_board_activity_with_session_control_metadata() {
        let event = parse_task_board_activity_stream_event(
            r#"{"ok":true,"kind":"activity","activity":{"providerId":"codex","workspaceId":"codex:/tmp/project","workspacePath":"/tmp/project","sessionId":"thread-a","title":"Run tests","status":"running","attentionReason":"","attentionKind":"","requestId":"","approvalSource":"","mirroredOnly":false,"canInterrupt":true,"canRecover":false,"controlReason":"","controlMode":"owned","recentEvents":[{"kind":"turn.started","createdAt":20.0,"summary":""}],"lastUserMessage":"Run tests","lastAssistantMessage":"working","lastFinalMessage":"","lastEventKind":"message.assistant.delta","updatedAt":20.0}}"#,
        )
        .expect("event");

        let activity = event.activity.expect("activity");
        assert!(activity.can_interrupt);
        assert!(!activity.can_recover);
        assert_eq!(activity.control_mode, "owned");
        assert_eq!(activity.recent_events.len(), 1);
        assert_eq!(activity.recent_events[0].kind, "turn.started");
    }

    #[test]
    fn session_control_forwards_normalized_request_and_response() {
        let temp_dir =
            std::path::PathBuf::from(format!("/tmp/owtb-control-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader.read_line(&mut request).expect("read request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse request");
            assert_eq!(payload["type"], "session_control");
            assert_eq!(payload["provider_id"], "codex");
            assert_eq!(payload["workspace_id"], "codex:/tmp/project");
            assert_eq!(payload["session_id"], "thread-a");
            assert_eq!(payload["action"], "interrupt");
            stream
                .write_all(
                    b"{\"ok\":true,\"accepted\":true,\"action\":\"interrupt\",\"provider_id\":\"codex\",\"session_id\":\"thread-a\",\"awaiting_provider_event\":true}\n",
                )
                .expect("write response");
        });

        let result = control_task_board_session_at_socket_path(
            &socket_path,
            "codex",
            "codex:/tmp/project",
            "thread-a",
            "interrupt",
            Duration::from_secs(1),
        )
        .expect("control result");
        assert!(result.accepted);
        assert!(result.awaiting_provider_event);
        assert_eq!(result.action, "interrupt");

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn parses_task_board_activity_stream_remove() {
        let event = parse_task_board_activity_stream_event(
            r#"{"ok":true,"kind":"remove","providerId":"external","sessionId":"ses-archived"}"#,
        )
        .expect("event");

        assert_eq!(event.kind, "remove");
        assert_eq!(event.provider_id, "external");
        assert_eq!(event.session_id, "ses-archived");
    }

    #[test]
    fn stale_task_board_activity_stream_stop_does_not_stop_new_stream() {
        let first_stream_id = begin_task_board_activity_stream();
        assert!(task_board_activity_stream_is_active(first_stream_id));

        let second_stream_id = begin_task_board_activity_stream();
        assert!(!task_board_activity_stream_is_active(first_stream_id));
        assert!(task_board_activity_stream_is_active(second_stream_id));

        stop_task_board_activity_stream_id(first_stream_id);
        assert!(task_board_activity_stream_is_active(second_stream_id));

        stop_task_board_activity_stream_id(second_stream_id);
        assert!(!task_board_activity_stream_is_active(second_stream_id));
    }

    #[test]
    fn task_board_session_activities_owner_bridge_timeout_returns_error() {
        let temp_dir =
            std::path::PathBuf::from(format!("/tmp/owtb-timeout-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = temp_dir.join("provider_owner_bridge.sock");
        let listener = UnixListener::bind(&socket_path).expect("bind owner bridge socket");

        let server = thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "session_activities");
            thread::sleep(Duration::from_millis(200));
        });

        let error = read_task_board_session_activities_from_socket_path_with_timeout(
            &socket_path,
            Duration::from_millis(50),
        )
        .expect_err("request should time out");
        assert!(error.contains("read provider owner bridge response failed"));

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }
}
