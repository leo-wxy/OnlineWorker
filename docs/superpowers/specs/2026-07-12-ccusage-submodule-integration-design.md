# ccusage Submodule Integration Design

Date: 2026-07-12
Status: Approved
Scope: ccusage source catalog, plugin integration, packaging, and Usage UI semantics

## Summary

Replace OnlineWorker's handwritten Codex and Claude usage parsers with the
upstream `ccusage` CLI, pinned as a Git submodule and packaged as an additional
application sidecar. Expose every usage source supported by the pinned ccusage
version through a dedicated OnlineWorker usage plugin.

OnlineWorker will no longer interpret provider JSONL usage records. It will
invoke the pinned `ccusage` binary, normalize its JSON report into the existing
`ProviderUsageSummary` contract, and render that contract in the desktop UI and
bot commands.

This prevents OnlineWorker from drifting behind ccusage fixes for replayed
parent history, copied or forked sessions, cache accounting, model metadata,
timezone grouping, and new agent usage sources.

## Goals

- Make ccusage the single source of truth for Codex and Claude token parsing.
- Display every usage source supported by the pinned ccusage version, even when
  that source is not an OnlineWorker Agent provider.
- Model usage discovery as a first-class plugin capability instead of
  hardcoding ccusage sources in React or shared Rust commands.
- Keep OnlineWorker builds deterministic by pinning an explicit submodule
  commit.
- Package ccusage inside `OnlineWorker.app`; no user-installed Node, Bun, npm,
  or ccusage command is required.
- Remove the old Codex and Claude usage implementations instead of retaining a
  fallback with different totals.
- Preserve the existing provider registry and `ProviderUsageSummary` boundary.
- Make the Usage page distinguish non-cached input, cache reads, output, and
  total processed tokens.
- Make upstream updates deliberate, reviewable, and covered by compatibility
  tests.

## Non-goals

- Expose every provider supported by ccusage as an executable OnlineWorker
  Agent provider. Usage-only sources do not appear in Tasks, Sessions,
  Commands, approvals, or provider process management.
- Replace OnlineWorker session browsing with ccusage session reports.
- Depend on `npx`, `bunx`, a global ccusage installation, or network access at
  runtime.
- Make OpenAI's server dashboard an exact automated oracle. ccusage reads local
  logs and can still differ from server-side account, profile, or entitlement
  filters.
- Change provider enablement or visibility rules.

## Selected Approach

Use a pinned Git submodule plus a compiled sidecar:

```text
third_party/ccusage/                 pinned upstream repository
  rust/crates/ccusage/               upstream parser and CLI

scripts/build.sh
  -> build OnlineWorker Python sidecar
  -> build pinned ccusage Rust CLI
  -> copy both target-specific binaries into Tauri externalBin staging
  -> build OnlineWorker.app / DMG
```

The submodule commit is part of the OnlineWorker Git tree, so normal builds are
reproducible. Updating ccusage means updating the submodule pointer and passing
OnlineWorker's compatibility checks before committing the new pointer.

## Plugin Model

Usage data is a separate extension surface from an executable Agent provider.
Add a new plugin kind:

```yaml
schema_version: 1
id: ccusage
kind: usage
visibility: public
label: ccusage
runtime:
  type: sidecar
  binary: ccusage
entrypoints:
  python_descriptor: plugins.usage.builtin.ccusage.python.plugin:create_usage_plugin_descriptor
sources:
  - id: codex
    label: Codex
    order: 10
    icon:
      path: icons/codex.svg
  - id: claude
    label: Claude
    order: 20
    icon:
      path: icons/claude.svg
```

The complete `sources` catalog is synchronized with the pinned ccusage version
and includes all focused source commands exposed by that version, including
Codex, Claude, OpenCode, Amp, Droid, Codebuff, Hermes Agent, Goose, OpenClaw,
Kilo, Kimi, Qwen, Copilot CLI, Gemini CLI, and pi-agent when present upstream.

The plugin catalog is the UI and runtime source of truth. React does not contain
a built-in ccusage source list.

For the pinned ccusage source tree, the authoritative machine-checked source
set is `rust/crates/ccusage/src/adapter/all/loader.rs` constant
`BUILT_IN_AGENT_NAMES`. `scripts/sync-ccusage-sources.py` extracts that Rust
string-array constant and merges the IDs with OnlineWorker-owned presentation
metadata (label, description, order, optional icon). The update fails if:

- an upstream source ID is missing from the manifest;
- the manifest contains an ID no longer present upstream;
- a source ID lacks presentation metadata;
- `ccusage <source> daily --json --no-cost` is not a valid command.

