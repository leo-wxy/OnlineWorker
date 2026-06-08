use serde::Serialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet, VecDeque};
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use uuid::Uuid;

use super::config::data_dir;
use super::provider_sessions::ComposerAttachment;
use super::session_state::{load_local_thread_overlays, LocalThreadOverlay};

const CLAUDE_SESSION_PREVIEW_TURNS: usize = 50;
const CLAUDE_CONTINUATION_CONTEXT_CHAR_LIMIT: usize = 12_000;
const CLAUDE_DETACHED_SEND_GRACE_MS: u64 = 1_200;
const CLAUDE_TAIL_READ_CHUNK_BYTES: usize = 64 * 1024;
const CLAUDE_APP_OWNED_SESSION_DIR: &str = "claude-app-owned-sessions";
const CLAUDE_RUNTIME_ENV_KEYS: [&str; 4] = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
];

#[derive(Debug, Clone)]
pub(crate) struct ClaudeStoredSession {
    pub id: String,
    pub cwd: String,
    pub created_at: i64,
    pub updated_at: i64,
    pub session_file: Option<PathBuf>,
}

#[derive(Debug, Clone, Default)]
pub(crate) struct ClaudeHistoryInfo {
    pub updated_at: i64,
    pub preview: Option<String>,
    pub project: Option<String>,
}

#[derive(Debug)]
struct ClaudeSessionCandidate {
    session: ClaudeSession,
    created_at: i64,
    updated_at: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ClaudeSession {
    pub id: String,
    pub title: String,
    pub directory: String,
    pub archived: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ClaudeTurn {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct ClaudeSendResult {
    pub session_id: String,
    pub created_new_session: bool,
}

fn is_claude_prompt_too_long_text(text: &str) -> bool {
    text.to_ascii_lowercase().contains("prompt is too long")
}

fn build_claude_continuation_system_prompt(turns: &[ClaudeTurn]) -> Option<String> {
    let mut selected = Vec::new();
    let mut used_chars = 0usize;

    for turn in turns.iter().rev().take(CLAUDE_SESSION_PREVIEW_TURNS) {
        let role = if turn.role == "user" {
            "User"
        } else {
            "Assistant"
        };
        let block = format!("[{role}]\n{}\n", turn.content.trim());
        let block_chars = block.chars().count();
        if !selected.is_empty() && used_chars + block_chars > CLAUDE_CONTINUATION_CONTEXT_CHAR_LIMIT
        {
            break;
        }
        selected.push(block);
        used_chars += block_chars;
    }

    if selected.is_empty() {
        return None;
    }

    selected.reverse();
    Some(format!(
        "You are continuing a previous Claude Code conversation in a fresh session because the original session is too large to resume directly.\n\
\n\
Treat the transcript below as recent context from the prior conversation. Continue naturally from the user's next message without repeating the transcript verbatim unless helpful.\n\
\n\
Recent transcript (oldest to newest):\n{}\n\
End of transcript.",
        selected.join("\n")
    ))
}

fn build_claude_compact_send_argv(
    claude_command: &[String],
    session_id: &str,
    text: &str,
    system_prompt: Option<&str>,
) -> Vec<String> {
    let mut argv = claude_command_prefix_or_default(claude_command);
    argv.extend([
        "-p".to_string(),
        "--verbose".to_string(),
        "--output-format".to_string(),
        "stream-json".to_string(),
        "--include-partial-messages".to_string(),
        "--session-id".to_string(),
        session_id.to_string(),
    ]);
    if let Some(prompt) = system_prompt.filter(|value| !value.trim().is_empty()) {
        argv.push("--append-system-prompt".to_string());
        argv.push(prompt.to_string());
    }
    argv.push(text.to_string());
    argv
}

fn split_claude_command_prefix(raw: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut quote: Option<char> = None;
    let mut escaped = false;

    for ch in raw.trim().chars() {
        if escaped {
            current.push(ch);
            escaped = false;
            continue;
        }

        if ch == '\\' {
            escaped = true;
            continue;
        }

        if let Some(quote_char) = quote {
            if ch == quote_char {
                quote = None;
            } else {
                current.push(ch);
            }
            continue;
        }

        if ch == '\'' || ch == '"' {
            quote = Some(ch);
            continue;
        }

        if ch.is_whitespace() {
            if !current.is_empty() {
                parts.push(current);
                current = String::new();
            }
            continue;
        }

        current.push(ch);
    }

    if escaped {
        current.push('\\');
    }
    if !current.is_empty() {
        parts.push(current);
    }
    if parts.is_empty() {
        vec!["claude".to_string()]
    } else {
        parts
    }
}

fn expand_home_path(value: &str) -> String {
    if value == "~" {
        return env::var("HOME").unwrap_or_else(|_| value.to_string());
    }
    if let Some(rest) = value.strip_prefix("~/") {
        if let Ok(home) = env::var("HOME") {
            return PathBuf::from(home).join(rest).to_string_lossy().to_string();
        }
    }
    value.to_string()
}

fn claude_command_prefix_or_default(claude_command: &[String]) -> Vec<String> {
    let mut parts = claude_command
        .iter()
        .map(|part| part.trim())
        .filter(|part| !part.is_empty())
        .map(str::to_string)
        .collect::<Vec<_>>();
    if parts.is_empty() {
        parts.push("claude".to_string());
    }
    parts[0] = expand_home_path(&parts[0]);
    parts
}

fn read_claude_command_prefix_from_config_raw(raw: &str) -> Vec<String> {
    let command = match serde_yaml::from_str::<serde_yaml::Value>(raw) {
        Ok(doc) => {
            let provider_command = doc
                .get("providers")
                .and_then(|providers| providers.get("claude"))
                .and_then(|claude| {
                    claude
                        .get("bin")
                        .or_else(|| claude.get("codex_bin"))
                        .or_else(|| claude.get("codexBin"))
                })
                .and_then(|value| value.as_str())
                .map(str::to_string);
            provider_command.or_else(|| {
                doc.get("tools")
                    .and_then(|tools| tools.as_sequence())
                    .and_then(|tools| {
                        tools.iter().find_map(|tool| {
                            let name = tool.get("name").and_then(|value| value.as_str())?;
                            if name != "claude" {
                                return None;
                            }
                            tool.get("bin")
                                .or_else(|| tool.get("codex_bin"))
                                .or_else(|| tool.get("codexBin"))
                                .and_then(|value| value.as_str())
                                .map(str::to_string)
                        })
                    })
            })
        }
        Err(_) => None,
    };
    let mut parts = split_claude_command_prefix(command.as_deref().unwrap_or("claude"));
    if !parts.is_empty() {
        parts[0] = expand_home_path(&parts[0]);
    }
    parts
}

fn read_claude_command_prefix_from_config() -> Vec<String> {
    let config_path = data_dir().join("config.yaml");
    match fs::read_to_string(config_path) {
        Ok(raw) => read_claude_command_prefix_from_config_raw(&raw),
        Err(_) => vec!["claude".to_string()],
    }
}

fn parse_node_semver(version_name: &str) -> Option<(u32, u32, u32)> {
    let trimmed = version_name.trim().trim_start_matches('v');
    let mut parts = trimmed.split('.');
    let major = parts.next()?.parse::<u32>().ok()?;
    let minor = parts
        .next()
        .and_then(|part| part.parse::<u32>().ok())
        .unwrap_or(0);
    let patch = parts
        .next()
        .and_then(|part| part.parse::<u32>().ok())
        .unwrap_or(0);
    Some((major, minor, patch))
}

fn resolve_preferred_node_bin_dir() -> Option<PathBuf> {
    let home = env::var("HOME").ok()?;
    let versions_dir = PathBuf::from(home).join(".nvm/versions/node");
    let mut candidates = fs::read_dir(versions_dir)
        .ok()?
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let version_name = entry.file_name().to_string_lossy().to_string();
            let version = parse_node_semver(&version_name)?;
            if version.0 < 20 {
                return None;
            }
            let bin_dir = entry.path().join("bin");
            if bin_dir.join("node").is_file() {
                Some((version, bin_dir))
            } else {
                None
            }
        })
        .collect::<Vec<_>>();

    candidates.sort_by(|left, right| right.0.cmp(&left.0));
    if let Some((_, bin_dir)) = candidates.into_iter().next() {
        return Some(bin_dir);
    }

    env::var("NVM_BIN")
        .ok()
        .map(PathBuf::from)
        .filter(|bin_dir| bin_dir.join("node").is_file())
}

fn build_claude_launcher_env() -> HashMap<String, String> {
    let mut values = HashMap::new();
    if let Some(node_bin) = resolve_preferred_node_bin_dir() {
        let node_bin = node_bin.to_string_lossy().to_string();
        let current_path = env::var("PATH").unwrap_or_default();
        let mut path_entries = vec![node_bin.clone()];
        path_entries.extend(
            current_path
                .split(':')
                .filter(|entry| !entry.is_empty() && *entry != node_bin)
                .map(str::to_string),
        );
        values.insert("PATH".to_string(), path_entries.join(":"));
        values.insert("NVM_BIN".to_string(), node_bin);
    }
    values.extend(detect_claude_runtime_env());
    if values.contains_key("ANTHROPIC_BASE_URL")
        && !values.contains_key("ANTHROPIC_AUTH_TOKEN")
        && !values.contains_key("ANTHROPIC_API_KEY")
    {
        values.insert("ANTHROPIC_API_KEY".to_string(), "dummy".to_string());
    }
    values
}

fn is_stale_claude_base_url(value: &str) -> bool {
    matches!(
        value
            .trim()
            .trim_end_matches('/')
            .to_ascii_lowercase()
            .as_str(),
        "http://localhost:3031" | "http://127.0.0.1:3031"
    )
}

fn claude_runtime_env_is_usable(env_map: &HashMap<String, String>) -> bool {
    if env_map
        .get("ANTHROPIC_BASE_URL")
        .map(|value| is_stale_claude_base_url(value))
        .unwrap_or(false)
    {
        return false;
    }
    CLAUDE_RUNTIME_ENV_KEYS.iter().any(|key| {
        env_map
            .get(*key)
            .map(|value| !value.trim().is_empty())
            .unwrap_or(false)
    })
}

fn collect_claude_runtime_env_from_pairs<I, K, V>(pairs: I) -> HashMap<String, String>
where
    I: IntoIterator<Item = (K, V)>,
    K: AsRef<str>,
    V: Into<String>,
{
    let mut values = HashMap::new();
    for (key, value) in pairs {
        let key = key.as_ref();
        if !CLAUDE_RUNTIME_ENV_KEYS.contains(&key) {
            continue;
        }
        let value = value.into();
        if !value.trim().is_empty() {
            values.insert(key.to_string(), value);
        }
    }
    if claude_runtime_env_is_usable(&values) {
        values
    } else {
        HashMap::new()
    }
}

fn detect_claude_runtime_env() -> HashMap<String, String> {
    collect_claude_runtime_env_from_pairs(
        CLAUDE_RUNTIME_ENV_KEYS
            .into_iter()
            .filter_map(|key| env::var(key).ok().map(|value| (key, value))),
    )
}

fn read_claude_command_log(path: &Path) -> String {
    fs::read_to_string(path)
        .unwrap_or_default()
        .trim()
        .to_string()
}

fn claude_project_dir_slug(cwd: &str) -> Option<String> {
    let trimmed = cwd.trim();
    if trimmed.is_empty() || !Path::new(trimmed).is_absolute() {
        return None;
    }

    Some(trimmed.replace(std::path::MAIN_SEPARATOR, "-"))
}

fn run_claude_command_with_grace(program: &str, args: &[String], cwd: &Path) -> Result<(), String> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let log_dir = data_dir().join("tmp");
    let _ = fs::create_dir_all(&log_dir);
    let stdout_path = log_dir.join(format!("claude-send-{stamp}.stdout.log"));
    let stderr_path = log_dir.join(format!("claude-send-{stamp}.stderr.log"));
    let stdout_file = fs::File::create(&stdout_path)
        .map_err(|error| format!("create claude stdout log failed: {error}"))?;
    let stderr_file = fs::File::create(&stderr_path)
        .map_err(|error| format!("create claude stderr log failed: {error}"))?;

