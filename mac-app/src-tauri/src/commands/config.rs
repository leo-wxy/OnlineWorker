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
    upper.starts_with("ANTHROPIC_")
        || LEGACY_EXTERNAL_CLI_ENV_KEYS
            .iter()
            .any(|candidate| *candidate == upper)
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

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderValidationCheck {
    pub id: String,
    pub label: String,
    pub ok: bool,
    pub severity: String,
    pub detail: Option<String>,
    pub remediation: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderValidationSources {
    pub config_path: String,
    pub provider_config_found: bool,
    pub cli_path: Option<String>,
    pub env_materialized: Vec<String>,
    pub runtime_id: Option<String>,
    pub bin: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderValidationReport {
    pub provider_id: String,
    pub ok: bool,
    pub status: String,
    pub summary: String,
    pub checks: Vec<ProviderValidationCheck>,
    pub sources: ProviderValidationSources,
}

fn provider_validation_command_program_token(command_line: &str) -> String {
    let mut token = String::new();
    let mut chars = command_line.trim().chars().peekable();
    let mut quote: Option<char> = None;
    while let Some(ch) = chars.next() {
        if let Some(q) = quote {
            if ch == q {
                quote = None;
            } else if ch == '\\' {
                token.push(chars.next().unwrap_or(ch));
            } else {
                token.push(ch);
            }
            continue;
        }
        match ch {
            '\'' | '"' => quote = Some(ch),
            '\\' => token.push(chars.next().unwrap_or(ch)),
            ch if ch.is_whitespace() => break,
            _ => token.push(ch),
        }
    }
    token
}

fn provider_validation_rich_path() -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    )
}

fn provider_validation_expand_home_path(value: &str) -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    if value.starts_with("~/") {
        format!("{}{}", home, &value[1..])
    } else {
        value.to_string()
    }
}

fn resolve_provider_cli_path(command_line: &str) -> Option<String> {
    let program = provider_validation_command_program_token(command_line);
    if program.trim().is_empty() {
        return None;
    }
    let expanded = provider_validation_expand_home_path(&program);
    if expanded.starts_with('/') {
        let path = Path::new(&expanded);
        if path.exists() && path.is_file() {
            return Some(expanded);
        }
        return None;
    }
    let output = std::process::Command::new("which")
        .arg(&expanded)
        .env("PATH", provider_validation_rich_path())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(str::to_string)
}

