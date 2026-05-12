mod commands;
mod menubar;

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;
use std::{env, path::Path};
use tauri::Manager;
use tokio::sync::Mutex;

use commands::claude::{list_claude_sessions, read_claude_session, send_claude_session_message};
use commands::codex::{
    list_codex_threads, read_codex_thread, read_codex_thread_state, read_codex_thread_updates,
    send_codex_thread_message, start_codex_thread_stream, stop_codex_thread_stream,
};
use commands::command_registry::{
    get_command_registry, publish_telegram_commands, refresh_command_registry,
    set_command_telegram_enabled,
};
use commands::config::{
    check_first_run, create_default_config, get_provider_metadata, list_env_keys, read_config,
    read_env, read_env_field, read_env_raw, read_provider_runtime_policies_from_disk,
    reveal_env_field, set_provider_flags, write_config, write_env, write_env_field,
};
use commands::dashboard::get_dashboard_state;
use commands::logs::{get_log_file_path, start_log_tail, stop_log_tail};
use commands::provider_sessions::{
    list_provider_sessions, read_provider_session, send_provider_session_message,
    start_provider_session_stream, stop_provider_session_stream,
};
use commands::provider_usage::get_provider_usage_summary;
use commands::service::{
    check_cli, check_http_health, read_codex_mirror_status, service_restart, service_start,
    service_status, service_stop, shutdown_managed_processes_for_app_exit, snapshot_service_status,
    start_service_internal, BotState, ServiceStatus,
};
use commands::telegram::{test_bot_permissions, test_bot_token, test_group_access};
use commands::terminal::open_terminal;
use menubar::setup_menubar;

#[derive(Default)]
struct AppExitState {
    exiting: AtomicBool,
}

impl AppExitState {
    fn mark_exiting(&self) {
        self.exiting.store(true, Ordering::SeqCst);
    }

    fn is_exiting(&self) -> bool {
        self.exiting.load(Ordering::SeqCst)
    }
}

fn should_hide_window_on_close(window_label: &str, app_is_exiting: bool) -> bool {
    window_label == "main" && !app_is_exiting
}

fn should_cleanup_on_destroy(app_is_exiting: bool) -> bool {
    app_is_exiting
}

fn should_restore_main_window_on_reopen(has_visible_windows: bool) -> bool {
    !has_visible_windows
}

fn launch_service_self_check_delay() -> Duration {
    Duration::from_secs(10)
}

fn service_guard_check_interval() -> Duration {
    Duration::from_secs(15)
}

fn default_provider_overlay_env(
    current_overlay: Option<&str>,
    packaged_provider_plugins_dir: &Path,
) -> Option<String> {
    let current_overlay = current_overlay.map(str::trim).unwrap_or_default();
    if !current_overlay.is_empty() {
        return None;
    }
    if !packaged_provider_plugins_dir.exists() {
        return None;
    }
    Some(packaged_provider_plugins_dir.to_string_lossy().to_string())
}

fn apply_default_provider_overlay_env(app: &tauri::AppHandle) {
    let packaged_provider_plugins_dir = match app.path().resource_dir() {
        Ok(resource_dir) => resource_dir.join("provider-plugins"),
        Err(_) => return,
    };
    let default_overlay = default_provider_overlay_env(
        env::var("ONLINEWORKER_PROVIDER_OVERLAY").ok().as_deref(),
        &packaged_provider_plugins_dir,
    );
    if let Some(default_overlay) = default_overlay {
        env::set_var("ONLINEWORKER_PROVIDER_OVERLAY", default_overlay);
    }
}

fn should_auto_start_service_after_launch(status: &ServiceStatus) -> bool {
    !status.running
}

fn should_auto_start_service_in_session(
    status: &ServiceStatus,
    session_auto_start_enabled: bool,
    config_auto_start_enabled: bool,
) -> bool {
    session_auto_start_enabled
        && config_auto_start_enabled
        && should_auto_start_service_after_launch(status)
}

