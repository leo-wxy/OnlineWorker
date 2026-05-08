use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalThreadOverlay {
    pub workspace_path: String,
    pub archived: bool,
    pub preview: Option<String>,
}

pub fn load_local_thread_overlays(
    state_path: &Path,
    tool: &str,
) -> HashMap<String, LocalThreadOverlay> {
    let Ok(raw) = std::fs::read_to_string(state_path) else {
        return HashMap::new();
    };
    let Ok(parsed) = serde_json::from_str::<Value>(&raw) else {
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
