use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, SystemTime};
use tauri::AppHandle;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

use super::config::{
    ensure_data_dir, read_provider_metadata_from_disk, read_provider_runtime_policies_from_disk,
};

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

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct CodexMirrorWatchSnapshot {
    #[serde(alias = "thread_id")]
    pub thread_id: String,
    #[serde(alias = "workspace_id")]
    pub workspace_id: String,
    #[serde(alias = "topic_id")]
    pub topic_id: i64,
    #[serde(alias = "session_file")]
    pub session_file: Option<String>,
    #[serde(alias = "last_offset")]
    pub last_offset: u64,
    #[serde(alias = "turn_started_sent")]
    pub turn_started_sent: bool,
    #[serde(alias = "poll_interval_seconds")]
    pub poll_interval_seconds: f64,
    #[serde(alias = "seconds_until_next_poll")]
    pub seconds_until_next_poll: f64,
    #[serde(alias = "seconds_until_expire")]
    pub seconds_until_expire: f64,
    #[serde(alias = "seconds_since_activity")]
    pub seconds_since_activity: Option<f64>,
    #[serde(alias = "idle_polls")]
    pub idle_polls: u64,
    #[serde(alias = "has_commentary")]
    pub has_commentary: bool,
    #[serde(alias = "has_final")]
    pub has_final: bool,
}

#[derive(Serialize, Deserialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct CodexMirrorStatus {
    pub tool: String,
    pub mode: String,
    #[serde(alias = "generated_at_epoch")]
    pub generated_at_epoch: f64,
    #[serde(alias = "mirror_task_running")]
    pub mirror_task_running: bool,
    #[serde(alias = "streaming_turn_count")]
    pub streaming_turn_count: u64,
    #[serde(alias = "watched_thread_count")]
    pub watched_thread_count: u64,
    #[serde(alias = "watched_threads")]
    pub watched_threads: Vec<CodexMirrorWatchSnapshot>,
}

fn codex_mirror_status_path() -> Result<std::path::PathBuf, String> {
    Ok(ensure_data_dir()?.join("codex_tui_mirror_status.json"))
}

