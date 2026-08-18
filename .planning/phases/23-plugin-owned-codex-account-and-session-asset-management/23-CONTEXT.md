# Phase 23: Plugin-Owned Codex Account and Session Asset Management - Context

**Gathered:** 2026-08-17
**Status:** Implemented; account worker/cache performance follow-up source and installed cache-hit path verified 2026-08-18

<domain>
## Phase Boundary

Phase 23 adds an independent account-management plugin surface carried by the OnlineWorker desktop shell. The shell discovers and mounts account-capable plugins; it does not own Codex account or session-asset business logic. The first implementation is the Codex plugin, with two self-contained surfaces: account credential import/export/application and offline Codex session-asset management.

The feature must remain usable when the OnlineWorker bot, Provider runtime, owner bridge, and Codex app-server are stopped. OnlineWorker is only the generic capability host.

</domain>

<decisions>
## Implementation Decisions

### Plugin ownership and host boundary
- **D-01:** OnlineWorker is only the generic feature carrier. The Codex plugin owns its UI, data model, storage, validation, import/export/application behavior, and session-asset operations.
- **D-02:** The feature must not depend on OnlineWorker Provider runtime state, owner bridge, Task Board, existing Sessions/Usage pages, notification flow, or Codex app-server lifecycle.
- **D-03:** Add a generic account-management plugin capability. At least one enabled plugin with this capability dynamically contributes a single `账号` sidebar entry; when no such plugin is enabled, the entry is hidden.
- **D-04:** The `账号` page presents one selector per account-capable plugin (`Codex`, later `Claude`/`Codemaker`). Each plugin supplies its own content and configuration; the host must not branch on provider IDs.
- **D-05:** A plugin load failure is isolated to that plugin selector and shows its own error, retry, and diagnostic state. Other account plugins remain usable.
- **D-06:** Phase 23 implements Codex only. Claude and Codemaker business implementations are deferred, but the host seam must permit them without adding provider-specific code later.
- **D-07:** The host may expose only generic system capabilities needed by plugins, such as mounting local assets, opening a browser, choosing files, saving files, and invoking a plugin-owned action. Action invocation uses one independent long-lived account-feature worker, not Provider runtime/app-server authority; timeout or crash clears that worker and the next request starts a new one without replaying the failed action. Those capabilities must not contain Codex account/session vocabulary.

### Codex account credential scope
- **D-08:** The account feature is a focused credential workflow: import into the plugin-owned account library, select an account, manually apply it, explicitly refresh the official Codex usage windows, and export it for backup or transfer. It is not a full account operations dashboard.
- **D-09:** Support four add paths in one modal: OAuth, `Token / JSON`, API Key, and local file import.
- **D-10:** OAuth uses the system browser with PKCE/state, automatic local callback capture when available, and manual callback URL input as fallback. Do not use an embedded login WebView.
- **D-11:** Import never auto-applies an account. The user explicitly clicks `应用`; application atomically projects the selected credentials to the current effective `CODEX_HOME` (`$CODEX_HOME` when set, otherwise `~/.codex`).
- **D-12:** Applying an account is only a credential-file operation. It does not inspect running tasks, stop or restart processes, reconnect adapters, or interact with app-server. Existing processes are outside this feature's responsibility; newly started Codex processes read the applied credentials.
- **D-13:** If credential projection fails, restore the previous credential file and keep the prior account marked current. Rollback is limited to files touched by the account plugin.
- **D-14:** Re-importing the same stable Codex identity updates the existing account in place rather than creating a duplicate, while preserving compatible unknown fields.
- **D-15:** On refresh, detect when the effective Codex credential file was changed externally. Match it to an existing library record when possible; otherwise show an external/unmanaged current account and require an explicit import decision.
- **D-16:** Support single-account and batch export with full credentials. Export is explicit, requires confirmation, uses a save dialog, and writes user-only file permissions where the destination filesystem permits it.

### Cockpit account-package compatibility
- **D-17:** Account imports and exports must be bidirectionally compatible with the current Cockpit Tools Codex account export format, not merely visually similar.
- **D-18:** Research and tests must pin the exact current Cockpit format at planning time. Additive unknown fields are accepted; an unsupported breaking format must fail with a clear version/shape error rather than silently losing data.
- **D-19:** Preserve unknown Cockpit fields through import, internal storage, and re-export so a supported round trip is as lossless as the JSON format permits.
- **D-20:** Import performs local structural validation of the file, required credential fields, and parseable account identity. It reports invalid records per item and does not automatically call a network endpoint, refresh a token, or log in.
- **D-21:** Cockpit Tools is a behavioral and data-format reference only. Its CC BY-NC-SA source must not be copied into OnlineWorker; implementation and tests must be independently written.

