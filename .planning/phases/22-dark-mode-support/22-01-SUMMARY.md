# Phase 22 Plan 01 Summary — Theme Runtime And Window Sync

## Result

Implemented and source verified.

## Delivered

- Added a validated `system | light | dark` preference stored under `onlineworker.theme`, with `system` as the safe default.
- Applied the resolved theme in `index.html` before the module loads, avoiding a React-first light frame.
- Added one shared runtime for DOM application, macOS window theme, System appearance changes, storage fallback, cross-window events, and cleanup.
- Initialized the runtime before either the main window or `menubar-popover` creates its React root.
- Added only `core:window:allow-set-theme` to the existing `main` and `menubar-popover` capability scope after the user confirmed that exact change.
- Kept theme state out of `config.yaml`, Rust business state, and React context; no dependency, ThemeProvider, or Rust command was added.

## Verification

- `cd mac-app && node --test tests/theme.test.mjs`: `4 passed; 0 failed`.
- `cd mac-app && node --test tests/*.test.mjs`: `183 passed; 0 failed`.
- `cd mac-app && ./node_modules/.bin/tsc --noEmit`: passed.
- `cd mac-app && pnpm build`: passed (`363 modules transformed`).
- `git diff --check`: passed.
- Independent runtime review found no P0/P1 issue; the asynchronous Tauri unlisten cleanup finding was corrected and covered by the source contract.

## Remaining Gate

Installed-app checks for native chrome, two real WKWebViews, cold-start persistence, System appearance changes, and visual parity have not been run because packaging/install/relaunch requires separate explicit permission.