    let mut command = Command::new(program);
    command
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::from(stdout_file))
        .stderr(Stdio::from(stderr_file));
    for (key, value) in build_claude_launcher_env() {
        command.env(key, value);
    }

    let mut child = command
        .spawn()
        .map_err(|error| format!("spawn claude failed: {error}"))?;
    let deadline = Instant::now() + Duration::from_millis(CLAUDE_DETACHED_SEND_GRACE_MS);

    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("wait claude failed: {error}"))?
        {
            let stderr = read_claude_command_log(&stderr_path);
            let stdout = read_claude_command_log(&stdout_path);
            let _ = fs::remove_file(&stdout_path);
            let _ = fs::remove_file(&stderr_path);

            if status.success() {
                return Ok(());
            }

            let detail = if !stderr.is_empty() {
                stderr
            } else if !stdout.is_empty() {
                stdout
            } else {
                format!("exit status {status}")
            };
            return Err(format!("claude send failed: {detail}"));
        }

        if Instant::now() >= deadline {
            break;
        }
        thread::sleep(Duration::from_millis(50));
    }

    thread::spawn(move || {
        let _ = child.wait();
        let _ = fs::remove_file(stdout_path);
        let _ = fs::remove_file(stderr_path);
    });

    Ok(())
}

fn list_claude_sessions_from_paths(
    projects_dir: &Path,
    history_path: Option<&Path>,
) -> Result<Vec<ClaudeSession>, String> {
    let stored_sessions = load_claude_project_sessions_from_dir(projects_dir);
    let history_index = build_claude_history_index(history_path);
    let session_by_id = stored_sessions
        .iter()
        .cloned()
        .map(|session| (session.id.clone(), session))
        .collect::<HashMap<_, _>>();

    let mut session_ids = session_by_id.keys().cloned().collect::<Vec<_>>();
    for session_id in history_index.keys() {
        if !session_by_id.contains_key(session_id) {
            session_ids.push(session_id.clone());
        }
    }

    let mut candidates = Vec::new();
    for session_id in session_ids {
        let stored = session_by_id.get(&session_id);
        let history = history_index.get(&session_id);
        if stored
            .and_then(|item| item.session_file.as_deref())
            .map(should_skip_claude_session_from_workspace_list)
            .unwrap_or(false)
        {
            continue;
        }
        let directory = history
            .and_then(|item| item.project.clone())
            .or_else(|| stored.map(|item| item.cwd.clone()))
            .unwrap_or_default();
        if directory.is_empty() {
            continue;
        }
        if is_claude_noise_workspace_path(&directory) {
            continue;
        }

        let mut title = history.and_then(|item| item.preview.clone());
        if title.is_none() {
            title = stored
                .and_then(|item| item.session_file.as_deref())
                .and_then(read_claude_project_session_preview);
        }

        if title.is_none() {
            continue;
        }

        let created_at = stored.map(|item| item.created_at).unwrap_or_default();
        let updated_at = history
            .map(|item| item.updated_at)
            .unwrap_or_default()
            .max(stored.map(|item| item.updated_at).unwrap_or_default());

        candidates.push(ClaudeSessionCandidate {
            created_at: if created_at != 0 {
                created_at
            } else {
                updated_at
            },
            updated_at: if updated_at != 0 {
                updated_at
            } else {
                created_at
            },
            session: ClaudeSession {
                id: session_id.clone(),
                title: title.unwrap_or(session_id),
                directory,
                archived: false,
            },
        });
    }

    candidates.sort_by(|left, right| {
        right
            .updated_at
            .cmp(&left.updated_at)
            .then(right.created_at.cmp(&left.created_at))
            .then(right.session.id.cmp(&left.session.id))
    });

    Ok(candidates.into_iter().map(|item| item.session).collect())
}

fn overlay_claude_sessions(
    mut sessions: Vec<ClaudeSession>,
    overlays: &HashMap<String, LocalThreadOverlay>,
) -> Vec<ClaudeSession> {
    if overlays.is_empty() {
        return sessions;
    }

    let mut existing_ids = HashSet::new();
    for session in &mut sessions {
        existing_ids.insert(session.id.clone());
        if let Some(overlay) = overlays.get(&session.id) {
            session.archived = overlay.archived;
            if !overlay.workspace_path.is_empty() {
                session.directory = overlay.workspace_path.clone();
            }
            if session.title.trim().is_empty() {
                if let Some(preview) = overlay.preview.as_deref() {
                    let trimmed = preview.trim();
                    if !trimmed.is_empty() {
                        session.title = trimmed.to_string();
                    }
                }
            }
        }
    }

    let mut archived_only = overlays
        .iter()
        .filter(|(session_id, overlay)| overlay.archived && !existing_ids.contains(*session_id))
        .map(|(session_id, overlay)| ClaudeSession {
            id: session_id.clone(),
            title: overlay
                .preview
                .clone()
                .unwrap_or_else(|| session_id.clone()),
            directory: overlay.workspace_path.clone(),
            archived: true,
        })
        .collect::<Vec<_>>();
    archived_only.sort_by(|left, right| left.id.cmp(&right.id));
    sessions.extend(archived_only);
    sessions
}