fn spawn_service_guard_loop(app_handle: tauri::AppHandle, state: Arc<Mutex<BotState>>) {
    tauri::async_runtime::spawn(async move {
        tokio::time::sleep(launch_service_self_check_delay()).await;
        let mut last_guard_state: Option<&'static str> = None;

        loop {
            match snapshot_service_status(&state).await {
                Ok(status) => {
                    let session_auto_start_enabled = {
                        let bot = state.lock().await;
                        bot.session_auto_start_enabled
                    };
                    let config_auto_start_enabled = read_provider_runtime_policies_from_disk()
                        .map(|policies| {
                            policies
                                .values()
                                .any(|policy| policy.managed && policy.autostart)
                        })
                        .unwrap_or(false);

                    if should_auto_start_service_in_session(
                        &status,
                        session_auto_start_enabled,
                        config_auto_start_enabled,
                    ) {
                        last_guard_state = Some("starting");
                        eprintln!(
                            "[app] service guard: service not running while config/session auto-start are enabled, starting now"
                        );
                        match start_service_internal(&app_handle, &state).await {
                            Ok(message) => {
                                eprintln!("[app] service guard: {}", message);
                            }
                            Err(error) => {
                                eprintln!("[app] service guard: start failed: {}", error);
                            }
                        }
                    } else if status.running {
                        if last_guard_state != Some("running") {
                            eprintln!(
                                "[app] service guard: service already running (pid={:?}), skip auto-start",
                                status.pid
                            );
                            last_guard_state = Some("running");
                        }
                    } else {
                        if last_guard_state != Some("disabled") {
                            eprintln!(
                                "[app] service guard: auto-start disabled by session or provider config, skip"
                            );
                            last_guard_state = Some("disabled");
                        }
                    }
                }
                Err(error) => {
                    if last_guard_state != Some("status-error") {
                        eprintln!(
                            "[app] service guard: failed to read service status: {}",
                            error
                        );
                        last_guard_state = Some("status-error");
                    }
                }
            }

            tokio::time::sleep(service_guard_check_interval()).await;
        }
    });
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .manage(Arc::new(Mutex::new(BotState::new())))
        .manage(AppExitState::default())
        .setup(|app| {
            apply_default_provider_overlay_env(&app.handle());
            // Ensure main window is visible on startup
            // (window-state plugin may restore visible:false from cache)
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
            }
            let state = app.state::<Arc<Mutex<BotState>>>().inner().clone();
            let app_handle = app.handle().clone();
            setup_menubar(&app_handle, state)?;
            spawn_service_guard_loop(
                app_handle,
                app.state::<Arc<Mutex<BotState>>>().inner().clone(),
            );
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            service_start,
            service_restart,
            service_stop,
            service_status,
            get_dashboard_state,
            read_codex_mirror_status,
            check_http_health,
            check_cli,
            get_log_file_path,
            start_log_tail,
            stop_log_tail,
            read_config,
            write_config,
            read_env,
            read_env_raw,
            write_env,
            read_env_field,
            write_env_field,
            set_provider_flags,
            get_provider_metadata,
            list_env_keys,
            reveal_env_field,
            open_terminal,
            list_codex_threads,
            read_codex_thread,
            read_codex_thread_state,
            read_codex_thread_updates,
            send_codex_thread_message,
            start_codex_thread_stream,
            stop_codex_thread_stream,
            list_claude_sessions,
            read_claude_session,
            send_claude_session_message,
            list_provider_sessions,
            read_provider_session,
            send_provider_session_message,
            start_provider_session_stream,
            stop_provider_session_stream,
            get_provider_usage_summary,
            test_bot_token,
            test_group_access,
            test_bot_permissions,
            get_command_registry,
            refresh_command_registry,
            set_command_telegram_enabled,
            publish_telegram_commands,
            check_first_run,
            create_default_config,
        ])
        .on_window_event(|window, event| match event {
            tauri::WindowEvent::CloseRequested { api, .. } => {
                let exit_state = window.app_handle().state::<AppExitState>();
                if should_hide_window_on_close(window.label(), exit_state.is_exiting()) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
            tauri::WindowEvent::Destroyed => {
                let app = window.app_handle().clone();
                let exit_state = app.state::<AppExitState>();
                if should_cleanup_on_destroy(exit_state.is_exiting()) {
                    tauri::async_runtime::block_on(async {
                        let state = app.state::<Arc<Mutex<BotState>>>();
                        shutdown_managed_processes_for_app_exit(state.inner()).await;
                    });
                }
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } => {
            let exit_state = app_handle.state::<AppExitState>();
            exit_state.mark_exiting();
        }
        #[cfg(target_os = "macos")]
        tauri::RunEvent::Reopen {
            has_visible_windows,
            ..
        } => {
            if should_restore_main_window_on_reopen(has_visible_windows) {
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.unminimize();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
        }
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::{
        default_provider_overlay_env, launch_service_self_check_delay,
        service_guard_check_interval, should_auto_start_service_after_launch,
        should_auto_start_service_in_session, should_cleanup_on_destroy, should_hide_window_on_close,
        should_restore_main_window_on_reopen,
    };
    use crate::commands::service::ServiceStatus;
    use std::{fs, time::Duration};

    #[test]
    fn main_window_close_hides_to_background_when_app_is_not_exiting() {
        assert!(should_hide_window_on_close("main", false));
    }

    #[test]
    fn main_window_close_does_not_hide_when_app_is_already_exiting() {
        assert!(!should_hide_window_on_close("main", true));
    }

    #[test]
    fn non_main_window_close_does_not_hide_to_background() {
        assert!(!should_hide_window_on_close("settings", false));
    }

    #[test]
    fn destroyed_window_only_triggers_cleanup_during_real_exit() {
        assert!(!should_cleanup_on_destroy(false));
        assert!(should_cleanup_on_destroy(true));
    }

    #[test]
    fn macos_reopen_restores_main_window_when_all_windows_are_hidden() {
        assert!(should_restore_main_window_on_reopen(false));
    }

    #[test]
    fn macos_reopen_does_not_force_restore_when_window_is_already_visible() {
        assert!(!should_restore_main_window_on_reopen(true));
    }

    #[test]
    fn launch_service_self_check_waits_ten_seconds_before_running() {
        assert_eq!(launch_service_self_check_delay(), Duration::from_secs(10));
    }

    #[test]
    fn service_guard_check_interval_runs_every_fifteen_seconds() {
        assert_eq!(service_guard_check_interval(), Duration::from_secs(15));
    }

    #[test]
    fn launch_service_self_check_only_auto_starts_when_service_is_not_running() {
        assert!(!should_auto_start_service_after_launch(&ServiceStatus {
            running: true,
            pid: Some(12345),
        }));
        assert!(should_auto_start_service_after_launch(&ServiceStatus {
            running: false,
            pid: None,
        }));
    }

    #[test]
    fn session_guard_only_auto_starts_when_enabled_and_service_is_stopped() {
        assert!(!should_auto_start_service_in_session(
            &ServiceStatus {
                running: true,
                pid: Some(12345),
            },
            true,
            true,
        ));
        assert!(!should_auto_start_service_in_session(
            &ServiceStatus {
                running: false,
                pid: None,
            },
            false,
            true,
        ));
        assert!(!should_auto_start_service_in_session(
            &ServiceStatus {
                running: false,
                pid: None,
            },
            true,
            false,
        ));
        assert!(should_auto_start_service_in_session(
            &ServiceStatus {
                running: false,
                pid: None,
            },
            true,
            true,
        ));
    }

    #[test]
    fn default_provider_overlay_env_uses_packaged_plugins_when_env_is_missing() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-packaged-provider-plugins-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create packaged provider dir");

        assert_eq!(
            default_provider_overlay_env(None, &dir).as_deref(),
            Some(dir.to_string_lossy().as_ref())
        );

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn default_provider_overlay_env_preserves_explicit_overlay() {
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-packaged-provider-plugins-explicit-{}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create packaged provider dir");

        assert_eq!(
            default_provider_overlay_env(Some("/tmp/custom-overlay"), &dir),
            None
        );

        let _ = fs::remove_dir_all(&dir);
    }
}
