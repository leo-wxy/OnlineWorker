use serde::Deserialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use base64::Engine;

use super::{
    normalize_provider_document_with_env, provider_assets, NotificationChannelConfigEntry,
    NotificationChannelMetadata, NotificationConfigDocument, NotificationSettingsField,
    NotificationSetupGuide, ProviderConfigDocument, ProviderIconEntry,
    ProviderPluginManifestSource,
};

#[derive(Deserialize, Default, Clone, Debug)]
struct NotificationSettingsManifest {
    fields: Option<Vec<NotificationSettingsField>>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct NotificationSetupGuideManifest {
    #[serde(rename = "type", default)]
    kind: String,
    #[serde(default)]
    assets: BTreeMap<String, String>,
}

#[derive(Clone, Debug)]
pub(super) struct NotificationPluginDefault {
    pub(super) id: String,
    pub(super) label: String,
    pub(super) description: String,
    pub(super) default_enabled: bool,
    pub(super) builtin: bool,
    pub(super) order: u32,
    pub(super) settings_fields: Vec<NotificationSettingsField>,
    pub(super) icon: Option<ProviderIconEntry>,
    pub(super) setup_guide: Option<NotificationSetupGuide>,
}

#[derive(Deserialize, Default, Clone, Debug)]
struct NotificationPluginManifest {
    id: String,
    kind: Option<String>,
    order: Option<u32>,
    label: Option<String>,
    description: Option<String>,
    default_enabled: Option<bool>,
    icon: Option<ProviderIconEntry>,
    #[serde(skip)]
    manifest_path: Option<PathBuf>,
    settings: Option<NotificationSettingsManifest>,
    setup_guide: Option<NotificationSetupGuideManifest>,
}

pub(super) fn normalize_notification_document(doc: &mut ProviderConfigDocument) {
    let notifications = doc
        .notifications
        .get_or_insert_with(NotificationConfigDocument::default);
    let channels = notifications.channels.get_or_insert_with(BTreeMap::new);

    for default in
        notification_plugin_default_list(super::notification_plugin_manifest_sources_with_paths())
    {
        let channel = channels.entry(default.id.clone()).or_default();
        channel.enabled = Some(channel.enabled.unwrap_or(default.default_enabled));
        channel.label.get_or_insert_with(|| default.label.clone());
        channel
            .description
            .get_or_insert_with(|| default.description.clone());
        channel.config.get_or_insert_with(BTreeMap::new);
    }

    for (channel_id, channel) in channels.iter_mut() {
        channel.enabled = Some(channel.enabled.unwrap_or(false));
        channel.label.get_or_insert_with(|| channel_id.to_string());
        channel.description.get_or_insert_with(String::new);
        channel.config.get_or_insert_with(BTreeMap::new);
    }
}

pub(crate) fn notification_channel_metadata_from_raw(
    raw: &str,
    env_raw: Option<&str>,
) -> Result<Vec<NotificationChannelMetadata>, String> {
    let doc = normalize_provider_document_with_env(raw, env_raw)?;
    let channels = doc
        .notifications
        .and_then(|notifications| notifications.channels)
        .unwrap_or_default();

    Ok(notification_channel_metadata_from_channels(channels))
}

fn notification_channel_metadata_from_channels(
    channels: BTreeMap<String, NotificationChannelConfigEntry>,
) -> Vec<NotificationChannelMetadata> {
    let mut ordered = Vec::new();
    let plugin_defaults =
        notification_plugin_default_list(super::notification_plugin_manifest_sources_with_paths());
    for default in &plugin_defaults {
        if let Some(channel) = channels.get(&default.id) {
            ordered.push(notification_channel_metadata_from_entry(
                &default.id,
                channel,
                &default.label,
                &default.description,
                default.builtin,
                default.settings_fields.clone(),
                default.icon.clone(),
                default.setup_guide.clone(),
            ));
        }
    }

    for (channel_id, channel) in channels {
        if plugin_defaults
            .iter()
            .any(|default| default.id == channel_id)
        {
            continue;
        }
        let label = channel.label.as_deref().unwrap_or(&channel_id);
        let description = channel.description.as_deref().unwrap_or("");
        ordered.push(notification_channel_metadata_from_entry(
            &channel_id,
            &channel,
            label,
            description,
            false,
            Vec::new(),
            None,
            None,
        ));
    }

    ordered
}

fn notification_plugin_default_list(
    manifest_sources: Vec<ProviderPluginManifestSource>,
) -> Vec<NotificationPluginDefault> {
    let mut defaults = Vec::new();
    for manifest_source in manifest_sources {
        let Ok(mut manifest) =
            serde_yaml::from_str::<NotificationPluginManifest>(&manifest_source.source)
        else {
            continue;
        };
        manifest.manifest_path = Some(manifest_source.path.clone());
        if manifest.kind.as_deref() != Some("notification") {
            continue;
        }
        let notification_id = manifest.id.trim().to_string();
        if notification_id.is_empty() {
            continue;
        }
        let builtin = manifest_source
            .path
            .components()
            .any(|component| component.as_os_str() == "builtin");
        defaults.push(NotificationPluginDefault {
            id: notification_id.clone(),
            label: manifest.label.unwrap_or_else(|| notification_id.clone()),
            description: manifest.description.unwrap_or_default(),
            default_enabled: manifest.default_enabled.unwrap_or(true),
            builtin,
            order: manifest.order.unwrap_or(u32::MAX),
            settings_fields: normalize_notification_settings_fields(
                manifest
                    .settings
                    .and_then(|settings| settings.fields)
                    .unwrap_or_default(),
            ),
            icon: resolve_notification_icon(
                manifest.icon,
                manifest.manifest_path.as_deref(),
                &notification_id,
            ),
            setup_guide: resolve_notification_setup_guide(
                manifest.setup_guide,
                manifest.manifest_path.as_deref(),
                &notification_id,
            ),
        });
    }
    defaults.sort_by(|left, right| {
        left.order
            .cmp(&right.order)
            .then_with(|| left.id.cmp(&right.id))
    });
    defaults
}

#[allow(clippy::too_many_arguments)]
fn notification_channel_metadata_from_entry(
    channel_id: &str,
    channel: &NotificationChannelConfigEntry,
    default_label: &str,
    default_description: &str,
    builtin: bool,
    settings_fields: Vec<NotificationSettingsField>,
    icon: Option<ProviderIconEntry>,
    setup_guide: Option<NotificationSetupGuide>,
) -> NotificationChannelMetadata {
    NotificationChannelMetadata {
        id: channel_id.to_string(),
        label: channel
            .label
            .clone()
            .filter(|value| !value.trim().is_empty())
            .unwrap_or_else(|| default_label.to_string()),
        description: channel
            .description
            .clone()
            .unwrap_or_else(|| default_description.to_string()),
        enabled: channel.enabled.unwrap_or(false),
        builtin,
        config: channel.config.clone().unwrap_or_default(),
        settings_fields,
        icon,
        setup_guide,
    }
}

fn normalize_notification_settings_fields(
    fields: Vec<NotificationSettingsField>,
) -> Vec<NotificationSettingsField> {
    fields
        .into_iter()
        .filter_map(|mut field| {
            field.key = field.key.trim().to_string();
            if field.key.is_empty() {
                return None;
            }
            field.label = if field.label.trim().is_empty() {
                field.key.clone()
            } else {
                field.label.trim().to_string()
            };
            field.kind = normalize_notification_field_type(&field.kind);
            field.description = field.description.trim().to_string();
            for option in field.options.iter_mut() {
                option.value = option.value.trim().to_string();
                if option.label.trim().is_empty() {
                    option.label = option.value.clone();
                } else {
                    option.label = option.label.trim().to_string();
                }
            }
            Some(field)
        })
        .collect()
}

fn normalize_notification_field_type(kind: &str) -> String {
    match kind.trim() {
        "string" | "number" | "boolean" | "select" | "secret" => kind.trim().to_string(),
        _ => "string".to_string(),
    }
}

fn resolve_notification_icon(
    icon: Option<ProviderIconEntry>,
    manifest_path: Option<&Path>,
    notification_id: &str,
) -> Option<ProviderIconEntry> {
    let mut icon = super::resolve_provider_icon(icon, manifest_path, notification_id)?;
    if icon.url.trim().is_empty() && icon.path.trim() == "icon.svg" {
        if let Some(svg) = provider_assets::builtin_notification_icon_svg(notification_id) {
            let encoded = base64::engine::general_purpose::STANDARD.encode(svg);
            icon.url = format!("data:image/svg+xml;base64,{encoded}");
            icon.generated_url = true;
        }
    }
    Some(icon)
}

fn resolve_notification_setup_guide(
    guide: Option<NotificationSetupGuideManifest>,
    manifest_path: Option<&Path>,
    notification_id: &str,
) -> Option<NotificationSetupGuide> {
    let guide = guide?;
    if guide.kind.trim() != "html" {
        return None;
    }
    let mut assets = BTreeMap::new();
    for (locale, asset_path) in guide.assets {
        let locale = locale.trim().to_string();
        if locale.is_empty() {
            continue;
        }
        if let Some(html) =
            read_notification_guide_asset(notification_id, manifest_path, asset_path.trim())
        {
            assets.insert(locale, html);
        }
    }
    if assets.is_empty() {
        None
    } else {
        Some(NotificationSetupGuide {
            kind: "html".to_string(),
            assets,
        })
    }
}

fn read_notification_guide_asset(
    notification_id: &str,
    manifest_path: Option<&Path>,
    asset_path: &str,
) -> Option<String> {
    if !is_safe_relative_asset_path(asset_path) {
        return None;
    }
    let file_asset = manifest_path.and_then(Path::parent).and_then(|dir| {
        let base = dir.canonicalize().ok()?;
        let target = dir.join(asset_path).canonicalize().ok()?;
        if !target.starts_with(&base) || !target.is_file() {
            return None;
        }
        fs::read_to_string(target).ok()
    });
    file_asset.or_else(|| {
        provider_assets::builtin_notification_guide_html(notification_id, asset_path)
            .map(str::to_string)
    })
}

fn is_safe_relative_asset_path(asset_path: &str) -> bool {
    let path = Path::new(asset_path);
    !asset_path.trim().is_empty()
        && path.is_relative()
        && path.components().all(|component| {
            matches!(
                component,
                std::path::Component::Normal(_) | std::path::Component::CurDir
            )
        })
}