### Credential storage
- **D-22:** Follow Cockpit's current storage behavior independently: keep a plaintext non-secret account summary index, store each full account detail in an AES-256-GCM envelope, and keep a random 32-byte local storage key in the plugin data directory with user-only permissions.
- **D-23:** Use atomic writes for the index, key, encrypted account details, and applied Codex credential file. Legacy plaintext plugin records, if supported, are rewritten encrypted after successful read.
- **D-24:** Secrets must not enter logs, diagnostics, frontend persistence, or ordinary list responses. Frontend persistence is limited to a versioned allowlist of redacted account-card fields already present in ordinary list responses, so cached rows can render before background calibration. Full credentials may leave the backend boundary only for explicit import, export, or apply operations.
- **D-25:** Storage lives under the Codex plugin's own data directory. It must not use Cockpit's `~/.antigravity_cockpit` directory or treat Cockpit files as a live datastore.

### Codex session assets
- **D-26:** Session-asset management is an offline, plugin-owned capability over the current effective `CODEX_HOME`; it is not an extension or replacement of OnlineWorker's live Sessions page.
- **D-27:** The Phase 23 session scope is: expandable list, title search, local 30-day token/cost summary, ZIP import/export, conflict/integrity validation, reversible trash/restore, and visibility repair.
- **D-28:** For the selected operations, match the current Cockpit Tools behavior and archive layout. Research must extract exact manifest, checksum, conflict, trash, restore, and visibility-repair semantics before planning; plans may not guess them from screenshots.
- **D-29:** Session import must never silently overwrite an existing conflicting Session. Apply the exact current Cockpit conflict behavior and report each skipped/rejected item.
- **D-30:** Trash is reversible and manifest-backed. Phase 23 does not permanently delete Codex conversation history.
- **D-31:** Session browsing and 30-day usage are computed directly from Codex-owned local files/indexes. They must not consume OnlineWorker's message bus, existing Usage plugin projections, or replay/publish user-visible message events.
- **D-32:** Copy-to-instance, cross-instance sync, and multiple named Codex-home management are explicitly excluded.

### User interface
- **D-33:** Align with Cockpit's information architecture and operation flow, while using OnlineWorker's existing theme, typography, accessibility states, and responsive behavior. Do not make a pixel-level copy.
- **D-34:** The Codex account overview uses responsive account cards with identity, current-account state, import source, plan, and official quota windows when available. Cards expose only the scoped actions such as apply/reapply, explicit quota refresh, and export; do not add the excluded operational dashboard controls.
- **D-35:** The add-account modal uses four tabs: `OAuth`, `Token / JSON`, `API Key`, and `导入`.
- **D-36:** The session-asset page follows the reference single-page hierarchy: 30-day summary, search and scoped batch actions, then a default-collapsed list grouped by effective `cwd`/project; expanding a group reveals its individual conversations.
- **D-37:** Plugin UI must remain self-contained behind the generic account-plugin host. Shared React/Tauri code may render the shell and generic failure/loading states, but no Codex-specific labels, models, or commands belong there.

### Explicitly excluded from Phase 23
- **D-38:** Only an explicit user-triggered read of the official Codex usage endpoint is in scope. Do not implement background quota polling, subscription management beyond those returned usage windows, account tags, notes, groups, auto-rotation, API gateway/relay, API service keys, account pools, load balancing, model-provider management, wake-up tasks, application multi-open, or automatic account switching.
- **D-39:** Do not implement Claude or Codemaker account behavior in this phase.
- **D-40:** Do not modify or coordinate OnlineWorker live provider/session behavior as a side effect of account or asset operations.

### the agent's Discretion
- Choose the smallest generic plugin-page contract that supports runtime discovery, a contributed sidebar entry, per-plugin isolation, local asset loading, and generic action invocation without adding a framework for unrequested extension types.
- Choose exact plugin data-directory names, envelope field names, and internal storage schema, provided Cockpit import/export compatibility and the storage/security decisions above remain true.
- Choose test file organization and fixture construction. All credential and session mutation tests must use temporary directories and synthetic secrets; tests must never read or write the user's real `CODEX_HOME`.
- Choose precise responsive spacing, empty/loading/error copy, and accessible component details within the existing OnlineWorker design system.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and architectural boundaries
- `.planning/PROJECT.md` — installed-app-first product boundary, provider-neutral shared surfaces, and current Python/Rust/React split.
- `.planning/ROADMAP.md` — Phase 23 placement, dependency, and planning status.
- `AGENTS.md` — plugin ownership, message-chain, data-safety, verification, and packaging permission rules.

