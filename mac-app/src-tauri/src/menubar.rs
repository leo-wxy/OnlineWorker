use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use tauri::image::Image;
use tauri::menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::{AppHandle, Emitter, Manager, Wry};
use tokio::sync::Mutex;

use crate::commands::dashboard::{compute_dashboard_state, DashboardState, SystemHealth};
use crate::commands::service::{
    ensure_service_running_if_needed, snapshot_service_status, start_service_internal,
    stop_service_internal, BotState,
};
use crate::AppExitState;

const APP_TRAY_ID: &str = "main-tray";
const APP_TRAY_TITLE_ID: &str = "tray_app_title";
const APP_TRAY_STATUS_ID: &str = "tray_status";
const APP_TRAY_WORKSPACE_ID: &str = "tray_workspace";
const APP_TRAY_SESSION_ID: &str = "tray_session";
const APP_TRAY_OPEN_DASHBOARD_ID: &str = "tray_open_dashboard";
const APP_TRAY_OPEN_SESSIONS_ID: &str = "tray_open_sessions";
const APP_TRAY_OPEN_SETUP_ID: &str = "tray_open_setup";
const APP_TRAY_TOGGLE_SERVICE_ID: &str = "tray_toggle_service";
const APP_TRAY_QUIT_ID: &str = "tray_quit";
const APP_NAVIGATE_TAB_EVENT: &str = "app:navigate-tab";
const APP_NAME: &str = "OnlineWorker";
const STATUS_PREFIX: &str = "Status: ";
const WORKSPACE_PREFIX: &str = "Workspace: ";
const SESSION_PREFIX: &str = "Active Session: ";
const REFRESH_INTERVAL_SECONDS: u64 = 4;
const CUSTOM_TRAY_ICON_RELATIVE_PATH: &str = "icons/tray-template.png";
const CUSTOM_TRAY_ICON_2X_RELATIVE_PATH: &str = "icons/tray-template@2x.png";

#[derive(Clone)]
struct TrayMenuHandles {
    status_item: MenuItem<Wry>,
    workspace_item: MenuItem<Wry>,
    session_item: MenuItem<Wry>,
    toggle_service_item: MenuItem<Wry>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TrayStatus {
    Running,
    Stopped,
    Degraded,
}

impl TrayStatus {
    fn label(self) -> &'static str {
        match self {
            Self::Running => "Running",
            Self::Stopped => "Stopped",
            Self::Degraded => "Degraded",
        }
    }
}

fn resolve_custom_tray_icon_paths(resource_dir: &Path) -> [PathBuf; 2] {
    [
        resource_dir.join(CUSTOM_TRAY_ICON_2X_RELATIVE_PATH),
        resource_dir.join(CUSTOM_TRAY_ICON_RELATIVE_PATH),
    ]
}

fn load_custom_tray_icon(app: &AppHandle) -> Option<Image<'static>> {
    let mut candidates = Vec::new();

    if let Ok(resource_dir) = app.path().resource_dir() {
        candidates.extend(resolve_custom_tray_icon_paths(&resource_dir));
    }

    candidates.push(Path::new(env!("CARGO_MANIFEST_DIR")).join(CUSTOM_TRAY_ICON_2X_RELATIVE_PATH));
    candidates.push(Path::new(env!("CARGO_MANIFEST_DIR")).join(CUSTOM_TRAY_ICON_RELATIVE_PATH));

    candidates
        .into_iter()
        .find(|path| path.exists())
        .and_then(|path| Image::from_path(path).ok())
        .map(Image::to_owned)
}

pub(crate) fn setup_menubar(app: &AppHandle, state: Arc<Mutex<BotState>>) -> tauri::Result<()> {
    let app_title_item = MenuItem::with_id(app, APP_TRAY_TITLE_ID, APP_NAME, false, None::<&str>)?;
    let status_item = MenuItem::with_id(
        app,
        APP_TRAY_STATUS_ID,
        format!("{}Unknown", STATUS_PREFIX),
        false,
        None::<&str>,
    )?;
    let workspace_item = MenuItem::with_id(
        app,
        APP_TRAY_WORKSPACE_ID,
        workspace_menu_label(None),
        false,
        None::<&str>,
    )?;
    let session_item = MenuItem::with_id(
        app,
        APP_TRAY_SESSION_ID,
        session_menu_label(None),
        false,
        None::<&str>,
    )?;
    let open_dashboard_item = MenuItem::with_id(
        app,
        APP_TRAY_OPEN_DASHBOARD_ID,
        "Open Dashboard",
        true,
        None::<&str>,
    )?;
    let open_sessions_item = MenuItem::with_id(
        app,
        APP_TRAY_OPEN_SESSIONS_ID,
        "Open Sessions",
        true,
        None::<&str>,
    )?;
    let open_setup_item = MenuItem::with_id(
        app,
        APP_TRAY_OPEN_SETUP_ID,
        "Open Setup",
        true,
        None::<&str>,
    )?;
    let toggle_service_item = MenuItem::with_id(
        app,
        APP_TRAY_TOGGLE_SERVICE_ID,
        service_toggle_label(false),
        true,
        None::<&str>,
    )?;
    let quit_item = MenuItem::with_id(app, APP_TRAY_QUIT_ID, "Quit", true, None::<&str>)?;
    let top_separator = PredefinedMenuItem::separator(app)?;
    let bottom_separator = PredefinedMenuItem::separator(app)?;

    let menu = Menu::with_items(
        app,
        &[
            &app_title_item,
            &status_item,
            &workspace_item,
            &session_item,
            &top_separator,
            &open_dashboard_item,
            &open_sessions_item,
            &open_setup_item,
            &bottom_separator,
            &toggle_service_item,
            &quit_item,
        ],
    )?;

    let handles = TrayMenuHandles {
        status_item: status_item.clone(),
        workspace_item: workspace_item.clone(),
        session_item: session_item.clone(),
        toggle_service_item: toggle_service_item.clone(),
    };

    let tray = build_tray(app, &menu, state.clone(), handles.clone())?;
    start_menubar_refresh_loop(app.clone(), state, handles, tray);

    Ok(())
}

