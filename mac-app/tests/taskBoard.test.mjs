import test from "node:test";
import assert from "node:assert/strict";

import {
  buildTaskBoardModel,
  collectTaskBoardPreviewHydrationPlan,
  selectRecentConversationTurns,
} from "../src/utils/taskBoard.js";

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

test("selectRecentConversationTurns keeps the latest six user and assistant messages", () => {
  const turns = [
    { role: "user", content: "one" },
    { role: "assistant", content: "two" },
    { role: "tool", content: "hidden tool output" },
    { role: "user", content: "three" },
    { role: "assistant", content: "four" },
    { role: "user", content: "   " },
    { role: "user", content: "five" },
    { role: "assistant", content: "six" },
    { role: "assistant", content: "seven" },
  ];

  assert.deepEqual(
    selectRecentConversationTurns(turns),
    [
      { role: "assistant", content: "two" },
      { role: "user", content: "three" },
      { role: "assistant", content: "four" },
      { role: "user", content: "five" },
      { role: "assistant", content: "six" },
      { role: "assistant", content: "seven" },
    ],
  );
});

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

test("buildTaskBoardModel ignores stale session-list running flags without live activity", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-completed",
        type: "claude",
        title: "Write a file and reply OK",
        raw: {
          running: true,
          status: "running",
          lastMessage: "OK",
          updatedAt: nowEpochMs - 60_000,
        },
      }),
    ],
    providerLabels: { claude: "Claude" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
  assert.equal(board.counts.pinnedIdle, 0);
});

test("buildTaskBoardModel puts provider-active session in running column", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "JSONL active task",
        raw: {
          providerActive: true,
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].sessionId, "thread-active");
  assert.equal(board.running[0].statusReason, "正在执行");
  assert.equal(board.running[0].recentEvent, "provider_active");
});

test("buildTaskBoardModel shows live preview from session raw when provider-active row has no dashboard preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "继续 phase17 的实现",
        raw: {
          providerActive: true,
          highlightedThreadPreview: "继续修 Session 列表 preview",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].sessionId, "thread-active");
  assert.equal(board.running[0].preview, "继续修 Session 列表 preview");
});

test("buildTaskBoardModel uses assistant preview when provider-active row lacks generic preview fields", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "继续 phase17 的实现",
        raw: {
          providerActive: true,
          lastAssistantMessage: "我现在继续同步 preview 到 task board。",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].preview, "同步 preview 到 task board。");
});

test("buildTaskBoardModel prefers live session preview over stale cached preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "继续 phase17 的实现",
        raw: {
          providerActive: true,
          preview: "旧的 cached preview",
          highlightedThreadPreview: "我现在继续通过事件流刷新 TaskBoard。",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].preview, "通过事件流刷新 TaskBoard。");
});

test("buildTaskBoardModel shows sanitized owner-bridge preview for provider-active row", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "继续phase17 的实现",
        raw: {
          providerActive: true,
          preview: "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(
    board.running[0].preview,
    "修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。",
  );
});

test("buildTaskBoardModel suppresses stale running activity when provider marks session inactive", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-stale",
        type: "claude",
        title: "Old Claude task",
        raw: {
          providerActive: false,
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    sessionActivities: [
      {
        providerId: "claude",
        workspaceId: "claude:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-stale",
        title: "Old Claude task",
        status: "running",
        attentionReason: "",
        lastUserMessage: "old prompt",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "message.user.accepted",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { claude: "Claude" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.total, 1);
});

test("buildTaskBoardModel keeps activity running when session metadata is absent", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-live",
        title: "Live task",
        status: "running",
        attentionReason: "",
        lastUserMessage: "live prompt",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].sessionId, "thread-live");
  assert.equal(board.running[0].recentEvent, "message.assistant.delta");
});

