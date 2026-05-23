# OnlineWorker

## What This Is

OnlineWorker is a macOS AI coding workspace built around local CLI agents. The installed Mac app is the primary control surface for setup, sessions, commands, logs, and service lifecycle, while Telegram acts as the remote entry point for starting work, handling approvals, checking status, and receiving final replies.

This repository is a brownfield product codebase. The archived v1.2.1 milestone improved the visible workbench, provider usage exploration, attachment handling, Claude safe resume behavior, and provider-session error visibility without changing the installed-app-first product model.

## Core Value

Developers can reliably control local AI coding CLI workflows from an installed Mac app while still receiving remote final results through Telegram.

## Current State

- Latest archived milestone: `v1.2.1`
- Release tag: `1.2.1`
- Active milestone: not started
- Active roadmap phases: none

## Requirements

### Validated

- ✓ Installed macOS app controls setup, dashboard, sessions, commands, and logs — existing
- ✓ Telegram works as the remote task, approval, and final-reply channel — existing
- ✓ Builtin `codex` and `claude` providers are supported behind a shared provider registry/runtime boundary — existing
- ✓ App-side session browsing and message sending are available from the desktop UI — existing
- ✓ Tauri + PyInstaller packaging produces installable macOS artifacts — existing
- ✓ Primary desktop workbench screens share a stable shell baseline with collapsible navigation — v1.2.1 Phase 1
- ✓ A first-class `Usage` page exposes daily `Codex / Claude` consumption through provider-specific adapters — v1.2.1 Phase 2
- ✓ File and image attachments work across Telegram and desktop workflows while staying inside provider/plugin routing boundaries — v1.2.1 Phase 3
- ✓ Claude existing-session sends are explicit and safe, without silent normal-send fork/remap or externally busy session stealing — v1.2.1 Phase 4
- ✓ Provider asynchronous failures can surface as visible Session Browser error turns through provider-neutral read normalization — v1.2.1 Phase 5

### Active

No active milestone requirements are currently defined.

### Out of Scope

- Browser-hosted or SaaS control plane — product is explicitly installed-app-first
- New builtin providers beyond `codex` and `claude` — external providers should use the public plugin/overlay boundary
- Windows or Linux desktop ports — current runtime and packaging target is macOS
- Replacing Telegram with a different remote interaction channel — existing workflow already depends on Telegram delivery/approvals

## Context

- The codebase is split across Python runtime orchestration, Rust/Tauri host commands, and a React frontend.
- Installed-app behavior matters more than source-only behavior; release confidence is tied to packaged-app validation.
- The repo includes provider abstraction boundaries, session/event tests, packaging scripts, plugin manifests, and tag-driven DMG release automation.
- v1.2.1 milestone artifacts are archived under `.planning/milestones/`.

## Constraints

- **Tech stack**: Preserve the current Python + Rust/Tauri + React split.
- **Platform**: macOS installed-app behavior is the source of truth.
- **Workflow compatibility**: Existing `App / Sessions + Telegram final reply` behavior must remain intact.
- **Provider boundary**: Shared app surfaces should not reintroduce provider-specific coupling.
- **Release path**: Tag-driven DMG packaging and startup/build sanity must stay working.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Initialize planning as a brownfield project | The repository already ships working product code, packaging, and provider runtimes | Validated |
| Use README + codebase map as project definition baseline | Current repo docs already state the product shape clearly enough for initialization | Validated |
| Keep installed-app-first framing | Public docs and architecture both center the packaged Mac app rather than browser hosting | Validated |
| Keep provider-specific behavior behind plugin/runtime boundaries | External provider support should not leak private provider concepts into shared app surfaces | Validated |

## Evolution

- 2026-05-10: Planning initialized for a brownfield OnlineWorker milestone.
- 2026-05-23: v1.2.1 milestone archived after completing phases 1-5 and publishing tag `1.2.1`.