fn build_tray(
    app: &AppHandle,
    menu: &Menu<Wry>,
    state: Arc<Mutex<BotState>>,
    handles: TrayMenuHandles,
) -> tauri::Result<TrayIcon<Wry>> {
    let menu_state = state.clone();
    let menu_handles = handles.clone();

    let mut builder = TrayIconBuilder::with_id(APP_TRAY_ID)
        .menu(menu)
        .tooltip(APP_NAME)
        .show_menu_on_left_click(true)
        .icon_as_template(true)
        .on_menu_event(move |app, event| {
            handle_tray_menu_event(app, event, menu_state.clone(), menu_handles.clone());
        });

    if let Some(icon) = load_custom_tray_icon(app).or_else(|| app.default_window_icon().cloned()) {
        builder = builder.icon(icon);
    }

    builder.build(app)
}

fn handle_tray_menu_event(
    app: &AppHandle,
    event: MenuEvent,
    state: Arc<Mutex<BotState>>,
    handles: TrayMenuHandles,
) {
    match event.id().as_ref() {
        APP_TRAY_OPEN_DASHBOARD_ID => {
            let _ = navigate_to_tab(app, "dashboard");
        }
        APP_TRAY_OPEN_SESSIONS_ID => {
            let _ = navigate_to_tab(app, "sessions");
        }
        APP_TRAY_OPEN_SETUP_ID => {
            let _ = navigate_to_tab(app, "setup");
        }
        APP_TRAY_TOGGLE_SERVICE_ID => {
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                let service_running = snapshot_service_status(&state)
                    .await
                    .map(|status| status.running)
                    .unwrap_or(false);

                let result = if service_running {
                    stop_service_internal(&state).await
                } else {
                    start_service_internal(&app, &state).await
                };

                if let Err(error) = result {
                    eprintln!("[menubar] tray service toggle failed: {}", error);
                }

                let tray = app.tray_by_id(APP_TRAY_ID);
                if let Err(error) =
                    update_menubar_state(&app, &state, &handles, tray.as_ref()).await
                {
                    eprintln!(
                        "[menubar] tray state refresh after action failed: {}",
                        error
                    );
                }
            });
        }
        APP_TRAY_QUIT_ID => {
            let exit_state = app.state::<AppExitState>();
            exit_state.mark_exiting();
            app.exit(0);
        }
        _ => {}
    }
}

fn start_menubar_refresh_loop(
    app: AppHandle,
    state: Arc<Mutex<BotState>>,
    handles: TrayMenuHandles,
    tray: TrayIcon<Wry>,
) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(REFRESH_INTERVAL_SECONDS));
        loop {
            ticker.tick().await;
            if let Err(error) = update_menubar_state(&app, &state, &handles, Some(&tray)).await {
                eprintln!("[menubar] tray state refresh failed: {}", error);
            }

            if app.tray_by_id(APP_TRAY_ID).is_none() {
                break;
            }
        }
    });
}

async fn update_menubar_state(
    app: &AppHandle,
    state: &Arc<Mutex<BotState>>,
    handles: &TrayMenuHandles,
    tray: Option<&TrayIcon<Wry>>,
) -> Result<(), String> {
    let service = ensure_service_running_if_needed(app, state).await?;
    let dashboard = compute_dashboard_state(state).await.ok();
    let tray_status = compute_tray_status(
        service.running,
        dashboard
            .as_ref()
            .map(|state| &state.overall)
            .unwrap_or(&SystemHealth::Unknown),
    );

    handles
        .status_item
        .set_text(format!("{}{}", STATUS_PREFIX, tray_status.label()))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .workspace_item
        .set_text(workspace_menu_label(
            dashboard
                .as_ref()
                .and_then(|state| state.recent_activity.as_ref())
                .and_then(|activity| activity.active_workspace_name.as_deref()),
        ))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .session_item
        .set_text(session_menu_label(
            dashboard
                .as_ref()
                .and_then(|state| state.recent_activity.as_ref())
                .and_then(|activity| activity.active_session_id.as_deref()),
        ))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .toggle_service_item
        .set_text(service_toggle_label(service.running))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .toggle_service_item
        .set_enabled(true)
        .map_err(|e: tauri::Error| e.to_string())?;

    if let Some(tray) = tray {
        tray.set_tooltip(Some(build_tray_tooltip(tray_status, dashboard.as_ref())))
            .map_err(|e: tauri::Error| e.to_string())?;
    }

    Ok(())
}

