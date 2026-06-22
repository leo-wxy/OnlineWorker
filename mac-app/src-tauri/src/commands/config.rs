use serde::Serialize;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use super::config_provider::{
    ai_config_metadata_from_raw, build_default_user_config_with_env, normalize_config_for_display,
    normalize_provider_document_with_env, notification_channel_metadata_from_raw,
    serialize_config_document_for_persistence, serialize_normalized_config_with_env,
    set_ai_config_in_document, set_notification_channel_config_in_document,
    set_notification_channel_enabled_in_document, set_provider_cli_config_in_document,
    set_provider_flags_in_document, set_provider_message_hook_enabled_in_document,
    visible_provider_ids_from_raw, AiConfigMetadata, AiScenarioConfigEntry, AiServiceConfigEntry,
    NotificationChannelMetadata, ProviderExternalCliConfig, ProviderLaunchMethodConfig,
    ProviderMetadata, ProviderRuntimePolicy,
};

pub(crate) const DEFAULT_APP_NAME: &str = "OnlineWorker";

pub(crate) fn app_name() -> &'static str {
    DEFAULT_APP_NAME
}

pub(crate) fn app_support_dir_name() -> &'static str {
    DEFAULT_APP_NAME
}

#[cfg(test)]
thread_local! {
    static TEST_HOME_OVERRIDE: std::cell::RefCell<Option<PathBuf>> =
        const { std::cell::RefCell::new(None) };
}

#[cfg(test)]
fn set_test_home_override(path: Option<PathBuf>) {
    TEST_HOME_OVERRIDE.with(|override_path| {
        *override_path.borrow_mut() = path;
    });
}

fn home_dir() -> PathBuf {
    #[cfg(test)]
    if let Some(path) = TEST_HOME_OVERRIDE.with(|override_path| override_path.borrow().clone()) {
        return path;
    }

    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/Users/unknown".to_string()))
}

