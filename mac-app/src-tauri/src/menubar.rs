use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, RwLock,
};
use std::time::Duration;

use chrono::Local;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::image::Image;
use tauri::tray::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
use tauri::utils::config::Color;
use tauri::webview::PageLoadEvent;
use tauri::{
    AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, Rect, Size, WebviewUrl,
    WebviewWindowBuilder, Wry,
};
use tokio::time::MissedTickBehavior;
use tokio::{sync::Mutex, task::JoinSet};

use crate::commands::config::{app_name, ensure_data_dir, read_provider_metadata_from_disk};
use crate::commands::dashboard::{compute_dashboard_state, DashboardState, SystemHealth};
use crate::commands::provider_sessions::load_provider_sessions_with_overlays;
use crate::commands::provider_usage::{
    get_usage_source_catalog, get_usage_source_summary, UsageSourceCatalogEntry,
};
use crate::commands::service::{ensure_service_running_if_needed, BotState};
use crate::commands::task_board_state::{
    get_task_board_session_activities, TaskBoardSessionActivity,
};

const APP_TRAY_ID: &str = "main-tray";
const MAIN_WINDOW_LABEL: &str = "main";
pub(crate) const MENUBAR_POPOVER_WINDOW_LABEL: &str = "menubar-popover";
const APP_NAVIGATE_TAB_EVENT: &str = "app:navigate-tab";
const APP_OPEN_SESSION_EVENT: &str = "app:open-session";
const MENUBAR_POPOVER_SNAPSHOT_EVENT: &str = "menubar:snapshot-updated";
const REFRESH_INTERVAL_SECONDS: u64 = 4;
const SNAPSHOT_REFRESH_INTERVAL_SECONDS: u64 = 10;
const MENUBAR_PROVIDER_LOAD_TIMEOUT: Duration = Duration::from_secs(3);
const MENUBAR_POPOVER_WIDTH: f64 = 420.0;
const MENUBAR_POPOVER_HEIGHT: f64 = 410.0;
const MENUBAR_POPOVER_TARGET_HEIGHT: f64 = 560.0;
const MENUBAR_POPOVER_MARGIN: i32 = 8;
const MENUBAR_POPOVER_VERTICAL_OFFSET: i32 = 6;
const MENUBAR_POPOVER_WARMUP_POSITION: f64 = -10_000.0;
const MENUBAR_POPOVER_WARMUP_THRESHOLD: i32 = -9_000;
const TRAY_REOPEN_SUPPRESSION_MS: u64 = 1_000;
const CUSTOM_TRAY_ICON_RELATIVE_PATH: &str = "icons/tray-template.png";
const CUSTOM_TRAY_ICON_2X_RELATIVE_PATH: &str = "icons/tray-template@2x.png";
static LAST_TRAY_INTERACTION_EPOCH_MS: AtomicU64 = AtomicU64::new(0);

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MenubarPopoverSnapshot {
    pub generated_at_epoch: u64,
    pub usage: MenubarPopoverUsage,
    pub latest_sessions: Vec<MenubarPopoverSessionLane>,
}

#[derive(Default)]
pub struct MenubarPopoverSnapshotStore {
    snapshot: RwLock<Option<MenubarPopoverSnapshot>>,
    refresh_lock: Mutex<()>,
}

impl MenubarPopoverSnapshotStore {
    fn read(&self) -> Option<MenubarPopoverSnapshot> {
        self.snapshot.read().ok()?.clone()
    }

