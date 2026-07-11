use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, OnceLock,
};
use tauri::ipc::Channel;
use tauri::AppHandle;

use super::config::ensure_data_dir;
use super::config_provider::{ProviderMetadata, ProviderSessionAccessCapabilities};
use super::provider_bridge_common::{
    provider_bridge_env, provider_owner_bridge_socket_path, require_runtime_provider,
    run_provider_bridge_sidecar,
};
use super::session_state::load_local_thread_overlays;

static PROVIDER_SESSION_STREAM_GENERATION: OnceLock<Arc<AtomicU64>> = OnceLock::new();
const PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT: std::time::Duration =
    std::time::Duration::from_secs(6);
const PROVIDER_SESSION_BRIDGE_LIST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(2);
const PROVIDER_SESSION_BRIDGE_READ_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(2);

async fn run_owner_bridge_blocking<T, F>(label: &str, operation: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, String> + Send + 'static,
{
    let label = label.to_string();
    tauri::async_runtime::spawn_blocking(operation)
        .await
        .map_err(|error| format!("{label} blocking task failed: {error}"))?
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ComposerAttachment {
    pub id: String,
    pub kind: String,
    pub name: String,
    pub mime_type: Option<String>,
    pub size_bytes: u64,
    pub path: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StagedComposerAttachmentInput {
    pub path: String,
    pub name: Option<String>,
    pub mime_type: Option<String>,
    pub size_bytes: Option<u64>,
    pub base64_data: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderSessionStreamEventTurn {
    pub role: String,
    pub content: String,
    pub display_mode: Option<String>,
    pub pending: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderSessionStreamEvent {
    pub kind: String,
    pub semantic_kind: Option<String>,
    pub turn: Option<ProviderSessionStreamEventTurn>,
    pub reason: Option<String>,
    pub error: Option<String>,
}

fn provider_session_stream_generation() -> Arc<AtomicU64> {
    PROVIDER_SESSION_STREAM_GENERATION
        .get_or_init(|| Arc::new(AtomicU64::new(0)))
        .clone()
}

fn normalized_session_access_value(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn canonical_session_access_value(value: &str) -> String {
    let value = normalized_session_access_value(value);
    if value.is_empty() {
        return "owner_bridge".to_string();
    }

    match value.as_str() {
        // Legacy provider-specific storage/runtime names may still exist in
        // user config.yaml files. The current app session surface routes those
        // operations through the provider owner bridge.
        "codex_threads" | "codex_app_server" | "codex_thread_jsonl" | "claude_projects"
        | "claude_project" => "owner_bridge".to_string(),
        _ => value,
    }
}

fn provider_session_access(provider: &ProviderMetadata) -> ProviderSessionAccessCapabilities {
    provider.capabilities.session_access.clone()
}

fn provider_session_list_access(provider: &ProviderMetadata) -> String {
    canonical_session_access_value(&provider_session_access(provider).list)
}

fn provider_session_read_access(provider: &ProviderMetadata) -> String {
    canonical_session_access_value(&provider_session_access(provider).read)
}

fn provider_session_send_access(provider: &ProviderMetadata) -> String {
    canonical_session_access_value(&provider_session_access(provider).send)
}

fn composer_attachment_staging_dir(data_dir: &Path) -> std::path::PathBuf {
    data_dir.join("composer-attachments")
}

fn infer_attachment_kind(name: &str, mime_type: Option<&str>) -> String {
    let mime = mime_type.unwrap_or_default().trim().to_ascii_lowercase();
    if mime.starts_with("image/") {
        return "image".to_string();
    }
    let lower_name = name.trim().to_ascii_lowercase();
    if [
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic",
    ]
    .iter()
    .any(|suffix| lower_name.ends_with(suffix))
    {
        return "image".to_string();
    }
    "file".to_string()
}

fn connect_owner_bridge_socket(
    data_dir: &Path,
    timeout: std::time::Duration,
) -> Result<UnixStream, String> {
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }

    let socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;
    socket
        .set_read_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge read timeout failed: {e}"))?;
    socket
        .set_write_timeout(Some(timeout))
        .map_err(|e| format!("set provider owner bridge write timeout failed: {e}"))?;
    Ok(socket)
}

fn send_provider_session_message_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    text: &str,
    attachments: &[ComposerAttachment],
    workspace_dir: Option<&str>,
) -> Result<Option<Value>, String> {
    let mut socket =
        match connect_owner_bridge_socket(data_dir, PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT) {
            Ok(socket) => socket,
            Err(error) if error.starts_with("provider owner bridge not ready: ") => {
                return Ok(None)
            }
            Err(error) => return Err(error),
        };

    let mut payload = serde_json::json!({
        "type": "send_message",
        "provider_id": provider_id,
        "thread_id": session_id,
        "text": text,
        "source": "session_tab",
    });
    if !attachments.is_empty() {
        payload["attachments"] = serde_json::to_value(attachments)
            .map_err(|e| format!("serialize attachments failed: {e}"))?;
    }
    if let Some(workspace_dir) = workspace_dir
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        payload["workspace_dir"] = Value::String(workspace_dir.to_string());
    }

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
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        return Ok(Some(response));
    }

    Err(response
        .get("error")
        .and_then(Value::as_str)
        .unwrap_or("provider owner bridge request failed")
        .to_string())
}

fn start_provider_session_message_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    workspace_dir: &str,
    text: &str,
    attachments: &[ComposerAttachment],
) -> Result<Value, String> {
    let mut socket = connect_owner_bridge_socket(data_dir, PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT)?;

    let mut payload = serde_json::json!({
        "type": "start_session_message",
        "provider_id": provider_id,
        "workspace_dir": workspace_dir,
        "text": text,
        "source": "session_tab",
    });
    if !attachments.is_empty() {
        payload["attachments"] = serde_json::to_value(attachments)
            .map_err(|e| format!("serialize attachments failed: {e}"))?;
    }

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
    if response.get("ok").and_then(Value::as_bool) == Some(true) {
        return Ok(response);
    }

    Err(response
        .get("error")
        .and_then(Value::as_str)
        .unwrap_or("provider owner bridge request failed")
        .to_string())
}

fn read_provider_session_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
    limit: usize,
) -> Result<Value, String> {
    read_provider_session_via_owner_bridge_with_timeout(
        data_dir,
        provider_id,
        session_id,
        workspace_dir,
        limit,
        PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT,
    )
}

fn read_provider_session_via_owner_bridge_with_timeout(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
    limit: usize,
    timeout: std::time::Duration,
) -> Result<Value, String> {
    let mut socket = connect_owner_bridge_socket(data_dir, timeout)?;

    let mut payload = serde_json::json!({
        "type": "read_session",
        "provider_id": provider_id,
        "session_id": session_id,
        "limit": limit,
    });
    if let Some(workspace_dir) = workspace_dir
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        payload["workspace_dir"] = Value::String(workspace_dir.to_string());
    }

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

    Ok(response
        .get("session")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

fn list_provider_sessions_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    limit: usize,
    force_refresh: bool,
) -> Result<Value, String> {
    list_provider_sessions_via_owner_bridge_with_timeout(
        data_dir,
        provider_id,
        limit,
        force_refresh,
        PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT,
    )
}

