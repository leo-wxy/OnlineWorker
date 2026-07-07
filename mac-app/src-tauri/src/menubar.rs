use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::image::Image;
use tauri::menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::utils::config::Color;
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, Rect, WebviewUrl, WebviewWindowBuilder, Wry,
};
use tokio::sync::Mutex;

use crate::commands::config::{app_name, ensure_data_dir, read_provider_metadata_from_disk};
use crate::commands::dashboard::{compute_dashboard_state, DashboardState, SystemHealth};
use crate::commands::provider_sessions::load_provider_sessions_with_overlays;
use crate::commands::provider_usage::get_provider_usage_summary;
use crate::commands::service::{
    ensure_service_running_if_needed, snapshot_service_status, start_service_internal,
    stop_service_internal, BotState,
};
use crate::commands::task_board_state::{
    get_task_board_session_activities, TaskBoardSessionActivity,
};
use crate::{cleanup_managed_processes_for_exit_once, AppExitState};

const APP_TRAY_ID: &str = "main-tray";
const MAIN_WINDOW_LABEL: &str = "main";
const MENUBAR_POPOVER_WINDOW_LABEL: &str = "menubar-popover";
const APP_TRAY_TITLE_ID: &str = "tray_app_title";
const APP_TRAY_STATUS_ID: &str = "tray_status";
const APP_TRAY_WORKSPACE_ID: &str = "tray_workspace";
const APP_TRAY_SESSION_ID: &str = "tray_session";
const APP_TRAY_THREADS_ID: &str = "tray_threads";
const APP_TRAY_ATTENTION_ID: &str = "tray_attention";
const APP_TRAY_USAGE_ID: &str = "tray_usage";
const APP_TRAY_OPEN_DASHBOARD_ID: &str = "tray_open_dashboard";
const APP_TRAY_OPEN_TASKS_ID: &str = "tray_open_tasks";
const APP_TRAY_OPEN_SESSIONS_ID: &str = "tray_open_sessions";
const APP_TRAY_OPEN_USAGE_ID: &str = "tray_open_usage";
const APP_TRAY_OPEN_SETUP_ID: &str = "tray_open_setup";
const APP_TRAY_TOGGLE_SERVICE_ID: &str = "tray_toggle_service";
const APP_TRAY_QUIT_ID: &str = "tray_quit";
const APP_NAVIGATE_TAB_EVENT: &str = "app:navigate-tab";
const APP_OPEN_SESSION_EVENT: &str = "app:open-session";
const STATUS_PREFIX: &str = "Status: ";
const WORKSPACE_PREFIX: &str = "Workspace: ";
const SESSION_PREFIX: &str = "Active Session: ";
const THREADS_PREFIX: &str = "Active Threads: ";
const ATTENTION_PREFIX: &str = "Needs Attention: ";
const USAGE_PREFIX: &str = "Usage Today: ";
const REFRESH_INTERVAL_SECONDS: u64 = 4;
const USAGE_REFRESH_INTERVAL_SECONDS: u64 = 300;
const MENUBAR_POPOVER_WIDTH: f64 = 420.0;
const MENUBAR_POPOVER_HEIGHT: f64 = 410.0;
const MENUBAR_POPOVER_MARGIN: i32 = 8;
const MENUBAR_POPOVER_VERTICAL_OFFSET: i32 = 6;
const CUSTOM_TRAY_ICON_RELATIVE_PATH: &str = "icons/tray-template.png";
const CUSTOM_TRAY_ICON_2X_RELATIVE_PATH: &str = "icons/tray-template@2x.png";

#[derive(Clone)]
struct TrayMenuHandles {
    status_item: MenuItem<Wry>,
    workspace_item: MenuItem<Wry>,
    session_item: MenuItem<Wry>,
    threads_item: MenuItem<Wry>,
    attention_item: MenuItem<Wry>,
    usage_item: MenuItem<Wry>,
    toggle_service_item: MenuItem<Wry>,
}

#[derive(Debug)]
struct TrayRuntimeState {
    last_usage_refresh: Option<Instant>,
    usage_label: String,
}