    fn replace(&self, snapshot: MenubarPopoverSnapshot) {
        if let Ok(mut cached) = self.snapshot.write() {
            *cached = Some(snapshot);
        }
    }
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
    active: bool,
    source: MenubarPopoverSessionCandidateSource,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MenubarPopoverSessionCandidateSource {
    Provider,
    LocalState,
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
    .position(
        MENUBAR_POPOVER_WARMUP_POSITION,
        MENUBAR_POPOVER_WARMUP_POSITION,
    )
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
    .on_page_load(|window, payload| {
        if !matches!(payload.event(), PageLoadEvent::Finished)
            || !popover_window_is_warming(&window)
        {
            return;
        }
        let app = window.app_handle().clone();
        tauri::async_runtime::spawn(async move {
            tokio::time::sleep(Duration::from_millis(100)).await;
            if let Err(error) = refresh_menubar_popover_snapshot(&app, true).await {
                eprintln!("[menubar] popover warmup snapshot failed: {error}");
            }
            if popover_window_is_warming(&window) {
                let _ = window.hide();
            }
        });
    })
    .build()
    .map(|_| ())
    .map_err(|error| format!("create menubar popover window failed: {error}"))
}

fn popover_window_is_warming(window: &tauri::WebviewWindow) -> bool {
    window
        .outer_position()
        .map(is_popover_warmup_position)
        .unwrap_or(false)
}

fn is_popover_warmup_position(position: PhysicalPosition<i32>) -> bool {
    position.x <= MENUBAR_POPOVER_WARMUP_THRESHOLD && position.y <= MENUBAR_POPOVER_WARMUP_THRESHOLD
}

pub(crate) fn setup_menubar(app: &AppHandle, state: Arc<Mutex<BotState>>) -> tauri::Result<()> {
    app.state::<MenubarPopoverSnapshotStore>()
        .replace(empty_popover_snapshot());
    if let Err(error) = ensure_popover_window(app) {
        eprintln!("[menubar] popover warmup failed: {error}");
    }
    let tray = build_tray(app)?;
    start_menubar_snapshot_refresh_loop(app.clone());
    start_menubar_refresh_loop(app.clone(), state, tray);

    Ok(())
}

fn build_tray(app: &AppHandle) -> tauri::Result<TrayIcon<Wry>> {
    let mut builder = TrayIconBuilder::with_id(APP_TRAY_ID)
        .tooltip(app_name())
        .show_menu_on_left_click(false)
        .icon_as_template(true)
        .on_tray_icon_event(move |tray, event| {
            handle_tray_icon_event(tray, event);
        });

    if let Some(icon) = load_custom_tray_icon(app).or_else(|| app.default_window_icon().cloned()) {
        builder = builder.icon(icon);
    }

    builder.build(app)
}

fn handle_tray_icon_event(tray: &TrayIcon<Wry>, event: TrayIconEvent) {
    if let TrayIconEvent::Click {
        button: MouseButton::Left,
        button_state,
        position,
        ..
    } = event
    {
        mark_tray_interaction();
        if !matches!(button_state, MouseButtonState::Up) {
            return;
        }
        let icon_rect = tray.rect().ok().flatten();
        if let Err(error) = toggle_menubar_popover(tray.app_handle(), icon_rect, Some(position)) {
            eprintln!("[menubar] tray click popover toggle failed: {}", error);
        }
    }
}

fn mark_tray_interaction() {
    LAST_TRAY_INTERACTION_EPOCH_MS.store(current_epoch_millis(), Ordering::SeqCst);
}

pub(crate) fn tray_interaction_is_recent() -> bool {
    tray_interaction_is_recent_at(
        LAST_TRAY_INTERACTION_EPOCH_MS.load(Ordering::SeqCst),
        current_epoch_millis(),
    )
}

fn tray_interaction_is_recent_at(last_interaction_ms: u64, now_ms: u64) -> bool {
    last_interaction_ms > 0
        && now_ms.saturating_sub(last_interaction_ms) <= TRAY_REOPEN_SUPPRESSION_MS
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

    if window.is_visible().map_err(|error| error.to_string())?
        && !popover_window_is_warming(&window)
    {
        window.hide().map_err(|error| error.to_string())?;
        return Ok(());
    }

    resize_menubar_popover(&window, app, icon_rect, click_position)?;
    position_menubar_popover(&window, app, icon_rect, click_position)?;
    window.unminimize().map_err(|error| error.to_string())?;
    window.show().map_err(|error| error.to_string())?;
    window.set_focus().map_err(|error| error.to_string())?;
    let refresh_app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(error) = refresh_menubar_popover_snapshot(&refresh_app, true).await {
            eprintln!("[menubar] popover open snapshot refresh failed: {error}");
        }
    });
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

fn resize_menubar_popover(
    window: &tauri::WebviewWindow,
    app: &AppHandle,
    icon_rect: Option<Rect>,
    click_position: Option<PhysicalPosition<f64>>,
) -> Result<LogicalSize<f64>, String> {
    let monitors = app
        .available_monitors()
        .map_err(|error| error.to_string())?;
    let primary_monitor = app.primary_monitor().map_err(|error| error.to_string())?;
    let target_monitor = click_position
        .and_then(|position| monitor_containing_point(&monitors, position))
        .or_else(|| icon_rect.and_then(|rect| monitor_for_rect_anchor(&monitors, rect)))
        .or(primary_monitor.as_ref());
    let height = menubar_popover_height_for_monitor(target_monitor);
    let size = LogicalSize::new(MENUBAR_POPOVER_WIDTH, height);
    window
        .set_size(Size::Logical(size))
        .map_err(|error| error.to_string())?;
    Ok(size)
}

fn menubar_popover_height_for_monitor(monitor: Option<&tauri::Monitor>) -> f64 {
    let Some(monitor) = monitor else {
        return MENUBAR_POPOVER_TARGET_HEIGHT;
    };
    let available_height = monitor.work_area().size.height as f64 / monitor.scale_factor();
    menubar_popover_height_for_available_height(available_height)
}

