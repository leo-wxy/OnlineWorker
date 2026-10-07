use semver::Version;
use serde::Serialize;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tauri::{AppHandle, Emitter, State};
use tauri_plugin_updater::{Update, UpdaterExt};

use super::config::ensure_data_dir;
use super::provider_bridge_common::provider_owner_bridge_socket_path;
use super::service::{snapshot_service_status, start_service_internal, stop_service_internal, BotState};

const RELEASE_PAGE: &str = "https://github.com/leo-wxy/OnlineWorker/releases/latest";

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppUpdateInfo {
    revision: u64,
    current_version: String,
    latest_version: String,
    update_available: bool,
    phase: String,
    downloaded_bytes: u64,
    total_bytes: Option<u64>,
    notes: String,
}

impl Default for AppUpdateInfo {
    fn default() -> Self {
        Self { revision: 0, current_version: env!("CARGO_PKG_VERSION").into(), latest_version: String::new(),
            update_available: false, phase: "idle".into(), downloaded_bytes: 0,
            total_bytes: None, notes: String::new() }
    }
}

#[derive(Default)]
struct PendingUpdate {
    update: Option<Update>,
    // ponytail: keep one verified package in memory; spool to disk if package sizes demand it.
    bytes: Option<Arc<Vec<u8>>>,
    info: AppUpdateInfo,
}

#[derive(Default)]
pub struct AppUpdateState {
    operation: tokio::sync::Mutex<()>,
    pending: Mutex<PendingUpdate>,
}

impl AppUpdateState {
    fn snapshot(&self) -> AppUpdateInfo { self.pending.lock().unwrap().info.clone() }
    fn publish(&self, app: &AppHandle) {
        let info = {
            let mut pending = self.pending.lock().unwrap();
            pending.info.revision += 1;
            pending.info.clone()
        };
        let _ = app.emit("app-update-status", info);
    }
    fn phase(&self, app: &AppHandle, phase: &str) {
        self.pending.lock().unwrap().info.phase = phase.into();
        self.publish(app);
    }
}

