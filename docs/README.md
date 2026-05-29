# Documentation Notes

This directory keeps lightweight public-facing support materials for the repository.

## Contents

- `screenshots/`
  - Current product screenshots used by the top-level README files.

## Screenshot Refresh

README screenshots are generated from the real React UI with sanitized demo
data, instead of capturing a live installed app and redacting it afterward. This
keeps layout fidelity while avoiding accidental exposure of local configuration
or session content.

To refresh the screenshots:

```bash
node scripts/capture-readme-screenshots.mjs
```

The script starts a temporary Vite dev server, injects mocked Tauri IPC
responses, captures the README images, and then exits. It does not package,
install, restart, or verify the macOS app. The default capture size is a stable
README viewport; set `ONLINEWORKER_SCREENSHOT_USE_TAURI_WINDOW=1` only when you
explicitly need the Tauri main-window dimensions.

Public screenshots must only show demo or masked values. Do not include real
tokens, user IDs, chat IDs, local filesystem paths, session titles, logs, usage
records, API keys, upstream endpoints, or private extension configuration.

## Scope

Files here are reference material only. They are not runtime assets, build inputs, or packaged-app requirements unless another document explicitly links to them.
