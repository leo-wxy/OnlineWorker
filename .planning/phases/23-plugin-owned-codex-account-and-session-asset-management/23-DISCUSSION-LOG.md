# Phase 23: Plugin-Owned Codex Account and Session Asset Management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-17
**Phase:** 23-plugin-owned-codex-account-and-session-asset-management
**Areas discussed:** Account scope, account application, session assets, plugin entry, package compatibility, credential storage, UI alignment

---

## Account scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full Cockpit account operations | Quotas, plans, tags, groups, notes, gateway, pool, and automation | |
| Focused credential workflow | Import, export, account library selection, and manual application | ✓ |
| Import/export only without application | Store and transfer credentials but never project them to Codex | |

**User's choice:** Keep the account feature focused on account import/export and application; most Cockpit operations are unnecessary.
**Notes:** Earlier selections for full quota cards and organizational metadata were superseded by this explicit scope reduction. Gateway/relay behavior was specifically rejected.

## Account import and export

| Option | Description | Selected |
|--------|-------------|----------|
| Four add paths | OAuth, Token/JSON, API Key, and local import in one feature | superseded |
| Partial add paths | OAuth plus Token/JSON | ✓ |
| Local auth.json only | Minimal existing-login import | |

**User's choice:** Keep OAuth and Token/JSON as the only add paths, while retaining full single/batch credential export.
**Notes:** The later scope reduction removes dedicated API Key and local-file add actions. Historical credential shapes remain readable/exportable. Re-importing the same account updates it in place; OAuth keeps local callback plus manual fallback.

## Account application

| Option | Description | Selected |
|--------|-------------|----------|
| Manual independent application | Import does not switch; `应用` writes the selected account to effective CODEX_HOME | ✓ |
| Apply and restart app-server | Coordinate application with OnlineWorker managed runtime | |
| Import without application | Never write the selected account to Codex | |

**User's choice:** Manual application to the effective `CODEX_HOME`.
**Notes:** The user explicitly corrected the design: the account system has no relationship to app-server or any OnlineWorker runtime. OnlineWorker is only the feature carrier.

## Session assets

| Option | Description | Selected |
|--------|-------------|----------|
| Core asset management | Search/list, 30-day usage, import/export, trash/restore, visibility repair | ✓ |
| Full Cockpit surface | Core management plus copy-to-instance, sync, and multiple homes | |
| Transfer only | Import/export without browsing, trash, or repair | |

**User's choice:** Core asset management, with behavior consistent with current Cockpit Tools.
**Notes:** Copy-to-instance, cross-instance sync, and multiple Codex homes are excluded. The feature is independent of OnlineWorker's live Sessions and Usage pages.

## Plugin entry and isolation

| Option | Description | Selected |
|--------|-------------|----------|
| Dynamic `账号` sidebar entry | One generic entry, plugin selectors inside, visible only when capability exists | ✓ |
| Plugin center only | Open account plugins through a generic management page | |
| Separate window | OnlineWorker only launches an external plugin window | |

**User's choice:** Add an `账号` sidebar entry dynamically.
**Notes:** Keep one entry for Codex/Claude/Codemaker plugin selectors. Hide it when no account plugin is enabled. Isolate load failures per plugin with error/retry/diagnostics.

## Account package compatibility

| Option | Description | Selected |
|--------|-------------|----------|
| Exact current Cockpit compatibility | Bidirectional compatibility with the current Cockpit export shape | ✓ |
| Versioned plugin-native format | Import Cockpit best-effort but export an independent schema | |
| Plugin-only format | No Cockpit compatibility | |

**User's choice:** Use the current Cockpit export format as the compatibility baseline.
**Notes:** Preserve unknown fields on round trip and perform only local structural/identity validation during import.

## Credential storage

| Option | Description | Selected |
|--------|-------------|----------|
| Follow current Cockpit storage behavior | Plain summary index plus AES-256-GCM account details and local protected key | ✓ |
| macOS Keychain | Store all secret fields in Keychain | |
| Plain protected JSON | Store full records in user-only plaintext files | |

**User's choice:** Reference Cockpit's current storage behavior.
**Notes:** Current Cockpit was verified to use AES-256-GCM envelopes, a random 32-byte local key with `0600` permissions, atomic writes, and plaintext migration. Phase 23 independently implements the behavior in its own plugin data directory.

## UI alignment

| Option | Description | Selected |
|--------|-------------|----------|
| Flow and information-architecture alignment | Cockpit page hierarchy with OnlineWorker's visual system | ✓ |
| Pixel-level visual copy | Reproduce Cockpit styling closely | |
| Function-only alignment | Entirely independent page structure | |

**User's choice:** Align information structure and operation flow, not pixels.
**Notes:** Use one responsive account list with fixed desktop column rails, a two-tab add modal, and the reference single-page session layout. Use OnlineWorker theme, typography, accessibility, and responsive behavior.

## the agent's Discretion

- Exact minimal generic plugin-page loading/action contract.
- Internal encrypted-envelope field names and plugin data-directory names.
- Responsive spacing, empty/error copy, and test organization within the locked behavior.

## Deferred Ideas

- Claude and Codemaker account implementations.
- Quotas, tags, notes, groups, gateway/relay, account pool, automation, and model-provider management.
- Multi-instance session copy and synchronization.
