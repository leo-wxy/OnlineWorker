use serde_json::Value;
use std::io::{BufRead, BufReader, Write};
use std::net::Shutdown;
use std::os::unix::net::UnixStream;
use std::path::Path;
use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, OnceLock,
};
use tauri::ipc::Channel;

use super::claude::{list_claude_sessions, read_claude_session, send_claude_session_message};
use super::codex::{
    list_codex_threads, read_codex_thread, read_codex_thread_updates, send_codex_thread_message,
    CodexThreadCursor,
};
use super::config::read_provider_metadata_from_disk;
use super::config_provider::ProviderMetadata;
use super::config::ensure_data_dir;

static PROVIDER_SESSION_STREAM_GENERATION: OnceLock<Arc<AtomicU64>> = OnceLock::new();
const PROVIDER_OVERLAY_ENV: &str = "ONLINEWORKER_PROVIDER_OVERLAY";

fn provider_session_stream_generation() -> Arc<AtomicU64> {
    PROVIDER_SESSION_STREAM_GENERATION
        .get_or_init(|| Arc::new(AtomicU64::new(0)))
        .clone()
}

fn provider_not_enabled_message(provider_id: &str) -> String {
    format!("Provider '{}' is not enabled", provider_id.trim())
}

fn require_runtime_provider(provider_id: &str) -> Result<ProviderMetadata, String> {
    let normalized = provider_id.trim();
    if normalized.is_empty() {
        return Err(provider_not_enabled_message("unknown"));
    }

    let provider = read_provider_metadata_from_disk()?
        .into_iter()
        .find(|provider| provider.id == normalized)
        .ok_or_else(|| provider_not_enabled_message(normalized))?;

    Ok(provider)
}

fn provider_session_bridge_path(home: &str) -> String {
    format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    )
}

