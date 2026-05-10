use serde_json::Value;
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

static PROVIDER_SESSION_STREAM_GENERATION: OnceLock<Arc<AtomicU64>> = OnceLock::new();

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

#[tauri::command]
pub fn list_provider_sessions(provider_id: String) -> Result<Value, String> {
    let provider = require_runtime_provider(&provider_id)?;
    match provider.runtime_id.as_str() {
        "codex" => serde_json::to_value(list_codex_threads()?).map_err(|error| error.to_string()),
        "claude" => {
            serde_json::to_value(list_claude_sessions()?).map_err(|error| error.to_string())
        }
        other => Err(format!(
            "Provider runtime '{other}' has no session implementation"
        )),
    }
}

#[tauri::command]
pub fn read_provider_session(
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
        other => Err(format!(
            "Provider runtime '{other}' has no session implementation"
        )),
    }
}

#[tauri::command]
pub async fn send_provider_session_message(
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
        other => Err(format!(
            "Provider runtime '{other}' has no session implementation"
        )),
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
    use super::provider_not_enabled_message;
    use crate::commands::config_provider::provider_metadata_from_raw;

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
}