This is intentionally pinned to a checked source path and symbol rather than an
assumed `list-sources` CLI that ccusage does not provide. A breaking upstream
move causes an explicit update failure and requires review.

### Relationship to Agent provider plugins

An Agent provider manifest may associate itself with a usage source:

```yaml
provider:
  usage:
    plugin_id: ccusage
    source_id: codex
```

This association lets Codex and Claude reuse their existing provider label,
icon, and ordering where appropriate. It does not make association mandatory:
usage-only sources supplied by the ccusage plugin remain visible in the Usage
page without an Agent provider manifest.

Provider visibility and enablement do not hide usage sources. The Usage page is
an inventory of the pinned ccusage plugin's supported sources; sources without
local records render an empty state.

Unassociated usage sources use a generic local usage icon. Codex and Claude may
reuse their existing provider icons through association. OnlineWorker does not
copy third-party brand icons without an explicit source and compatible license.

### Plugin discovery boundary

Add a usage-plugin loader parallel to the existing provider and notification
plugin loaders. It supports:

- bundled manifests under `plugins/usage/builtin/`;
- packaged staged manifests;
- an explicit public overlay path for external usage plugins;
- icon resolution using the same safe relative-path rules as provider and
  notification plugins;
- schema normalization in both Rust and Python where runtime access is needed.

The initial bundled implementation is `plugins/usage/builtin/ccusage`. The
plugin boundary remains generic so another local usage backend can be added
without modifying `UsageBrowser`.

### Usage plugin runtime ABI

Every executable usage plugin declares `entrypoints.python_descriptor`. The
entrypoint returns a `UsagePluginDescriptor` with:

```python
UsagePluginDescriptor(
    plugin_id: str,
    runtime_identity: Callable[[], str],
    get_summary: Callable[[UsageSummaryRequest], dict],
)
```

`UsageSummaryRequest` contains `plugin_id`, `source_id`, `start_date`,
`end_date`, `timezone`, and `force_refresh`. `get_summary` returns the shared
OnlineWorker normalized daily summary, not provider-specific raw JSON.

The Python usage registry:

1. loads and validates the manifest;
2. imports the descriptor entrypoint using the same safe overlay import-root
   rules as other plugin types;
3. requires descriptor `plugin_id` to equal manifest `id`;
4. verifies the requested source exists in the manifest catalog;
5. applies the shared single-flight, cache, timeout/error, and response-schema
   boundary around the descriptor call.

The ccusage descriptor invokes the bundled sidecar and converts ccusage JSON.
Another usage plugin may use a different local backend behind the same
descriptor ABI without changing Rust, React, Telegram, or the owner bridge.
There is no generic shell-command manifest that accepts arbitrary argv; code
execution remains in the reviewed Python descriptor.

## Authoritative Runtime Boundary

`onlineworker-bot` owns the only execution and normalization implementation.
Add a shared Python package with explicit responsibilities:

```text
core/usage/contracts.py          normalized request/response shapes
core/usage/registry.py           usage plugin and source resolution
core/usage/runtime.py            shared single-flight, cache, timeout/error boundary
plugins/usage/builtin/ccusage/
  python/plugin.py               descriptor and ccusage JSON normalization
  python/runtime.py              fixed argv execution and binary resolution
```

All consumers call this package:

```text
Desktop React
  -> Tauri get_usage_source_summary
    -> provider owner bridge request: usage_source_summary
      -> core.usage registry/runtime

Desktop owner bridge unavailable
  -> one-shot onlineworker-bot usage bridge
    -> the same core.usage registry/runtime

Telegram /token_usage
  -> Agent provider usage association
    -> the same core.usage registry/runtime
```

Rust owns transport and deserializes the final OnlineWorker contract only. It
does not parse ccusage JSON. React never executes ccusage. The owner bridge and
one-shot bridge use the same request and response schema, and the Telegram path
imports the same Python function rather than a wrapper with separate rules.

## Why Not Link ccusage as a Rust Library

ccusage's Codex and Claude adapters currently rely on internal crate APIs. A
path dependency would couple OnlineWorker to unstable Rust internals and make
routine upstream refactors compile-breaking.

The CLI JSON format is the stable integration boundary already intended for
automation. Treating ccusage as an executable sidecar isolates upstream code
and keeps the OnlineWorker adapter small.

## Repository Layout

Planned repository additions:

