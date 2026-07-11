# Phase 19: Attention Center And Session Interrupt/Resume - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-11
**Phase:** 19-attention-center-and-session-interrupt-resume
**Areas discussed:** Task Board surface, layout direction, interrupt truth, post-interrupt classification

---

## Task Board Surface

| Option | Description | Selected |
|--------|-------------|----------|
| New attention page | Add a separate top-level attention surface | |
| Existing Task Board | Reuse and redesign the existing Task Board Tab | ✓ |

**User's choice:** Reuse the existing Task Board Tab.
**Notes:** The user allowed a full internal UI redesign but did not want an unnecessary new top-level page.

---

## Layout Direction

| Option | Description | Selected |
|--------|-------------|----------|
| A: Triage split | Dense queue with selected-item detail | Partial |
| B: Agent groups | Needs you / Running / Recent grouped Session rows | Partial |
| C: Notification inbox | Filter rail, flat notifications, and bulk triage | |
| B+A synthesis | B as primary structure plus A right-hand detail pane | ✓ |

**User's choice:** “以 B 为主体，再加入 A 的右侧详情面板”.
**Notes:** The first card/Kanban exploration was rejected as visually strange. Market references were reviewed before the second round.

---

## Interrupt Truth

| Option | Description | Selected |
|--------|-------------|----------|
| Inactivity inference | Treat a quiet Session as interrupted | |
| Provider authority | Require capability, owned control, active turn, and terminal provider confirmation | ✓ |

**User's choice:** Proceed with provider-owned truth after asking how interruption is determined.
**Notes:** Stalled and interrupted remain distinct states.

---

## Post-Interrupt Classification

| Option | Description | Selected |
|--------|-------------|----------|
| Split by origin | User interrupt to Recent; unexpected abort/failure to Needs you | ✓ |
| All to Needs you | Every interruption remains actionable | |
| Hide after interrupt | Remove interrupted Sessions from Task Board | |

**User's choice:** Option 1.
**Notes:** Continue remains available for the same real Session.

---

## the agent's Discretion

- Continue opens the same Session and focuses its composer; it does not generate a message.
- Recovery is provider-owned, never silently replays input, and needs fresh provider evidence.
- Owned actionable pending items rank ahead of mirrored observations; mirrored-only controls remain unavailable.
- Exact layout tokens, control payload shape, and recovery polling details follow existing project patterns.

## Deferred Ideas

- Global search.
- Automatic message replay after interrupt.
- Taking command ownership of mirrored-only external Sessions.