fn cleanup_codex_mirror_status_file() {
    if let Ok(path) = codex_mirror_status_path() {
        let _ = std::fs::remove_file(path);
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
struct ManagedProcessCleanupPolicy {
    provider_matchers: Vec<String>,
}

fn cleanup_process_matchers(policy: ManagedProcessCleanupPolicy) -> Vec<String> {
    let mut matchers = vec![
        "onlineworker-bot".to_string(),
        "python.*main.py".to_string(),
    ];
    for matcher in policy.provider_matchers {
        if !matcher.trim().is_empty() && !matchers.iter().any(|existing| existing == &matcher) {
            matchers.push(matcher);
        }
    }
    matchers
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

fn cleanup_managed_processes(policy: ManagedProcessCleanupPolicy) {
    // 1. kill bot 进程
    for matcher in cleanup_process_matchers(policy) {
        let _ = std::process::Command::new("pkill")
            .args(["-9", "-f", &matcher])
            .output();
    }

    // 3. 清理锁文件
    let _ = std::fs::remove_file("/tmp/onlineworker_bot.lock");
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

fn find_external_bot_pid(data_dir: &std::path::Path) -> Option<u32> {
    let pattern = format!("onlineworker-bot --data-dir {}", data_dir.to_string_lossy());
    let output = std::process::Command::new("pgrep")
        .args(["-f", &pattern])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let pids = pids_from_output(&output.stdout);
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
    if let Some(child) = bot.child.take() {
        let _ = child.kill();
    }
    bot.running = false;
    bot.starting = false;
    bot.pid = None;
    bot.last_started_at = None;
    drop(bot);

    cleanup_managed_processes(cleanup_policy);
    cleanup_codex_mirror_status_file();
}

/// Internal: do the actual sidecar spawn. Stores child in state, starts monitor task.
async fn do_spawn(app: &AppHandle, state: &Arc<Mutex<BotState>>) -> Result<u32, String> {
    let dir = ensure_data_dir()?;
    let dir_str = dir.to_string_lossy().to_string();
    eprintln!("[service] do_spawn: data_dir={}", dir_str);
    cleanup_codex_mirror_status_file();

    let home = std::env::var("HOME").unwrap_or_default();
    let path = format!(
        "{}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        home
    );

    eprintln!("[service] do_spawn: creating sidecar command...");
    let sidecar = app.shell().sidecar("onlineworker-bot").map_err(|e| {
        eprintln!("[service] Sidecar not found: {}", e);
        format!("Sidecar not found: {}", e)
    })?;

    eprintln!(
        "[service] do_spawn: spawning sidecar with --data-dir {}...",
        dir_str
    );
    let (rx, child) = sidecar
        .args(["--data-dir", &dir_str])
        .env("PATH", &path)
        .env("HOME", &home)
        .env("LANG", "en_US.UTF-8")
        .spawn()
        .map_err(|e| {
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
        if let Some(child) = bot.child.take() {
            let _ = child.kill();
        }
        bot.running = false;
        bot.starting = true;
        bot.pid = None;
        bot.last_started_at = None;
        apply_service_start_policy(&mut bot);
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

#[tauri::command]
pub async fn read_codex_mirror_status() -> Result<Option<CodexMirrorStatus>, String> {
    let path = codex_mirror_status_path()?;
    if !path.exists() {
        return Ok(None);
    }

    let raw = std::fs::read_to_string(&path)
        .map_err(|e| format!("Cannot read codex mirror status: {}", e))?;
    let parsed: CodexMirrorStatus = serde_json::from_str(&raw)
        .map_err(|e| format!("Cannot parse codex mirror status: {}", e))?;
    Ok(Some(parsed))
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

/// Check if a CLI binary is installed.
/// Expands leading `~/` and then checks PATH via `which`, falling back to
/// a direct executable check for absolute/expanded paths.
/// Note: .app bundles have minimal PATH, so we set a rich PATH for `which`.
#[tauri::command]
pub async fn check_cli(bin: String) -> Result<bool, String> {
    let home = std::env::var("HOME").unwrap_or_default();

    let expanded = if bin.starts_with("~/") {
        format!("{}{}", home, &bin[1..])
    } else {
        bin.clone()
    };

    if expanded.starts_with('/') {
        return Ok(std::path::Path::new(&expanded).exists());
    }

    // .app bundles inherit minimal PATH; provide a rich one for `which`
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
        apply_manual_stop_policy, apply_service_start_policy, cleanup_process_matchers,
        compute_service_status, pid_parent_pairs_from_output, pids_from_output, probe_http_health,
        select_primary_pid, should_attempt_background_service_recovery, BotState,
        CodexMirrorStatus, ManagedProcessCleanupPolicy,
    };
    use std::collections::HashMap;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::thread;
    use std::time::Duration;
    use tauri_plugin_shell::process::CommandEvent;

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
        assert!(matchers.contains(&"onlineworker-bot".to_string()));
        assert!(matchers.contains(&"python.*main.py".to_string()));
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
        assert!(matchers.contains(&"codex.*app-server".to_string()));
        assert!(matchers.contains(&"codex-aar".to_string()));
        assert!(matchers.contains(&"custom-provider.*serve".to_string()));
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
    fn codex_mirror_status_accepts_snake_case_snapshot_and_serializes_camel_case() {
        let raw = r#"{
          "tool": "codex",
          "mode": "tui",
          "generated_at_epoch": 1775477775.18,
          "mirror_task_running": true,
          "streaming_turn_count": 0,
          "watched_thread_count": 1,
          "watched_threads": [
            {
              "thread_id": "tid-1",
              "workspace_id": "codex:onlineWorker",
              "topic_id": 100,
              "session_file": "/tmp/demo.jsonl",
              "last_offset": 123,
              "turn_started_sent": false,
              "poll_interval_seconds": 0.5,
              "seconds_until_next_poll": 0.2,
              "seconds_until_expire": 10.0,
              "seconds_since_activity": 0.4,
              "idle_polls": 0,
              "has_commentary": false,
              "has_final": false
            }
          ]
        }"#;

        let parsed: CodexMirrorStatus = serde_json::from_str(raw).expect("parse snake_case");
        let serialized = serde_json::to_value(parsed).expect("serialize camelCase");

        assert_eq!(serialized["generatedAtEpoch"], 1775477775.18);
        assert_eq!(serialized["mirrorTaskRunning"], true);
        assert_eq!(serialized["watchedThreadCount"], 1);
        assert_eq!(serialized["watchedThreads"][0]["threadId"], "tid-1");
        assert_eq!(
            serialized["watchedThreads"][0]["workspaceId"],
            "codex:onlineWorker"
        );
        assert_eq!(serialized["watchedThreads"][0]["pollIntervalSeconds"], 0.5);
    }
}