fn read_claude_session_from_paths(
    session_id: &str,
    projects_dir: &Path,
    history_path: Option<&Path>,
    workspace_dir: Option<&str>,
    turn_limit: Option<usize>,
) -> Result<Vec<ClaudeTurn>, String> {
    if let Some(session_file) =
        find_claude_project_session_file(session_id, projects_dir, workspace_dir)
    {
        let turns = if let Some(limit) = turn_limit {
            read_claude_project_turns_tail(&session_file, limit)
        } else {
            read_claude_project_turns(&session_file)
        };
        if !turns.is_empty() {
            return Ok(turns);
        }
    }

    Ok(read_claude_history_turns(
        session_id,
        history_path,
        turn_limit,
    ))
}

fn build_claude_send_argv(
    claude_command: &[String],
    session_id: &str,
    text: &str,
    session_exists: bool,
) -> Vec<String> {
    let mut argv = claude_command_prefix_or_default(claude_command);
    argv.extend([
        "-p".to_string(),
        "--verbose".to_string(),
        "--output-format".to_string(),
        "stream-json".to_string(),
        "--include-partial-messages".to_string(),
    ]);
    if session_exists {
        argv.push("--resume".to_string());
    } else {
        argv.push("--session-id".to_string());
    }
    argv.push(session_id.to_string());
    argv.push(text.to_string());
    argv
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ClaudeSessionSendPlan {
    Direct {
        send_session_id: String,
        session_exists: bool,
    },
}

fn build_claude_session_send_plan(
    session_id: &str,
    session_exists: bool,
    _app_owned: bool,
    _session_turns: &[ClaudeTurn],
) -> ClaudeSessionSendPlan {
    ClaudeSessionSendPlan::Direct {
        send_session_id: session_id.to_string(),
        session_exists,
    }
}

fn claude_app_owned_session_marker_path_for_base(
    base_dir: &Path,
    session_id: &str,
) -> Option<PathBuf> {
    let safe_name = session_id
        .trim()
        .chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '-' || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect::<String>();
    if safe_name.is_empty() {
        return None;
    }
    Some(
        base_dir
            .join(CLAUDE_APP_OWNED_SESSION_DIR)
            .join(format!("{safe_name}.json")),
    )
}

fn is_app_owned_claude_session(session_id: &str) -> bool {
    is_app_owned_claude_session_in_dir(&data_dir(), session_id)
}

fn is_app_owned_claude_session_in_dir(base_dir: &Path, session_id: &str) -> bool {
    claude_app_owned_session_marker_path_for_base(base_dir, session_id)
        .map(|path| path.exists())
        .unwrap_or(false)
}

fn mark_app_owned_claude_session(
    session_id: &str,
    branched_from: Option<&str>,
) -> Result<(), String> {
    mark_app_owned_claude_session_in_dir(&data_dir(), session_id, branched_from)
}

fn mark_app_owned_claude_session_in_dir(
    base_dir: &Path,
    session_id: &str,
    branched_from: Option<&str>,
) -> Result<(), String> {
    let path = claude_app_owned_session_marker_path_for_base(base_dir, session_id)
        .ok_or_else(|| "claude session id is empty".to_string())?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| {
            format!(
                "failed to create claude app-owned session marker dir {}: {err}",
                parent.display()
            )
        })?;
    }
    let payload = serde_json::json!({
        "sessionId": session_id,
        "source": "onlineworker-app",
        "branchedFrom": branched_from,
    });
    fs::write(
        &path,
        serde_json::to_vec_pretty(&payload).map_err(|err| err.to_string())?,
    )
    .map_err(|err| {
        format!(
            "failed to write claude app-owned session marker {}: {err}",
            path.display()
        )
    })
}

fn run_claude_send_command(
    claude_command: &[String],
    session_id: &str,
    final_text: &str,
    session_exists: bool,
    cwd: &Path,
) -> Result<(), String> {
    let argv = build_claude_send_argv(claude_command, session_id, final_text, session_exists);
    let (program, args) = argv
        .split_first()
        .ok_or("claude argv is empty".to_string())?;
    run_claude_command_with_grace(program, args, cwd)
}

fn run_claude_compact_send_command(
    claude_command: &[String],
    session_id: &str,
    final_text: &str,
    system_prompt: Option<&str>,
    cwd: &Path,
) -> Result<(), String> {
    let argv =
        build_claude_compact_send_argv(claude_command, session_id, final_text, system_prompt);
    let (program, args) = argv
        .split_first()
        .ok_or("claude compact argv is empty".to_string())?;
    run_claude_command_with_grace(program, args, cwd)
}

#[tauri::command]
pub fn list_claude_sessions() -> Result<Vec<ClaudeSession>, String> {
    let projects_dir =
        default_claude_projects_dir().ok_or("claude projects directory not found")?;
    let history_path = default_claude_history_path();
    let sessions = list_claude_sessions_from_paths(&projects_dir, history_path.as_deref())?;
    let overlays =
        load_local_thread_overlays(&data_dir().join("onlineworker_state.json"), "claude");
    Ok(overlay_claude_sessions(sessions, &overlays))
}

#[tauri::command]
pub fn read_claude_session(
    session_id: String,
    workspace_dir: Option<String>,
) -> Result<Vec<ClaudeTurn>, String> {
    let projects_dir =
        default_claude_projects_dir().ok_or("claude projects directory not found")?;
    let history_path = default_claude_history_path();
    read_claude_session_from_paths(
        &session_id,
        &projects_dir,
        history_path.as_deref(),
        workspace_dir.as_deref(),
        Some(CLAUDE_SESSION_PREVIEW_TURNS),
    )
}

#[tauri::command]
pub fn send_claude_session_message(
    session_id: String,
    text: String,
    attachments: Vec<ComposerAttachment>,
    workspace_dir: Option<String>,
) -> Result<ClaudeSendResult, String> {
    let trimmed = text.trim();
    let attachment_prompt = attachments
        .iter()
        .filter_map(|attachment| {
            let name = attachment.name.trim();
            let path = attachment.path.trim();
            if name.is_empty() && path.is_empty() {
                return None;
            }
            let label = if attachment.kind == "image" {
                "Attached image"
            } else {
                "Attached file"
            };
            let title = if !name.is_empty() { name } else { path };
            let mut block = format!("[{label}] {title}");
            if !path.is_empty() {
                block.push_str(&format!("\nPath: {path}"));
            }
            Some(block)
        })
        .collect::<Vec<_>>()
        .join("\n\n");
    let final_text = match (trimmed.is_empty(), attachment_prompt.is_empty()) {
        (true, true) => return Err("message is empty".to_string()),
        (false, true) => trimmed.to_string(),
        (true, false) => attachment_prompt,
        (false, false) => format!("{trimmed}\n\n{attachment_prompt}"),
    };

    if final_text.trim().is_empty() {
        return Err("message is empty".to_string());
    }

    let projects_dir = default_claude_projects_dir();
    let (cwd, session_exists) = resolve_claude_send_context(
        &session_id,
        projects_dir.as_deref(),
        workspace_dir.as_deref(),
    )?;

    let history_path = default_claude_history_path();
    let session_turns = projects_dir
        .as_deref()
        .and_then(|dir| {
            read_claude_session_from_paths(
                &session_id,
                dir,
                history_path.as_deref(),
                workspace_dir.as_deref(),
                None,
            )
            .ok()
        })
        .unwrap_or_default();
    let claude_command = read_claude_command_prefix_from_config();
    let session_app_owned = is_app_owned_claude_session(&session_id);
    let send_plan = build_claude_session_send_plan(
        &session_id,
        session_exists,
        session_app_owned,
        &session_turns,
    );
    let send_result = match &send_plan {
        ClaudeSessionSendPlan::Direct {
            send_session_id,
            session_exists,
        } => run_claude_send_command(
            &claude_command,
            send_session_id,
            &final_text,
            *session_exists,
            &cwd,
        ),
    };

    match send_result {
        Ok(()) => match send_plan {
            ClaudeSessionSendPlan::Direct {
                send_session_id, ..
            } => {
                mark_app_owned_claude_session(&send_session_id, None)?;
                Ok(ClaudeSendResult {
                    session_id: send_session_id,
                    created_new_session: false,
                })
            }
        },
        Err(error) if is_claude_prompt_too_long_text(&error) => {
            let new_session_id = Uuid::new_v4().to_string();
            let continuation_prompt = build_claude_continuation_system_prompt(&session_turns);
            run_claude_compact_send_command(
                &claude_command,
                &new_session_id,
                &final_text,
                continuation_prompt.as_deref(),
                &cwd,
            )?;
            mark_app_owned_claude_session(&new_session_id, Some(&session_id))?;
            Ok(ClaudeSendResult {
                session_id: new_session_id,
                created_new_session: true,
            })
        }
        Err(error) => Err(error),
    }
}

