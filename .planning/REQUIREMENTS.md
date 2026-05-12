# Requirements: OnlineWorker

**Defined:** 2026-05-10
**Core Value:** Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.

## v1 Requirements

Requirements for the current brownfield improvement milestone. These focus on UI quality and workflow clarity without changing the product's core operating model.

### Visual System

- [x] **UI-01**: User can move between `Setup`, `Dashboard`, `Sessions`, and `Commands` without the app feeling visually inconsistent between screens.
- [x] **UI-02**: User can identify hierarchy and primary actions quickly because typography, spacing, and emphasis are consistent across major desktop surfaces.

### Provider Usage

- [x] **USG-01**: User can open a first-class `Usage` page from the main app navigation and inspect daily token consumption without manually opening provider-specific logs, databases, or session files.
- [x] **USG-02**: Provider usage data is exposed through provider/plugin-specific adapters so the shared `Usage` UI can switch between providers without embedding provider-specific parsing logic.

### Operations

- [ ] **OPS-01**: User can understand current service state and next recommended action from the `Dashboard` at a glance.

### Workspace Ergonomics

- [ ] **WRK-01**: User can scan session history and metadata efficiently in the desktop app during repeated daily use.
- [ ] **WRK-02**: User can find command and provider controls quickly because related controls use a consistent interaction model.

### Quality

- [ ] **QLT-01**: User can still install and launch the packaged app after UI changes without frontend regressions breaking startup.
- [ ] **QLT-02**: User can use key desktop views without clipped text, overlapping controls, or unstable layout at common window sizes.

## v2 Requirements

Deferred to future release work after the current UI refinement milestone.

### UX Extensions

- **UX-01**: User can customize more of the app appearance from first-class settings surfaces.
- **UX-02**: User can discover and configure external provider extensions from a richer in-app management experience.

### Platform Expansion

- **PLT-01**: User can use equivalent first-class desktop packaging flows beyond macOS.
- **PLT-02**: User can use richer release automation including signing/notarization without manual release intervention.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Browser-hosted control plane | Conflicts with the installed-app-first product model |
| New builtin provider families | Current milestone is about UI quality, not provider expansion |
| Replacing Telegram remote flow | Existing product value already depends on Telegram delivery/approvals |
| Cross-platform desktop porting | Expands scope far beyond the current UI refinement goal |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| UI-01 | Phase 1 | Completed (2026-05-10) |
| UI-02 | Phase 1 | Completed (2026-05-10) |
| USG-01 | Phase 2 | Completed (2026-05-12) |
| USG-02 | Phase 2 | Completed (2026-05-12) |
| OPS-01 | Phase 3 | Pending |
| WRK-01 | Phase 4 | Pending |
| WRK-02 | Phase 4 | Pending |
| QLT-01 | Phase 5 | Pending |
| QLT-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-05-10*
*Last updated: 2026-05-10 after initialization*
