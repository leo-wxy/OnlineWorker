# Phase 22 Plan 03 Summary — App Shell And Menubar Theme

## Result

Implemented and source verified.

## Delivered

- Added a compact System/Light/Dark preference group beside the existing language control in the expanded sidebar; the collapsed sidebar keeps it hidden.
- Connected the main window control to the shared theme runtime without adding a ThemeProvider or a menubar-owned preference.
- Migrated the App shell, first-run banner, navigation states, service state, loading state, and attention badges to semantic tokens.
- Migrated the complete menubar inner panel, header, provider tabs, session rows, usage summary, errors, and footer actions while preserving its transparent outer window, dimensions, content, and commands.
- Simplified provider accents to reusable semantic token mappings and retained visible focus and disabled states.

## Verification

- `cd mac-app && node --test tests/appShell.test.mjs tests/menubarPopover.test.mjs tests/themeContract.test.mjs`: `32 passed; 0 failed`.
- `cd mac-app && ./node_modules/.bin/tsc --noEmit`: passed.
- `cd mac-app && pnpm build`: passed (`363 modules transformed`).
- `git diff --check`: passed.
- Independent App and menubar reviews completed; contrast, grouping, focus, disabled, and provider-border findings were corrected.

## Remaining Gate

The explicitly confirmed `core:window:allow-set-theme` capability landed in Plan 22-01. Installed-app visual verification has not been run.
