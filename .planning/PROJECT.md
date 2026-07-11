# OnlineWorker

## What This Is

OnlineWorker is a macOS AI coding workspace built around local CLI agents. The installed Mac app is the primary control surface for setup, sessions, commands, logs, and service lifecycle, while Telegram acts as the current remote entry point for starting work, handling approvals, checking status, and receiving final replies.

This repository is a brownfield product codebase. The archived v1.2.1 milestone improved the visible workbench, provider usage exploration, attachment handling, Claude safe resume behavior, and provider-session error visibility without changing the installed-app-first product model.

## Core Value

Developers can reliably control local AI coding CLI workflows from an installed Mac app while receiving timely remote notifications and final results through supported notification channels.

## Current State

- Latest archived milestone: `v1.2.1`
- Release tag: `1.7.4`
- Active milestone: General AI Capability and Session Operations
- Active roadmap phase: Phase 19 — Attention Center And Session Interrupt/Resume

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
- ✓ Provider-private session/workspace parsing stays behind provider/plugin boundaries, while shared App surfaces consume normalized provider facts — Phase 17
- ✓ App and Telegram new-session entry points share a real provider-backed creation/first-message core with no visible local draft session — Phase 18

### Active

- [ ] Add a focused pending-action center for actionable approval, question, failure, and stalled-session states.
- [ ] Add provider-owned Session interrupt/resume/recovery controls that operate on real provider sessions and fail clearly when unsupported.

### Out of Scope

- Browser-hosted or SaaS control plane — product is explicitly installed-app-first
- New builtin providers beyond `codex` and `claude` — external providers should use the public plugin/overlay boundary
- Windows or Linux desktop ports — current runtime and packaging target is macOS
- Replacing Telegram as an input channel in this phase — current work is notification delivery abstraction, not full remote interaction replacement
- Global search in Phase 19 — the user explicitly excluded it; Phase 19 stays focused on pending actions and Session lifecycle control

## Context

- The codebase is split across Python runtime orchestration, Rust/Tauri host commands, and a React frontend.
- Installed-app behavior matters more than source-only behavior; release confidence is tied to packaged-app validation.
- The repo includes provider abstraction boundaries, session/event tests, packaging scripts, plugin manifests, and tag-driven DMG release automation.
- v1.2.1 milestone artifacts are archived under `.planning/milestones/`.
- The current milestone resolved the practical limitation that notifications were Telegram-only by adding a notification plugin boundary with Telegram as the first builtin channel.

## Constraints

- **Tech stack**: Preserve the current Python + Rust/Tauri + React split.
- **Platform**: macOS installed-app behavior is the source of truth.
- **Workflow compatibility**: Existing `App / Sessions + Telegram final reply` behavior must remain intact.
- **Provider boundary**: Shared app surfaces should not reintroduce provider-specific coupling.
- **Notification boundary**: New notification delivery should avoid spreading app-specific conditionals through shared runtime code.
- **Release path**: Tag-driven DMG packaging and startup/build sanity must stay working.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Initialize planning as a brownfield project | The repository already ships working product code, packaging, and provider runtimes | Validated |
| Use README + codebase map as project definition baseline | Current repo docs already state the product shape clearly enough for initialization | Validated |
| Keep installed-app-first framing | Public docs and architecture both center the packaged Mac app rather than browser hosting | Validated |
| Keep provider-specific behavior behind plugin/runtime boundaries | External provider support should not leak private provider concepts into shared app surfaces | Validated |
| Treat notification delivery as a plugin boundary | Telegram is currently the only builtin notification plugin, but future apps such as WeChat should not require rewriting shared send/status logic | Validated |
| Share only the provider-backed new-session core | App keeps pending UX and Telegram keeps topic binding/rollback while both reuse validation, materialization, and first-message send | Validated in Phase 18 |
| Keep Phase 19 focused on pending actions and Session lifecycle | Global search has low product value here and would dilute the next operational slice | Accepted |

## Evolution

- 2026-05-10: Planning initialized for a brownfield OnlineWorker milestone.
- 2026-05-23: v1.2.1 milestone archived after completing phases 1-5 and publishing tag `1.2.1`.
- 2026-05-23: Phase 6 added for notification channel abstraction.
- 2026-05-25: Phase 6 completed with notification plugin routing, Telegram builtin channel, configuration UI, local setup guide assets, plugin development docs, and installed-app validation.
- 2026-07-11: Reliability follow-up restored the full Python/Rust/frontend source regression gates and corrected menubar usage/active-session semantics.
- 2026-07-11: Phase 17 and Phase 18 closed after canonical UAT/verification, full source gates, version `1.7.4` package/install/relaunch checks, and installed App provider-session materialization. Real Telegram UAT was explicitly waived and is not claimed as passed.
- 2026-07-11: Phase 19 added for the pending-action center and Session interrupt/resume/recovery; global search is explicitly out of scope.

---
*Last updated: 2026-07-11 after Phase 18 closure*
