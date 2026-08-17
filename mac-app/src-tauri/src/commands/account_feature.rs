use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddrV4, TcpListener, TcpStream};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Condvar, Mutex,
};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

use super::provider_bridge_common::{kill_provider_bridge_process_tree, ProviderBridgeOutput};

const ACTION_TIMEOUT: Duration = Duration::from_secs(60);
const LIST_TIMEOUT: Duration = Duration::from_secs(10);
const NATIVE_HANDLE_TTL: Duration = Duration::from_secs(120);
const LOOPBACK_RESULT_TTL: Duration = Duration::from_secs(120);
const MAX_ACTION_BYTES: usize = 8 * 1024 * 1024;
const MAX_HOST_OUTPUT_BYTES: usize = 8 * 1024 * 1024;
const MAX_BROWSER_URL_BYTES: usize = 4096;
const MAX_CALLBACK_PATH_BYTES: usize = 128;
const MAX_REQUEST_TARGET_BYTES: usize = 8192;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountFeatureError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diagnostic_id: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct AccountFeatureResponse {
    pub ok: bool,
    pub data: Option<Value>,
    pub error: Option<AccountFeatureError>,
}

fn success(data: Value) -> AccountFeatureResponse {
    AccountFeatureResponse {
        ok: true,
        data: Some(data),
        error: None,
    }
}

fn failure(code: &str, message: &str, retryable: bool) -> AccountFeatureResponse {
    AccountFeatureResponse {
        ok: false,
        data: None,
        error: Some(AccountFeatureError {
            code: code.into(),
            message: message.into(),
            retryable,
            diagnostic_id: None,
        }),
    }
}

fn safe_token(value: &str) -> bool {
    let mut chars = value.chars();
    matches!(chars.next(), Some(first) if first.is_ascii_alphanumeric())
        && chars.all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-')
        })
}

pub(crate) fn valid_feature_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 && safe_token(value)
}

fn valid_action(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 && safe_token(value)
}

fn contains_reserved_context(value: &Value) -> bool {
    match value {
        Value::Object(object) => object.iter().any(|(key, child)| {
            matches!(
                key.as_str(),
                "data_root" | "dataRoot" | "native_paths" | "nativePaths"
            ) || contains_reserved_context(child)
        }),
        Value::Array(values) => values.iter().any(contains_reserved_context),
        _ => false,
    }
}

pub(crate) fn validate_action_payload(payload: &Value) -> Result<(), String> {
    if contains_reserved_context(payload) {
        Err("invalid_payload".into())
    } else {
        Ok(())
    }
}

fn set_mode(path: &Path, mode: u32) -> Result<(), String> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode))
        .map_err(|_| "account_feature_storage_unavailable".to_string())
}

pub(crate) fn confined_feature_root(base: &Path, feature_id: &str) -> Result<PathBuf, String> {
    if !valid_feature_id(feature_id) {
        return Err("invalid_feature_id".into());
    }
    fs::create_dir_all(base).map_err(|_| "account_feature_storage_unavailable".to_string())?;
    set_mode(base, 0o700)?;
    let canonical_base = base
        .canonicalize()
        .map_err(|_| "account_feature_storage_unavailable".to_string())?;
    let candidate = canonical_base.join(feature_id);
    fs::create_dir_all(&candidate)
        .map_err(|_| "account_feature_storage_unavailable".to_string())?;
    if fs::symlink_metadata(&candidate)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(true)
    {
        return Err("unsafe_feature_root".into());
    }
    set_mode(&candidate, 0o700)?;
    let canonical = candidate
        .canonicalize()
        .map_err(|_| "account_feature_storage_unavailable".to_string())?;
    if !canonical.starts_with(&canonical_base) {
        return Err("unsafe_feature_root".into());
    }
    Ok(canonical)
}

fn account_feature_root(app: &AppHandle, feature_id: &str) -> Result<PathBuf, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|_| "account_feature_storage_unavailable".to_string())?;
    fs::create_dir_all(&app_data).map_err(|_| "account_feature_storage_unavailable".to_string())?;
    let canonical_app_data = app_data
        .canonicalize()
        .map_err(|_| "account_feature_storage_unavailable".to_string())?;
    let base = canonical_app_data.join("plugins").join("account-features");
    let root = confined_feature_root(&base, feature_id)?;
    if !root.starts_with(canonical_app_data) {
        return Err("unsafe_feature_root".into());
    }
    Ok(root)
}

