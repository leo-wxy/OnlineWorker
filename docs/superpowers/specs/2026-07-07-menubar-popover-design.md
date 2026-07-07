# Menubar Popover Design

Date: 2026-07-07
Status: Draft for review
Scope: `OnlineWorker/mac-app`

## Summary

Replace the current menubar native menu as the primary interaction surface with a compact menubar popover. The first screen should prioritize today's usage, then show the latest active session for `Codex` and `Claude` in separate provider lanes. Clicking a session card opens that session in the main app.

This is intentionally not a mini dashboard and not a full task board. It is a fast re-entry surface for the user's current work.

## Goals

- Show a high-signal usage summary at the top of the popover.
- Keep `Codex` and `Claude` visually separated.
- Show only the latest active session per provider.
- Make each session card a direct "open session" target.
- Keep the popover compact enough to feel like a menubar tool, not a second app shell.

## Non-goals

- Inline `approve` / `deny` / `continue` actions in the first iteration.
- Showing every active session inside the popover.
- Reproducing the full Task Board, Sessions, or Usage pages inside the popover.
- Replacing the main app window for deeper session browsing or diagnostics.

## User Intent

The popover should answer three questions in one glance:

1. How much usage has happened today?
2. What is the latest active `Codex` session?
3. What is the latest active `Claude` session?

The default next action is to open one of those sessions.

## Recommended Direction

Use `A1`:

- Top `Usage Hero`
- Middle `Active Session Board`
- Bottom `Secondary Entry`

Within the session board:

- Separate `Codex` and `Claude` into two stacked provider lanes.
- Show one latest session card per provider.
- Use `message-first` cards: title, workspace, latest message preview, age, light status badge.

## Popover Container

Use a dedicated Tauri popover-style window instead of trying to force richer UI into native tray menu rows.

Recommended runtime behavior:

- Hidden by default.
- Toggled from tray icon click.
- Frameless, non-resizable, always-on-top.
- Compact width, approximately `400-440px`.
- Max height approximately `560-620px`.
- Hide on blur and `Esc`.
- Primary click target is the tray icon; native tray menu remains fallback-only for `Quit` and possible future diagnostics.

If exact tray-anchor bounds are available from the tray click event, position the popover against those bounds. If not, use a stable top-right fallback position that still feels anchored to the menubar.

## Information Architecture

### 1. Usage Hero

Purpose: provide the first visual hit.

Content:

- Today's total token usage.
- Per-provider usage summary for `Codex` and `Claude`.
- Light secondary status such as `active sessions` and `needs attention`.

Visual rules:

- Largest number on the screen is total usage.
- Provider usage stays secondary.
- Keep this section as a single card.

### 2. Active Session Board

Purpose: provide the main working-entry surface.

Structure:

- `Codex` lane
- `Claude` lane

Each lane contains:

- Provider heading
- One latest active session card

Card content:

- Session title
- Workspace name
- Latest message preview
- Relative age
- Light status badge such as `Running` or `Needs reply`

Card interaction:

- Whole card is clickable.
- Clicking opens the corresponding session in the main app window.

### 3. Secondary Entry

Purpose: keep fallback navigation available without diluting the primary flow.

Initial actions:

- `Task Board`
- `Sessions`
- `Usage`

These actions are secondary and should read as escape hatches, not as the main focal area.

## Visual Direction

The popover should feel denser and more polished than a native menu, but lighter than the main app.

Guidelines:

- Soft high-contrast surface with subtle depth, not a flat panel.
- One usage hero card at the top with stronger emphasis than the session lanes.
- Provider accents stay distinct:
  - `Codex`: blue family
  - `Claude`: violet/plum family
- Avoid a purple-dominant whole surface; provider color should mark lanes, not flood the layout.
- Session cards should privilege readability of the message preview over ornamental chrome.

## Data Model

The popover should not assemble its state from many independent frontend calls. Add a dedicated backend snapshot command that returns exactly the popover view model.

Proposed command:

- `get_menubar_popover_snapshot`

Proposed payload shape:

```ts
type MenubarPopoverSnapshot = {
  generatedAtEpoch: number;
  usage: {
    totalTokensToday: number | null;
    needsAttentionCount: number;
    activeSessionCount: number;
    providers: Array<{
      providerId: "codex" | "claude";
      label: string;
      tokensToday: number | null;
    }>;
  };
  latestSessions: Array<{
    providerId: "codex" | "claude";
    label: string;
    sessionId: string | null;
    workspaceId: string | null;
    workspaceName: string | null;
    title: string | null;
    latestPreview: string | null;
    status: string | null;
    updatedAtEpoch: number | null;
  }>;
};
```

## Data Sources

Prefer reusing existing commands and helpers internally:

- Usage:
  - `get_provider_usage_summary`
- Attention count:
  - `get_task_board_session_activities`
- Provider identity and visibility:
  - `read_provider_metadata_from_disk`
- Current activity and workspace context:
  - dashboard / recent activity helpers
- Session candidates:
  - existing provider session listing logic

Implementation note:

- `latest active session` should mean the most recently updated session that is currently relevant to the user, not simply the most recently created session.
- If a provider has no active session, keep the provider lane visible and show an empty-state row such as `No active session`.

## Open Session Behavior

Clicking a session card should:

1. Ensure the main window is shown and focused.
2. Navigate to the `sessions` tab.
3. Pass an explicit open target with:
   - `providerId`
   - `sessionId`
   - `workspace` when available

This should reuse the same main-window open-target pattern already used by the Task Board to avoid inventing a second session-opening route.

## Error Handling

- If usage is unavailable, keep the hero visible and render `No data` for the missing provider or total.
- If one provider has no active session, render an empty state only for that provider lane.
- If opening a session fails, keep the popover visible and show a compact inline failure state or fallback toast.
- Snapshot generation failure should degrade to partial rendering when possible instead of blanking the whole popover.

## Implementation Boundaries

First iteration:

- Build the popover container and snapshot path.
- Render the approved `A1` layout.
- Wire session-card click to open the session in the main window.

Deferred:

- Inline approval controls
- Multi-session expanders
- Rich scrolling provider lists
- In-popover reply composition

## Verification

Minimum verification for the implementation phase:

- Rust tests for snapshot aggregation and empty-state handling.
- Frontend tests for provider lanes and empty-state rendering where practical.
- Manual desktop verification:
  - tray click opens popover
  - blur hides popover
  - usage hero renders
  - `Codex` and `Claude` lanes render separately
  - clicking each latest-session card opens the correct session

## Risks

- Tray-anchor positioning may vary by macOS runtime behavior.
- Usage aggregation can become too expensive if refreshed too often.
- Session freshness rules can be inconsistent if different sources disagree about "latest".

Mitigation:

- Cache usage more aggressively than session state.
- Keep one dedicated snapshot command so the aggregation policy lives in one place.
- Prefer graceful partial rendering over all-or-nothing failure.
