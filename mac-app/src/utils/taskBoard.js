import { formatSessionPreviewText, sessionPreviewFromRaw } from "./sessionBrowserState.js";

const BOARD_LANE_LIMIT = 12;

function normalizeTimestamp(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value > 1_000_000_000_000 ? value : value * 1000;
}

export function isLowSignalTaskBoardText(value) {
  const text = normalizedBoardText(value).toLowerCase();
  if (!text) {
    return true;
  }
  if (text.length <= 2) {
    return true;
  }
  return ["ok", "done", "yes", "no", "test", "ping"].includes(text);
}

export function taskBoardActivityKey(activity) {
  return `${activity.providerId}:${activity.sessionId}`;
}

export function taskBoardSessionKey(providerId, sessionId) {
  return `${providerId}:${sessionId}`;
}

export function upsertTaskBoardActivity(activities, activity) {
  const key = taskBoardActivityKey(activity);
  const next = activities.filter((item) => taskBoardActivityKey(item) !== key);
  next.unshift(activity);
  return next;
}

export function removeTaskBoardActivity(activities, providerId, sessionId) {
  return activities.filter((item) => item.providerId !== providerId || item.sessionId !== sessionId);
}

function normalizedBoardText(value) {
  return typeof value === "string" ? value.trim().replace(/\s+/g, " ") : "";
}

function readSessionTimestamp(session) {
  const raw = session?.raw ?? {};
  return normalizeTimestamp(
    raw.updatedAt ??
      raw.updated_at ??
      raw.lastUpdatedAt ??
      raw.last_updated_at ??
      raw.createdAt ??
      raw.created_at,
  );
}

function providerLabelFor(providerLabels, providerId) {
  return providerLabels[providerId] || providerId;
}

function isUuidLike(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
    normalizedString(value),
  );
}

function isTruncatedUuidLike(value) {
  return /^[0-9a-f]{8}(?:-[0-9a-f]{1,4}){1,4}$/i.test(normalizedString(value));
}

function isPlaceholderTitle(title, sessionId) {
  const text = normalizedString(title);
  return (
    !text ||
    text === normalizedString(sessionId) ||
    isUuidLike(text) ||
    isTruncatedUuidLike(text) ||
    isLowSignalTaskBoardText(text)
  );
}

function sessionTitle(session) {
  const title = normalizedString(session.title);
  if (!isPlaceholderTitle(title, session.id)) {
    return title;
  }
  const preview = sessionPreview(session);
  if (preview && !isPlaceholderTitle(preview, session.id)) {
    return preview.slice(0, 160);
  }
  return title || session.id;
}

function shortSessionLabel(sessionId) {
  const text = normalizedString(sessionId);
  return text.length > 12 ? text.slice(0, 12) : text;
}

function activityTitle(activity, session) {
  const sessionId = normalizedString(activity.sessionId);
  const sessionLabel = normalizedString(session?.title);
  if (!isPlaceholderTitle(sessionLabel, sessionId)) {
    return sessionLabel;
  }
  const rawTitle = normalizedString(activity.title);
  if (!isPlaceholderTitle(rawTitle, sessionId)) {
    return rawTitle;
  }
  const userMessage = normalizedString(activity.lastUserMessage);
  if (userMessage) {
    return userMessage.slice(0, 160);
  }
  return shortSessionLabel(sessionId) || "未命名任务";
}

function sessionPreview(session) {
  return sessionPreviewFromRaw(session?.raw ?? {});
}

function activityPreview(activity) {
  const status = normalizedString(activity.status).toLowerCase();
  const eventKind = normalizedString(activity.lastEventKind);
  const lastAssistantMessage = formatSessionPreviewText(activity.lastAssistantMessage);
  const lastFinalMessage = formatSessionPreviewText(activity.lastFinalMessage);
  const attentionReason = normalizedString(activity.attentionReason);
  const lastUserMessage = formatSessionPreviewText(activity.lastUserMessage);

  if (status === "running" || eventKind === "message.assistant.delta") {
    return lastAssistantMessage || attentionReason || lastUserMessage || null;
  }
  if (status === "needs_attention" || status === "failed") {
    return attentionReason || lastAssistantMessage || lastUserMessage || lastFinalMessage || null;
  }
  return lastFinalMessage || lastAssistantMessage || attentionReason || lastUserMessage || null;
}