pub(crate) fn normalize_sidecar_result(
    result: Result<ProviderBridgeOutput, String>,
) -> AccountFeatureResponse {
    let output = match result {
        Ok(output) => output,
        Err(error) if error.contains("timed out") => {
            return failure("host_timeout", "账号功能操作超时。", true)
        }
        Err(error) if error.contains("output too large") => {
            return failure("output_too_large", "账号功能返回数据过大。", false)
        }
        Err(_) => return failure("host_unavailable", "账号功能宿主不可用。", true),
    };
    if !output.success() {
        return failure("feature_failed", "账号功能操作失败。", true);
    }
    let parsed: Value = match serde_json::from_slice(&output.stdout) {
        Ok(value) => value,
        Err(_) => return failure("invalid_response", "账号功能返回无效。", false),
    };
    let Some(ok) = parsed.get("ok").and_then(Value::as_bool) else {
        return failure("invalid_response", "账号功能返回无效。", false);
    };
    if ok {
        return success(parsed.get("data").cloned().unwrap_or(Value::Null));
    }
    let code = parsed
        .pointer("/error/code")
        .and_then(Value::as_str)
        .filter(|code| safe_token(code))
        .unwrap_or("feature_failed");
    let retryable = parsed
        .pointer("/error/retryable")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    failure(code, "账号功能操作失败。", retryable)
}

async fn collect_account_feature_events<F>(
    mut rx: tauri::async_runtime::Receiver<CommandEvent>,
    root_pid: u32,
    max_output_bytes: usize,
    kill_root: F,
) -> Result<ProviderBridgeOutput, String>
where
    F: FnOnce(u32),
{
    let mut code = None;
    let mut signal = None;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Terminated(payload) => {
                code = payload.code;
                signal = payload.signal;
            }
            CommandEvent::Stdout(line) | CommandEvent::Stderr(line)
                if stdout
                    .len()
                    .saturating_add(stderr.len())
                    .saturating_add(line.len())
                    .saturating_add(1)
                    > max_output_bytes =>
            {
                kill_root(root_pid);
                return Err("account feature output too large".into());
            }
            CommandEvent::Stdout(line) => {
                stdout.extend(line);
                stdout.push(b'\n');
            }
            CommandEvent::Stderr(line) => {
                stderr.extend(line);
                stderr.push(b'\n');
            }
            CommandEvent::Error(_) => return Err("account feature event failed".into()),
            _ => {}
        }
    }

    Ok(ProviderBridgeOutput {
        code,
        signal,
        stdout,
        stderr,
    })
}