test("buildTaskBoardModel prefers fresher provider session preview over stale activity preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-live",
        type: "codex",
        title: "继续phase17 的实现",
        raw: {
          providerActive: true,
          preview: "我先直接取安装态 owner bridge 的实时返回，不再靠猜。",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-live",
        title: "继续phase17 的实现",
        status: "running",
        attentionReason: "",
        lastUserMessage: "继续phase17 的实现",
        lastAssistantMessage: "旧的 activity preview",
        lastFinalMessage: "",
        lastEventKind: "message.assistant.delta",
        updatedAt: Math.floor((nowEpochMs - 30_000) / 1000),
      },
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].sessionId, "thread-live");
  assert.equal(
    board.running[0].preview,
    "直接取安装态 owner bridge 的实时返回，不再靠猜。",
  );
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

test("buildTaskBoardModel suppresses pinned preview when it only repeats the title", () => {
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
  assert.equal(board.pinnedIdle[0].preview, null);
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

test("buildTaskBoardModel renders approval request above previous user prompt", () => {
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

test("buildTaskBoardModel prioritizes owned actions then oldest waiting items", () => {
  const activity = (overrides) => ({
    providerId: "codex",
    workspaceId: "codex:/tmp/project",
    workspacePath: "/tmp/project",
    sessionId: "thread-a",
    title: "Task",
    status: "needs_attention",
    attentionReason: "需要处理",
    attentionKind: "approval",
    requestId: "req-1",
    approvalSource: "app-server",
    mirroredOnly: false,
    canInterrupt: false,
    canRecover: false,
    controlReason: "",
    controlMode: "owned",
    recentEvents: [],
    lastUserMessage: "prompt",
    lastAssistantMessage: "",
    lastFinalMessage: "",
    lastEventKind: "approval.requested",
    updatedAt: 10,
    ...overrides,
  });
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      activity({ sessionId: "failure-old", status: "failed", attentionKind: "failure", requestId: "", updatedAt: 5 }),
      activity({ sessionId: "approval-new", updatedAt: 30 }),
      activity({ sessionId: "approval-old", requestId: "req-2", updatedAt: 20 }),
      activity({ sessionId: "mirrored-oldest", mirroredOnly: true, updatedAt: 1 }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.deepEqual(
    board.needsAttention.map((task) => task.sessionId),
    ["approval-old", "approval-new", "failure-old", "mirrored-oldest"],
  );
});

test("buildTaskBoardModel puts interrupted and completed activities in recent ended", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-interrupted",
        title: "Interrupted task",
        status: "completed",
        attentionReason: "任务已由用户中断",
        attentionKind: "interrupted",
        requestId: "",
        approvalSource: "",
        mirroredOnly: false,
        canInterrupt: false,
        canRecover: false,
        controlReason: "",
        controlMode: "owned",
        recentEvents: [{ kind: "turn.failed", createdAt: 20, summary: "interrupted" }],
        lastUserMessage: "implement phase 19",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "turn.failed",
        updatedAt: 20,
      },
      {
        providerId: "claude",
        workspaceId: "claude:/tmp/project",
        workspacePath: "/tmp/project",
        sessionId: "thread-completed",
        title: "Completed task",
        status: "completed",
        attentionReason: "",
        attentionKind: "",
        requestId: "",
        approvalSource: "",
        mirroredOnly: false,
        canInterrupt: false,
        canRecover: false,
        controlReason: "",
        controlMode: "owned",
        recentEvents: [],
        lastUserMessage: "run tests",
        lastAssistantMessage: "done",
        lastFinalMessage: "done",
        lastEventKind: "turn.completed",
        updatedAt: 10,
      },
    ],
    providerLabels: { codex: "Codex", claude: "Claude" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.recentEnded, 2);
  assert.deepEqual(board.recentEnded.map((task) => task.sessionId), ["thread-interrupted", "thread-completed"]);
  assert.equal(board.recentEnded[0].interrupted, true);
  assert.equal(board.recentEnded[0].canContinue, true);
  assert.equal(board.recentEnded[0].recentEvents[0].kind, "turn.failed");
  assert.equal(board.recentEnded[0].lastUserMessage, "implement phase 19");
  assert.equal(board.recentEnded[1].lastAssistantMessage, "done");
});

test("buildTaskBoardModel shows Claude permission command as dynamic preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "fe8cfb27-d4b2-4df7-9b03-000000000001",
        type: "claude",
        title: "fe8cfb27-d4b",
        workspace: "sample_engine",
        raw: { status: "running", updatedAt: nowEpochMs - 1_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "claude",
        workspaceId: "claude:/Users/example/Projects/sample_engine",
        workspacePath: "/Users/example/Projects/sample_engine",
        sessionId: "fe8cfb27-d4b2-4df7-9b03-000000000001",
        title: "fe8cfb27-d4b2-4df7-9b03-000000000001",
        status: "needs_attention",
        attentionReason: "需要处理授权请求：git remote get-url origin 2>/dev/null",
        attentionKind: "approval",
        requestId: "req-1",
        approvalSource: "item/commandExecution/requestApproval",
        mirroredOnly: true,
        lastUserMessage: "engine实现情况如何？",
        lastAssistantMessage: "",
        lastFinalMessage: "",
        lastEventKind: "approval.requested",
        updatedAt: Math.floor(nowEpochMs / 1000),
      },
    ],
    providerLabels: { claude: "Claude" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.needsAttention, 1);
  assert.equal(board.needsAttention[0].title, "engine实现情况如何？");
  assert.equal(board.needsAttention[0].mirroredOnly, true);
  assert.equal(board.needsAttention[0].requestId, "req-1");
  assert.equal(
    board.needsAttention[0].preview,
    "需要处理授权请求：git remote get-url origin 2>/dev/null",
  );
  assert.equal(
    board.needsAttention[0].statusReason,
    "需要处理授权请求：git remote get-url origin 2>/dev/null",
  );
});

