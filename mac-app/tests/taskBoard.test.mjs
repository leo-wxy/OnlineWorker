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

test("buildTaskBoardModel shows latest message for pinned idle sessions", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        title: "梳理一下当前未完成的 phase",
        raw: {
          lastMessage: "最后一条会话内容应该显示在关注中卡片里。",
          updatedAt: nowEpochMs - 60_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    taskBoardState: {
      version: 1,
      pinned: [
        { providerId: "codex", sessionId: "thread-a", updatedAtEpoch: nowEpochMs },
      ],
    },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.pinnedIdle, 1);
  assert.equal(board.pinnedIdle[0].title, "梳理一下当前未完成的 phase");
  assert.equal(board.pinnedIdle[0].preview, "最后一条会话内容应该显示在关注中卡片里。");
});

test("buildTaskBoardModel keeps title text visible as pinned preview fallback", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        title: "梳理一下当前未完成的 phase",
        raw: {
          lastMessage: "梳理一下当前未完成的 phase",
          updatedAt: nowEpochMs - 60_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    taskBoardState: {
      version: 1,
      pinned: [
        { providerId: "codex", sessionId: "thread-a", updatedAtEpoch: nowEpochMs },
      ],
    },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.pinnedIdle, 1);
  assert.equal(board.pinnedIdle[0].title, "梳理一下当前未完成的 phase");
  assert.equal(board.pinnedIdle[0].preview, "梳理一下当前未完成的 phase");
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

test("buildTaskBoardModel renders session title above activity summary", () => {
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
  assert.equal(board.needsAttention[0].title, "Thread A");
  assert.equal(board.needsAttention[0].preview, "需要处理授权请求");
  assert.equal(board.needsAttention[0].statusReason, "需要处理授权请求");
  assert.equal(board.needsAttention[0].recentEvent, "approval.requested");
});

test("buildTaskBoardModel uses activity title as running preview fallback without message content", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "thread-a",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "message.user.accepted",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(board.running[0].preview, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(board.running[0].statusReason, "");
});

test("buildTaskBoardModel shows latest user message when activity has no assistant summary", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "thread-a",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        status: "running",
        attentionReason: "",
        lastUserMessage: "切换 codex/phase-14-message-event-bus 这个分支",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "message.user.accepted",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(board.running[0].preview, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(board.running[0].statusReason, "");
});

test("buildTaskBoardModel replaces uuid activity title with session title", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "修复 TaskBoard 卡片标题",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "我现在继续修 TaskBoard。",
        lastFinalMessage: "旧的完成摘要不应该盖过当前流式内容。",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "修复 TaskBoard 卡片标题");
  assert.equal(board.running[0].preview, "修 TaskBoard。");
});

test("buildTaskBoardModel renders session title above live assistant summary", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "我正在通过事件流更新 TaskBoard。",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "我正在通过事件流更新 TaskBoard。",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(board.running[0].preview, "通过事件流更新 TaskBoard。");
});

test("buildTaskBoardModel trims assistant process preface from live preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "我明白你的意思了：不能等“下一条 activity”才出现。当前会话已经存在，TaskBoard 打开时就应该显示当前 running 卡片；stream 只负责后续更新。",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(
    board.running[0].preview,
    "不能等“下一条 activity”才出现。当前会话已经存在，TaskBoard 打开时就应该显示当前 running 卡片；stream 只负责后续更新。",
  );
});

test("buildTaskBoardModel trims hook discussion preface from live preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "是，可以结合 hook，但位置要放对：hook 把更早到达的 user/turn 信号发布进同一个 message bus；TaskBoard 仍然只监听 bus stream。",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "切换 codex/phase-14-message-event-bus 这个分支");
  assert.equal(
    board.running[0].preview,
    "hook 把更早到达的 user/turn 信号发布进同一个 message bus；TaskBoard 仍然只监听 bus stream。",
  );
});

test("buildTaskBoardModel does not use assistant text as title without session metadata", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/wxy/Projects/onlineWorker",
        workspacePath: "/Users/wxy/Projects/onlineWorker",
        sessionId: "019e92cb-9559-7eb0-be3e-ab23f37f7b27",
        title: "",
        status: "running",
        attentionReason: "",
        lastUserMessage: "",
        lastAssistantMessage: "我正在通过事件流更新 TaskBoard。",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "019e92cb-955");
  assert.equal(board.running[0].preview, "通过事件流更新 TaskBoard。");
});
