---
phase: 19
slug: attention-center-and-session-interrupt-resume
status: approved
shadcn_initialized: false
preset: none
created: 2026-07-11
---

# Phase 19 — UI Design Contract

> Visual and interaction contract for the Task Board attention center and Session lifecycle controls.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | Existing Tailwind CSS + OnlineWorker `ow-*` utilities |
| Preset | Existing installed-app light surface |
| Component library | None; use native React/HTML controls |
| Icon library | Existing inline SVG icon pattern; no new dependency |
| Font | Existing macOS system stack from `mac-app/src/index.css` |

No new component library, icon package, font, gradient language, or global theme token is introduced in Phase 19.

---

## Information Architecture

### Desktop layout

```text
Task Board toolbar
┌──────────────────────────────┬────────────────────────────────┐
│ grouped agent rows           │ selected Session detail        │
│                              │                                │
│ 需要你                       │ title + provider/workspace     │
│ 正在运行                     │ reason/current activity        │
│ 最近结束                     │ recent canonical events        │
│                              │ available real actions         │
└──────────────────────────────┴────────────────────────────────┘
```

- Reuse the current Task Board Tab and application sidebar.
- The left pane is the primary navigation surface and uses compact rows, not cards.
- The right pane is contextual. It updates when a row is selected and never duplicates the full Session transcript.
- Initial selection: first actionable owned item; otherwise first running Session; otherwise first recent Session.
- Keep the existing global Task Board badge count sourced from `needs_attention` activities.

### Responsive layout

- At widths below the existing desktop split threshold, show the grouped list full width.
- Opening a row replaces the list with the detail view and provides a standard Back control.
- Do not stack the complete detail pane below every row.

---

## Group and Row Contract

### `需要你`

- Includes owned approvals, owned questions, unexpected failures, and provider-backed stalled/recovery states.
- Owned actionable rows appear before observational mirrored-only rows.
- Rows show: state icon, Session title, provider + workspace, concise reason, waiting time, and at most one primary quick action.
- Mirrored-only rows show `请在原终端处理` and no OnlineWorker decision control.

### `正在运行`

- Includes Sessions whose normalized provider activity says running and whose provider-active fact is not false.
- Rows show current activity preview and last update time.
- `中断` appears only when the selected concrete Session exposes owned interrupt capability and an active turn.

### `最近结束`

- Includes user-interrupted Sessions and recently completed managed Sessions already present in the Task Board projection.
- User-interrupted Sessions expose `继续`; ordinary completed rows expose `打开`.
- Limit the initial list to the existing board bound; no unbounded history or pagination is added in Phase 19.

---

## Detail Pane Contract

The selected row detail contains, in order:

1. Session title and normalized state.
2. Provider, workspace, Session identifier, ownership/control mode, and wait/update time.
3. Attention reason or current/recent activity preview.
4. Up to five recent canonical lifecycle events, newest first.
5. Available actions for the concrete item.

Action hierarchy:

- One high-emphasis action maximum (`允许`, `回答`, `恢复`, or `继续`).
- Secondary destructive approval action (`拒绝`) remains visible but is not visually louder than the primary action.
- `中断` is a neutral bordered action, not a red destructive CTA.
- `打开 Session` is always the low-emphasis navigation action when a real Session target exists.
- Unsupported commands are omitted; the detail text explains the concrete provider/control limitation.

---

## Interaction States

| State | Presentation | Exit condition |
|-------|--------------|----------------|
| Idle | Real normalized provider state | Provider event or user action |
| Replying | `正在提交…`; related controls disabled | Authoritative approval/question response |
| Interrupting | `正在中断…`; interrupt disabled | Aborted/cancelled terminal result or explicit error |
| Recovering | `正在恢复…`; recovery disabled | Fresh provider-active/activity evidence or explicit error |
| Opening Continue | Navigate to same Session and focus composer | Sessions surface mounted/focused |
| Error | Inline action error in detail pane | Next attempt or selected-row change |

- Optimistic interaction state is transient UI state only; it must never overwrite provider Session truth.
- No generated prompt is sent by `继续`.
- No last-message replay occurs during recovery.
- Resolved pending rows leave `需要你` only after authoritative confirmation.

