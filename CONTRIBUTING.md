# Contributing

Thank you for contributing to OnlineWorker.

## Scope

This repository is the public app surface. Public contributions should stay
within the open-source scope:

- macOS app behavior
- Telegram integration
- public provider surface
- builtin providers: `codex` and `claude`
- packaging, tests, documentation, and developer ergonomics

Do not submit private provider implementations, private service endpoints,
private credentials, or internal-only workflow details to this repository.

## Before You Start

1. Open an issue or discussion first for non-trivial changes.
2. Keep changes focused.
3. Match the existing code style and module boundaries.
4. Prefer tests next to the code you change.

## Development Setup

Requirements:

- macOS
- Node.js 20
- Python 3.13
- Rust toolchain

Install app dependencies:

```bash
cd mac-app
pnpm install
```

## Validation

Run the relevant checks for the area you changed.

Python:

```bash
/path/to/python3 -m pytest -q tests/test_config.py tests/test_provider_facts.py tests/test_state.py tests/test_session_events.py
```

Rust / Tauri backend:

```bash
cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet
```

Frontend:

```bash
cd mac-app
node --test tests/*.test.mjs
pnpm build
```

If your change affects packaged app behavior, verify it against an installed
`OnlineWorker.app`, not only source-mode runs.

## Pull Requests

PRs should include:

- what changed
- why it changed
- how it was validated
- any remaining risk or unverified area

Small PRs are preferred over broad mixed changes.

## Public / Private Boundary

This repository supports external provider overlays through the public plugin
contracts, but it does not carry private provider code. If you maintain a
private overlay downstream, keep that code in a separate private repository.
