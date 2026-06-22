use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

use tauri::AppHandle;

use super::config::{ensure_data_dir, read_provider_metadata_from_disk};

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn temp_provider_tui_host_script_path() -> PathBuf {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or(0);
    std::env::temp_dir().join(format!("onlineworker-provider-tui-host-{}.command", stamp))
}

fn build_provider_tui_host_script(
    sidecar_path: &Path,
    data_dir: &Path,
    workspace_path: &str,
    sidecar_args: &[String],
) -> String {
    let rendered_args = sidecar_args
        .iter()
        .map(|arg| shell_quote(arg))
        .collect::<Vec<_>>()
        .join(" ");
    format!(
        "#!/bin/zsh\nset -e\ncd {workspace}\nexec {bot} --data-dir {data_dir}{args}\n",
        workspace = shell_quote(workspace_path),
        bot = shell_quote(&sidecar_path.to_string_lossy()),
        data_dir = shell_quote(&data_dir.to_string_lossy()),
        args = if rendered_args.is_empty() {
            String::new()
        } else {
            format!(" {rendered_args}")
        },
    )
}

fn render_provider_tui_host_args(
    templates: &[String],
    workspace_path: &str,
    thread_id: &str,
) -> Vec<String> {
    templates
        .iter()
        .map(|template| {
            template
                .replace("{workspace}", workspace_path)
                .replace("{thread_id}", thread_id)
        })
        .collect()
}

fn provider_tui_host_sidecar_args(provider_id: &str) -> Result<Vec<String>, String> {
    let normalized_provider_id = provider_id.trim();
    if normalized_provider_id.is_empty() {
        return Err("provider_id is required".to_string());
    }

    let provider = read_provider_metadata_from_disk()?
        .into_iter()
        .find(|provider| provider.id == normalized_provider_id)
        .ok_or_else(|| format!("Provider not found: {normalized_provider_id}"))?;
    let sidecar_args = provider
        .tui_host
        .sidecar_args
        .into_iter()
        .map(|arg| arg.trim().to_string())
        .filter(|arg| !arg.is_empty())
        .collect::<Vec<_>>();
    if sidecar_args.is_empty() {
        Err(format!(
            "Provider {normalized_provider_id} does not declare tui_host.sidecar_args"
        ))
    } else {
        Ok(sidecar_args)
    }
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
pub async fn open_finder(workspace_path: String) -> Result<(), String> {
    let normalized_workspace = workspace_path.trim();
    if normalized_workspace.is_empty() {
        return Err("workspace_path is required".to_string());
    }

    let result = Command::new("open")
        .args(["-a", "Finder", normalized_workspace])
        .output()
        .map_err(|e| e.to_string())?;

    if result.status.success() {
        Ok(())
    } else {
        Err(format!(
            "Failed to open Finder: {}",
            String::from_utf8_lossy(&result.stderr)
        ))
    }
}

#[tauri::command]
pub async fn open_provider_tui_host_terminal(
    app: AppHandle,
    provider_id: String,
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
    let script_path = temp_provider_tui_host_script_path();
    let sidecar_arg_templates = provider_tui_host_sidecar_args(&provider_id)?;
    let sidecar_args = render_provider_tui_host_args(
        &sidecar_arg_templates,
        normalized_workspace,
        normalized_thread_id,
    );
    let script = build_provider_tui_host_script(
        &sidecar_path,
        &data_dir,
        normalized_workspace,
        &sidecar_args,
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
            "Failed to open provider TUI host terminal: {}",
            String::from_utf8_lossy(&result.stderr)
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::{build_provider_tui_host_script, render_provider_tui_host_args, shell_quote};
    use std::path::Path;

    #[test]
    fn shell_quote_wraps_single_quotes() {
        assert_eq!(shell_quote("/tmp/a'b"), "'/tmp/a'\\''b'");
    }

    #[test]
    fn provider_tui_host_script_uses_packaged_sidecar_entrypoint() {
        let script = build_provider_tui_host_script(
            Path::new("/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-bot"),
            Path::new("/Users/example/Library/Application Support/OnlineWorker"),
            "/Users/example/Projects/sample-repo",
            &[
                "--provider-tui-host".to_string(),
                "--provider-cd=/Users/example/Projects/sample-repo".to_string(),
                "--provider-target=tid-1".to_string(),
                "--provider-extra-arg=--no-alt-screen".to_string(),
            ],
        );

        assert!(script.contains("'--provider-tui-host'"));
        assert!(script.contains("'--provider-cd=/Users/example/Projects/sample-repo'"));
        assert!(script.contains("'--provider-target=tid-1'"));
        assert!(script.contains("'--provider-extra-arg=--no-alt-screen'"));
    }

    #[test]
    fn provider_tui_host_args_replace_workspace_and_thread_placeholders() {
        let rendered = render_provider_tui_host_args(
            &[
                "--provider-cd={workspace}".to_string(),
                "--provider-target={thread_id}".to_string(),
            ],
            "/Users/example/Projects/sample-repo",
            "tid-1",
        );

        assert_eq!(
            rendered,
            vec![
                "--provider-cd=/Users/example/Projects/sample-repo",
                "--provider-target=tid-1",
            ]
        );
    }
}