pub(crate) fn default_claude_projects_dir() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let path = PathBuf::from(home).join(".claude/projects");
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

pub(crate) fn default_claude_history_path() -> Option<PathBuf> {
    let home = std::env::var("HOME").ok()?;
    let path = PathBuf::from(home).join(".claude/history.jsonl");
    if path.exists() {
        Some(path)
    } else {
        None
    }
}

fn collect_claude_session_files(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };

    let mut paths = entries
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .collect::<Vec<_>>();
    paths.sort();

    for path in paths {
        if path.is_dir() {
            if path.file_name().and_then(|name| name.to_str()) == Some("subagents") {
                continue;
            }
            collect_claude_session_files(&path, out);
            continue;
        }

        if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            out.push(path);
        }
    }
}

fn file_mtime_ms(path: &Path) -> i64 {
    fs::metadata(path)
        .ok()
        .and_then(|meta| meta.modified().ok())
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|duration| duration.as_millis() as i64)
        .unwrap_or_default()
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = year - i64::from(month <= 2);
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let year_of_era = year - era * 400;
    let month_prime = month + if month > 2 { -3 } else { 9 };
    let day_of_year = (153 * month_prime + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146097 + day_of_era - 719_468
}

fn parse_utc_offset_seconds(offset_text: &str) -> Option<i64> {
    if offset_text == "Z" {
        return Some(0);
    }

    if offset_text.len() != 6 {
        return None;
    }

    let sign = match &offset_text[0..1] {
        "+" => 1_i64,
        "-" => -1_i64,
        _ => return None,
    };
    if &offset_text[3..4] != ":" {
        return None;
    }

    let hours = offset_text[1..3].parse::<i64>().ok()?;
    let minutes = offset_text[4..6].parse::<i64>().ok()?;
    Some(sign * (hours * 3600 + minutes * 60))
}

fn parse_rfc3339_timestamp_ms(text: &str) -> Option<i64> {
    let trimmed = text.trim();
    let (datetime, offset_text) = if let Some(prefix) = trimmed.strip_suffix('Z') {
        (prefix, "Z")
    } else if trimmed.len() >= 6 {
        let suffix = &trimmed[trimmed.len() - 6..];
        if suffix.starts_with('+') || suffix.starts_with('-') {
            (&trimmed[..trimmed.len() - 6], suffix)
        } else {
            return None;
        }
    } else {
        return None;
    };

    let mut parts = datetime.split('T');
    let date_part = parts.next()?;
    let time_part = parts.next()?;
    if parts.next().is_some() {
        return None;
    }

    let mut date_iter = date_part.split('-');
    let year = date_iter.next()?.parse::<i64>().ok()?;
    let month = date_iter.next()?.parse::<i64>().ok()?;
    let day = date_iter.next()?.parse::<i64>().ok()?;
    if date_iter.next().is_some() {
        return None;
    }

    let (time_main, fraction_part) = match time_part.split_once('.') {
        Some((main, fraction)) => (main, Some(fraction)),
        None => (time_part, None),
    };
    let mut time_iter = time_main.split(':');
    let hour = time_iter.next()?.parse::<i64>().ok()?;
    let minute = time_iter.next()?.parse::<i64>().ok()?;
    let second = time_iter.next()?.parse::<i64>().ok()?;
    if time_iter.next().is_some() {
        return None;
    }

    let millis = fraction_part
        .map(|fraction| {
            let digits = fraction
                .chars()
                .take_while(|ch| ch.is_ascii_digit())
                .collect::<String>();
            if digits.is_empty() {
                return 0_i64;
            }
            let digits = if digits.len() >= 3 {
                digits[..3].to_string()
            } else {
                format!("{digits:0<3}")
            };
            digits.parse::<i64>().unwrap_or_default()
        })
        .unwrap_or_default();

    let offset_seconds = parse_utc_offset_seconds(offset_text)?;
    let days = days_from_civil(year, month, day);
    let seconds = days * 86_400 + hour * 3_600 + minute * 60 + second - offset_seconds;
    Some(seconds * 1000 + millis)
}

fn parse_claude_timestamp_value(value: &Value) -> i64 {
    match value {
        Value::Number(number) => {
            if let Some(value) = number.as_i64() {
                value
            } else {
                number
                    .as_f64()
                    .map(|value| value as i64)
                    .unwrap_or_default()
            }
        }
        Value::String(text) => text
            .trim()
            .parse::<i64>()
            .ok()
            .or_else(|| parse_rfc3339_timestamp_ms(text))
            .unwrap_or_default(),
        _ => 0,
    }
}

fn normalize_claude_project_path(value: &Value) -> Option<String> {
    value
        .as_str()
        .map(str::trim)
        .filter(|path| !path.is_empty() && Path::new(path).is_absolute())
        .map(ToOwned::to_owned)
}

fn is_claude_display_command(text: &str) -> bool {
    let trimmed = text.trim();
    trimmed.starts_with('/')
        || trimmed.contains("<command-message>")
        || trimmed.contains("<command-name>/")
}

fn normalize_claude_message_text(text: &str) -> String {
    let trimmed = text.trim();
    if trimmed.starts_with("<local-command-") {
        return String::new();
    }
    trimmed.to_string()
}

fn extract_claude_content_text(content: &Value) -> String {
    match content {
        Value::String(text) => normalize_claude_message_text(text),
        Value::Object(object) => {
            if let Some(text) = object.get("text").and_then(Value::as_str) {
                return normalize_claude_message_text(text);
            }
            object
                .get("content")
                .map(extract_claude_content_text)
                .unwrap_or_default()
        }
        Value::Array(items) => items
            .iter()
            .filter_map(|item| match item {
                Value::String(text) => Some(normalize_claude_message_text(text)),
                Value::Object(object) => {
                    let item_type = object
                        .get("type")
                        .and_then(Value::as_str)
                        .unwrap_or_default();
                    if item_type != "text"
                        && item_type != "input_text"
                        && item_type != "output_text"
                    {
                        return None;
                    }
                    object
                        .get("text")
                        .and_then(Value::as_str)
                        .map(normalize_claude_message_text)
                }
                _ => None,
            })
            .filter(|text| !text.is_empty())
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

fn extract_claude_row_text(row: &Value) -> String {
    if let Some(message) = row.get("message").and_then(Value::as_object) {
        if let Some(content) = message.get("content") {
            let text = extract_claude_content_text(content);
            if !text.is_empty() {
                return text;
            }
        }
    }

    if row.get("type").and_then(Value::as_str) == Some("last-prompt") {
        return row
            .get("lastPrompt")
            .and_then(Value::as_str)
            .map(normalize_claude_message_text)
            .unwrap_or_default();
    }

    String::new()
}

pub(crate) fn load_claude_project_sessions_from_dir(
    projects_dir: &Path,
) -> Vec<ClaudeStoredSession> {
    if !projects_dir.is_dir() {
        return Vec::new();
    }

    let mut files = Vec::new();
    collect_claude_session_files(projects_dir, &mut files);

    let mut sessions = Vec::new();
    for session_file in files {
        let mut session_id = session_file
            .file_stem()
            .and_then(|stem| stem.to_str())
            .unwrap_or_default()
            .to_string();
        let mut cwd = String::new();
        let mut created_at = 0_i64;
        let mut updated_at = 0_i64;

        let Ok(file) = fs::File::open(&session_file) else {
            continue;
        };
        let reader = BufReader::new(file);

        for line in reader.lines() {
            let Ok(line) = line else {
                continue;
            };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
                continue;
            };
            if !row.is_object() {
                continue;
            }

            if let Some(row_session_id) = row.get("sessionId").and_then(Value::as_str) {
                if !row_session_id.trim().is_empty() {
                    session_id = row_session_id.trim().to_string();
                }
            }

            if cwd.is_empty() {
                if let Some(row_cwd) = row.get("cwd").and_then(normalize_claude_project_path) {
                    cwd = row_cwd;
                }
            }

            let row_timestamp = row
                .get("timestamp")
                .map(parse_claude_timestamp_value)
                .unwrap_or_default();
            if row_timestamp != 0 && (created_at == 0 || row_timestamp < created_at) {
                created_at = row_timestamp;
            }
            if row_timestamp > updated_at {
                updated_at = row_timestamp;
            }
        }

        if session_id.is_empty() || cwd.is_empty() {
            continue;
        }
        let file_mtime = file_mtime_ms(&session_file);
        if created_at == 0 {
            created_at = file_mtime;
        }
        if updated_at == 0 {
            updated_at = file_mtime.max(created_at);
        }

        sessions.push(ClaudeStoredSession {
            id: session_id,
            cwd,
            created_at,
            updated_at,
            session_file: Some(session_file),
        });
    }

    sessions
}

pub(crate) fn build_claude_history_index(
    history_path: Option<&Path>,
) -> HashMap<String, ClaudeHistoryInfo> {
    let Some(history_path) = history_path.filter(|path| path.exists()) else {
        return HashMap::new();
    };
    let Ok(file) = fs::File::open(history_path) else {
        return HashMap::new();
    };

    let reader = BufReader::new(file);
    let mut index = HashMap::new();
    for line in reader.lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };
        let Some(session_id) = row
            .get("sessionId")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
        else {
            continue;
        };

        let display = row
            .get("display")
            .and_then(Value::as_str)
            .map(normalize_claude_message_text)
            .unwrap_or_default();
        let timestamp = row
            .get("timestamp")
            .map(parse_claude_timestamp_value)
            .unwrap_or_default();
        let project = row.get("project").and_then(normalize_claude_project_path);

        let info = index
            .entry(session_id.to_string())
            .or_insert_with(ClaudeHistoryInfo::default);
        if timestamp > info.updated_at {
            info.updated_at = timestamp;
        }
        if info.project.is_none() && project.is_some() {
            info.project = project;
        }
        if info.preview.is_none() && !display.is_empty() && !is_claude_display_command(&display) {
            info.preview = Some(display);
        }
    }

    index
}