function normalizedString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function activityStatusReason(activity, fallback) {
  const attentionReason = normalizedString(activity.attentionReason);
  if (attentionReason) {
    return attentionReason;
  }
  return fallback === "需要处理" ? fallback : "";
}

function activityNeedsAttention(activity) {
  const status = normalizedString(activity.status).toLowerCase();
  return status === "needs_attention" || status === "failed";
}

function activityRunning(activity) {
  return normalizedString(activity.status).toLowerCase() === "running";
}

function sessionRefSet(refs) {
  return new Set(
    (refs ?? [])
      .map((item) => taskBoardSessionKey(item.providerId, item.sessionId))
      .filter((value) => value !== ":"),
  );
}

function compareTasks(left, right) {
  const leftTime = left.updatedAtEpochMs ?? 0;
  const rightTime = right.updatedAtEpochMs ?? 0;
  if (rightTime !== leftTime) {
    return rightTime - leftTime;
  }
  return left.title.localeCompare(right.title);
}

function attentionPriority(task) {
  if (!task.mirroredOnly && ["approval", "question"].includes(task.attentionKind)) {
    return 0;
  }
  return task.mirroredOnly ? 2 : 1;
}

function compareAttentionTasks(left, right) {
  const priorityDifference = attentionPriority(left) - attentionPriority(right);
  if (priorityDifference !== 0) {
    return priorityDifference;
  }
  const leftTime = left.updatedAtEpochMs ?? Number.MAX_SAFE_INTEGER;
  const rightTime = right.updatedAtEpochMs ?? Number.MAX_SAFE_INTEGER;
  if (leftTime !== rightTime) {
    return leftTime - rightTime;
  }
  return left.title.localeCompare(right.title);
}

