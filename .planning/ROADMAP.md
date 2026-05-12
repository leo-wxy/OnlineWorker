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
- [ ] **Phase 3: Dashboard Clarity** - Improve at-a-glance operational visibility on the dashboard
- [ ] **Phase 4: Workspace Ergonomics** - Refine session and command surfaces for repeated daily use
- [ ] **Phase 5: Consistency & Release Verification** - Close visual gaps across screens and verify packaged-app confidence

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

### Phase 3: Dashboard Clarity
**Goal**: Make the dashboard a dependable operational summary instead of a secondary landing surface.
**Depends on**: Phase 2
**Requirements**: [OPS-01]
**Success Criteria** (what must be TRUE):
  1. Service state, important next actions, and useful entry points are obvious at a glance.
  2. The dashboard supports quick orientation after app launch without forcing users into deeper screens first.
  3. Dashboard visual density stays workbench-oriented rather than drifting into marketing-style layout.
**Plans**: 2 plans

Plans:
- [ ] 03-01: Rework dashboard information hierarchy around operational status
- [ ] 03-02: Tighten dashboard actions and summary components for quicker scanning

### Phase 4: Workspace Ergonomics
**Goal**: Improve how users inspect sessions and commands during repeated day-to-day usage.
**Depends on**: Phase 3
**Requirements**: [WRK-01, WRK-02]
**Success Criteria** (what must be TRUE):
  1. Session history, metadata, and related status badges are easier to scan in the desktop app.
  2. Command and provider controls feel organized, discoverable, and visually aligned with the rest of the workbench.
  3. Workspace-heavy screens preserve efficiency for repeated expert use rather than adding decorative noise.
**Plans**: 3 plans

Plans:
- [ ] 04-01: Improve session browser information hierarchy and metadata presentation
- [ ] 04-02: Refine command registry and provider control ergonomics
- [ ] 04-03: Align workspace-heavy surfaces with the shared workbench baseline

### Phase 5: Consistency & Release Verification
**Goal**: Close remaining UI inconsistencies and prove that the refined interface still ships cleanly.
**Depends on**: Phase 4
**Requirements**: [QLT-01, QLT-02]
**Success Criteria** (what must be TRUE):
  1. Key desktop surfaces avoid overlap, clipping, or unstable layout at common window sizes.
  2. The packaged app still builds and launches after the UI refinement milestone.
  3. The final visual pass removes remaining obvious mismatches between primary product surfaces.
**Plans**: 2 plans

Plans:
- [ ] 05-01: Run cross-screen polish and layout regression pass
- [ ] 05-02: Verify packaged-app build and launch confidence after UI changes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. UI Foundation | 2/2 | Completed | 2026-05-10 |
| 2. Provider Usage Explorer | 2/2 | Completed | 2026-05-12 |
| 3. Dashboard Clarity | 0/2 | Not started | - |
| 4. Workspace Ergonomics | 0/3 | Not started | - |
| 5. Consistency & Release Verification | 0/2 | Not started | - |