fn find_claude_project_session_file(
    session_id: &str,
    projects_dir: &Path,
    workspace_dir: Option<&str>,
) -> Option<PathBuf> {
    let target_name = format!("{session_id}.jsonl");
    if let Some(workspace_slug) = workspace_dir.and_then(claude_project_dir_slug) {
        let direct_path = projects_dir.join(&workspace_slug).join(&target_name);
        if direct_path.exists() {
            return Some(direct_path);
        }
    }

    let mut files = Vec::new();
    collect_claude_session_files(projects_dir, &mut files);
    let mut matches = files
        .into_iter()
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .map(|name| name == target_name)
                .unwrap_or(false)
        })
        .collect::<Vec<_>>();

    if matches.len() <= 1 {
        return matches.pop();
    }

    let workspace_slug = workspace_dir.and_then(claude_project_dir_slug);
    matches.sort_by(|left, right| {
        let left_slug_match = workspace_slug
            .as_deref()
            .map(|slug| {
                left.parent()
                    .and_then(|parent| parent.file_name())
                    .and_then(|name| name.to_str())
                    == Some(slug)
            })
            .unwrap_or(false);
        let right_slug_match = workspace_slug
            .as_deref()
            .map(|slug| {
                right
                    .parent()
                    .and_then(|parent| parent.file_name())
                    .and_then(|name| name.to_str())
                    == Some(slug)
            })
            .unwrap_or(false);

        right_slug_match
            .cmp(&left_slug_match)
            .then(file_mtime_ms(right).cmp(&file_mtime_ms(left)))
            .then(left.cmp(right))
    });

    matches.into_iter().next()
}

pub(crate) fn read_claude_project_session_preview(session_file: &Path) -> Option<String> {
    let Ok(file) = fs::File::open(session_file) else {
        return None;
    };

    for line in BufReader::new(file).lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };
        if row.get("isSidechain").and_then(Value::as_bool) == Some(true) {
            continue;
        }
        let row_type = row.get("type").and_then(Value::as_str).unwrap_or_default();
        if row_type != "user" && row_type != "last-prompt" {
            continue;
        }
        let text = extract_claude_row_text(&row);
        if !text.is_empty() && !is_claude_display_command(&text) {
            return Some(text);
        }
    }

    None
}

fn parse_claude_turn_row(row: &Value) -> Option<ClaudeTurn> {
    if row.get("isSidechain").and_then(Value::as_bool) == Some(true) {
        return None;
    }

    let role = row.get("type").and_then(Value::as_str).unwrap_or_default();
    if role != "user" && role != "assistant" {
        return None;
    }

    let text = extract_claude_row_text(row);
    if text.is_empty() {
        return None;
    }
    if role == "user" && is_claude_display_command(&text) {
        return None;
    }

    Some(ClaudeTurn {
        role: role.to_string(),
        content: text,
    })
}

fn read_claude_project_turns_tail(session_file: &Path, max_turns: usize) -> Vec<ClaudeTurn> {
    if max_turns == 0 {
        return Vec::new();
    }

    let Ok(mut file) = fs::File::open(session_file) else {
        return Vec::new();
    };
    let Ok(mut position) = file.seek(SeekFrom::End(0)) else {
        return Vec::new();
    };

    let mut remainder = String::new();
    let mut turns = VecDeque::new();

    while position > 0 && turns.len() < max_turns {
        let chunk_len = CLAUDE_TAIL_READ_CHUNK_BYTES.min(position as usize);
        position -= chunk_len as u64;

        if file.seek(SeekFrom::Start(position)).is_err() {
            break;
        }

        let mut buffer = vec![0_u8; chunk_len];
        if file.read_exact(&mut buffer).is_err() {
            break;
        }

        let chunk = String::from_utf8_lossy(&buffer);
        let combined = format!("{chunk}{remainder}");
        let mut lines = combined.split('\n').collect::<Vec<_>>();
        remainder = lines.first().copied().unwrap_or_default().to_string();

        for line in lines.drain(1..).rev() {
            if let Some(turn) = serde_json::from_str::<Value>(line)
                .ok()
                .and_then(|row| parse_claude_turn_row(&row))
            {
                turns.push_front(turn);
                if turns.len() >= max_turns {
                    break;
                }
            }
        }
    }

    if turns.len() < max_turns && !remainder.trim().is_empty() {
        if let Some(turn) = serde_json::from_str::<Value>(&remainder)
            .ok()
            .and_then(|row| parse_claude_turn_row(&row))
        {
            turns.push_front(turn);
        }
    }

    turns.into_iter().collect()
}

fn read_claude_project_session_cwd(session_file: &Path) -> Option<String> {
    let Ok(file) = fs::File::open(session_file) else {
        return None;
    };

    for line in BufReader::new(file).lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };
        if let Some(cwd) = row.get("cwd").and_then(normalize_claude_project_path) {
            return Some(cwd);
        }
    }

    None
}

fn read_claude_project_turns(session_file: &Path) -> Vec<ClaudeTurn> {
    let Ok(file) = fs::File::open(session_file) else {
        return Vec::new();
    };

    let mut turns = Vec::new();
    for line in BufReader::new(file).lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };
        if let Some(turn) = parse_claude_turn_row(&row) {
            turns.push(turn);
        }
    }

    turns
}

fn is_claude_login_failed_text(text: &str) -> bool {
    text.trim() == "Not logged in · Please run /login"
}

fn is_claude_noise_workspace_path(path: &str) -> bool {
    let normalized = path.trim();
    normalized.contains("/.worktrees/")
        || normalized.starts_with("/private/tmp/")
        || (normalized.starts_with("/private/var/folders/") && normalized.contains("/T/tmp"))
}

fn is_claude_smoke_prompt_text(text: &str) -> bool {
    matches!(
        text.trim().to_ascii_lowercase().as_str(),
        "reply with exactly ok" | "please reply with exactly ok"
    ) || text.trim() == "请只回复 OK"
}

pub(crate) fn should_skip_claude_session_from_workspace_list(session_file: &Path) -> bool {
    if read_claude_project_session_cwd(session_file)
        .map(|cwd| is_claude_noise_workspace_path(&cwd))
        .unwrap_or(false)
    {
        return true;
    }

    let turns = read_claude_project_turns(session_file);
    if turns.is_empty() {
        return false;
    }

    let user_turns = turns
        .iter()
        .filter(|turn| turn.role == "user")
        .collect::<Vec<_>>();
    let assistant_turns = turns
        .iter()
        .filter(|turn| turn.role == "assistant")
        .collect::<Vec<_>>();
    if assistant_turns.is_empty() {
        return false;
    }
    if user_turns.len() > 1 {
        return false;
    }

    let user_prompt = user_turns
        .first()
        .map(|turn| turn.content.trim())
        .unwrap_or_default();
    if is_claude_smoke_prompt_text(user_prompt) {
        return true;
    }

    assistant_turns
        .iter()
        .all(|turn| is_claude_login_failed_text(&turn.content))
}

fn read_claude_history_turns(
    session_id: &str,
    history_path: Option<&Path>,
    turn_limit: Option<usize>,
) -> Vec<ClaudeTurn> {
    let Some(history_path) = history_path.filter(|path| path.exists()) else {
        return Vec::new();
    };
    let Ok(file) = fs::File::open(history_path) else {
        return Vec::new();
    };

    let max_turns = turn_limit.unwrap_or(usize::MAX);
    let mut turns = VecDeque::new();
    for line in BufReader::new(file).lines() {
        let Ok(line) = line else {
            continue;
        };
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(trimmed) else {
            continue;
        };
        if row.get("sessionId").and_then(Value::as_str) != Some(session_id) {
            continue;
        }
        let display = row
            .get("display")
            .and_then(Value::as_str)
            .map(normalize_claude_message_text)
            .unwrap_or_default();
        if display.is_empty() || is_claude_display_command(&display) {
            continue;
        }
        turns.push_back(ClaudeTurn {
            role: "user".to_string(),
            content: display,
        });
        while turns.len() > max_turns {
            let _ = turns.pop_front();
        }
    }

    turns.into_iter().collect()
}

