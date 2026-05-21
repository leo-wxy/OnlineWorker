use serde::Serialize;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};

use super::config::data_dir;

const TELEGRAM_ATTACHMENTS_DIR: &str = "attachments";
const COMPOSER_ATTACHMENTS_DIR: &str = "composer-attachments";

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AttachmentCacheStats {
    pub file_count: u64,
    pub total_bytes: u64,
    pub paths: Vec<AttachmentCachePathStats>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AttachmentCachePathStats {
    pub name: String,
    pub path: String,
    pub exists: bool,
    pub file_count: u64,
    pub total_bytes: u64,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AttachmentCacheClearResult {
    pub deleted_files: u64,
    pub deleted_dirs: u64,
    pub freed_bytes: u64,
    pub failed: Vec<String>,
    pub stats: AttachmentCacheStats,
}

fn attachment_cache_dirs(data_dir: &Path) -> Vec<(&'static str, PathBuf)> {
    vec![
        (
            "Telegram attachments",
            data_dir.join(TELEGRAM_ATTACHMENTS_DIR),
        ),
        (
            "Composer attachments",
            data_dir.join(COMPOSER_ATTACHMENTS_DIR),
        ),
    ]
}

fn create_data_dir() -> Result<PathBuf, String> {
    let dir = data_dir();
    fs::create_dir_all(&dir).map_err(|err| format!("Cannot create data dir: {}", err))?;
    Ok(dir)
}

#[derive(Debug, Default, Clone, Copy)]
struct ScanStats {
    files: u64,
    dirs: u64,
    bytes: u64,
}

impl ScanStats {
    fn add(&mut self, other: ScanStats) {
        self.files += other.files;
        self.dirs += other.dirs;
        self.bytes += other.bytes;
    }
}

fn scan_path(path: &Path) -> Result<ScanStats, String> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(err) if err.kind() == ErrorKind::NotFound => return Ok(ScanStats::default()),
        Err(err) => return Err(format!("Cannot read {}: {}", path.display(), err)),
    };

    if !metadata.is_dir() {
        return Ok(ScanStats {
            files: 1,
            dirs: 0,
            bytes: metadata.len(),
        });
    }

    let mut stats = ScanStats {
        files: 0,
        dirs: 1,
        bytes: 0,
    };
    for entry in
        fs::read_dir(path).map_err(|err| format!("Cannot list {}: {}", path.display(), err))?
    {
        let entry =
            entry.map_err(|err| format!("Cannot read {} entry: {}", path.display(), err))?;
        stats.add(scan_path(&entry.path())?);
    }
    Ok(stats)
}

fn attachment_cache_stats_for_data_dir(data_dir: &Path) -> Result<AttachmentCacheStats, String> {
    let mut paths = Vec::new();
    let mut file_count = 0;
    let mut total_bytes = 0;

    for (name, path) in attachment_cache_dirs(data_dir) {
        let exists = fs::symlink_metadata(&path).is_ok();
        let stats = scan_path(&path)?;
        file_count += stats.files;
        total_bytes += stats.bytes;
        paths.push(AttachmentCachePathStats {
            name: name.to_string(),
            path: path.to_string_lossy().to_string(),
            exists,
            file_count: stats.files,
            total_bytes: stats.bytes,
        });
    }

    Ok(AttachmentCacheStats {
        file_count,
        total_bytes,
        paths,
    })
}

#[derive(Debug, Default)]
struct ClearStats {
    deleted_files: u64,
    deleted_dirs: u64,
    freed_bytes: u64,
    failed: Vec<String>,
}

impl ClearStats {
    fn add(&mut self, other: ClearStats) {
        self.deleted_files += other.deleted_files;
        self.deleted_dirs += other.deleted_dirs;
        self.freed_bytes += other.freed_bytes;
        self.failed.extend(other.failed);
    }
}

fn clear_entry(path: &Path) -> Result<ClearStats, String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|err| format!("Cannot read {}: {}", path.display(), err))?;

    if metadata.is_dir() {
        let stats = scan_path(path)?;
        fs::remove_dir_all(path)
            .map_err(|err| format!("Cannot remove directory {}: {}", path.display(), err))?;
        return Ok(ClearStats {
            deleted_files: stats.files,
            deleted_dirs: stats.dirs,
            freed_bytes: stats.bytes,
            failed: Vec::new(),
        });
    }

    let bytes = metadata.len();
    fs::remove_file(path)
        .map_err(|err| format!("Cannot remove file {}: {}", path.display(), err))?;
    Ok(ClearStats {
        deleted_files: 1,
        deleted_dirs: 0,
        freed_bytes: bytes,
        failed: Vec::new(),
    })
}

