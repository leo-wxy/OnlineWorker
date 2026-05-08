use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use super::command_catalog::{bot_commands, downstream_commands_for_visible_provider_ids};
use super::config::ensure_data_dir;
use super::config::read_visible_provider_ids_from_disk;
use super::config_provider::public_default_provider_ids;
use super::telegram::{publish_scoped_commands, TelegramCommandScope};

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum CommandSource {
    Bot,
    Downstream,
    Skill,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CommandBackend {
    Local,
    Shared,
    Provider(String),
}

impl CommandBackend {
    pub(crate) fn provider(provider_id: &str) -> Self {
        CommandBackend::Provider(provider_id.trim().to_lowercase())
    }

    pub(crate) fn as_str(&self) -> &str {
        match self {
            CommandBackend::Local => "local",
            CommandBackend::Shared => "shared",
            CommandBackend::Provider(provider_id) => provider_id.as_str(),
        }
    }

    pub(crate) fn provider_id(&self) -> Option<&str> {
        match self {
            CommandBackend::Provider(provider_id) => Some(provider_id.as_str()),
            CommandBackend::Local | CommandBackend::Shared => None,
        }
    }
}

impl Serialize for CommandBackend {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for CommandBackend {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        let normalized = value.trim().to_lowercase();
        Ok(match normalized.as_str() {
            "local" => CommandBackend::Local,
            "both" | "shared" => CommandBackend::Shared,
            provider_id => CommandBackend::provider(provider_id),
        })
    }
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum CommandScope {
    Global,
    Workspace,
    Thread,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum CommandStatus {
    Active,
    Missing,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CommandRegistryEntry {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub telegram_name: String,
    pub source: CommandSource,
    pub backend: CommandBackend,
    pub scope: CommandScope,
    pub description: String,
    pub enabled_for_telegram: bool,
    pub published_to_telegram: bool,
    pub status: CommandStatus,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DiscoveredCommand {
    pub id: String,
    pub name: String,
    pub source: CommandSource,
    pub backend: CommandBackend,
    pub scope: CommandScope,
    pub description: String,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
pub struct CommandRegistryStore {
    pub commands: Vec<CommandRegistryEntry>,
    pub last_refreshed_epoch: Option<u64>,
    pub last_published_epoch: Option<u64>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CommandRegistryResponse {
    pub commands: Vec<CommandRegistryEntry>,
    pub last_refreshed_epoch: Option<u64>,
    pub last_published_epoch: Option<u64>,
    pub has_unpublished_changes: bool,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TelegramPublishCommand {
    pub command: String,
    pub description: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct TelegramPublishPlan {
    commands: Vec<TelegramPublishCommand>,
    published_names: HashSet<String>,
}

fn command_registry_path(data_dir: &Path) -> PathBuf {
    data_dir.join("command_registry.json")
}

fn merge_registry_with_discovery(
    store: &CommandRegistryStore,
    discovered: Vec<DiscoveredCommand>,
    refreshed_at_epoch: u64,
) -> CommandRegistryStore {
    let mut existing_by_id: HashMap<String, CommandRegistryEntry> = store
        .commands
        .iter()
        .cloned()
        .map(|command| (command.id.clone(), command))
        .collect();
    let mut merged = Vec::with_capacity(existing_by_id.len() + discovered.len());

    for command in discovered {
        if let Some(mut existing) = existing_by_id.remove(&command.id) {
            existing.name = command.name;
            existing.source = command.source;
            existing.backend = command.backend;
            existing.scope = command.scope;
            existing.description = command.description;
            existing.status = CommandStatus::Active;
            merged.push(existing);
        } else {
            merged.push(CommandRegistryEntry {
                id: command.id,
                name: command.name,
                telegram_name: String::new(),
                source: command.source,
                backend: command.backend,
                scope: command.scope,
                description: command.description,
                enabled_for_telegram: false,
                published_to_telegram: false,
                status: CommandStatus::Active,
            });
        }
    }

    for (_, mut stale) in existing_by_id {
        stale.status = CommandStatus::Missing;
        merged.push(stale);
    }

    sort_commands(&mut merged);
    assign_telegram_names(&mut merged);

    CommandRegistryStore {
        commands: merged,
        last_refreshed_epoch: Some(refreshed_at_epoch),
        last_published_epoch: store.last_published_epoch,
    }
}

fn build_response(store: CommandRegistryStore) -> CommandRegistryResponse {
    let has_unpublished_changes = store.commands.iter().any(|command| {
        command.published_to_telegram
            != (command.enabled_for_telegram && command.status == CommandStatus::Active)
    });

    CommandRegistryResponse {
        has_unpublished_changes,
        commands: store.commands,
        last_refreshed_epoch: store.last_refreshed_epoch,
        last_published_epoch: store.last_published_epoch,
    }
}

fn build_publishable_commands(commands: &[CommandRegistryEntry]) -> TelegramPublishPlan {
    let mut grouped: BTreeMap<String, Vec<&CommandRegistryEntry>> = BTreeMap::new();

    for command in commands {
        if !command.enabled_for_telegram || command.status != CommandStatus::Active {
            continue;
        }

        if !is_valid_telegram_command_name(&command.telegram_name) {
            continue;
        }

        grouped
            .entry(command.telegram_name.clone())
            .or_default()
            .push(command);
    }

    let published_names = grouped.keys().cloned().collect();
    let commands = grouped
        .into_iter()
        .map(|(name, entries)| TelegramPublishCommand {
            command: name.clone(),
            description: telegram_description_for_group(&name, &entries),
        })
        .collect();

    TelegramPublishPlan {
        commands,
        published_names,
    }
}

fn save_registry_store(path: &Path, store: &CommandRegistryStore) -> Result<(), String> {
    let raw = serde_json::to_string_pretty(store)
        .map_err(|error| format!("序列化 command registry 失败: {error}"))?;
    fs::write(path, raw).map_err(|error| format!("写入 command registry 失败: {error}"))
}

fn load_registry_store(path: &Path) -> Result<CommandRegistryStore, String> {
    let raw =
        fs::read_to_string(path).map_err(|error| format!("读取 command registry 失败: {error}"))?;
    let mut store: CommandRegistryStore = serde_json::from_str(&raw)
        .map_err(|error| format!("解析 command registry 失败: {error}"))?;
    sort_commands(&mut store.commands);
    assign_telegram_names(&mut store.commands);
    Ok(store)
}

fn load_or_initialize_store(data_dir: &Path) -> Result<CommandRegistryStore, String> {
    let path = command_registry_path(data_dir);
    if path.exists() {
        return load_registry_store(&path);
    }

    let initial = merge_registry_with_discovery(
        &CommandRegistryStore::default(),
        discover_commands(),
        current_epoch_seconds(),
    );
    save_registry_store(&path, &initial)?;
    Ok(initial)
}

fn update_command_enabled(
    mut store: CommandRegistryStore,
    command_id: &str,
    enabled: bool,
) -> Result<CommandRegistryStore, String> {
    let target = store
        .commands
        .iter_mut()
        .find(|command| command.id == command_id)
        .ok_or_else(|| format!("未找到命令 `{command_id}`"))?;
    target.enabled_for_telegram = enabled;
    sort_commands(&mut store.commands);
    assign_telegram_names(&mut store.commands);
    Ok(store)
}

fn apply_publish_success(
    mut store: CommandRegistryStore,
    published_names: &HashSet<String>,
    published_at_epoch: u64,
) -> CommandRegistryStore {
    for command in &mut store.commands {
        command.published_to_telegram = command.enabled_for_telegram
            && command.status == CommandStatus::Active
            && published_names.contains(&command.telegram_name);
    }
    store.last_published_epoch = Some(published_at_epoch);
    sort_commands(&mut store.commands);
    assign_telegram_names(&mut store.commands);
    store
}

fn discover_commands() -> Vec<DiscoveredCommand> {
    let skill_commands = discover_skill_commands();
    let skill_names: HashSet<String> = skill_commands
        .iter()
        .map(|command| command.name.clone())
        .collect();
    let mut commands = bot_commands();
    commands.extend(discover_downstream_commands(&skill_names));
    commands.extend(skill_commands);
    sort_discovered_commands(&mut commands);
    commands
}

fn discover_downstream_commands(_skill_names: &HashSet<String>) -> Vec<DiscoveredCommand> {
    let visible_provider_ids =
        read_visible_provider_ids_from_disk().unwrap_or_else(|_| public_default_provider_ids());
    let mut commands = downstream_commands_for_visible_provider_ids(&visible_provider_ids);
    commands.extend(discover_codex_file_commands());
    sort_discovered_commands(&mut commands);
    commands
}

fn discover_codex_file_commands() -> Vec<DiscoveredCommand> {
    discover_codex_file_commands_from_roots(&codex_command_roots())
}

fn discover_codex_file_commands_from_roots(roots: &[PathBuf]) -> Vec<DiscoveredCommand> {
    let mut discovered = Vec::new();
    let mut seen_names = HashSet::new();

    for root in roots {
        if !root.exists() {
            continue;
        }

        let mut command_files = Vec::new();
        collect_markdown_files(root, &mut command_files, None);
        command_files.sort();

        for command_file in command_files {
            let Some(relative_path) = command_file.strip_prefix(root).ok() else {
                continue;
            };
            let Some(name) = command_name_from_relative_path(relative_path) else {
                continue;
            };
            if !seen_names.insert(name.clone()) {
                continue;
            }
            let description = parse_frontmatter_description(&command_file)
                .unwrap_or_else(|| "Codex command".to_string());
            discovered.push(DiscoveredCommand {
                id: format!("downstream:codex:file:{name}"),
                name,
                source: CommandSource::Downstream,
                backend: CommandBackend::provider("codex"),
                scope: CommandScope::Thread,
                description,
            });
        }
    }

    sort_discovered_commands(&mut discovered);
    discovered
}

fn discover_skill_commands() -> Vec<DiscoveredCommand> {
    discover_skill_commands_from_roots(&skill_roots())
}

fn discover_skill_commands_from_roots(
    roots: &[(PathBuf, CommandBackend)],
) -> Vec<DiscoveredCommand> {
    let mut discovered = Vec::new();
    let mut seen_names = HashSet::new();

    for (root, backend) in roots {
        if !root.exists() {
            continue;
        }

        let mut skill_files = Vec::new();
        collect_markdown_files(root, &mut skill_files, Some("SKILL.md"));
        skill_files.sort();

        for skill_file in skill_files {
            if let Some((name, description)) = parse_skill_markdown(&skill_file) {
                if !seen_names.insert(name.clone()) {
                    continue;
                }
                discovered.push(DiscoveredCommand {
                    id: format!("skill:{name}"),
                    name,
                    source: CommandSource::Skill,
                    backend: backend.clone(),
                    scope: CommandScope::Thread,
                    description,
                });
            }
        }
    }

    sort_discovered_commands(&mut discovered);
    discovered
}

fn skill_roots() -> Vec<(PathBuf, CommandBackend)> {
    let home = std::env::var("HOME").unwrap_or_default();
    if home.is_empty() {
        return Vec::new();
    }
    let home = PathBuf::from(home);
    vec![
        // Prefer platform-specific roots before shared roots so duplicate names keep their backend.
        (
            home.join(".codex/skills"),
            CommandBackend::provider("codex"),
        ),
        (
            home.join(".codex/superpowers/skills"),
            CommandBackend::provider("codex"),
        ),
        (
            home.join(".claude/skills"),
            CommandBackend::provider("claude"),
        ),
        (home.join(".agents/skills"), CommandBackend::Shared),
        (home.join(".git-ai/skills"), CommandBackend::Shared),
        (home.join(".raven/skills"), CommandBackend::Shared),
    ]
}

fn codex_command_roots() -> Vec<PathBuf> {
    let home = std::env::var("HOME").unwrap_or_default();
    if home.is_empty() {
        return Vec::new();
    }
    let home = PathBuf::from(home);
    vec![
        home.join(".codex/commands"),
        home.join(".codex/superpowers/commands"),
        home.join(".codex/get-shit-done/commands"),
    ]
}

fn collect_markdown_files(
    root: &Path,
    output: &mut Vec<PathBuf>,
    include_only_file_name: Option<&str>,
) {
    let read_dir = match fs::read_dir(root) {
        Ok(read_dir) => read_dir,
        Err(_) => return,
    };

    for entry in read_dir.flatten() {
        let path = entry.path();
        if path.is_dir() {
            collect_markdown_files(&path, output, include_only_file_name);
        } else if path.extension().and_then(|value| value.to_str()) == Some("md") {
            if let Some(include_name) = include_only_file_name {
                if path.file_name().and_then(|value| value.to_str()) != Some(include_name) {
                    continue;
                }
            }
            output.push(path);
        }
    }
}

fn parse_skill_markdown(path: &Path) -> Option<(String, String)> {
    let (name, description) = parse_frontmatter(path);

    let name = name.or_else(|| {
        path.parent()
            .and_then(|parent| parent.file_name())
            .and_then(|name| name.to_str())
            .map(|value| value.to_string())
    })?;

    let description = description.unwrap_or_else(|| "Skill command".to_string());
    Some((name, description))
}

fn parse_frontmatter(path: &Path) -> (Option<String>, Option<String>) {
    let Ok(raw) = fs::read_to_string(path) else {
        return (None, None);
    };
    let mut lines = raw.lines();
    let mut name: Option<String> = None;
    let mut description: Option<String> = None;

    if lines.next() == Some("---") {
        for line in lines {
            if line.trim() == "---" {
                break;
            }
            let trimmed = line.trim();
            if let Some(value) = trimmed.strip_prefix("name:") {
                name = Some(unquote_yaml_value(value));
            } else if let Some(value) = trimmed.strip_prefix("description:") {
                description = Some(unquote_yaml_value(value));
            }
        }
    }

    (name, description)
}

fn parse_frontmatter_description(path: &Path) -> Option<String> {
    let (_, description) = parse_frontmatter(path);
    description
}

fn command_name_from_relative_path(relative_path: &Path) -> Option<String> {
    let mut parts = relative_path
        .iter()
        .map(|part| part.to_str())
        .collect::<Option<Vec<_>>>()?;
    if parts.is_empty() {
        return None;
    }
    let last = parts.pop()?;
    let stem = last.strip_suffix(".md")?;
    parts.push(stem);
    Some(parts.join("-"))
}

fn unquote_yaml_value(value: &str) -> String {
    value
        .trim()
        .trim_matches('"')
        .trim_matches('\'')
        .to_string()
}

fn read_env_key(data_dir: &Path, target_key: &str) -> Result<Option<String>, String> {
    let env_path = data_dir.join(".env");
    let raw = fs::read_to_string(&env_path)
        .map_err(|error| format!("读取 Telegram 配置失败: {error}"))?;

    for line in raw.lines() {
        if line.starts_with('#') || line.trim().is_empty() {
            continue;
        }
        if let Some((key, value)) = line.split_once('=') {
            if key.trim() == target_key {
                let value = value.trim().to_string();
                if value.is_empty() {
                    return Ok(None);
                }
                return Ok(Some(value));
            }
        }
    }

    Ok(None)
}

fn read_bot_token(data_dir: &Path) -> Result<String, String> {
    read_env_key(data_dir, "TELEGRAM_TOKEN")?
        .ok_or_else(|| "未找到 TELEGRAM_TOKEN，无法发布 Telegram 菜单".to_string())
}

fn read_group_chat_id(data_dir: &Path) -> Result<Option<i64>, String> {
    let Some(raw_chat_id) = read_env_key(data_dir, "GROUP_CHAT_ID")? else {
        return Ok(None);
    };
    raw_chat_id
        .parse::<i64>()
        .map(Some)
        .map_err(|error| format!("GROUP_CHAT_ID 非法，无法发布群组命令 scope: {error}"))
}

fn build_publish_scopes(group_chat_id: Option<i64>) -> Vec<TelegramCommandScope> {
    let mut scopes = vec![
        TelegramCommandScope::Default,
        TelegramCommandScope::AllGroupChats,
    ];
    if let Some(chat_id) = group_chat_id {
        scopes.push(TelegramCommandScope::Chat { chat_id });
    }
    scopes
}

fn telegram_description_for(command: &CommandRegistryEntry) -> String {
    let description = if command.description.trim().is_empty() {
        format!("Run /{}", command.telegram_name)
    } else {
        command.description.trim().to_string()
    };
    description.chars().take(256).collect()
}

fn telegram_description_for_group(name: &str, entries: &[&CommandRegistryEntry]) -> String {
    if entries.len() == 1 {
        return telegram_description_for(entries[0]);
    }

    format!("按当前 topic 执行 /{name}")
        .chars()
        .take(256)
        .collect()
}

fn is_valid_telegram_command_name(name: &str) -> bool {
    let length = name.len();
    if length == 0 || length > 32 {
        return false;
    }
    name.bytes()
        .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'_')
}

fn preferred_telegram_name(name: &str, id: &str) -> String {
    let mut normalized = String::new();
    let mut previous_was_underscore = false;

    for byte in name.bytes() {
        let mapped = if byte.is_ascii_lowercase() || byte.is_ascii_digit() {
            byte as char
        } else if byte.is_ascii_uppercase() {
            (byte as char).to_ascii_lowercase()
        } else {
            '_'
        };

        if mapped == '_' {
            if normalized.is_empty() || previous_was_underscore {
                continue;
            }
            previous_was_underscore = true;
            normalized.push(mapped);
            continue;
        }

        previous_was_underscore = false;
        normalized.push(mapped);
    }

    while normalized.ends_with('_') {
        normalized.pop();
    }

    if normalized.len() > 32 {
        normalized.truncate(32);
        while normalized.ends_with('_') {
            normalized.pop();
        }
    }

    if normalized.is_empty() {
        return fallback_telegram_name(id);
    }

    normalized
}

fn fallback_telegram_name(id: &str) -> String {
    let mut alias = String::from("cmd_");
    alias.push_str(&short_alias_hash(id));
    alias.truncate(32);
    alias
}

fn short_alias_hash(input: &str) -> String {
    let mut hash: u64 = 0xcbf29ce484222325;
    for byte in input.as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(0x100000001b3);
    }
    format!("{:06x}", hash & 0x00ff_ffff)
}

fn alias_conflict_priority(name: &str, preferred: &str) -> u8 {
    if name == preferred && is_valid_telegram_command_name(name) {
        0
    } else {
        1
    }
}

fn conflict_telegram_name(preferred: &str, id: &str, attempt: u32) -> String {
    let seed = if attempt == 0 {
        id.to_string()
    } else {
        format!("{id}:{attempt}")
    };
    let suffix = short_alias_hash(&seed);
    let reserved = suffix.len() + 1;
    let mut prefix = if preferred.is_empty() {
        String::from("cmd")
    } else {
        preferred.to_string()
    };
    if prefix.len() > 32 - reserved {
        prefix.truncate(32 - reserved);
    }
    while prefix.ends_with('_') {
        prefix.pop();
    }
    if prefix.is_empty() {
        prefix.push_str("cmd");
    }
    format!("{prefix}_{suffix}")
}

fn assign_telegram_names(commands: &mut Vec<CommandRegistryEntry>) {
    let mut name_candidates: BTreeMap<String, (String, String)> = BTreeMap::new();

    for command in commands.iter() {
        let preferred = preferred_telegram_name(&command.name, &command.id);
        match name_candidates.get_mut(&command.name) {
            Some((existing_preferred, representative_id)) => {
                if command.id < *representative_id {
                    *representative_id = command.id.clone();
                }
                if alias_conflict_priority(&command.name, &preferred)
                    < alias_conflict_priority(&command.name, existing_preferred)
                {
                    *existing_preferred = preferred;
                }
            }
            None => {
                name_candidates.insert(command.name.clone(), (preferred, command.id.clone()));
            }
        }
    }

    let mut distinct_names = name_candidates
        .iter()
        .map(|(name, (preferred, representative_id))| {
            (name.clone(), preferred.clone(), representative_id.clone())
        })
        .collect::<Vec<_>>();

    distinct_names.sort_by(|left, right| {
        left.1
            .cmp(&right.1)
            .then(
                alias_conflict_priority(&left.0, &left.1)
                    .cmp(&alias_conflict_priority(&right.0, &right.1)),
            )
            .then(left.0.cmp(&right.0))
            .then(left.2.cmp(&right.2))
    });

    let mut assigned_by_name: HashMap<String, String> = HashMap::new();
    let mut used_aliases: HashSet<String> = HashSet::new();

    for (name, preferred, representative_id) in distinct_names {
        let mut assigned = preferred.clone();
        if used_aliases.contains(&assigned) {
            let mut attempt = 0;
            loop {
                let candidate = conflict_telegram_name(&preferred, &representative_id, attempt);
                if !used_aliases.contains(&candidate) {
                    assigned = candidate;
                    break;
                }
                attempt += 1;
            }
        }

        used_aliases.insert(assigned.clone());
        assigned_by_name.insert(name, assigned);
    }

    for command in commands.iter_mut() {
        command.telegram_name = assigned_by_name
            .get(&command.name)
            .cloned()
            .unwrap_or_else(|| preferred_telegram_name(&command.name, &command.id));
    }
}

fn current_epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

fn sort_commands(commands: &mut Vec<CommandRegistryEntry>) {
    commands.sort_by(|left, right| {
        source_order(&left.source)
            .cmp(&source_order(&right.source))
            .then(backend_order(&left.backend).cmp(&backend_order(&right.backend)))
            .then(left.name.cmp(&right.name))
            .then(left.id.cmp(&right.id))
    });
}

fn sort_discovered_commands(commands: &mut Vec<DiscoveredCommand>) {
    commands.sort_by(|left, right| {
        source_order(&left.source)
            .cmp(&source_order(&right.source))
            .then(backend_order(&left.backend).cmp(&backend_order(&right.backend)))
            .then(left.name.cmp(&right.name))
            .then(left.id.cmp(&right.id))
    });
}

fn source_order(source: &CommandSource) -> u8 {
    match source {
        CommandSource::Bot => 0,
        CommandSource::Downstream => 1,
        CommandSource::Skill => 2,
    }
}

fn backend_order(backend: &CommandBackend) -> u8 {
    match backend {
        CommandBackend::Local => 0,
        CommandBackend::Provider(_) => 1,
        CommandBackend::Shared => 2,
    }
}

#[tauri::command]
pub async fn get_command_registry() -> Result<CommandRegistryResponse, String> {
    let data_dir = ensure_data_dir()?;
    let store = load_or_initialize_store(&data_dir)?;
    Ok(build_response(store))
}

#[tauri::command]
pub async fn refresh_command_registry() -> Result<CommandRegistryResponse, String> {
    let data_dir = ensure_data_dir()?;
    let path = command_registry_path(&data_dir);
    let store = load_or_initialize_store(&data_dir)?;
    let refreshed =
        merge_registry_with_discovery(&store, discover_commands(), current_epoch_seconds());
    save_registry_store(&path, &refreshed)?;
    Ok(build_response(refreshed))
}

#[tauri::command]
pub async fn set_command_telegram_enabled(
    command_id: String,
    enabled: bool,
) -> Result<CommandRegistryResponse, String> {
    let data_dir = ensure_data_dir()?;
    let path = command_registry_path(&data_dir);
    let store = load_or_initialize_store(&data_dir)?;
    let updated = update_command_enabled(store, &command_id, enabled)?;
    save_registry_store(&path, &updated)?;
    Ok(build_response(updated))
}

#[tauri::command]
pub async fn publish_telegram_commands() -> Result<CommandRegistryResponse, String> {
    let data_dir = ensure_data_dir()?;
    let path = command_registry_path(&data_dir);
    let store = load_or_initialize_store(&data_dir)?;
    let publishable = build_publishable_commands(&store.commands);
    let token = read_bot_token(&data_dir)?;
    let group_chat_id = read_group_chat_id(&data_dir)?;
    let scopes = build_publish_scopes(group_chat_id);
    publish_scoped_commands(&token, &publishable.commands, &scopes)?;
    let updated =
        apply_publish_success(store, &publishable.published_names, current_epoch_seconds());
    save_registry_store(&path, &updated)?;
    Ok(build_response(updated))
}

#[cfg(test)]
mod tests {
    use super::{
        apply_publish_success, build_publish_scopes, build_publishable_commands, build_response,
        command_registry_path, discover_codex_file_commands_from_roots,
        discover_downstream_commands, discover_skill_commands_from_roots, load_registry_store,
        merge_registry_with_discovery, preferred_telegram_name, save_registry_store,
        CommandBackend, CommandRegistryEntry, CommandRegistryStore, CommandScope, CommandSource,
        CommandStatus, DiscoveredCommand,
    };
    use crate::commands::telegram::TelegramCommandScope;
    use std::collections::HashSet;

    fn entry(
        id: &str,
        name: &str,
        source: CommandSource,
        backend: CommandBackend,
        status: CommandStatus,
        enabled_for_telegram: bool,
        published_to_telegram: bool,
        description: &str,
    ) -> CommandRegistryEntry {
        CommandRegistryEntry {
            id: id.to_string(),
            name: name.to_string(),
            telegram_name: preferred_telegram_name(name, id),
            source,
            backend,
            scope: CommandScope::Thread,
            description: description.to_string(),
            enabled_for_telegram,
            published_to_telegram,
            status,
        }
    }

    fn discovered(
        id: &str,
        name: &str,
        source: CommandSource,
        backend: CommandBackend,
        description: &str,
    ) -> DiscoveredCommand {
        DiscoveredCommand {
            id: id.to_string(),
            name: name.to_string(),
            source,
            backend,
            scope: CommandScope::Thread,
            description: description.to_string(),
        }
    }

    #[test]
    fn merge_marks_missing_entries_and_preserves_selection_flags() {
        let store = CommandRegistryStore {
            commands: vec![
                entry(
                    "bot:help",
                    "help",
                    CommandSource::Bot,
                    CommandBackend::Local,
                    CommandStatus::Active,
                    true,
                    true,
                    "old help",
                ),
                entry(
                    "skill:ask",
                    "ask",
                    CommandSource::Skill,
                    CommandBackend::Shared,
                    CommandStatus::Active,
                    true,
                    false,
                    "old ask",
                ),
            ],
            last_refreshed_epoch: Some(1),
            last_published_epoch: Some(2),
        };

        let merged = merge_registry_with_discovery(
            &store,
            vec![
                discovered(
                    "bot:help",
                    "help",
                    CommandSource::Bot,
                    CommandBackend::Local,
                    "new help",
                ),
                discovered(
                    "skill:find-skills",
                    "find-skills",
                    CommandSource::Skill,
                    CommandBackend::Shared,
                    "find skills",
                ),
            ],
            100,
        );

        assert_eq!(merged.last_refreshed_epoch, Some(100));
        assert_eq!(merged.commands.len(), 3);

        let help = merged
            .commands
            .iter()
            .find(|command| command.id == "bot:help")
            .expect("help command");
        assert_eq!(help.description, "new help");
        assert!(help.enabled_for_telegram);
        assert!(help.published_to_telegram);
        assert_eq!(help.status, CommandStatus::Active);

        let ask = merged
            .commands
            .iter()
            .find(|command| command.id == "skill:ask")
            .expect("ask command");
        assert!(ask.enabled_for_telegram);
        assert!(!ask.published_to_telegram);
        assert_eq!(ask.status, CommandStatus::Missing);

        let find_skills = merged
            .commands
            .iter()
            .find(|command| command.id == "skill:find-skills")
            .expect("find skills command");
        assert!(!find_skills.enabled_for_telegram);
        assert!(!find_skills.published_to_telegram);
        assert_eq!(find_skills.status, CommandStatus::Active);
    }

    #[test]
    fn response_reports_unpublished_changes_for_missing_published_command() {
        let response = build_response(CommandRegistryStore {
            commands: vec![entry(
                "skill:ask",
                "ask",
                CommandSource::Skill,
                CommandBackend::Shared,
                CommandStatus::Missing,
                true,
                true,
                "ask",
            )],
            last_refreshed_epoch: Some(10),
            last_published_epoch: Some(20),
        });

        assert!(response.has_unpublished_changes);
    }

    #[test]
    fn publishable_commands_coalesce_duplicate_active_names() {
        let publishable = build_publishable_commands(&[
            entry(
                "bot:help",
                "help",
                CommandSource::Bot,
                CommandBackend::Local,
                CommandStatus::Active,
                true,
                false,
                "bot help",
            ),
            entry(
                "downstream:codex:help",
                "help",
                CommandSource::Downstream,
                CommandBackend::provider("codex"),
                CommandStatus::Active,
                true,
                false,
                "codex help",
            ),
        ]);

        assert_eq!(publishable.commands.len(), 1);
        assert_eq!(publishable.commands[0].command, "help");
        assert!(publishable.published_names.contains("help"));
    }

    #[test]
    fn publishable_commands_keep_valid_names_and_alias_invalid_ones() {
        let publishable = build_publishable_commands(&[
            entry(
                "bot:help",
                "help",
                CommandSource::Bot,
                CommandBackend::Local,
                CommandStatus::Active,
                true,
                false,
                "bot help",
            ),
            entry(
                "skill:gsd-fast",
                "gsd-fast",
                CommandSource::Skill,
                CommandBackend::Shared,
                CommandStatus::Active,
                true,
                false,
                "fast path",
            ),
        ]);

        assert_eq!(publishable.commands.len(), 2);
        assert_eq!(publishable.commands[0].command, "gsd_fast");
        assert_eq!(publishable.commands[1].command, "help");
        assert!(publishable.published_names.contains("gsd_fast"));
        assert!(publishable.published_names.contains("help"));
        assert!(!publishable.published_names.contains("gsd-fast"));
    }

    #[test]
    fn publishable_commands_generate_alias_for_invalid_names() {
        let publishable = build_publishable_commands(&[entry(
            "skill:gsd-fast",
            "gsd-fast",
            CommandSource::Skill,
            CommandBackend::Shared,
            CommandStatus::Active,
            true,
            false,
            "fast path",
        )]);

        assert_eq!(publishable.commands.len(), 1);
        assert_eq!(publishable.commands[0].command, "gsd_fast");
        assert!(publishable.published_names.contains("gsd_fast"));
    }

    #[test]
    fn apply_publish_success_marks_only_names_that_reached_telegram() {
        let published_names = HashSet::from([String::from("help")]);
        let store = apply_publish_success(
            CommandRegistryStore {
                commands: vec![
                    entry(
                        "bot:help",
                        "help",
                        CommandSource::Bot,
                        CommandBackend::Local,
                        CommandStatus::Active,
                        true,
                        false,
                        "bot help",
                    ),
                    entry(
                        "skill:gsd-fast",
                        "gsd-fast",
                        CommandSource::Skill,
                        CommandBackend::Shared,
                        CommandStatus::Active,
                        true,
                        false,
                        "fast path",
                    ),
                ],
                last_refreshed_epoch: Some(10),
                last_published_epoch: None,
            },
            &published_names,
            20,
        );

        let response = build_response(store.clone());
        let help = store
            .commands
            .iter()
            .find(|command| command.id == "bot:help")
            .expect("help command");
        let gsd_fast = store
            .commands
            .iter()
            .find(|command| command.id == "skill:gsd-fast")
            .expect("gsd-fast command");

        assert!(help.published_to_telegram);
        assert!(!gsd_fast.published_to_telegram);
        assert!(response.has_unpublished_changes);
    }

    #[test]
    fn apply_publish_success_marks_aliased_name_as_published() {
        let published_names = HashSet::from([String::from("gsd_fast")]);
        let store = apply_publish_success(
            CommandRegistryStore {
                commands: vec![entry(
                    "skill:gsd-fast",
                    "gsd-fast",
                    CommandSource::Skill,
                    CommandBackend::Shared,
                    CommandStatus::Active,
                    true,
                    false,
                    "fast path",
                )],
                last_refreshed_epoch: Some(10),
                last_published_epoch: None,
            },
            &published_names,
            20,
        );

        let aliased = store
            .commands
            .iter()
            .find(|command| command.id == "skill:gsd-fast")
            .expect("aliased command");

        assert!(aliased.published_to_telegram);
    }

    #[test]
    fn save_and_load_registry_roundtrip() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-command-registry-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        std::fs::create_dir_all(&temp_dir).expect("create temp dir");
        let path = command_registry_path(&temp_dir);

        let original = CommandRegistryStore {
            commands: vec![entry(
                "bot:status",
                "status",
                CommandSource::Bot,
                CommandBackend::Local,
                CommandStatus::Active,
                true,
                false,
                "status",
            )],
            last_refreshed_epoch: Some(123),
            last_published_epoch: Some(456),
        };

        save_registry_store(&path, &original).expect("save registry");
        let loaded = load_registry_store(&path).expect("load registry");

        assert_eq!(loaded, original);

        let _ = std::fs::remove_file(&path);
        let _ = std::fs::remove_dir(&temp_dir);
    }

    #[test]
    fn discover_codex_file_commands_reads_nested_command_files() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-command-discovery-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let root = temp_dir.join("commands");
        std::fs::create_dir_all(root.join("gsd")).expect("create command dirs");
        std::fs::write(
            root.join("brainstorm.md"),
            "---\ndescription: Brainstorm command\n---\n",
        )
        .expect("write brainstorm command");
        std::fs::write(
            root.join("gsd/workstreams.md"),
            "---\ndescription: Workstream command\n---\n",
        )
        .expect("write workstreams command");

        let discovered = discover_codex_file_commands_from_roots(&[root]);

        assert_eq!(discovered.len(), 2);

        let brainstorm = discovered
            .iter()
            .find(|command| command.id == "downstream:codex:file:brainstorm")
            .expect("brainstorm command");
        assert_eq!(brainstorm.name, "brainstorm");
        assert_eq!(brainstorm.source, CommandSource::Downstream);
        assert_eq!(brainstorm.backend, CommandBackend::provider("codex"));
        assert_eq!(brainstorm.scope, CommandScope::Thread);
        assert_eq!(brainstorm.description, "Brainstorm command");

        let workstreams = discovered
            .iter()
            .find(|command| command.id == "downstream:codex:file:gsd-workstreams")
            .expect("workstreams command");
        assert_eq!(workstreams.name, "gsd-workstreams");
        assert_eq!(workstreams.description, "Workstream command");

        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn discover_skill_commands_classifies_backend_by_root() {
        let temp_dir = std::env::temp_dir().join(format!(
            "onlineworker-skill-discovery-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("system time")
                .as_nanos()
        ));
        let codex_root = temp_dir.join("codex-skills");
        let claude_root = temp_dir.join("claude-skills");
        let shared_root = temp_dir.join("shared-skills");

        std::fs::create_dir_all(codex_root.join("brainstorm")).expect("create codex skill dir");
        std::fs::create_dir_all(claude_root.join("triage")).expect("create claude skill dir");
        std::fs::create_dir_all(shared_root.join("find-skills")).expect("create shared skill dir");

        std::fs::write(
            codex_root.join("brainstorm/SKILL.md"),
            "---\nname: brainstorm\ndescription: Codex brainstorm\n---\n",
        )
        .expect("write codex skill");
        std::fs::write(
            claude_root.join("triage/SKILL.md"),
            "---\nname: triage\ndescription: Claude triage\n---\n",
        )
        .expect("write claude skill");
        std::fs::write(
            shared_root.join("find-skills/SKILL.md"),
            "---\nname: find-skills\ndescription: Shared discovery\n---\n",
        )
        .expect("write shared skill");

        let discovered = discover_skill_commands_from_roots(&[
            (codex_root, CommandBackend::provider("codex")),
            (claude_root, CommandBackend::provider("claude")),
            (shared_root, CommandBackend::Shared),
        ]);

        let brainstorm = discovered
            .iter()
            .find(|command| command.id == "skill:brainstorm")
            .expect("codex skill");
        assert_eq!(brainstorm.backend, CommandBackend::provider("codex"));
        assert_eq!(brainstorm.description, "Codex brainstorm");

        let triage = discovered
            .iter()
            .find(|command| command.id == "skill:triage")
            .expect("claude skill");
        assert_eq!(triage.backend, CommandBackend::provider("claude"));
        assert_eq!(triage.description, "Claude triage");

        let find_skills = discovered
            .iter()
            .find(|command| command.id == "skill:find-skills")
            .expect("shared skill");
        assert_eq!(find_skills.backend, CommandBackend::Shared);
        assert_eq!(find_skills.description, "Shared discovery");

        let _ = std::fs::remove_dir_all(&temp_dir);
    }

    #[test]
    fn discover_downstream_commands_keeps_claude_static_fallback_catalog() {
        let commands = discover_downstream_commands(&HashSet::new());

        let doctor = commands
            .iter()
            .find(|command| command.id == "downstream:claude:doctor")
            .expect("claude doctor fallback command");
        assert_eq!(doctor.name, "doctor");
        assert_eq!(doctor.source, CommandSource::Downstream);
        assert_eq!(doctor.backend, CommandBackend::provider("claude"));
    }

    #[test]
    fn build_publish_scopes_includes_default_group_and_chat() {
        let scopes = build_publish_scopes(Some(-1003766519352));
        assert_eq!(scopes.len(), 3);
        assert_eq!(scopes[0], TelegramCommandScope::Default);
        assert_eq!(scopes[1], TelegramCommandScope::AllGroupChats);
        assert_eq!(
            scopes[2],
            TelegramCommandScope::Chat {
                chat_id: -1003766519352,
            }
        );
    }
}
