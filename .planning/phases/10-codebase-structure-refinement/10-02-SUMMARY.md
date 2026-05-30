# 10-02 Summary: Tauri Config and Dashboard Helper Extraction

**Date:** 2026-05-30
**Status:** completed
**Mode:** behavior-preserving refactor

## Completed

- Extracted builtin provider/notification asset access from `config_provider.rs` into `config_provider/provider_assets.rs`.
- Extracted notification plugin metadata parsing, settings-field normalization, setup guide loading, and channel metadata projection into `config_provider/notification_metadata.rs`.
- Extracted dashboard provider config snapshots, owner bridge runtime status reads, provider health derivation, and provider status construction into `dashboard/provider_status.rs`.
- Extracted dashboard recent activity reading, Codex sqlite activity lookup, Claude local-session activity lookup, overlay filtering, and recent-activity cache into `dashboard/recent_activity.rs`.
- Kept all public Tauri command names, response structs, and JSON shapes unchanged.

## Files Changed

- `mac-app/src-tauri/src/commands/config_provider.rs`
- `mac-app/src-tauri/src/commands/config_provider/provider_assets.rs`
- `mac-app/src-tauri/src/commands/config_provider/notification_metadata.rs`
- `mac-app/src-tauri/src/commands/dashboard.rs`
- `mac-app/src-tauri/src/commands/dashboard/provider_status.rs`
- `mac-app/src-tauri/src/commands/dashboard/recent_activity.rs`

## Behavior Preserved

- Provider metadata still comes through the existing config provider command path.
- Notification channel metadata still exposes the same fields, including builtin Telegram icon and local setup guide HTML.
- Dashboard provider health still reads owner bridge runtime status when available and falls back to CLI availability when appropriate.
- Dashboard recent activity still prefers provider-specific activity sources and falls back to `onlineworker_state.json` workspace/thread state.

## Verification

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider --quiet
```

Result: `32 passed`.

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml dashboard --quiet
```

Result: `21 passed`.

```bash
git diff --check
```

Result: passed.

## Packaged-App Verification

Not required for this slice. The refactor did not change startup, sidecar process management, Tauri command names, bundled asset paths from the caller perspective, owner bridge protocol payloads, or installed app data paths.

## Notes

- `cargo test --manifest-path mac-app/src-tauri/Cargo.toml config_provider dashboard --quiet` was attempted first, but Cargo accepts only one test filter. The focused checks were run as separate commands instead.
- `cargo fmt` briefly produced unrelated import formatting in `mac-app/src-tauri/src/lib.rs`; that unrelated formatting was reverted so this slice remains scoped to config/dashboard command modules.

## Next Slice

Plan or execute `10-03`: extract pure helpers from `bot/handlers/workspace.py`.
