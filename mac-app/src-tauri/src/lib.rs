mod commands;
mod menubar;

use std::io::Write;
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;
use std::{
    env, fs,
    path::{Path, PathBuf},
    thread,
};
use tauri::Manager;
use tokio::sync::Mutex;

use commands::ai_config::test_ai_service_connection;
use commands::attachment_cache::{clear_attachment_cache, get_attachment_cache_stats};
use commands::command_registry::{
    get_command_registry, publish_telegram_commands, refresh_command_registry,
    set_command_telegram_enabled,
};
use commands::config::{
    check_first_run, create_default_config, get_ai_config, get_notification_channels,
    get_provider_metadata, read_config, read_env, read_env_field, read_env_raw,
    read_provider_runtime_policies_from_disk, reveal_env_field, set_ai_config,
    set_notification_channel_config, set_notification_channel_enabled, set_provider_cli_config,
    set_provider_flags, set_provider_message_hook_enabled, validate_provider_config, write_config,
    write_env, write_env_field,
};
use commands::dashboard::get_dashboard_state;
use commands::logs::{get_log_file_path, start_log_tail, stop_log_tail};
use commands::provider_sessions::{
    archive_provider_session, create_provider_session, list_provider_sessions,
    read_provider_session, send_provider_session_message, stage_session_composer_attachments,
    start_provider_session_event_stream, start_provider_session_message,
    stop_provider_session_event_stream,
};
use commands::provider_usage::{get_usage_source_catalog, get_usage_source_summary};
use commands::service::{
    check_cli, service_restart, service_start, service_status, service_stop,
    shutdown_managed_processes_for_app_exit, snapshot_service_status, start_service_internal,
    BotState, ServiceStatus,
};
use commands::support_bundle::{
    export_support_bundle, reveal_support_bundle, run_support_diagnostics,
};
use commands::task_board_state::{
    control_task_board_session, get_task_board_session_activities, get_task_board_state,
    pin_task_board_session, reply_task_board_approval, start_task_board_activity_stream,
    stop_task_board_activity_stream, unpin_task_board_session,
};
use commands::telegram::{test_bot_permissions, test_bot_token, test_group_access};
use commands::terminal::{open_finder, open_provider_tui_host_terminal, open_terminal};
use menubar::{
    get_menubar_popover_snapshot, open_menubar_popover_session, open_menubar_tab, setup_menubar,
    show_main_window,
};

#[derive(Default)]
struct AppExitState {
    exiting: AtomicBool,
    cleanup_started: AtomicBool,
}

const SINGLE_INSTANCE_SOCKET_FILENAME: &str = "onlineworker-app-instance.sock";
const SINGLE_INSTANCE_ACTIVATE_MESSAGE: &[u8] = b"activate\n";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ExistingInstanceStatus {
    NotRunning,
    Activated,
    StaleSocket,
}

enum SingleInstanceStartup {
    Primary {
        listener: UnixListener,
        socket_path: PathBuf,
    },
    Secondary,
}

impl AppExitState {
    fn mark_exiting(&self) {
        self.exiting.store(true, Ordering::SeqCst);
    }

    fn is_exiting(&self) -> bool {
        self.exiting.load(Ordering::SeqCst)
    }

    fn begin_exit_cleanup(&self) -> bool {
        if self
            .cleanup_started
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return false;
        }
        self.mark_exiting();
        true
    }
}

fn should_hide_window_on_close(window_label: &str, app_is_exiting: bool) -> bool {
    matches!(window_label, "main" | "menubar-popover") && !app_is_exiting
}

fn should_hide_window_on_focus_loss(window_label: &str, focused: bool) -> bool {
    window_label == "menubar-popover" && !focused
}

fn should_cleanup_on_destroy(app_is_exiting: bool) -> bool {
    app_is_exiting
}

pub(crate) fn cleanup_managed_processes_for_exit_once(app: &tauri::AppHandle) {
    let exit_state = app.state::<AppExitState>();
    if !exit_state.begin_exit_cleanup() {
        return;
    }
    tauri::async_runtime::block_on(async {
        let state = app.state::<Arc<Mutex<BotState>>>();
        shutdown_managed_processes_for_app_exit(state.inner()).await;
    });
}

fn should_restore_main_window_on_reopen(has_visible_windows: bool) -> bool {
    !has_visible_windows
}

fn single_instance_socket_path(data_dir: &Path) -> PathBuf {
    data_dir.join(SINGLE_INSTANCE_SOCKET_FILENAME)
}

fn probe_existing_instance(socket_path: &Path) -> Result<ExistingInstanceStatus, String> {
    match UnixStream::connect(socket_path) {
        Ok(mut stream) => {
            stream
                .write_all(SINGLE_INSTANCE_ACTIVATE_MESSAGE)
                .map_err(|error| format!("write single-instance activation failed: {error}"))?;
            Ok(ExistingInstanceStatus::Activated)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            Ok(ExistingInstanceStatus::NotRunning)
        }
        Err(error)
            if matches!(
                error.kind(),
                std::io::ErrorKind::ConnectionRefused
                    | std::io::ErrorKind::ConnectionReset
                    | std::io::ErrorKind::BrokenPipe
            ) =>
        {
            Ok(ExistingInstanceStatus::StaleSocket)
        }
        Err(error) => Err(format!("connect single-instance socket failed: {error}")),
    }
}