fn list_provider_sessions_via_owner_bridge_with_timeout(
    data_dir: &Path,
    provider_id: &str,
    limit: usize,
    force_refresh: bool,
    timeout: std::time::Duration,
) -> Result<Value, String> {
    let mut socket = connect_owner_bridge_socket(data_dir, timeout)?;

    let payload = serde_json::json!({
        "type": "list_sessions",
        "provider_id": provider_id,
        "limit": limit,
        "force_refresh": force_refresh,
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

    Ok(response
        .get("sessions")
        .cloned()
        .unwrap_or(Value::Array(vec![])))
}

fn archive_provider_session_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
) -> Result<Value, String> {
    let mut socket = connect_owner_bridge_socket(data_dir, PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT)?;

    let mut payload = serde_json::json!({
        "type": "archive_session",
        "provider_id": provider_id,
        "session_id": session_id,
    });
    if let Some(workspace_dir) = workspace_dir.filter(|value| !value.trim().is_empty()) {
        payload["workspace_dir"] = Value::String(workspace_dir.to_string());
    }

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

    Ok(response)
}

fn create_provider_session_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    workspace_dir: &str,
) -> Result<Value, String> {
    let mut socket = connect_owner_bridge_socket(data_dir, PROVIDER_OWNER_BRIDGE_REQUEST_TIMEOUT)?;

    let payload = serde_json::json!({
        "type": "create_session",
        "provider_id": provider_id,
        "workspace_dir": workspace_dir,
        "create_mode": "app_state",
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

    Ok(response)
}

fn stream_provider_session_events_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
    generation: Arc<AtomicU64>,
    my_generation: u64,
    channel: Channel<ProviderSessionStreamEvent>,
) {
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    let provider_id = provider_id.to_string();
    let session_id = session_id.to_string();
    let workspace_dir = workspace_dir
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string);

    tauri::async_runtime::spawn_blocking(move || {
        while generation.load(Ordering::SeqCst) == my_generation {
            let socket = match UnixStream::connect(&socket_path) {
                Ok(socket) => socket,
                Err(error) => {
                    let _ = channel.send(ProviderSessionStreamEvent {
                        kind: "error".to_string(),
                        semantic_kind: None,
                        turn: None,
                        reason: None,
                        error: Some(format!("connect provider owner bridge failed: {error}")),
                    });
                    std::thread::sleep(std::time::Duration::from_millis(500));
                    continue;
                }
            };
            let _ = socket.set_read_timeout(Some(std::time::Duration::from_secs(1)));
            let _ = socket.set_write_timeout(Some(std::time::Duration::from_secs(1)));
            let mut writer = match socket.try_clone() {
                Ok(cloned) => cloned,
                Err(error) => {
                    let _ = channel.send(ProviderSessionStreamEvent {
                        kind: "error".to_string(),
                        semantic_kind: None,
                        turn: None,
                        reason: None,
                        error: Some(format!(
                            "clone provider owner bridge socket failed: {error}"
                        )),
                    });
                    std::thread::sleep(std::time::Duration::from_millis(500));
                    continue;
                }
            };
            let mut payload = serde_json::json!({
                "type": "session_event_stream",
                "provider_id": provider_id,
                "session_id": session_id,
            });
            if let Some(workspace_dir) = workspace_dir.as_deref() {
                payload["workspace_dir"] = Value::String(workspace_dir.to_string());
            }
            let raw_request = format!("{}\n", payload);
            if let Err(error) = writer.write_all(raw_request.as_bytes()) {
                let _ = channel.send(ProviderSessionStreamEvent {
                    kind: "error".to_string(),
                    semantic_kind: None,
                    turn: None,
                    reason: None,
                    error: Some(format!(
                        "write provider owner bridge stream request failed: {error}"
                    )),
                });
                std::thread::sleep(std::time::Duration::from_millis(500));
                continue;
            }
            if let Err(error) = writer.flush() {
                let _ = channel.send(ProviderSessionStreamEvent {
                    kind: "error".to_string(),
                    semantic_kind: None,
                    turn: None,
                    reason: None,
                    error: Some(format!(
                        "flush provider owner bridge stream request failed: {error}"
                    )),
                });
                std::thread::sleep(std::time::Duration::from_millis(500));
                continue;
            }

            let mut reader = BufReader::new(socket);
            while generation.load(Ordering::SeqCst) == my_generation {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => break,
                    Ok(_) => {
                        match serde_json::from_str::<ProviderSessionStreamEvent>(line.trim()) {
                            Ok(event) => {
                                let is_fatal_error = event.kind == "error";
                                let _ = channel.send(event);
                                if is_fatal_error {
                                    break;
                                }
                            }
                            Err(error) => {
                                let _ = channel.send(ProviderSessionStreamEvent {
                                    kind: "error".to_string(),
                                    semantic_kind: None,
                                    turn: None,
                                    reason: None,
                                    error: Some(format!(
                                    "parse provider owner bridge session stream failed: {error}"
                                )),
                                });
                                break;
                            }
                        }
                    }
                    Err(error)
                        if matches!(
                            error.kind(),
                            std::io::ErrorKind::WouldBlock
                                | std::io::ErrorKind::TimedOut
                                | std::io::ErrorKind::Interrupted
                        ) =>
                    {
                        continue;
                    }
                    Err(error) => {
                        let _ = channel.send(ProviderSessionStreamEvent {
                            kind: "error".to_string(),
                            semantic_kind: None,
                            turn: None,
                            reason: None,
                            error: Some(format!(
                                "read provider owner bridge session stream failed: {error}"
                            )),
                        });
                        break;
                    }
                }
            }

            if generation.load(Ordering::SeqCst) == my_generation {
                std::thread::sleep(std::time::Duration::from_millis(500));
            }
        }
    });
}

fn owner_bridge_archive_error_allows_sidecar(error: &str) -> bool {
    let lowered = error.to_ascii_lowercase();
    lowered.contains("provider owner bridge not ready")
        || lowered.contains("connect provider owner bridge failed")
        || lowered.contains("write provider owner bridge request failed")
        || lowered.contains("shutdown provider owner bridge write failed")
        || lowered.contains("read provider owner bridge response failed")
        || lowered.contains("parse provider owner bridge response failed")
}

fn owner_bridge_archive_error_allows_local_overlay(error: &str) -> bool {
    let lowered = error.to_ascii_lowercase();
    lowered.contains("does not expose a real source archive operation")
        || error.contains("不支持真实归档")
}

