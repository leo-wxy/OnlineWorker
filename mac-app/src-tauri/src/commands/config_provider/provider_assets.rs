const BUILTIN_CODEX_PLUGIN_MANIFEST: &str =
    include_str!("../../../../../plugins/providers/builtin/codex/plugin.yaml");
const BUILTIN_CLAUDE_PLUGIN_MANIFEST: &str =
    include_str!("../../../../../plugins/providers/builtin/claude/plugin.yaml");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/plugin.yaml");
const BUILTIN_CODEX_PLUGIN_ICON: &str =
    include_str!("../../../../../plugins/providers/builtin/codex/icon.svg");
const BUILTIN_CLAUDE_PLUGIN_ICON: &str =
    include_str!("../../../../../plugins/providers/builtin/claude/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_ICON: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/icon.svg");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_ZH: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/guides/setup.zh-CN.html");
const BUILTIN_TELEGRAM_NOTIFICATION_GUIDE_EN: &str =
    include_str!("../../../../../plugins/notifications/builtin/telegram/guides/setup.en-US.html");

pub(super) fn builtin_provider_manifest(provider_id: &str) -> Option<&'static str> {
    match provider_id {
        "codex" => Some(BUILTIN_CODEX_PLUGIN_MANIFEST),
        "claude" => Some(BUILTIN_CLAUDE_PLUGIN_MANIFEST),
        _ => None,
    }
}

pub(super) fn builtin_notification_manifest(notification_id: &str) -> Option<&'static str> {
    match notification_id {
        "telegram" => Some(BUILTIN_TELEGRAM_NOTIFICATION_PLUGIN_MANIFEST),
        _ => None,
    }
}

pub(super) fn builtin_provider_icon_svg(provider_id: &str) -> Option<&'static str> {
    match provider_id {
        "codex" => Some(BUILTIN_CODEX_PLUGIN_ICON),
        "claude" => Some(BUILTIN_CLAUDE_PLUGIN_ICON),
        _ => None,
    }
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