fn provider_session_overlay_env_spec_from_app_env(data_dir: &Path) -> Option<String> {
    let raw = std::fs::read_to_string(data_dir.join(".env")).ok()?;
    raw.lines().find_map(|line| {
        let (line_key, value) = line.split_once('=')?;
        if line_key.trim() != PROVIDER_OVERLAY_ENV {
            return None;
        }
        let trimmed = value.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn provider_session_overlay_env_spec(data_dir: &Path) -> Option<String> {
    std::env::var(PROVIDER_OVERLAY_ENV)
        .ok()
        .and_then(|value| {
            let trimmed = value.trim().to_string();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed)
            }
        })
        .or_else(|| provider_session_overlay_env_spec_from_app_env(data_dir))
}

fn provider_session_bridge_env(data_dir: &Path) -> Vec<(String, String)> {
    let home = std::env::var("HOME").unwrap_or_default();
    let mut envs = vec![
        ("PATH".to_string(), provider_session_bridge_path(&home)),
        ("HOME".to_string(), home),
        ("LANG".to_string(), "en_US.UTF-8".to_string()),
    ];
    if let Some(overlay_env) = provider_session_overlay_env_spec(data_dir) {
        envs.push((PROVIDER_OVERLAY_ENV.to_string(), overlay_env));
    }
    envs
}

fn provider_owner_bridge_socket_path(data_dir: &Path) -> std::path::PathBuf {
    data_dir.join("provider_owner_bridge.sock")
}

fn send_provider_session_message_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    text: &str,
    workspace_dir: Option<&str>,
) -> Result<bool, String> {
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Ok(false);
    }

    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;

    let mut payload = serde_json::json!({
        "type": "send_message",
        "provider_id": provider_id,
        "thread_id": session_id,
        "text": text,
    });
    if let Some(workspace_dir) = workspace_dir.map(str::trim).filter(|value| !value.is_empty()) {
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
        return Ok(true);
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
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    if !socket_path.exists() {
        return Err(format!(
            "provider owner bridge not ready: {}",
            socket_path.display()
        ));
    }

    let mut socket = UnixStream::connect(&socket_path)
        .map_err(|e| format!("connect provider owner bridge failed: {e}"))?;

    let mut payload = serde_json::json!({
        "type": "read_session",
        "provider_id": provider_id,
        "session_id": session_id,
        "limit": limit,
    });
    if let Some(workspace_dir) = workspace_dir.map(str::trim).filter(|value| !value.is_empty()) {
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

    Ok(response.get("session").cloned().unwrap_or(Value::Array(vec![])))
}

fn list_provider_sessions_via_owner_bridge(
    data_dir: &Path,
    provider_id: &str,
    limit: usize,
) -> Result<Value, String> {
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
        "type": "list_sessions",
        "provider_id": provider_id,
        "limit": limit,
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

fn send_provider_session_message_via_owner_bridge_with_retry(
    data_dir: &Path,
    provider_id: &str,
    session_id: &str,
    text: &str,
    workspace_dir: Option<&str>,
    timeout: std::time::Duration,
) -> Result<(), String> {
    let started_at = std::time::Instant::now();
    let poll_interval = std::time::Duration::from_millis(100);
    let socket_path = provider_owner_bridge_socket_path(data_dir);
    let mut last_error = format!(
        "provider owner bridge not ready: {}",
        socket_path.display()
    );

    loop {
        match send_provider_session_message_via_owner_bridge(
            data_dir,
            provider_id,
            session_id,
            text,
            workspace_dir,
        ) {
            Ok(true) => return Ok(()),
            Ok(false) => {
                last_error = format!(
                    "provider owner bridge not ready: {}",
                    socket_path.display()
                );
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
) -> Result<Value, String> {
    let data_dir = ensure_data_dir()?;
    let sidecar = app
        .shell()
        .sidecar("onlineworker-bot")
        .map_err(|error| format!("Sidecar not found: {}", error))?;

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

    let mut sidecar = sidecar.args(args);
    for (key, value) in provider_session_bridge_env(&data_dir) {
        sidecar = sidecar.env(&key, value);
    }

    let output = sidecar
        .output()
        .await
        .map_err(|error| format!("provider session bridge failed: {}", error))?;

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

    serde_json::from_slice(&output.stdout).map_err(|error| {
        format!(
            "provider session bridge returned invalid JSON: {}",
            error
        )
    })
}

#[tauri::command]
pub async fn list_provider_sessions(app: AppHandle, provider_id: String) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    match provider.runtime_id.as_str() {
        "codex" => serde_json::to_value(list_codex_threads()?).map_err(|error| error.to_string()),
        "claude" => {
            serde_json::to_value(list_claude_sessions()?).map_err(|error| error.to_string())
        }
        _ => {
            let data_dir = ensure_data_dir()?;
            match list_provider_sessions_via_owner_bridge(&data_dir, &provider.id, 100) {
                Ok(value) => Ok(value),
                Err(_) => run_provider_session_bridge(&app, &provider.id, "list", None, None).await,
            }
        }
    }
}

#[tauri::command]
pub async fn read_provider_session(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    workspace_dir: Option<String>,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    match provider.runtime_id.as_str() {
        "codex" => {
            serde_json::to_value(read_codex_thread(session_id)?).map_err(|error| error.to_string())
        }
        "claude" => serde_json::to_value(read_claude_session(session_id, workspace_dir)?)
            .map_err(|error| error.to_string()),
        _ => {
            let _ = app;
            let data_dir = ensure_data_dir()?;
            read_provider_session_via_owner_bridge(
                &data_dir,
                &provider.id,
                &session_id,
                workspace_dir.as_deref(),
                20,
            )
        }
    }
}

#[tauri::command]
pub async fn send_provider_session_message(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    text: String,
    workspace_dir: Option<String>,
) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    match provider.runtime_id.as_str() {
        "codex" => {
            send_codex_thread_message(session_id, text, workspace_dir).await?;
            Ok(Value::Null)
        }
        "claude" => serde_json::to_value(send_claude_session_message(
            session_id,
            text,
            workspace_dir,
        )?)
        .map_err(|error| error.to_string()),
        _ => {
            let _ = app;
            let data_dir = ensure_data_dir()?;
            let trimmed = text.trim().to_string();
            if trimmed.is_empty() {
                return Err("message is empty".to_string());
            }
            send_provider_session_message_via_owner_bridge_with_retry(
                &data_dir,
                &provider.id,
                &session_id,
                &trimmed,
                workspace_dir.as_deref(),
                std::time::Duration::from_secs(8),
            )?;
            Ok(Value::Null)
        }
    }
}

#[tauri::command]
pub async fn start_provider_session_stream(
    provider_id: String,
    session_id: String,
    cursor: Option<Value>,
    channel: Channel<Value>,
) -> Result<(), String> {
    let provider = require_runtime_provider(&provider_id)?;
    let generation = provider_session_stream_generation();
    let my_generation = generation.fetch_add(1, Ordering::SeqCst) + 1;

    match provider.runtime_id.as_str() {
        "codex" => {
            let mut cursor = cursor
                .and_then(|value| serde_json::from_value::<CodexThreadCursor>(value).ok())
                .unwrap_or_default();
            tauri::async_runtime::spawn(async move {
                while generation.load(Ordering::SeqCst) == my_generation {
                    match read_codex_thread_updates(session_id.clone(), cursor) {
                        Ok(result) => {
                            cursor = result.cursor;
                            for turn in result.turns {
                                let _ = channel.send(serde_json::json!({
                                    "kind": if turn.role == "assistant" { "assistant_completed" } else { "user_message" },
                                    "turn": turn,
                                    "cursor": cursor,
                                    "replace": result.replace,
                                }));
                            }
                        }
                        Err(error) => {
                            let _ = channel.send(serde_json::json!({
                                "kind": "error",
                                "error": error,
                            }));
                            break;
                        }
                    }
                    tokio::time::sleep(tokio::time::Duration::from_millis(250)).await;
                }
            });
            Ok(())
        }
        "claude" => Ok(()),
        other => Err(format!(
            "Provider runtime '{other}' has no session implementation"
        )),
    }
}

#[tauri::command]
pub async fn stop_provider_session_stream(
    provider_id: String,
    session_id: String,
) -> Result<(), String> {
    let provider = require_runtime_provider(&provider_id)?;
    let _ = session_id;
    provider_session_stream_generation().fetch_add(1, Ordering::SeqCst);
    match provider.runtime_id.as_str() {
        "codex" => Ok(()),
        "claude" => Ok(()),
        other => Err(format!(
            "Provider runtime '{other}' has no session implementation"
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::{
        provider_not_enabled_message, provider_owner_bridge_socket_path,
        provider_session_bridge_env, provider_session_bridge_path, send_provider_session_message_via_owner_bridge,
        send_provider_session_message_via_owner_bridge_with_retry, PROVIDER_OVERLAY_ENV,
    };
    use crate::commands::config_provider::provider_metadata_from_raw;
    use std::fs;
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixListener;
    use std::thread;
    use std::time::Duration;

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
        let path = provider_session_bridge_path("/Users/test");
        assert_eq!(
            path,
            "/Users/test/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        );
    }

    #[test]
    fn provider_session_bridge_env_includes_overlay_from_process_env() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-session-env-process-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create data dir");
        std::env::set_var(PROVIDER_OVERLAY_ENV, "/tmp/provider-overlay");

        let envs = provider_session_bridge_env(&dir);
        let overlay = envs
            .iter()
            .find(|(key, _)| key == PROVIDER_OVERLAY_ENV)
            .map(|(_, value)| value.clone());

        assert_eq!(overlay.as_deref(), Some("/tmp/provider-overlay"));

        std::env::remove_var(PROVIDER_OVERLAY_ENV);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn provider_session_bridge_env_reads_overlay_from_app_env_file() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-provider-session-env-file-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create data dir");
        fs::write(
            dir.join(".env"),
            "ONLINEWORKER_PROVIDER_OVERLAY=/tmp/provider-overlay-from-file\n",
        )
        .expect("write env file");
        std::env::remove_var(PROVIDER_OVERLAY_ENV);

        let envs = provider_session_bridge_env(&dir);
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
            reader.read_line(&mut request).expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["thread_id"], "tid-1");
            assert_eq!(payload["text"], "hello");
            assert_eq!(payload["workspace_dir"], "/tmp/workspace");

            let response = serde_json::json!({ "ok": true, "accepted": true });
            writeln!(stream, "{response}").expect("write response");
        });

        let used_bridge = send_provider_session_message_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            "tid-1",
            "hello",
            Some("/tmp/workspace"),
        )
        .expect("send via owner bridge");

        assert!(used_bridge);
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
            reader.read_line(&mut request).expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["provider_id"], "overlay-tool");
            let response = serde_json::json!({ "ok": true, "accepted": true });
            writeln!(stream, "{response}").expect("write response");
        });

        send_provider_session_message_via_owner_bridge_with_retry(
            &temp_dir,
            "overlay-tool",
            "tid-1",
            "hello",
            Some("/tmp/workspace"),
            Duration::from_secs(2),
        )
        .expect("owner bridge should become ready within timeout");

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
            reader.read_line(&mut request).expect("read owner bridge request");
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
            reader.read_line(&mut request).expect("read owner bridge request");
            let payload: serde_json::Value =
                serde_json::from_str(request.trim()).expect("parse owner bridge request");
            assert_eq!(payload["type"], "list_sessions");
            assert_eq!(payload["provider_id"], "overlay-tool");
            assert_eq!(payload["limit"], 100);

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

        let result = super::list_provider_sessions_via_owner_bridge(
            &temp_dir,
            "overlay-tool",
            100,
        )
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
}