/// Application data directory: ~/Library/Application Support/<app name>/
pub fn data_dir() -> PathBuf {
    home_dir()
        .join("Library/Application Support")
        .join(app_support_dir_name())
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

pub(crate) fn env_path() -> PathBuf {
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
const LEGACY_EXTERNAL_CLI_ENV_KEYS: &[&str] = &[
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
];

fn default_env_template() -> String {
    format!(
        "# {} .env\n\nTELEGRAM_TOKEN=\nALLOWED_USER_ID=\nGROUP_CHAT_ID=\n",
        app_name()
    )
}

fn is_sensitive_key(key: &str) -> bool {
    SENSITIVE_KEYS
        .iter()
        .any(|k| key.to_uppercase().contains(k))
}

fn is_legacy_external_cli_env_key(key: &str) -> bool {
    let upper = key.trim().to_uppercase();
    upper.starts_with("ANTHROPIC_") || LEGACY_EXTERNAL_CLI_ENV_KEYS.iter().any(|candidate| *candidate == upper)
}

fn sanitize_env_content(raw: &str) -> String {
    let mut lines = Vec::new();
    for line in raw.lines() {
        if let Some((key, _)) = line.split_once('=') {
            if is_legacy_external_cli_env_key(key) {
                continue;
            }
        }
        lines.push(line.to_string());
    }
    if lines.is_empty() {
        String::new()
    } else {
        lines.join("\n") + "\n"
    }
}

fn cleanup_legacy_external_cli_config(dir: &PathBuf) -> Result<(), String> {
    let env = dir.join(".env");
    if env.exists() {
        let raw = std::fs::read_to_string(&env).map_err(|e| format!("Cannot read .env: {}", e))?;
        let sanitized = sanitize_env_content(&raw);
        if sanitized != raw {
            std::fs::write(&env, sanitized).map_err(|e| format!("Cannot write .env: {}", e))?;
        }
    }

    let config = dir.join("config.yaml");
    if config.exists() {
        let raw = std::fs::read_to_string(&config)
            .map_err(|e| format!("Cannot read config.yaml: {}", e))?;
        let env_raw = std::fs::read_to_string(&env).unwrap_or_default();
        let normalized = serialize_normalized_config_with_env(&raw, Some(&env_raw))?;
        if normalized != raw {
            std::fs::write(&config, normalized)
                .map_err(|e| format!("Cannot write config.yaml: {}", e))?;
        }
    }
    Ok(())
}

fn read_config_or_materialize_default(path: &Path, env_raw: &str) -> Result<String, String> {
    if path.exists() {
        std::fs::read_to_string(path).map_err(|e| format!("Cannot read config.yaml: {}", e))
    } else {
        build_default_user_config_with_env(Some(env_raw))
    }
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
    cleanup_legacy_external_cli_config(&dir)?;
    let env = dir.join(".env");
    if !env.exists() {
        let template = default_env_template();
        std::fs::write(&env, template).map_err(|e| e.to_string())?;
    }
    let config = dir.join("config.yaml");
    if !config.exists() {
        let env_raw = std::fs::read_to_string(&env).unwrap_or_default();
        let default = build_default_user_config_with_env(Some(&env_raw))?;
        std::fs::write(&config, default).map_err(|e| e.to_string())?;
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
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_provider_flags_in_document(&mut doc, &provider_id, managed, autostart);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

#[tauri::command]
pub async fn set_provider_message_hook_enabled(
    provider_id: String,
    hook_name: String,
    enabled: bool,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_provider_message_hook_enabled_in_document(&mut doc, &provider_id, &hook_name, enabled);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

#[tauri::command]
pub async fn set_provider_cli_config(
    provider_id: String,
    bin: Option<String>,
    external_cli: ProviderExternalCliConfig,
    launch_methods: Option<Vec<ProviderLaunchMethodConfig>>,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_provider_cli_config_in_document(&mut doc, &provider_id, bin, external_cli, launch_methods);
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

pub(crate) fn read_notification_channels_from_disk(
) -> Result<Vec<NotificationChannelMetadata>, String> {
    let config_raw = std::fs::read_to_string(config_path()).unwrap_or_default();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    notification_channel_metadata_from_raw(&config_raw, Some(&env_raw))
}

pub(crate) fn read_ai_config_from_disk() -> Result<AiConfigMetadata, String> {
    let config_raw = std::fs::read_to_string(config_path()).unwrap_or_default();
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    ai_config_metadata_from_raw(&config_raw, Some(&env_raw))
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
pub async fn get_notification_channels() -> Result<Vec<NotificationChannelMetadata>, String> {
    read_notification_channels_from_disk()
}

#[tauri::command]
pub async fn get_ai_config() -> Result<AiConfigMetadata, String> {
    read_ai_config_from_disk()
}

#[tauri::command]
pub async fn set_ai_config(
    services: Vec<AiServiceConfigEntry>,
    scenarios: BTreeMap<String, AiScenarioConfigEntry>,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_ai_config_in_document(&mut doc, services, scenarios);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

#[tauri::command]
pub async fn set_notification_channel_enabled(
    channel_id: String,
    enabled: bool,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_notification_channel_enabled_in_document(&mut doc, &channel_id, enabled);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
}

#[tauri::command]
pub async fn set_notification_channel_config(
    channel_id: String,
    config: BTreeMap<String, serde_yaml::Value>,
) -> Result<(), String> {
    let dir = ensure_data_dir()?;
    cleanup_legacy_external_cli_config(&dir)?;
    let path = dir.join("config.yaml");
    let env_raw = std::fs::read_to_string(env_path()).unwrap_or_default();
    let raw = read_config_or_materialize_default(&path, &env_raw)?;

    let mut doc = normalize_provider_document_with_env(&raw, Some(&env_raw))?;
    set_notification_channel_config_in_document(&mut doc, &channel_id, config);
    let serialized = serialize_config_document_for_persistence(doc, &raw)?;
    std::fs::write(&path, serialized).map_err(|e| format!("Cannot write config.yaml: {}", e))
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
    let raw = sanitize_env_content(
        &std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?,
    );

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
    let raw = sanitize_env_content(
        &std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?,
    );
    Ok(ConfigContent {
        raw,
        path: path.to_string_lossy().to_string(),
    })
}

#[tauri::command]
pub async fn write_env(content: String) -> Result<(), String> {
    let path = env_path();
    std::fs::write(&path, sanitize_env_content(&content))
        .map_err(|e| format!("Cannot write .env: {}", e))
}

/// Read a single field from .env (returns masked value for sensitive fields)
#[tauri::command]
pub async fn read_env_field(key: String) -> Result<String, String> {
    if is_legacy_external_cli_env_key(&key) {
        return Err(format!(
            "Key '{}' is no longer managed by OnlineWorker",
            key
        ));
    }
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

    if is_legacy_external_cli_env_key(&key) {
        return Err(format!(
            "Key '{}' is no longer managed by OnlineWorker",
            key
        ));
    }
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
    if is_legacy_external_cli_env_key(&key) {
        return Err(format!(
            "Key '{}' is no longer managed by OnlineWorker",
            key
        ));
    }
    let path = env_path();
    let raw = sanitize_env_content(
        &std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?,
    );

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
    let raw = sanitize_env_content(
        &std::fs::read_to_string(&path).map_err(|e| format!("Cannot read .env: {}", e))?,
    );

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
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    use serde_yaml::Value;

    use super::{
        config_path, create_default_config, default_env_template, env_path, is_sensitive_key,
        read_config, sanitize_env_content, set_provider_flags, set_test_home_override,
        write_config,
    };
    use crate::commands::config_provider::{
        provider_default_metadata, public_default_provider_ids,
    };

    struct TestHomeGuard {
        root: PathBuf,
    }

    impl TestHomeGuard {
        fn new() -> Self {
            let stamp = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("current time")
                .as_nanos();
            let root = std::env::temp_dir().join(format!(
                "onlineworker-config-command-tests-{}-{}",
                std::process::id(),
                stamp
            ));
            fs::create_dir_all(&root).expect("create test home");
            set_test_home_override(Some(root.clone()));
            Self { root }
        }
    }

    impl Drop for TestHomeGuard {
        fn drop(&mut self) {
            set_test_home_override(None);
            let _ = fs::remove_dir_all(&self.root);
        }
    }

    fn default_provider_ids_for_test() -> Vec<String> {
        let ids = public_default_provider_ids();
        assert!(!ids.is_empty());
        ids
    }

    fn provider_value<'a>(doc: &'a Value, provider_id: &str, key: &str) -> Option<&'a Value> {
        doc.get("providers")
            .and_then(|providers| providers.get(provider_id))
            .and_then(|provider| provider.get(key))
    }

    #[test]
    fn default_env_template_only_contains_telegram_fields() {
        let template = default_env_template();
        assert!(template.contains("TELEGRAM_TOKEN="));
        assert!(template.contains("ALLOWED_USER_ID="));
        assert!(template.contains("GROUP_CHAT_ID="));
        assert!(!template.contains("ANTHROPIC_API_KEY="));
        assert!(!template.contains("ANTHROPIC_BASE_URL="));
        assert!(!template.contains("ANTHROPIC_AUTH_TOKEN="));
        assert!(!template.contains("ANTHROPIC_MODEL="));
    }

    #[test]
    fn api_key_fields_are_masked() {
        assert!(is_sensitive_key("ANTHROPIC_API_KEY"));
        assert!(is_sensitive_key("ANTHROPIC_AUTH_TOKEN"));
        assert!(is_sensitive_key("OPENAI_API_KEY"));
    }

    #[test]
    fn sanitize_env_content_removes_legacy_external_cli_env_keys() {
        let raw = "\
# OnlineWorker .env
TELEGRAM_TOKEN=token
ANTHROPIC_API_KEY=dummy
ANTHROPIC_AUTH_TOKEN=token-123
ANTHROPIC_BASE_URL=https://runtime.example.test/langbase
ANTHROPIC_MODEL=claude-opus-4-6
GROUP_CHAT_ID=-1001
";

        let sanitized = sanitize_env_content(raw);

        assert!(sanitized.contains("TELEGRAM_TOKEN=token"));
        assert!(sanitized.contains("GROUP_CHAT_ID=-1001"));
        assert!(!sanitized.contains("ANTHROPIC_API_KEY"));
        assert!(!sanitized.contains("ANTHROPIC_AUTH_TOKEN"));
        assert!(!sanitized.contains("ANTHROPIC_BASE_URL"));
        assert!(!sanitized.contains("ANTHROPIC_MODEL"));
        assert!(!sanitized.contains("runtime.example.test"));
    }

    #[test]
    fn create_default_config_writes_generated_readable_yaml() {
        let _guard = TestHomeGuard::new();

        tauri::async_runtime::block_on(create_default_config()).expect("create default config");

        let raw = fs::read_to_string(config_path()).expect("read config.yaml");
        let doc: Value = serde_yaml::from_str(&raw).expect("parse config.yaml");

        assert_eq!(
            doc.get("schema_version").and_then(|value| value.as_i64()),
            Some(2)
        );
        for provider_id in default_provider_ids_for_test() {
            let metadata = provider_default_metadata(&provider_id);
            assert_eq!(
                provider_value(&doc, &provider_id, "bin").and_then(|value| value.as_str()),
                metadata.bin.as_deref()
            );
            assert_eq!(
                provider_value(&doc, &provider_id, "owner_transport")
                    .and_then(|value| value.as_str()),
                Some(metadata.transport.owner.as_str())
            );
        }
        assert!(doc
            .get("notifications")
            .and_then(|notifications| notifications.get("channels"))
            .and_then(|channels| channels.get("telegram"))
            .is_some());
        assert_eq!(
            doc.get("ai")
                .and_then(|ai| ai.get("services"))
                .and_then(|services| services.as_sequence())
                .map(|services| services.len()),
            Some(2)
        );
        assert!(env_path().exists());
    }

    #[test]
    fn create_default_config_materializes_schema_only_existing_config() {
        let _guard = TestHomeGuard::new();
        fs::create_dir_all(config_path().parent().expect("config parent"))
            .expect("create config parent");
        fs::write(config_path(), "schema_version: 2\n").expect("write schema-only config");

        tauri::async_runtime::block_on(create_default_config()).expect("create default config");

        let raw = fs::read_to_string(config_path()).expect("read migrated config");
        let doc: Value = serde_yaml::from_str(&raw).expect("parse migrated config");

        for provider_id in default_provider_ids_for_test() {
            assert!(doc
                .get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .is_some());
        }
        assert!(doc
            .get("notifications")
            .and_then(|notifications| notifications.get("channels"))
            .and_then(|channels| channels.get("telegram"))
            .is_some());
        assert_eq!(
            doc.get("ai")
                .and_then(|ai| ai.get("services"))
                .and_then(|services| services.as_sequence())
                .map(|services| services.len()),
            Some(2)
        );
    }

    #[test]
    fn read_config_renders_effective_defaults_from_fresh_yaml() {
        let _guard = TestHomeGuard::new();
        tauri::async_runtime::block_on(create_default_config()).expect("create default config");

        let content = tauri::async_runtime::block_on(read_config()).expect("read config");
        let doc: Value = serde_yaml::from_str(&content.raw).expect("parse rendered config");

        for provider_id in default_provider_ids_for_test() {
            let metadata = provider_default_metadata(&provider_id);
            assert_eq!(
                provider_value(&doc, &provider_id, "bin").and_then(|value| value.as_str()),
                metadata.bin.as_deref()
            );
        }
        assert_eq!(
            doc.get("ai")
                .and_then(|ai| ai.get("services"))
                .and_then(|services| services.as_sequence())
                .map(|services| services.len()),
            Some(2)
        );
    }

    #[test]
    fn write_config_round_trips_effective_yaml_without_pruning_to_minimal() {
        let _guard = TestHomeGuard::new();
        tauri::async_runtime::block_on(create_default_config()).expect("create default config");

        let content = tauri::async_runtime::block_on(read_config()).expect("read config");
        tauri::async_runtime::block_on(write_config(content.raw)).expect("write config");

        let raw = fs::read_to_string(config_path()).expect("read persisted config");
        let doc: Value = serde_yaml::from_str(&raw).expect("parse persisted config");

        assert_eq!(
            doc.get("schema_version").and_then(|value| value.as_i64()),
            Some(2)
        );
        assert!(doc.get("providers").is_some());
        assert!(doc.get("notifications").is_some());
        assert!(doc.get("ai").is_some());
        for provider_id in default_provider_ids_for_test() {
            let metadata = provider_default_metadata(&provider_id);
            assert_eq!(
                provider_value(&doc, &provider_id, "owner_transport")
                    .and_then(|value| value.as_str()),
                Some(metadata.transport.owner.as_str())
            );
        }
    }

    #[test]
    fn write_config_persists_provider_override_without_dropping_other_defaults() {
        let _guard = TestHomeGuard::new();
        tauri::async_runtime::block_on(create_default_config()).expect("create default config");

        let content = tauri::async_runtime::block_on(read_config()).expect("read config");
        let mut doc: Value = serde_yaml::from_str(&content.raw).expect("parse rendered config");
        let provider_id = default_provider_ids_for_test()
            .into_iter()
            .next()
            .expect("default provider");
        doc["providers"][&provider_id]["managed"] = Value::Bool(false);
        doc["providers"][&provider_id]["autostart"] = Value::Bool(false);

        let edited = serde_yaml::to_string(&doc).expect("serialize edited config");
        tauri::async_runtime::block_on(write_config(edited)).expect("write config");

        let raw = fs::read_to_string(config_path()).expect("read persisted config");
        let persisted: Value = serde_yaml::from_str(&raw).expect("parse persisted config");

        assert_eq!(
            persisted
                .get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .and_then(|provider| provider.get("managed"))
                .and_then(|value| value.as_bool()),
            Some(false)
        );
        assert_eq!(
            persisted
                .get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .and_then(|provider| provider.get("autostart"))
                .and_then(|value| value.as_bool()),
            Some(false)
        );
        for default_provider_id in default_provider_ids_for_test() {
            assert!(persisted
                .get("providers")
                .and_then(|providers| providers.get(&default_provider_id))
                .is_some());
        }
        assert!(persisted.get("ai").is_some());
        assert!(persisted.get("notifications").is_some());
    }

    #[test]
    fn set_provider_flags_materializes_missing_config_without_template_fallback() {
        let _guard = TestHomeGuard::new();
        let provider_id = default_provider_ids_for_test()
            .into_iter()
            .next()
            .expect("default provider");

        tauri::async_runtime::block_on(set_provider_flags(provider_id.clone(), false, false))
            .expect("set provider flags");

        let raw = fs::read_to_string(config_path()).expect("read materialized config");
        let doc: Value = serde_yaml::from_str(&raw).expect("parse materialized config");

        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .and_then(|provider| provider.get("managed"))
                .and_then(|value| value.as_bool()),
            Some(false)
        );
        let metadata = provider_default_metadata(&provider_id);
        assert_eq!(
            doc.get("providers")
                .and_then(|providers| providers.get(&provider_id))
                .and_then(|provider| provider.get("owner_transport"))
                .and_then(|value| value.as_str()),
            Some(metadata.transport.owner.as_str())
        );
        for default_provider_id in default_provider_ids_for_test() {
            assert!(doc
                .get("providers")
                .and_then(|providers| providers.get(&default_provider_id))
                .is_some());
        }
        assert!(doc.get("notifications").is_some());
        assert!(doc.get("ai").is_some());
    }
}
