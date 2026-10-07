import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildTaskBoardModel,
  formatTaskBoardRelativeTime,
  taskBoardStatusKey,
} from "../src/utils/taskBoard.js";

const nowEpochMs = 1_800_000_000_000;
const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("task status follows execution state rather than pin state", () => {
  for (const pinned of [false, true]) {
    assert.equal(taskBoardStatusKey({ status: "completed", pinned }), "statusCompleted");
    assert.equal(taskBoardStatusKey({ status: "completed", interrupted: true, pinned }), "statusInterrupted");
    assert.equal(taskBoardStatusKey({ status: "running", running: true, pinned }), "statusRunning");
    assert.equal(taskBoardStatusKey({ status: "needs_attention", needsAttention: true, pinned }), "statusNeedsAttention");
    assert.equal(taskBoardStatusKey({ status: "idle", pinned }), null);
  }
});

const fixedThemeColor = /\b(?:bg|text|border|ring|divide|from|via|to)-(?:white|black|gray|slate|red|rose|orange|amber|green|emerald|sky|blue|violet|purple)(?:-\d+)?(?:\/[^\s"'`}]+)?/;

test("dashboard and task board surfaces use the shared theme contract", () => {
  const files = [
    "src/pages/TaskBoard.tsx",
    "src/components/dashboard/DashboardAlerts.tsx",
    "src/components/dashboard/DashboardError.tsx",
    "src/components/dashboard/DashboardHero.tsx",
    "src/components/dashboard/DashboardSidebar.tsx",
    "src/components/dashboard/ProviderStatusList.tsx",
    "src/components/dashboard/SettingSwitch.tsx",
    "src/components/dashboard/model.ts",
  ];

  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    assert.match(source, /var\(--ow-/);
    assert.doesNotMatch(source, fixedThemeColor, file);
    assert.doesNotMatch(source, /transition-all|#[0-9a-f]{3,8}\b|rgba?\(/i, file);
  }
});

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

test("buildTaskBoardModel does not infer running from dashboard without bus events", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
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

test("buildTaskBoardModel does not infer running from provider metadata without bus events", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel does not display raw metadata messages without a bus projection", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel does not use metadata assistant messages as activity", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel does not choose between metadata message caches", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel requires a bus projection for owner-bridge message previews", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel preserves bus running state when metadata is stale", () => {
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

  assert.equal(board.counts.running, 1);
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

test("buildTaskBoardModel keeps bus preview authoritative over newer metadata", () => {
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
    "旧的 activity preview",
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

test("buildTaskBoardModel keeps metadata-only pinned sessions without inventing message previews", () => {
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
  assert.equal(board.pinnedIdle[0].preview, null);
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

test("buildTaskBoardModel does not create a dashboard-only running task", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
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
        updatedAt: (nowEpochMs - 10_000) / 1000,
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
        updatedAt: (nowEpochMs - 20_000) / 1000,
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

test("recent ended includes only completed sessions within seven days even when pinned", () => {
  const week = 7 * 86400_000;
  const rows = [
    ["recent", "completed", nowEpochMs - 1000],
    ["boundary", "completed", nowEpochMs - week],
    ["old-pinned", "completed", nowEpochMs - week - 1],
    ["idle-pinned", "idle", nowEpochMs - 1000],
    ["running", "running", nowEpochMs - 1000],
    ["failed", "failed", nowEpochMs - 1000],
    ["unknown-time", "completed", 0],
    ["future", "completed", nowEpochMs + 1000],
    ["archived", "completed", nowEpochMs - 1000],
  ];
  const board = buildTaskBoardModel({
    sessions: [session({ id: "archived", archived: true })],
    sessionActivities: rows.map(([sessionId, status, updatedAt]) => ({ providerId: "codex", sessionId, status, updatedAt })),
    taskBoardState: { pinned: ["old-pinned", "idle-pinned"].map(sessionId => ({ providerId: "codex", sessionId })) },
    providerLabels: {}, dashboardState: null, nowEpochMs,
  });
  assert.deepEqual(board.recentEnded.map(task => task.sessionId), ["recent", "boundary"]);
  assert.equal(board.counts.recentEnded, 2);
  assert.equal(board.counts.running, 1);
  assert.equal(board.counts.needsAttention, 1);
});

test("recent ended keeps only the latest five sessions and reports the visible count", () => {
  const board = buildTaskBoardModel({
    sessions: [],
    sessionActivities: Array.from({ length: 7 }, (_, index) => ({
      providerId: "codex", sessionId: `sample-${index}`, status: "completed",
      updatedAt: nowEpochMs - (index + 1) * 1000,
    })).reverse(),
    providerLabels: {}, dashboardState: null, nowEpochMs,
  });
  assert.deepEqual(board.recentEnded.map(task => task.sessionId), ["sample-0", "sample-1", "sample-2", "sample-3", "sample-4"]);
  assert.equal(board.counts.recentEnded, 5);
});

test("task times use natural relative units in Chinese and English", () => {
  const cases = [[59, "59秒钟前", "59 seconds ago"], [60, "1分钟前", "1 minute ago"],
    [3600, "1小时前", "1 hour ago"], [86400, "1天前", "1 day ago"],
    [7 * 86400, "1周前", "1 week ago"], [30 * 86400, "1个月前", "1 month ago"],
    [365 * 86400, "1年前", "1 year ago"]];
  for (const [seconds, zh, en] of cases) {
    assert.equal(formatTaskBoardRelativeTime(nowEpochMs - seconds * 1000, nowEpochMs, "zh"), zh);
    assert.equal(formatTaskBoardRelativeTime(nowEpochMs - seconds * 1000, nowEpochMs, "en"), en);
  }
  assert.equal(formatTaskBoardRelativeTime(null, nowEpochMs, "zh"), null);
  assert.equal(formatTaskBoardRelativeTime(NaN, nowEpochMs, "zh"), null);
  assert.equal(formatTaskBoardRelativeTime(nowEpochMs + 1000, nowEpochMs, "zh"), "0秒钟前");
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

test("buildTaskBoardModel ignores metadata preview even when it repeats the title", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel does not use provider messages as a dashboard fallback", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
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

test("buildTaskBoardModel ignores dashboard and provider activity without bus events", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
});

test("buildTaskBoardModel does not render file-path metadata previews as bus messages", () => {
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

  assert.equal(board.counts.running, 0);
  assert.equal(board.counts.needsAttention, 0);
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
