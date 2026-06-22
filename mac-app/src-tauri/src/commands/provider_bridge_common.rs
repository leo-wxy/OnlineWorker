use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::Duration;
use tauri::AppHandle;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

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

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ProviderBridgeOutput {
    pub(crate) code: Option<i32>,
    pub(crate) signal: Option<i32>,
    pub(crate) stdout: Vec<u8>,
    pub(crate) stderr: Vec<u8>,
}

impl ProviderBridgeOutput {
    pub(crate) fn success(&self) -> bool {
        self.code == Some(0)
    }
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

pub(crate) fn kill_provider_bridge_process_tree(root_pid: u32) {
    for pid in running_process_tree_pids(root_pid) {
        kill_pid(pid);
    }
}

pub(crate) async fn collect_provider_bridge_events_with_timeout<F>(
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
    root_pid: u32,
    timeout: Option<Duration>,
    label: &str,
    kill_root: F,
) -> Result<ProviderBridgeOutput, String>
where
    F: FnOnce(u32),
{
    let collect = async {
        let mut code = None;
        let mut signal = None;
        let mut stdout = Vec::new();
        let mut stderr = Vec::new();
        let mut event_error = None;

        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Terminated(payload) => {
                    code = payload.code;
                    signal = payload.signal;
                }
                CommandEvent::Stdout(line) => {
                    stdout.extend(line);
                    stdout.push(b'\n');
                }
                CommandEvent::Stderr(line) => {
                    stderr.extend(line);
                    stderr.push(b'\n');
                }
                CommandEvent::Error(error) => {
                    event_error = Some(error);
                }
                _ => {}
            }
        }

        if let Some(error) = event_error {
            Err(format!("{label} event failed: {error}"))
        } else {
            Ok(ProviderBridgeOutput {
                code,
                signal,
                stdout,
                stderr,
            })
        }
    };

    match timeout {
        Some(timeout) => match tokio::time::timeout(timeout, collect).await {
            Ok(result) => result,
            Err(_) => {
                kill_root(root_pid);
                Err(format!("{label} timed out after {}ms", timeout.as_millis()))
            }
        },
        None => collect.await,
    }
}

pub(crate) async fn run_provider_bridge_sidecar(
    app: &AppHandle,
    args: Vec<String>,
    envs: Vec<(String, String)>,
    timeout: Option<Duration>,
    label: &str,
) -> Result<ProviderBridgeOutput, String> {
    let sidecar = app
        .shell()
        .sidecar("onlineworker-bot")
        .map_err(|error| format!("Sidecar not found: {}", error))?;
    let mut sidecar = sidecar.args(args);
    for (key, value) in envs {
        sidecar = sidecar.env(key, value);
    }

    let (rx, child) = sidecar
        .spawn()
        .map_err(|error| format!("{label} failed: {error}"))?;
    let root_pid = child.pid();
    collect_provider_bridge_events_with_timeout(
        rx,
        root_pid,
        timeout,
        label,
        kill_provider_bridge_process_tree,
    )
    .await
}

#[cfg(test)]
mod tests {
    use super::{collect_provider_bridge_events_with_timeout, process_tree_pids};
    use std::collections::HashMap;
    use std::sync::{
        atomic::{AtomicU32, Ordering},
        Arc,
    };
    use std::time::Duration;

    #[tokio::test]
    async fn provider_bridge_timeout_kills_root_pid() {
        let (_tx, rx) = tauri::async_runtime::channel(1);
        let killed_pid = Arc::new(AtomicU32::new(0));
        let killed_pid_for_callback = killed_pid.clone();

        let error = collect_provider_bridge_events_with_timeout(
            rx,
            4242,
            Some(Duration::from_millis(10)),
            "provider session bridge",
            move |pid| {
                killed_pid_for_callback.store(pid, Ordering::SeqCst);
            },
        )
        .await
        .expect_err("stalled bridge should time out");

        assert!(error.contains("provider session bridge timed out after 10ms"));
        assert_eq!(killed_pid.load(Ordering::SeqCst), 4242);
    }

    #[test]
    fn process_tree_pids_orders_children_before_root() {
        let parents = HashMap::from([(11, 10), (12, 11), (13, 10), (99, 1)]);

        assert_eq!(process_tree_pids(10, &parents), vec![12, 11, 13, 10]);
    }
}