test("buildTaskBoardModel suppresses running preview when only the title is available", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
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
  assert.equal(board.running[0].preview, null);
  assert.equal(board.running[0].statusReason, "");
});

test("buildTaskBoardModel keeps latest user message preview even when it repeats the title", () => {
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
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
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

test("buildTaskBoardModel suppresses active session preview when it repeats the title", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        title: "继续 /Users/example/Projects/sample-repo 的任务",
        raw: { status: "running", updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: {
      recentActivity: {
        activeSessionId: "thread-a",
        activeSessionTool: "codex",
        highlightedThreadPreview: "继续 /Users/example/Projects/sample-repo 的任务",
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "继续 /Users/example/Projects/sample-repo 的任务");
  assert.equal(board.running[0].preview, null);
});

test("buildTaskBoardModel falls back to provider session preview when active dashboard preview only repeats the title", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-a",
        title: "继续phase17 的实现",
        raw: {
          providerActive: true,
          preview: "我先抓一份安装态 owner bridge 的真实 list_sessions 返回。",
          updatedAt: nowEpochMs - 30_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: {
      recentActivity: {
        activeSessionId: "thread-a",
        activeSessionTool: "codex",
        highlightedThreadPreview: "继续phase17 的实现",
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.running[0].title, "继续phase17 的实现");
  assert.equal(
    board.running[0].preview,
    "抓一份安装态 owner bridge 的真实 list_sessions 返回。",
  );
});

test("buildTaskBoardModel ignores stale low-signal dashboard active session without live provider signal", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "ses-old-ok",
        type: "overlay-tool",
        title: "OK",
        workspace: "/Users/example/Projects/onlineWorker",
        raw: {
          updatedAt: nowEpochMs - 30_000,
          providerActive: false,
        },
      }),
    ],
    providerLabels: { "overlay-tool": "Overlay Tool" },
    dashboardState: {
      recentActivity: {
        activeSessionId: "ses-old-ok",
        activeSessionTool: "overlay-tool",
        highlightedThreadPreview: "OK",
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.counts.running, 0);
  assert.equal(board.running.length, 0);
});

test("buildTaskBoardModel ignores stale dashboard active workspace when matching session is explicitly inactive", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "ses-old-ok",
        type: "overlay-tool",
        title: "OK",
        workspace: "/Users/example/Projects/onlineWorker",
        raw: {
          preview: "OK",
          updatedAt: nowEpochMs - 30_000,
          providerActive: false,
        },
      }),
      session({
        id: "thread-live",
        type: "codex",
        title: "继续phase17 的实现",
        workspace: "/Users/example/Projects/onlineworker-workspace",
        raw: {
          preview: "继续phase17 的实现",
          updatedAt: nowEpochMs - 5_000,
          providerActive: true,
        },
      }),
    ],
    providerLabels: { "overlay-tool": "Overlay Tool", codex: "Codex" },
    dashboardState: {
      recentActivity: {
        activeWorkspaceId: "overlay-tool:onlineWorker",
        activeWorkspaceName: "onlineWorker",
        activeWorkspacePath: "/Users/example/Projects/onlineWorker",
        activeTool: "overlay-tool",
        activeSessionId: "ses-old-ok",
        activeSessionTool: "overlay-tool",
        highlightedThreadPreview: "OK",
        activeThreadCount: 5,
      },
      generatedAtEpoch: Math.floor(nowEpochMs / 1000),
    },
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running.length, 1);
  assert.equal(board.running[0].providerId, "codex");
  assert.equal(board.running[0].sessionId, "thread-live");
});

