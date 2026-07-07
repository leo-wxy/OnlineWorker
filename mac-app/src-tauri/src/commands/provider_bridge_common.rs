use std::path::{Path, PathBuf};

use super::config::read_provider_metadata_from_disk;
use super::config_provider::ProviderMetadata;

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

pub fn provider_owner_bridge_socket_path(data_dir: &Path) -> PathBuf {
    data_dir.join("provider_owner_bridge.sock")
}
