# Phase 19: Attention Center And Session Interrupt/Resume - Context

**Gathered:** 2026-07-11
**Status:** Ready for planning and implementation

<domain>
## Phase Boundary

Phase 19 redesigns the existing Task Board Tab into a focused agent-work surface that combines actionable pending states with real provider Session lifecycle controls. It adds provider-owned interrupt, continue, and recovery entry points without creating local-only Session truth, changing approval authority, or adding global search.

</domain>

<decisions>
## Implementation Decisions

### Task Board information architecture
- **D-01:** Reuse the existing Task Board Tab; do not add a new top-level attention page.
- **D-02:** Use the selected B+A synthesis from Sketch 002: the primary surface is a compact grouped agent list, and selecting a row opens a right-hand detail pane.
- **D-03:** The primary groups are `需要你`, `正在运行`, and `最近结束`. Avoid card-based Kanban columns and notification-first chrome.
- **D-04:** The right-hand pane shows source/provider identity, workspace, Session identity, attention reason or current activity, recent canonical events, and only the real actions available for that concrete Session.
- **D-05:** Preserve the existing Task Board Tab route, app shell, badge feed, pin/follow behavior, and open-Session navigation contract.

### Pending-state membership and ordering
- **D-06:** `需要你` contains approval requests, questions, failures, and stalled/recovery states that require a human decision or action.
- **D-07:** Owned actionable requests rank before failures/recovery items; mirrored-only observations remain visible but are clearly labeled as requiring action in the owning/native surface and expose no OnlineWorker decision control.
- **D-08:** Within the same priority class, older waiting items rank first to prevent starvation. `正在运行` and `最近结束` sort by latest real provider activity descending.
- **D-09:** Resolving an approval or question removes it from `需要你` only after the authoritative request/reply path confirms resolution.

### Session interrupt behavior
- **D-10:** Show interrupt only when the provider supports it for the concrete control mode, OnlineWorker owns a real control channel, a concrete active turn exists, and the Session is not mirrored-only.
- **D-11:** Clicking interrupt enters a transient `正在中断` presentation state. This is request progress only and must not be persisted as Session truth.
- **D-12:** Mark interruption successful only after the provider returns or emits an authoritative aborted/cancelled terminal result. A click or local timeout alone is not success.
- **D-13:** A user-initiated successful interruption moves the Session to `最近结束` and retains a `继续` action. Unexpected aborts and failures move to `需要你`.

### Continue and recovery behavior
- **D-14:** `继续` opens the same real Session in the existing Sessions surface and focuses the composer. It does not send a generated “continue” prompt and does not claim the interrupted turn itself resumed.
- **D-15:** A new user message after `继续` uses the existing provider-backed same-Session send path from Phase 18.
- **D-16:** `恢复` is reserved for provider-owned recovery of a stalled or disconnected managed Session. It may reconnect or resume the provider thread, but it must not replay the last user message or create a replacement Session silently.
- **D-17:** Recovery success requires fresh provider evidence (connection/session activity or an explicit provider result). Failure stays visible in `需要你` with a clear reason.

### Authority and unsupported states
- **D-18:** Existing app-server request/reply remains the only approval command authority. Phase 19 only changes presentation and routes existing owned actions.
- **D-19:** Mirrored-only approvals, questions, and externally controlled Sessions are observational. They may show where the user must act, but OnlineWorker must not expose allow/deny/interrupt/recovery controls without an owned command path.
- **D-20:** Unsupported controls are omitted from row quick actions. When the selected detail pane needs to explain the limitation, show the provider/control-mode reason rather than a generic disabled button.
- **D-21:** Inactivity can classify a Session as potentially stalled only when backed by provider/liveness evidence. It must never be relabeled as interrupted.

