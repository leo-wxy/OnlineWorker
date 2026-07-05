import test from "node:test";
import assert from "node:assert/strict";

import {
  hasPendingSelectedSession,
  mergeLiveSessionActivities,
  mergeSessionListSnapshot,
  nextSelectedSessionId,
  resolveSessionSnapshotUpdate,
  sessionPreviewText,
} from "../src/utils/sessionBrowserState.js";

function session(overrides = {}) {
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

test("sessionPreviewText prefers live assistant summary and trims boilerplate", () => {
  const preview = sessionPreviewText(session({
    raw: {
      lastAssistantMessage: "我现在继续修 Session 列表预览。",
    },
  }));

  assert.equal(preview, "修 Session 列表预览。");
});

test("sessionPreviewText falls back to final message when assistant delta is absent", () => {
  const preview = sessionPreviewText(session({
    raw: {
      lastFinalMessage: "我现在继续补 TaskBoard 预览。",
    },
  }));

  assert.equal(preview, "补 TaskBoard 预览。");
});

test("sessionPreviewText preserves sanitized owner-bridge preview summaries", () => {
  const preview = sessionPreviewText(session({
    title: "继续phase17 的实现",
    raw: {
      preview: "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。",
      providerActive: true,
    },
  }));

  assert.equal(preview, "修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。");
});

test("sessionPreviewText sanitizes absolute paths from summary previews", () => {
  const preview = sessionPreviewText(session({
    title: "继续phase17 的实现",
    raw: {
      preview: "我现在继续读 /Users/wxy/Projects/onlineworker-combined/OnlineWorker/mac-app/src/pages/TaskBoard.tsx 这条链路。",
      providerActive: true,
    },
  }));

  assert.equal(preview, "读 [path] 这条链路。");
});

test("mergeSessionListSnapshot preserves richer cached preview when incoming row is empty", () => {
  const merged = mergeSessionListSnapshot(
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。" },
    })],
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "" },
    })],
  );

  assert.equal(merged[0].raw.preview, "我现在继续修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。");
  assert.equal(sessionPreviewText(merged[0]), "修 Session 列表预览，并检查 [path] 里的 owner bridge 数据链。");
});

test("mergeSessionListSnapshot accepts fresher non-empty preview updates", () => {
  const merged = mergeSessionListSnapshot(
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "旧 preview" },
    })],
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "新 preview" },
    })],
  );

  assert.equal(merged[0].raw.preview, "新 preview");
});

test("resolveSessionSnapshotUpdate preserves cached rows and retries one transient empty refresh", () => {
  const result = resolveSessionSnapshotUpdate(
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "cached preview" },
    })],
    [],
    {
      preserveOnEmpty: true,
      emptyRetryBudget: 1,
      emptyRetryCount: 0,
    },
  );

  assert.equal(result.accepted, false);
  assert.equal(result.preserved, true);
  assert.equal(result.shouldRetry, true);
  assert.equal(result.sessions.length, 1);
  assert.equal(result.sessions[0].raw.preview, "cached preview");
});

test("resolveSessionSnapshotUpdate keeps cached rows after retry budget is exhausted", () => {
  const result = resolveSessionSnapshotUpdate(
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "cached preview" },
    })],
    [],
    {
      preserveOnEmpty: true,
      emptyRetryBudget: 1,
      emptyRetryCount: 1,
    },
  );

  assert.equal(result.accepted, true);
  assert.equal(result.preserved, true);
  assert.equal(result.shouldRetry, false);
  assert.equal(result.sessions.length, 1);
  assert.equal(result.sessions[0].raw.preview, "cached preview");
});

test("resolveSessionSnapshotUpdate allows manual refresh to accept authoritative empty snapshots", () => {
  const result = resolveSessionSnapshotUpdate(
    [session({
      id: "thread-a",
      title: "继续phase17 的实现",
      raw: { preview: "cached preview" },
    })],
    [],
    {
      preserveOnEmpty: false,
      emptyRetryBudget: 0,
      emptyRetryCount: 0,
    },
  );

  assert.equal(result.accepted, true);
  assert.equal(result.preserved, false);
  assert.equal(result.shouldRetry, false);
  assert.equal(result.sessions.length, 0);
});

test("nextSelectedSessionId falls back to the first visible session when nothing is selected", () => {
  const nextId = nextSelectedSessionId([
    session({ id: "thread-b", title: "最新会话" }),
    session({ id: "thread-a", title: "旧会话" }),
  ], null);

  assert.equal(nextId, "thread-b");
});

test("nextSelectedSessionId preserves an explicit target while its row is still loading", () => {
  const nextId = nextSelectedSessionId([
    session({ id: "thread-b", title: "最新会话" }),
  ], "thread-pending", { preserveMissing: true });

  assert.equal(nextId, "thread-pending");
});

test("hasPendingSelectedSession reports when a selected session has not hydrated yet", () => {
  assert.equal(hasPendingSelectedSession([
    session({ id: "thread-a" }),
  ], "thread-pending"), true);
  assert.equal(hasPendingSelectedSession([
    session({ id: "thread-a" }),
  ], "thread-a"), false);
  assert.equal(hasPendingSelectedSession([], null), false);
});

test("sessionPreviewText prefers live preview over stale cached preview", () => {
  const preview = sessionPreviewText(session({
    title: "继续phase17 的实现",
    raw: {
      preview: "旧的 cached preview",
      highlightedThreadPreview: "我现在继续通过 event bus 刷新最新摘要。",
      providerActive: true,
    },
  }));

  assert.equal(preview, "通过 event bus 刷新最新摘要。");
});