fn bind_primary_instance_listener(socket_path: &Path) -> Result<UnixListener, String> {
    UnixListener::bind(socket_path)
        .map_err(|error| format!("bind single-instance socket failed: {error}"))
}

fn prepare_single_instance_startup(data_dir: &Path) -> Result<SingleInstanceStartup, String> {
    fs::create_dir_all(data_dir).map_err(|error| format!("create data dir failed: {error}"))?;
    let socket_path = single_instance_socket_path(data_dir);

    match probe_existing_instance(&socket_path)? {
        ExistingInstanceStatus::Activated => Ok(SingleInstanceStartup::Secondary),
        ExistingInstanceStatus::NotRunning => {
            let _ = fs::remove_file(&socket_path);
            let listener = bind_primary_instance_listener(&socket_path)?;
            Ok(SingleInstanceStartup::Primary {
                listener,
                socket_path,
            })
        }
        ExistingInstanceStatus::StaleSocket => {
            let _ = fs::remove_file(&socket_path);
            let listener = bind_primary_instance_listener(&socket_path)?;
            Ok(SingleInstanceStartup::Primary {
                listener,
                socket_path,
            })
        }
    }
}

fn cleanup_single_instance_socket(socket_path: &Path) {
    let _ = fs::remove_file(socket_path);
}

