# Codex Hook 操作引导浮层 Design QA

**Comparison target**

- Source visual truth: `/tmp/onlineworker-hook-guide-preview/public/source-copy.png`
- Implementation screenshot: `/tmp/onlineworker-hook-guide-implementation-final-v2.png`
- Viewport: `1179 x 1334` CSS px, device pixel ratio `1`
- Pixel dimensions: source `1179 x 1334`; implementation `1179 x 1334`
- Density normalization: no scaling or density conversion was required
- State: Dashboard provider card reports Codex Hook trust review required and the action guide dialog is open

**Full-view comparison evidence**

- The source and implementation were rendered side by side at identical dimensions.
- Dialog position, width, backdrop blur, hierarchy, steps, command row, note block, and footer proportions match the selected direction.
- The surrounding Dashboard remains visible enough to preserve context while the dialog clearly owns focus.

**Focused region comparison evidence**

- The dialog region was inspected separately because its step rhythm, command affordance, note wrapping, and footer order are the fidelity-critical details.
- Copy, close, primary, secondary, backdrop-click, and Escape interactions were exercised; no browser console warnings or errors were reported.

**Findings**

- No actionable P0, P1, or P2 findings remain.
- [P3] The implementation uses the localized existing close button treatment instead of the mock's icon-only close control. This preserves the current component vocabulary and an explicit accessible label.
- [P3] The note contains one additional sentence explaining automatic verification after the first real Hook event. This is intentional product behavior rather than visual drift.

**Comparison history**

- First comparison: [P2] footer actions were reversed relative to the selected mock.
- Fix: placed the primary action before the secondary action in the reusable dialog footer.
- Post-fix evidence: the second side-by-side comparison shows the blue primary action on the left and the secondary action on the right, with matching spacing and alignment.

**Implementation checklist**

- Reusable action guide dialog implemented.
- Provider warning row opens the guide without changing provider-specific card layout.
- Copy, dismiss, recheck, backdrop, and Escape interactions verified.
- Responsive source build and focused backend regressions verified.

**Follow-up polish**

- None required for acceptance.

final result: passed

# Codex 账号卡片改版 Design QA

**Comparison target**

- Source visual truth: the user-provided account-card reference image (local path omitted).
- Implementation screenshot: `/tmp/onlineworker-account-card-final-wide.jpg`.
- Responsive screenshot: `/tmp/onlineworker-account-card-final-narrow.jpg`.
- Focused comparison: `/tmp/onlineworker-account-card-comparison-final.jpg`.
- Desktop viewport: `1493 x 768` CSS px; narrow viewport: `620 x 768` CSS px; device pixel ratio `1`.
- Source pixels: `784 x 846`, normalized from `2x` to `392 x 423`; implementation card crop: `416 x 463`, normalized to `392 x 436` for the focused comparison.
- State: synthetic current `PRO 20X` account with two quota windows plus one unapplied account.

**Full-view comparison evidence**

- The account library now uses fixed-width responsive cards rather than full-width rows.
- Desktop renders multiple cards from left to right; the narrow viewport collapses to one card without horizontal overflow.
- Current state, plan, authentication, application state, quota hierarchy and actions remain visible above the fold at desktop size.

**Focused region comparison evidence**

- The source and implementation card were normalized and combined in one comparison image.
- Typography keeps the existing OnlineWorker system font and weight hierarchy; spacing, blue current-account outline, green/amber state colors and rounded surfaces follow the selected reference direction.
- No raster or decorative image assets were required; all visible content is native account UI.

**Findings**

- No actionable P0, P1 or P2 findings remain.
- [P3] Reference-only Team Name, user ID, validity, note, reset and gateway actions remain absent because OnlineWorker does not expose those account fields or features.
- [P3] Action controls retain readable text labels instead of copying the reference's icon-only footer, preserving the app's current accessibility and control vocabulary.

**Comparison history**

- First card pass was visually too plain; authentication/application metadata, quota grouping, semantic progress colors and contained footer actions were added.
- The metadata grid was initially indented under the checkbox/content column while the quota block used full card width.
- Fix: moved the metadata grid to the card root. Post-fix browser geometry reports identical edges: `metaLeft/quotaLeft = 206.5` and `metaRight/quotaRight = 584.5`.

**Interaction evidence**

- Selecting an account updates the toolbar to `已选择 1 项` and enables `导出选中`; unselecting restores the default state.
- Browser console error count after the final reload: `0`.
- The focused account regression suite passes `7/7`.

**Follow-up polish**

- None required for the current scope.

final result: passed

# Phase 23 Codex 账号与会话资产 Design QA