fn local_overlay_archive_result(
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
) -> Result<Value, String> {
    let workspace_dir = workspace_dir
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(
            "Provider 不支持真实归档，且缺少 workspace_dir，无法创建本地归档覆盖层".to_string(),
        )?;
    Ok(serde_json::json!({
        "ok": true,
        "provider_id": provider_id,
        "thread_id": session_id,
        "workspace_id": format!("{provider_id}:{workspace_dir}"),
        "workspace_dir": workspace_dir,
        "archive_mode": "local_overlay",
    }))
}

fn owner_bridge_list_error_allows_sidecar(error: &str) -> bool {
    let lowered = error.to_ascii_lowercase();
    lowered.contains("provider owner bridge not ready")
        || lowered.contains("connect provider owner bridge failed")
}

fn send_provider_session_message_via_owner_bridge_with_retry(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    text: &str,
    attachments: &[ComposerAttachment],
    workspace_dir: Option<&str>,
    timeout: std::time::Duration,
) -> Result<Value, String> {
    let started_at = std::time::Instant::now();
    let poll_interval = std::time::Duration::from_millis(100);
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    let mut last_error = format!("provider owner bridge not ready: {}", socket_path.display());

    loop {
        match send_provider_session_message_via_owner_bridge(
            data_dir,
            provider_id,
            session_id,
            text,
            attachments,
            workspace_dir,
        ) {
            Ok(Some(response)) => return Ok(response),
            Ok(None) => {
                last_error = format!("provider owner bridge not ready: {}", socket_path.display());
            }
            Err(error) => {
                last_error = error;
            }
        }

        if started_at.elapsed() >= timeout {
            return Err(last_error);
        }

        std::thread::sleep(poll_interval);
    }
}