```text
.gitmodules
third_party/ccusage/                  Git submodule
scripts/update-ccusage.sh             deliberate update workflow
mac-app/src-tauri/binaries/
  ccusage-<target-triple>             generated, not committed
mac-app/src-tauri/third-party-licenses/
  ccusage-LICENSE                     staged during packaging
```

The submodule must be initialized by clone/bootstrap documentation and by CI
before builds that need usage integration.

## Runtime Architecture

### Usage registry boundary

The application exposes `list_usage_sources` from normalized usage-plugin
metadata. Each returned item includes plugin ID, source ID, label, description,
icon, order, and availability metadata.

`get_provider_usage_summary` is replaced by `get_usage_source_summary`. Its
response retains the current daily row fields, but the identity field becomes
`sourceId`; a temporary frontend compatibility alias is allowed only within the
TypeScript API adapter and is removed before the phase is complete. The request
is resolved through the usage plugin registry, then dispatched to the ccusage
sidecar.

The Codex and Claude `usage_hooks` are removed together with their handwritten
parsers. Desktop and bot consumers call the shared usage registry rather than a
provider-specific Python implementation. No React or shared command surface
knows provider log formats.

### Invocation

For a requested usage source and date range, the adapter runs the equivalent
of:

```text
ccusage <source> daily
  --since YYYYMMDD
  --until YYYYMMDD
  --timezone <system IANA timezone>
  --json
  --offline
  --no-cost
```

The executable is resolved in this order:

1. Explicit test/development override environment variable.
2. A `ccusage` executable beside the packaged `onlineworker-bot` executable.
3. The known source-build output under the initialized submodule.

Failure to resolve or execute ccusage returns an explicit provider usage error.
It must not fall back to the deleted handwritten parser.

### Performance and concurrency

Listing the source catalog never invokes ccusage. Only the selected Usage-page
source is queried. Menubar usage queries only sources associated with active
OnlineWorker Agent providers, and Telegram queries only the source associated
with the current Agent topic.

The Python runtime provides:

- single-flight execution keyed by `(plugin_id, source_id, start_date,
  end_date, timezone, ccusage_version)`;
- a 30-second successful-result TTL cache;
- no cache for failures;
- a process-wide concurrency limit of two ccusage child processes;
- a 30-second child timeout with termination and reap;
- explicit refresh that bypasses the TTL but still joins an equivalent
  in-flight request;
- cache-key invalidation when the resolved binary path, mtime, or reported
  ccusage version changes.

This bounds repeated UI, menubar, owner-bridge, and Telegram requests without
eagerly scanning every supported source.

### JSON normalization

The shared adapter validates the pinned ccusage focused daily JSON contract and
maps each daily row into `UsageSourceSummary`:

- `date` -> `date`
- `inputTokens` -> non-cached `inputTokens`
- `outputTokens` -> `outputTokens`
- `cacheCreationTokens` -> `cacheCreationTokens`
- `cacheReadTokens` -> `cacheReadTokens`
- `totalTokens` -> total processed tokens, including cached input as defined by
  the provider
- cost -> `None` while OnlineWorker invokes ccusage with `--no-cost`

Unknown extra ccusage fields are ignored. Missing required numeric fields,
invalid dates, non-zero exit codes, timeouts, and invalid JSON produce bounded
errors without partial fabricated totals. A valid empty report produces a
source-specific empty state rather than an error.

The pinned ccusage version provides the same daily row field names for focused
source reports. In particular, its Codex reporter already emits non-cached
`inputTokens` by subtracting cached input and emits cache reads as
`cacheReadTokens`. OnlineWorker must not subtract cache a second time. Contract
tests execute every declared focused source command and fail an upstream update
if this unified row shape changes.

## Timezone Semantics

Daily grouping uses the host system timezone by default, matching ccusage's
default behavior. OnlineWorker sends the resolved IANA timezone explicitly so
the UI, bot sidecar, tests, and packaged app use the same boundary.

The selected date range is interpreted in that timezone. The previous behavior
of slicing the first ten characters from a UTC timestamp is removed.

## UI Semantics

The Usage page keeps the date-range workflow but replaces the two-column
Codex/Claude switcher with a scalable source selector driven by
`list_usage_sources`.

All sources declared by the pinned ccusage plugin are displayed. The selector
must remain usable with roughly fifteen or more sources, so it uses a compact,
scrollable source rail or wrapping source grid rather than one equal-width
column per source.

For every source:

- Rename the input summary and table label to `Non-cached input` / `非缓存输入`.
- Add cache-read usage to the summary cards.
- Describe total tokens as processed tokens including cache.
- Keep cache creation as a separate table field where the provider reports it.
- Do not present local totals as authoritative server billing totals.

