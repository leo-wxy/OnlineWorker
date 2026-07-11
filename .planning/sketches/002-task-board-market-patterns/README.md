---
sketch: 002
name: task-board-market-patterns
question: "Which mature inbox or agent-task pattern best fits OnlineWorker Task Board?"
winner: "B+A"
tags: [layout, task-board, triage, agent-sessions, market-reference]
---

# Sketch 002: Task Board Market Patterns

## Design Question

Which mature information pattern best combines actionable pending states with real provider Session controls?

## How to View

Open `.planning/sketches/002-task-board-market-patterns/index.html`.

## Variants

- **A: Triage 分栏** — Inspired by Linear Inbox/Triage: dense queue on the left, selected item context and actions on the right.
- **B: Agent 分组** — Inspired by Codex/Cursor task views: grouped rows for Needs you, Running, and Recent.
- **C: 通知收件箱** — Inspired by GitHub Notifications: filter rail, flat notification rows, and optional bulk triage.

## Selected Direction

**B+A synthesis** — Keep Variant B's grouped agent list as the primary structure (`需要你 / 正在运行 / 最近完成`). Selecting any row opens Variant A's right-hand detail pane with source context, recent activity, and the real provider-backed actions available for that item.

The selected direction explicitly rejects a card-based Kanban and a notification-first inbox as the main Task Board structure.

## What to Look For

- Whether pending work is clearly separated from passive Session activity.
- Whether there is enough context to approve, answer, recover, or interrupt safely.
- Whether many Sessions remain scannable without large cards or decorative dashboard chrome.
- Whether the pattern still feels like an agent task surface rather than a generic notification center.
