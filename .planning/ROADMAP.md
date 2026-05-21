# Roadmap: OnlineWorker

## Overview

This roadmap treats OnlineWorker as a brownfield macOS desktop product with an existing runtime core. The next milestone is not about inventing the product from scratch; it is about making the visible workbench feel more coherent, more readable, and more dependable without regressing the installed-app workflow, provider boundaries, or release path.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: UI Foundation** - Establish a consistent visual system and hierarchy baseline for the desktop workbench
- [x] **Phase 2: Provider Usage Explorer** - Add a first-class Usage menu for daily provider consumption while keeping statistics behind provider/plugin boundaries
- [x] **Phase 3: File and Image Support** - Add first-class file and image attachment support plus Settings Maintenance cache cleanup; packaged app and live attachment smokes verified
- [ ] **Phase 4: Claude Session Ownership and Safe Resume** - Allow TG/App to continue existing Claude sessions without stealing externally active terminal Claude work

## Phase Details

### Phase 1: UI Foundation
**Goal**: Define and apply a stable visual baseline so the desktop app feels like one coherent workbench instead of loosely related screens.
**Depends on**: Nothing (first phase)
**Requirements**: [UI-01, UI-02]
**Success Criteria** (what must be TRUE):
  1. Primary screens share a visibly consistent page structure, spacing rhythm, and action emphasis.
  2. Navigation, headings, and section framing feel coherent when moving between `Dashboard`, `Setup`, `Sessions`, and `Commands`.
  3. A clear set of reusable UI rules or primitives exists for follow-on phases to apply instead of re-styling screens ad hoc.
**Plans**: 2 plans

Plans:
- [x] 01-01: Audit current desktop UI and define the shared workbench visual baseline
- [x] 01-02: Apply the baseline to the highest-traffic shared layout surfaces

### Phase 2: Provider Usage Explorer
**Goal**: Add a first-class `Usage` page to the desktop app so users can inspect daily provider consumption with a `Codex / Claude` switcher while keeping provider-specific parsing and aggregation behind provider/plugin adapters.
**Depends on**: Phase 1
**Requirements**: [USG-01, USG-02]
**Success Criteria** (what must be TRUE):
  1. User can open a dedicated `Usage` tab from the primary app navigation and inspect recent provider usage without manually opening provider-specific logs, databases, or raw session files.
  2. The `Usage` surface supports at least `Codex / Claude` switching with a layout and interaction model aligned to the existing `Sessions` workflow, including visible loading and date-window feedback.
  3. Shared desktop surfaces obtain usage data through provider/plugin adapters rather than embedding provider-specific parsing in React components.
**Plans**: 2 plans

Plans:
- [x] 02-01: Define a provider usage summary contract and implement local daily usage readers for builtin providers
- [x] 02-02: Add a dedicated Usage tab with provider switching, fallback states, and shell validation

### Phase 3: File and Image Support
**Goal**: Add first-class file and image attachment support so Telegram and the desktop app can accept, route, and surface attachments without breaking the existing text-first workflow.
**Depends on**: Phase 2
**Requirements**: [ATT-01, ATT-02]
**Success Criteria** (what must be TRUE):
  1. Users can attach files and images through the supported app surfaces without needing unsupported workarounds.
  2. Attachments are routed through the existing Telegram and provider/plugin workflow boundaries rather than bypassing them with ad hoc handling.
  3. The packaged app still builds and launches after attachment support is introduced.
  4. Users can clear accumulated local attachment cache from the Settings `Maintenance` sub tab without using a Telegram command.
**Plans**: 2 plans

Plans:
- [x] 03-01: Upgrade the shared message contract and wire Telegram attachments into provider runtimes
- [x] 03-02: Add desktop attachment send support and validate the packaged app flow

Latest verification:
- Source/runtime attachment routing tests passed on 2026-05-21: `68 passed in 4.75s`.
- Related handler/events/Claude attachment regression tests passed on 2026-05-21: `80 passed in 5.37s`.
- Attachment cache command test passed on 2026-05-21: `2 passed`.
- Desktop app shell test passed after Settings `Maintenance` cache cleanup wiring: `5 passed`.
- Installed-app Settings `Maintenance` cache smoke passed on 2026-05-21 14:44 +0800: UI cleared `2.2 MB` / `6` files, both cache directories remained present with `0` files and `0B`, and config/env/state/log files remained present.
- `cd mac-app && npm run build` completed successfully.
- Final `bash build.sh` completed successfully and produced `OnlineWorker_1.1.0_aarch64.dmg` with mtime `2026-05-21 14:38:28 +0800` and sha256 `94fbb7abce3f694178f1d91c1ebad9f574df91d172372ef9e405afb7fd24a403`.
- `/Applications/OnlineWorker.app` was replaced and restarted from the final package at `2026-05-21 14:40:03 +0800`; installed version is `1.1.0`.
- User-confirmed live smoke passed on 2026-05-21: fresh Telegram attachment send no longer hits `Separator is not found`, and installed Session Browser desktop attachment send reaches the provider path.

Remaining Phase 3 verification:
- None. Phase 3 is closed.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. UI Foundation | 2/2 | Completed | 2026-05-10 |
| 2. Provider Usage Explorer | 2/2 | Completed | 2026-05-12 |
| 3. File and Image Support | 2/2 | Completed | 2026-05-21 |

### Phase 4: Claude Session Ownership and Safe Resume

**Goal:** Make Claude session sending explicit and safe: existing Claude sessions remain writable from TG/App, but OnlineWorker must not silently fork them or race an externally active terminal Claude process.
**Requirements**: [CLAUDE-01, CLAUDE-02]
**Depends on:** Phase 3
**Success Criteria** (what must be TRUE):
  1. TG/App can continue an existing Claude session by resuming the original session id; imported/history sessions are not silently remapped into new app-owned sessions.
  2. OnlineWorker refuses to inject a message into a Claude session that appears externally busy, and tells the user to wait or explicitly fork rather than stealing the terminal task.
  3. Concurrent sends to the same Claude session are serialized through the provider runtime so TG/App do not launch competing `claude --resume` processes.
  4. The desktop Session Browser sends Claude messages through the provider owner path instead of bypassing the bot/provider runtime with an independent Tauri Claude send path.
**Plans:** 1 plan

Plans:
- [ ] 04-01: Align Claude existing-session resume ownership across TG, provider owner bridge, and Session Browser