Agent provider associations may enrich a source's presentation, but they do not
control whether the source appears.

## Removal of Old Implementations

The implementation must remove, not deprecate, the provider-specific local
usage aggregators and hooks:

- Codex JSONL token parsing and usage bucket merging from the Codex storage
  runtime.
- Claude `message.usage` scanning, request/message deduplication, and daily
  aggregation from the Claude storage runtime.
- Codex and Claude provider descriptor `usage_hooks` wiring.
- Tests that assert the old handwritten algorithms.

The migration also removes or replaces every provider-bound usage entry point:

- `ProviderUsageHooks` from Python provider contracts;
- bundled provider `capabilities.usage` booleans as the discovery mechanism;
- `core.provider_session_bridge.get_provider_usage_summary`;
- owner bridge request type `usage_summary`;
- Rust `require_runtime_provider` gating for usage;
- frontend `visibleUsageProviders` and provider-only Usage tab discovery;
- menubar loops that treat every usage source as an Agent provider;
- direct Telegram `provider_id` usage lookup.

Codex and Claude manifests gain explicit usage-source associations. External
provider plugins that previously supplied `ProviderUsageHooks` migrate to a
usage plugin manifest/runtime; this breaking extension change is documented in
the provider and usage plugin development guides.

Session listing, preview, archive, and resume parsing remain in their provider
storage runtimes. Codex session scanning must stop computing or caching usage
buckets as a side effect.

No compatibility flag or hidden fallback may reactivate the old parsers. The
new usage plugin registry is the only application entry point for local usage
reports.

## Build and Packaging

`scripts/build.sh` gains a dedicated ccusage build step:

1. Verify the submodule is initialized at the pinned commit.
2. Resolve one explicit target triple from `ONLINEWORKER_TARGET_TRIPLE`, falling
   back to the Rust host only when no release target was requested. The same
   triple drives ccusage Cargo, sidecar naming, and Tauri build target.
3. Build ccusage with `cargo build --locked --target <triple>` and a checked-in
   deterministic `CCUSAGE_PRICING_JSON_PATH`. Because runtime always uses
   `--no-cost`, this snapshot may be the validated empty LiteLLM object, but the
   upstream build must accept it in compatibility tests.
4. Copy the binary to `mac-app/src-tauri/binaries/ccusage-<target-triple>`.
5. Stage the upstream MIT license into the application resources.
6. Let Tauri bundle `onlineworker-bot` and `ccusage` as external binaries.

Intel and Apple Silicon builds use the same target-triple naming rules already
used for `onlineworker-bot`. Intel build documentation, CI, and release scripts
set `ONLINEWORKER_TARGET_TRIPLE=x86_64-apple-darwin`; Apple Silicon uses
`aarch64-apple-darwin`. `bootstrap-sidecar.sh` creates test placeholders for
both declared external binaries, and packaging checks verify the Mach-O
architecture of both sidecars.

Clean builds may fetch locked Rust crates through Cargo, matching the existing
Tauri dependency model. They must not perform ccusage's independent mutable
LiteLLM pricing download. CI runs `cargo fetch --locked` followed by the same
build with the checked-in pricing input; an additional warmed-cache job verifies
`cargo build --locked --offline`.

Bootstrap and packaged-verification scripts must recognize both sidecars.
Installed-app verification compares the ccusage binary hash between the DMG and
`/Applications/OnlineWorker.app` just as it does for the bot sidecar.

## Update Workflow

`scripts/update-ccusage.sh <ref>` performs a controlled update:

1. Fetch upstream refs inside the submodule.
2. Checkout the requested tag or commit.
3. Build ccusage with the OnlineWorker build settings.
4. Synchronize the usage plugin source catalog from upstream
   `BUILT_IN_AGENT_NAMES` and OnlineWorker presentation metadata.
5. Verify every declared source exposes a focused daily report command.
6. Run adapter contract tests for every declared source.
7. Run Codex and Claude fixture parity tests against the newly built binary.
8. Print the old and new submodule commits, catalog diff, and test result.

The script does not commit or push. The submodule pointer changes only when a
maintainer reviews and commits it.

## Test Strategy

Implementation follows test-first development.

### Shared adapter tests

- Builds correct command arguments for every declared ccusage source.
- Resolves packaged and development binaries deterministically.
- Normalizes valid ccusage daily JSON.
- Rejects invalid JSON, missing fields, command failure, and timeout.
- Preserves non-cached input and cache-read fields without double counting.
- Never calls the old storage parser.