test("buildTaskBoardModel sanitizes absolute local paths in provider session preview", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "thread-active",
        type: "codex",
        title: "继续phase17 的实现",
        raw: {
          providerActive: true,
          preview: "我现在继续读 /Users/example/Projects/onlineworker-workspace/OnlineWorker/mac-app/src/pages/TaskBoard.tsx 这条链路。",
          updatedAt: nowEpochMs - 5_000,
        },
      }),
    ],
    providerLabels: { codex: "Codex" },
    dashboardState: null,
    nowEpochMs,
  });

  assert.equal(board.counts.running, 1);
  assert.equal(board.running[0].preview, "读 [path] 这条链路。");
});

test("buildTaskBoardModel replaces uuid activity title with session title", () => {
  const board = buildTaskBoardModel({
    sessions: [
      session({
        id: "00000000-0000-7000-8000-000000000001",
        title: "修复 TaskBoard 卡片标题",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
        sessionId: "00000000-0000-7000-8000-000000000001",
        title: "00000000-0000-7000-8000-000000000001",
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
        id: "00000000-0000-7000-8000-000000000001",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
        sessionId: "00000000-0000-7000-8000-000000000001",
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
        id: "00000000-0000-7000-8000-000000000001",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
        sessionId: "00000000-0000-7000-8000-000000000001",
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
        id: "00000000-0000-7000-8000-000000000001",
        title: "切换 codex/phase-14-message-event-bus 这个分支",
        raw: { updatedAt: nowEpochMs - 30_000 },
      }),
    ],
    sessionActivities: [
      {
        providerId: "codex",
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
        sessionId: "00000000-0000-7000-8000-000000000001",
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
        workspaceId: "codex:/Users/example/Projects/sample-workspace",
        workspacePath: "/Users/example/Projects/sample-workspace",
        sessionId: "00000000-0000-7000-8000-000000000001",
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

  assert.equal(board.running[0].title, "00000000-000");
  assert.equal(board.running[0].preview, "通过事件流更新 TaskBoard。");
});

test("collectTaskBoardPreviewHydrationPlan dedupes sessions that are both pinned and low-signal", () => {
  const target = session({
    id: "thread-a",
    title: "OK",
    raw: {
      preview: "OK",
      updatedAt: nowEpochMs - 5_000,
    },
  });

  const plan = collectTaskBoardPreviewHydrationPlan({
    sessions: [target],
    taskBoardState: {
      version: 1,
      pinned: [
        { providerId: "codex", sessionId: "thread-a", updatedAtEpoch: nowEpochMs },
      ],
    },
  });

  assert.deepEqual(plan.keys, ["codex:thread-a"]);
  assert.deepEqual(plan.pinnedKeys, ["codex:thread-a"]);
});