**Comparison target**

- Account reference: the user-provided account reference image (local path omitted)
- Account implementation: the captured OnlineWorker account view (local path omitted)
- Session reference: the user-provided session reference image (local path omitted)
- Session implementation: the captured OnlineWorker session view (local path omitted)
- Collapsed sidebar: the captured collapsed-sidebar view (local path omitted)
- Short-window collapsed sidebar: the captured short-window sidebar view (local path omitted)
- Viewport: `1493 x 768` for both reference and implementation states.
- Combined comparisons: `/tmp/phase23-account-final-comparison.jpg`, `/tmp/phase23-session-final-comparison.jpg`.

**Findings and fixes**

- The first packaged UI was rejected: one oversized account card left most of the page empty, action hierarchy was weak, export only appeared disabled, and the collapsed sidebar showed oversized white blocks plus a heavy scrollbar.
- The account view now uses one compact selectable row with identity/current/plan, quota, explicit reapply, refresh and export actions. Reference gateway, API service, account pool, tag, note, rotation and multi-open surfaces remain intentionally absent.
- Export now opens the native save panel with `codex-accounts.json`; cancelling returns to the unchanged one-account list instead of clearing it.
- Reapply, visibility repair and trash use a plugin-owned accessible confirmation dialog instead of an unreliable browser confirm.
- The session view follows the reference hierarchy: 30-day local summary, search/filter, scoped actions, default-collapsed `cwd`/project rows, then conversation rows on expansion.
- The collapsed sidebar removes decorative outer cards, uses 40 px controls, hides only the scrollbar chrome, and keeps the middle rail scrollable while the locale control stays fixed at the bottom.
- No actionable P0, P1 or P2 visual findings remain in the compared desktop state.

**Interaction evidence**

- Mounted-DMG checks exercised the sidebar collapse/expand flow, independent short-window nav scrolling, account/session tabs, native export save panel and cancel, reapply confirmation and project-group disclosure.
- The packaged account page rendered account status and quota, with `重新应用`/`刷新额度`/`导出` actions enabled; personal account values are omitted.
- The packaged session page rendered project groups and conversations; expanding a project rendered its conversation rows. Private workspace names and account-specific counts are omitted.
- Real OAuth, quota network refresh, apply/reapply confirmation, file write, trash, restore and visibility repair were not executed against the user's data.

final result: passed

# Phase 23 会话工程卡片与选择弹窗 Design QA

**Comparison target**

- Source visual truth: `.planning/sketches/003-account-session-assets/index.html`, Variant C `卡片流 + 选择弹窗`.
- Implementation captures: `/tmp/onlineworker-session-assets-loaded.png` and `/tmp/onlineworker-session-picker.png` from the installed `/Applications/OnlineWorker.app`.
- Comparison captures: `/tmp/onlineworker-session-assets-comparison.jpg` and `/tmp/onlineworker-session-picker-comparison.jpg`.
- Viewport: desktop `1493 x 768` CSS px, device pixel ratio `1`.
- State: populated project cards and a project-specific conversation picker; private workspace names and account-specific counts are omitted.

**Packaged verification completed**

- Project cards retain the existing `cwd` grouping and session IDs from the plugin backend.
- Card actions share one bottom-aligned `选择会话` position.
- Native dialog supports search, visible-result select-all, individual selection, cancel without commit, and scoped confirmation.
- Cancel left the global selection empty and actions disabled; confirming one conversation produced `已选择 1 项`, `已选 1`, and enabled export/trash actions.
- The installed app preserved the OnlineWorker shell, account/session segmented control, quota summary, responsive card grid, dialog focus and backdrop without clipping at the tested desktop viewport.

**Findings**

- P0: none.
- P1: none.
- P2: none. The packaged app uses the existing OnlineWorker three-column desktop density instead of the sketch's illustrative two-column density; card hierarchy, bottom action alignment and picker flow remain equivalent.
- P3: the installed dialog is slightly narrower than the sketch but keeps all controls readable and scrollable.

**Build evidence**

- `bash build.sh` passed.
- `bash verify-packaged-fast.sh` rebuilt and validated the DMG but its first install attempt was blocked by two stale bot processes that ignored SIGTERM.
- After stopping only those verified PIDs, `OnlineWorker/scripts/install-current-dmg.sh` passed; installed app/bot/ccusage hashes matched the DMG and the configured extension manifests were present (repository-external names omitted).
- DMG SHA-256: `ae1802ddd9bd0a900a42d3761f12b7bc493f5d738db288c6094ccc4521e92101`.

final result: passed