fn validate_claude_workspace_dir(path: PathBuf) -> Result<PathBuf, String> {
    if path.is_dir() {
        Ok(path)
    } else {
        Err(format!(
            "workspace directory does not exist: {}",
            path.display()
        ))
    }
}

fn resolve_claude_send_context(
    session_id: &str,
    projects_dir: Option<&Path>,
    workspace_dir: Option<&str>,
) -> Result<(PathBuf, bool), String> {
    let explicit_workspace = workspace_dir
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from);
    let session_file = projects_dir
        .and_then(|dir| find_claude_project_session_file(session_id, dir, workspace_dir));
    let session_exists = session_file.is_some();

    if let Some(workspace) = explicit_workspace {
        return validate_claude_workspace_dir(workspace).map(|cwd| (cwd, session_exists));
    }

    if let Some(session_file) = session_file {
        if let Some(cwd) = read_claude_project_session_cwd(&session_file) {
            return validate_claude_workspace_dir(PathBuf::from(cwd)).map(|cwd| (cwd, true));
        }
    }

    Err("workspace directory required for new claude session".to_string())
}

#[cfg(test)]
mod tests {
    use super::{
        build_claude_continuation_system_prompt, build_claude_send_argv,
        build_claude_session_send_plan, collect_claude_runtime_env_from_pairs,
        is_app_owned_claude_session_in_dir, is_claude_prompt_too_long_text,
        list_claude_sessions_from_paths, mark_app_owned_claude_session_in_dir,
        overlay_claude_sessions, read_claude_command_prefix_from_config_raw,
        read_claude_session_from_paths, resolve_claude_send_context, ClaudeSession,
        ClaudeSessionSendPlan, ClaudeTurn,
    };
    use crate::commands::session_state::LocalThreadOverlay;
    use serde_json::json;
    use std::collections::HashMap;
    use std::fs;
    use std::path::Path;