### Existing plugin and host seams
- `core/providers/contracts.py` — current Provider descriptor/capability vocabulary; evidence that no account-page capability exists yet.
- `core/providers/registry.py` — current builtin Provider discovery and normalization pattern.
- `plugins/providers/builtin/codex/plugin.yaml` — current Codex plugin manifest and the extension point Phase 23 must evolve without embedding business code in the host.
- `plugins/providers/builtin/codex/python/provider.py` — current Codex descriptor factory and plugin-owned hooks.
- `mac-app/src/App.tsx` — current static sidebar/page mounting; Phase 23 must add a generic plugin-contributed `账号` entry.
- `mac-app/src/components/ProviderSettingsPanel.tsx` — existing provider metadata/config rendering patterns; reuse only generic host behavior.

### Codex local files and offline facts
- `plugins/providers/builtin/codex/python/transport.py` — existing effective `CODEX_HOME` resolution precedent.
- `plugins/providers/builtin/codex/python/storage_runtime.py` — existing plugin-owned Codex session/index parsing utilities and hardcoded-path risks to avoid.
- `plugins/usage/builtin/ccusage/python/runtime.py` — existing local Codex usage parsing reference; Phase 23 must not depend on the OnlineWorker Usage projection.

### External behavioral reference
- `https://github.com/jlcodes99/cockpit-tools/tree/35963163813d7424b63cd6053874ce5fc7973d03` — current Cockpit Tools behavior and Codex account/session transfer-format reference inspected for this phase. Reference behavior and fixtures only; do not copy source because the repository is CC BY-NC-SA 4.0.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/providers/registry.py` and plugin manifests already demonstrate discovery by declared capability; the account host should reuse that discovery style without reusing Provider runtime state.
- `mac-app/src/App.tsx` already owns sidebar visibility and page mounting, so it is the natural generic host integration point.
- `plugins/providers/builtin/codex/python/transport.py` already centralizes one correct `CODEX_HOME` rule that the independent account/session feature can reuse as a pure path helper.
- `plugins/providers/builtin/codex/python/storage_runtime.py` already contains local Codex session parsing knowledge inside the Codex plugin boundary; pure parsing pieces may be reused or narrowed without importing live runtime state.

### Established Patterns
- Shared OnlineWorker surfaces consume plugin metadata and normalized facts; provider-private data parsing stays in the provider/plugin package.
- Frontend behavior tests use Node's builtin test runner, Python plugin behavior uses pytest, and Tauri host contracts use nearby Rust tests.
- Existing packaging stages builtin plugin resources, but the current plugin contract does not support a runtime-contributed full frontend page.

### Integration Points
- Add one minimal generic account-feature descriptor to plugin metadata/discovery.
- Add a generic host action transport and plugin-page asset mount that do not route through `core/provider_owner_bridge.py` or live Provider lifecycle state.
- Render one dynamic `账号` sidebar entry and a provider selector from discovered account-feature plugins.
- Keep all Codex account/session commands, schemas, storage, compatibility parsing, and page assets under the Codex plugin package.

</code_context>

<specifics>
## Specific Ideas

- The user selected Cockpit's account overview, four-tab add-account modal, and session-manager information hierarchy as product references, while explicitly rejecting the unrelated gateway/relay/account-pool surface.
- The account feature should feel like a focused credential transfer, application, and quota-status tool, not an administrative account-pool dashboard.
- Cockpit account-file compatibility targets the format present at commit `35963163813d7424b63cd6053874ce5fc7973d03`; planning research must capture exact fixtures and round-trip assertions from that version.
- OnlineWorker's visual system remains the presentation source of truth even when the plugin mirrors Cockpit's flow.

</specifics>

<deferred>
## Deferred Ideas

- Claude account plugin implementation.
- Codemaker account plugin implementation.
- Subscription management beyond the official usage windows, background/automatic quota refresh, tags, notes, groups, and automatic rotation.
- API gateways, relay services, account pools, load balancing, API-service management, model providers, wake-up tasks, and application multi-open.
- Session copy-to-instance, cross-instance synchronization, and multiple named Codex homes.

</deferred>

---

*Phase: 23-plugin-owned-codex-account-and-session-asset-management*
*Context gathered: 2026-08-17*
