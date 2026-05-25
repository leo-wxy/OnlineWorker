use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use tauri::AppHandle;

use super::config::ensure_data_dir;

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn temp_codex_tui_host_script_path() -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    std::env::temp_dir().join(format!("onlineworker-codex-tui-host-{}.command", stamp))
}

fn build_codex_tui_host_script(
    sidecar_path: &Path,
    data_dir: &Path,
    workspace_path: &str,
    thread_id: &str,
) -> String {
    format!(
        "#!/bin/zsh\nset -e\ncd {workspace}\nexec {bot} --data-dir {data_dir} --codex-tui-host --codex-tui-cd {workspace} --codex-tui-target {thread_id} --codex-tui-extra-arg=--no-alt-screen\n",
        workspace = shell_quote(workspace_path),
        bot = shell_quote(&sidecar_path.to_string_lossy()),
        data_dir = shell_quote(&data_dir.to_string_lossy()),
        thread_id = shell_quote(thread_id),
    )
}

fn write_executable_script(path: &Path, content: &str) -> Result<(), String> {
    let mut file = fs::File::create(path).map_err(|error| error.to_string())?;
    file.write_all(content.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut permissions = file
        .metadata()
        .map_err(|error| error.to_string())?
        .permissions();
    permissions.set_mode(0o700);
    fs::set_permissions(path, permissions).map_err(|error| error.to_string())
}

fn bundled_onlineworker_bot_path() -> Result<PathBuf, String> {
    let current_exe = std::env::current_exe().map_err(|error| error.to_string())?;
    let current_dir = current_exe
        .parent()
        .ok_or_else(|| "Cannot resolve current executable directory".to_string())?;
    let arch = std::env::consts::ARCH;
    let sidecar_candidates = [
        current_dir.join("onlineworker-bot"),
        current_dir.join(format!("onlineworker-bot-{}-apple-darwin", arch)),
        current_dir.join("binaries").join("onlineworker-bot"),
        current_dir
            .join("binaries")
            .join(format!("onlineworker-bot-{}-apple-darwin", arch)),
    ];
    sidecar_candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| {
            format!(
                "Cannot resolve bundled onlineworker-bot next to {}",
                current_exe.to_string_lossy()
            )
        })
}

#[tauri::command]
pub async fn open_terminal(workspace_path: String) -> Result<(), String> {
    // Try iTerm2 first
    let iterm_result = Command::new("open")
        .args(["-a", "iTerm", &workspace_path])
        .output();

    match iterm_result {
        Ok(output) if output.status.success() => return Ok(()),
        _ => {}
    }

    // Fall back to Terminal.app
    let result = Command::new("open")
        .args(["-a", "Terminal", &workspace_path])
        .output()
        .map_err(|e| e.to_string())?;

    if result.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Failed to open terminal: {}",
            String::from_utf8_lossy(&result.stderr)
        ))
    }
}

#[tauri::command]
pub async fn open_codex_tui_host_terminal(
    app: AppHandle,
    workspace_path: String,
    thread_id: String,
) -> Result<(), String> {
    let normalized_workspace = workspace_path.trim();
    let normalized_thread_id = thread_id.trim();
    if normalized_workspace.is_empty() {
        return Err("workspace_path is required".to_string());
    }
    if normalized_thread_id.is_empty() {
        return Err("thread_id is required".to_string());
    }

    let data_dir = ensure_data_dir()?;
    let _ = app;
    let sidecar_path = bundled_onlineworker_bot_path()?;
    let script_path = temp_codex_tui_host_script_path();
    let script = build_codex_tui_host_script(
        &sidecar_path,
        &data_dir,
        normalized_workspace,
        normalized_thread_id,
    );
    write_executable_script(&script_path, &script)?;

    let result = Command::new("open")
        .args(["-a", "Terminal", script_path.to_string_lossy().as_ref()])
        .output()
        .map_err(|error| error.to_string())?;

    if result.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Failed to open codex TUI host terminal: {}",
            String::from_utf8_lossy(&result.stderr)
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::{build_codex_tui_host_script, shell_quote};
    use std::path::Path;

    #[test]
    fn shell_quote_wraps_single_quotes() {
        assert_eq!(shell_quote("/tmp/a'b"), "'/tmp/a'\\''b'");
    }

    #[test]
    fn codex_tui_host_script_uses_packaged_sidecar_entrypoint() {
        let script = build_codex_tui_host_script(
            Path::new("/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot"),
            Path::new("/Users/wxy/Library/Application Support/OnlineWorker"),
            "/Users/wxy/Projects/onlineworker-combined",
            "tid-1",
        );

        assert!(script.contains("--codex-tui-host"));
        assert!(script.contains("--codex-tui-cd '/Users/wxy/Projects/onlineworker-combined'"));
        assert!(script.contains("--codex-tui-target 'tid-1'"));
        assert!(script.contains("--codex-tui-extra-arg=--no-alt-screen"));
    }
}