fn clear_cache_dir(path: &Path) -> ClearStats {
    let mut result = ClearStats::default();

    match fs::symlink_metadata(path) {
        Ok(metadata) if !metadata.is_dir() => {
            match clear_entry(path) {
                Ok(entry_result) => result.add(entry_result),
                Err(err) => result.failed.push(err),
            }
            if let Err(err) = fs::create_dir_all(path) {
                result
                    .failed
                    .push(format!("Cannot recreate {}: {}", path.display(), err));
            }
            return result;
        }
        Ok(_) => {}
        Err(err) if err.kind() == ErrorKind::NotFound => {
            if let Err(create_err) = fs::create_dir_all(path) {
                result
                    .failed
                    .push(format!("Cannot create {}: {}", path.display(), create_err));
            }
            return result;
        }
        Err(err) => {
            result
                .failed
                .push(format!("Cannot read {}: {}", path.display(), err));
            return result;
        }
    }

    let entries = match fs::read_dir(path) {
        Ok(entries) => entries,
        Err(err) => {
            result
                .failed
                .push(format!("Cannot list {}: {}", path.display(), err));
            return result;
        }
    };

    for entry in entries {
        match entry {
            Ok(entry) => match clear_entry(&entry.path()) {
                Ok(entry_result) => result.add(entry_result),
                Err(err) => result.failed.push(err),
            },
            Err(err) => {
                result
                    .failed
                    .push(format!("Cannot read {} entry: {}", path.display(), err))
            }
        }
    }

    if let Err(err) = fs::create_dir_all(path) {
        result
            .failed
            .push(format!("Cannot recreate {}: {}", path.display(), err));
    }

    result
}

fn clear_attachment_cache_for_data_dir(
    data_dir: &Path,
) -> Result<AttachmentCacheClearResult, String> {
    let mut clear_stats = ClearStats::default();

    for (_, path) in attachment_cache_dirs(data_dir) {
        clear_stats.add(clear_cache_dir(&path));
    }

    Ok(AttachmentCacheClearResult {
        deleted_files: clear_stats.deleted_files,
        deleted_dirs: clear_stats.deleted_dirs,
        freed_bytes: clear_stats.freed_bytes,
        failed: clear_stats.failed,
        stats: attachment_cache_stats_for_data_dir(data_dir)?,
    })
}

#[tauri::command]
pub async fn get_attachment_cache_stats() -> Result<AttachmentCacheStats, String> {
    let data_dir = create_data_dir()?;
    attachment_cache_stats_for_data_dir(&data_dir)
}

#[tauri::command]
pub async fn clear_attachment_cache() -> Result<AttachmentCacheClearResult, String> {
    let data_dir = create_data_dir()?;
    clear_attachment_cache_for_data_dir(&data_dir)
}

#[cfg(test)]
mod tests {
    use super::{attachment_cache_stats_for_data_dir, clear_attachment_cache_for_data_dir};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_data_dir(name: &str) -> PathBuf {
        let unique = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time")
            .as_nanos();
        let dir = std::env::temp_dir().join(format!(
            "onlineworker-attachment-cache-{name}-{}-{unique}",
            std::process::id()
        ));
        fs::create_dir_all(&dir).expect("create temp data dir");
        dir
    }

    #[test]
    fn stats_include_telegram_and_composer_attachment_caches() {
        let dir = temp_data_dir("stats");
        let telegram_dir = dir.join("attachments");
        let composer_dir = dir.join("composer-attachments").join("nested");
        fs::create_dir_all(&telegram_dir).expect("create telegram cache dir");
        fs::create_dir_all(&composer_dir).expect("create composer cache dir");
        fs::write(telegram_dir.join("image.jpg"), [1_u8, 2, 3]).expect("write telegram image");
        fs::write(composer_dir.join("document.pdf"), [4_u8, 5, 6, 7]).expect("write composer file");

        let stats = attachment_cache_stats_for_data_dir(&dir).expect("stats");

        assert_eq!(stats.file_count, 2);
        assert_eq!(stats.total_bytes, 7);
        assert_eq!(stats.paths.len(), 2);
        assert_eq!(stats.paths[0].name, "Telegram attachments");
        assert_eq!(stats.paths[0].file_count, 1);
        assert_eq!(stats.paths[0].total_bytes, 3);
        assert_eq!(stats.paths[1].name, "Composer attachments");
        assert_eq!(stats.paths[1].file_count, 1);
        assert_eq!(stats.paths[1].total_bytes, 4);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn clear_removes_cache_contents_but_keeps_cache_directories() {
        let dir = temp_data_dir("clear");
        let telegram_dir = dir.join("attachments");
        let composer_nested_dir = dir.join("composer-attachments").join("nested");
        fs::create_dir_all(&telegram_dir).expect("create telegram cache dir");
        fs::create_dir_all(&composer_nested_dir).expect("create composer cache dir");
        fs::write(telegram_dir.join("image.jpg"), [1_u8, 2, 3]).expect("write telegram image");
        fs::write(composer_nested_dir.join("document.pdf"), [4_u8, 5, 6, 7])
            .expect("write composer file");

        let result = clear_attachment_cache_for_data_dir(&dir).expect("clear cache");

        assert_eq!(result.deleted_files, 2);
        assert_eq!(result.freed_bytes, 7);
        assert_eq!(result.failed, Vec::<String>::new());
        assert!(dir.join("attachments").is_dir());
        assert!(dir.join("composer-attachments").is_dir());
        assert!(fs::read_dir(dir.join("attachments"))
            .expect("read telegram cache")
            .next()
            .is_none());
        assert!(fs::read_dir(dir.join("composer-attachments"))
            .expect("read composer cache")
            .next()
            .is_none());
        assert_eq!(result.stats.file_count, 0);
        assert_eq!(result.stats.total_bytes, 0);

        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn source_does_not_call_config_ensure_data_dir_from_cache_commands() {
        let source = include_str!("attachment_cache.rs");
        let config_ensure_import = concat!("use super::config::", "ensure_data_dir;");
        let config_ensure_call = concat!("ensure_data", "_dir()?");

        assert!(!source.contains(config_ensure_import));
        assert!(!source.contains(config_ensure_call));
        assert!(source.contains("create_data_dir()?"));
    }
}
