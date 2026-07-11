# Phase 20 — UI Design Contract

## Surface

Extend `Settings → Maintenance` below attachment-cache maintenance. Do not add a sidebar item, modal-first flow, dashboard hero, or detached support page.

## Layout

- One standard `ow-page-frame` section with a compact title, description, last-run timestamp, and right-aligned primary `运行诊断` action.
- After a run, show a simple vertical list grouped by `正常`, `警告`, and `失败`; each row contains status icon/dot, label, summary, duration, and optional remediation.
- Keep details collapsed by default when the summary is sufficient; use a native button to reveal detail text.
- Footer actions: `复制摘要`, `导出支持包`, and, after export, `在 Finder 中显示`.
- On narrow widths, actions wrap below content; no horizontal scrolling.

## States

- Initial: explanation and Run button only.
- Running: button disabled with inline progress text; previous report remains visible but marked as previous.
- Partial: successful and failed checks render together; export remains available.
- Exporting: export action disabled; diagnostic run action remains disabled to prevent overlapping snapshots.
- Save cancelled: no error banner and no success state.
- Error: concise inline error without replacing attachment-cache maintenance or blanking the page.

## Visual Rules

- Reuse current typography, spacing, `ow-btn`, `ow-btn-primary`, borders, and semantic slate/emerald/amber/rose colors.
- No gradients, oversized radii, metric cards, pills for every row, decorative copy, or animations beyond existing color transitions.
- Status is never communicated by color alone; include text and an icon/shape.

## Copy

- Chinese first-class strings with matching English keys.
- Describe export as local and sanitized. Explicitly state that Session content and credentials are excluded.
- Do not imply automatic repair or remote support upload.

## Accessibility

- Buttons use native disabled state and visible labels.
- Result list uses semantic list markup and `aria-live="polite"` for completion/export messages.
- Expand/collapse controls use `aria-expanded`.

## Verification

- Frontend contract tests assert the existing Maintenance surface, result grouping, overlap guards, privacy copy, and export/reveal commands.
- Installed UAT covers healthy and partial reports, save cancellation, ZIP export, and Finder reveal.