fn build_tray_tooltip(status: TrayStatus, dashboard: Option<&DashboardState>) -> String {
    let mut lines = vec![APP_NAME.to_string(), format!("Status: {}", status.label())];

    if let Some(workspace_name) = dashboard
        .and_then(|state| state.recent_activity.as_ref())
        .and_then(|activity| activity.active_workspace_name.as_deref())
    {
        lines.push(format!("Workspace: {}", workspace_name));
    }

    if let Some(session_id) = dashboard
        .and_then(|state| state.recent_activity.as_ref())
        .and_then(|activity| activity.active_session_id.as_deref())
    {
        lines.push(format!("Active Session: {}", session_id));
    }

    lines.join("\n")
}

fn show_main_window(app: &AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| "Cannot find main window".to_string())?;

    window.unminimize().map_err(|e| e.to_string())?;
    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;

    Ok(())
}

fn navigate_to_tab(app: &AppHandle, tab: &str) -> Result<(), String> {
    show_main_window(app)?;
    app.emit(APP_NAVIGATE_TAB_EVENT, tab.to_string())
        .map_err(|e| e.to_string())
}

fn compute_tray_status(service_running: bool, overall: &SystemHealth) -> TrayStatus {
    if !service_running {
        return TrayStatus::Stopped;
    }

    match overall {
        SystemHealth::Healthy => TrayStatus::Running,
        SystemHealth::Stopped => TrayStatus::Stopped,
        SystemHealth::Degraded | SystemHealth::Misconfigured | SystemHealth::Unknown => {
            TrayStatus::Degraded
        }
    }
}

fn workspace_menu_label(workspace_name: Option<&str>) -> String {
    format!(
        "{}{}",
        WORKSPACE_PREFIX,
        workspace_name.unwrap_or("No workspace")
    )
}

fn session_menu_label(session_id: Option<&str>) -> String {
    format!(
        "{}{}",
        SESSION_PREFIX,
        session_id.unwrap_or("No active session")
    )
}

fn service_toggle_label(service_running: bool) -> &'static str {
    if service_running {
        "Stop Service"
    } else {
        "Start Service"
    }
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use crate::commands::dashboard::SystemHealth;

    use super::{
        compute_tray_status, resolve_custom_tray_icon_paths, service_toggle_label,
        session_menu_label, workspace_menu_label, TrayStatus,
    };

    #[test]
    fn stopped_status_wins_when_service_is_not_running() {
        assert_eq!(
            compute_tray_status(false, &SystemHealth::Healthy),
            TrayStatus::Stopped
        );
        assert_eq!(
            compute_tray_status(false, &SystemHealth::Misconfigured),
            TrayStatus::Stopped
        );
    }

    #[test]
    fn degraded_status_is_used_for_running_but_unhealthy_systems() {
        assert_eq!(
            compute_tray_status(true, &SystemHealth::Degraded),
            TrayStatus::Degraded
        );
        assert_eq!(
            compute_tray_status(true, &SystemHealth::Misconfigured),
            TrayStatus::Degraded
        );
    }

    #[test]
    fn running_status_is_used_for_healthy_running_service() {
        assert_eq!(
            compute_tray_status(true, &SystemHealth::Healthy),
            TrayStatus::Running
        );
    }

    #[test]
    fn service_toggle_label_reflects_current_runtime_state() {
        assert_eq!(service_toggle_label(false), "Start Service");
        assert_eq!(service_toggle_label(true), "Stop Service");
    }

    #[test]
    fn workspace_menu_label_uses_placeholder_when_workspace_is_missing() {
        assert_eq!(workspace_menu_label(None), "Workspace: No workspace");
        assert_eq!(
            workspace_menu_label(Some("onlineWorker")),
            "Workspace: onlineWorker"
        );
    }

    #[test]
    fn session_menu_label_uses_placeholder_when_session_is_missing() {
        assert_eq!(
            session_menu_label(None),
            "Active Session: No active session"
        );
        assert_eq!(
            session_menu_label(Some("session-123")),
            "Active Session: session-123"
        );
    }

    #[test]
    fn custom_tray_icon_paths_prioritize_the_retina_asset() {
        let resolved = resolve_custom_tray_icon_paths(Path::new("/tmp/onlineworker-app"));
        assert_eq!(
            resolved,
            [
                Path::new("/tmp/onlineworker-app/icons/tray-template@2x.png").to_path_buf(),
                Path::new("/tmp/onlineworker-app/icons/tray-template.png").to_path_buf(),
            ]
        );
    }
}