fn non_empty(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn provider_launch_command(provider: &ProviderMetadata) -> Option<String> {
    provider
        .launch_methods
        .iter()
        .find_map(|method| non_empty(Some(method.bin.as_str())))
        .or_else(|| non_empty(provider.bin.as_deref()))
        .or_else(|| {
            provider
                .install
                .cli_names
                .iter()
                .find_map(|name| non_empty(Some(name.as_str())))
        })
        .or_else(|| non_empty(Some(provider.id.as_str())))
}

fn provider_external_cli_env(provider: &ProviderMetadata) -> Vec<String> {
    let mut keys = Vec::new();
    if non_empty(provider.external_cli.auth_token.as_deref()).is_some() {
        keys.push("ANTHROPIC_AUTH_TOKEN".to_string());
    }
    if non_empty(provider.external_cli.upstream_base_url.as_deref()).is_some() {
        keys.push("ANTHROPIC_BASE_URL".to_string());
    }
    if non_empty(provider.external_cli.model.as_deref()).is_some() {
        keys.push("ANTHROPIC_MODEL".to_string());
    }
    keys
}

fn validation_check(
    id: &str,
    label: &str,
    ok: bool,
    severity: &str,
    detail: Option<String>,
    remediation: Option<String>,
) -> ProviderValidationCheck {
    ProviderValidationCheck {
        id: id.to_string(),
        label: label.to_string(),
        ok,
        severity: severity.to_string(),
        detail,
        remediation,
    }
}

fn report_status(checks: &[ProviderValidationCheck], provider_found: bool) -> String {
    if !provider_found {
        return "missing_provider".to_string();
    }
    if checks
        .iter()
        .any(|check| check.id == "cli_available" && !check.ok && check.severity == "error")
    {
        return "missing_cli".to_string();
    }
    if checks
        .iter()
        .any(|check| !check.ok && check.severity == "error")
    {
        return "misconfigured".to_string();
    }
    "ready".to_string()
}

fn build_provider_validation_report<F>(
    provider_id: &str,
    provider: Option<ProviderMetadata>,
    config_path: String,
    resolve_cli: F,
) -> ProviderValidationReport
where
    F: Fn(&str) -> Option<String>,
{
    let normalized_provider_id = provider_id.trim().to_string();
    let provider_config_found = provider.is_some();
    let mut checks = vec![validation_check(
        "provider_config",
        "Provider config",
        provider_config_found,
        if provider_config_found {
            "info"
        } else {
            "error"
        },
        if provider_config_found {
            Some(format!(
                "{} found in config metadata.",
                normalized_provider_id
            ))
        } else {
            Some(format!(
                "{} is not present in provider metadata.",
                normalized_provider_id
            ))
        },
        (!provider_config_found).then(|| "Save or materialize provider config first.".to_string()),
    )];

    let mut cli_path = None;
    let mut env_materialized = Vec::new();
    let mut runtime_id = None;
    let mut bin = None;

    if let Some(provider) = provider {
        runtime_id = Some(provider.runtime_id.clone());
        let launch_command = provider_launch_command(&provider);
        bin = launch_command.clone();
        checks.push(validation_check(
            "launch_command",
            "Launch command",
            launch_command.is_some(),
            if launch_command.is_some() {
                "info"
            } else {
                "error"
            },
            launch_command
                .as_ref()
                .map(|command| format!("Using `{}`.", command))
                .or_else(|| Some("No launch command is configured.".to_string())),
            launch_command
                .is_none()
                .then(|| "Set the provider launch command and save the provider card.".to_string()),
        ));

        if let Some(command) = launch_command.as_deref() {
            cli_path = resolve_cli(command);
            let cli_ok = cli_path.is_some();
            checks.push(validation_check(
                "cli_available",
                "CLI available",
                cli_ok,
                if cli_ok { "info" } else { "error" },
                cli_path
                    .as_ref()
                    .map(|path| format!("Resolved to `{}`.", path))
                    .or_else(|| Some(format!("Could not resolve `{}` on the app PATH.", command))),
                (!cli_ok).then(|| "Install the CLI or set an absolute launcher path.".to_string()),
            ));
        }

        let supports_send = provider.capabilities.sessions && provider.capabilities.send;
        checks.push(validation_check(
            "session_send_capability",
            "Session send capability",
            supports_send,
            if supports_send { "info" } else { "warning" },
            if supports_send {
                Some("Provider declares session list and send support.".to_string())
            } else {
                Some("Provider does not declare full Session send support.".to_string())
            },
            (!supports_send)
                .then(|| "This provider may not be usable from the Sessions tab.".to_string()),
        ));

        env_materialized = provider_external_cli_env(&provider);
        let external_cli_mode = provider
            .capabilities
            .message_rewrite
            .external_cli
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .unwrap_or("");
        let uses_anthropic_env_cli = external_cli_mode == "http_proxy";
        if uses_anthropic_env_cli || !env_materialized.is_empty() {
            checks.push(validation_check(
                "external_cli_env",
                "External CLI runtime env",
                !env_materialized.is_empty(),
                if env_materialized.is_empty() { "warning" } else { "info" },
                if env_materialized.is_empty() {
                    Some("No external CLI env keys are configured; native CLI auth may still be used.".to_string())
                } else {
                    Some(format!("Will materialize {}.", env_materialized.join(", ")))
                },
                None,
            ));
        }
    }

    let status = report_status(&checks, provider_config_found);
    let ok = !checks
        .iter()
        .any(|check| !check.ok && check.severity == "error");
    let has_warning = checks
        .iter()
        .any(|check| !check.ok && check.severity == "warning");
    let summary = if ok && has_warning {
        "Required checks passed; review warnings before using this provider.".to_string()
    } else if ok {
        "Configuration ready for lightweight provider startup checks.".to_string()
    } else {
        checks
            .iter()
            .find(|check| !check.ok && check.severity == "error")
            .and_then(|check| check.detail.clone())
            .unwrap_or_else(|| "Provider configuration is not ready.".to_string())
    };

    ProviderValidationReport {
        provider_id: normalized_provider_id,
        ok,
        status,
        summary,
        checks,
        sources: ProviderValidationSources {
            config_path,
            provider_config_found,
            cli_path,
            env_materialized,
            runtime_id,
            bin,
        },
    }
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
pub async fn validate_provider_config(
    provider_id: String,
) -> Result<ProviderValidationReport, String> {
    let providers = read_provider_metadata_from_disk()?;
    let normalized_provider_id = provider_id.trim().to_string();
    let provider = providers
        .into_iter()
        .find(|provider| provider.id == normalized_provider_id);
    Ok(build_provider_validation_report(
        &normalized_provider_id,
        provider,
        config_path().to_string_lossy().to_string(),
        resolve_provider_cli_path,
    ))
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

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    use serde_yaml::Value;

    use super::{
        build_provider_validation_report, config_path, create_default_config, default_env_template,
        env_path, is_sensitive_key, read_config, sanitize_env_content, set_provider_flags,
        set_test_home_override, write_config,
    };
    use crate::commands::config_provider::{
        provider_default_metadata, public_default_provider_ids, ProviderExternalCliConfig,
        ProviderMetadata,
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

    #[test]
    fn validate_provider_config_reports_cli_and_external_env_checks() {
        let provider = ProviderMetadata {
            id: "claude".to_string(),
            runtime_id: "claude".to_string(),
            label: "Claude".to_string(),
            description: "Claude provider".to_string(),
            visible: true,
            visibility: "public".to_string(),
            managed: true,
            autostart: false,
            bin: Some("claude".to_string()),
            transport: crate::commands::config_provider::ProviderTransportMetadata {
                owner: "stdio".to_string(),
                live: "owner_bridge".to_string(),
                kind: "stdio".to_string(),
                app_server_port: None,
                app_server_url: None,
            },
            live_transport: "owner_bridge".to_string(),
            control_mode: None,
            capabilities: crate::commands::config_provider::ProviderCapabilitiesEntry {
                sessions: true,
                send: true,
                ..Default::default()
            },
            message_hooks: crate::commands::config_provider::ProviderMessageHooksMetadata {
                abusive_language_normalization:
                    crate::commands::config_provider::ProviderMessageHookStatus {
                        enabled: true,
                        mode: "none".to_string(),
                    },
            },
            external_cli: ProviderExternalCliConfig {
                upstream_base_url: Some("https://anthropic.example.test".to_string()),
                auth_token: Some("secret-token".to_string()),
                model: Some("claude-sonnet".to_string()),
                launches_managed_child_cli: false,
            },
            launch_methods: Vec::new(),
            install: Default::default(),
            process: Default::default(),
            discovery: Default::default(),
            tui_host: Default::default(),
            icon: None,
        };

        let report = build_provider_validation_report(
            "claude",
            Some(provider),
            "/tmp/OnlineWorker/config.yaml".to_string(),
            |_| Some("/opt/homebrew/bin/claude".to_string()),
        );

        assert!(report.ok);
        assert_eq!(report.status, "ready");
        assert!(report.sources.provider_config_found);
        assert_eq!(
            report.sources.cli_path.as_deref(),
            Some("/opt/homebrew/bin/claude")
        );
        assert_eq!(
            report.sources.env_materialized,
            vec![
                "ANTHROPIC_AUTH_TOKEN".to_string(),
                "ANTHROPIC_BASE_URL".to_string(),
                "ANTHROPIC_MODEL".to_string()
            ]
        );
        assert!(report.checks.iter().any(|check| {
            check.id == "external_cli_env" && check.ok && check.severity == "info"
        }));
    }

    #[test]
    fn validate_provider_config_marks_missing_cli_as_error() {
        let provider = provider_default_metadata("claude");

        let report = build_provider_validation_report(
            "claude",
            Some(provider),
            "/tmp/OnlineWorker/config.yaml".to_string(),
            |_| None,
        );

        assert!(!report.ok);
        assert_eq!(report.status, "missing_cli");
        assert!(report.checks.iter().any(|check| {
            check.id == "cli_available" && !check.ok && check.severity == "error"
        }));
    }

    #[test]
    fn validate_provider_config_summarizes_external_cli_env_warning() {
        let provider = provider_default_metadata("claude");

        let report = build_provider_validation_report(
            "claude",
            Some(provider),
            "/tmp/OnlineWorker/config.yaml".to_string(),
            |_| Some("/opt/homebrew/bin/claude".to_string()),
        );

        assert!(report.ok);
        assert_eq!(report.status, "ready");
        assert!(report.checks.iter().any(|check| {
            check.id == "external_cli_env" && !check.ok && check.severity == "warning"
        }));
        assert_eq!(
            report.summary,
            "Required checks passed; review warnings before using this provider."
        );
    }

    #[test]
    fn validate_provider_config_does_not_warn_codex_remote_proxy_about_anthropic_env() {
        let provider = provider_default_metadata("codex");

        let report = build_provider_validation_report(
            "codex",
            Some(provider),
            "/tmp/OnlineWorker/config.yaml".to_string(),
            |_| Some("/opt/homebrew/bin/codex".to_string()),
        );

        assert!(report.ok);
        assert_eq!(report.status, "ready");
        assert_eq!(
            report.summary,
            "Configuration ready for lightweight provider startup checks."
        );
        assert!(report
            .checks
            .iter()
            .all(|check| check.id != "external_cli_env"));
        assert!(report.sources.env_materialized.is_empty());
    }
}
