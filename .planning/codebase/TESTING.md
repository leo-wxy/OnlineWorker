# Testing Patterns

**Analysis Date:** 2026-05-10

## Test Framework

**Runner:**
- Python: `pytest 8.3.5` with `pytest-asyncio 0.24.0`
- Rust: built-in `cargo test`
- Frontend: Node built-in test runner via `node --test`

**Assertion Library:**
- Python: pytest built-in assertions
- Rust: standard Rust `assert!` / `assert_eq!`
- Frontend: Node test assertions / standard runtime assertions used in `.mjs` files

**Run Commands:**
```bash
python -m pytest -q                                 # Python suite
cargo test --manifest-path mac-app/src-tauri/Cargo.toml --quiet
cd mac-app && node --test tests/*.test.mjs          # Frontend tests
cd mac-app && pnpm build                            # Frontend type/build verification
```

## Test File Organization

**Location:**
- Python tests live in `tests/`
- Frontend tests live in `mac-app/tests/`
- Rust tests are colocated in the Tauri crate under `mac-app/src-tauri`

**Naming:**
- Python: `tests/test_*.py`
- Frontend: descriptive `*.test.mjs`, e.g. `sessionStreamLifecycle.test.mjs`
- Helper/fixture support:
  - `tests/helpers/`
  - `tests/fixtures/`

**Structure:**
```text
tests/
  test_config.py
  test_provider_facts.py
  test_state.py
  helpers/
  fixtures/

mac-app/tests/
  appTabs.test.mjs
  sessionPolling.test.mjs
  sessionStreamLifecycle.test.mjs
```

## Test Structure

**Patterns:**
- Python tests are mostly narrow behavior/regression tests around shared runtime boundaries
- Async behavior is explicitly tested where provider/session streaming is involved
- Frontend tests are model/transform/state tests, not browser-heavy visual tests
- Rust tests cover native command/service logic and host-side integration helpers

## Mocking

**Python:**
- Uses monkeypatching and `unittest.mock` where external CLI/process/network boundaries need isolation
- Common targets include adapters, app-server processes, and filesystem/environment access

**Frontend:**
- Tests usually exercise pure helpers/state transforms with lightweight stubs rather than heavy mocking frameworks

**What gets mocked:**
- External provider connections
- CLI/runtime transport edges
- Environment/file detection in packaging/runtime helpers

**What usually stays real:**
- Internal state models
- Config normalization logic
- Session event merge/transform logic

## Fixtures and Factories

**Test Data:**
- Shared fixtures exist for semantic event sequences and runtime helpers:
  - `tests/fixtures/codex_semantic_sequences.json`
  - `tests/helpers/codex_runtime.py`
- Many tests also build small inline dataclass/config payloads directly inside the test file

## Coverage

**Observed focus:**
- High emphasis on regression coverage around:
  - provider contracts
  - Telegram event/handler behavior
  - session event semantics
  - packaging/runtime edge cases
  - config/state/storage compatibility

**No explicit repo-level coverage gate is visible** in the public files reviewed, but the test distribution is broad and behavior-driven.

## Test Types

**Unit / behavior tests:**
- Dominant style across Python and frontend
- Examples:
  - `tests/test_provider_facts.py`
  - `tests/test_events_streaming.py`
  - `mac-app/tests/sessionMerge.test.mjs`

**Integration-style runtime tests:**
- Python side includes broader runtime/lifecycle/bridge coverage
- Examples:
  - `tests/test_startup_runtime.py`
  - `tests/test_codex_tui_mode.py`
  - `tests/test_claude_runtime.py`

**Packaging verification:**
- Build/package issues are also protected by targeted regression tests
- Example:
  - `tests/test_packaging_socks_support.py`

## Common Patterns

**Async Testing:**
- Common on provider/session/runtime code with `pytest-asyncio`
- Important for streaming turns, reconnects, bridge relays, and approval/question flows

**Error Testing:**
- Tests often assert specific failure classes/messages for bad provider state, unsupported operations, or config mismatches

**Frontend Regression Testing:**
- Prefer deterministic event/state transformation tests over browser snapshots
- Examples include reply watch logic, session merging, metadata badges, and provider visibility logic

## Practical Guidance

**When adding Python runtime changes:**
- Put targeted regression tests in `tests/`
- Prefer behavior-level assertions over broad fixture dumps

**When adding frontend session/config logic:**
- Add a focused `.test.mjs` in `mac-app/tests/`
- Keep the test close to the data model or transformation affected

**When touching Tauri/native commands:**
- Add or update Rust tests in `mac-app/src-tauri`
- Re-run `cargo test` and frontend build/test path because UI/native boundaries are tightly coupled

---

*Testing analysis: 2026-05-10*
*Update when test patterns change*
