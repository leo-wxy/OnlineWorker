import test from "node:test";
import assert from "node:assert/strict";

import { buildTaskBoardModel } from "../src/utils/taskBoard.js";

const nowEpochMs = 1_800_000_000_000;

function session(overrides) {
  return {
    id: "thread-a",
    type: "codex",
    workspace: "/tmp/project",
    title: "Thread A",
    archived: false,
    raw: {},
    ...overrides,
  };
}

test("buildTaskBoardModel puts dashboard active session in running column", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        raw: { updatedAt: nowEpochMs - 60_000 },
      }),
      session({
        id: "thread-b",
        title: "Thread B",
        raw: { updatedAt: nowEpochMs - 120_000 },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: {
      recentActivity: {
        activeSessionId: "thread-a",
        activeSessionTool: "codex",
        highlightedThreadPreview: "active work",
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.counts.needsAttention, 0);
  assert.equal(board.counts.pinnedIdle, 0);
  assert.equal(board.counts.total, 2);
  assert.equal(board.running[0].sessionId, "thread-a");
  assert.equal(board.running[0].preview, "active work");
});

test("buildTaskBoardModel separates archived sessions", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        raw: { updatedAt: nowEpochMs - 60_000 },
      }),
      session({
        id: "thread-archived",
        title: "Archived Thread",
        archived: true,
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    providerLabels: { codex: "Codex" },
    taskBoardState: {
      version: 1,
      pinned: [
        { providerId: "codex", sessionId: "thread-a", updatedAtEpoch: nowEpochMs },
        { providerId: "codex", sessionId: "thread-archived", updatedAtEpoch: nowEpochMs },
      ],
      hidden: [],
    },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.needsAttention, 0);
  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.pinnedIdle, 1);
  assert.equal(board.counts.total, 2);
  assert.equal(board.pinnedIdle[0].sessionId, "thread-a");
});

test("buildTaskBoardModel creates a running fallback from dashboard activity", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    providerLabels: { codex: "Codex" },
    dashboardState: {
      recentActivity: {
        activeSessionId: "thread-live",
        activeSessionTool: "codex",
        activeWorkspacePath: "/tmp/live",
        highlightedThreadPreview: "live title",
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.counts.total, 1);
  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].sessionId, "thread-live");
  assert.equal(board.running[0].workspace, "/tmp/live");
});

test("buildTaskBoardModel prefers session activity projection over session raw fields", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        raw: { status: "running", updatedAt: nowEpochMs - 60_000, preview: "old preview" },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-a",
        title: "Projection title",
        status: "needs_attention",
        attentionReason: "需要处理授权请求",
        lastUserMessage: "run tests",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "approval.requested",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.total, 1);
  assert.equal(board.counts.needsAttention, 1);
  assert.equal(board.counts.running, 0);
  assert.equal(board.needsAttention[0].title, "Projection title");
  assert.equal(board.needsAttention[0].preview, "需要处理授权请求");
  assert.equal(board.needsAttention[0].statusReason, "需要处理授权请求");
  assert.equal(board.needsAttention[0].recentEvent, "approval.requested");
});