fn menubar_popover_height_for_available_height(available_height: f64) -> f64 {
    let available_height =
        available_height - (MENUBAR_POPOVER_MARGIN * 2 + MENUBAR_POPOVER_VERTICAL_OFFSET) as f64;
    if available_height < MENUBAR_POPOVER_HEIGHT {
        return available_height.max(320.0);
    }
    MENUBAR_POPOVER_TARGET_HEIGHT
        .min(available_height)
        .max(MENUBAR_POPOVER_HEIGHT)
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

fn start_menubar_refresh_loop(app: AppHandle, state: Arc<Mutex<BotState>>, tray: TrayIcon<Wry>) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(Duration::from_secs(REFRESH_INTERVAL_SECONDS));
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
        loop {
            ticker.tick().await;
            if let Err(error) = update_menubar_state(&app, &state, Some(&tray)).await {
                eprintln!("[menubar] tray state refresh failed: {}", error);
            }

            if app.tray_by_id(APP_TRAY_ID).is_none() {
                break;
            }
        }
    });
}

fn start_menubar_snapshot_refresh_loop(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut ticker =
            tokio::time::interval(Duration::from_secs(SNAPSHOT_REFRESH_INTERVAL_SECONDS));
        ticker.set_missed_tick_behavior(MissedTickBehavior::Skip);
        ticker.tick().await;
        loop {
            ticker.tick().await;
            let popover_is_visible = app
                .get_webview_window(MENUBAR_POPOVER_WINDOW_LABEL)
                .and_then(|window| window.is_visible().ok())
                .unwrap_or(false);
            if popover_is_visible {
                if let Err(error) = refresh_menubar_popover_snapshot(&app, true).await {
                    eprintln!("[menubar] popover snapshot refresh failed: {error}");
                }
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
    tray: Option<&TrayIcon<Wry>>,
) -> Result<(), String> {
    let service = ensure_service_running_if_needed(app, state).await?;
    let dashboard = compute_dashboard_state(app, state).await.ok();
    let active_threads = dashboard
        .as_ref()
        .and_then(|state| state.recent_activity.as_ref())
        .map(|activity| activity.active_thread_count)
        .unwrap_or(0);
    let attention_count = load_needs_attention_count().await.ok();
    let tray_status = compute_tray_status(
        service.running,
        dashboard
            .as_ref()
            .map(|state| &state.overall)
            .unwrap_or(&SystemHealth::Unknown),
    );

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
    force_refresh: Option<bool>,
) -> Result<MenubarPopoverSnapshot, String> {
    if !force_refresh.unwrap_or(false) {
        return app
            .state::<MenubarPopoverSnapshotStore>()
            .read()
            .ok_or_else(|| "menubar popover snapshot is not ready".to_string());
    }

    refresh_menubar_popover_snapshot(&app, true).await
}

async fn refresh_menubar_popover_snapshot(
    app: &AppHandle,
    force_refresh: bool,
) -> Result<MenubarPopoverSnapshot, String> {
    let store = app.state::<MenubarPopoverSnapshotStore>();
    let _refresh_guard = store.refresh_lock.lock().await;
    let providers = popover_provider_specs();
    let (usage_providers, activities, session_candidates) = tokio::join!(
        load_popover_usage_providers(&app, &providers),
        get_task_board_session_activities(),
        load_popover_session_candidates(&app, &providers, force_refresh),
    );

    let snapshot = build_popover_snapshot(
        current_epoch_seconds(),
        usage_providers?,
        activities.unwrap_or_default(),
        session_candidates,
    );
    store.replace(snapshot.clone());
    if let Err(error) = app.emit_to(
        MENUBAR_POPOVER_WINDOW_LABEL,
        MENUBAR_POPOVER_SNAPSHOT_EVENT,
        snapshot.clone(),
    ) {
        eprintln!("[menubar] popover snapshot event failed: {error}");
    }
    Ok(snapshot)
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
    specs: &[(String, String)],
) -> Result<Vec<MenubarPopoverUsageProvider>, String> {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let usage_catalog = get_usage_source_catalog(app.clone())
        .await
        .unwrap_or_default();
    let mut providers = specs
        .iter()
        .map(|(provider_id, label)| MenubarPopoverUsageProvider {
            provider_id: provider_id.clone(),
            label: label.clone(),
            tokens_today: None,
            input_tokens: None,
            output_tokens: None,
            cache_creation_tokens: None,
            cache_read_tokens: None,
            total_cost_usd: None,
            estimated: false,
        })
        .collect::<Vec<_>>();
    let mut tasks = JoinSet::new();

    for (index, (provider_id, _)) in specs.iter().enumerate() {
        let app = app.clone();
        let provider_id = provider_id.clone();
        let today = today.clone();
        let (plugin_id, source_id) =
            popover_usage_source_for_provider(&provider_id, &usage_catalog);
        tasks.spawn(async move {
            let usage = match get_usage_source_summary(
                app,
                plugin_id.clone(),
                source_id.clone(),
                today.clone(),
                today.clone(),
                None,
                Some(false),
            )
            .await
            {
                Ok(summary) => usage_breakdown_from_usage_summary(&summary, &today),
                Err(error) => {
                    eprintln!(
                        "[menubar] popover usage refresh failed for {} via {}/{}: {}",
                        provider_id, plugin_id, source_id, error
                    );
                    MenubarPopoverUsageBreakdown::default()
                }
            };
            (index, usage)
        });
    }

    while let Some(result) = tasks.join_next().await {
        let Ok((index, usage)) = result else {
            continue;
        };
        if let Some(provider) = providers.get_mut(index) {
            provider.tokens_today = usage.total_tokens;
            provider.input_tokens = usage.input_tokens;
            provider.output_tokens = usage.output_tokens;
            provider.cache_creation_tokens = usage.cache_creation_tokens;
            provider.cache_read_tokens = usage.cache_read_tokens;
            provider.total_cost_usd = usage.total_cost_usd;
        }
    }

    Ok(providers)
}

fn empty_popover_snapshot() -> MenubarPopoverSnapshot {
    let providers = popover_provider_specs()
        .into_iter()
        .map(|(provider_id, label)| MenubarPopoverUsageProvider {
            provider_id,
            label,
            tokens_today: None,
            input_tokens: None,
            output_tokens: None,
            cache_creation_tokens: None,
            cache_read_tokens: None,
            total_cost_usd: None,
            estimated: false,
        })
        .collect();
    build_popover_snapshot(current_epoch_seconds(), providers, Vec::new(), Vec::new())
}

fn popover_usage_source_for_provider(
    provider_id: &str,
    catalog: &[UsageSourceCatalogEntry],
) -> (String, String) {
    catalog
        .iter()
        .find(|source| source.provider_id.as_deref() == Some(provider_id))
        .map(|source| (source.plugin_id.clone(), source.source_id.clone()))
        .unwrap_or_else(|| ("ccusage".to_string(), provider_id.to_string()))
}

async fn load_popover_session_candidates(
    app: &AppHandle,
    providers: &[(String, String)],
    force_refresh: bool,
) -> Vec<MenubarPopoverSessionCandidate> {
    let mut candidates = Vec::new();
    let mut tasks = JoinSet::new();

    for (provider_id, _) in providers {
        let app = app.clone();
        let provider_id = provider_id.clone();
        tasks.spawn(async move {
            match tokio::time::timeout(
                MENUBAR_PROVIDER_LOAD_TIMEOUT,
                load_provider_sessions_with_overlays(&app, &provider_id, force_refresh),
            )
            .await
            {
                Ok(Ok(sessions)) => parse_provider_session_candidates(&provider_id, &sessions),
                Ok(Err(error)) => {
                    eprintln!(
                        "[menubar] popover session refresh failed for {}: {}",
                        provider_id, error
                    );
                    Vec::new()
                }
                Err(_) => {
                    eprintln!(
                        "[menubar] popover session refresh timed out for {}",
                        provider_id
                    );
                    Vec::new()
                }
            }
        });
    }

    while let Some(result) = tasks.join_next().await {
        if let Ok(provider_candidates) = result {
            candidates.extend(provider_candidates);
        }
    }

    candidates.extend(load_local_state_session_candidates(providers));

    candidates
}

fn load_local_state_session_candidates(
    providers: &[(String, String)],
) -> Vec<MenubarPopoverSessionCandidate> {
    let provider_ids = providers
        .iter()
        .map(|(provider_id, _)| provider_id.as_str())
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
                active,
                source: MenubarPopoverSessionCandidateSource::LocalState,
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
    summary: &crate::commands::provider_usage::UsageSourceSummary,
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

fn current_epoch_millis() -> u64 {
    Local::now().timestamp_millis().max(0) as u64
}

fn build_popover_snapshot(
    generated_at_epoch: u64,
    providers: Vec<MenubarPopoverUsageProvider>,
    activities: Vec<TaskBoardSessionActivity>,
    candidates: Vec<MenubarPopoverSessionCandidate>,
) -> MenubarPopoverSnapshot {
    let total_tokens_today = providers
        .iter()
        .filter_map(|provider| provider.tokens_today)
        .reduce(u64::saturating_add);

    let latest_sessions = providers
        .iter()
        .map(|provider| build_popover_session_lane(provider, &activities, &candidates))
        .collect::<Vec<_>>();
    let active_session_count = count_active_snapshot_sessions(&latest_sessions);

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

fn build_popover_session_lane(
    provider: &MenubarPopoverUsageProvider,
    activities: &[TaskBoardSessionActivity],
    candidates: &[MenubarPopoverSessionCandidate],
) -> MenubarPopoverSessionLane {
    let latest_active_activity = activities
        .iter()
        .filter(|activity| {
            activity.provider_id == provider.provider_id && activity_is_active(activity)
        })
        .max_by(|left, right| {
            left.updated_at
                .partial_cmp(&right.updated_at)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    let latest_active_provider_candidate = candidates
        .iter()
        .filter(|candidate| {
            candidate.provider_id == provider.provider_id
                && candidate.source == MenubarPopoverSessionCandidateSource::Provider
                && candidate.active
        })
        .max_by_key(|candidate| candidate.sort_rank);
    if let Some(candidate) = latest_active_provider_candidate {
        if let Some(activity) = latest_active_activity {
            if activity_rank_epoch(activity) > candidate_rank_epoch(candidate) {
                let matching_candidate = matching_session_candidate(candidates, activity);
                return build_activity_session_lane(provider, activity, matching_candidate);
            }
        }
        let matching_activity = matching_session_activity(activities, candidate);
        return build_candidate_session_lane(provider, candidate, matching_activity);
    }

    if let Some(activity) = latest_active_activity {
        let matching_candidate = matching_session_candidate(candidates, activity);
        return build_activity_session_lane(provider, activity, matching_candidate);
    }

    if let Some(candidate) = candidates
        .iter()
        .filter(|candidate| {
            candidate.provider_id == provider.provider_id
                && candidate.source == MenubarPopoverSessionCandidateSource::Provider
        })
        .max_by_key(|candidate| candidate.sort_rank)
    {
        return build_candidate_session_lane(provider, candidate, None);
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

fn matching_session_activity<'a>(
    activities: &'a [TaskBoardSessionActivity],
    candidate: &MenubarPopoverSessionCandidate,
) -> Option<&'a TaskBoardSessionActivity> {
    activities.iter().find(|activity| {
        activity.provider_id == candidate.provider_id
            && activity.session_id == candidate.session_id
            && activity_is_active(activity)
    })
}

fn activity_is_active(activity: &TaskBoardSessionActivity) -> bool {
    matches!(
        activity.status.trim().to_ascii_lowercase().as_str(),
        "active" | "running" | "needs_attention"
    )
}

fn matching_session_candidate<'a>(
    candidates: &'a [MenubarPopoverSessionCandidate],
    activity: &TaskBoardSessionActivity,
) -> Option<&'a MenubarPopoverSessionCandidate> {
    candidates.iter().find(|candidate| {
        candidate.provider_id == activity.provider_id && candidate.session_id == activity.session_id
    })
}

fn candidate_rank_epoch(candidate: &MenubarPopoverSessionCandidate) -> u64 {
    candidate.updated_at_epoch.unwrap_or(candidate.sort_rank)
}

fn activity_rank_epoch(activity: &TaskBoardSessionActivity) -> u64 {
    activity.updated_at.max(0.0) as u64
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
        title: candidate
            .and_then(|row| row.title.clone())
            .or_else(|| session_lane_title(activity)),
        latest_preview: session_lane_primary_preview(activity)
            .or_else(|| candidate.and_then(|row| row.latest_preview.clone()))
            .or_else(|| session_lane_user_preview(activity)),
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
        title: candidate
            .title
            .clone()
            .or_else(|| activity.and_then(session_lane_title))
            .or_else(|| Some(candidate.session_id.clone())),
        latest_preview: activity
            .and_then(session_lane_primary_preview)
            .or_else(|| candidate.latest_preview.clone())
            .or_else(|| activity.and_then(session_lane_user_preview)),
        status: activity
            .and_then(session_lane_status)
            .or_else(|| candidate.status.clone()),
        updated_at_epoch: candidate
            .updated_at_epoch
            .or_else(|| activity.map(|row| row.updated_at.max(0.0) as u64)),
    }
}

fn count_active_snapshot_sessions(lanes: &[MenubarPopoverSessionLane]) -> usize {
    lanes
        .iter()
        .filter(|lane| {
            lane.status
                .as_deref()
                .map(|status| matches!(status, "Active" | "Running" | "Needs reply"))
                .unwrap_or(false)
        })
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
    let status = value_text(row, &["status", "state"]);
    let active = value_bool(row, &["providerActive", "is_active", "active"]).unwrap_or(false)
        || status
            .as_deref()
            .map(|value| value.eq_ignore_ascii_case("active"))
            .unwrap_or(false);
    let updated_at_epoch = value_epoch(
        row,
        &[
            "updatedAt",
            "updated_at",
            "lastActivityAt",
            "createdAt",
            "created_at",
        ],
    );

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
        status: if active {
            Some("Active".to_string())
        } else {
            status
        },
        updated_at_epoch,
        sort_rank: updated_at_epoch.unwrap_or(0),
        active,
        source: MenubarPopoverSessionCandidateSource::Provider,
    })
}

fn session_lane_title(activity: &TaskBoardSessionActivity) -> Option<String> {
    non_empty_text(&activity.title).or_else(|| non_empty_text(&activity.session_id))
}

fn session_lane_primary_preview(activity: &TaskBoardSessionActivity) -> Option<String> {
    normalize_preview_text(&activity.last_final_message)
        .or_else(|| normalize_preview_text(&activity.last_assistant_message))
        .or_else(|| normalize_preview_text(&activity.attention_reason))
}

fn session_lane_user_preview(activity: &TaskBoardSessionActivity) -> Option<String> {
    normalize_preview_text(&activity.last_user_message)
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
        .find_map(|value| value_as_epoch_seconds(value).filter(|epoch| *epoch > 0))
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

#[cfg(test)]
mod tests {
    use std::path::Path;

    use crate::commands::dashboard::SystemHealth;
    use crate::commands::provider_usage::{
        UsageSourceCatalogEntry, UsageSourceDay, UsageSourceSummary,
    };
    use crate::commands::task_board_state::TaskBoardSessionActivity;
    use serde_json::json;

    use super::{
        anchored_popover_position, build_popover_snapshot, compute_tray_status,
        count_needs_attention, menubar_popover_height_for_available_height,
        parse_provider_session_candidate, popover_provider_specs_from_metadata,
        popover_usage_source_for_provider, resolve_custom_tray_icon_paths,
        usage_breakdown_from_usage_summary, MenubarPopoverOpenSessionTarget,
        MenubarPopoverSessionCandidate, MenubarPopoverSessionCandidateSource,
        MenubarPopoverUsageProvider, TrayStatus,
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
    fn usage_breakdown_keeps_input_output_and_cache_tokens() {
        let summary = UsageSourceSummary {
            plugin_id: "ccusage".into(),
            source_id: "claude".into(),
            days: vec![UsageSourceDay {
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
    fn popover_usage_source_uses_catalog_provider_association() {
        let catalog = vec![UsageSourceCatalogEntry {
            plugin_id: "ccusage".into(),
            source_id: "opencode".into(),
            provider_id: Some("overlay-tool".into()),
            label: "OpenCode".into(),
            description: String::new(),
            order: 30,
            icon: serde_json::Value::Null,
        }];

        assert_eq!(
            popover_usage_source_for_provider("overlay-tool", &catalog),
            ("ccusage".into(), "opencode".into())
        );
        assert_eq!(
            popover_usage_source_for_provider("codex", &catalog),
            ("ccusage".into(), "codex".into())
        );
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
                can_interrupt: false,
                can_recover: false,
                control_reason: String::new(),
                control_mode: String::new(),
                recent_events: Vec::new(),
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
                can_interrupt: false,
                can_recover: false,
                control_reason: String::new(),
                control_mode: String::new(),
                recent_events: Vec::new(),
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
    fn menubar_popover_height_uses_available_screen_space() {
        assert_eq!(menubar_popover_height_for_available_height(900.0), 560.0);
        assert_eq!(menubar_popover_height_for_available_height(480.0), 458.0);
        assert_eq!(menubar_popover_height_for_available_height(330.0), 320.0);
    }

    #[test]
    fn popover_snapshot_keeps_provider_lanes_and_sums_usage() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-workspace".into(),
            workspace_path: "/tmp/onlineworker-workspace".into(),
            session_id: "session-1".into(),
            title: "menubar polish".into(),
            status: "needs_attention".into(),
            attention_reason: "reply required".into(),
            attention_kind: String::new(),
            request_id: String::new(),
            approval_source: String::new(),
            mirrored_only: false,
            can_interrupt: false,
            can_recover: false,
            control_reason: String::new(),
            control_mode: String::new(),
            recent_events: Vec::new(),
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
    fn popover_snapshot_uses_latest_provider_sessions_when_idle() {
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
                    workspace: Some("/tmp/onlineworker-workspace".into()),
                    title: Some("Menubar popover".into()),
                    latest_preview: Some("实现 provider session fallback".into()),
                    status: None,
                    updated_at_epoch: Some(200),
                    sort_rank: 200,
                    active: false,
                    source: MenubarPopoverSessionCandidateSource::Provider,
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
                    active: false,
                    source: MenubarPopoverSessionCandidateSource::Provider,
                },
            ],
        );

        assert_eq!(snapshot.usage.active_session_count, 0);
        assert_eq!(snapshot.usage.total_tokens_today, None);
        assert_eq!(snapshot.usage.providers[0].tokens_today, None);
        assert!(!snapshot.usage.providers[0].estimated);
        assert_eq!(snapshot.usage.providers[1].tokens_today, None);
        assert!(!snapshot.usage.providers[1].estimated);
        assert_eq!(
            snapshot.latest_sessions[0].session_id.as_deref(),
            Some("codex-latest")
        );
        assert_eq!(
            snapshot.latest_sessions[0].workspace_name.as_deref(),
            Some("onlineworker-workspace")
        );
        assert_eq!(
            snapshot.latest_sessions[0].latest_preview.as_deref(),
            Some("实现 provider session fallback")
        );
        assert_eq!(snapshot.latest_sessions[0].status, None);
        assert_eq!(snapshot.latest_sessions[1].session_id, None);
    }

    #[test]
    fn popover_snapshot_does_not_treat_unarchived_local_state_as_active() {
        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![usage_provider("codex", "Codex", None)],
            Vec::new(),
            vec![MenubarPopoverSessionCandidate {
                provider_id: "codex".into(),
                session_id: "stale-local-session".into(),
                workspace: Some("/tmp/onlineworker-workspace".into()),
                title: Some("旧会话".into()),
                latest_preview: Some("旧状态残留".into()),
                status: Some("Active".into()),
                updated_at_epoch: None,
                sort_rank: 1_000_000_000_000,
                active: true,
                source: MenubarPopoverSessionCandidateSource::LocalState,
            }],
        );

        assert_eq!(snapshot.usage.active_session_count, 0);
        assert_eq!(snapshot.latest_sessions[0].session_id, None);
    }

    #[test]
    fn popover_snapshot_overlays_task_board_status_for_matching_session() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-workspace".into(),
            workspace_path: "/tmp/onlineworker-workspace".into(),
            session_id: "codex-latest".into(),
            title: String::new(),
            status: "needs_attention".into(),
            attention_reason: "等待授权".into(),
            attention_kind: "approval".into(),
            request_id: "req-1".into(),
            approval_source: "command".into(),
            mirrored_only: false,
            can_interrupt: false,
            can_recover: false,
            control_reason: String::new(),
            control_mode: String::new(),
            recent_events: Vec::new(),
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
                workspace: Some("/tmp/onlineworker-workspace".into()),
                title: Some("Provider title".into()),
                latest_preview: Some("Provider preview".into()),
                status: None,
                updated_at_epoch: Some(200),
                sort_rank: 200,
                active: false,
                source: MenubarPopoverSessionCandidateSource::Provider,
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
    fn popover_snapshot_keeps_provider_title_and_preview_when_new_turn_has_only_user_message() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "claude".into(),
            workspace_id: "claude:/tmp/sample_audio_module".into(),
            workspace_path: "/tmp/sample_audio_module".into(),
            session_id: "claude-session".into(),
            title: "现在又换了新的想法".into(),
            status: "running".into(),
            attention_reason: String::new(),
            attention_kind: String::new(),
            request_id: String::new(),
            approval_source: String::new(),
            mirrored_only: false,
            can_interrupt: false,
            can_recover: false,
            control_reason: String::new(),
            control_mode: String::new(),
            recent_events: Vec::new(),
            last_user_message: "现在又换了新的想法".into(),
            last_assistant_message: String::new(),
            last_final_message: String::new(),
            last_event_kind: "turn.started".into(),
            updated_at: 200.0,
        }];

        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![usage_provider("claude", "Claude", None)],
            activities,
            vec![MenubarPopoverSessionCandidate {
                provider_id: "claude".into(),
                session_id: "claude-session".into(),
                workspace: Some("/tmp/sample_audio_module".into()),
                title: Some("分轨 multitrackfile 不生效".into()),
                latest_preview: Some("上一条 assistant 回复".into()),
                status: Some("Active".into()),
                updated_at_epoch: Some(100),
                sort_rank: 100,
                active: true,
                source: MenubarPopoverSessionCandidateSource::Provider,
            }],
        );

        assert_eq!(
            snapshot.latest_sessions[0].title.as_deref(),
            Some("分轨 multitrackfile 不生效")
        );
        assert_eq!(
            snapshot.latest_sessions[0].latest_preview.as_deref(),
            Some("上一条 assistant 回复")
        );
    }

    #[test]
    fn popover_snapshot_prefers_current_provider_session_over_stale_local_state() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-workspace".into(),
            workspace_path: "/tmp/onlineworker-workspace".into(),
            session_id: "old-session".into(),
            title: "今天是几号？".into(),
            status: "completed".into(),
            attention_reason: String::new(),
            attention_kind: String::new(),
            request_id: String::new(),
            approval_source: String::new(),
            mirrored_only: false,
            can_interrupt: false,
            can_recover: false,
            control_reason: String::new(),
            control_mode: String::new(),
            recent_events: Vec::new(),
            last_user_message: "今天是几号？".into(),
            last_assistant_message: "今天是 2026年06月22日".into(),
            last_final_message: "今天是 2026年06月22日".into(),
            last_event_kind: "message.assistant.final".into(),
            updated_at: 100.0,
        }];

        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![usage_provider("codex", "Codex", None)],
            activities,
            vec![
                MenubarPopoverSessionCandidate {
                    provider_id: "codex".into(),
                    session_id: "current-session".into(),
                    workspace: Some("/tmp/onlineworker-workspace".into()),
                    title: Some("当前 menubar 调试".into()),
                    latest_preview: Some("正在处理 latest session".into()),
                    status: Some("Active".into()),
                    updated_at_epoch: Some(200),
                    sort_rank: 200,
                    active: true,
                    source: MenubarPopoverSessionCandidateSource::Provider,
                },
                MenubarPopoverSessionCandidate {
                    provider_id: "codex".into(),
                    session_id: "old-session".into(),
                    workspace: Some("/tmp/onlineworker-workspace".into()),
                    title: Some("今天是几号？".into()),
                    latest_preview: Some("旧 state 残留".into()),
                    status: Some("Active".into()),
                    updated_at_epoch: None,
                    sort_rank: 1_000_000_000_000,
                    active: true,
                    source: MenubarPopoverSessionCandidateSource::LocalState,
                },
            ],
        );

        assert_eq!(
            snapshot.latest_sessions[0].session_id.as_deref(),
            Some("current-session")
        );
        assert_eq!(
            snapshot.latest_sessions[0].title.as_deref(),
            Some("当前 menubar 调试")
        );
        assert_eq!(
            snapshot.latest_sessions[0].latest_preview.as_deref(),
            Some("正在处理 latest session")
        );
    }

    #[test]
    fn popover_snapshot_uses_newer_task_board_activity_when_provider_session_is_older() {
        let activities = vec![TaskBoardSessionActivity {
            provider_id: "codex".into(),
            workspace_id: "codex:/tmp/onlineworker-workspace".into(),
            workspace_path: "/tmp/onlineworker-workspace".into(),
            session_id: "new-activity".into(),
            title: "Task Board newer".into(),
            status: "running".into(),
            attention_reason: String::new(),
            attention_kind: String::new(),
            request_id: String::new(),
            approval_source: String::new(),
            mirrored_only: false,
            can_interrupt: false,
            can_recover: false,
            control_reason: String::new(),
            control_mode: String::new(),
            recent_events: Vec::new(),
            last_user_message: "new input".into(),
            last_assistant_message: String::new(),
            last_final_message: String::new(),
            last_event_kind: "message.user.accepted".into(),
            updated_at: 300.0,
        }];

        let snapshot = build_popover_snapshot(
            1_720_000_000,
            vec![usage_provider("codex", "Codex", None)],
            activities,
            vec![MenubarPopoverSessionCandidate {
                provider_id: "codex".into(),
                session_id: "older-provider".into(),
                workspace: Some("/tmp/older".into()),
                title: Some("Provider older".into()),
                latest_preview: Some("older".into()),
                status: None,
                updated_at_epoch: Some(200),
                sort_rank: 200,
                active: false,
                source: MenubarPopoverSessionCandidateSource::Provider,
            }],
        );

        assert_eq!(
            snapshot.latest_sessions[0].session_id.as_deref(),
            Some("new-activity")
        );
        assert_eq!(
            snapshot.latest_sessions[0].status.as_deref(),
            Some("Running")
        );
    }

    #[test]
    fn provider_session_candidate_marks_provider_active_rows() {
        let row = json!({
            "id": "codex-current",
            "title": "Current Codex",
            "providerActive": true,
            "updatedAt": 1_783_665_734_921_u64
        });

        let candidate = parse_provider_session_candidate("codex", &row).unwrap();

        assert!(candidate.active);
        assert_eq!(candidate.status.as_deref(), Some("Active"));
        assert_eq!(candidate.updated_at_epoch, Some(1_783_665_734));
        assert_eq!(candidate.sort_rank, 1_783_665_734);
        assert_eq!(
            candidate.source,
            MenubarPopoverSessionCandidateSource::Provider
        );
    }

    #[test]
    fn provider_session_candidate_falls_back_from_zero_updated_at() {
        let row = json!({
            "id": "codex-idle",
            "updatedAt": 0,
            "createdAt": 1_783_665_734_921_u64
        });

        let candidate = parse_provider_session_candidate("codex", &row).unwrap();

        assert_eq!(candidate.updated_at_epoch, Some(1_783_665_734));
        assert_eq!(candidate.sort_rank, 1_783_665_734);
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
