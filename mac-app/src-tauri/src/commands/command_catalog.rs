use super::command_registry::{CommandBackend, CommandScope, CommandSource, DiscoveredCommand};
use super::config_provider::provider_plugin_manifest_sources;
use serde::Deserialize;
use std::collections::HashSet;

fn discovered(
    id: &str,
    name: &str,
    source: CommandSource,
    backend: CommandBackend,
    scope: CommandScope,
    description: &str,
) -> DiscoveredCommand {
    DiscoveredCommand {
        id: id.to_string(),
        name: name.to_string(),
        source,
        backend,
        scope,
        description: description.to_string(),
    }
}

#[derive(Deserialize, Default)]
struct ProviderCommandCatalogManifest {
    id: String,
    kind: Option<String>,
    provider: Option<ProviderCommandCatalogConfig>,
}

#[derive(Deserialize, Default)]
struct ProviderCommandCatalogConfig {
    #[serde(default)]
    commands: Vec<ProviderCommandCatalogEntry>,
}

#[derive(Deserialize, Default)]
struct ProviderCommandCatalogEntry {
    name: String,
    description: Option<String>,
    scope: Option<String>,
}

fn command_scope_from_manifest(raw: Option<&str>) -> CommandScope {
    match raw.unwrap_or("thread").trim().to_lowercase().as_str() {
        "global" => CommandScope::Global,
        "workspace" => CommandScope::Workspace,
        _ => CommandScope::Thread,
    }
}

pub fn bot_commands() -> Vec<DiscoveredCommand> {
    vec![
        discovered(
            "bot:start",
            "start",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "启动 bot 并显示帮助入口",
        ),
        discovered(
            "bot:ping",
            "ping",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "检查 bot 是否存活",
        ),
        discovered(
            "bot:echo",
            "echo",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "原样回显文本",
        ),
        discovered(
            "bot:help",
            "help",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "查看 onlineWorker 帮助",
        ),
        discovered(
            "bot:status",
            "status",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "查看 bot 和服务状态",
        ),
        discovered(
            "bot:active",
            "active",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "查看当前活跃 workspace/thread",
        ),
        discovered(
            "bot:cli",
            "cli",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "打开 CLI 相关入口",
        ),
        discovered(
            "bot:workspace",
            "workspace",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "列出并打开 workspace",
        ),
        discovered(
            "bot:new",
            "new",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Workspace,
            "在当前 workspace 新建 thread",
        ),
        discovered(
            "bot:list",
            "list",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Workspace,
            "列出当前 workspace 下的 thread",
        ),
        discovered(
            "bot:archive",
            "archive",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Thread,
            "归档当前 thread",
        ),
        discovered(
            "bot:skills",
            "skills",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Thread,
            "查看当前 thread 可用 skills",
        ),
        discovered(
            "bot:history",
            "history",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Thread,
            "查看当前 thread 历史",
        ),
        discovered(
            "bot:restart",
            "restart",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "重启 bot",
        ),
        discovered(
            "bot:stop",
            "stop",
            CommandSource::Bot,
            CommandBackend::Local,
            CommandScope::Global,
            "停止 bot",
        ),
    ]
}

pub(crate) fn downstream_commands_from_manifest_source(
    source: &str,
) -> Result<Vec<DiscoveredCommand>, String> {
    let manifest: ProviderCommandCatalogManifest = serde_yaml::from_str(source)
        .map_err(|error| format!("provider manifest parse failed: {error}"))?;
    if manifest.kind.as_deref() != Some("provider") {
        return Ok(Vec::new());
    }
    let provider_id = manifest.id.trim().to_lowercase();
    if provider_id.is_empty() {
        return Ok(Vec::new());
    }

    let commands = manifest
        .provider
        .unwrap_or_default()
        .commands
        .into_iter()
        .filter_map(|command| {
            let name = command.name.trim().to_string();
            if name.is_empty() {
                return None;
            }
            Some(discovered(
                &format!("downstream:{provider_id}:{name}"),
                &name,
                CommandSource::Downstream,
                CommandBackend::provider(&provider_id),
                command_scope_from_manifest(command.scope.as_deref()),
                command.description.as_deref().unwrap_or(""),
            ))
        })
        .collect();
    Ok(commands)
}

fn all_downstream_commands() -> Vec<DiscoveredCommand> {
    provider_plugin_manifest_sources()
        .into_iter()
        .filter_map(|source| downstream_commands_from_manifest_source(&source).ok())
        .flatten()
        .collect()
}

pub fn downstream_commands_for_visible_provider_ids<I, S>(provider_ids: I) -> Vec<DiscoveredCommand>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let visible = provider_ids
        .into_iter()
        .map(|id| id.as_ref().trim().to_lowercase())
        .collect::<HashSet<_>>();

    all_downstream_commands()
        .into_iter()
        .filter(|command| {
            command
                .backend
                .provider_id()
                .map(|provider_id| visible.contains(provider_id))
                .unwrap_or(true)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::{
        downstream_commands_for_visible_provider_ids, downstream_commands_from_manifest_source,
    };
    use crate::commands::command_registry::CommandBackend;

    #[test]
    fn public_default_downstream_catalog_omits_private_provider() {
        let ids = downstream_commands_for_visible_provider_ids(["codex", "claude"])
            .into_iter()
            .map(|command| command.id)
            .collect::<Vec<_>>();

        assert!(ids.contains(&"downstream:codex:help".to_string()));
        assert!(!ids.contains(&"downstream:private-provider:help".to_string()));
    }

    #[test]
    fn provider_manifest_can_register_unknown_provider_commands() {
        let commands = downstream_commands_from_manifest_source(
            r#"
schema_version: 1
id: opencode
kind: provider
provider:
  commands:
    - name: status
      scope: thread
      description: Inspect OpenCode session state
"#,
        )
        .expect("manifest command catalog");

        assert_eq!(commands.len(), 1);
        assert_eq!(commands[0].id, "downstream:opencode:status");
        assert_eq!(commands[0].name, "status");
        assert_eq!(
            commands[0].backend,
            CommandBackend::Provider("opencode".to_string())
        );
    }
}
