use serde::Serialize;
use std::collections::BTreeMap;
use std::path::PathBuf;

use super::config_provider::{
    normalize_config_for_display, normalize_provider_document_with_env,
    serialize_config_document_for_persistence, serialize_normalized_config_with_env,
    set_provider_flags_in_document, visible_provider_ids_from_raw, ProviderMetadata,
    ProviderRuntimePolicy,
};

/// Application data directory: ~/Library/Application Support/OnlineWorker/
pub fn data_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/Users/unknown".to_string());
    PathBuf::from(home).join("Library/Application Support/OnlineWorker")
}

/// Ensure the data directory exists, creating it if necessary.
pub fn ensure_data_dir() -> Result<PathBuf, String> {
    let dir = data_dir();
    std::fs::create_dir_all(&dir).map_err(|e| format!("Cannot create data dir: {}", e))?;
    Ok(dir)
}

fn config_path() -> PathBuf {
    data_dir().join("config.yaml")
}

fn env_path() -> PathBuf {
    data_dir().join(".env")
}

/// Fields that should be masked by default in the UI
const SENSITIVE_KEYS: &[&str] = &[
    "TELEGRAM_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    "ALLOWED_USER_ID",
    "BOT_TOKEN",
    "API_KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
];

fn default_env_template() -> &'static str {
    "# OnlineWorker .env\n\nTELEGRAM_TOKEN=\nALLOWED_USER_ID=\nGROUP_CHAT_ID=\n"
}

fn is_sensitive_key(key: &str) -> bool {
    SENSITIVE_KEYS
        .iter()
        .any(|k| key.to_uppercase().contains(k))
}

#[derive(Serialize)]
pub struct ConfigContent {
    pub raw: String,
    pub path: String,
}

#[derive(Serialize)]
pub struct EnvLine {
    pub key: String,
    pub value: String,
    pub masked: bool,
}

#[derive(Serialize)]
pub struct EnvContent {
    pub lines: Vec<EnvLine>,
    pub path: String,
}

/// Check if this is the first run (no config.yaml in data dir).
#[tauri::command]
pub async fn check_first_run() -> Result<bool, String> {
    let config = data_dir().join("config.yaml");
    Ok(!config.exists())
}