async fn run_account_feature_sidecar(
    app: &AppHandle,
    args: Vec<String>,
    input: Value,
    timeout: Duration,
) -> AccountFeatureResponse {
    let encoded = match serde_json::to_vec(&input) {
        Ok(encoded) if encoded.len() <= MAX_ACTION_BYTES => encoded,
        _ => return failure("invalid_payload", "账号功能参数无效。", false),
    };
    let sidecar = match app.shell().sidecar("onlineworker-bot") {
        Ok(sidecar) => sidecar,
        Err(_) => return failure("host_unavailable", "账号功能宿主不可用。", true),
    };
    let (rx, mut child) = match sidecar
        .args(args)
        .env("PYINSTALLER_RESET_ENVIRONMENT", "1")
        .set_raw_out(true)
        .spawn()
    {
        Ok(result) => result,
        Err(_) => return failure("host_unavailable", "账号功能宿主不可用。", true),
    };
    let root_pid = child.pid();
    let writer = tauri::async_runtime::spawn_blocking(move || child.write(&encoded));
    let work = async {
        let (write_result, collect_result) = tokio::join!(
            writer,
            collect_account_feature_events(
                rx,
                root_pid,
                MAX_HOST_OUTPUT_BYTES,
                kill_provider_bridge_process_tree,
            )
        );
        match write_result {
            Ok(Ok(())) => collect_result,
            _ => Err("account feature write failed".into()),
        }
    };
    let result = match tokio::time::timeout(timeout, work).await {
        Ok(result) => result,
        Err(_) => {
            kill_provider_bridge_process_tree(root_pid);
            Err(format!(
                "account feature timed out after {}ms",
                timeout.as_millis()
            ))
        }
    };
    normalize_sidecar_result(result)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CapabilityMode {
    Open,
    Save,
}

impl CapabilityMode {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "open" => Some(Self::Open),
            "save" => Some(Self::Save),
            _ => None,
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Save => "save",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct NativeCapabilityHandle {
    pub handle_id: String,
    pub display_name: String,
    pub expires_at: u64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CapabilityHandleRef {
    pub handle_id: String,
    pub mode: String,
}

#[derive(Clone)]
struct NativeHandleRecord {
    feature_id: String,
    mode: CapabilityMode,
    path: PathBuf,
    anchor_device: u64,
    anchor_inode: u64,
    expires_at: Instant,
}

#[derive(Clone)]
struct LoopbackSession {
    feature_id: String,
    shared: Arc<LoopbackShared>,
}

struct LoopbackShared {
    result: Mutex<Option<LoopbackResult>>,
    ready: Condvar,
    cancelled: AtomicBool,
    consumed: AtomicBool,
}

#[derive(Clone, Default)]
pub struct AccountFeatureHostState {
    native_handles: Arc<Mutex<HashMap<String, NativeHandleRecord>>>,
    loopbacks: Arc<Mutex<HashMap<String, LoopbackSession>>>,
}

fn expiry_epoch_ms(ttl: Duration) -> u64 {
    SystemTime::now()
        .checked_add(ttl)
        .unwrap_or(SystemTime::now())
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

fn validate_native_target(mode: CapabilityMode, path: &Path) -> Result<PathBuf, String> {
    if fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
    {
        return Err("unsafe_native_path".into());
    }
    match mode {
        CapabilityMode::Open => path
            .canonicalize()
            .map_err(|_| "invalid_native_path".to_string())
            .and_then(|canonical| {
                if canonical.is_file() {
                    Ok(canonical)
                } else {
                    Err("invalid_native_path".into())
                }
            }),
        CapabilityMode::Save => {
            let parent = path
                .parent()
                .ok_or_else(|| "invalid_native_path".to_string())?
                .canonicalize()
                .map_err(|_| "invalid_native_path".to_string())?;
            let name = path
                .file_name()
                .filter(|name| !name.is_empty())
                .ok_or_else(|| "invalid_native_path".to_string())?;
            Ok(parent.join(name))
        }
    }
}

fn validated_native_target(
    mode: CapabilityMode,
    path: &Path,
) -> Result<(PathBuf, u64, u64), String> {
    let canonical = validate_native_target(mode, path)?;
    let anchor = match mode {
        CapabilityMode::Open => canonical.as_path(),
        CapabilityMode::Save => canonical
            .parent()
            .ok_or_else(|| "invalid_native_path".to_string())?,
    };
    let metadata = fs::metadata(anchor).map_err(|_| "invalid_native_path".to_string())?;
    Ok((canonical, metadata.dev(), metadata.ino()))
}

impl AccountFeatureHostState {
    pub(crate) fn issue_native_handle(
        &self,
        feature_id: &str,
        mode: CapabilityMode,
        path: PathBuf,
        ttl: Duration,
    ) -> Result<NativeCapabilityHandle, String> {
        if !valid_feature_id(feature_id) {
            return Err("invalid_feature_id".into());
        }
        let (path, anchor_device, anchor_inode) = validated_native_target(mode, &path)?;
        let display_name = path
            .file_name()
            .and_then(|name| name.to_str())
            .filter(|name| !name.is_empty())
            .unwrap_or("Selected file")
            .chars()
            .take(128)
            .collect();
        let handle_id = uuid::Uuid::new_v4().to_string();
        let expires_at = Instant::now() + ttl;
        let mut handles = self
            .native_handles
            .lock()
            .map_err(|_| "capability_unavailable".to_string())?;
        handles.retain(|_, record| record.expires_at > Instant::now());
        handles.insert(
            handle_id.clone(),
            NativeHandleRecord {
                feature_id: feature_id.into(),
                mode,
                path,
                anchor_device,
                anchor_inode,
                expires_at,
            },
        );
        Ok(NativeCapabilityHandle {
            handle_id,
            display_name,
            expires_at: expiry_epoch_ms(ttl),
        })
    }

    pub(crate) fn redeem_native_handle(
        &self,
        feature_id: &str,
        handle_id: &str,
        mode: CapabilityMode,
    ) -> Result<PathBuf, String> {
        let mut handles = self
            .native_handles
            .lock()
            .map_err(|_| "capability_unavailable".to_string())?;
        let record = handles
            .get(handle_id)
            .cloned()
            .ok_or_else(|| "invalid_capability_handle".to_string())?;
        if record.feature_id != feature_id || record.mode != mode {
            return Err("invalid_capability_handle".into());
        }
        if record.expires_at <= Instant::now() {
            handles.remove(handle_id);
            return Err("expired_capability_handle".into());
        }
        handles.remove(handle_id);
        drop(handles);
        let (path, anchor_device, anchor_inode) = validated_native_target(mode, &record.path)?;
        if path != record.path
            || anchor_device != record.anchor_device
            || anchor_inode != record.anchor_inode
        {
            return Err("unsafe_native_path".into());
        }
        Ok(path)
    }
}

fn redeem_native_handles(
    state: &AccountFeatureHostState,
    feature_id: &str,
    handles: &[CapabilityHandleRef],
) -> Result<Vec<Value>, String> {
    let mut trusted = Vec::with_capacity(handles.len());
    for handle in handles {
        let mode = CapabilityMode::parse(&handle.mode)
            .ok_or_else(|| "invalid_capability_handle".to_string())?;
        let path = state.redeem_native_handle(feature_id, &handle.handle_id, mode)?;
        trusted.push(json!({"mode": mode.as_str(), "path": path}));
    }
    Ok(trusted)
}

fn is_cancelled(stderr: &str) -> bool {
    stderr.contains("(-128)") || stderr.to_ascii_lowercase().contains("user canceled")
}

fn sanitized_default_name(value: Option<String>) -> String {
    let name: String = value
        .unwrap_or_else(|| "export.json".into())
        .chars()
        .filter(|character| !character.is_control() && !matches!(character, '/' | '\\' | ':'))
        .take(128)
        .collect();
    if name.trim().is_empty() {
        "export.json".into()
    } else {
        name
    }
}

fn choose_native_path(
    mode: CapabilityMode,
    default_name: Option<String>,
) -> Result<Option<PathBuf>, String> {
    let script = match mode {
        CapabilityMode::Open => {
            "on run argv\ntell application \"Finder\"\nactivate\nset targetFile to choose file with prompt (item 1 of argv)\nreturn POSIX path of targetFile\nend tell\nend run"
        }
        CapabilityMode::Save => {
            "on run argv\ntell application \"Finder\"\nactivate\nset targetFile to choose file name with prompt (item 1 of argv) default name (item 2 of argv)\nreturn POSIX path of targetFile\nend tell\nend run"
        }
    };
    let mut command = Command::new("osascript");
    command.args(["-e", script, "--", "Choose an account feature file"]);
    if mode == CapabilityMode::Save {
        command.arg(sanitized_default_name(default_name));
    }
    let output = command
        .output()
        .map_err(|_| "native_dialog_unavailable".to_string())?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return if is_cancelled(&stderr) {
            Ok(None)
        } else {
            Err("native_dialog_failed".into())
        };
    }
    let raw = String::from_utf8(output.stdout).map_err(|_| "native_dialog_failed".to_string())?;
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        Ok(None)
    } else {
        Ok(Some(PathBuf::from(trimmed)))
    }
}

fn valid_browser_url(url: &str) -> bool {
    !url.is_empty()
        && url.len() <= MAX_BROWSER_URL_BYTES
        && !url
            .chars()
            .any(|character| character.is_control() || character.is_whitespace())
        && (url.starts_with("https://") || url.starts_with("http://"))
}

fn valid_callback_path(path: &str) -> bool {
    path.starts_with('/')
        && path.len() <= MAX_CALLBACK_PATH_BYTES
        && !path.contains("..")
        && path.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '/' | '_' | '-')
        })
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoopbackBeginResult {
    pub handle_id: String,
    pub redirect_uri: String,
    pub expires_at: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LoopbackResult {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub callback_url: Option<String>,
}

fn set_loopback_result(shared: &LoopbackShared, result: LoopbackResult) {
    if let Ok(mut current) = shared.result.lock() {
        if current.is_none() {
            *current = Some(result);
            shared.ready.notify_all();
        }
    }
}

fn read_request_target(
    stream: &mut TcpStream,
    deadline: Instant,
    cancelled: &AtomicBool,
) -> Result<String, ()> {
    let mut request = Vec::new();
    let mut chunk = [0_u8; 1024];
    while !request.windows(2).any(|window| window == b"\r\n") {
        if cancelled.load(Ordering::SeqCst) || Instant::now() >= deadline {
            return Err(());
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        let _ = stream.set_read_timeout(Some(remaining.min(Duration::from_millis(100))));
        let count = match stream.read(&mut chunk) {
            Ok(count) => count,
            Err(error)
                if matches!(
                    error.kind(),
                    std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
                ) =>
            {
                continue
            }
            Err(_) => return Err(()),
        };
        if count == 0 {
            break;
        }
        request.extend_from_slice(&chunk[..count]);
        if request.len() > MAX_REQUEST_TARGET_BYTES {
            return Err(());
        }
    }
    let line_end = request
        .windows(2)
        .position(|window| window == b"\r\n")
        .ok_or(())?;
    let line = std::str::from_utf8(&request[..line_end]).map_err(|_| ())?;
    let mut parts = line.split_whitespace();
    if parts.next() != Some("GET") {
        return Err(());
    }
    let target = parts.next().ok_or(())?;
    if parts.next().is_none() || parts.next().is_some() || target.len() > MAX_REQUEST_TARGET_BYTES {
        return Err(());
    }
    Ok(target.to_string())
}

fn serve_loopback(
    listener: TcpListener,
    callback_path: String,
    redirect_uri: String,
    shared: Arc<LoopbackShared>,
    ttl: Duration,
) {
    let deadline = Instant::now() + ttl;
    while Instant::now() < deadline && !shared.cancelled.load(Ordering::SeqCst) {
        match listener.accept() {
            Ok((mut stream, _)) => {
                match read_request_target(&mut stream, deadline, &shared.cancelled) {
                    Ok(target)
                        if target == callback_path
                            || target.starts_with(&(callback_path.clone() + "?")) =>
                    {
                        let _ = stream.write_all(
                        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: 38\r\nConnection: close\r\n\r\nAuthorization received. You may close.",
                    );
                        set_loopback_result(
                            &shared,
                            LoopbackResult {
                                status: "completed".into(),
                                callback_url: Some(format!("{redirect_uri}{target}")),
                            },
                        );
                        return;
                    }
                    Ok(_) => {
                        let _ = stream.write_all(
                        b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    );
                    }
                    Err(_) => {
                        let _ = stream.write_all(
                        b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                    );
                    }
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(10));
            }
            Err(_) => break,
        }
    }
    let status = if shared.cancelled.load(Ordering::SeqCst) {
        "cancelled"
    } else {
        "timedOut"
    };
    set_loopback_result(
        &shared,
        LoopbackResult {
            status: status.into(),
            callback_url: None,
        },
    );
}

pub(crate) fn begin_loopback_session(
    state: &AccountFeatureHostState,
    feature_id: &str,
    preferred_port: u16,
    callback_path: &str,
    ttl: Duration,
) -> Result<LoopbackBeginResult, String> {
    if !valid_feature_id(feature_id) || !valid_callback_path(callback_path) {
        return Err("invalid_loopback_request".into());
    }
    if ttl < Duration::from_millis(100) || ttl > Duration::from_secs(300) {
        return Err("invalid_loopback_request".into());
    }
    let address = SocketAddrV4::new(Ipv4Addr::LOCALHOST, preferred_port);
    let listener = TcpListener::bind(address)
        .or_else(|_| TcpListener::bind(SocketAddrV4::new(Ipv4Addr::LOCALHOST, 0)))
        .map_err(|_| "loopback_unavailable".to_string())?;
    listener
        .set_nonblocking(true)
        .map_err(|_| "loopback_unavailable".to_string())?;
    let port = listener
        .local_addr()
        .map_err(|_| "loopback_unavailable".to_string())?
        .port();
    let handle_id = uuid::Uuid::new_v4().to_string();
    let redirect_uri = format!("http://127.0.0.1:{port}");
    let shared = Arc::new(LoopbackShared {
        result: Mutex::new(None),
        ready: Condvar::new(),
        cancelled: AtomicBool::new(false),
        consumed: AtomicBool::new(false),
    });
    state
        .loopbacks
        .lock()
        .map_err(|_| "loopback_unavailable".to_string())?
        .insert(
            handle_id.clone(),
            LoopbackSession {
                feature_id: feature_id.into(),
                shared: shared.clone(),
            },
        );
    let callback_path = callback_path.to_string();
    let thread_callback_path = callback_path.clone();
    let thread_redirect_uri = redirect_uri.clone();
    let cleanup_handle_id = handle_id.clone();
    let cleanup_sessions = state.loopbacks.clone();
    let cleanup_shared = shared.clone();
    thread::spawn(move || {
        serve_loopback(
            listener,
            thread_callback_path,
            thread_redirect_uri,
            shared,
            ttl,
        );
        thread::sleep(LOOPBACK_RESULT_TTL);
        if let Ok(mut sessions) = cleanup_sessions.lock() {
            let should_remove = sessions
                .get(&cleanup_handle_id)
                .map(|session| Arc::ptr_eq(&session.shared, &cleanup_shared))
                .unwrap_or(false);
            if should_remove {
                sessions.remove(&cleanup_handle_id);
            }
        }
    });
    Ok(LoopbackBeginResult {
        handle_id,
        redirect_uri: format!("{redirect_uri}{callback_path}"),
        expires_at: expiry_epoch_ms(ttl),
    })
}

pub(crate) fn await_loopback_session(
    state: &AccountFeatureHostState,
    feature_id: &str,
    handle_id: &str,
) -> Result<LoopbackResult, String> {
    let session = state
        .loopbacks
        .lock()
        .map_err(|_| "loopback_unavailable".to_string())?
        .get(handle_id)
        .cloned()
        .ok_or_else(|| "invalid_loopback_handle".to_string())?;
    if session.feature_id != feature_id {
        return Err("invalid_loopback_handle".into());
    }
    if session
        .shared
        .consumed
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return Err("invalid_loopback_handle".into());
    }
    let mut result = session
        .shared
        .result
        .lock()
        .map_err(|_| "loopback_unavailable".to_string())?;
    while result.is_none() {
        result = session
            .shared
            .ready
            .wait(result)
            .map_err(|_| "loopback_unavailable".to_string())?;
    }
    let result = result
        .clone()
        .ok_or_else(|| "loopback_unavailable".to_string())?;
    state
        .loopbacks
        .lock()
        .map_err(|_| "loopback_unavailable".to_string())?
        .remove(handle_id);
    Ok(result)
}

pub(crate) fn cancel_loopback_session(
    state: &AccountFeatureHostState,
    feature_id: &str,
    handle_id: &str,
) -> Result<bool, String> {
    let mut sessions = state
        .loopbacks
        .lock()
        .map_err(|_| "loopback_unavailable".to_string())?;
    let Some(session) = sessions.get(handle_id) else {
        return Ok(false);
    };
    if session.feature_id != feature_id {
        return Err("invalid_loopback_handle".into());
    }
    let session = sessions
        .remove(handle_id)
        .expect("checked loopback session");
    session.shared.cancelled.store(true, Ordering::SeqCst);
    set_loopback_result(
        &session.shared,
        LoopbackResult {
            status: "cancelled".into(),
            callback_url: None,
        },
    );
    Ok(true)
}

#[tauri::command]
pub async fn list_account_features(app: AppHandle) -> AccountFeatureResponse {
    run_account_feature_sidecar(
        &app,
        vec!["--account-feature-list".into()],
        json!({}),
        LIST_TIMEOUT,
    )
    .await
}

#[tauri::command]
pub async fn invoke_account_feature(
    app: AppHandle,
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
    action: String,
    payload: Value,
    capability_handles: Option<Vec<CapabilityHandleRef>>,
) -> Result<AccountFeatureResponse, String> {
    if !valid_feature_id(&feature_id)
        || !valid_action(&action)
        || validate_action_payload(&payload).is_err()
    {
        return Ok(failure("invalid_request", "账号功能请求无效。", false));
    }
    let data_root = match account_feature_root(&app, &feature_id) {
        Ok(root) => root,
        Err(_) => return Ok(failure("storage_unavailable", "账号功能存储不可用。", true)),
    };
    let native_paths = match redeem_native_handles(
        state.inner(),
        &feature_id,
        capability_handles.as_deref().unwrap_or(&[]),
    ) {
        Ok(paths) => paths,
        Err(_) => {
            return Ok(failure(
                "invalid_capability",
                "账号功能文件授权无效。",
                false,
            ))
        }
    };
    Ok(run_account_feature_sidecar(
        &app,
        vec![
            "--account-feature-action".into(),
            "--account-feature-id".into(),
            feature_id,
            "--account-feature-action-name".into(),
            action,
        ],
        json!({
            "payload": payload,
            "trusted_context": {
                "data_root": data_root,
                "native_paths": native_paths,
            }
        }),
        ACTION_TIMEOUT,
    )
    .await)
}

#[tauri::command]
pub async fn choose_account_feature_file(
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
) -> Result<Option<NativeCapabilityHandle>, String> {
    if !valid_feature_id(&feature_id) {
        return Err("invalid_feature_id".into());
    }
    let selected = tauri::async_runtime::spawn_blocking(move || {
        choose_native_path(CapabilityMode::Open, None)
    })
    .await
    .map_err(|_| "native_dialog_failed".to_string())??;
    selected
        .map(|path| {
            state.issue_native_handle(&feature_id, CapabilityMode::Open, path, NATIVE_HANDLE_TTL)
        })
        .transpose()
}

#[tauri::command]
pub async fn choose_account_feature_save(
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
    suggested_name: Option<String>,
) -> Result<Option<NativeCapabilityHandle>, String> {
    if !valid_feature_id(&feature_id) {
        return Err("invalid_feature_id".into());
    }
    let selected = tauri::async_runtime::spawn_blocking(move || {
        choose_native_path(CapabilityMode::Save, suggested_name)
    })
    .await
    .map_err(|_| "native_dialog_failed".to_string())??;
    selected
        .map(|path| {
            state.issue_native_handle(&feature_id, CapabilityMode::Save, path, NATIVE_HANDLE_TTL)
        })
        .transpose()
}

#[tauri::command]
pub async fn open_account_feature_browser(url: String) -> Result<(), String> {
    if !valid_browser_url(&url) {
        return Err("invalid_browser_url".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        Command::new("open")
            .arg(url)
            .output()
            .map_err(|_| "browser_unavailable".to_string())
            .and_then(|output| {
                if output.status.success() {
                    Ok(())
                } else {
                    Err("browser_unavailable".into())
                }
            })
    })
    .await
    .map_err(|_| "browser_unavailable".to_string())?
}

#[tauri::command]
pub async fn begin_account_feature_loopback(
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
    preferred_port: u16,
    callback_path: String,
    timeout_ms: u64,
) -> Result<LoopbackBeginResult, String> {
    begin_loopback_session(
        state.inner(),
        &feature_id,
        preferred_port,
        &callback_path,
        Duration::from_millis(timeout_ms),
    )
}

#[tauri::command]
pub async fn await_account_feature_loopback(
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
    handle_id: String,
) -> Result<LoopbackResult, String> {
    let owned = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        await_loopback_session(&owned, &feature_id, &handle_id)
    })
    .await
    .map_err(|_| "loopback_unavailable".to_string())?
}