    fn write_jsonl(path: &Path, rows: &[serde_json::Value]) {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).expect("create parent");
        }
        let content = rows
            .iter()
            .map(|row| serde_json::to_string(row).expect("json row"))
            .collect::<Vec<_>>()
            .join("\n");
        fs::write(path, format!("{content}\n")).expect("write jsonl");
    }

    fn temp_dir(prefix: &str) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "{prefix}-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("time")
                .as_nanos()
        ));
        fs::create_dir_all(&path).expect("create temp dir");
        path
    }

    #[test]
    fn list_claude_sessions_from_paths_reads_project_store_and_history_preview() {
        let root = temp_dir("onlineworker-claude-session-list");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let cwd = "/Users/example/Projects/onlineWorker";

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-old.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-old",
                "message": {"role": "user", "content": "继续旧会话"},
            })],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-new.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-new",
                "message": {"role": "user", "content": "继续新会话"},
            })],
        );
        write_jsonl(
            &history_path,
            &[
                json!({
                    "display": "旧会话第一条消息",
                    "timestamp": 1775520000000_i64,
                    "project": cwd,
                    "sessionId": "ses-old",
                }),
                json!({
                    "display": "新会话第一条消息",
                    "timestamp": 1775523600000_i64,
                    "project": cwd,
                    "sessionId": "ses-new",
                }),
            ],
        );

        let sessions = list_claude_sessions_from_paths(&projects_dir, Some(&history_path))
            .expect("list claude sessions");

        assert_eq!(
            sessions,
            vec![
                ClaudeSession {
                    id: "ses-new".into(),
                    title: "新会话第一条消息".into(),
                    directory: cwd.into(),
                    archived: false,
                },
                ClaudeSession {
                    id: "ses-old".into(),
                    title: "旧会话第一条消息".into(),
                    directory: cwd.into(),
                    archived: false,
                },
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn overlay_claude_sessions_applies_local_archived_state() {
        let sessions = vec![ClaudeSession {
            id: "ses-live".into(),
            title: "继续处理问题".into(),
            directory: "/tmp/live".into(),
            archived: false,
        }];
        let mut overlays = HashMap::new();
        overlays.insert(
            "ses-live".into(),
            LocalThreadOverlay {
                workspace_path: "/tmp/archived".into(),
                archived: true,
                preview: Some("已归档 smoke".into()),
            },
        );
        overlays.insert(
            "ses-overlay-only".into(),
            LocalThreadOverlay {
                workspace_path: "/tmp/overlay-only".into(),
                archived: true,
                preview: Some("overlay only".into()),
            },
        );

        let overlaid = overlay_claude_sessions(sessions, &overlays);

        assert_eq!(
            overlaid,
            vec![
                ClaudeSession {
                    id: "ses-live".into(),
                    title: "继续处理问题".into(),
                    directory: "/tmp/archived".into(),
                    archived: true,
                },
                ClaudeSession {
                    id: "ses-overlay-only".into(),
                    title: "overlay only".into(),
                    directory: "/tmp/overlay-only".into(),
                    archived: true,
                },
            ]
        );
    }

    #[test]
    fn read_claude_session_from_paths_reads_user_and_assistant_messages() {
        let root = temp_dir("onlineworker-claude-session-read");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let session_id = "ses-a";
        let cwd = "/Users/example/Projects/onlineWorker";

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-a.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-07T09:31:18.002Z",
                    "cwd": cwd,
                    "sessionId": session_id,
                    "message": {"role": "user", "content": [{"type": "text", "text": "第一条用户消息"}]},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-07T09:31:20.002Z",
                    "sessionId": session_id,
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "第一条 AI 回复"},
                            {"type": "tool_use", "name": "bash"},
                        ],
                    },
                }),
                json!({
                    "type": "user",
                    "timestamp": "2026-04-07T09:31:25.002Z",
                    "cwd": cwd,
                    "sessionId": session_id,
                    "message": {"role": "user", "content": "/status"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-07T09:31:26.002Z",
                    "sessionId": session_id,
                    "isSidechain": true,
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "subagent"}]},
                }),
                json!({
                    "type": "user",
                    "timestamp": "2026-04-07T09:31:27.002Z",
                    "cwd": cwd,
                    "sessionId": session_id,
                    "message": {"role": "user", "content": "第二条用户消息"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-07T09:31:28.002Z",
                    "sessionId": session_id,
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "第二条 AI 回复"}]},
                }),
            ],
        );
        write_jsonl(
            &history_path,
            &[json!({
                "display": "第一条用户消息",
                "timestamp": 1775523600000_i64,
                "project": cwd,
                "sessionId": session_id,
            })],
        );

        let turns = read_claude_session_from_paths(
            session_id,
            &projects_dir,
            Some(&history_path),
            None,
            None,
        )
        .expect("read claude session");

        assert_eq!(
            turns,
            vec![
                ClaudeTurn {
                    role: "user".into(),
                    content: "第一条用户消息".into(),
                },
                ClaudeTurn {
                    role: "assistant".into(),
                    content: "第一条 AI 回复".into(),
                },
                ClaudeTurn {
                    role: "user".into(),
                    content: "第二条用户消息".into(),
                },
                ClaudeTurn {
                    role: "assistant".into(),
                    content: "第二条 AI 回复".into(),
                },
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn read_claude_session_from_paths_prefers_workspace_specific_file_when_duplicate_ids_exist() {
        let root = temp_dir("onlineworker-claude-session-duplicate-read");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let session_id = "11111111-1111-4111-8111-111111111111";
        let cwd = "/Users/example/Projects/onlineWorker";

        write_jsonl(
            &projects_dir.join(
                "-Users-example-Projects-onlineWorker/11111111-1111-4111-8111-111111111111.jsonl",
            ),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": "真实 onlineWorker 会话"},
            })],
        );
        write_jsonl(
            &projects_dir
                .join("-private-tmp-ow-claude-smoke/11111111-1111-4111-8111-111111111111.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T10:31:18.002Z",
                "cwd": cwd,
                "sessionId": session_id,
                "message": {"role": "user", "content": "Reply with exactly OK"},
            })],
        );
        fs::write(&history_path, "").expect("write empty history");

        let turns = read_claude_session_from_paths(
            session_id,
            &projects_dir,
            Some(&history_path),
            Some(cwd),
            Some(50),
        )
        .expect("read workspace-specific claude session");

        assert_eq!(
            turns,
            vec![ClaudeTurn {
                role: "user".into(),
                content: "真实 onlineWorker 会话".into(),
            }]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn read_claude_session_from_paths_only_keeps_recent_window_when_limited() {
        let root = temp_dir("onlineworker-claude-session-tail-window");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let session_id = "ses-tail";
        let cwd = "/Users/example/Projects/onlineWorker";

        let rows = (1..=60)
            .map(|index| {
                json!({
                    "type": "user",
                    "timestamp": format!("2026-04-07T09:{:02}:18.002Z", index % 60),
                    "cwd": cwd,
                    "sessionId": session_id,
                    "message": {"role": "user", "content": format!("用户消息 {index}")},
                })
            })
            .collect::<Vec<_>>();
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-tail.jsonl"),
            &rows,
        );
        fs::write(&history_path, "").expect("write empty history");

        let turns = read_claude_session_from_paths(
            session_id,
            &projects_dir,
            Some(&history_path),
            Some(cwd),
            Some(5),
        )
        .expect("read limited claude session");

        assert_eq!(
            turns
                .iter()
                .map(|turn| turn.content.as_str())
                .collect::<Vec<_>>(),
            vec![
                "用户消息 56",
                "用户消息 57",
                "用户消息 58",
                "用户消息 59",
                "用户消息 60"
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn list_claude_sessions_from_paths_keeps_meaningful_cli_sessions_and_skips_noise() {
        let root = temp_dir("onlineworker-claude-session-noise");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let cwd = "/Users/example/Projects/onlineWorker";

        write_jsonl(
            &history_path,
            &[json!({
                "display": "等一下 怎么Engine出来了。。目前Demo应该只有Unit才对",
                "timestamp": 1_776_393_832_943_i64,
                "project": cwd,
                "sessionId": "ses-cli-real",
            })],
        );

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-cli-noise.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T09:33:42.791Z",
                "cwd": cwd,
                "sessionId": "ses-cli-noise",
                "entrypoint": "cli",
                "message": {
                    "role": "user",
                    "content": "<local-command-caveat>Caveat: The messages below were generated by the user while running local commands. DO NOT respond.</local-command-caveat>",
                },
            })],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-login-failed.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-12T11:47:36.917Z",
                    "cwd": cwd,
                    "sessionId": "ses-login-failed",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "Reply with exactly OK"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-12T11:47:37.020Z",
                    "cwd": cwd,
                    "sessionId": "ses-login-failed",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Not logged in · Please run /login"}],
                    },
                    "error": "authentication_failed",
                    "isApiErrorMessage": true,
                }),
                json!({
                    "type": "last-prompt",
                    "lastPrompt": "Reply with exactly OK",
                    "sessionId": "ses-login-failed",
                }),
            ],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-cli-real.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-16T02:30:22.087Z",
                "cwd": cwd,
                "sessionId": "ses-cli-real",
                "entrypoint": "cli",
                "message": {
                    "role": "user",
                    "content": "<local-command-caveat>Caveat: The messages below were generated by the user while running local commands. DO NOT respond.</local-command-caveat>",
                },
            })],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-hybrid.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-16T02:30:22.087Z",
                    "cwd": cwd,
                    "sessionId": "ses-hybrid",
                    "entrypoint": "cli",
                    "message": {
                        "role": "user",
                        "content": "<command-message>sdd-new-change</command-message>\n<command-name>/sdd-new-change</command-name>",
                    },
                }),
                json!({
                    "type": "user",
                    "timestamp": "2026-04-16T02:31:22.087Z",
                    "cwd": cwd,
                    "sessionId": "ses-hybrid",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "继续处理当前问题"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-16T02:31:27.397Z",
                    "cwd": cwd,
                    "sessionId": "ses-hybrid",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "继续处理。"}],
                    },
                }),
            ],
        );

        let sessions = list_claude_sessions_from_paths(&projects_dir, Some(&history_path))
            .expect("list claude sessions");

        assert_eq!(
            sessions,
            vec![
                ClaudeSession {
                    id: "ses-cli-real".into(),
                    title: "等一下 怎么Engine出来了。。目前Demo应该只有Unit才对".into(),
                    directory: cwd.into(),
                    archived: false,
                },
                ClaudeSession {
                    id: "ses-hybrid".into(),
                    title: "继续处理当前问题".into(),
                    directory: cwd.into(),
                    archived: false,
                },
            ]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn list_claude_sessions_from_paths_filters_noise_workspace_paths_and_smoke_prompts() {
        let root = temp_dir("onlineworker-claude-session-app-noise");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let real_cwd = "/Users/example/Projects/sample-project";
        let worktree_cwd = "/Users/example/Projects/onlineWorker/.worktrees/phase16-sample-surface";

        write_jsonl(
            &projects_dir.join(
                "-Users-example-Projects-onlineWorker--worktrees-phase16-sample-surface/ses-worktree.jsonl",
            ),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-17T03:21:12.377Z",
                    "cwd": worktree_cwd,
                    "sessionId": "ses-worktree",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "请只回复 OK"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-17T03:21:13.377Z",
                    "cwd": worktree_cwd,
                    "sessionId": "ses-worktree",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "OK"}],
                    },
                }),
            ],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-sample-project/ses-smoke.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-17T07:00:08.431Z",
                    "cwd": real_cwd,
                    "sessionId": "ses-smoke",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "请只回复 OK"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-17T07:00:09.431Z",
                    "cwd": real_cwd,
                    "sessionId": "ses-smoke",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "OK"}],
                    },
                }),
                json!({
                    "type": "last-prompt",
                    "lastPrompt": "请只回复 OK",
                    "sessionId": "ses-smoke",
                }),
            ],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-sample-project/ses-real.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-17T07:10:08.431Z",
                    "cwd": real_cwd,
                    "sessionId": "ses-real",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "继续处理播放器问题"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-17T07:10:09.431Z",
                    "cwd": real_cwd,
                    "sessionId": "ses-real",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "继续处理。"}],
                    },
                }),
            ],
        );
        fs::write(&history_path, "").expect("write empty history");

        let sessions = list_claude_sessions_from_paths(&projects_dir, Some(&history_path))
            .expect("list claude sessions");

        assert_eq!(
            sessions
                .iter()
                .map(|session| session.id.as_str())
                .collect::<Vec<_>>(),
            vec!["ses-real"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn list_claude_sessions_from_paths_sorts_by_latest_activity_not_creation_time() {
        let root = temp_dir("onlineworker-claude-session-recency");
        let projects_dir = root.join("projects");
        let history_path = root.join("history.jsonl");
        let cwd = "/Users/example/Projects/onlineWorker";

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-old-but-active.jsonl"),
            &[
                json!({
                    "type": "user",
                    "timestamp": "2026-04-10T07:54:48.214Z",
                    "cwd": cwd,
                    "sessionId": "ses-old-but-active",
                    "entrypoint": "sdk-cli",
                    "message": {"role": "user", "content": "旧会话"},
                }),
                json!({
                    "type": "assistant",
                    "timestamp": "2026-04-17T10:45:00.000Z",
                    "cwd": cwd,
                    "sessionId": "ses-old-but-active",
                    "entrypoint": "sdk-cli",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "今天刚继续。"}],
                    },
                }),
            ],
        );
        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-new-but-stale.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-16T10:00:00.000Z",
                "cwd": cwd,
                "sessionId": "ses-new-but-stale",
                "entrypoint": "sdk-cli",
                "message": {"role": "user", "content": "新建但没再继续"},
            })],
        );
        fs::write(&history_path, "").expect("write empty history");

        let sessions = list_claude_sessions_from_paths(&projects_dir, Some(&history_path))
            .expect("list claude sessions");

        assert_eq!(
            sessions
                .iter()
                .map(|session| session.id.as_str())
                .collect::<Vec<_>>(),
            vec!["ses-old-but-active", "ses-new-but-stale"]
        );

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn build_claude_continuation_system_prompt_keeps_recent_context_with_budget() {
        let turns = vec![
            ClaudeTurn {
                role: "user".into(),
                content: "第一轮问题".into(),
            },
            ClaudeTurn {
                role: "assistant".into(),
                content: "第一轮回答".into(),
            },
            ClaudeTurn {
                role: "user".into(),
                content: "第二轮问题".into(),
            },
            ClaudeTurn {
                role: "assistant".into(),
                content: "第二轮回答".into(),
            },
        ];

        let prompt =
            build_claude_continuation_system_prompt(&turns).expect("continuation system prompt");

        assert!(prompt.contains("[User]\n第一轮问题"));
        assert!(prompt.contains("[Assistant]\n第二轮回答"));
        assert!(prompt.contains("fresh session"));
    }

    #[test]
    fn is_claude_prompt_too_long_text_detects_error_message() {
        assert!(is_claude_prompt_too_long_text(
            "claude send failed: Prompt is too long"
        ));
        assert!(!is_claude_prompt_too_long_text(
            "claude send failed: Not logged in"
        ));
    }

    #[test]
    fn build_claude_send_argv_switches_between_resume_and_session_id() {
        let claude_command = vec!["claude".to_string()];

        assert_eq!(
            build_claude_send_argv(&claude_command, "ses-existing", "继续", true),
            vec![
                "claude".to_string(),
                "-p".to_string(),
                "--verbose".to_string(),
                "--output-format".to_string(),
                "stream-json".to_string(),
                "--include-partial-messages".to_string(),
                "--resume".to_string(),
                "ses-existing".to_string(),
                "继续".to_string(),
            ]
        );
        assert_eq!(
            build_claude_send_argv(&claude_command, "ses-new", "继续", false),
            vec![
                "claude".to_string(),
                "-p".to_string(),
                "--verbose".to_string(),
                "--output-format".to_string(),
                "stream-json".to_string(),
                "--include-partial-messages".to_string(),
                "--session-id".to_string(),
                "ses-new".to_string(),
                "继续".to_string(),
            ]
        );
    }

    #[test]
    fn build_claude_session_send_plan_resumes_existing_sessions_directly() {
        let turns = vec![ClaudeTurn {
            role: "user".into(),
            content: "上一轮问题".into(),
        }];

        let plan = build_claude_session_send_plan("ses-existing", true, false, &turns);

        assert_eq!(
            plan,
            ClaudeSessionSendPlan::Direct {
                send_session_id: "ses-existing".to_string(),
                session_exists: true,
            }
        );
    }

    #[test]
    fn build_claude_session_send_plan_keeps_new_sessions_direct() {
        let plan = build_claude_session_send_plan("ses-new", false, false, &[]);

        assert_eq!(
            plan,
            ClaudeSessionSendPlan::Direct {
                send_session_id: "ses-new".to_string(),
                session_exists: false,
            }
        );
    }

    #[test]
    fn build_claude_session_send_plan_resumes_app_owned_existing_sessions() {
        let plan = build_claude_session_send_plan("ses-app-owned", true, true, &[]);

        assert_eq!(
            plan,
            ClaudeSessionSendPlan::Direct {
                send_session_id: "ses-app-owned".to_string(),
                session_exists: true,
            }
        );
    }

    #[test]
    fn mark_app_owned_claude_session_writes_resume_marker() {
        let root = temp_dir("onlineworker-claude-owned-marker");

        mark_app_owned_claude_session_in_dir(&root, "ses-app-owned", Some("ses-imported"))
            .expect("mark app-owned");

        assert!(is_app_owned_claude_session_in_dir(&root, "ses-app-owned"));
        assert!(!is_app_owned_claude_session_in_dir(&root, "ses-imported"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn collect_claude_runtime_env_from_pairs_preserves_current_baseurl_chain() {
        let env_map = collect_claude_runtime_env_from_pairs([
            ("ANTHROPIC_MODEL", "claude-opus-4-6"),
            (
                "ANTHROPIC_BASE_URL",
                "https://langbase.netease.com/langbase",
            ),
            ("ANTHROPIC_AUTH_TOKEN", "token-123"),
            ("IGNORED_KEY", "ignored"),
        ]);

        assert_eq!(
            env_map.get("ANTHROPIC_BASE_URL").map(String::as_str),
            Some("https://langbase.netease.com/langbase")
        );
        assert_eq!(
            env_map.get("ANTHROPIC_AUTH_TOKEN").map(String::as_str),
            Some("token-123")
        );
        assert_eq!(
            env_map.get("ANTHROPIC_MODEL").map(String::as_str),
            Some("claude-opus-4-6")
        );
    }

    #[test]
    fn collect_claude_runtime_env_from_pairs_rejects_stale_localhost_baseurl() {
        let env_map = collect_claude_runtime_env_from_pairs([
            ("ANTHROPIC_BASE_URL", "http://localhost:3031"),
            ("ANTHROPIC_MODEL", "claude-opus-4-6"),
        ]);

        assert!(env_map.is_empty());
    }

    #[test]
    fn collect_claude_runtime_env_from_pairs_adds_dummy_key_for_baseurl_without_token() {
        let mut env_map = collect_claude_runtime_env_from_pairs([
            (
                "ANTHROPIC_BASE_URL",
                "https://langbase.netease.com/langbase",
            ),
            ("ANTHROPIC_MODEL", "claude-opus-4-6"),
        ]);
        if env_map.contains_key("ANTHROPIC_BASE_URL")
            && !env_map.contains_key("ANTHROPIC_AUTH_TOKEN")
            && !env_map.contains_key("ANTHROPIC_API_KEY")
        {
            env_map.insert("ANTHROPIC_API_KEY".to_string(), "dummy".to_string());
        }

        assert_eq!(
            env_map.get("ANTHROPIC_BASE_URL").map(String::as_str),
            Some("https://langbase.netease.com/langbase")
        );
        assert_eq!(
            env_map.get("ANTHROPIC_API_KEY").map(String::as_str),
            Some("dummy")
        );
    }

    #[test]
    fn build_claude_send_argv_preserves_launcher_prefix() {
        let claude_command = vec!["ow-claude-launcher".to_string(), "claude".to_string()];

        assert_eq!(
            build_claude_send_argv(&claude_command, "ses-new", "继续", false),
            vec![
                "ow-claude-launcher".to_string(),
                "claude".to_string(),
                "-p".to_string(),
                "--verbose".to_string(),
                "--output-format".to_string(),
                "stream-json".to_string(),
                "--include-partial-messages".to_string(),
                "--session-id".to_string(),
                "ses-new".to_string(),
                "继续".to_string(),
            ]
        );
    }

    #[test]
    fn read_claude_command_prefix_from_config_uses_provider_bin() {
        let command = read_claude_command_prefix_from_config_raw(
            r#"
schema_version: 2
providers:
  claude:
    bin: "ow-claude-launcher claude"
"#,
        );

        assert_eq!(
            command,
            vec!["ow-claude-launcher".to_string(), "claude".to_string()]
        );
    }

    #[test]
    fn read_claude_command_prefix_from_config_supports_quoted_launcher_path() {
        let command = read_claude_command_prefix_from_config_raw(
            r#"
schema_version: 2
providers:
  claude:
    bin: '"/Applications/Claude Wrapper/bin/launch" claude'
"#,
        );

        assert_eq!(
            command,
            vec![
                "/Applications/Claude Wrapper/bin/launch".to_string(),
                "claude".to_string(),
            ]
        );
    }

    #[test]
    fn resolve_claude_send_context_uses_session_cwd_when_workspace_missing() {
        let root = temp_dir("onlineworker-claude-send-context-existing");
        let projects_dir = root.join("projects");
        let cwd_path = root.join("onlineWorker");
        fs::create_dir_all(&cwd_path).expect("create cwd");
        let cwd = cwd_path.to_string_lossy().to_string();

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-existing.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": cwd,
                "sessionId": "ses-existing",
                "message": {"role": "user", "content": "继续"},
            })],
        );

        let (resolved_cwd, session_exists) =
            resolve_claude_send_context("ses-existing", Some(&projects_dir), None)
                .expect("resolve send context");

        assert_eq!(resolved_cwd, cwd_path);
        assert!(session_exists);

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn resolve_claude_send_context_rejects_missing_explicit_workspace() {
        let root = temp_dir("onlineworker-claude-send-context-missing-explicit");
        let projects_dir = root.join("projects");
        let missing_cwd = root.join("deleted-onlineWorker");

        write_jsonl(
            &projects_dir.join("-Users-example-Projects-onlineWorker/ses-existing.jsonl"),
            &[json!({
                "type": "user",
                "timestamp": "2026-04-07T09:31:18.002Z",
                "cwd": missing_cwd.to_string_lossy(),
                "sessionId": "ses-existing",
                "message": {"role": "user", "content": "继续"},
            })],
        );

        let error = resolve_claude_send_context(
            "ses-existing",
            Some(&projects_dir),
            Some(missing_cwd.to_string_lossy().as_ref()),
        )
        .expect_err("missing explicit workspace should not be used");

        assert!(error.contains("workspace directory does not exist"));

        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn resolve_claude_send_context_requires_workspace_for_new_session() {
        let root = temp_dir("onlineworker-claude-send-context-new");
        let projects_dir = root.join("projects");
        fs::create_dir_all(&projects_dir).expect("create projects dir");

        let error = resolve_claude_send_context("ses-new", Some(&projects_dir), None)
            .expect_err("new session should require workspace");

        assert_eq!(error, "workspace directory required for new claude session");

        let _ = fs::remove_dir_all(root);
    }
}
