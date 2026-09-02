use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalThreadOverlay {
    pub workspace_path: String,
    pub archived: bool,
    pub preview: Option<String>,
}

fn load_state_value(state_path: &Path) -> Option<Value> {
    [
        state_path.to_path_buf(),
        state_path.with_extension("json.bak"),
    ]
    .into_iter()
    .find_map(|path| {
        let raw = std::fs::read_to_string(path).ok()?;
        let parsed = serde_json::from_str::<Value>(&raw).ok()?;
        if parsed
            .get("workspaces")
            .and_then(Value::as_object)
            .is_some()
        {
            Some(parsed)
        } else {
            None
        }
    })
}

pub fn load_local_thread_overlays(
    state_path: &Path,
    tool: &str,
) -> HashMap<String, LocalThreadOverlay> {
    let Some(parsed) = load_state_value(state_path) else {
        return HashMap::new();
    };
    let Some(workspaces) = parsed.get("workspaces").and_then(Value::as_object) else {
        return HashMap::new();
    };

    let mut overlays = HashMap::new();
    for workspace in workspaces.values() {
        if workspace.get("tool").and_then(Value::as_str) != Some(tool) {
            continue;
        }
        let workspace_path = workspace
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let Some(threads) = workspace.get("threads").and_then(Value::as_object) else {
            continue;
        };
        for (thread_id, info) in threads {
            let archived = info
                .get("archived")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let preview = info
                .get("preview")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|text| !text.is_empty())
                .map(ToOwned::to_owned);
            overlays.insert(
                thread_id.clone(),
                LocalThreadOverlay {
                    workspace_path: workspace_path.clone(),
                    archived,
                    preview,
                },
            );
        }
    }

    overlays
}

#[cfg(test)]
mod tests {
    use super::load_local_thread_overlays;
    use std::fs;

    #[test]
    fn invalid_primary_recovers_local_overlays_from_backup() {
        let temp_dir =
            std::env::temp_dir().join(format!("ow-overlay-backup-{}", std::process::id()));
        let _ = fs::remove_dir_all(&temp_dir);
        fs::create_dir_all(&temp_dir).expect("create temp dir");
        let state_path = temp_dir.join("onlineworker_state.json");
        fs::write(&state_path, "{").expect("write invalid primary");
        fs::write(
            state_path.with_extension("json.bak"),
            serde_json::to_string(&serde_json::json!({
                "workspaces": {
                    "overlay-tool:/tmp/sample-workspace": {
                        "path": "/tmp/sample-workspace",
                        "tool": "overlay-tool",
                        "threads": {
                            "session-a": {
                                "archived": true,
                                "preview": "Recovered overlay"
                            }
                        }
                    }
                }
            }))
            .expect("serialize backup"),
        )
        .expect("write backup");

        let overlays = load_local_thread_overlays(&state_path, "overlay-tool");

        assert_eq!(
            overlays["session-a"].workspace_path,
            "/tmp/sample-workspace"
        );
        assert!(overlays["session-a"].archived);
        assert_eq!(
            overlays["session-a"].preview.as_deref(),
            Some("Recovered overlay")
        );
        let _ = fs::remove_dir_all(&temp_dir);
    }
}
