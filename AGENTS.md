# OnlineWorker Repository Notes

This file gives coding agents and maintainers the minimum repository-specific
rules needed to work safely in this codebase.

## Scope

- Public repository surface only.
- Builtin providers in this repository: `codex`, `claude`.
- Additional provider packages may be mounted through the public extension
  boundary, but they are outside this repository.

## Core Rules

1. Validate packaged-app behavior against an installed `OnlineWorker.app`, not
   only source-mode runs.
2. If a change touches the Python bot sidecar, rebuild it before packaging.
3. Keep provider-specific behavior behind the current provider registry and
   runtime boundaries. Do not reintroduce hardcoded provider wiring into shared
   app surfaces.
4. Keep public docs and code free of non-public credentials, endpoints, or
   repository-external implementation details.

## Packaging

- Apple Silicon packaging entry point: `bash scripts/build.sh`
- Intel packaging is documented in [deploy/BUILD.md](deploy/BUILD.md)
- `scripts/build.sh` is the shared build pipeline
- `ONLINEWORKER_PLUGIN_SOURCE_DIRS` is the public build-time extension hook

## Runtime and Storage

- Installed app data lives under:
  - `~/Library/Application Support/OnlineWorker/config.yaml`
  - `~/Library/Application Support/OnlineWorker/.env`
- Source-mode bot state may also use repo-local files such as:
  - `config.yaml`
  - `.env`
  - `onlineworker_state.json`

## Validation

- Python tests live under `tests/`
- Rust/Tauri tests live under `mac-app/src-tauri`
- Frontend tests live under `mac-app/tests`
- For packaged-app changes, document whether installed-app verification was
  completed or remains unverified

## Reference Documents

- [README.md](README.md)
- [README.zh.md](README.zh.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [SUPPORT.md](SUPPORT.md)
- [deploy/BUILD.md](deploy/BUILD.md)