export function buildTaskBoardModel({
  sessions,
  sessionActivities = [],
  dashboardState,
  taskBoardState,
  providerLabels,
  nowEpochMs = Date.now(),
}) {
  const generatedAtEpochMs = normalizeTimestamp(dashboardState?.generatedAtEpoch) ?? nowEpochMs;
  const pinnedKeys = sessionRefSet(taskBoardState?.pinned);
  const sessionsByKey = new Map(
    sessions.map((session) => [taskBoardSessionKey(session.type, session.id), session]),
  );

  const tasks = sessionActivities.flatMap((activity) => {
    const providerId = normalizedString(activity.providerId);
    const sessionId = normalizedString(activity.sessionId);
    if (!providerId || !sessionId) {
      return [];
    }
    const key = taskBoardSessionKey(providerId, sessionId);
    const session = sessionsByKey.get(key);
    const needsAttention = activityNeedsAttention(activity);
    const status = normalizedString(activity.status).toLowerCase();
    const attentionKind = normalizedString(activity.attentionKind).toLowerCase();
    const interrupted = status === "completed" && attentionKind === "interrupted";
    const recentEnded = status === "completed";
    const running = !needsAttention && activityRunning(activity);
    const pinned = pinnedKeys.has(key);
    const title = activityTitle({ ...activity, sessionId }, session);
    const fallbackReason = needsAttention
      ? "需要处理"
      : running
        ? "正在执行"
        : pinned
          ? "关注中"
          : "";
    const preview = activityPreview(activity);

    return [{
      id: key,
      sessionId,
      providerId,
      providerLabel: providerLabelFor(providerLabels, providerId),
      title,
      workspace: normalizedString(activity.workspacePath) ||
        normalizedString(activity.workspaceId) ||
        normalizedString(session?.workspace),
      workspaceId: normalizedString(activity.workspaceId),
      workspacePath: normalizedString(activity.workspacePath),
      preview,
      archived: Boolean(session?.archived),
      needsAttention,
      status,
      attentionKind,
      requestId: normalizedString(activity.requestId),
      approvalSource: normalizedString(activity.approvalSource),
      mirroredOnly: activity.mirroredOnly === true,
      canInterrupt: activity.canInterrupt === true,
      canRecover: activity.canRecover === true,
      controlReason: normalizedString(activity.controlReason),
      controlMode: normalizedString(activity.controlMode) || "external",
      recentEvents: Array.isArray(activity.recentEvents) ? activity.recentEvents.slice(0, 5) : [],
      conversationTurns: Array.isArray(activity.conversationTurns) ? activity.conversationTurns : [],
      lastUserMessage: normalizedString(activity.lastUserMessage),
      lastAssistantMessage: normalizedString(activity.lastAssistantMessage),
      interrupted,
      canContinue: interrupted && normalizedString(activity.controlMode) === "owned",
      recentEnded,
      running,
      pinned,
      statusReason: activityStatusReason(activity, fallbackReason),
      recentEvent: normalizedString(activity.lastEventKind) || null,
      updatedAtEpochMs: normalizeTimestamp(activity.updatedAt),
    }];
  });
  const projectedKeys = new Set(tasks.map((task) => task.id));

  sessions.forEach((session) => {
    const updatedAtEpochMs = readSessionTimestamp(session);
    const key = taskBoardSessionKey(session.type, session.id);
    if (projectedKeys.has(key)) {
      return;
    }
    const needsAttention = false;
    const running = false;
    const pinned = pinnedKeys.has(key);
    const title = sessionTitle(session);
    const preview = null;

    tasks.push({
      id: key,
      sessionId: session.id,
      providerId: session.type,
      providerLabel: providerLabelFor(providerLabels, session.type),
      title,
      workspace: session.workspace,
      workspaceId: "",
      workspacePath: session.workspace,
      preview,
      archived: session.archived,
      needsAttention,
      status: needsAttention ? "needs_attention" : running ? "running" : "idle",
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      canInterrupt: false,
      canRecover: false,
      controlReason: "",
      controlMode: "external",
      recentEvents: [],
      conversationTurns: [],
      lastUserMessage: "",
      lastAssistantMessage: normalizedString(preview),
      interrupted: false,
      canContinue: false,
      recentEnded: false,
      running,
      pinned,
      statusReason: "",
      recentEvent: null,
      updatedAtEpochMs,
    });
  });

  const boardTasks = tasks.filter((task) => {
    if (task.archived) {
      return false;
    }
    if (task.needsAttention || task.running) {
      return true;
    }
    return task.recentEnded || task.pinned;
  });

  const needsAttentionTasks = boardTasks
    .filter((task) => task.needsAttention)
    .sort(compareAttentionTasks)
    .slice(0, BOARD_LANE_LIMIT);
  const needsAttentionTaskKeys = new Set(needsAttentionTasks.map((task) => task.id));
  const runningTasks = boardTasks
    .filter((task) => !needsAttentionTaskKeys.has(task.id) && task.running)
    .sort(compareTasks)
    .slice(0, BOARD_LANE_LIMIT);
  const runningTaskKeys = new Set(runningTasks.map((task) => task.id));
  const pinnedIdleTasks = boardTasks
    .filter((task) => !needsAttentionTaskKeys.has(task.id) && !runningTaskKeys.has(task.id) && task.pinned)
    .sort(compareTasks)
    .slice(0, BOARD_LANE_LIMIT);
  const recentEndedTasks = boardTasks
    .filter((task) => !needsAttentionTaskKeys.has(task.id) && !runningTaskKeys.has(task.id) && (task.recentEnded || task.pinned))
    .sort(compareTasks)
    .slice(0, BOARD_LANE_LIMIT);

  return {
    needsAttention: needsAttentionTasks,
    running: runningTasks,
    pinnedIdle: pinnedIdleTasks,
    recentEnded: recentEndedTasks,
    counts: {
      needsAttention: boardTasks.filter((task) => task.needsAttention).length,
      running: boardTasks.filter((task) => !task.needsAttention && task.running).length,
      pinnedIdle: boardTasks.filter((task) => !task.needsAttention && !task.running && task.pinned).length,
      recentEnded: boardTasks.filter((task) => !task.needsAttention && !task.running && (task.recentEnded || task.pinned)).length,
      total: tasks.length,
    },
    generatedAtEpochMs,
  };
}
