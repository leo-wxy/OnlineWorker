# OnlineWorker

## What This Is

OnlineWorker is a macOS AI coding workspace built around local CLI agents. The installed Mac app is the primary control surface for setup, sessions, commands, logs, and service lifecycle, while Telegram acts as the remote entry point for starting work, handling approvals, checking status, and receiving final replies.

This repository is a brownfield product codebase, not a greenfield prototype. The current planning baseline assumes the existing app and provider runtime already work, and upcoming work should refine product quality without breaking the installed-app workflow.

## Core Value

Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.

## Requirements

### Validated

- ✓ Installed macOS app controls setup, dashboard, sessions, commands, and logs — existing
- ✓ Telegram works as the remote task, approval, and final-reply channel — existing
- ✓ Builtin `codex` and `claude` providers are supported behind a shared provider registry/runtime boundary — existing
- ✓ App-side session browsing and message sending are available from the desktop UI — existing
- ✓ Tauri + PyInstaller packaging produces installable macOS artifacts — existing

### Active

- [ ] Improve the Mac app visual hierarchy and consistency across the primary workbench screens
- [ ] Make first-run and setup flows clearer without changing the underlying provider/runtime contract
- [ ] Improve session and command ergonomics for repeated day-to-day use
- [ ] Preserve packaged-app and release-path confidence while UI changes land

### Out of Scope

- Browser-hosted or SaaS control plane — product is explicitly installed-app-first
- New builtin providers beyond `codex` and `claude` — not the focus of the current milestone
- Windows or Linux desktop ports — current runtime and packaging target is macOS
- Replacing Telegram with a different remote interaction channel — existing workflow already depends on it

## Context

- The codebase is split across Python runtime orchestration, Rust/Tauri host commands, and a React frontend.
- Installed-app behavior matters more than source-only behavior; release confidence is tied to packaged-app validation.
- The repo already includes provider abstraction boundaries, session/event tests, packaging scripts, and tag-driven DMG release automation.
- Current user intent after public-repo preparation is to improve the visible UI quality of the desktop workbench rather than redesign the core product model.

## Constraints

- **Tech stack**: Preserve the current Python + Rust/Tauri + React split — it already matches the shipped product architecture.
- **Platform**: macOS installed-app behavior is the source of truth — UI work cannot be validated only in source mode.
- **Workflow compatibility**: Existing `App / Sessions + Telegram final reply` behavior must remain intact — this is the product's operating model.
- **Provider boundary**: UI improvements should not reintroduce provider-specific coupling into shared app surfaces.
- **Release path**: Tag-driven DMG packaging and startup/build sanity must stay working while UI changes are made.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Initialize planning as a brownfield project | The repository already ships working product code, packaging, and provider runtimes | ✓ Good |
| Use README + codebase map as project definition baseline | Current repo docs already state the product shape clearly enough for initialization | ✓ Good |
| Focus current active scope on UI refinement | The next requested work is “调整 UI 效果”, not core runtime replacement | — Pending |
| Keep installed-app-first framing | Public docs and architecture both center the packaged Mac app rather than browser hosting | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `$gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `$gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-10 after initialization*
