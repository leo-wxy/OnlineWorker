# Coding Conventions

**Analysis Date:** 2026-05-10

## Naming Patterns

**Files:**
- Python source and tests use snake_case filenames, e.g. `core/storage.py`, `tests/test_state.py`
- Frontend page/component roots use PascalCase filenames, e.g. `SessionBrowser.tsx`, `SetupWizard.tsx`
- Frontend tests use `*.test.mjs` under `mac-app/tests/`
- Rust command modules use snake_case under `mac-app/src-tauri/src/commands/`

**Functions:**
- Python functions use snake_case
- React hooks/callbacks use camelCase
- Tauri/Rust command/helper functions use snake_case
- Handler factories in Python commonly use `make_*_handler` naming, e.g. `make_message_handler`

**Variables:**
- Python local variables are snake_case
- TypeScript/Rust local variables are camelCase / snake_case according to language norms
- Constants are UPPER_SNAKE_CASE when they represent true constants, e.g. `MAX_RAPID_CRASHES`

**Types:**
- Python dataclasses use PascalCase, e.g. `AppState`, `ThreadInfo`, `ProviderDescriptor`
- TypeScript types/interfaces use PascalCase
- Rust structs/enums use PascalCase

## Code Style

**Formatting:**
- Python code follows a pragmatic PEP8-like style with type hints and dataclasses used heavily
- TypeScript/React code uses double quotes in current sources and compact JSX class strings
- Rust code follows standard `rustfmt` conventions
- Markdown/docs are concise, explicit, and repository-facing rather than promotional

**Linting/Type Discipline:**
- Frontend build path relies on `tsc && vite build`
- Rust compile/test path is the primary static correctness check on native code
- Python correctness is enforced mostly via focused tests rather than a separate linter in the current public workflow

## Import Organization

**Python:**
1. Standard library imports
2. Third-party libraries
3. Local project modules

**TypeScript/React:**
1. React / Tauri external packages
2. Local component/page/i18n/utils imports

**Rust:**
1. `mod` declarations
2. Standard library
3. External crates
4. Local command modules

## Error Handling

**Patterns:**
- Python orchestration code logs and continues where partial startup failure is acceptable, especially across providers
- Fatal packaging/build/script paths use fail-fast shell behavior (`set -euo pipefail`)
- Tauri commands return per-command errors instead of crashing the whole desktop app
- Telegram and PTB update failures are logged centrally

**Error Types:**
- Runtime routing/provider issues usually surface as logged warnings/errors with context
- Config and manifest mismatches raise explicit `ValueError` / `TypeError` during load
- Tests often assert exact failure shapes for provider/runtime boundary behavior

## Logging

**Framework:**
- Python uses the stdlib `logging` package with rotating file + stdout handlers configured in `main.py`
- Rust uses `eprintln!`-style operational logging around service guard and startup behavior

**Patterns:**
- Log state transitions, connection status, startup failures, and raw Telegram callback/update diagnostics
- Keep enough structured context (provider/thread/workspace ids) to debug event-driven flows

## Comments

**When to Comment:**
- Short orienting comments appear where lifecycle/process behavior is not obvious
- Inline comments are used sparingly and usually explain compatibility or operational rationale
- Repository docs carry much of the operational explanation instead of over-commenting code

**JSDoc/TSDoc / Docstrings:**
- Python docstrings are common on public helpers/dataclasses
- TypeScript files rely more on clear naming than heavy docblock use

## Function Design

**Patterns:**
- Python runtime logic prefers small focused helpers around explicit state objects
- Handler registration is composed from factory functions rather than monolithic inline closures
- Config/state/provider code strongly favors normalized helper methods over scattered ad hoc lookups

## Module Design

**Exports:**
- Python modules usually expose concrete functions/classes directly
- React components/pages export a single main component from a file
- Rust native surface is organized as command modules aggregated through `lib.rs`

**Abstraction Preference:**
- Shared/provider-neutral behavior belongs in `core/providers/*`
- Provider-specific behavior stays in `plugins/providers/builtin/<provider>/`
- Desktop-specific bridges stay in Tauri command modules rather than leaking into shared Python runtime code

---

*Convention analysis: 2026-05-10*
*Update when patterns change*