---

## Spacing Scale

Declared values use the existing Tailwind 4px scale:

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon/text micro-gap |
| sm | 8px | Inline actions, compact metadata |
| md | 12px | Row horizontal/vertical padding |
| lg | 16px | Pane padding, toolbar spacing |
| xl | 24px | Major detail sections only |

Exceptions: 1px borders and the existing 3px active navigation indicator.

---

## Typography

| Role | Size | Weight | Line Height |
|------|------|--------|-------------|
| Body | 14px | 400 | 1.45 |
| Metadata | 12px | 500 | 1.4 |
| Row title | 14px | 700 | 1.4 |
| Section label | 13px | 700 | 1.4 |
| Page title | 16px | 700 | 1.35 |

- Do not use uppercase eyebrow labels or expanded tracking.
- Keep Session titles to two lines maximum; metadata and previews truncate safely.

---

## Color

| Role | Value | Usage |
|------|-------|-------|
| Dominant | `var(--ow-panel)` | Main Task Board surface |
| Secondary | `var(--ow-panel-soft)` | Selected row and detail subdivisions |
| Structure | `var(--ow-line-soft)` | Row and pane separators |
| Text | `var(--ow-text)` | Primary labels and content |
| Muted | `var(--ow-muted)` | Provider/workspace/timestamps |
| Selection/focus | `var(--ow-blue)` / `var(--ow-blue-soft)` | Selected row, keyboard focus, primary owned action |
| Running | `var(--ow-green)` | Small running state mark only |
| Waiting/recovery | `var(--ow-amber)` | Small waiting/stalled state mark only |
| Failure | `var(--ow-red)` | Failure state and inline error only |

Accent is reserved for selected/focused elements and the one primary owned action. Large colored cards, colored shadows, gradients, and provider-colored surfaces are prohibited.

---

## Copywriting Contract

| Element | Copy |
|---------|------|
| Group 1 | `需要你` |
| Group 2 | `正在运行` |
| Group 3 | `最近结束` |
| Interrupt | `中断` → `正在中断…` |
| Continue | `继续` |
| Recovery | `恢复` → `正在恢复…` |
| Mirrored-only | `请在原终端处理` |
| No attention items | `当前没有需要你处理的 Session。` |
| No running items | `当前没有正在运行的 Session。` |
| No recent items | `当前没有最近结束的 Session。` |
| Interrupt unavailable | `当前 Session 没有可中断的活跃任务。` |
| Control unavailable | `此 Session 由外部客户端控制，请在原客户端处理。` |
| Interrupt failure | `中断失败：{provider reason}` |
| Recovery failure | `恢复失败：{provider reason}` |

Copy rules:

- Name the real object (`Session`, Provider, original client) and the recovery path.
- Do not use vague `操作失败`, celebratory copy, or decorative dashboard descriptions.
- Do not confirm success before provider evidence arrives.

---

## Accessibility and Keyboard

- Group headings use semantic headings and expose item counts as text.
- Each row is a real button or link with a visible selected state and keyboard focus.
- Inline action buttons stop row navigation and keep explicit accessible names.
- Status is never color-only: icon/state text accompanies every colored mark.
- When an action changes to pending or error, announce it through an `aria-live` region in the detail pane.
- Preserve native tab order: group list first, selected detail actions second.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | None | Not applicable |
| Third-party registry | None | Not applicable |

No registry content or new frontend dependency is allowed for this phase.

---

## Checker Sign-Off

- [x] Dimension 1 Copywriting: PASS — every state/action has concrete product copy and a recovery path.
- [x] Dimension 2 Visuals: PASS — selected B+A hierarchy, compact rows, detail structure, responsive behavior, and interaction states are explicit.
- [x] Dimension 3 Color: PASS — existing tokens only; accents are narrowly assigned and color is not the only status signal.
- [x] Dimension 4 Typography: PASS — sizes, weights, line heights, truncation, and prohibited treatments are explicit.
- [x] Dimension 5 Spacing: PASS — 4px-based scale with named usage and only structural exceptions.
- [x] Dimension 6 Registry Safety: PASS — no registry or new component dependency.

**Approval:** approved 2026-07-11