impl Default for TrayRuntimeState {
    fn default() -> Self {
        Self {
            last_usage_refresh: None,
            usage_label: usage_menu_label(TrayUsageValue::Loading),
        }
    }
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TrayUsageValue {
    Loading,
    NoData,
    TotalTokens(u64),
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverSnapshot {
    pub generated_at_epoch: u64,
    pub usage: MenubarPopoverUsage,
    pub latest_sessions: Vec<MenubarPopoverSessionLane>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverUsage {
    pub total_tokens_today: Option<u64>,
    pub needs_attention_count: usize,
    pub active_session_count: usize,
    pub providers: Vec<MenubarPopoverUsageProvider>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverUsageProvider {
    pub provider_id: String,
    pub label: String,
    pub tokens_today: Option<u64>,
    pub input_tokens: Option<u64>,
    pub output_tokens: Option<u64>,
    pub cache_creation_tokens: Option<u64>,
    pub cache_read_tokens: Option<u64>,
    pub total_cost_usd: Option<f64>,
    pub estimated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverSessionLane {
    pub provider_id: String,
    pub label: String,
    pub session_id: Option<String>,
    pub workspace: Option<String>,
    pub workspace_name: Option<String>,
    pub title: Option<String>,
    pub latest_preview: Option<String>,
    pub status: Option<String>,
    pub updated_at_epoch: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverOpenSessionTarget {
    pub provider_id: String,
    pub session_id: String,
    pub workspace: Option<String>,
}

#[derive(Debug, Clone, PartialEq)]
struct MenubarPopoverSessionCandidate {
    provider_id: String,
    session_id: String,
    workspace: Option<String>,
    title: Option<String>,
    latest_preview: Option<String>,
    status: Option<String>,
    updated_at_epoch: Option<u64>,
    sort_rank: u64,
}

#[derive(Debug, Clone, Copy, Default, PartialEq)]
struct MenubarPopoverUsageBreakdown {
    total_tokens: Option<u64>,
    input_tokens: Option<u64>,
    output_tokens: Option<u64>,
    cache_creation_tokens: Option<u64>,
    cache_read_tokens: Option<u64>,
    total_cost_usd: Option<f64>,
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

fn ensure_popover_window(app: &AppHandle) -> Result<(), String> {
    if app
        .get_webview_window(MENUBAR_POPOVER_WINDOW_LABEL)
        .is_some()
    {
        return Ok(());
    }

    WebviewWindowBuilder::new(
        app,
        MENUBAR_POPOVER_WINDOW_LABEL,
        WebviewUrl::App("index.html".into()),
    )
    .title(app_name())
    .position(0.0, 0.0)
    .inner_size(MENUBAR_POPOVER_WIDTH, MENUBAR_POPOVER_HEIGHT)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .focused(false)
    .visible(false)
    .decorations(false)
    .transparent(true)
    .background_color(Color(0, 0, 0, 0))
    .always_on_top(true)
    .skip_taskbar(true)
    .shadow(false)
    .build()
    .map(|_| ())
    .map_err(|error| format!("create menubar popover window failed: {error}"))
}

pub(crate) fn setup_menubar(app: &AppHandle, state: Arc<Mutex<BotState>>) -> tauri::Result<()> {
    let app_title = app_name();
    let app_title_item = MenuItem::with_id(app, APP_TRAY_TITLE_ID, app_title, false, None::<&str>)?;
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
    let threads_item = MenuItem::with_id(
        app,
        APP_TRAY_THREADS_ID,
        threads_menu_label(0),
        false,
        None::<&str>,
    )?;
    let attention_item = MenuItem::with_id(
        app,
        APP_TRAY_ATTENTION_ID,
        attention_menu_label(None),
        false,
        None::<&str>,
    )?;
    let usage_item = MenuItem::with_id(
        app,
        APP_TRAY_USAGE_ID,
        usage_menu_label(TrayUsageValue::Loading),
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
    let open_tasks_item = MenuItem::with_id(
        app,
        APP_TRAY_OPEN_TASKS_ID,
        "Open Task Board",
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
    let open_usage_item = MenuItem::with_id(
        app,
        APP_TRAY_OPEN_USAGE_ID,
        "Open Usage",
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
            &threads_item,
            &attention_item,
            &usage_item,
            &top_separator,
            &open_dashboard_item,
            &open_tasks_item,
            &open_sessions_item,
            &open_usage_item,
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
        threads_item: threads_item.clone(),
        attention_item: attention_item.clone(),
        usage_item: usage_item.clone(),
        toggle_service_item: toggle_service_item.clone(),
    };
    let runtime_state = Arc::new(Mutex::new(TrayRuntimeState::default()));

    let tray = build_tray(
        app,
        &menu,
        state.clone(),
        handles.clone(),
        runtime_state.clone(),
    )?;
    start_menubar_refresh_loop(app.clone(), state, handles, tray, runtime_state);

    Ok(())
}

fn build_tray(
    app: &AppHandle,
    menu: &Menu<Wry>,
    state: Arc<Mutex<BotState>>,
    handles: TrayMenuHandles,
    runtime_state: Arc<Mutex<TrayRuntimeState>>,
) -> tauri::Result<TrayIcon<Wry>> {
    let menu_state = state.clone();
    let menu_handles = handles.clone();
    let menu_runtime_state = runtime_state.clone();

    let mut builder = TrayIconBuilder::with_id(APP_TRAY_ID)
        .menu(menu)
        .tooltip(app_name())
        .show_menu_on_left_click(false)
        .icon_as_template(true)
        .on_menu_event(move |app, event| {
            handle_tray_menu_event(
                app,
                event,
                menu_state.clone(),
                menu_handles.clone(),
                menu_runtime_state.clone(),
            );
        })
        .on_tray_icon_event(move |tray, event| {
            handle_tray_icon_event(tray, event);
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
    runtime_state: Arc<Mutex<TrayRuntimeState>>,
) {
    match event.id().as_ref() {
        APP_TRAY_OPEN_DASHBOARD_ID => {
            let _ = navigate_to_tab(app, "dashboard");
        }
        APP_TRAY_OPEN_TASKS_ID => {
            let _ = navigate_to_tab(app, "tasks");
        }
        APP_TRAY_OPEN_SESSIONS_ID => {
            let _ = navigate_to_tab(app, "sessions");
        }
        APP_TRAY_OPEN_USAGE_ID => {
            let _ = navigate_to_tab(app, "usage");
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
                    update_menubar_state(&app, &state, &handles, tray.as_ref(), &runtime_state)
                        .await
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
            cleanup_managed_processes_for_exit_once(app);
            app.exit(0);
        }
        _ => {}
    }
}

fn handle_tray_icon_event(tray: &TrayIcon<Wry>, event: TrayIconEvent) {
    if let TrayIconEvent::Click {
        button: MouseButton::Left,
        button_state: MouseButtonState::Up,
        position,
        ..
    } = event
    {
        let icon_rect = tray.rect().ok().flatten();
        if let Err(error) = toggle_menubar_popover(tray.app_handle(), icon_rect, Some(position)) {
            eprintln!("[menubar] tray click popover toggle failed: {}", error);
        }
    }
}

fn toggle_menubar_popover(
    app: &AppHandle,
    icon_rect: Option<Rect>,
    click_position: Option<PhysicalPosition<f64>>,
) -> Result<(), String> {
    ensure_popover_window(app)?;
    let window = app
        .get_webview_window(MENUBAR_POPOVER_WINDOW_LABEL)
        .ok_or_else(|| "Cannot find menubar popover window".to_string())?;

    if window.is_visible().map_err(|error| error.to_string())? {
        window.hide().map_err(|error| error.to_string())?;
        return Ok(());
    }

    position_menubar_popover(&window, app, icon_rect, click_position)?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    Ok(())
}

fn hide_menubar_popover(app: &AppHandle) -> Result<(), String> {
    let Some(window) = app.get_webview_window(MENUBAR_POPOVER_WINDOW_LABEL) else {
        return Ok(());
    };
    if window.is_visible().map_err(|error| error.to_string())? {
        window.hide().map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn position_menubar_popover(
    window: &tauri::WebviewWindow,
    app: &AppHandle,
    icon_rect: Option<Rect>,
    click_position: Option<PhysicalPosition<f64>>,
) -> Result<(), String> {
    let width = window
        .outer_size()
        .map(|size| size.width as i32)
        .unwrap_or(MENUBAR_POPOVER_WIDTH as i32);
    let height = window
        .outer_size()
        .map(|size| size.height as i32)
        .unwrap_or(MENUBAR_POPOVER_HEIGHT as i32);

    let monitors = app
        .available_monitors()
        .map_err(|error| error.to_string())?;
    let primary_monitor = app.primary_monitor().map_err(|error| error.to_string())?;
    let target_monitor = click_position
        .and_then(|position| monitor_containing_point(&monitors, position))
        .or_else(|| icon_rect.and_then(|rect| monitor_for_rect_anchor(&monitors, rect)))
        .or(primary_monitor.as_ref());
    let fallback = fallback_popover_position(target_monitor, width, height);
    let next_position = icon_rect
        .map(|rect| anchored_popover_position_from_rect(rect, target_monitor, width, height))
        .or_else(|| {
            click_position
                .map(|position| anchored_popover_position(position, target_monitor, width, height))
        })
        .unwrap_or(fallback);

    window
        .set_position(next_position)
        .map_err(|error| error.to_string())
}

fn anchored_popover_position_from_rect(
    rect: Rect,
    monitor: Option<&tauri::Monitor>,
    width: i32,
    height: i32,
) -> PhysicalPosition<i32> {
    let anchor = popover_anchor_from_rect(rect, monitor);
    anchored_popover_position(anchor, monitor, width, height)
}

fn popover_anchor_from_rect(rect: Rect, monitor: Option<&tauri::Monitor>) -> PhysicalPosition<f64> {
    let scale_factor = monitor.map(|value| value.scale_factor()).unwrap_or(1.0);
    let rect_position = rect.position.to_physical::<i32>(scale_factor);
    let rect_size = rect.size.to_physical::<u32>(scale_factor);
    let anchor_x = rect_position.x + (rect_size.width as i32 / 2);
    let anchor_y = rect_position.y + rect_size.height as i32;
    PhysicalPosition::new(anchor_x as f64, anchor_y as f64)
}

fn monitor_for_rect_anchor(monitors: &[tauri::Monitor], rect: Rect) -> Option<&tauri::Monitor> {
    monitors.iter().find(|monitor| {
        let anchor = popover_anchor_from_rect(rect, Some(monitor));
        monitor_contains_point(monitor, anchor)
    })
}

fn monitor_containing_point(
    monitors: &[tauri::Monitor],
    point: PhysicalPosition<f64>,
) -> Option<&tauri::Monitor> {
    monitors
        .iter()
        .find(|monitor| monitor_contains_point(monitor, point))
}

fn monitor_contains_point(monitor: &tauri::Monitor, point: PhysicalPosition<f64>) -> bool {
    let work_area = monitor.work_area();
    let x = point.x.round() as i32;
    let y = point.y.round() as i32;
    let min_x = work_area.position.x;
    let min_y = work_area.position.y;
    let max_x = min_x + work_area.size.width as i32;
    let max_y = min_y + work_area.size.height as i32;

    x >= min_x && x < max_x && y >= min_y && y < max_y
}

fn fallback_popover_position(
    monitor: Option<&tauri::Monitor>,
    width: i32,
    height: i32,
) -> PhysicalPosition<i32> {
    let Some(monitor) = monitor else {
        return PhysicalPosition::new(0, 0);
    };
    let work_area = monitor.work_area();
    let x = clamp_i32(
        work_area.position.x + work_area.size.width as i32 - width - MENUBAR_POPOVER_MARGIN,
        work_area.position.x + MENUBAR_POPOVER_MARGIN,
        work_area.position.x + work_area.size.width as i32 - width - MENUBAR_POPOVER_MARGIN,
    );
    let y = clamp_i32(
        work_area.position.y + MENUBAR_POPOVER_MARGIN,
        work_area.position.y + MENUBAR_POPOVER_MARGIN,
        work_area.position.y + work_area.size.height as i32 - height - MENUBAR_POPOVER_MARGIN,
    );
    PhysicalPosition::new(x, y)
}

fn anchored_popover_position(
    anchor: PhysicalPosition<f64>,
    monitor: Option<&tauri::Monitor>,
    width: i32,
    height: i32,
) -> PhysicalPosition<i32> {
    let Some(monitor) = monitor else {
        return PhysicalPosition::new(
            anchor.x.round() as i32 - width + 24,
            anchor.y.round() as i32 + MENUBAR_POPOVER_VERTICAL_OFFSET,
        );
    };
    let work_area = monitor.work_area();
    let min_x = work_area.position.x + MENUBAR_POPOVER_MARGIN;
    let max_x = work_area.position.x + work_area.size.width as i32 - width - MENUBAR_POPOVER_MARGIN;
    let min_y = work_area.position.y + MENUBAR_POPOVER_MARGIN;
    let max_y =
        work_area.position.y + work_area.size.height as i32 - height - MENUBAR_POPOVER_MARGIN;

    PhysicalPosition::new(
        clamp_i32(anchor.x.round() as i32 - width + 24, min_x, max_x),
        clamp_i32(
            anchor.y.round() as i32 + MENUBAR_POPOVER_VERTICAL_OFFSET,
            min_y,
            max_y,
        ),
    )
}

fn clamp_i32(value: i32, min: i32, max: i32) -> i32 {
    if max < min {
        return min;
    }
    value.clamp(min, max)
}

fn start_menubar_refresh_loop(
    app: AppHandle,
    state: Arc<Mutex<BotState>>,
    handles: TrayMenuHandles,
    tray: TrayIcon<Wry>,
    runtime_state: Arc<Mutex<TrayRuntimeState>>,
) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(REFRESH_INTERVAL_SECONDS));
        loop {
            ticker.tick().await;
            if let Err(error) =
                update_menubar_state(&app, &state, &handles, Some(&tray), &runtime_state).await
            {
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
    runtime_state: &Arc<Mutex<TrayRuntimeState>>,
) -> Result<(), String> {
    let service = ensure_service_running_if_needed(app, state).await?;
    let dashboard = compute_dashboard_state(app, state).await.ok();
    let active_threads = dashboard
        .as_ref()
        .and_then(|state| state.recent_activity.as_ref())
        .map(|activity| activity.active_thread_count)
        .unwrap_or(0);
    let attention_count = load_needs_attention_count().await.ok();
    let usage_label = usage_menu_label_cached(app, runtime_state).await;
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
        .threads_item
        .set_text(threads_menu_label(active_threads))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .attention_item
        .set_text(attention_menu_label(attention_count))
        .map_err(|e: tauri::Error| e.to_string())?;
    handles
        .usage_item
        .set_text(usage_label)
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
        tray.set_tooltip(Some(build_tray_tooltip(
            tray_status,
            dashboard.as_ref(),
            attention_count,
            active_threads,
        )))
        .map_err(|e: tauri::Error| e.to_string())?;
    }

    Ok(())
}

async fn load_needs_attention_count() -> Result<usize, String> {
    let activities = get_task_board_session_activities().await?;
    Ok(count_needs_attention(&activities))
}

async fn usage_menu_label_cached(
    app: &AppHandle,
    runtime_state: &Arc<Mutex<TrayRuntimeState>>,
) -> String {
    {
        let state = runtime_state.lock().await;
        if state
            .last_usage_refresh
            .map(|instant| instant.elapsed() < Duration::from_secs(USAGE_REFRESH_INTERVAL_SECONDS))
            .unwrap_or(false)
        {
            return state.usage_label.clone();
        }
    }

    let next_label = match load_usage_menu_label(app).await {
        Ok(label) => label,
        Err(error) => {
            eprintln!("[menubar] tray usage snapshot refresh failed: {}", error);
            let state = runtime_state.lock().await;
            state.usage_label.clone()
        }
    };

    let mut state = runtime_state.lock().await;
    state.last_usage_refresh = Some(Instant::now());
    state.usage_label = next_label.clone();
    next_label
}

async fn load_usage_menu_label(app: &AppHandle) -> Result<String, String> {
    let usage_providers = load_popover_usage_providers(app).await?;
    let total_tokens = usage_providers
        .iter()
        .filter_map(|provider| provider.tokens_today)
        .fold(0_u64, u64::saturating_add);
    let has_usage_data = usage_providers
        .iter()
        .any(|provider| provider.tokens_today.is_some());

    if has_usage_data {
        Ok(usage_menu_label(TrayUsageValue::TotalTokens(total_tokens)))
    } else {
        Ok(usage_menu_label(TrayUsageValue::NoData))
    }
}

fn build_tray_tooltip(
    status: TrayStatus,
    dashboard: Option<&DashboardState>,
    attention_count: Option<usize>,
    active_threads: u32,
) -> String {
    let mut lines = vec![
        app_name().to_string(),
        format!("Status: {}", status.label()),
    ];

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

    lines.push(format!("Active Threads: {}", active_threads));

    if let Some(count) = attention_count {
        lines.push(format!("Needs Attention: {}", count));
    }

    lines.join("\n")
}

pub(crate) fn show_main_window(app: &AppHandle) -> Result<(), String> {
    let window = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "Cannot find main window".to_string())?;

    window.unminimize().map_err(|e| e.to_string())?;
    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;

    Ok(())
}

fn navigate_to_tab(app: &AppHandle, tab: &str) -> Result<(), String> {
    show_main_window(app)?;
    app.emit_to(MAIN_WINDOW_LABEL, APP_NAVIGATE_TAB_EVENT, tab.to_string())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_menubar_popover_snapshot(
    app: AppHandle,
) -> Result<MenubarPopoverSnapshot, String> {
    let usage_providers = load_popover_usage_providers(&app).await?;
    let activities = get_task_board_session_activities()
        .await
        .unwrap_or_default();
    let session_candidates = load_popover_session_candidates(&app, &usage_providers).await;

    Ok(build_popover_snapshot(
        current_epoch_seconds(),
        usage_providers,
        activities,
        session_candidates,
    ))
}

#[tauri::command]
pub async fn open_menubar_popover_session(
    app: AppHandle,
    provider_id: String,
    session_id: String,
    workspace_dir: Option<String>,
) -> Result<(), String> {
    hide_menubar_popover(&app)?;
    show_main_window(&app)?;
    app.emit_to(
        MAIN_WINDOW_LABEL,
        APP_OPEN_SESSION_EVENT,
        MenubarPopoverOpenSessionTarget {
            provider_id,
            session_id,
            workspace: workspace_dir.filter(|value| !value.trim().is_empty()),
        },
    )
    .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn open_menubar_tab(app: AppHandle, tab: String) -> Result<(), String> {
    hide_menubar_popover(&app)?;
    navigate_to_tab(&app, tab.trim())
}

async fn load_popover_usage_providers(
    app: &AppHandle,
) -> Result<Vec<MenubarPopoverUsageProvider>, String> {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let mut providers = Vec::new();

    for (provider_id, label) in popover_provider_specs() {
        let usage = match get_provider_usage_summary(
            app.clone(),
            provider_id.clone(),
            today.clone(),
            today.clone(),
        )
        .await
        {
            Ok(summary) => usage_breakdown_from_usage_summary(&summary, &today),
            Err(error) => {
                eprintln!(
                    "[menubar] popover usage refresh failed for {}: {}",
                    provider_id, error
                );
                MenubarPopoverUsageBreakdown::default()
            }
        };

        providers.push(MenubarPopoverUsageProvider {
            provider_id,
            label,
            tokens_today: usage.total_tokens,
            input_tokens: usage.input_tokens,
            output_tokens: usage.output_tokens,
            cache_creation_tokens: usage.cache_creation_tokens,
            cache_read_tokens: usage.cache_read_tokens,
            total_cost_usd: usage.total_cost_usd,
            estimated: false,
        });
    }

    Ok(providers)
}

async fn load_popover_session_candidates(
    app: &AppHandle,
    providers: &[MenubarPopoverUsageProvider],
) -> Vec<MenubarPopoverSessionCandidate> {
    let mut candidates = Vec::new();

    for provider in providers {
        match load_provider_sessions_with_overlays(app, &provider.provider_id, false).await {
            Ok(sessions) => {
                candidates.extend(parse_provider_session_candidates(
                    &provider.provider_id,
                    &sessions,
                ));
            }
            Err(error) => {
                eprintln!(
                    "[menubar] popover session refresh failed for {}: {}",
                    provider.provider_id, error
                );
            }
        }
    }

    candidates.extend(load_local_state_session_candidates(providers));

    candidates
}

fn load_local_state_session_candidates(
    providers: &[MenubarPopoverUsageProvider],
) -> Vec<MenubarPopoverSessionCandidate> {
    let provider_ids = providers
        .iter()
        .map(|provider| provider.provider_id.as_str())
        .collect::<std::collections::BTreeSet<_>>();
    let Ok(data_dir) = ensure_data_dir() else {
        return Vec::new();
    };
    let Ok(raw) = fs::read_to_string(data_dir.join("onlineworker_state.json")) else {
        return Vec::new();
    };
    let Ok(parsed) = serde_json::from_str::<Value>(&raw) else {
        return Vec::new();
    };
    let Some(workspaces) = parsed.get("workspaces").and_then(Value::as_object) else {
        return Vec::new();
    };

    let mut candidates = Vec::new();
    let mut sequence = 0_u64;
    for workspace in workspaces.values() {
        sequence = sequence.saturating_add(1);
        let Some(provider_id) = workspace.get("tool").and_then(Value::as_str) else {
            continue;
        };
        if !provider_ids.contains(provider_id) {
            continue;
        }
        let workspace_path = value_text(workspace, &["path", "workspace", "workspacePath"]);
        let Some(threads) = workspace.get("threads").and_then(Value::as_object) else {
            continue;
        };
        for (thread_key, thread) in threads {
            sequence = sequence.saturating_add(1);
            if value_bool(thread, &["archived"]).unwrap_or(false) {
                continue;
            }
            let session_id = value_text(thread, &["thread_id", "id", "sessionId", "session_id"])
                .unwrap_or_else(|| thread_key.clone());
            if session_id.trim().is_empty() {
                continue;
            }

            let explicit_epoch = value_epoch(
                thread,
                &[
                    "updatedAt",
                    "updated_at",
                    "updated_at_epoch",
                    "createdAt",
                    "created_at",
                ],
            );
            let active = value_bool(thread, &["is_active", "providerActive"]).unwrap_or(false);
            let tg_message_rank = value_epoch(thread, &["last_tg_user_message_id"]).unwrap_or(0);
            let sort_rank = explicit_epoch
                .unwrap_or(0)
                .saturating_add(if active { 1_000_000_000_000 } else { 0 })
                .saturating_add(tg_message_rank.saturating_mul(10_000))
                .saturating_add(sequence);

            candidates.push(MenubarPopoverSessionCandidate {
                provider_id: provider_id.to_string(),
                session_id,
                workspace: workspace_path.clone(),
                title: value_text(thread, &["title", "preview"])
                    .or_else(|| value_text(workspace, &["name"])),
                latest_preview: value_text(thread, &["preview", "lastMessage", "last_message"]),
                status: if active {
                    Some("Active".to_string())
                } else {
                    value_text(thread, &["status", "state"])
                },
                updated_at_epoch: explicit_epoch.filter(|value| *value >= 1_000_000_000),
                sort_rank,
            });
        }
    }

    candidates
}

fn fallback_popover_provider_specs() -> Vec<(String, String)> {
    vec![
        ("codex".to_string(), "Codex".to_string()),
        ("claude".to_string(), "Claude".to_string()),
    ]
}

fn popover_provider_specs() -> Vec<(String, String)> {
    match read_provider_metadata_from_disk() {
        Ok(metadata) => popover_provider_specs_from_metadata(metadata),
        Err(_) => fallback_popover_provider_specs(),
    }
}

fn popover_provider_specs_from_metadata(
    metadata: Vec<crate::commands::config_provider::ProviderMetadata>,
) -> Vec<(String, String)> {
    let mut rows = metadata
        .into_iter()
        .enumerate()
        .filter_map(|(index, provider)| {
            let provider_id = provider.id.trim();
            if provider_id.is_empty()
                || !provider.visible
                || !(provider.capabilities.sessions || provider.capabilities.usage)
            {
                return None;
            }
            let label = provider.label.trim();
            Some((
                provider_sort_key(provider_id, index),
                provider_id.to_string(),
                if label.is_empty() {
                    provider_id.to_string()
                } else {
                    label.to_string()
                },
            ))
        })
        .collect::<Vec<_>>();

    rows.sort_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)));

    let mut providers = Vec::new();
    for (_, provider_id, label) in rows {
        if providers
            .iter()
            .any(|(existing_id, _): &(String, String)| existing_id == &provider_id)
        {
            continue;
        }
        providers.push((provider_id, label));
    }

    if providers.is_empty() {
        fallback_popover_provider_specs()
    } else {
        providers
    }
}

fn provider_sort_key(provider_id: &str, index: usize) -> (u8, usize) {
    match provider_id {
        "codex" => (0, 0),
        "claude" => (0, 1),
        _ => (1, index),
    }
}

fn usage_breakdown_from_usage_summary(
    summary: &crate::commands::provider_usage::ProviderUsageSummary,
    today: &str,
) -> MenubarPopoverUsageBreakdown {
    if summary.unsupported_reason.is_some() {
        return MenubarPopoverUsageBreakdown::default();
    }

    let Some(day) = summary
        .days
        .iter()
        .find(|day| day.date == today)
        .or_else(|| summary.days.first())
    else {
        return MenubarPopoverUsageBreakdown::default();
    };

    MenubarPopoverUsageBreakdown {
        total_tokens: Some(day.total_tokens),
        input_tokens: Some(day.input_tokens),
        output_tokens: Some(day.output_tokens),
        cache_creation_tokens: Some(day.cache_creation_tokens),
        cache_read_tokens: Some(day.cache_read_tokens),
        total_cost_usd: day.total_cost_usd,
    }
}

fn current_epoch_seconds() -> u64 {
    Local::now().timestamp().max(0) as u64
}

fn build_popover_snapshot(
    generated_at_epoch: u64,
    providers: Vec<MenubarPopoverUsageProvider>,
    activities: Vec<TaskBoardSessionActivity>,
    candidates: Vec<MenubarPopoverSessionCandidate>,
) -> MenubarPopoverSnapshot {
    let providers = providers_with_usage_fallbacks(providers, &candidates);
    let total_tokens_today = providers
        .iter()
        .filter_map(|provider| provider.tokens_today)
        .reduce(u64::saturating_add);

    let latest_sessions = providers
        .iter()
        .map(|provider| build_popover_session_lane(provider, &activities, &candidates))
        .collect::<Vec<_>>();
    let active_session_count = count_snapshot_sessions(&latest_sessions);

    MenubarPopoverSnapshot {
        generated_at_epoch,
        usage: MenubarPopoverUsage {
            total_tokens_today,
            needs_attention_count: count_needs_attention(&activities),
            active_session_count,
            providers,
        },
        latest_sessions,
    }
}

fn providers_with_usage_fallbacks(
    providers: Vec<MenubarPopoverUsageProvider>,
    candidates: &[MenubarPopoverSessionCandidate],
) -> Vec<MenubarPopoverUsageProvider> {
    providers
        .into_iter()
        .map(|mut provider| {
            if provider.tokens_today.is_none() {
                provider.tokens_today = Some(estimate_provider_tokens_today(
                    &provider.provider_id,
                    candidates,
                ));
                provider.input_tokens = None;
                provider.output_tokens = None;
                provider.cache_creation_tokens = None;
                provider.cache_read_tokens = None;
                provider.total_cost_usd = None;
                provider.estimated = true;
            }
            provider
        })
        .collect()
}

fn estimate_provider_tokens_today(
    provider_id: &str,
    candidates: &[MenubarPopoverSessionCandidate],
) -> u64 {
    let mut active_count = 0_u64;
    let mut total_count = 0_u64;
    for candidate in candidates
        .iter()
        .filter(|candidate| candidate.provider_id == provider_id)
    {
        total_count = total_count.saturating_add(1);
        if candidate
            .status
            .as_deref()
            .map(|value| value.eq_ignore_ascii_case("active"))
            .unwrap_or(false)
        {
            active_count = active_count.saturating_add(1);
        }
    }

    active_count
        .max(total_count.min(3))
        .max(1)
        .saturating_mul(12_400)
}

fn build_popover_session_lane(
    provider: &MenubarPopoverUsageProvider,
    activities: &[TaskBoardSessionActivity],
    candidates: &[MenubarPopoverSessionCandidate],
) -> MenubarPopoverSessionLane {
    let latest_activity = activities
        .iter()
        .filter(|activity| activity.provider_id == provider.provider_id)
        .max_by(|left, right| {
            left.updated_at
                .partial_cmp(&right.updated_at)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    let latest_candidate = candidates
        .iter()
        .filter(|candidate| candidate.provider_id == provider.provider_id)
        .max_by_key(|candidate| candidate.sort_rank);

    if let Some(candidate) = latest_candidate {
        let matching_activity = activities.iter().find(|activity| {
            activity.provider_id == candidate.provider_id
                && activity.session_id == candidate.session_id
        });
        return build_candidate_session_lane(provider, candidate, matching_activity);
    }

    if let Some(activity) = latest_activity {
        return build_activity_session_lane(provider, activity, None);
    }

    MenubarPopoverSessionLane {
        provider_id: provider.provider_id.clone(),
        label: provider.label.clone(),
        session_id: None,
        workspace: None,
        workspace_name: None,
        title: None,
        latest_preview: None,
        status: None,
        updated_at_epoch: None,
    }
}

fn build_activity_session_lane(
    provider: &MenubarPopoverUsageProvider,
    activity: &TaskBoardSessionActivity,
    candidate: Option<&MenubarPopoverSessionCandidate>,
) -> MenubarPopoverSessionLane {
    let workspace = non_empty_text(&activity.workspace_path)
        .or_else(|| candidate.and_then(|row| row.workspace.clone()));

    MenubarPopoverSessionLane {
        provider_id: provider.provider_id.clone(),
        label: provider.label.clone(),
        session_id: Some(activity.session_id.clone()),
        workspace: workspace.clone(),
        workspace_name: workspace.as_deref().map(workspace_display_name),
        title: session_lane_title(activity).or_else(|| candidate.and_then(|row| row.title.clone())),
        latest_preview: session_lane_preview(activity)
            .or_else(|| candidate.and_then(|row| row.latest_preview.clone())),
        status: session_lane_status(activity)
            .or_else(|| candidate.and_then(|row| row.status.clone())),
        updated_at_epoch: Some(activity.updated_at.max(0.0) as u64)
            .or_else(|| candidate.and_then(|row| row.updated_at_epoch)),
    }
}

fn build_candidate_session_lane(
    provider: &MenubarPopoverUsageProvider,
    candidate: &MenubarPopoverSessionCandidate,
    activity: Option<&TaskBoardSessionActivity>,
) -> MenubarPopoverSessionLane {
    let workspace = candidate
        .workspace
        .clone()
        .or_else(|| activity.and_then(|row| non_empty_text(&row.workspace_path)));

    MenubarPopoverSessionLane {
        provider_id: provider.provider_id.clone(),
        label: provider.label.clone(),
        session_id: Some(candidate.session_id.clone()),
        workspace: workspace.clone(),
        workspace_name: workspace.as_deref().map(workspace_display_name),
        title: activity
            .and_then(session_lane_title)
            .or_else(|| candidate.title.clone())
            .or_else(|| Some(candidate.session_id.clone())),
        latest_preview: activity
            .and_then(session_lane_preview)
            .or_else(|| candidate.latest_preview.clone()),
        status: activity
            .and_then(session_lane_status)
            .or_else(|| candidate.status.clone()),
        updated_at_epoch: candidate
            .updated_at_epoch
            .or_else(|| activity.map(|row| row.updated_at.max(0.0) as u64)),
    }
}

fn count_snapshot_sessions(lanes: &[MenubarPopoverSessionLane]) -> usize {
    lanes
        .iter()
        .filter(|lane| lane.session_id.is_some())
        .count()
}

fn parse_provider_session_candidates(
    provider_id: &str,
    sessions: &Value,
) -> Vec<MenubarPopoverSessionCandidate> {
    let Some(rows) = sessions.as_array() else {
        return Vec::new();
    };

    rows.iter()
        .filter_map(|row| parse_provider_session_candidate(provider_id, row))
        .collect()
}

fn parse_provider_session_candidate(
    provider_id: &str,
    row: &Value,
) -> Option<MenubarPopoverSessionCandidate> {
    if value_bool(row, &["archived"]).unwrap_or(false) {
        return None;
    }

    let session_id = value_text(row, &["id", "sessionId", "session_id", "thread_id"])?;

    Some(MenubarPopoverSessionCandidate {
        provider_id: provider_id.to_string(),
        session_id,
        workspace: value_text(
            row,
            &[
                "workspace",
                "workspaceDir",
                "workspace_dir",
                "directory",
                "cwd",
            ],
        ),
        title: value_text(row, &["title", "name", "summary"]),
        latest_preview: value_text(
            row,
            &["preview", "lastMessage", "last_message", "lastFinalMessage"],
        ),
        status: value_text(row, &["status", "state"]),
        updated_at_epoch: value_epoch(
            row,
            &[
                "updatedAt",
                "updated_at",
                "lastActivityAt",
                "createdAt",
                "created_at",
            ],
        ),
        sort_rank: value_epoch(
            row,
            &[
                "updatedAt",
                "updated_at",
                "lastActivityAt",
                "createdAt",
                "created_at",
            ],
        )
        .unwrap_or(0),
    })
}

fn session_lane_title(activity: &TaskBoardSessionActivity) -> Option<String> {
    non_empty_text(&activity.title).or_else(|| non_empty_text(&activity.session_id))
}

fn session_lane_preview(activity: &TaskBoardSessionActivity) -> Option<String> {
    normalize_preview_text(&activity.last_final_message)
        .or_else(|| normalize_preview_text(&activity.last_assistant_message))
        .or_else(|| normalize_preview_text(&activity.last_user_message))
        .or_else(|| normalize_preview_text(&activity.attention_reason))
}

fn session_lane_status(activity: &TaskBoardSessionActivity) -> Option<String> {
    let normalized = activity.status.trim().to_lowercase();
    if normalized.is_empty() {
        return None;
    }
    if normalized == "needs_attention" {
        return Some("Needs reply".to_string());
    }
    if normalized == "running" {
        return Some("Running".to_string());
    }

    let mut words = Vec::new();
    for word in normalized.split(['_', '-', ' ']) {
        if word.is_empty() {
            continue;
        }
        let mut chars = word.chars();
        if let Some(first) = chars.next() {
            words.push(format!("{}{}", first.to_ascii_uppercase(), chars.as_str()));
        }
    }
    if words.is_empty() {
        None
    } else {
        Some(words.join(" "))
    }
}

fn normalize_preview_text(value: &str) -> Option<String> {
    let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.is_empty() {
        None
    } else {
        Some(collapsed)
    }
}

fn workspace_display_name(workspace: &str) -> String {
    Path::new(workspace)
        .file_name()
        .and_then(|value| value.to_str())
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(workspace)
        .to_string()
}

fn non_empty_text(value: &str) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}

fn value_text(row: &Value, keys: &[&str]) -> Option<String> {
    keys.iter()
        .filter_map(|key| row.get(*key))
        .find_map(|value| match value {
            Value::String(text) => non_empty_text(text),
            Value::Number(number) => Some(number.to_string()),
            _ => None,
        })
}

fn value_bool(row: &Value, keys: &[&str]) -> Option<bool> {
    keys.iter()
        .filter_map(|key| row.get(*key))
        .find_map(Value::as_bool)
}

fn value_epoch(row: &Value, keys: &[&str]) -> Option<u64> {
    keys.iter()
        .filter_map(|key| row.get(*key))
        .find_map(value_as_epoch_seconds)
}

fn value_as_epoch_seconds(value: &Value) -> Option<u64> {
    let raw = match value {
        Value::Number(number) => number
            .as_u64()
            .or_else(|| number.as_i64().and_then(|value| u64::try_from(value).ok()))
            .or_else(|| number.as_f64().map(|value| value.max(0.0) as u64)),
        Value::String(text) => {
            let text = text.trim();
            text.parse::<u64>().ok().or_else(|| {
                chrono::DateTime::parse_from_rfc3339(text)
                    .ok()
                    .map(|value| value.timestamp().max(0) as u64)
            })
        }
        _ => None,
    }?;

    if raw > 1_000_000_000_000 {
        Some(raw / 1000)
    } else {
        Some(raw)
    }
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

fn threads_menu_label(active_threads: u32) -> String {
    format!("{}{}", THREADS_PREFIX, active_threads)
}

fn attention_menu_label(attention_count: Option<usize>) -> String {
    match attention_count {
        Some(count) => format!("{}{}", ATTENTION_PREFIX, count),
        None => format!("{}--", ATTENTION_PREFIX),
    }
}

fn usage_menu_label(value: TrayUsageValue) -> String {
    match value {
        TrayUsageValue::Loading => format!("{}...", USAGE_PREFIX),
        TrayUsageValue::NoData => format!("{}--", USAGE_PREFIX),
        TrayUsageValue::TotalTokens(total_tokens) => {
            format!("{}{}", USAGE_PREFIX, format_token_count(total_tokens))
        }
    }
}

fn format_token_count(total_tokens: u64) -> String {
    if total_tokens >= 1_000_000 {
        format!("{:.1}M tok", total_tokens as f64 / 1_000_000.0)
    } else if total_tokens >= 1_000 {
        format!("{:.1}k tok", total_tokens as f64 / 1_000.0)
    } else {
        format!("{} tok", total_tokens)
    }
}

fn count_needs_attention(activities: &[TaskBoardSessionActivity]) -> usize {
    activities
        .iter()
        .filter(|activity| {
            activity
                .status
                .trim()
                .eq_ignore_ascii_case("needs_attention")
        })
        .count()
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
    use crate::commands::provider_usage::{ProviderUsageDay, ProviderUsageSummary};
    use crate::commands::task_board_state::TaskBoardSessionActivity;

    use super::{
        anchored_popover_position, attention_menu_label, build_popover_snapshot,
        compute_tray_status, count_needs_attention, format_token_count,
        popover_provider_specs_from_metadata, resolve_custom_tray_icon_paths, service_toggle_label,
        session_menu_label, threads_menu_label, usage_breakdown_from_usage_summary,
        usage_menu_label, workspace_menu_label, MenubarPopoverOpenSessionTarget,
        MenubarPopoverSessionCandidate, MenubarPopoverUsageProvider, TrayStatus, TrayUsageValue,
    };

    fn usage_provider(
        provider_id: &str,
        label: &str,
        tokens_today: Option<u64>,
    ) -> MenubarPopoverUsageProvider {
        MenubarPopoverUsageProvider {
            provider_id: provider_id.into(),
            label: label.into(),
            tokens_today,
            input_tokens: None,
            output_tokens: None,
            cache_creation_tokens: None,
            cache_read_tokens: None,
            total_cost_usd: None,
            estimated: false,
        }
    }

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
    fn threads_menu_label_reflects_current_activity_count() {
        assert_eq!(threads_menu_label(0), "Active Threads: 0");
        assert_eq!(threads_menu_label(3), "Active Threads: 3");
    }

    #[test]
    fn attention_menu_label_uses_placeholder_until_snapshot_is_available() {
        assert_eq!(attention_menu_label(None), "Needs Attention: --");
        assert_eq!(attention_menu_label(Some(2)), "Needs Attention: 2");
    }

    #[test]
    fn usage_menu_label_formats_loading_no_data_and_real_totals() {
        assert_eq!(
            usage_menu_label(TrayUsageValue::Loading),
            "Usage Today: ..."
        );
        assert_eq!(usage_menu_label(TrayUsageValue::NoData), "Usage Today: --");
        assert_eq!(
            usage_menu_label(TrayUsageValue::TotalTokens(12_300)),
            "Usage Today: 12.3k tok"
        );
    }

    #[test]
    fn token_count_format_uses_compact_suffixes() {
        assert_eq!(format_token_count(999), "999 tok");
        assert_eq!(format_token_count(1_200), "1.2k tok");
        assert_eq!(format_token_count(2_500_000), "2.5M tok");
    }

    #[test]
    fn usage_breakdown_keeps_input_output_and_cache_tokens() {
        let summary = ProviderUsageSummary {
            provider_id: "claude".into(),
            days: vec![ProviderUsageDay {
                date: "2026-07-07".into(),
                input_tokens: 1_200,
                output_tokens: 340,
                cache_creation_tokens: 560,
                cache_read_tokens: 7_800,
                total_tokens: 9_900,
                total_cost_usd: Some(0.42),
            }],
            updated_at_epoch: 1_720_000_000,
            unsupported_reason: None,
        };

        let breakdown = usage_breakdown_from_usage_summary(&summary, "2026-07-07");

        assert_eq!(breakdown.total_tokens, Some(9_900));
        assert_eq!(breakdown.input_tokens, Some(1_200));
        assert_eq!(breakdown.output_tokens, Some(340));
        assert_eq!(breakdown.cache_creation_tokens, Some(560));
        assert_eq!(breakdown.cache_read_tokens, Some(7_800));
        assert_eq!(breakdown.total_cost_usd, Some(0.42));
    }

    #[test]
    fn popover_provider_specs_include_visible_metadata_with_sessions_or_usage() {
        let mut codex = crate::commands::config_provider::provider_default_metadata("codex");
        codex.label = "Codex".into();
        codex.capabilities.sessions = true;
        codex.capabilities.usage = true;

        let mut local = crate::commands::config_provider::provider_default_metadata("localai");
        local.id = "localai".into();
        local.runtime_id = "localai".into();
        local.label = "Local AI".into();
        local.visible = true;
        local.capabilities.sessions = true;

        let mut hidden = crate::commands::config_provider::provider_default_metadata("hidden");
        hidden.id = "hidden".into();
        hidden.label = "Hidden".into();
        hidden.visible = false;
        hidden.capabilities.sessions = true;
        hidden.capabilities.usage = true;

        let specs = popover_provider_specs_from_metadata(vec![local, hidden, codex]);

        assert_eq!(
            specs,
            vec![
                ("codex".to_string(), "Codex".to_string()),
                ("localai".to_string(), "Local AI".to_string()),
            ]
        );
    }

    #[test]
    fn needs_attention_count_only_includes_matching_status_rows() {
        let activities = vec![
            TaskBoardSessionActivity {
                provider_id: "codex".into(),
                workspace_id: "workspace-1".into(),
                workspace_path: "/tmp/workspace-1".into(),
                session_id: "session-1".into(),
                title: "Need approval".into(),
                status: "needs_attention".into(),
                attention_reason: String::new(),
                attention_kind: String::new(),
                request_id: String::new(),
                approval_source: String::new(),
                mirrored_only: false,
                last_user_message: String::new(),
                last_assistant_message: String::new(),
                last_final_message: String::new(),
                last_event_kind: String::new(),
                updated_at: 0.0,
            },
            TaskBoardSessionActivity {
                provider_id: "claude".into(),
                workspace_id: "workspace-2".into(),
                workspace_path: "/tmp/workspace-2".into(),
                session_id: "session-2".into(),
                title: "Running".into(),
                status: "running".into(),
                attention_reason: String::new(),
                attention_kind: String::new(),
                request_id: String::new(),
                approval_source: String::new(),
                mirrored_only: false,
                last_user_message: String::new(),
                last_assistant_message: String::new(),
                last_final_message: String::new(),
                last_event_kind: String::new(),
                updated_at: 0.0,
            },
        ];

        assert_eq!(count_needs_attention(&activities), 1);
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

    #[test]
    fn popover_snapshot_keeps_provider_lanes_and_sums_usage() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-combined".into(),
            workspace_path: "/tmp/onlineworker-combined".into(),
            session_id: "session-1".into(),
            title: "menubar polish".into(),
            status: "needs_attention".into(),
            attention_reason: "reply required".into(),
            attention_kind: String::new(),
            request_id: String::new(),
            approval_source: String::new(),
            mirrored_only: false,
            last_user_message: "codex claude 分开展示吧".into(),
            last_assistant_message: String::new(),
            last_final_message: String::new(),
            last_event_kind: "message.user.accepted".into(),
            updated_at: 50.0,
        }];

        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![
                usage_provider("codex", "Codex", Some(92_100)),
                usage_provider("claude", "Claude", Some(36_300)),
            ],
            activities,
            Vec::new(),
        );

        assert_eq!(snapshot.usage.total_tokens_today, Some(128_400));
        assert_eq!(snapshot.usage.active_session_count, 1);
        assert_eq!(snapshot.usage.needs_attention_count, 1);
        assert_eq!(snapshot.latest_sessions.len(), 2);
        assert_eq!(snapshot.latest_sessions[0].provider_id, "codex");
        assert_eq!(snapshot.latest_sessions[1].provider_id, "claude");
        assert_eq!(snapshot.latest_sessions[1].session_id, None);
    }

    #[test]
    fn popover_snapshot_uses_provider_sessions_when_task_board_is_empty() {
        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![
                usage_provider("codex", "Codex", None),
                usage_provider("claude", "Claude", None),
            ],
            Vec::new(),
            vec![
                MenubarPopoverSessionCandidate {
                    provider_id: "codex".into(),
                    session_id: "codex-latest".into(),
                    workspace: Some("/tmp/onlineworker-combined".into()),
                    title: Some("Menubar popover".into()),
                    latest_preview: Some("实现 provider session fallback".into()),
                    status: None,
                    updated_at_epoch: Some(200),
                    sort_rank: 200,
                },
                MenubarPopoverSessionCandidate {
                    provider_id: "codex".into(),
                    session_id: "codex-older".into(),
                    workspace: Some("/tmp/older".into()),
                    title: Some("Older".into()),
                    latest_preview: None,
                    status: None,
                    updated_at_epoch: Some(100),
                    sort_rank: 100,
                },
            ],
        );

        assert_eq!(snapshot.usage.active_session_count, 1);
        assert_eq!(snapshot.usage.total_tokens_today, Some(37_200));
        assert_eq!(snapshot.usage.providers[0].tokens_today, Some(24_800));
        assert!(snapshot.usage.providers[0].estimated);
        assert_eq!(snapshot.usage.providers[1].tokens_today, Some(12_400));
        assert!(snapshot.usage.providers[1].estimated);
        assert_eq!(
            snapshot.latest_sessions[0].session_id.as_deref(),
            Some("codex-latest")
        );
        assert_eq!(
            snapshot.latest_sessions[0].workspace_name.as_deref(),
            Some("onlineworker-combined")
        );
        assert_eq!(
            snapshot.latest_sessions[0].latest_preview.as_deref(),
            Some("实现 provider session fallback")
        );
        assert_eq!(snapshot.latest_sessions[1].session_id, None);
    }

    #[test]
    fn popover_snapshot_overlays_task_board_status_for_matching_session() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-combined".into(),
            workspace_path: "/tmp/onlineworker-combined".into(),
            session_id: "codex-latest".into(),
            title: String::new(),
            status: "needs_attention".into(),
            attention_reason: "等待授权".into(),
            attention_kind: "approval".into(),
            request_id: "req-1".into(),
            approval_source: "command".into(),
            mirrored_only: false,
            last_user_message: String::new(),
            last_assistant_message: String::new(),
            last_final_message: String::new(),
            last_event_kind: "approval.requested".into(),
            updated_at: 150.0,
        }];

        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![usage_provider("codex", "Codex", None)],
            activities,
            vec![MenubarPopoverSessionCandidate {
                provider_id: "codex".into(),
                session_id: "codex-latest".into(),
                workspace: Some("/tmp/onlineworker-combined".into()),
                title: Some("Provider title".into()),
                latest_preview: Some("Provider preview".into()),
                status: None,
                updated_at_epoch: Some(200),
                sort_rank: 200,
            }],
        );

        assert_eq!(snapshot.usage.needs_attention_count, 1);
        assert_eq!(
            snapshot.latest_sessions[0].session_id.as_deref(),
            Some("codex-latest")
        );
        assert_eq!(
            snapshot.latest_sessions[0].status.as_deref(),
            Some("Needs reply")
        );
        assert_eq!(
            snapshot.latest_sessions[0].latest_preview.as_deref(),
            Some("等待授权")
        );
    }

    #[test]
    fn popover_position_anchors_below_click_and_stays_on_screen() {
        let position =
            anchored_popover_position(tauri::PhysicalPosition::new(500.0, 24.0), None, 392, 500);

        assert_eq!(position.x, 132);
        assert_eq!(position.y, 30);
    }

    #[test]
    fn open_session_event_payload_keeps_workspace() {
        let payload = MenubarPopoverOpenSessionTarget {
            provider_id: "claude".into(),
            session_id: "session-9".into(),
            workspace: Some("/tmp/OnlineWorker".into()),
        };

        assert_eq!(payload.provider_id, "claude");
        assert_eq!(payload.session_id, "session-9");
        assert_eq!(payload.workspace.as_deref(), Some("/tmp/OnlineWorker"));
    }
}
