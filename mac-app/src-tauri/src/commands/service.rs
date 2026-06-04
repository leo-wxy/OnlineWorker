use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, SystemTime};
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

use super::config::{
    ensure_data_dir, read_provider_metadata_from_disk, read_provider_runtime_policies_from_disk,
};

const PROVIDER_OVERLAY_ENV: &str = "ONLINEWORKER_PROVIDER_OVERLAY";

/// Managed state for the sidecar bot process.
pub struct BotState {
    pub child: Option<CommandChild>,
    pub running: bool,
    pub starting: bool,
    pub pid: Option<u32>,
    pub auto_restart: bool,
    pub session_auto_start_enabled: bool,
    pub last_started_at: Option<SystemTime>,
}

impl BotState {
    pub fn new() -> Self {
        Self {
            child: None,
            running: false,
            starting: false,
            pid: None,
            auto_restart: true,
            session_auto_start_enabled: true,
            last_started_at: None,
        }
    }
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
pub struct ServiceStatus {
    pub running: bool,
    pub pid: Option<u32>,
}

const OWNER_BRIDGE_SOCKET_FILENAMES: [&str; 2] =
    ["provider_owner_bridge.sock", "codex_owner_bridge.sock"];

fn cleanup_owner_bridge_socket_files_in_dir(data_dir: &Path) {
    for filename in OWNER_BRIDGE_SOCKET_FILENAMES {
        let _ = std::fs::remove_file(data_dir.join(filename));
    }
}

fn cleanup_owner_bridge_socket_files() {
    if let Ok(data_dir) = ensure_data_dir() {
        cleanup_owner_bridge_socket_files_in_dir(&data_dir);
    }
}

fn read_env_key(raw: &str, key: &str) -> Option<String> {
    raw.lines().find_map(|line| {
        let (line_key, value) = line.split_once('=')?;
        if line_key.trim() == key {
            let trimmed = value.trim();
            if trimmed.is_empty() {
                None
            } else {
                Some(trimmed.to_string())
            }
        } else {
            None
        }
    })
}

fn overlay_env_spec_from_app_env(data_dir: &Path) -> Option<String> {
    let raw = fs::read_to_string(data_dir.join(".env")).ok()?;
    read_env_key(&raw, PROVIDER_OVERLAY_ENV)
}

fn overlay_env_spec(data_dir: &Path) -> Option<String> {
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
        .or_else(|| overlay_env_spec_from_app_env(data_dir))
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct ManagedProcessCleanupPolicy {
    provider_matchers: Vec<String>,
}

fn cleanup_process_matchers(policy: ManagedProcessCleanupPolicy) -> Vec<String> {
    let mut matchers = vec![];
    for matcher in policy.provider_matchers {
        let matcher = matcher.trim();
        if matcher.is_empty() || is_unsafe_global_cleanup_matcher(matcher) {
            continue;
        }
        if !matchers.iter().any(|existing| existing == matcher) {
            matchers.push(matcher.to_string());
        }
    }
    matchers
}

fn is_unsafe_global_cleanup_matcher(matcher: &str) -> bool {
    matches!(matcher, "codex.*app-server" | "codex-aar")
}

fn cleanup_policy_from_config() -> ManagedProcessCleanupPolicy {
    if let Ok(providers) = read_provider_metadata_from_disk() {
        return ManagedProcessCleanupPolicy {
            provider_matchers: providers
                .into_iter()
                .filter(|provider| provider.managed)
                .flat_map(|provider| provider.process.cleanup_matchers)
                .collect(),
        };
    }

    let Ok(policies) = read_provider_runtime_policies_from_disk() else {
        return ManagedProcessCleanupPolicy {
            provider_matchers: vec!["codex.*app-server".to_string(), "codex-aar".to_string()],
        };
    };
    let mut provider_matchers = Vec::new();
    if policies
        .get("codex")
        .map(|policy| policy.managed)
        .unwrap_or(false)
    {
        provider_matchers.push("codex.*app-server".to_string());
        provider_matchers.push("codex-aar".to_string());
    }
    ManagedProcessCleanupPolicy { provider_matchers }
}

fn is_onlineworker_cli_wrapper_command(command_line: &str) -> bool {
    let mut args = command_line.split_whitespace();
    args.any(|arg| matches!(arg, "--ow-codex" | "--ow-claude" | "--codex-tui-host"))
}

fn is_packaged_onlineworker_bot_command(command: &str) -> bool {
    command.ends_with("/onlineworker-bot") || command == "onlineworker-bot"
}

fn is_source_onlineworker_bot_command(command_line: &str) -> bool {
    let mut args = command_line.split_whitespace();
    let command = args.next().unwrap_or("");
    if !command.ends_with("python") && !command.ends_with("python3") && !command.contains("python")
    {
        return false;
    }
    args.any(|arg| arg.ends_with("/main.py") || arg == "main.py")
}

fn managed_bot_cleanup_pids_from_rows(output: &[u8], data_dir: &Path) -> Vec<u32> {
    let expected_arg = format!(" --data-dir {}", data_dir.to_string_lossy());
    std::str::from_utf8(output)
        .ok()
        .map(|text| {
            text.lines()
                .filter_map(|line| {
                    let trimmed = line.trim_start();
                    let (pid_raw, command_line) = trimmed.split_once(char::is_whitespace)?;
                    let pid = pid_raw.parse::<u32>().ok()?;
                    if is_onlineworker_cli_wrapper_command(command_line) {
                        return None;
                    }
                    if !command_line.contains(&expected_arg) {
                        return None;
                    }
                    let command = command_line.split_whitespace().next()?;
                    if is_packaged_onlineworker_bot_command(command)
                        || is_source_onlineworker_bot_command(command_line)
                    {
                        Some(pid)
                    } else {
                        None
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn cleanup_managed_bot_processes(data_dir: &Path) {
    let Ok(output) = std::process::Command::new("ps")
        .args(["-axo", "pid=,command="])
        .output()
    else {
        return;
    };
    for pid in managed_bot_cleanup_pids_from_rows(&output.stdout, data_dir) {
        kill_pid(pid);
    }
}

fn cleanup_managed_processes(policy: ManagedProcessCleanupPolicy) {
    if let Ok(data_dir) = ensure_data_dir() {
        cleanup_managed_bot_processes(&data_dir);
    }

    for matcher in cleanup_process_matchers(policy) {
        let _ = std::process::Command::new("pkill")
            .args(["-9", "-f", &matcher])
            .output();
    }

    // 3. 清理锁文件
    let _ = std::fs::remove_file("/tmp/onlineworker_bot.lock");
    cleanup_owner_bridge_socket_files();
}

fn pids_from_output(output: &[u8]) -> Vec<u32> {
    std::str::from_utf8(output)
        .ok()
        .map(|text| {
            text.lines()
                .filter_map(|line| line.trim().parse::<u32>().ok())
                .collect()
        })
        .unwrap_or_default()
}

fn pids_from_bot_process_rows(output: &[u8], data_dir: &Path) -> Vec<u32> {
    let expected_arg = format!(" --data-dir {}", data_dir.to_string_lossy());
    std::str::from_utf8(output)
        .ok()
        .map(|text| {
            text.lines()
                .filter_map(|line| {
                    let trimmed = line.trim_start();
                    let (pid_raw, command_line) = trimmed.split_once(char::is_whitespace)?;
                    let pid = pid_raw.parse::<u32>().ok()?;
                    let command = command_line.split_whitespace().next()?;
                    if !command.ends_with("/onlineworker-bot") && command != "onlineworker-bot" {
                        return None;
                    }
                    if command_line.contains(&expected_arg) {
                        Some(pid)
                    } else {
                        None
                    }
                })
                .collect()
        })
        .unwrap_or_default()
}

fn pid_parent_pairs_from_output(output: &[u8]) -> HashMap<u32, u32> {
    std::str::from_utf8(output)
        .ok()
        .map(|text| {
            text.lines()
                .filter_map(|line| {
                    let mut parts = line.split_whitespace();
                    let pid = parts.next()?.parse::<u32>().ok()?;
                    let ppid = parts.next()?.parse::<u32>().ok()?;
                    Some((pid, ppid))
                })
                .collect()
        })
        .unwrap_or_default()
}

fn pid_depth_within_candidates(
    pid: u32,
    parents: &HashMap<u32, u32>,
    candidates: &HashSet<u32>,
) -> usize {
    let mut depth = 0;
    let mut current = pid;
    while let Some(parent) = parents.get(&current).copied() {
        if !candidates.contains(&parent) {
            break;
        }
        depth += 1;
        current = parent;
    }
    depth
}

fn select_primary_pid(pids: &[u32], parents: &HashMap<u32, u32>) -> Option<u32> {
    if pids.is_empty() {
        return None;
    }
    if pids.len() == 1 {
        return pids.first().copied();
    }

    let candidate_set: HashSet<u32> = pids.iter().copied().collect();
    let parent_set: HashSet<u32> = parents
        .values()
        .filter(|parent| candidate_set.contains(parent))
        .copied()
        .collect();
    let mut leaves: Vec<u32> = pids
        .iter()
        .copied()
        .filter(|pid| !parent_set.contains(pid))
        .collect();

    if leaves.is_empty() {
        leaves = pids.to_vec();
    }

    leaves.into_iter().max_by_key(|pid| {
        (
            pid_depth_within_candidates(*pid, parents, &candidate_set),
            *pid,
        )
    })
}

fn process_tree_pids(root_pid: u32, parents: &HashMap<u32, u32>) -> Vec<u32> {
    let mut children: HashMap<u32, Vec<u32>> = HashMap::new();
    for (pid, ppid) in parents {
        children.entry(*ppid).or_default().push(*pid);
    }

    fn visit(pid: u32, children: &HashMap<u32, Vec<u32>>, ordered: &mut Vec<u32>) {
        if let Some(child_pids) = children.get(&pid) {
            let mut sorted = child_pids.clone();
            sorted.sort_unstable();
            for child in sorted {
                visit(child, children, ordered);
            }
        }
        ordered.push(pid);
    }

    let mut ordered = Vec::new();
    visit(root_pid, &children, &mut ordered);
    ordered
}

fn running_process_tree_pids(root_pid: u32) -> Vec<u32> {
    let ps_output = match std::process::Command::new("ps")
        .args(["-axo", "pid=,ppid="])
        .output()
    {
        Ok(output) if output.status.success() => output,
        _ => return vec![root_pid],
    };
    let parents = pid_parent_pairs_from_output(&ps_output.stdout);
    process_tree_pids(root_pid, &parents)
}

fn kill_pid(pid: u32) {
    let _ = std::process::Command::new("kill")
        .args(["-9", &pid.to_string()])
        .output();
}

fn cleanup_tracked_process_tree(root_pid: Option<u32>) {
    let Some(root_pid) = root_pid else {
        return;
    };
    for pid in running_process_tree_pids(root_pid) {
        kill_pid(pid);
    }
}

fn find_external_bot_pid(data_dir: &std::path::Path) -> Option<u32> {
    let output = std::process::Command::new("pgrep")
        .args(["-x", "onlineworker-bot"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let pids = pids_from_output(&output.stdout);
    if pids.is_empty() {
        return None;
    }

    let pid_arg = pids
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let command_output = std::process::Command::new("ps")
        .args(["-o", "pid=,command=", "-p", &pid_arg])
        .output()
        .ok()?;
    if !command_output.status.success() {
        return None;
    }
    let pids = pids_from_bot_process_rows(&command_output.stdout, data_dir);
    if pids.is_empty() {
        return None;
    }
    if pids.len() == 1 {
        return pids.first().copied();
    }

    let pid_arg = pids
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let ps_output = std::process::Command::new("ps")
        .args(["-o", "pid=,ppid=", "-p", &pid_arg])
        .output()
        .ok()?;
    if !ps_output.status.success() {
        return pids.last().copied();
    }
    let parents = pid_parent_pairs_from_output(&ps_output.stdout);
    select_primary_pid(&pids, &parents).or_else(|| pids.last().copied())
}

#[derive(Clone, Copy)]
enum TrackedPidLiveness {
    Unknown,
    Alive(bool),
}

impl From<bool> for TrackedPidLiveness {
    fn from(value: bool) -> Self {
        Self::Alive(value)
    }
}

impl From<Option<bool>> for TrackedPidLiveness {
    fn from(value: Option<bool>) -> Self {
        match value {
            Some(alive) => Self::Alive(alive),
            None => Self::Unknown,
        }
    }
}

fn compute_service_status<T: Into<TrackedPidLiveness>>(
    tracked_running: bool,
    tracked_pid: Option<u32>,
    tracked_pid_alive: T,
    external_pid: Option<u32>,
) -> ServiceStatus {
    let tracked_pid_alive = tracked_pid_alive.into();

    if tracked_running {
        if let Some(pid) = tracked_pid {
            match tracked_pid_alive {
                TrackedPidLiveness::Unknown | TrackedPidLiveness::Alive(true) => {
                    return ServiceStatus {
                        running: true,
                        pid: external_pid.or(Some(pid)),
                    };
                }
                TrackedPidLiveness::Alive(false) => {}
            }
        }
    }

    if let Some(pid) = external_pid {
        return ServiceStatus {
            running: true,
            pid: Some(pid),
        };
    }

    ServiceStatus {
        running: false,
        pid: None,
    }
}

fn apply_service_start_policy(bot: &mut BotState) {
    bot.auto_restart = true;
    bot.session_auto_start_enabled = true;
}

fn apply_manual_stop_policy(bot: &mut BotState) {
    bot.auto_restart = false;
    bot.session_auto_start_enabled = false;
}

pub(crate) fn should_attempt_background_service_recovery(
    status: &ServiceStatus,
    session_auto_start_enabled: bool,
    config_auto_start_enabled: bool,
) -> bool {
    session_auto_start_enabled && config_auto_start_enabled && !status.running
}

pub async fn shutdown_managed_processes_for_app_exit(state: &Arc<Mutex<BotState>>) {
    let cleanup_policy = cleanup_policy_from_config();
    let mut bot = state.lock().await;
    apply_manual_stop_policy(&mut bot);
    let tracked_pid = bot.pid;
    if let Some(child) = bot.child.take() {
        let _ = child.kill();
    }
    bot.running = false;
    bot.starting = false;
    bot.pid = None;
    bot.last_started_at = None;
    drop(bot);

    cleanup_tracked_process_tree(tracked_pid);
    cleanup_managed_processes(cleanup_policy);
}

/// Internal: do the actual sidecar spawn. Stores child in state, starts monitor task.
async fn do_spawn(app: &AppHandle, state: &Arc<Mutex<BotState>>) -> Result<u32, String> {
    let dir = ensure_data_dir()?;
    let dir_str = dir.to_string_lossy().to_string();
    eprintln!("[service] do_spawn: data_dir={}", dir_str);

    let home = std::env::var("HOME").unwrap_or_default();
    let path = format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    );
    let overlay_env = overlay_env_spec(&dir);

    eprintln!("[service] do_spawn: creating sidecar command...");
    let sidecar = app.shell().sidecar("onlineworker-bot").map_err(|e| {
        eprintln!("[service] Sidecar not found: {}", e);
        format!("Sidecar not found: {}", e)
    })?;

    eprintln!(
        "[service] do_spawn: spawning sidecar with --data-dir {}...",
        dir_str
    );
    let mut sidecar = sidecar
        .args(["--data-dir", &dir_str])
        .env("PATH", &path)
        .env("HOME", &home)
        .env("LANG", "en_US.UTF-8");
    if let Some(overlay_env) = overlay_env {
        sidecar = sidecar.env(PROVIDER_OVERLAY_ENV, overlay_env);
    }
    let (rx, child) = sidecar.spawn().map_err(|e| {
        eprintln!("[service] Failed to spawn: {}", e);
        format!("Failed to spawn: {}", e)
    })?;

    let pid = child.pid();
    eprintln!("[service] do_spawn: sidecar spawned, pid={}", pid);

    // Store child in state
    {
        let mut bot = state.lock().await;
        bot.pid = Some(pid);
        bot.child = Some(child);
        bot.running = true;
        bot.starting = false;
        bot.last_started_at = Some(SystemTime::now());
    }

    // Monitor process in background for crash detection + auto-restart
    let state_clone = state.clone();
    let app_clone = app.clone();
    start_monitor(rx, state_clone, app_clone);

    eprintln!("[service] do_spawn: complete, pid={}", pid);
    Ok(pid)
}

/// Spawn a background task that monitors CommandEvents and handles auto-restart.
fn start_monitor(
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
    state: Arc<Mutex<BotState>>,
    app: AppHandle,
) {
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            if should_ignore_sidecar_output_event(&event) {
                continue;
            }
            match event {
                CommandEvent::Terminated(payload) => {
                    eprintln!(
                        "[service] sidecar terminated: code={:?}, signal={:?}",
                        payload.code, payload.signal
                    );
                    let should_restart;
                    {
                        let mut bot = state.lock().await;
                        bot.running = false;
                        bot.starting = false;
                        bot.child = None;
                        bot.pid = None;
                        bot.last_started_at = None;

                        // Only restart on abnormal exit:
                        // - exit code non-zero (crash)
                        // - NOT signal termination (SIGTERM/SIGKILL from pkill or service_stop)
                        let crashed =
                            payload.signal.is_none() && payload.code.map_or(true, |c| c != 0);
                        should_restart = bot.auto_restart && crashed;
                    }

                    if should_restart {
                        tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;
                        let _ = do_spawn(&app, &state).await;
                    }
                    break;
                }
                _ => {
                    // Stdout/Stderr: bot writes its own log file, we ignore here
                }
            }
        }
    });
}

fn should_ignore_sidecar_output_event(event: &CommandEvent) -> bool {
    matches!(event, CommandEvent::Stdout(_) | CommandEvent::Stderr(_))
}

#[tauri::command]
pub async fn service_start(
    app: AppHandle,
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<String, String> {
    start_service_internal(&app, state.inner()).await
}

#[tauri::command]
pub async fn service_stop(state: tauri::State<'_, Arc<Mutex<BotState>>>) -> Result<String, String> {
    stop_service_internal(state.inner()).await
}

#[tauri::command]
pub async fn service_restart(
    app: AppHandle,
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<String, String> {
    start_service_internal(&app, state.inner()).await
}

#[tauri::command]
pub async fn service_status(
    state: tauri::State<'_, Arc<Mutex<BotState>>>,
) -> Result<ServiceStatus, String> {
    snapshot_service_status(state.inner()).await
}

pub(crate) async fn snapshot_service_status(
    state: &Arc<Mutex<BotState>>,
) -> Result<ServiceStatus, String> {
    let mut bot = state.lock().await;
    let tracked_running = bot.running;
    let tracked_pid_alive = bot.pid.map(is_pid_alive);

    if bot.running && matches!(tracked_pid_alive, Some(false)) {
        if let Some(pid) = bot.pid {
            eprintln!(
                "[service] Tracked PID {} is dead, clearing tracked state",
                pid
            );
        }
        bot.running = false;
        bot.pid = None;
        bot.child = None;
    }

    let external_pid = ensure_data_dir()
        .ok()
        .and_then(|dir| find_external_bot_pid(&dir));
    let status = compute_service_status(bot.running, bot.pid, tracked_pid_alive, external_pid);

    if !bot.running && status.running {
        if let Some(pid) = status.pid {
            eprintln!(
                "[service] Detected externally running onlineworker-bot pid {}, reporting as running",
                pid
            );
        }
    }

    if tracked_running && !matches!(tracked_pid_alive, Some(false)) {
        bot.running = status.running;
    } else {
        if bot.pid != status.pid {
            bot.child = None;
        }
        bot.running = status.running;
        bot.pid = status.pid;
    }

    Ok(status)
}

pub(crate) async fn ensure_service_running_if_needed(
    app: &AppHandle,
    state: &Arc<Mutex<BotState>>,
) -> Result<ServiceStatus, String> {
    let status = snapshot_service_status(state).await?;
    let (session_auto_start_enabled, starting) = {
        let bot = state.lock().await;
        (bot.session_auto_start_enabled, bot.starting)
    };
    if starting {
        return Ok(status);
    }

    let config_auto_start_enabled = read_provider_runtime_policies_from_disk()
        .map(|policies| {
            policies
                .values()
                .any(|policy| policy.managed && policy.autostart)
        })
        .unwrap_or(false);

    if !should_attempt_background_service_recovery(
        &status,
        session_auto_start_enabled,
        config_auto_start_enabled,
    ) {
        return Ok(status);
    }

    eprintln!(
        "[service] background recovery: service stopped while autostart is enabled, starting now"
    );
    match start_service_internal(app, state).await {
        Ok(message) => {
            eprintln!("[service] background recovery: {}", message);
            snapshot_service_status(state).await
        }
        Err(error) => {
            eprintln!("[service] background recovery failed: {}", error);
            Err(error)
        }
    }
}

pub(crate) async fn start_service_internal(
    app: &AppHandle,
    state: &Arc<Mutex<BotState>>,
) -> Result<String, String> {
    eprintln!("[service] service_start called");
    let cleanup_policy = cleanup_policy_from_config();

    {
        let mut bot = state.lock().await;
        if bot.starting {
            return Ok("Start already in progress".to_string());
        }
        let tracked_pid = bot.pid;
        if let Some(child) = bot.child.take() {
            let _ = child.kill();
        }
        bot.running = false;
        bot.starting = true;
        bot.pid = None;
        bot.last_started_at = None;
        apply_service_start_policy(&mut bot);
        drop(bot);
        cleanup_tracked_process_tree(tracked_pid);
    }

    eprintln!("[service_start] 先停止 bot 并清理本地接口...");
    cleanup_managed_processes(cleanup_policy);

    eprintln!("[service_start] 等待端口释放...");
    tokio::time::sleep(tokio::time::Duration::from_millis(1000)).await;

    eprintln!("[service] calling do_spawn...");
    let pid = match do_spawn(app, state).await {
        Ok(pid) => pid,
        Err(error) => {
            let mut bot = state.lock().await;
            bot.starting = false;
            return Err(error);
        }
    };
    eprintln!("[service] service_start complete, pid={}", pid);
    Ok(format!("Started (pid: {})", pid))
}

pub(crate) async fn stop_service_internal(state: &Arc<Mutex<BotState>>) -> Result<String, String> {
    eprintln!("[service_stop] 清理所有相关进程...");
    shutdown_managed_processes_for_app_exit(state).await;
    eprintln!("[service_stop] 清理完成");
    Ok("Stopped".to_string())
}

/// Check if a PID is still alive
fn is_pid_alive(pid: u32) -> bool {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        Command::new("kill")
            .args(["-0", &pid.to_string()])
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }
    #[cfg(not(target_os = "macos"))]
    {
        false // Fallback for other platforms
    }
}

fn command_program_token(command: &str) -> String {
    let mut token = String::new();
    let mut chars = command.trim_start().chars().peekable();
    let mut quote: Option<char> = None;
    while let Some(ch) = chars.next() {
        if let Some(active_quote) = quote {
            if ch == active_quote {
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

fn expand_home_path(value: &str) -> String {
    let home = std::env::var("HOME").unwrap_or_default();
    if value.starts_with("~/") {
        format!("{}{}", home, &value[1..])
    } else {
        value.to_string()
    }
}

/// Check if a CLI command is installed.
/// Accepts command lines such as `/path/to/raven cc`; only the executable token
/// is checked. .app bundles have minimal PATH, so we set a rich PATH for `which`.
#[tauri::command]
pub async fn check_cli(bin: String) -> Result<bool, String> {
    let program = command_program_token(&bin);
    if program.is_empty() {
        return Ok(false);
    }
    let expanded = expand_home_path(&program);

    if expanded.starts_with('/') {
        let path = std::path::Path::new(&expanded);
        return Ok(path.exists() && path.is_file());
    }

    // .app bundles inherit minimal PATH; provide a rich one for `which`
    let home = std::env::var("HOME").unwrap_or_default();
    let rich_path = format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    );

    let output = std::process::Command::new("which")
        .arg(&expanded)
        .env("PATH", &rich_path)
        .output()
        .map_err(|e| e.to_string())?;

    Ok(output.status.success())
}

/// Check HTTP endpoint health with a real HTTP GET request.
#[tauri::command]
pub async fn check_http_health(url: String) -> Result<bool, String> {
    let url_clone = url.clone();
    tauri::async_runtime::spawn_blocking(move || probe_http_health(&url_clone))
        .await
        .map_err(|e| e.to_string())?
}

fn probe_http_health(url: &str) -> Result<bool, String> {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_millis(500))
        .timeout_read(Duration::from_millis(500))
        .timeout_write(Duration::from_millis(500))
        .build();

    match agent.get(url).call() {
        Ok(resp) => Ok(resp.status() == 200),
        Err(ureq::Error::Status(code, _)) => Ok(code == 200),
        Err(_) => Ok(false),
    }
}

#[cfg(test)]
mod tests {
    use super::should_ignore_sidecar_output_event;
    use super::{
        apply_manual_stop_policy, apply_service_start_policy,
        cleanup_owner_bridge_socket_files_in_dir, cleanup_process_matchers, compute_service_status,
        managed_bot_cleanup_pids_from_rows, overlay_env_spec, overlay_env_spec_from_app_env,
        pid_parent_pairs_from_output, pids_from_bot_process_rows, pids_from_output,
        probe_http_health, process_tree_pids, read_env_key, select_primary_pid,
        should_attempt_background_service_recovery, command_program_token, BotState,
        ManagedProcessCleanupPolicy,
    };
    use std::collections::HashMap;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::Path;
    use std::thread;
    use std::time::Duration;
    use tauri_plugin_shell::process::CommandEvent;

    #[test]
    fn command_program_token_accepts_command_lines_with_arguments() {
        assert_eq!(
            command_program_token("/Users/wxy/.nvm/versions/node/v20.20.1/bin/raven cc"),
            "/Users/wxy/.nvm/versions/node/v20.20.1/bin/raven"
        );
        assert_eq!(
            command_program_token("\"/some path/bin/raven\" cc"),
            "/some path/bin/raven"
        );
    }

    #[test]
    fn compute_service_status_reports_external_orphan_process_as_running() {
        let status = compute_service_status(false, None, false, Some(45937));
        assert!(status.running);
        assert_eq!(status.pid, Some(45937));
    }

    #[test]
    fn compute_service_status_falls_back_to_external_process_when_tracked_pid_is_dead() {
        let status = compute_service_status(true, Some(123), false, Some(45937));
        assert!(status.running);
        assert_eq!(status.pid, Some(45937));
    }

    #[test]
    fn compute_service_status_prefers_logical_runtime_pid_when_external_leaf_exists() {
        let status = compute_service_status(true, Some(21014), true, Some(21035));
        assert!(status.running);
        assert_eq!(status.pid, Some(21035));
    }

    #[test]
    fn compute_service_status_marks_service_stopped_when_tracked_pid_is_dead_and_no_external_exists(
    ) {
        let status = compute_service_status(true, Some(123), false, None);
        assert!(!status.running);
        assert_eq!(status.pid, None);
    }

    #[test]
    fn probe_http_health_returns_true_for_http_200() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind listener");
        let addr = listener.local_addr().expect("listener addr");

        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept connection");
            let mut buf = [0_u8; 1024];
            let _ = stream.read(&mut buf);
            let response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK";
            stream.write_all(response).expect("write response");
        });

        let ok = probe_http_health(&format!("http://{addr}/readyz")).expect("probe result");
        handle.join().expect("server thread join");

        assert!(ok);
    }

    #[test]
    fn probe_http_health_returns_false_for_bare_tcp_port() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind listener");
        let addr = listener.local_addr().expect("listener addr");

        let handle = thread::spawn(move || {
            let (_stream, _) = listener.accept().expect("accept connection");
            thread::sleep(Duration::from_millis(50));
        });

        let ok = probe_http_health(&format!("http://{addr}/readyz")).expect("probe result");
        handle.join().expect("server thread join");

        assert!(!ok);
    }

    #[test]
    fn sidecar_output_events_are_ignored_by_monitor() {
        assert!(should_ignore_sidecar_output_event(&CommandEvent::Stdout(
            b"log line".to_vec(),
        )));
        assert!(should_ignore_sidecar_output_event(&CommandEvent::Stderr(
            b"error line".to_vec(),
        )));
    }

    #[test]
    fn bot_state_defaults_to_session_auto_start_enabled() {
        let bot = BotState::new();
        assert!(bot.auto_restart);
        assert!(bot.session_auto_start_enabled);
    }

    #[test]
    fn manual_stop_disables_session_auto_start_until_user_starts_again() {
        let mut bot = BotState::new();
        apply_manual_stop_policy(&mut bot);
        assert!(!bot.auto_restart);
        assert!(!bot.session_auto_start_enabled);

        apply_service_start_policy(&mut bot);
        assert!(bot.auto_restart);
        assert!(bot.session_auto_start_enabled);
    }

    #[test]
    fn background_service_recovery_requires_stopped_service_and_both_autostart_flags() {
        assert!(!should_attempt_background_service_recovery(
            &super::ServiceStatus {
                running: true,
                pid: Some(12345),
            },
            true,
            true,
        ));

        assert!(!should_attempt_background_service_recovery(
            &super::ServiceStatus {
                running: false,
                pid: None,
            },
            false,
            true,
        ));

        assert!(!should_attempt_background_service_recovery(
            &super::ServiceStatus {
                running: false,
                pid: None,
            },
            true,
            false,
        ));

        assert!(should_attempt_background_service_recovery(
            &super::ServiceStatus {
                running: false,
                pid: None,
            },
            true,
            true,
        ));
    }

    #[test]
    fn cleanup_process_matchers_skip_unmanaged_provider_processes() {
        let matchers = cleanup_process_matchers(ManagedProcessCleanupPolicy {
            provider_matchers: vec![],
        });
        assert!(!matchers.contains(&"onlineworker-bot".to_string()));
        assert!(!matchers.contains(&"python.*main.py".to_string()));
        assert!(!matchers.contains(&"codex.*app-server".to_string()));
        assert!(!matchers.contains(&"custom-provider.*serve".to_string()));
    }

    #[test]
    fn cleanup_process_matchers_include_managed_provider_processes() {
        let matchers = cleanup_process_matchers(ManagedProcessCleanupPolicy {
            provider_matchers: vec![
                "codex.*app-server".to_string(),
                "codex-aar".to_string(),
                "custom-provider.*serve".to_string(),
            ],
        });
        assert!(!matchers.contains(&"codex.*app-server".to_string()));
        assert!(!matchers.contains(&"codex-aar".to_string()));
        assert!(matchers.contains(&"custom-provider.*serve".to_string()));
    }

    #[test]
    fn cleanup_process_matchers_skip_legacy_codex_global_matchers() {
        let matchers = cleanup_process_matchers(ManagedProcessCleanupPolicy {
            provider_matchers: vec!["codex.*app-server".to_string(), "codex-aar".to_string()],
        });

        assert!(!matchers.contains(&"codex.*app-server".to_string()));
        assert!(!matchers.contains(&"codex-aar".to_string()));
    }

    #[test]
    fn cleanup_owner_bridge_socket_files_removes_stale_bridge_paths_only() {
        let dir =
            std::env::temp_dir().join(format!("ow-service-socket-cleanup-{}", std::process::id()));
        fs::create_dir_all(&dir).expect("create temp dir");
        let provider_socket = dir.join("provider_owner_bridge.sock");
        let codex_socket = dir.join("codex_owner_bridge.sock");
        let unrelated = dir.join("onlineworker_state.json");
        fs::write(&provider_socket, "").expect("write provider socket placeholder");
        fs::write(&codex_socket, "").expect("write codex socket placeholder");
        fs::write(&unrelated, "{}").expect("write unrelated file");

        cleanup_owner_bridge_socket_files_in_dir(&dir);

        assert!(!provider_socket.exists());
        assert!(!codex_socket.exists());
        assert!(unrelated.exists());

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn read_env_key_trims_overlay_path_values() {
        let raw = "ONLINEWORKER_PROVIDER_OVERLAY=  /tmp/private-overlay  \n";
        assert_eq!(
            read_env_key(raw, "ONLINEWORKER_PROVIDER_OVERLAY").as_deref(),
            Some("/tmp/private-overlay")
        );
    }

    #[test]
    fn overlay_env_spec_from_app_env_reads_data_dir_env_file() {
        let dir = std::env::temp_dir().join(format!("onlineworker-overlay-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        fs::write(
            dir.join(".env"),
            "TELEGRAM_TOKEN=token\nONLINEWORKER_PROVIDER_OVERLAY=/tmp/private-overlay\n",
        )
        .expect("write .env");

        assert_eq!(
            overlay_env_spec_from_app_env(&dir).as_deref(),
            Some("/tmp/private-overlay")
        );

        let _ = fs::remove_file(dir.join(".env"));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn overlay_env_spec_prefers_process_env_over_app_env_file() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-overlay-process-{}",
            std::process::id()
        ));
        let _ = fs::create_dir_all(&dir);
        fs::write(
            dir.join(".env"),
            "ONLINEWORKER_PROVIDER_OVERLAY=/tmp/from-app-env\n",
        )
        .expect("write .env");
        std::env::set_var("ONLINEWORKER_PROVIDER_OVERLAY", "/tmp/from-process-env");

        assert_eq!(
            overlay_env_spec(&dir).as_deref(),
            Some("/tmp/from-process-env")
        );

        std::env::remove_var("ONLINEWORKER_PROVIDER_OVERLAY");
        let _ = fs::remove_file(dir.join(".env"));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn pids_from_output_parses_multiple_rows() {
        assert_eq!(pids_from_output(b"21014\n21035\n"), vec![21014, 21035]);
    }

    #[test]
    fn pid_parent_pairs_from_output_parses_ps_rows() {
        let pairs = pid_parent_pairs_from_output(b"21014 1\n21035 21014\n");
        assert_eq!(pairs.get(&21014), Some(&1));
        assert_eq!(pairs.get(&21035), Some(&21014));
    }

    #[test]
    fn select_primary_pid_prefers_pyinstaller_leaf_child() {
        let parents = HashMap::from([(21014, 1), (21035, 21014)]);
        let pid = select_primary_pid(&[21014, 21035], &parents);
        assert_eq!(pid, Some(21035));
    }

    #[test]
    fn process_tree_pids_returns_only_descendants_before_root() {
        let parents = HashMap::from([(100, 1), (110, 100), (120, 110), (200, 1), (210, 200)]);

        assert_eq!(process_tree_pids(100, &parents), vec![120, 110, 100]);
    }

    #[test]
    fn find_external_bot_pid_ignores_other_processes_with_bot_command_text() {
        let data_dir = std::env::temp_dir().join(format!(
            "onlineworker-data-dir with spaces {}",
            std::process::id()
        ));
        fs::create_dir_all(&data_dir).expect("create temp data dir");
        let pattern = format!("onlineworker-bot --data-dir {}", data_dir.to_string_lossy());
        let mut child = std::process::Command::new("python3")
            .arg("-c")
            .arg("import time; time.sleep(10)")
            .arg("onlineworker-bot")
            .arg("--data-dir")
            .arg(data_dir.to_string_lossy().to_string())
            .spawn()
            .expect("spawn decoy process");

        let visible = (0..20).any(|_| {
            let status = std::process::Command::new("pgrep")
                .args(["-f", &pattern])
                .status()
                .map(|status| status.success())
                .unwrap_or(false);
            if !status {
                thread::sleep(Duration::from_millis(50));
            }
            status
        });
        assert!(visible, "decoy process should be visible in command text");

        let detected = super::find_external_bot_pid(&data_dir);

        let _ = child.kill();
        let _ = child.wait();
        let _ = fs::remove_dir_all(&data_dir);

        assert_eq!(detected, None);
    }

    #[test]
    fn pids_from_bot_process_rows_matches_data_dir_with_spaces() {
        let data_dir = Path::new("/Users/wxy/Library/Application Support/OnlineWorker");
        let rows = b" 123 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker\n 456 /usr/bin/python3 -c sleep onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker\n";

        assert_eq!(pids_from_bot_process_rows(rows, data_dir), vec![123]);
    }

    #[test]
    fn managed_bot_cleanup_pids_exclude_cli_wrappers_for_same_data_dir() {
        let data_dir = Path::new("/Users/wxy/Library/Application Support/OnlineWorker");
        let rows = b"\
 101 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker
 102 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker --ow-codex
 103 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --data-dir /Users/wxy/Library/Application Support/OnlineWorker --ow-claude
 104 /Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot --ow-claude --data-dir /Users/wxy/Library/Application Support/OnlineWorker
 105 /usr/bin/python3 /repo/main.py --data-dir /Users/wxy/Library/Application Support/OnlineWorker
 106 /usr/bin/python3 /repo/main.py --data-dir /Users/wxy/Library/Application Support/OnlineWorker --ow-codex
 107 /usr/bin/python3 /repo/main.py --ow-claude --data-dir /Users/wxy/Library/Application Support/OnlineWorker
";

        assert_eq!(
            managed_bot_cleanup_pids_from_rows(rows, data_dir),
            vec![101, 105]
        );
    }
}