test("mergeLiveSessionActivities updates matching session preview without replacing stable title", () => {
  const sessions = [
    session({
      id: "thread-a",
      title: "继续 phase17 的实现",
      raw: { updatedAt: 1000 },
    }),
  ];

  const merged = mergeLiveSessionActivities(sessions, [
    {
      providerId: "codex",
      workspaceId: "codex:/tmp/project",
      workspacePath: "/tmp/project",
      sessionId: "thread-a",
      title: "我正在通过事件流更新 Session 列表。",
      status: "running",
      attentionReason: "",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      lastUserMessage: "",
      lastAssistantMessage: "我正在通过事件流更新 Session 列表。",
      lastFinalMessage: "",
      lastEventKind: "message.assistant.delta",
      updatedAt: 1800000000,
    },
  ]);

  assert.equal(merged[0].title, "继续 phase17 的实现");
  assert.equal(merged[0].raw.lastAssistantMessage, "我正在通过事件流更新 Session 列表。");
  assert.equal(merged[0].raw.lastEventKind, "message.assistant.delta");
  assert.equal(sessionPreviewText(merged[0]), "通过事件流更新 Session 列表。");
});

test("mergeLiveSessionActivities creates a live session row when cached list missed it", () => {
  const merged = mergeLiveSessionActivities([], [
    {
      providerId: "codex",
      workspaceId: "codex:/tmp/project",
      workspacePath: "/tmp/project",
      sessionId: "thread-live",
      title: "继续接手这个问题",
      status: "running",
      attentionReason: "",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      lastUserMessage: "继续接手这个问题",
      lastAssistantMessage: "",
      lastFinalMessage: "",
      lastEventKind: "message.user.accepted",
      updatedAt: 1800000000,
    },
  ]);

  assert.equal(merged.length, 1);
  assert.equal(merged[0].id, "thread-live");
  assert.equal(merged[0].workspace, "/tmp/project");
  assert.equal(merged[0].raw.providerActive, true);
  assert.equal(merged[0].raw.lastEventKind, "message.user.accepted");
  assert.equal(sessionPreviewText(merged[0]), "继续接手这个问题");
});

test("mergeLiveSessionActivities does not create a synthetic row for completed stale activity", () => {
  const merged = mergeLiveSessionActivities([], [
    {
      providerId: "codex",
      workspaceId: "codex:/tmp/project",
      workspacePath: "/tmp/project",
      sessionId: "thread-stale",
      title: "你好",
      status: "completed",
      attentionReason: "",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      lastUserMessage: "你好",
      lastAssistantMessage: "旧的摘要",
      lastFinalMessage: "旧的摘要",
      lastEventKind: "message.assistant.final",
      updatedAt: 1800000000,
    },
  ]);

  assert.equal(merged.length, 0);
});

test("mergeLiveSessionActivities ignores completed stale activity when a real session row already exists", () => {
  const merged = mergeLiveSessionActivities([
    session({
      id: "thread-stale",
      title: "继续phase17 的实现",
      raw: {
        preview: "owner bridge 的新 preview",
        updatedAt: 1800000001000,
      },
    }),
  ], [
    {
      providerId: "codex",
      workspaceId: "codex:/tmp/project",
      workspacePath: "/tmp/project",
      sessionId: "thread-stale",
      title: "你好",
      status: "completed",
      attentionReason: "",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      lastUserMessage: "你好",
      lastAssistantMessage: "旧的摘要",
      lastFinalMessage: "旧的摘要",
      lastEventKind: "message.assistant.final",
      updatedAt: 1800000000,
    },
  ]);

  assert.equal(merged[0].title, "继续phase17 的实现");
  assert.equal(merged[0].raw.preview, "owner bridge 的新 preview");
  assert.equal(sessionPreviewText(merged[0]), "owner bridge 的新 preview");
});

test("mergeLiveSessionActivities refreshes timestamps from live activity for sorting", () => {
  const merged = mergeLiveSessionActivities([
    session({
      id: "thread-a",
      title: "旧会话",
      raw: { updatedAt: 1000, createdAt: 900 },
    }),
  ], [
    {
      providerId: "codex",
      workspaceId: "codex:/tmp/project",
      workspacePath: "/tmp/project",
      sessionId: "thread-a",
      title: "旧会话",
      status: "running",
      attentionReason: "",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      lastUserMessage: "",
      lastAssistantMessage: "继续处理排序问题",
      lastFinalMessage: "",
      lastEventKind: "message.assistant.delta",
      updatedAt: 1800000000,
    },
  ]);

  assert.equal(merged[0].raw.updatedAt, 1800000000000);
  assert.equal(merged[0].raw.providerActive, true);
});

test("mergeLiveSessionActivities clears stale live markers when activity disappears", () => {
  const merged = mergeLiveSessionActivities([
    session({
      id: "thread-a",
      title: "旧会话",
      raw: {
        providerActive: true,
        highlightedThreadPreview: "旧的 live preview",
        lastAssistantMessage: "旧的 live preview",
        updatedAt: 1000,
      },
    }),
  ], []);

  assert.equal(merged[0].raw.providerActive, false);
  assert.equal(merged[0].raw.highlightedThreadPreview, "");
  assert.equal(merged[0].raw.lastAssistantMessage, "");
});