#[tauri::command]
pub fn get_app_update_status(state: State<'_, AppUpdateState>) -> AppUpdateInfo { state.snapshot() }

#[tauri::command]
pub async fn check_app_update(app: AppHandle, state: State<'_, AppUpdateState>) -> Result<AppUpdateInfo, String> {
    let _operation = state.operation.try_lock().map_err(|_| "更新操作正在进行中。")?;
    let previous = state.snapshot().phase;
    state.phase(&app, "checking");
    let result = async {
        app.updater_builder().timeout(Duration::from_secs(30))
            .version_comparator(|current, release| release.version.pre.is_empty() && release.version.cmp_precedence(&current).is_gt())
            .build().map_err(|e| e.to_string())?.check().await.map_err(|e| e.to_string())
    }.await;
    match result {
        Ok(update) => {
            let mut pending = state.pending.lock().unwrap();
            let same_package = pending.update.as_ref().zip(update.as_ref()).is_some_and(|(old, new)|
                old.version == new.version && old.signature == new.signature && old.download_url == new.download_url);
            if !same_package { pending.bytes = None; }
            pending.info.latest_version = update.as_ref().map(|u| u.version.clone()).unwrap_or_default();
            pending.info.notes = update.as_ref().and_then(|u| u.body.clone()).unwrap_or_default();
            pending.info.update_available = update.is_some();
            pending.info.phase = if pending.bytes.is_some() { "ready" } else if update.is_some() { "available" } else { "current" }.into();
            if pending.bytes.is_none() { pending.info.downloaded_bytes = 0; pending.info.total_bytes = None; }
            pending.update = update;
            drop(pending);
            state.publish(&app);
            Ok(state.snapshot())
        }
        Err(error) => { state.phase(&app, &previous); Err(format!("检查更新失败：{error}")) }
    }
}

#[tauri::command]
pub async fn download_app_update(app: AppHandle, state: State<'_, AppUpdateState>) -> Result<AppUpdateInfo, String> {
    let _operation = state.operation.try_lock().map_err(|_| "更新操作正在进行中。")?;
    let mut update = state.pending.lock().unwrap().update.clone().ok_or("请先检查更新。")?;
    update.timeout = Some(Duration::from_secs(900));
    if state.pending.lock().unwrap().bytes.is_some() { return Ok(state.snapshot()); }
    state.phase(&app, "downloading");
    {
        let mut pending = state.pending.lock().unwrap();
        pending.info.downloaded_bytes = 0;
        pending.info.total_bytes = None;
    }
    let bytes = update.download(|chunk, total| {
        {
            let mut pending = state.pending.lock().unwrap();
            pending.info.downloaded_bytes += chunk as u64;
            pending.info.total_bytes = total;
        }
        state.publish(&app);
    }, || {}).await;
    match bytes {
        Ok(bytes) => {
            let mut pending = state.pending.lock().unwrap();
            pending.info.downloaded_bytes = bytes.len() as u64;
            pending.bytes = Some(Arc::new(bytes));
            pending.info.phase = "ready".into();
            drop(pending);
            state.publish(&app);
            Ok(state.snapshot())
        }
        Err(error) => { state.phase(&app, "available"); Err(format!("下载或签名校验失败：{error}")) }
    }
}

fn update_bridge_request(socket_path: &Path, request_type: &str) -> Result<(), String> {
    let mut socket = UnixStream::connect(socket_path).map_err(|e| format!("无法确认任务空闲：{e}"))?;
    socket.set_read_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    socket.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
    writeln!(socket, "{}", serde_json::json!({"type": request_type})).map_err(|e| e.to_string())?;
    let mut line = String::new();
    BufReader::new(socket).read_line(&mut line).map_err(|e| e.to_string())?;
    let response: serde_json::Value = serde_json::from_str(&line).map_err(|e| e.to_string())?;
    if response["ok"] == true { Ok(()) } else {
        Err(response["error"].as_str().unwrap_or("无法确认任务空闲。").into())
    }
}

fn current_app_bundle(executable: &Path) -> Result<PathBuf, String> {
    executable.ancestors().find(|path| path.extension().is_some_and(|ext| ext == "app"))
        .map(Path::to_path_buf).ok_or_else(|| "自动安装仅适用于已安装的 App，请从官方下载页安装。".into())
}

struct AppBackup { source: PathBuf, previous: PathBuf }

fn backup_app(source: &Path) -> Result<AppBackup, String> {
    let parent = source.parent().ok_or("无效的 App 安装路径。")?;
    // ponytail: retain each backup; add user-approved archive cleanup if disk use matters.
    let folder = parent.join(format!(".OnlineWorker-update-{}", uuid::Uuid::new_v4()));
    std::fs::create_dir(&folder).map_err(|e| format!("安装目录不可写，请使用官方下载页的 DMG 手动安装：{e}"))?;
    let previous = folder.join("previous.app");
    let status = std::process::Command::new("ditto").arg(source).arg(&previous).status().map_err(|e| e.to_string())?;
    if !status.success() { return Err("创建旧 App 备份失败，未开始安装。".into()); }
    std::fs::write(folder.join("manifest.json"), serde_json::to_vec_pretty(&serde_json::json!({
        "source": source, "backup": previous, "version": env!("CARGO_PKG_VERSION"),
    })).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    Ok(AppBackup { source: source.to_path_buf(), previous })
}

fn prepare_app_backup(source: &Path, mut check_idle: impl FnMut() -> Result<(), String>) -> Result<AppBackup, String> {
    check_idle()?;
    let backup = backup_app(source)?;
    // Copying can outlast the admission lease; recheck before stopping the bot.
    check_idle()?;
    Ok(backup)
}

fn restore_app(backup: &AppBackup) -> Result<(), String> {
    let failed = backup.previous.parent().unwrap().join("failed.app");
    if backup.source.exists() { std::fs::rename(&backup.source, &failed).map_err(|e| e.to_string())?; }
    if let Err(error) = std::fs::rename(&backup.previous, &backup.source) {
        if failed.exists() { let _ = std::fs::rename(&failed, &backup.source); }
        return Err(format!("恢复旧 App 失败：{error}；备份：{}", backup.previous.display()));
    }
    Ok(())
}

fn verify_installed_app(path: &Path, version: &str, identifier: &str) -> Result<(), String> {
    for (key, expected) in [("CFBundleShortVersionString", version), ("CFBundleIdentifier", identifier)] {
        let output = std::process::Command::new("/usr/libexec/PlistBuddy")
            .args(["-c", &format!("Print :{key}")]).arg(path.join("Contents/Info.plist"))
            .output().map_err(|e| e.to_string())?;
        if !output.status.success() || String::from_utf8_lossy(&output.stdout).trim() != expected {
            return Err(format!("更新后的 App {key} 与预期不符。"));
        }
    }
    for binary in ["onlineworker-app", "onlineworker-bot", "ccusage"] {
        if !path.join("Contents/MacOS").join(binary).is_file() { return Err(format!("更新包缺少 {binary}。")); }
    }
    Ok(())
}

fn install_with_backup(backup: &AppBackup, install: impl FnOnce() -> Result<(), String>) -> Result<(), String> {
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(install))
        .unwrap_or_else(|_| Err("更新安装器异常退出。".into()));
    match result {
        Ok(()) => Ok(()),
        Err(error) => match restore_app(backup) {
            Ok(()) => Err(format!("{error}；已恢复旧 App。")),
            Err(restore_error) => Err(format!("{error}；{restore_error}")),
        },
    }
}

#[tauri::command]
pub async fn install_app_update(app: AppHandle, state: State<'_, AppUpdateState>, bot_state: State<'_, Arc<tokio::sync::Mutex<BotState>>>) -> Result<(), String> {
    let _operation = state.operation.try_lock().map_err(|_| "更新操作正在进行中。")?;
    let (update, bytes) = {
        let pending = state.pending.lock().unwrap();
        (pending.update.clone().ok_or("请先检查更新。")?, pending.bytes.clone().ok_or("请先下载更新。")?)
    };
    let bundle = current_app_bundle(&std::env::current_exe().map_err(|e| e.to_string())?)?;
    let expected_version = Version::parse(&update.version).map_err(|e| e.to_string())?.to_string();
    let expected_identifier = app.config().identifier.clone();
    let socket = provider_owner_bridge_socket_path(&ensure_data_dir()?);
    state.phase(&app, "installing");
    {
        let mut bot = bot_state.lock().await;
        if bot.starting || bot.updating { state.phase(&app, "ready"); return Err("服务正在启动或更新，请稍后再安装。".into()); }
        bot.updating = true;
    }
    let result = async {
        let was_running = snapshot_service_status(bot_state.inner()).await?.running;
        let source = bundle.clone();
        let socket_path = socket.clone();
        let backup = tauri::async_runtime::spawn_blocking(move || {
            prepare_app_backup(&source, || {
                if was_running { update_bridge_request(&socket_path, "prepare_app_update") } else { Ok(()) }
            })
        }).await.map_err(|e| e.to_string())??;
        let installed = async {
            stop_service_internal(bot_state.inner()).await?;
            for attempt in 0..30 {
                if !snapshot_service_status(bot_state.inner()).await?.running { break; }
                if attempt == 29 { return Err("旧 bot 未完全退出，未覆盖 App。".into()); }
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            tauri::async_runtime::spawn_blocking(move || install_with_backup(&backup, || {
                update.install(bytes.as_slice()).map_err(|e| e.to_string())?;
                verify_installed_app(&bundle, &expected_version, &expected_identifier)
            })).await.map_err(|e| e.to_string())?
        }.await;
        if let Err(error) = installed {
            bot_state.lock().await.updating = false;
            if was_running {
                if let Err(restart_error) = start_service_internal(&app, bot_state.inner()).await {
                    return Err(format!("{error}；恢复 bot 失败：{restart_error}"));
                }
            }
            return Err(error);
        }
        Ok(was_running)
    }.await;
    let was_running = match result {
        Ok(was_running) => was_running,
        Err(error) => {
            bot_state.lock().await.updating = false;
            let _ = tauri::async_runtime::spawn_blocking(move || update_bridge_request(&socket, "cancel_app_update")).await;
            state.phase(&app, "ready");
            return Err(error);
        }
    };
    std::env::set_var("ONLINEWORKER_SERVICE_AFTER_UPDATE", if was_running { "running" } else { "stopped" });
    // Reuse the app exit lifecycle to clean remaining managed processes.
    app.restart()
}

#[tauri::command]
pub async fn open_app_release_page() -> Result<(), String> {
    let status = std::process::Command::new("open").arg(RELEASE_PAGE).status().map_err(|e| e.to_string())?;
    if status.success() { Ok(()) } else { Err("Open release page failed".into()) }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn busy_tasks_prevent_backup_and_idle_is_rechecked_after_copy() {
        let folder = std::env::temp_dir().join(format!("ow-update-{}", uuid::Uuid::new_v4()));
        let source = folder.join("OnlineWorker.app");
        std::fs::create_dir_all(&source).unwrap();
        assert!(prepare_app_backup(&source, || Err("busy".into())).is_err());
        assert_eq!(std::fs::read_dir(&folder).unwrap().count(), 1);
        let mut checks = 0;
        assert!(prepare_app_backup(&source, || {
            checks += 1;
            if checks == 2 { Err("new task after lease expired".into()) } else { Ok(()) }
        }).is_err());
        assert_eq!(checks, 2);
        assert!(source.exists());
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn install_failure_restores_the_previous_app_without_deleting_failed_contents() {
        let folder = std::env::temp_dir().join(format!("ow-update-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&folder).unwrap();
        let source = folder.join("OnlineWorker.app");
        std::fs::create_dir(&source).unwrap();
        std::fs::write(source.join("version"), "old").unwrap();
        let backup = backup_app(&source).unwrap();
        let error = install_with_backup(&backup, || {
            std::fs::write(source.join("version"), "partial-new").unwrap();
            Err("install failed".into())
        }).unwrap_err();
        assert!(error.contains("已恢复旧 App"));
        assert_eq!(std::fs::read_to_string(source.join("version")).unwrap(), "old");
        assert_eq!(std::fs::read_to_string(backup.previous.parent().unwrap().join("failed.app/version")).unwrap(), "partial-new");
        assert!(backup.previous.parent().unwrap().join("manifest.json").exists());
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn development_executable_cannot_be_used_as_an_install_target() {
        assert!(current_app_bundle(Path::new("/tmp/sample-workspace/target/debug/onlineworker-app")).is_err());
        assert_eq!(current_app_bundle(Path::new("/Applications/OnlineWorker.app/Contents/MacOS/onlineworker-app")).unwrap(), PathBuf::from("/Applications/OnlineWorker.app"));
    }
}