### Usage plugin tests

- Loads the bundled ccusage usage-plugin manifest in Rust and Python.
- Resolves safe local icons and rejects traversal or remote asset paths.
- Lists all sources declared by the pinned ccusage catalog.
- Keeps usage-only sources out of Agent provider, session, task, command, and
  process-management registries.
- Applies optional Agent provider associations without hiding unassociated
  sources.
- Detects stale source catalogs during a ccusage submodule update.

### Runtime cache tests

- Coalesces identical in-flight requests.
- Reuses successful results within the TTL.
- Explicit refresh bypasses cached results without duplicating an in-flight
  process.
- Does not cache failures or invalid JSON.
- Enforces the concurrency limit and terminates timed-out children.
- Invalidates cached results when binary identity/version changes.

### Upstream parity fixtures

- Codex replayed parent history in a `thread_spawn` subagent file.
- Codex forked/copied session history.
- Codex real subagent usage after replay history.
- Claude duplicate message/request records.
- Date grouping around the local midnight boundary.

For each fixture, OnlineWorker's normalized daily rows must equal the JSON rows
returned by the pinned ccusage binary.

### Regression suites

- Python provider and owner-bridge tests.
- Rust/Tauri tests for sidecar packaging and provider contracts.
- Frontend tests for labels and summary fields.
- Production frontend build.
- Packaged application smoke with both sidecars running/resolvable.

### Real-data comparison

As a read-only UAT step, run the packaged ccusage sidecar and OnlineWorker usage
command against the same local date range. The normalized daily token fields
must match exactly.

OpenAI's server dashboard is recorded as a separate comparison. Any remaining
difference is reported as server-vs-local scope rather than patched by changing
ccusage output.

## Failure Handling

- Missing submodule: fail the build with the exact initialization command.
- ccusage build failure: stop packaging before Tauri build.
- Missing packaged ccusage: show source usage unavailable; do not blank the
  rest of the application.
- ccusage timeout: terminate the child process and return a bounded error.
- Invalid upstream JSON: return a schema/normalization error with no totals.
- Unsupported source: reject the usage-plugin manifest or stale catalog during
  normalization/update verification.

## Security and Privacy

- ccusage runs locally and reads the same local provider history already read by
  OnlineWorker.
- Runtime invocation uses `--offline`; no usage content is uploaded by this
  integration.
- Arguments are passed as an argv array, not through a shell.
- Errors must not include transcript content or environment secrets.
- Support bundles may include ccusage version and exit status, but not raw
  ccusage JSON or session paths.

## Licensing

ccusage is MIT licensed. OnlineWorker will retain the upstream submodule's
license and bundle a copy in its third-party license resources. The update
workflow also generates a reviewed third-party notice from the pinned ccusage
`Cargo.lock` for statically linked Rust dependencies and fails on unapproved or
unknown licenses. Both the ccusage license and dependency notice are packaged.

No upstream source file is copied into OnlineWorker outside the submodule.
Unassociated sources use a generic icon; any later source-specific icon must
record its source and license in the usage plugin manifest and notice file.

## Rollback

Rollback is performed by reverting the integration commit and its submodule
pointer. The removed handwritten parsers are restored only by that Git revert;
there is no runtime fallback switch.

An upstream ccusage update can be rolled back independently by restoring the
previous submodule commit and rebuilding.

## Acceptance Criteria

- The Usage page lists every source supported by the pinned ccusage version.
- Codex, Claude, and every usage-only source query the bundled ccusage sidecar.
- Usage source discovery comes from the usage plugin registry, not a React or
  Rust hardcoded list.
- Desktop, one-shot bridge, menubar, and Telegram resolve through the same
  Python usage runtime and normalized contract.
- The old Codex and Claude usage aggregation code is absent.
- Same input fixtures and timezone produce the same daily token fields as the
  pinned ccusage binary.
- Real local Codex data for 2026-07-11 UTC no longer reports the known
  `693,470,470` replay-inflated total and matches pinned ccusage output.
- The UI labels non-cached input and cache reads separately.
- Usage-only sources never appear as executable Agent providers elsewhere in
  the application.
- Catalog listing does not invoke ccusage, and only selected/associated sources
  are queried under the documented single-flight and TTL policy.
- The installed app contains executable `onlineworker-bot` and `ccusage`
  sidecars plus the ccusage MIT license and dependency notice.
- Source tests, production build, and packaged-app smoke pass without requiring
  a global ccusage installation or runtime network access.