### the agent's Discretion
- Exact typography, spacing, icons, responsive breakpoints, and transition timing within the existing design system.
- The smallest provider-neutral command/result payload needed between Tauri and the owner bridge, provided ownership and provider-private details stay behind current boundaries.
- Exact recovery timeout and polling interval, provided tests cover timeout and late-authoritative-event behavior.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Product and phase boundaries
- `.planning/PROJECT.md` — active requirements, installed-app-first constraints, and provider boundary.
- `.planning/ROADMAP.md` — Phase 19 goal, dependency, and scope fence.
- `.planning/phases/18-provider-session-new-flow/CONTEXT.md` — real provider-backed Session creation/send behavior that Continue must reuse.
- `.planning/phases/15-bus-driven-rendering-approval-command-boundary/CONTEXT.md` — message-bus rendering and approval/question command-authority rules.
- `.planning/sketches/002-task-board-market-patterns/README.md` — selected B+A information architecture and rejected alternatives.

### Existing Task Board and session-control contracts
- `mac-app/src/pages/TaskBoard.tsx` — current Task Board loading, rendering, approval action, pinning, and open-Session integration.
- `mac-app/src/utils/taskBoard.js` — current activity-to-board projection and status derivation.
- `mac-app/src-tauri/src/commands/task_board_state.rs` — current owner-bridge activity and approval command transport.
- `core/providers/contracts.py` — provider-neutral thread hooks including interrupt capability and execution.
- `core/messages/session_bridge.py` — canonical mapping for aborted/cancelled provider events.
- `bot/thread_controls.py` — existing provider interrupt capability and TG control behavior.
- `plugins/providers/builtin/codex/python/runtime.py` — Codex interrupt support, real turn interrupt, and stale-stream recovery.
- `plugins/providers/builtin/claude/python/adapter.py` — Claude managed-process interrupt and cancelled terminal event behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TaskBoard` page: already owns provider metadata, activity stream consumption, pin state, approval reply actions, and navigation to a real Session.
- `buildTaskBoardModel`: already normalizes activities and provider-active facts into board rows; Phase 19 should evolve this projection instead of building parallel UI state.
- `TaskBoardSessionActivity`: already carries provider/workspace/Session identity, attention kind, request id, approval source, mirrored-only state, recent messages, event kind, and timestamp.
- Provider `interrupt_thread` / `interrupt_supported` hooks: existing provider boundary for real interrupt commands.
- Canonical Session events and message bus: existing source for terminal aborted/cancelled state and activity projection updates.

### Established Patterns
- Shared app surfaces consume normalized provider facts; provider-private turn/process details remain in builtin provider packages.
- Task Board is event/projection-driven and must not create an independent Session source of truth.
- Approval actions route through the owner bridge and preserve app-server request identity.
- Frontend behavior tests live under `mac-app/tests`, Rust command tests stay near `task_board_state.rs`, and provider/runtime regression tests live under `tests/`.

### Integration Points
- Add provider-neutral Session control request/result handling to the existing owner-bridge/Tauri Task Board command path.
- Extend the activity projection with normalized control availability, terminal reason/origin, and recovery facts needed by the selected UI.
- Refactor `TaskBoard.tsx` into grouped-list and detail-pane presentation without changing its top-level route or `onOpenSession` contract.
- Reuse the Sessions surface open-target path for Continue, adding composer-focus intent only if required.

</code_context>

<specifics>
## Specific Ideas

- Market references were used as patterns, not visual copies: Linear-style selected-item detail, Codex/Cursor-style agent grouping, and GitHub-style dense rows.
- The selected result is explicitly B+A: agent groups as the main structure, selected-row detail on the right.
- The user asked to stop further design questioning and begin Phase 19 implementation using the confirmed direction and safe defaults above.

</specifics>

<deferred>
## Deferred Ideas

- Global search remains outside Phase 19.
- Automatic replay of interrupted user messages is rejected for this phase.
- Upgrading mirrored-only external Sessions into controllable owned Sessions requires a separate ownership contract and is not added here.

</deferred>

---

*Phase: 19-attention-center-and-session-interrupt-resume*
*Context gathered: 2026-07-11*
