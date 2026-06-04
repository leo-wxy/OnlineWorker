use std::path::{Path, PathBuf};

use super::config::read_provider_metadata_from_disk;
use super::config_provider::ProviderMetadata;

pub const PROVIDER_OVERLAY_ENV: &str = "ONLINEWORKER_PROVIDER_OVERLAY";
const PYINSTALLER_RESET_ENVIRONMENT_ENV: &str = "PYINSTALLER_RESET_ENVIRONMENT";

pub fn provider_not_enabled_message(provider_id: &str) -> String {
    format!("Provider '{}' is not enabled", provider_id.trim())
}

pub fn require_runtime_provider(provider_id: &str) -> Result<ProviderMetadata, String> {
    let normalized = provider_id.trim();
    if normalized.is_empty() {
        return Err(provider_not_enabled_message("unknown"));
    }

    read_provider_metadata_from_disk()?
        .into_iter()
        .find(|provider| provider.id == normalized)
        .ok_or_else(|| provider_not_enabled_message(normalized))
}

pub fn provider_bridge_path(home: &str) -> String {
    format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    )
}

fn provider_overlay_env_spec_from_app_env(data_dir: &Path) -> Option<String> {
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

fn provider_overlay_env_spec(data_dir: &Path) -> Option<String> {
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
        .or_else(|| provider_overlay_env_spec_from_app_env(data_dir))
}

pub fn provider_bridge_env(data_dir: &Path) -> Vec<(String, String)> {
    let home = std::env::var("HOME").unwrap_or_default();
    let mut envs = vec![
        ("PATH".to_string(), provider_bridge_path(&home)),
        ("HOME".to_string(), home),
        ("LANG".to_string(), "en_US.UTF-8".to_string()),
        (
            PYINSTALLER_RESET_ENVIRONMENT_ENV.to_string(),
            "1".to_string(),
        ),
    ];
    if let Some(overlay_env) = provider_overlay_env_spec(data_dir) {
        envs.push((PROVIDER_OVERLAY_ENV.to_string(), overlay_env));
    }
    envs
}

pub fn provider_owner_bridge_socket_path(data_dir: &Path) -> PathBuf {
    data_dir.join("provider_owner_bridge.sock")
}
