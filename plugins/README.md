# Plugins

This directory is the repository-level extension boundary for OnlineWorker.

Provider manifests under `plugins/providers/` describe the public provider surface that the app can discover and render. Implementation code may live alongside the app code when that is the simplest public contract to keep stable.

For provider plugin development rules, see [providers/DEVELOPMENT.md](providers/DEVELOPMENT.md).
