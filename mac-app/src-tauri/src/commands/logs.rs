use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::ipc::Channel;
use tauri::AppHandle;

use super::config::data_dir;

// Global stop flag for log tail
static LOG_TAIL_RUNNING: std::sync::OnceLock<Arc<AtomicBool>> = std::sync::OnceLock::new();

fn get_running_flag() -> Arc<AtomicBool> {
    LOG_TAIL_RUNNING
        .get_or_init(|| Arc::new(AtomicBool::new(false)))
        .clone()
}

#[tauri::command]
pub async fn start_log_tail(_app: AppHandle, channel: Channel<String>) -> Result<(), String> {
    let log_path = data_dir().join("onlineworker.log");
    let running = get_running_flag();
    running.store(true, Ordering::SeqCst);

    let running_clone = running.clone();
    tauri::async_runtime::spawn(async move {
        let file = match std::fs::File::open(&log_path) {
            Ok(f) => f,
            Err(e) => {
                let _ = channel.send(format!("[ERROR] Cannot open log: {}", e));
                return;
            }
        };
        let mut reader = BufReader::new(file);
        // Seek to end — only tail new lines
        let _ = reader.seek(SeekFrom::End(0));

        while running_clone.load(Ordering::SeqCst) {
            let mut line = String::new();
            match reader.read_line(&mut line) {
                Ok(0) => {
                    tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
                }
                Ok(_) => {
                    let trimmed = line.trim().to_string();
                    if !trimmed.is_empty() {
                        let _ = channel.send(trimmed);
                    }
                }
                Err(_) => break,
            }
        }
    });

    Ok(())
}

#[tauri::command]
pub fn get_log_file_path() -> Result<String, String> {
    Ok(data_dir().join("onlineworker.log").display().to_string())
}

#[tauri::command]
pub async fn stop_log_tail() -> Result<(), String> {
    get_running_flag().store(false, Ordering::SeqCst);
    Ok(())
}