/// Create default config.yaml and .env template if they don't exist.
#[tauri::command]
pub async fn create_default_config() -> Result<(), String> {
    let dir = ensure_data_dir()?;
    let config = dir.join("config.yaml");
    if !config.exists() {
        let default = include_str!("../../default-config.yaml");
        std::fs::write(&config, default).map_err(|e| e.to_string())?;
    }
    let env = dir.join(".env");
    if !env.exists() {
        let template = default_env_template();
        std::fs::write(&env, template).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub async fn set_provider_flags(
    provider_id: String,
    managed: bool,
    autostart: bool,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    let path = dir.join("config.yaml");
    let raw = if path.exists() {
        std::fs::read_to_string(&path).map_err(|e| format!("Cannot read config.yaml: {}", e))?
    } else {
        include_str!("../../default-config.yaml").to_string()
    };
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_provider_flags_in_document(&mut doc, &provider_id, managed, autostart);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

pub(crate) fn read_provider_runtime_policies_from_disk(
) -> Result<BTreeMap<String, ProviderRuntimePolicy>, String> {
    let config_raw = std::fs::read_to_string(config_path()).unwrap_or_default();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let doc = normalize_provider_document_with_env(&config_raw, Some(&env_raw))?;
    let providers = doc.providers.unwrap_or_default();
    Ok(providers
        .into_iter()
        .map(|(provider_id, provider)| {
            (
                provider_id,
                ProviderRuntimePolicy {
                    managed: provider.managed.unwrap_or(false),
                    autostart: provider.autostart.unwrap_or(false),
                },
            )
        })
        .collect())
}

pub(crate) fn read_provider_metadata_from_disk() -> Result<Vec<ProviderMetadata>, String> {
    let config_raw = std::fs::read_to_string(config_path()).unwrap_or_default();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    super::config_provider::provider_metadata_from_raw(&config_raw, Some(&env_raw))
}

pub(crate) fn read_visible_provider_ids_from_disk() -> Result<Vec<String>, String> {
    let config_raw = std::fs::read_to_string(config_path()).unwrap_or_default();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    visible_provider_ids_from_raw(&config_raw, Some(&env_raw))
}

#[tauri::command]
pub async fn get_provider_metadata() -> Result<Vec<ProviderMetadata>, String> {
    read_provider_metadata_from_disk()
}

#[tauri::command]
pub async fn read_config() -> Result<ConfigContent, String> {
    let path = config_path();
    let raw =
        std::fs::read_to_string(&path).map_err(|e| format!("Cannot read config.yaml: {}", e))?;
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    Ok(ConfigContent {
        raw: normalize_config_for_display(&raw, Some(&env_raw)),
        path: path.to_string_lossy().to_string(),
    })
}

#[tauri::command]
pub async fn write_config(content: String) -> Result<(), String> {
    let path = config_path();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let normalized = serialize_normalized_config_with_env(&content, Some(&env_raw))?;
    std::fs::write(&path, normalized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

#[tauri::command]
pub async fn read_env() -> Result<EnvContent, String> {
    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;

    let lines = raw
        .lines()
        .map(|line| {
            if line.starts_with('#') || line.is_empty() {
                EnvLine {
                    key: line.to_string(),
                    value: String::new(),
                    masked: false,
                }
            } else if let Some(eq_pos) = line.find('=') {
                let key = line[..eq_pos].trim().to_string();
                let value = line[eq_pos + 1..].to_string();
                EnvLine {
                    key: key.clone(),
                    value: if is_sensitive_key(&key) {
                        "***".to_string()
                    } else {
                        value
                    },
                    masked: is_sensitive_key(&key),
                }
            } else {
                EnvLine {
                    key: line.to_string(),
                    value: String::new(),
                    masked: false,
                }
            }
        })
        .collect();

    Ok(EnvContent {
        lines,
        path: path.to_string_lossy().to_string(),
    })
}

#[tauri::command]
pub async fn read_env_raw() -> Result<ConfigContent, String> {
    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;
    Ok(ConfigContent {
        raw,
        path: path.to_string_lossy().to_string(),
    })
}

#[tauri::command]
pub async fn write_env(content: String) -> Result<(), String> {
    let path = env_path();
    std::fs::write(&path, content).map_err(|e| format!("Cannot write .env: {}", e))
}

/// Read a single field from .env (returns masked value for sensitive fields)
#[tauri::command]
pub async fn read_env_field(key: String) -> Result<String, String> {
    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;

    for line in raw.lines() {
        if let Some(eq_pos) = line.find('=') {
            let line_key = line[..eq_pos].trim();
            if line_key == key {
                let value = line[eq_pos + 1..].to_string();
                return Ok(if is_sensitive_key(&key) && !value.is_empty() {
                    "***".to_string()
                } else {
                    value
                });
            }
        }
    }
    Err(format!("Key '{}' not found in .env", key))
}

/// Reveal the actual value of a sensitive field (with logging)
#[tauri::command]
pub async fn reveal_env_field(key: String) -> Result<String, String> {
    use std::time::SystemTime;

    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;

    for line in raw.lines() {
        if let Some(eq_pos) = line.find('=') {
            let line_key = line[..eq_pos].trim();
            if line_key == key {
                let value = line[eq_pos + 1..].to_string();

                // Log the reveal operation
                let timestamp = SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap()
                    .as_secs();
                eprintln!(
                    "[SECURITY] Field '{}' revealed at timestamp {}",
                    key, timestamp
                );

                return Ok(value);
            }
        }
    }
    Err(format!("Key '{}' not found in .env", key))
}

/// Write/update a single field in .env (patch style - preserves other fields and comments)
#[tauri::command]
pub async fn write_env_field(key: String, value: String) -> Result<(), String> {
    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;

    let mut lines: Vec<String> = Vec::new();
    let mut found = false;

    for line in raw.lines() {
        if line.starts_with('#') || line.is_empty() {
            // Preserve comments and empty lines
            lines.push(line.to_string());
        } else if let Some(eq_pos) = line.find('=') {
            let line_key = line[..eq_pos].trim();
            if line_key == key {
                // Update the matching key
                lines.push(format!("{}={}", key, value));
                found = true;
            } else {
                // Preserve other keys
                lines.push(line.to_string());
            }
        } else {
            // Preserve malformed lines
            lines.push(line.to_string());
        }
    }

    // If key not found, append it at the end
    if !found {
        lines.push(format!("{}={}", key, value));
    }

    let new_content = lines.join("\n") + "\n";
    std::fs::write(&path, new_content).map_err(|e| format!("Cannot write .env: {}", e))
}

/// List all keys in .env (excluding comments and empty lines)
#[tauri::command]
pub async fn list_env_keys() -> Result<Vec<String>, String> {
    let path = env_path();
    let raw = std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?;

    let keys: Vec<String> = raw
        .lines()
        .filter_map(|line| {
            if line.starts_with('#') || line.is_empty() {
                None
            } else if let Some(eq_pos) = line.find('=') {
                Some(line[..eq_pos].trim().to_string())
            } else {
                None
            }
        })
        .collect();

    Ok(keys)
}

#[cfg(test)]
mod tests {
    use super::{default_env_template, is_sensitive_key};

    #[test]
    fn default_env_template_only_contains_telegram_fields() {
        let template = default_env_template();
        assert!(template.contains("TELEGRAM_TOKEN="));
        assert!(template.contains("ALLOWED_USER_ID="));
        assert!(template.contains("GROUP_CHAT_ID="));
        assert!(!template.contains("ANTHROPIC_API_KEY="));
        assert!(!template.contains("ANTHROPIC_BASE_URL="));
        assert!(!template.contains("ANTHROPIC_MODEL="));
    }

    #[test]
    fn api_key_fields_are_masked() {
        assert!(is_sensitive_key("ANTHROPIC_API_KEY"));
        assert!(is_sensitive_key("OPENAI_API_KEY"));
    }
}
