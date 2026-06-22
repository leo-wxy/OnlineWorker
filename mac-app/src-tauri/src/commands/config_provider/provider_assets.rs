const BUILTIN_PROVIDER_CODEX_MANIFEST: &str =
    include_str!("../../../../../plugins/providers/builtin/codex/plugin.yaml");
const BUILTIN_PROVIDER_CLAUDE_MANIFEST: &str =
    include_str!("../../../../../plugins/providers/builtin/claude/plugin.yaml");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/plugin.yaml");
const BUILTIN_PROVIDER_CODEX_ICON: &str =
    include_str!("../../../../../plugins/providers/builtin/codex/icon.svg");
const BUILTIN_PROVIDER_CLAUDE_ICON: &str =
    include_str!("../../../../../plugins/providers/builtin/claude/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_ICON: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_ZH: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/guides/setup.zh-CN.html");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_EN: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/guides/setup.en-US.html");

pub(super) struct BuiltinProviderAsset {
    pub(super) manifest: &'static str,
    pub(super) icon_svg: &'static str,
}

impl BuiltinProviderAsset {
    pub(super) fn id(&self) -> Option<&str> {
        manifest_id(self.manifest)
    }
}

fn manifest_id(source: &str) -> Option<&str> {
    source.lines().find_map(|line| {
        let raw = line.trim();
        let id = raw.strip_prefix("id:")?.trim();
        let id = id.trim_matches('"').trim_matches('\'').trim();
        if id.is_empty() {
            None
        } else {
            Some(id)
        }
    })
}

const BUILTIN_PROVIDER_ASSETS: &[BuiltinProviderAsset] = &[
    BuiltinProviderAsset {
        manifest: BUILTIN_PROVIDER_CODEX_MANIFEST,
        icon_svg: BUILTIN_PROVIDER_CODEX_ICON,
    },
    BuiltinProviderAsset {
        manifest: BUILTIN_PROVIDER_CLAUDE_MANIFEST,
        icon_svg: BUILTIN_PROVIDER_CLAUDE_ICON,
    },
];

pub(super) fn builtin_provider_assets() -> &'static [BuiltinProviderAsset] {
    BUILTIN_PROVIDER_ASSETS
}

pub(super) fn builtin_notification_manifest(notification_id: &str) -> Option<&'static str> {
    match notification_id {
        "telegram" => Some(BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST),
        _ => None,
    }
}

pub(super) fn builtin_provider_icon_svg(provider_id: &str) -> Option<&'static str> {
    builtin_provider_assets()
        .iter()
        .find(|asset| asset.id() == Some(provider_id))
        .map(|asset| asset.icon_svg)
}

pub(super) fn builtin_notification_icon_svg(notification_id: &str) -> Option<&'static str> {
    match notification_id {
        "telegram" => Some(BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_ICON),
        _ => None,
    }
}

pub(super) fn builtin_notification_guide_html(
    notification_id: &str,
    asset_path: &str,
) -> Option<&'static str> {
    match (notification_id, asset_path) {
        ("telegram", "guides/setup.zh-CN.html") => Some(BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_ZH),
        ("telegram", "guides/setup.en-US.html") => Some(BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_EN),
        _ => None,
    }
}