async fn run_provider_session_bridge(
    app: &AppHandle,
    provider_id: &str,
    operation: &str,
    session_id: Option<&str>,
    workspace_dir: Option<&str>,
    timeout: Option<std::time::Duration>,
) -> Result<Value, String> {
    let data_dir = ensure_data_dir()?;
    let mut args = vec![
        "--data-dir".to_string(),
        data_dir.to_string_lossy().to_string(),
        "--provider-session-bridge".to_string(),
        "--provider-id".to_string(),
        provider_id.to_string(),
        "--provider-session-op".to_string(),
        operation.to_string(),
        "--provider-limit".to_string(),
        if operation == "list" { "100" } else { "50" }.to_string(),
    ];

    if let Some(session_id) = session_id {
        args.push("--provider-session-id".to_string());
        args.push(session_id.to_string());
    }
    if let Some(workspace_dir) = workspace_dir.filter(|value| !value.trim().is_empty()) {
        args.push("--provider-workspace-dir".to_string());
        args.push(workspace_dir.to_string());
    }

    let output = run_provider_bridge_sidecar(
        app,
        args,
        provider_bridge_env(&data_dir),
        timeout,
        "provider session bridge",
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
        .map_err(|error| format!("provider session bridge returned invalid JSON: {}", error))
}

async fn run_provider_session_archive_bridge(
    app: &AppHandle,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
) -> Result<Value, String> {
    run_provider_session_bridge(
        app,
        provider_id,
        "archive",
        Some(session_id),
        workspace_dir,
        None,
    )
    .await
}

fn session_state_path(data_dir: &Path) -> std::path::PathBuf {
    data_dir.join("onlineworker_state.json")
}

fn state_workspace_key(provider_id: &str, workspace_dir: &str) -> String {
    format!("{provider_id}:{workspace_dir}")
}

fn workspace_name_from_path(workspace_dir: &str) -> String {
    Path::new(workspace_dir)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(workspace_dir)
        .to_string()
}

fn overlay_provider_sessions(data_dir: &Path, provider_id: &str, sessions: Value) -> Value {
    let mut rows = match sessions {
        Value::Array(rows) => rows,
        other => return other,
    };
    let overlays = load_local_thread_overlays(&session_state_path(data_dir), provider_id);
    if overlays.is_empty() {
        return Value::Array(rows);
    }

    for row in rows.iter_mut() {
        let Some(object) = row.as_object_mut() else {
            continue;
        };
        let session_id = object
            .get("id")
            .or_else(|| object.get("sessionId"))
            .or_else(|| object.get("thread_id"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        if session_id.is_empty() {
            continue;
        }
        if let Some(overlay) = overlays.get(&session_id) {
            object.insert("archived".to_string(), Value::Bool(overlay.archived));
            if !overlay.workspace_path.is_empty() {
                object.insert(
                    "workspace".to_string(),
                    Value::String(overlay.workspace_path.clone()),
                );
            }
            if let Some(preview) = &overlay.preview {
                object.insert("title".to_string(), Value::String(preview.clone()));
                object
                    .entry("preview".to_string())
                    .or_insert_with(|| Value::String(preview.clone()));
            }
        }
    }

    let existing_ids = rows
        .iter()
        .filter_map(|row| {
            row.get("id")
                .or_else(|| row.get("sessionId"))
                .or_else(|| row.get("thread_id"))
                .and_then(Value::as_str)
                .map(ToOwned::to_owned)
        })
        .collect::<std::collections::BTreeSet<_>>();
    for (session_id, overlay) in overlays {
        if !overlay.archived || existing_ids.contains(&session_id) {
            continue;
        }
        rows.push(serde_json::json!({
            "id": session_id,
            "title": overlay.preview.unwrap_or_else(|| session_id.clone()),
            "workspace": overlay.workspace_path,
            "archived": true,
            "updatedAt": 0,
            "createdAt": 0,
        }));
    }

    Value::Array(rows)
}

pub(crate) async fn load_provider_sessions_with_overlays(
    app: &AppHandle,
    provider_id: &str,
    force_refresh: bool,
) -> Result<Value, String> {
    let provider = require_runtime_provider(provider_id)?;
    match provider_session_list_access(&provider).as_str() {
        "owner_bridge" | "sidecar" => {
            let data_dir = ensure_data_dir()?;
            let bridge_data_dir = data_dir.clone();
            let bridge_provider_id = provider.id.clone();
            let sessions = match run_owner_bridge_blocking("list provider sessions", move || {
                list_provider_sessions_via_owner_bridge(
                    &bridge_data_dir,
                    &bridge_provider_id,
                    100,
                    force_refresh,
                )
            })
            .await
            {
                Ok(value) => Ok(value),
                Err(error) => {
                    if owner_bridge_list_error_allows_sidecar(&error) {
                        run_provider_session_bridge(
                            app,
                            &provider.id,
                            "list",
                            None,
                            None,
                            Some(PROVIDER_SESSION_BRIDGE_LIST_TIMEOUT),
                        )
                        .await
                    } else {
                        Err(error)
                    }
                }
            }?;
            Ok(overlay_provider_sessions(&data_dir, &provider.id, sessions))
        }
        other => Err(format!(
            "Provider '{}' has unsupported session list access '{}'",
            provider.id, other
        )),
    }
}

pub(crate) async fn load_provider_session(
    app: &AppHandle,
    provider_id: &str,
    session_id: &str,
    workspace_dir: Option<&str>,
    limit: usize,
) -> Result<Value, String> {
    let provider = require_runtime_provider(provider_id)?;
    match provider_session_read_access(&provider).as_str() {
        "owner_bridge" | "sidecar" => {
            let data_dir = ensure_data_dir()?;
            let bridge_data_dir = data_dir.clone();
            let bridge_provider_id = provider.id.clone();
            let bridge_session_id = session_id.to_string();
            let bridge_workspace_dir = workspace_dir.map(str::to_string);
            match run_owner_bridge_blocking("read provider session", move || {
                read_provider_session_via_owner_bridge(
                    &bridge_data_dir,
                    &bridge_provider_id,
                    &bridge_session_id,
                    bridge_workspace_dir.as_deref(),
                    limit,
                )
            })
            .await
            {
                Ok(value) => Ok(value),
                Err(_) => {
                    run_provider_session_bridge(
                        app,
                        &provider.id,
                        "read",
                        Some(session_id),
                        workspace_dir,
                        Some(PROVIDER_SESSION_BRIDGE_READ_TIMEOUT),
                    )
                    .await
                }
            }
        }
        other => Err(format!(
            "Provider '{}' has unsupported session read access '{}'",
            provider.id, other
        )),
    }
}

fn persist_provider_session_archived_state(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    workspace_dir: &str,
    preview: Option<&str>,
) -> Result<(), String> {
    let state_path = session_state_path(data_dir);
    let mut state = match std::fs::read_to_string(&state_path) {
        Ok(raw) => serde_json::from_str::<Value>(&raw)
            .map_err(|e| format!("parse onlineworker_state.json failed: {e}"))?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => serde_json::json!({}),
        Err(error) => return Err(format!("read onlineworker_state.json failed: {error}")),
    };

    if !state.is_object() {
        state = serde_json::json!({});
    }
    let root = state
        .as_object_mut()
        .ok_or("onlineworker_state root must be an object".to_string())?;
    let workspaces = root
        .entry("workspaces".to_string())
        .or_insert_with(|| Value::Object(Default::default()));
    if !workspaces.is_object() {
        *workspaces = Value::Object(Default::default());
    }
    let workspaces = workspaces
        .as_object_mut()
        .ok_or("onlineworker_state.workspaces must be an object".to_string())?;

    let canonical_workspace_key = state_workspace_key(provider_id, workspace_dir);
    let matches_provider = |key: &str, workspace: &Value| {
        workspace.get("tool").and_then(Value::as_str) == Some(provider_id)
            || key.starts_with(&format!("{provider_id}:"))
    };
    let contains_session = |workspace: &Value| {
        workspace
            .get("threads")
            .and_then(Value::as_object)
            .is_some_and(|threads| threads.contains_key(session_id))
    };
    let contains_real_session = |workspace: &Value| {
        workspace
            .get("threads")
            .and_then(Value::as_object)
            .and_then(|threads| threads.get(session_id))
            .and_then(|thread| thread.get("source"))
            .and_then(Value::as_str)
            .is_some_and(|source| source != "app")
    };
    let matches_path =
        |workspace: &Value| workspace.get("path").and_then(Value::as_str) == Some(workspace_dir);
    let workspace_key = workspaces
        .iter()
        .find(|(key, workspace)| {
            matches_provider(key, workspace)
                && contains_session(workspace)
                && contains_real_session(workspace)
        })
        .or_else(|| {
            workspaces.iter().find(|(key, workspace)| {
                matches_provider(key, workspace) && contains_session(workspace)
            })
        })
        .or_else(|| {
            workspaces.iter().find(|(key, workspace)| {
                matches_provider(key, workspace) && matches_path(workspace)
            })
        })
        .map(|(key, _)| key.clone())
        .unwrap_or(canonical_workspace_key);
    let workspace = workspaces.entry(workspace_key.clone()).or_insert_with(|| {
        serde_json::json!({
            "name": workspace_name_from_path(workspace_dir),
            "path": workspace_dir,
            "tool": provider_id,
            "topic_id": null,
            "daemon_workspace_id": workspace_key,
            "threads": {}
        })
    });
    if !workspace.is_object() {
        *workspace = serde_json::json!({});
    }
    let workspace = workspace
        .as_object_mut()
        .ok_or("workspace state must be an object".to_string())?;
    workspace
        .entry("name".to_string())
        .or_insert_with(|| Value::String(workspace_name_from_path(workspace_dir)));
    workspace
        .entry("path".to_string())
        .or_insert_with(|| Value::String(workspace_dir.to_string()));
    workspace
        .entry("tool".to_string())
        .or_insert_with(|| Value::String(provider_id.to_string()));
    workspace
        .entry("daemon_workspace_id".to_string())
        .or_insert_with(|| Value::String(workspace_key));
    let threads = workspace
        .entry("threads".to_string())
        .or_insert_with(|| Value::Object(Default::default()));
    if !threads.is_object() {
        *threads = Value::Object(Default::default());
    }
    let threads = threads
        .as_object_mut()
        .ok_or("workspace threads must be an object".to_string())?;
    let thread = threads.entry(session_id.to_string()).or_insert_with(|| {
        serde_json::json!({
            "thread_id": session_id,
            "topic_id": null,
            "preview": null,
            "archived": false,
            "streaming_msg_id": null,
            "last_tg_user_message_id": null,
            "history_sync_cursor": null,
            "is_active": false,
            "source": "app"
        })
    });
    if !thread.is_object() {
        *thread = Value::Object(Default::default());
    }
    let thread = thread
        .as_object_mut()
        .ok_or("thread state must be an object".to_string())?;
    thread.insert(
        "thread_id".to_string(),
        Value::String(session_id.to_string()),
    );
    thread.insert("archived".to_string(), Value::Bool(true));
    thread.insert("is_active".to_string(), Value::Bool(false));
    if let Some(preview) = preview.map(str::trim).filter(|value| !value.is_empty()) {
        thread.insert("preview".to_string(), Value::String(preview.to_string()));
    }
    thread
        .entry("source".to_string())
        .or_insert_with(|| Value::String("app".to_string()));

    std::fs::create_dir_all(data_dir).map_err(|e| format!("create data dir failed: {e}"))?;
    let mut sorted = BTreeMap::new();
    if let Some(object) = state.as_object() {
        for (key, value) in object {
            sorted.insert(key.clone(), value.clone());
        }
    }
    let payload = serde_json::to_string_pretty(&Value::Object(sorted.into_iter().collect()))
        .map_err(|e| format!("serialize onlineworker_state failed: {e}"))?;
    let tmp_path = state_path.with_extension("json.tmp");
    std::fs::write(&tmp_path, payload)
        .map_err(|e| format!("write onlineworker_state tmp failed: {e}"))?;
    std::fs::rename(&tmp_path, &state_path)
        .map_err(|e| format!("replace onlineworker_state failed: {e}"))?;
    Ok(())
}

#[tauri::command]
pub async fn list_provider_sessions(
    app: AppHandle,
    provider_id: String,
    force_refresh: Option<bool>,
) -> Result<Value, String> {
    load_provider_sessions_with_overlays(&app, &provider_id, force_refresh.unwrap_or(false)).await
}

#[tauri::command]
pub async fn read_provider_session(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    workspace_dir: Option<String>,
) -> Result<Value, String> {
    load_provider_session(
        &app,
        &provider_id,
        &session_id,
        workspace_dir.as_deref(),
        20,
    )
    .await
}

#[tauri::command]
pub async fn create_provider_session(
    provider_id: String,
    workspace_dir: String,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    let normalized_workspace_dir = workspace_dir.trim().to_string();
    if normalized_workspace_dir.is_empty() {
        return Err("workspace_dir is required".to_string());
    }
    let data_dir = ensure_data_dir()?;
    run_owner_bridge_blocking("create provider session", move || {
        create_provider_session_via_owner_bridge(&data_dir, &provider.id, &normalized_workspace_dir)
    })
    .await
}

#[tauri::command]
pub async fn send_provider_session_message(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    text: String,
    attachments: Option<Vec<ComposerAttachment>>,
    workspace_dir: Option<String>,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    let attachments = attachments.unwrap_or_default();
    match provider_session_send_access(&provider).as_str() {
        "owner_bridge" => {
            let _ = app;
            let data_dir = ensure_data_dir()?;
            let trimmed = text.trim().to_string();
            if trimmed.is_empty() && attachments.is_empty() {
                return Err("message is empty".to_string());
            }
            run_owner_bridge_blocking("send provider session message", move || {
                send_provider_session_message_via_owner_bridge_with_retry(
                    &data_dir,
                    &provider.id,
                    &session_id,
                    &trimmed,
                    &attachments,
                    workspace_dir.as_deref(),
                    std::time::Duration::from_secs(8),
                )
            })
            .await
        }
        "none" | "unsupported" => Err(format!(
            "Provider '{}' has no session send implementation",
            provider.id
        )),
        _ => Err(format!(
            "Provider '{}' has unsupported session send access '{}'",
            provider.id,
            provider_session_send_access(&provider)
        )),
    }
}

#[tauri::command]
pub async fn start_provider_session_message(
    provider_id: String,
    workspace_dir: String,
    text: String,
    attachments: Option<Vec<ComposerAttachment>>,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    let attachments = attachments.unwrap_or_default();
    let normalized_workspace_dir = workspace_dir.trim().to_string();
    let trimmed = text.trim().to_string();
    if normalized_workspace_dir.is_empty() {
        return Err("workspace_dir is required".to_string());
    }
    if trimmed.is_empty() && attachments.is_empty() {
        return Err("message is empty".to_string());
    }
    match provider_session_send_access(&provider).as_str() {
        "owner_bridge" => {
            let data_dir = ensure_data_dir()?;
            run_owner_bridge_blocking("start provider session message", move || {
                start_provider_session_message_via_owner_bridge(
                    &data_dir,
                    &provider.id,
                    &normalized_workspace_dir,
                    &trimmed,
                    &attachments,
                )
            })
            .await
        }
        "none" | "unsupported" => Err(format!(
            "Provider '{}' has no session send implementation",
            provider.id
        )),
        _ => Err(format!(
            "Provider '{}' has unsupported session send access '{}'",
            provider.id,
            provider_session_send_access(&provider)
        )),
    }
}

#[tauri::command]
pub async fn archive_provider_session(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    workspace_dir: Option<String>,
    session_title: Option<String>,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    let normalized_session_id = session_id.trim().to_string();
    if normalized_session_id.is_empty() {
        return Err("session_id is required".to_string());
    }
    let normalized_workspace_dir = workspace_dir
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned);
    let data_dir = ensure_data_dir()?;

    let bridge_data_dir = data_dir.clone();
    let bridge_provider_id = provider.id.clone();
    let bridge_session_id = normalized_session_id.clone();
    let bridge_workspace_dir = normalized_workspace_dir.clone();
    let owner_archive = run_owner_bridge_blocking("archive provider session", move || {
        archive_provider_session_via_owner_bridge(
            &bridge_data_dir,
            &bridge_provider_id,
            &bridge_session_id,
            bridge_workspace_dir.as_deref(),
        )
    })
    .await;

    let (result, archive_mode) = match owner_archive {
        Ok(value) => Ok((value, "provider")),
        Err(owner_error) if owner_bridge_archive_error_allows_local_overlay(&owner_error) => {
            local_overlay_archive_result(
                &provider.id,
                &normalized_session_id,
                normalized_workspace_dir.as_deref(),
            )
            .map(|value| (value, "local_overlay"))
        }
        Err(owner_error) => {
            if !owner_bridge_archive_error_allows_sidecar(&owner_error) {
                return Err(owner_error);
            }
            match run_provider_session_archive_bridge(
                &app,
                &provider.id,
                &normalized_session_id,
                normalized_workspace_dir.as_deref(),
            )
            .await
            {
                Ok(value) => Ok((value, "provider_sidecar")),
                Err(sidecar_error)
                    if owner_bridge_archive_error_allows_local_overlay(&sidecar_error) =>
                {
                    local_overlay_archive_result(
                        &provider.id,
                        &normalized_session_id,
                        normalized_workspace_dir.as_deref(),
                    )
                    .map(|value| (value, "local_overlay"))
                }
                Err(sidecar_error) => Err(format!(
                    "真实归档失败: owner bridge: {owner_error}; sidecar: {sidecar_error}"
                )),
            }
        }
    }?;

    let workspace_for_state = normalized_workspace_dir
        .or_else(|| {
            result
                .get("workspace_dir")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .or_else(|| {
            result
                .get("workspaceId")
                .or_else(|| result.get("workspace_id"))
                .and_then(Value::as_str)
                .and_then(|workspace_id| {
                    workspace_id
                        .split_once(':')
                        .map(|(_, path)| path.to_string())
                })
        })
        .ok_or("真实归档成功，但缺少 workspace_dir，无法更新本地归档状态".to_string())?;

    persist_provider_session_archived_state(
        &data_dir,
        &provider.id,
        &normalized_session_id,
        &workspace_for_state,
        session_title.as_deref(),
    )?;

    Ok(serde_json::json!({
        "ok": true,
        "providerId": provider.id,
        "sessionId": normalized_session_id,
        "workspaceDir": workspace_for_state,
        "archiveMode": archive_mode,
    }))
}

#[tauri::command]
pub async fn stage_session_composer_attachments(
    files: Vec<StagedComposerAttachmentInput>,
) -> Result<Vec<ComposerAttachment>, String> {
    let data_dir = ensure_data_dir()?;
    let staging_dir = composer_attachment_staging_dir(&data_dir);
    std::fs::create_dir_all(&staging_dir)
        .map_err(|e| format!("create composer attachment dir failed: {e}"))?;

    let mut staged = Vec::new();
    for file in files {
        let raw_name = file
            .name
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .or_else(|| {
                std::path::Path::new(&file.path)
                    .file_name()
                    .and_then(|value| value.to_str())
            })
            .unwrap_or("attachment.bin")
            .to_string();
        let safe_name = raw_name
            .chars()
            .map(|ch| if ch == '/' || ch == '\\' { '_' } else { ch })
            .collect::<String>();
        let attachment_id = uuid::Uuid::new_v4().to_string();
        let target_path = staging_dir.join(format!("{attachment_id}-{safe_name}"));

        if let Some(base64_data) = file
            .base64_data
            .as_deref()
            .filter(|value| !value.trim().is_empty())
        {
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(base64_data.trim())
                .map_err(|e| format!("decode attachment base64 failed: {e}"))?;
            std::fs::write(&target_path, &bytes)
                .map_err(|e| format!("write staged attachment failed: {e}"))?;
        } else {
            std::fs::copy(&file.path, &target_path)
                .map_err(|e| format!("copy staged attachment failed: {e}"))?;
        }

        let metadata = std::fs::metadata(&target_path)
            .map_err(|e| format!("stat staged attachment failed: {e}"))?;
        let mime_type = file
            .mime_type
            .clone()
            .filter(|value| !value.trim().is_empty());
        staged.push(ComposerAttachment {
            id: attachment_id,
            kind: infer_attachment_kind(&safe_name, mime_type.as_deref()),
            name: raw_name,
            mime_type,
            size_bytes: file.size_bytes.unwrap_or(metadata.len()),
            path: target_path.to_string_lossy().to_string(),
        });
    }

    Ok(staged)
}

#[tauri::command]
pub async fn start_provider_session_event_stream(
    provider_id: String,
    session_id: String,
    workspace_dir: Option<String>,
    channel: Channel<ProviderSessionStreamEvent>,
) -> Result<(), String> {
    let _provider = require_runtime_provider(&provider_id)?;
    let generation = provider_session_stream_generation();
    let my_generation = generation.fetch_add(1, Ordering::SeqCst) + 1;
    let data_dir = ensure_data_dir()?;
    stream_provider_session_events_via_owner_bridge(
        &data_dir,
        &provider_id,
        &session_id,
        workspace_dir.as_deref(),
        generation,
        my_generation,
        channel,
    );
    Ok(())
}

#[tauri::command]
pub async fn stop_provider_session_event_stream() -> Result<(), String> {
    provider_session_stream_generation().fetch_add(1, Ordering::SeqCst);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        archive_provider_session_via_owner_bridge, create_provider_session_via_owner_bridge,
        list_provider_sessions_via_owner_bridge_with_timeout,
        owner_bridge_archive_error_allows_local_overlay, owner_bridge_archive_error_allows_sidecar,
        owner_bridge_list_error_allows_sidecar, persist_provider_session_archived_state,
        provider_session_list_access, provider_session_read_access, provider_session_send_access,
        send_provider_session_message_via_owner_bridge,
        send_provider_session_message_via_owner_bridge_with_retry,
        start_provider_session_message_via_owner_bridge, ComposerAttachment,
    };
    use crate::commands::config_provider::{
        provider_metadata_from_raw, public_default_provider_ids,
    };
    use crate::commands::provider_bridge_common::{
        provider_bridge_env, provider_bridge_path, provider_not_enabled_message,
        provider_owner_bridge_socket_path, PROVIDER_OVERLAY_ENV,
    };
    use std::fs;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::sync::Mutex;
    use std::thread;
    use std::time::Duration;

    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn provider_session_routes_are_declared_by_manifest_capabilities() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let public_provider_ids = public_default_provider_ids();

        for provider_id in public_provider_ids {
            let provider = providers
                .iter()
                .find(|provider| provider.id == provider_id)
                .expect("public provider");
            assert_eq!(provider_session_list_access(provider), "owner_bridge");
            assert_eq!(provider_session_read_access(provider), "owner_bridge");
            assert_eq!(provider_session_send_access(provider), "owner_bridge");
        }
    }

    #[test]
    fn provider_session_routes_accept_legacy_config_access_tokens() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        let mut codex = providers
            .iter()
            .find(|provider| provider.id == "codex")
            .expect("codex provider")
            .clone();
        codex.capabilities.session_access.list = "codex_threads".to_string();
        codex.capabilities.session_access.read = "codex_thread_jsonl".to_string();
        codex.capabilities.session_access.send = "codex_app_server".to_string();
        assert_eq!(provider_session_list_access(&codex), "owner_bridge");
        assert_eq!(provider_session_read_access(&codex), "owner_bridge");
        assert_eq!(provider_session_send_access(&codex), "owner_bridge");

        let mut claude = providers
            .iter()
            .find(|provider| provider.id == "claude")
            .expect("claude provider")
            .clone();
        claude.capabilities.session_access.list = "claude_projects".to_string();
        claude.capabilities.session_access.read = "claude_project".to_string();
        assert_eq!(provider_session_list_access(&claude), "owner_bridge");
        assert_eq!(provider_session_read_access(&claude), "owner_bridge");
        assert_eq!(provider_session_send_access(&claude), "owner_bridge");
    }

    #[test]
    fn disabled_overlay_message_uses_provider_not_enabled_prefix() {
        let providers = provider_metadata_from_raw("", None).expect("metadata");
        assert!(!providers
            .iter()
            .any(|provider| provider.id == "overlay-tool"));
        assert_eq!(
            provider_not_enabled_message("overlay-tool"),
            "Provider 'overlay-tool' is not enabled"
        );
    }

    #[test]
    fn provider_session_bridge_path_prefers_local_bins() {
        let path = provider_bridge_path("/Users/test");
        assert_eq!(
            path,
            "/Users/test/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        );
    }

    #[test]
    fn provider_session_bridge_env_includes_overlay_from_process_env() {
        let _guard = ENV_LOCK.lock().expect("lock env");
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-session-env-process-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create data dir");
        std::env::set_var(PROVIDER_OVERLAY_ENV, "/tmp/provider-overlay");

        let envs = provider_bridge_env(&dir);
        let overlay = envs
            .iter()
            .find(|(key, _)| key == PROVIDER_OVERLAY_ENV)
            .map(|(_, value)| value.clone());

        assert_eq!(overlay.as_deref(), Some("/tmp/provider-overlay"));

        std::env::remove_var(PROVIDER_OVERLAY_ENV);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn provider_session_bridge_env_resets_pyinstaller_parent_state() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-session-pyi-env-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create data dir");

        let envs = provider_bridge_env(&dir);

        assert!(envs
            .iter()
            .any(|(key, value)| { key == "PYINSTALLER_RESET_ENVIRONMENT" && value == "1" }));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn provider_session_bridge_env_reads_overlay_from_app_env_file() {
        let _guard = ENV_LOCK.lock().expect("lock env");
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-session-env-file-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create data dir");
        std::env::remove_var(PROVIDER_OVERLAY_ENV);
        fs::write(
            dir.join(".env"),
            "ONLINEWORKER_PROVIDER_OVERLAY=/tmp/provider-overlay-from-file\n",
        )
        .expect("write env file");
        std::env::remove_var(PROVIDER_OVERLAY_ENV);

        let envs = provider_bridge_env(&dir);
        let overlay = envs
            .iter()
            .find(|(key, _)| key == PROVIDER_OVERLAY_ENV)
            .map(|(_, value)| value.clone());

        assert_eq!(overlay.as_deref(), Some("/tmp/provider-overlay-from-file"));

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn send_provider_session_message_uses_owner_bridge_when_socket_exists() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pob-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["thread_id"], "tid-1");
            assert_eq!(payload["text"], "hello");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");
            assert_eq!(payload["attachments"][0]["kind"], "image");
            assert_eq!(
                payload["attachments"][0]["path"],
                "/tmp/workspace/image.png"
            );

            let response = serde_json::json!({ "ok": true, "accepted": true });
            writeln!(stream, "{response}").expect("write response");
        });

        let attachments = vec![ComposerAttachment {
            id: "att-1".to_string(),
            kind: "image".to_string(),
            name: "image.png".to_string(),
            mime_type: Some("image/png".to_string()),
            size_bytes: 128,
            path: "/tmp/workspace/image.png".to_string(),
        }];

        let used_bridge = send_provider_session_message_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            "tid-1",
            "hello",
            &attachments,
            Some("/tmp/workspace"),
        )
        .expect("send via owner bridge");

        assert_eq!(
            used_bridge,
            Some(serde_json::json!({ "ok": true, "accepted": true }))
        );
        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn start_provider_session_message_uses_owner_bridge_payload() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pob-start-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "start_session_message");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");
            assert_eq!(payload["text"], "hello");
            assert_eq!(payload["attachments"][0]["kind"], "file");

            let response = serde_json::json!({
                "ok": true,
                "accepted": true,
                "thread_id": "tid-new",
                "created_new_thread": true
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let attachments = vec![ComposerAttachment {
            id: "att-1".to_string(),
            kind: "file".to_string(),
            name: "notes.txt".to_string(),
            mime_type: Some("text/plain".to_string()),
            size_bytes: 128,
            path: "/tmp/workspace/notes.txt".to_string(),
        }];

        let response = start_provider_session_message_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            "/tmp/workspace",
            "hello",
            &attachments,
        )
        .expect("start session via owner bridge");

        assert_eq!(response["thread_id"], "tid-new");
        assert_eq!(response["created_new_thread"], true);
        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_can_create_provider_session_payload() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pob-create-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "create_session");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");
            assert_eq!(payload["create_mode"], "app_state");

            let response = serde_json::json!({
                "ok": true,
                "thread_id": "tid-new",
                "session": {
                    "id": "tid-new",
                    "workspace": "/tmp/workspace",
                    "title": "tid-new",
                    "archived": false
                }
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let result =
            create_provider_session_via_owner_bridge(&temp_dir, "overlay-tool", "/tmp/workspace")
                .expect("create via owner bridge");

        assert_eq!(result["thread_id"], "tid-new");
        assert_eq!(result["session"]["id"], "tid-new");
        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn send_provider_session_message_waits_for_owner_bridge_socket() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pobr-{}", std::process::id()));
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = provider_owner_bridge_socket_path(&temp_dir);
        let socket_path_for_server = socket_path.clone();

        let server = thread::spawn(move || {
            thread::sleep(Duration::from_millis(150));
            let listener =
                UnixListener::bind(&socket_path_for_server).expect("bind owner bridge socket");
            let (mut stream, _) = listener.accept().expect("accept owner bridge socket");
            let mut request = String::new();
            let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
            reader
                .read_line(&mut request)
                .expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["provider_id"], "overlay-tool");
            let response = serde_json::json!({ "ok": true, "accepted": true });
            writeln!(stream, "{response}").expect("write response");
        });

        let response = send_provider_session_message_via_owner_bridge_with_retry(
            &temp_dir,
            "overlay-tool",
            "tid-1",
            "hello",
            &[],
            Some("/tmp/workspace"),
            Duration::from_secs(2),
        )
        .expect("owner bridge should become ready within timeout");

        assert_eq!(
            response,
            serde_json::json!({ "ok": true, "accepted": true })
        );
        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_can_read_provider_session_payload() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pobr-read-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "read_session");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["session_id"], "tid-9");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");
            assert_eq!(payload["limit"], 20);

            let response = serde_json::json!({
                "ok": true,
                "session": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "world"},
                ],
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let result = super::read_provider_session_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            "tid-9",
            Some("/tmp/workspace"),
            20,
        )
        .expect("read via owner bridge");

        assert_eq!(
            result,
            serde_json::json!([
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ])
        );

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_can_list_provider_sessions_payload() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pobr-list-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "list_sessions");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["limit"], 100);
            assert_eq!(payload["force_refresh"], false);

            let response = serde_json::json!({
                "ok": true,
                "sessions": [
                    {
                        "id": "tid-2",
                        "title": "Beta",
                        "workspace": "/tmp/beta",
                        "archived": false,
                        "updatedAt": 20,
                        "createdAt": 20
                    }
                ],
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let result =
            super::list_provider_sessions_via_owner_bridge(&temp_dir, "overlay-tool", 100, false)
                .expect("list via owner bridge");

        assert_eq!(
            result,
            serde_json::json!([
                {
                    "id": "tid-2",
                    "title": "Beta",
                    "workspace": "/tmp/beta",
                    "archived": false,
                    "updatedAt": 20,
                    "createdAt": 20
                }
            ])
        );

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_list_provider_sessions_force_refresh_payload() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-pobr-list-force-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "list_sessions");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["force_refresh"], true);

            let response = serde_json::json!({ "ok": true, "sessions": [] });
            writeln!(stream, "{response}").expect("write response");
        });

        let result =
            super::list_provider_sessions_via_owner_bridge(&temp_dir, "overlay-tool", 100, true)
                .expect("list via owner bridge");

        assert_eq!(result, serde_json::json!([]));
        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_list_provider_sessions_times_out() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-pobr-list-timeout-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let socket_path = provider_owner_bridge_socket_path(&temp_dir);
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
            assert_eq!(payload["type"], "list_sessions");
            thread::sleep(Duration::from_millis(200));
        });

        let error = list_provider_sessions_via_owner_bridge_with_timeout(
            &temp_dir,
            "overlay-tool",
            100,
            false,
            Duration::from_millis(50),
        )
        .expect_err("list should time out");
        assert!(error.contains("read provider owner bridge response failed"));

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_list_errors_only_fall_back_before_owner_is_ready() {
        assert!(owner_bridge_list_error_allows_sidecar(
            "provider owner bridge not ready: /tmp/provider_owner_bridge.sock"
        ));
        assert!(owner_bridge_list_error_allows_sidecar(
            "connect provider owner bridge failed: connection refused"
        ));

        assert!(!owner_bridge_list_error_allows_sidecar(
            "read provider owner bridge response failed: resource temporarily unavailable"
        ));
        assert!(!owner_bridge_list_error_allows_sidecar(
            "parse provider owner bridge response failed: expected value"
        ));
        assert!(!owner_bridge_list_error_allows_sidecar(
            "Provider 'codex' list_sessions failed"
        ));
    }

    #[test]
    fn owner_bridge_can_archive_provider_session_payload() {
        let temp_dir = std::env::temp_dir().join(format!("ow-pobr-archive-{}", std::process::id()));
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
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "archive_session");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["session_id"], "tid-archive");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");

            let response = serde_json::json!({
                "ok": true,
                "provider_id": "overlay-tool",
                "thread_id": "tid-archive",
                "workspace_id": "overlay-tool:/tmp/workspace",
                "workspace_dir": "/tmp/workspace"
            });
            writeln!(stream, "{response}").expect("write response");
        });

        let result = archive_provider_session_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            "tid-archive",
            Some("/tmp/workspace"),
        )
        .expect("archive via owner bridge");

        assert_eq!(
            result,
            serde_json::json!({
                "ok": true,
                "provider_id": "overlay-tool",
                "thread_id": "tid-archive",
                "workspace_id": "overlay-tool:/tmp/workspace",
                "workspace_dir": "/tmp/workspace"
            })
        );

        server.join().expect("join owner bridge server");
        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn owner_bridge_archive_errors_only_fall_back_for_transport_failures() {
        assert!(owner_bridge_archive_error_allows_sidecar(
            "provider owner bridge not ready: /tmp/provider_owner_bridge.sock"
        ));
        assert!(owner_bridge_archive_error_allows_sidecar(
            "connect provider owner bridge failed: connection refused"
        ));
        assert!(owner_bridge_archive_error_allows_sidecar(
            "read provider owner bridge response failed: early eof"
        ));

        assert!(!owner_bridge_archive_error_allows_sidecar(
            "Provider 'secondary' 不支持真实归档"
        ));
        assert!(!owner_bridge_archive_error_allows_sidecar(
            "source archive failed"
        ));
    }

    #[test]
    fn explicit_unsupported_archive_errors_allow_reversible_local_overlay() {
        assert!(owner_bridge_archive_error_allows_local_overlay(
            "Claude provider does not expose a real source archive operation yet."
        ));
        assert!(owner_bridge_archive_error_allows_local_overlay(
            "Provider 'secondary' 不支持真实归档"
        ));

        assert!(!owner_bridge_archive_error_allows_local_overlay(
            "connect provider owner bridge failed: connection refused"
        ));
        assert!(!owner_bridge_archive_error_allows_local_overlay(
            "source archive failed"
        ));
    }

    #[test]
    fn persist_provider_session_archived_state_updates_state_file() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-state-archive-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");

        persist_provider_session_archived_state(
            &temp_dir,
            "overlay-tool",
            "tid-archive",
            "/tmp/workspace",
            Some("Archived title"),
        )
        .expect("persist archived state");

        let raw = fs::read_to_string(temp_dir.join("onlineworker_state.json"))
            .expect("read persisted state");
        let state: serde_json::Value = serde_json::from_str(&raw).expect("parse persisted state");
        let thread = &state["workspaces"]["overlay-tool:/tmp/workspace"]["threads"]["tid-archive"];

        assert_eq!(thread["thread_id"], "tid-archive");
        assert_eq!(thread["archived"], true);
        assert_eq!(thread["is_active"], false);
        assert_eq!(thread["preview"], "Archived title");
        assert_eq!(thread["source"], "app");

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn persist_archive_reuses_existing_workspace_that_contains_the_session() {
        let temp_dir = std::env::temp_dir().join(format!(
            "ow-state-existing-workspace-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        fs::write(
            temp_dir.join("onlineworker_state.json"),
            serde_json::to_string_pretty(&serde_json::json!({
                "workspaces": {
                    "claude:wxy": {
                        "name": "wxy",
                        "path": "/Users/wxy",
                        "tool": "claude",
                        "daemon_workspace_id": "claude:wxy",
                        "threads": {
                            "session-a": {
                                "thread_id": "session-a",
                                "archived": false,
                                "is_active": true,
                                "source": "provider"
                            }
                        }
                    }
                }
            }))
            .expect("serialize state"),
        )
        .expect("write state");

        persist_provider_session_archived_state(
            &temp_dir,
            "claude",
            "session-a",
            "/Users/wxy",
            Some("Archived title"),
        )
        .expect("persist archived state");

        let raw = fs::read_to_string(temp_dir.join("onlineworker_state.json"))
            .expect("read persisted state");
        let state: serde_json::Value = serde_json::from_str(&raw).expect("parse persisted state");
        assert_eq!(
            state["workspaces"]["claude:wxy"]["threads"]["session-a"]["archived"],
            true
        );
        assert!(state["workspaces"].get("claude:/Users/wxy").is_none());

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn overlay_provider_sessions_adds_archived_state_only_rows() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-state-overlay-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");

        persist_provider_session_archived_state(
            &temp_dir,
            "overlay-tool",
            "ses-archived",
            "/tmp/workspace",
            Some("Archived Overlay Session"),
        )
        .expect("persist archived state");

        let result = super::overlay_provider_sessions(
            &temp_dir,
            "overlay-tool",
            serde_json::json!([
                {
                    "id": "ses-active",
                    "title": "Active Overlay Session",
                    "workspace": "/tmp/workspace",
                    "archived": false,
                    "updatedAt": 20,
                    "createdAt": 10
                }
            ]),
        );

        assert_eq!(
            result,
            serde_json::json!([
                {
                    "id": "ses-active",
                    "title": "Active Overlay Session",
                    "workspace": "/tmp/workspace",
                    "archived": false,
                    "updatedAt": 20,
                    "createdAt": 10
                },
                {
                    "id": "ses-archived",
                    "title": "Archived Overlay Session",
                    "workspace": "/tmp/workspace",
                    "archived": true,
                    "updatedAt": 0,
                    "createdAt": 0
                }
            ])
        );

        let _ = fs::remove_dir_all(&temp_dir);
    }

    #[tokio::test(flavor = "current_thread")]
    async fn owner_bridge_blocking_work_does_not_starve_async_runtime() {
        let slow_operation = super::run_owner_bridge_blocking("test", || {
            std::thread::sleep(std::time::Duration::from_millis(120));
            Ok::<_, String>("done")
        });
        tokio::pin!(slow_operation);

        tokio::select! {
            _ = tokio::time::sleep(std::time::Duration::from_millis(20)) => {}
            result = &mut slow_operation => panic!("blocking work completed unexpectedly early: {result:?}"),
        }

        assert_eq!(slow_operation.await.expect("blocking work"), "done");
    }
}
