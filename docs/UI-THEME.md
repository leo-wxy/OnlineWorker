# UI Theme Development Guide

OnlineWorker supports `System`, `Light`, and `Dark` preferences. `System` is the
first-run default and follows the macOS appearance. The preference is stored in
`localStorage` under `onlineworker.theme`; the resolved `light` or `dark` value
is written to `data-ow-theme` on the root element before React starts.

The main window is the only preference writer. Both the main window and the
menubar popover consume the shared runtime in `src/utils/theme.ts`, including
native theme changes and the `app:theme-changed` event. Do not put theme state
in `config.yaml`, a page component, or a second menubar-specific store.

## Semantic tokens

`mac-app/src/index.css` is the single source of truth. Light and Dark must
define the same roles:

| Role | Tokens |
| --- | --- |
| Canvas and shell | `--ow-bg`, `--ow-canvas`, `--ow-shell` |
| Surfaces | `--ow-sidebar`, `--ow-panel`, `--ow-panel-soft`, `--ow-panel-elevated`, `--ow-toolbar`, `--ow-input`, `--ow-code`, `--ow-glass-highlight` |
| Interaction surfaces | `--ow-hover`, `--ow-selected`, `--ow-disabled-surface` |
| Structure | `--ow-line`, `--ow-line-soft` |
| Text | `--ow-text`, `--ow-muted`, `--ow-subtle`, `--ow-disabled`, `--ow-inverse`, `--ow-on-accent` |
| Focus | `--ow-focus` |
| Accent | `--ow-blue`, `--ow-blue-soft`, `--ow-purple`, `--ow-purple-soft`, `--ow-primary-surface` |
| Status | `--ow-green`, `--ow-green-soft`, `--ow-amber`, `--ow-amber-soft`, `--ow-warning-text`, `--ow-red`, `--ow-red-soft`, `--ow-error-text` |
| Overlay and depth | `--ow-overlay`, `--ow-shadow-sm`, `--ow-shadow-md`, `--ow-shadow-lg` |
| Scroll and texture | `--ow-scrollbar`, `--ow-scrollbar-hover`, `--ow-pattern` |

Prefer an existing token or `.ow-*` surface class. Add a token only when a
semantic role is reused and genuinely missing; define it in both theme blocks
and add it to the contract test and this table in the same change. Do not add a
token for one screen or one component.

## Component rules

- Preserve layout, size, information hierarchy, and behavior when applying a
  theme. Theme work changes color, material, border, shadow, and focus only.
- Components consume semantic tokens. New TSX must not introduce theme colors
  such as `bg-white`, `text-slate-*`, `border-slate-*`, raw hex values, or raw
  `rgba(...)`. Provider brand artwork and `currentColor` icons are reviewed
  exceptions, not directory-wide exemptions.
- Cover normal, hover, focus-visible, selected, disabled, loading, empty,
  warning, and error states. Focus needs a visible ring, and status must also
  have text or an icon rather than relying on color alone.
- Use `--ow-on-accent` for text on solid accent colors, `--ow-inverse` for text
  on the primary gradient, and `--ow-text` for content on `--ow-code`.
- Keep native controls and keyboard order intact. Inputs need labels or
  accessible names; async status remains available to assistive technology.
- The menubar keeps a transparent outer window. Apply surface, border, and
  shadow tokens only to its inner rounded panel; do not add a theme selector or
  a separate visual language there.

## Motion and extension

Theme transitions are approximately 150 ms and limited to color, background,
border, shadow, fill, and stroke. Never use whole-window opacity or
`transition-all` for theme changes. `prefers-reduced-motion: reduce` disables
these transitions.

To add another theme, extend the root attribute resolution and provide the full
semantic token map. Do not add per-component theme branches, a ThemeProvider,
a theme dependency, or Tailwind dark-mode configuration.

## Validation

Run the focused contract before the normal frontend checks:

```bash
cd mac-app
node --test tests/theme.test.mjs tests/themeContract.test.mjs
node --test tests/*.test.mjs
./node_modules/.bin/tsc --noEmit
pnpm build
```

Then inspect the main window and menubar in System, Light, and Dark, including
interactive states and reduced motion. Installed-app validation is required for
packaged behavior and follows the repository's explicit-permission rule.
