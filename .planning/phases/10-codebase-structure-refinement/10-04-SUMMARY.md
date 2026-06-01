# 10-04 Summary: Frontend Dashboard State and Presentation Extraction

**Date:** 2026-06-01
**Status:** completed
**Mode:** behavior-preserving refactor

## Completed

- Extracted Dashboard view-model helpers into
  `mac-app/src/components/dashboard/model.ts`.
- Split Dashboard presentation into component-local files:
  - `DashboardHero.tsx`
  - `DashboardSidebar.tsx`
  - `ProviderStatusList.tsx`
  - `DashboardAlerts.tsx`
  - `DashboardError.tsx`
  - `ProviderIcon.tsx`
  - `TelegramBadge.tsx`
  - `SettingSwitch.tsx`
- Reduced `mac-app/src/pages/Dashboard.tsx` to page orchestration: hook state,
  service/provider Tauri actions, Codex TUI host open action, and component
  wiring.
- Extended `useDashboardState` with derived provider list, service-control
  status, and Codex TUI host openability.

## Files Changed

- `mac-app/src/pages/Dashboard.tsx`
- `mac-app/src/hooks/useDashboardState.ts`
- `mac-app/src/components/dashboard/*`

## Behavior Preserved

- Dashboard still calls the same Tauri commands:
  - `get_dashboard_state`
  - `set_provider_flags`
  - `service_start`
  - `service_stop`
  - `service_restart`
  - `open_codex_tui_host_terminal`
- Provider managed/autostart toggles still restart the service only when the
  bot process is currently running.
- The Codex TUI host action still appears only when recent activity identifies
  a Codex session with both workspace path and session id.
- Existing Dashboard visual structure, localized text, badges, quick actions,
  alerts, and provider status rows are preserved.

## Verification

```bash
node --test mac-app/tests/appShell.test.mjs mac-app/tests/dashboardProviderStatus.test.mjs
```

Result: `13 passed`.

```bash
cd mac-app && ./node_modules/.bin/tsc --noEmit
```

Result: passed. The shell printed `pyenv: cannot rehash:
/Users/wxy/.pyenv/shims isn't writable`, but the TypeScript command exited 0.

```bash
git diff --check
```

Result: passed.

Full source verification after completion:

```bash
node --test mac-app/tests/*.test.mjs
```

Result: `90 passed`.

```bash
cd mac-app && npm run build
```

Result: passed.

```bash
/Users/wxy/.pyenv/shims/python3.13 -m pytest -q
```

Result: `760 passed`.

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet
```

Result: `197 passed`.

```bash
node /Users/wxy/.codex/get-shit-done/bin/gsd-tools.cjs validate consistency
```

Result: passed with existing warnings for older phase artifacts.

## Packaged-App Verification

Not required for this slice. The refactor did not touch startup, backend Tauri
commands, sidecar packaging, bridge IPC, or installed-app data paths.

## Phase 10 Status

This completes the three selected implementation slices from the Phase 10
structure-debt audit:

1. Tauri config/dashboard helpers.
2. Python workspace pure helpers.
3. Frontend Dashboard state/presentation.