#[tauri::command]
pub async fn cancel_account_feature_loopback(
    state: tauri::State<'_, AccountFeatureHostState>,
    feature_id: String,
    handle_id: String,
) -> Result<bool, String> {
    cancel_loopback_session(state.inner(), &feature_id, &handle_id)
}

#[cfg(test)]
mod tests {
    use super::{
        await_loopback_session, begin_loopback_session, cancel_loopback_session,
        collect_account_feature_events, confined_feature_root, normalize_sidecar_result,
        valid_feature_id, validate_action_payload, AccountFeatureHostState, CapabilityMode,
    };
    use crate::commands::provider_bridge_common::ProviderBridgeOutput;
    use serde_json::json;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::os::unix::fs::{symlink, PermissionsExt};
    use std::sync::{
        atomic::{AtomicU32, Ordering},
        Arc, Barrier,
    };
    use std::thread;
    use std::time::{Duration, Instant};
    use tauri_plugin_shell::process::CommandEvent;

    fn temp_dir() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!(
            "onlineworker-account-feature-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    #[test]
    fn feature_root_is_safe_and_confined() {
        let base = temp_dir();
        assert!(valid_feature_id("feature-a"));
        for invalid in ["", "../feature", "feature/a", "feature\\a", "/absolute"] {
            assert!(!valid_feature_id(invalid));
        }

        let root = confined_feature_root(&base, "feature-a").unwrap();

        assert!(root.starts_with(base.canonicalize().unwrap()));
        assert_eq!(
            fs::metadata(&root).unwrap().permissions().mode() & 0o777,
            0o700
        );
        assert!(confined_feature_root(&base, "../escape").is_err());
        let _ = fs::remove_dir_all(base);
    }

    #[test]
    fn reserved_trusted_context_fields_are_rejected() {
        assert!(validate_action_payload(&json!({"value": 1})).is_ok());
        for key in ["data_root", "dataRoot", "native_paths", "nativePaths"] {
            let mut payload = serde_json::Map::new();
            payload.insert(key.to_string(), json!("/tmp/not-trusted"));
            assert!(validate_action_payload(&serde_json::Value::Object(payload)).is_err());
        }
    }

    #[test]
    fn process_failures_are_generic_and_redacted() {
        let failed = normalize_sidecar_result(Ok(ProviderBridgeOutput {
            code: Some(1),
            signal: None,
            stdout: b"credential-fixture".to_vec(),
            stderr: b"credential-fixture /Users/example/private.json".to_vec(),
        }));
        let malformed = normalize_sidecar_result(Ok(ProviderBridgeOutput {
            code: Some(0),
            signal: None,
            stdout: b"not-json".to_vec(),
            stderr: Vec::new(),
        }));
        let timeout = normalize_sidecar_result(Err("account feature timed out after 10ms".into()));
        let oversized = normalize_sidecar_result(Err("account feature output too large".into()));

        for response in [&failed, &malformed, &timeout, &oversized] {
            let serialized = serde_json::to_string(response).unwrap();
            assert!(!serialized.contains("credential-fixture"));
            assert!(!serialized.contains("/Users/example"));
        }
        assert_eq!(failed.error.unwrap().code, "feature_failed");
        assert_eq!(malformed.error.unwrap().code, "invalid_response");
        assert_eq!(timeout.error.unwrap().code, "host_timeout");
        assert_eq!(oversized.error.unwrap().code, "output_too_large");
    }

    #[tokio::test]
    async fn sidecar_output_is_bounded_and_kills_process() {
        let (tx, rx) = tauri::async_runtime::channel(1);
        tx.send(CommandEvent::Stdout(vec![0; 9])).await.unwrap();
        drop(tx);
        let killed_pid = Arc::new(AtomicU32::new(0));
        let killed_pid_for_callback = killed_pid.clone();

        let error = collect_account_feature_events(rx, 4242, 8, move |pid| {
            killed_pid_for_callback.store(pid, Ordering::SeqCst);
        })
        .await
        .unwrap_err();

        assert_eq!(error, "account feature output too large");
        assert_eq!(killed_pid.load(Ordering::SeqCst), 4242);
    }

    #[test]
    fn native_handles_are_feature_mode_expiry_and_replay_bound() {
        let state = AccountFeatureHostState::default();
        let root = temp_dir();
        let file = root.join("fixture.json");
        fs::write(&file, b"fixture").unwrap();
        let handle = state
            .issue_native_handle(
                "feature-a",
                CapabilityMode::Open,
                file.clone(),
                Duration::from_secs(5),
            )
            .unwrap();
        let visible = serde_json::to_string(&handle).unwrap();
        assert!(!visible.contains(file.to_string_lossy().as_ref()));

        assert!(state
            .redeem_native_handle("feature-b", &handle.handle_id, CapabilityMode::Open)
            .is_err());
        assert_eq!(
            state
                .redeem_native_handle("feature-a", &handle.handle_id, CapabilityMode::Open)
                .unwrap(),
            file.canonicalize().unwrap()
        );
        assert!(state
            .redeem_native_handle("feature-a", &handle.handle_id, CapabilityMode::Open)
            .is_err());

        let wrong_mode = state
            .issue_native_handle(
                "feature-a",
                CapabilityMode::Open,
                file.clone(),
                Duration::from_secs(5),
            )
            .unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &wrong_mode.handle_id, CapabilityMode::Save)
            .is_err());

