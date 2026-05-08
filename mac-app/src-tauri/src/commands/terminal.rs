use std::process::Command;

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