fn spawn_single_instance_listener(app_handle: tauri::AppHandle, listener: UnixListener) {
    thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(stream) = stream else {
                continue;
            };
            drop(stream);
            let app_handle = app_handle.clone();
            let focus_handle = app_handle.clone();
            let _ = app_handle.run_on_main_thread(move || {
                let _ = show_main_window(&focus_handle);
            });
        }
    });
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
    let data_dir = match commands::config::ensure_data_dir() {
        Ok(dir) => dir,
        Err(error) => panic!("failed to initialize app data dir: {error}"),
    };
    let single_instance = match prepare_single_instance_startup(&data_dir) {
        Ok(startup) => startup,
        Err(error) => panic!("failed to initialize single-instance guard: {error}"),
    };
    if matches!(single_instance, SingleInstanceStartup::Secondary) {
        return;
    }
    let (single_instance_listener, single_instance_socket_path) = match single_instance {
        SingleInstanceStartup::Primary {
            listener,
            socket_path,
        } => (listener, socket_path),
        SingleInstanceStartup::Secondary => unreachable!(),
    };

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
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
            spawn_single_instance_listener(app_handle.clone(), single_instance_listener);
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
            test_ai_service_connection,
            get_dashboard_state,
            check_cli,
            get_attachment_cache_stats,
            clear_attachment_cache,
            run_support_diagnostics,
            export_support_bundle,
            reveal_support_bundle,
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
            set_provider_cli_config,
            set_provider_message_hook_enabled,
            get_ai_config,
            set_ai_config,
            get_notification_channels,
            set_notification_channel_config,
            set_notification_channel_enabled,
            get_provider_metadata,
            validate_provider_config,
            reveal_env_field,
            open_terminal,
            open_finder,
            open_provider_tui_host_terminal,
            list_provider_sessions,
            read_provider_session,
            create_provider_session,
            archive_provider_session,
            send_provider_session_message,
            start_provider_session_message,
            stage_session_composer_attachments,
            start_provider_session_event_stream,
            stop_provider_session_event_stream,
            get_usage_source_catalog,
            get_usage_source_summary,
            get_menubar_popover_snapshot,
            open_menubar_popover_session,
            open_menubar_tab,
            get_task_board_session_activities,
            get_task_board_state,
            control_task_board_session,
            pin_task_board_session,
            reply_task_board_approval,
            start_task_board_activity_stream,
            stop_task_board_activity_stream,
            unpin_task_board_session,
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
                let app = window.app_handle().clone();
                let exit_state = app.state::<AppExitState>();
                if should_hide_window_on_close(window.label(), exit_state.is_exiting()) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
            tauri::WindowEvent::Destroyed => {
                let app = window.app_handle().clone();
                let exit_state = app.state::<AppExitState>();
                if should_cleanup_on_destroy(exit_state.is_exiting()) {
                    cleanup_managed_processes_for_exit_once(&app);
                }
            }
            tauri::WindowEvent::Focused(focused) => {
                if should_hide_window_on_focus_loss(window.label(), *focused) {
                    let _ = window.hide();
                }
            }
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(move |app_handle, event| match event {
        tauri::RunEvent::ExitRequested { .. } => {
            let exit_state = app_handle.state::<AppExitState>();
            exit_state.mark_exiting();
            cleanup_managed_processes_for_exit_once(app_handle);
            cleanup_single_instance_socket(&single_instance_socket_path);
        }
        tauri::RunEvent::Exit => {
            cleanup_managed_processes_for_exit_once(app_handle);
            cleanup_single_instance_socket(&single_instance_socket_path);
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
        prepare_single_instance_startup, probe_existing_instance, service_guard_check_interval,
        should_auto_start_service_after_launch, should_auto_start_service_in_session,
        should_cleanup_on_destroy, should_hide_window_on_close, should_hide_window_on_focus_loss,
        should_restore_main_window_on_reopen, single_instance_socket_path, AppExitState,
        ExistingInstanceStatus, SingleInstanceStartup,
    };
    use crate::commands::service::ServiceStatus;
    use std::os::unix::net::UnixListener;
    use std::{fs, path::Path, time::Duration};

    fn temp_single_instance_dir(name: &str) -> std::path::PathBuf {
        let dir =
            std::path::PathBuf::from("/tmp").join(format!("ow-si-{name}-{}", std::process::id(),));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    #[test]
    fn main_window_close_hides_window_when_app_is_not_exiting() {
        assert!(should_hide_window_on_close("main", false));
    }

    #[test]
    fn popover_window_close_hides_window_when_app_is_not_exiting() {
        assert!(should_hide_window_on_close("menubar-popover", false));
    }

    #[test]
    fn main_window_close_does_not_hide_window_when_app_is_already_exiting() {
        assert!(!should_hide_window_on_close("main", true));
    }

    #[test]
    fn non_main_window_close_does_not_hide_window() {
        assert!(!should_hide_window_on_close("settings", false));
    }

    #[test]
    fn popover_focus_loss_hides_only_popover_window() {
        assert!(should_hide_window_on_focus_loss("menubar-popover", false));
        assert!(!should_hide_window_on_focus_loss("menubar-popover", true));
        assert!(!should_hide_window_on_focus_loss("main", false));
    }

    #[test]
    fn destroyed_window_only_triggers_cleanup_during_real_exit() {
        assert!(!should_cleanup_on_destroy(false));
        assert!(should_cleanup_on_destroy(true));
    }

    #[test]
    fn exit_cleanup_can_start_even_when_exit_requested_was_not_observed() {
        let exit_state = AppExitState::default();

        assert!(exit_state.begin_exit_cleanup());
        assert!(exit_state.is_exiting());
        assert!(!exit_state.begin_exit_cleanup());
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
    fn single_instance_socket_path_uses_data_dir() {
        let data_dir = Path::new("/tmp/onlineworker-data");
        assert_eq!(
            single_instance_socket_path(data_dir),
            data_dir.join("onlineworker-app-instance.sock")
        );
    }

    #[test]
    fn probe_existing_instance_reports_not_running_when_socket_is_missing() {
        let dir = temp_single_instance_dir("missing");
        let socket_path = single_instance_socket_path(&dir);

        assert_eq!(
            probe_existing_instance(&socket_path).expect("probe missing socket"),
            ExistingInstanceStatus::NotRunning
        );

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn probe_existing_instance_reports_activated_when_listener_exists() {
        let dir = temp_single_instance_dir("active");
        let socket_path = single_instance_socket_path(&dir);
        let listener = UnixListener::bind(&socket_path).expect("bind listener");

        assert_eq!(
            probe_existing_instance(&socket_path).expect("probe active listener"),
            ExistingInstanceStatus::Activated
        );

        drop(listener);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn probe_existing_instance_reports_stale_socket_when_listener_is_gone() {
        let dir = temp_single_instance_dir("stale");
        let socket_path = single_instance_socket_path(&dir);
        let listener = UnixListener::bind(&socket_path).expect("bind listener");
        drop(listener);

        assert_eq!(
            probe_existing_instance(&socket_path).expect("probe stale socket"),
            ExistingInstanceStatus::StaleSocket
        );

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn prepare_single_instance_startup_returns_secondary_when_listener_exists() {
        let dir = temp_single_instance_dir("secondary");
        let socket_path = single_instance_socket_path(&dir);
        let listener = UnixListener::bind(&socket_path).expect("bind listener");

        assert!(matches!(
            prepare_single_instance_startup(&dir).expect("prepare single instance startup"),
            SingleInstanceStartup::Secondary
        ));

        drop(listener);
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn prepare_single_instance_startup_rebinds_stale_socket_as_primary() {
        let dir = temp_single_instance_dir("primary");
        let socket_path = single_instance_socket_path(&dir);
        let listener = UnixListener::bind(&socket_path).expect("bind listener");
        drop(listener);

        let startup = prepare_single_instance_startup(&dir).expect("prepare startup");
        match startup {
            SingleInstanceStartup::Primary { socket_path, .. } => {
                assert_eq!(socket_path, single_instance_socket_path(&dir));
            }
            SingleInstanceStartup::Secondary => panic!("expected primary startup"),
        }

        let _ = fs::remove_dir_all(&dir);
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