        let expired = state
            .issue_native_handle(
                "feature-a",
                CapabilityMode::Open,
                file.clone(),
                Duration::ZERO,
            )
            .unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &expired.handle_id, CapabilityMode::Open)
            .is_err());

        let replaced = state
            .issue_native_handle(
                "feature-a",
                CapabilityMode::Open,
                file.clone(),
                Duration::from_secs(5),
            )
            .unwrap();
        fs::remove_file(&file).unwrap();
        fs::write(&file, b"replacement").unwrap();
        assert!(state
            .redeem_native_handle("feature-a", &replaced.handle_id, CapabilityMode::Open)
            .is_err());

        let target = root.join("target.json");
        symlink(&file, &target).unwrap();
        assert!(state
            .issue_native_handle(
                "feature-a",
                CapabilityMode::Open,
                target,
                Duration::from_secs(5),
            )
            .is_err());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn loopback_callback_has_exactly_one_waiter() {
        let state = AccountFeatureHostState::default();
        let session = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_secs(2),
        )
        .unwrap();
        let barrier = Arc::new(Barrier::new(3));
        let waiters: Vec<_> = (0..2)
            .map(|_| {
                let state = state.clone();
                let handle_id = session.handle_id.clone();
                let barrier = barrier.clone();
                thread::spawn(move || {
                    barrier.wait();
                    await_loopback_session(&state, "feature-a", &handle_id)
                })
            })
            .collect();
        barrier.wait();

        let address = session.redirect_uri.trim_start_matches("http://");
        let address = address.split('/').next().unwrap();
        let mut stream = TcpStream::connect(address).unwrap();
        stream
            .write_all(b"GET /auth/callback?code=fixture HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            .unwrap();
        let results: Vec<_> = waiters
            .into_iter()
            .map(|waiter| waiter.join().unwrap())
            .collect();

        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);
    }

    #[test]
    fn loopback_deadline_bounds_a_slow_request() {
        let state = AccountFeatureHostState::default();
        let session = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_millis(150),
        )
        .unwrap();
        let address = session.redirect_uri.trim_start_matches("http://");
        let address = address.split('/').next().unwrap();
        let mut stream = TcpStream::connect(address).unwrap();
        stream.write_all(b"G").unwrap();
        let started = Instant::now();

        let result = await_loopback_session(&state, "feature-a", &session.handle_id).unwrap();

        assert_eq!(result.status, "timedOut");
        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn loopback_is_local_bounded_single_use_and_cancellable() {
        let state = AccountFeatureHostState::default();
        let session = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_secs(2),
        )
        .unwrap();
        assert!(session.redirect_uri.starts_with("http://127.0.0.1:"));
        let address = session.redirect_uri.trim_start_matches("http://");
        let address = address.split('/').next().unwrap();
        let mut stream = TcpStream::connect(address).unwrap();
        stream
            .write_all(b"GET /auth/callback?code=fixture&state=fixture HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            .unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        assert!(response.starts_with("HTTP/1.1 200"));

        let completed = await_loopback_session(&state, "feature-a", &session.handle_id).unwrap();
        assert_eq!(completed.status, "completed");
        assert!(completed
            .callback_url
            .unwrap()
            .ends_with("/auth/callback?code=fixture&state=fixture"));
        assert!(await_loopback_session(&state, "feature-a", &session.handle_id).is_err());

        let cancelled = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_secs(2),
        )
        .unwrap();
        assert!(cancel_loopback_session(&state, "feature-a", &cancelled.handle_id).unwrap());
        let _ = cancel_loopback_session(&state, "feature-a", &cancelled.handle_id);
        let timed_out = begin_loopback_session(
            &state,
            "feature-a",
            0,
            "/auth/callback",
            Duration::from_millis(120),
        )
        .unwrap();
        assert_eq!(
            await_loopback_session(&state, "feature-a", &timed_out.handle_id)
                .unwrap()
                .status,
            "timedOut"
        );
        assert!(
            begin_loopback_session(&state, "feature-a", 0, "bad?path", Duration::from_secs(1))
                .is_err()
        );
    }

    #[test]
    fn shared_host_source_has_no_live_or_provider_business_authority() {
        let source = include_str!("account_feature.rs");
        for forbidden in [
            ["provider", "_owner_bridge"].concat(),
            ["provider", "_sessions"].concat(),
            ["provider", "_usage"].concat(),
            ["task_board", "_state"].concat(),
            ["Bot", "State"].concat(),
            ["Tele", "gram"].concat(),
        ] {
            assert!(!source.contains(&forbidden));
        }
    }
}
