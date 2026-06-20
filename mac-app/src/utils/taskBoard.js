const BOARD_LANE_LIMIT = 12;
const ABSOLUTE_PATH_RE = /(^|\s)(\/(?:Users|Volumes|Applications|private|tmp|var|opt|Library|System)\/[\w./~:-]+)/g;

const NEEDS_ATTENTION_STATUSES = new Set([
  "approval_requested",
  "blocked",
  "failed",
  "needs_attention",
  "question_waiting",
  "waiting",
  "waiting_for_approval",
  "waiting_for_input",
]);

const RUNNING_STATUSES = new Set([
  "active",
  "assistant_progress",
  "in_progress",
  "running",
  "streaming",
  "tool_started",
]);

function normalizeTimestamp(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return null;
  }
  return value > 1_000_000_000_000 ? value : value * 1000;
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

function preferSessionPreviewOverActivity({ activityPreviewText, session, activity, title }) {
  const sessionText = uniquePreview(
    sessionPreview(session) ||
      activityPreviewFallback({ ...activity, sessionId: normalizedString(activity.sessionId) }, title),
    title,
  );
  const activityText = activityPreviewText || null;
  if (!sessionText) {
    return activityText;
  }
  if (!activityText) {
    return sessionText;
  }
  const sessionUpdatedAt = readSessionTimestamp(session) ?? 0;
  const activityUpdatedAt = normalizeTimestamp(activity?.updatedAt) ?? 0;
  if (sessionUpdatedAt > activityUpdatedAt) {
    return sessionText;
  }
  return activityText;
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

function isLowSignalTitleText(value) {
  const text = normalizedString(value).toLowerCase();
  if (!text) {
    return true;
  }
  if (text.length <= 2) {
    return true;
  }
  return ["ok", "done", "yes", "no", "test", "ping"].includes(text);
}

function isPlaceholderTitle(title, sessionId) {
  const text = normalizedString(title);
  return (
    !text ||
    text === normalizedString(sessionId) ||
    isUuidLike(text) ||
    isTruncatedUuidLike(text) ||
    isLowSignalTitleText(text)
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
  const raw = session?.raw ?? {};
  const preview = firstNonEmptyString(
    raw.highlightedThreadPreview,
    raw.lastAssistantMessage,
    raw.last_assistant_message,
    raw.lastFinalMessage,
    raw.last_final_message,
    raw.lastUserMessage,
    raw.last_user_message,
    raw.lastMessage,
    raw.last_message,
    raw.latestMessage,
    raw.latest_message,
    raw.preview,
    raw.summary,
  );
  const text = preview ? previewText(preview) : "";
  return text || null;
}

function activityPreview(activity) {
  const status = normalizedString(activity.status).toLowerCase();
  const eventKind = normalizedString(activity.lastEventKind);
  const lastAssistantMessage = previewText(activity.lastAssistantMessage);
  const lastFinalMessage = previewText(activity.lastFinalMessage);
  const attentionReason = normalizedString(activity.attentionReason);
  const lastUserMessage = previewText(activity.lastUserMessage);

  if (status === "running" || eventKind === "message.assistant.delta") {
    return lastAssistantMessage || attentionReason || lastUserMessage || null;
  }
  if (status === "needs_attention" || status === "failed") {
    return attentionReason || lastAssistantMessage || lastUserMessage || lastFinalMessage || null;
  }
  return lastFinalMessage || lastAssistantMessage || attentionReason || lastUserMessage || null;
}

function activityPreviewFallback(activity, title) {
  const sessionId = normalizedString(activity.sessionId);
  const text = previewText(activity.lastUserMessage) || previewText(activity.title) || previewText(title);
  if (!text || isPlaceholderTitle(text, sessionId)) {
    return null;
  }
  return text;
}

function normalizedString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function firstNonEmptyString(...values) {
  for (const value of values) {
    const text = normalizedString(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function previewText(value) {
  let text = normalizedString(value)
    .replace(ABSOLUTE_PATH_RE, (_, prefix) => `${prefix}[path]`)
    .replace(/\s+/g, " ");
  for (let index = 0; index < 4; index += 1) {
    const next = text
      .replace(/^你说得对[，。:：]\s*/, "")
      .replace(/^是[，,]\s*/, "")
      .replace(/^我明白[^。！？:：]*[。！？:：]\s*/, "")
      .replace(/^可以结合\s*hook[，,，]\s*但位置要放对[:：]\s*/i, "")
      .replace(/^我(?:现在|继续|正在|先|会)(?:继续|先|会|正在)?\s*/, "")
      .replace(/^现在我(?:继续|正在|先|会)?\s*/, "")
      .trim();
    if (next === text) {
      break;
    }
    text = next;
  }
  return text;
}

function meaningfulPreview(preview, title, fallback) {
  const text = normalizedString(preview);
  const normalizedTitle = previewText(title);
  if (text && text !== normalizedTitle) {
    return text;
  }
  const fallbackText = normalizedString(fallback);
  return fallbackText && fallbackText !== normalizedTitle ? fallbackText : null;
}

function uniquePreview(preview, title) {
  const text = normalizedString(preview);
  return text && text !== previewText(title) ? text : null;
}

function activityStatusReason(activity, fallback) {
  const attentionReason = normalizedString(activity.attentionReason);
  if (attentionReason) {
    return attentionReason;
  }
  return fallback === "需要处理" ? fallback : "";
}

function readStatusValue(raw) {
  return normalizedString(
    raw.status ??
      raw.state ??
      raw.runtimeStatus ??
      raw.runtime_status ??
      raw.lastEvent ??
      raw.last_event ??
      raw.event ??
      raw.eventName ??
      raw.event_name,
  ).toLowerCase();
}

function readRecentEvent(raw) {
  const event = normalizedString(
    raw.lastEvent ??
      raw.last_event ??
      raw.event ??
      raw.eventName ??
      raw.event_name ??
      raw.status ??
      raw.state,
  );
  return event || null;
}

function hasNeedsAttentionSignal(raw) {
  if (
    raw.needsAttention === true ||
    raw.needs_attention === true ||
    raw.waitingForInput === true ||
    raw.waiting_for_input === true ||
    raw.approvalRequested === true ||
    raw.approval_requested === true
  ) {
    return true;
  }
  return NEEDS_ATTENTION_STATUSES.has(readStatusValue(raw));
}

function hasRunningSignal(raw) {
  if (
    raw.running === true ||
    raw.isRunning === true ||
    raw.is_running === true ||
    raw.streaming === true ||
    raw.inProgress === true ||
    raw.in_progress === true
  ) {
    return true;
  }
  return RUNNING_STATUSES.has(readStatusValue(raw));
}

function activityNeedsAttention(activity) {
  const status = normalizedString(activity.status).toLowerCase();
  return status === "needs_attention" || status === "failed";
}

function activityRunning(activity) {
  return normalizedString(activity.status).toLowerCase() === "running";
}

function readProviderActiveSignal(raw) {
  if (
    raw.providerActive === true ||
    raw.provider_active === true ||
    raw.ownerBridgeActive === true ||
    raw.owner_bridge_active === true
  ) {
    return true;
  }
  if (
    raw.providerActive === false ||
    raw.provider_active === false ||
    raw.ownerBridgeActive === false ||
    raw.owner_bridge_active === false
  ) {
    return false;
  }
  return null;
}

function hasStrongActiveRecentActivity(recentActivity) {
  if (!recentActivity) {
    return false;
  }
  const activeSessionId = normalizedString(recentActivity.activeSessionId);
  if (!activeSessionId) {
    return false;
  }
  const preview = previewText(recentActivity.highlightedThreadPreview || "");
  return !isPlaceholderTitle(preview, activeSessionId) && !isLowSignalTitleText(preview);
}

function taskBoardKey(providerId, sessionId) {
  return `${providerId}:${sessionId}`;
}

function sessionRefSet(refs) {
  return new Set(
    (refs ?? [])
      .map((item) => taskBoardKey(item.providerId, item.sessionId))
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

export function buildTaskBoardModel({
  sessions,
  sessionActivities = [],
  dashboardState,
  taskBoardState,
  providerLabels,
  nowEpochMs = Date.now(),
}) {
  const recentActivity = dashboardState?.recentActivity ?? null;
  const activeSessionId = recentActivity?.activeSessionId?.trim() || null;
  const activeProviderId =
    recentActivity?.activeSessionTool?.trim() ||
    recentActivity?.activeTool?.trim() ||
    null;
  const activeWorkspacePath = recentActivity?.activeWorkspacePath?.trim() || null;
  const hasStrongActiveSession = hasStrongActiveRecentActivity(recentActivity);
  const generatedAtEpochMs = normalizeTimestamp(dashboardState?.generatedAtEpoch) ?? nowEpochMs;
  const pinnedKeys = sessionRefSet(taskBoardState?.pinned);
  const sessionsByKey = new Map(
    sessions.map((session) => [taskBoardKey(session.type, session.id), session]),
  );
  const activeSessionKey =
    activeSessionId && activeProviderId
      ? taskBoardKey(activeProviderId, activeSessionId)
      : null;
  const activeRecentSession = activeSessionKey ? sessionsByKey.get(activeSessionKey) : null;
  const activeRecentSessionProviderActive = activeRecentSession
    ? readProviderActiveSignal(activeRecentSession.raw ?? {})
    : null;
  const allowDashboardActiveSession =
    hasStrongActiveSession && activeRecentSessionProviderActive !== false;

  const tasks = sessionActivities.flatMap((activity) => {
    const providerId = normalizedString(activity.providerId);
    const sessionId = normalizedString(activity.sessionId);
    if (!providerId || !sessionId) {
      return [];
    }
    const key = taskBoardKey(providerId, sessionId);
    const session = sessionsByKey.get(key);
    const needsAttention = activityNeedsAttention(activity);
    const providerActive = readProviderActiveSignal(session?.raw ?? {});
    const running = !needsAttention && activityRunning(activity) && providerActive !== false;
    const pinned = pinnedKeys.has(key);
    const title = activityTitle({ ...activity, sessionId }, session);
    const fallbackReason = needsAttention
      ? "需要处理"
      : running
        ? "正在执行"
        : pinned
          ? "关注中"
          : "";
    const activityPreviewText = normalizedString(activityPreview(activity));
    const preview = preferSessionPreviewOverActivity({
      activityPreviewText,
      session,
      activity: { ...activity, sessionId },
      title,
    });

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
      attentionKind: normalizedString(activity.attentionKind).toLowerCase(),
      requestId: normalizedString(activity.requestId),
      approvalSource: normalizedString(activity.approvalSource),
      mirroredOnly: activity.mirroredOnly === true,
      running,
      pinned,
      statusReason: activityStatusReason(activity, fallbackReason),
      recentEvent: providerActive === true ? "provider_active" : normalizedString(activity.lastEventKind) || null,
      updatedAtEpochMs: normalizeTimestamp(activity.updatedAt),
    }];
  });
  const projectedKeys = new Set(tasks.map((task) => task.id));

  sessions.forEach((session) => {
    const raw = session.raw ?? {};
    const updatedAtEpochMs = readSessionTimestamp(session);
    const isActive =
      allowDashboardActiveSession &&
      Boolean(activeSessionId) &&
      session.id === activeSessionId &&
      (!activeProviderId || session.type === activeProviderId);
    const providerActive = readProviderActiveSignal(raw) === true;
    const key = taskBoardKey(session.type, session.id);
    if (projectedKeys.has(key)) {
      return;
    }
    const needsAttention = hasNeedsAttentionSignal(raw);
    const running = !needsAttention && (isActive || providerActive);
    const pinned = pinnedKeys.has(key);
    const title = sessionTitle(session);
    const fallbackReason = needsAttention
      ? "需要处理"
      : running
        ? "正在执行"
        : pinned
          ? "关注中"
          : "";
    const sessionPreviewText = sessionPreview(session);
    const activePreviewText = previewText(recentActivity?.highlightedThreadPreview || "");
    const rawPreview = isActive
      ? meaningfulPreview(activePreviewText, title, sessionPreviewText || "")
      : providerActive
        ? sessionPreviewText
        : sessionPreviewText;
    const preview = pinned
      ? uniquePreview(rawPreview, title)
      : meaningfulPreview(rawPreview, title, "");

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
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      running,
      pinned,
      statusReason: needsAttention || running ? fallbackReason : "",
      recentEvent: isActive ? "active_session" : providerActive ? "provider_active" : readRecentEvent(raw),
      updatedAtEpochMs: isActive ? Math.max(updatedAtEpochMs ?? 0, generatedAtEpochMs) : updatedAtEpochMs,
    });
  });

  if (
    allowDashboardActiveSession &&
    activeSessionId &&
    !tasks.some((task) => task.sessionId === activeSessionId && (!activeProviderId || task.providerId === activeProviderId)) &&
    (activeWorkspacePath || recentActivity?.highlightedThreadPreview)
  ) {
    const providerId = activeProviderId || "unknown";
    const key = taskBoardKey(providerId, activeSessionId);
    tasks.push({
      id: key,
      sessionId: activeSessionId,
      providerId,
      providerLabel: providerLabelFor(providerLabels, providerId),
      title: recentActivity?.highlightedThreadPreview || activeSessionId,
      workspace: activeWorkspacePath || recentActivity?.activeWorkspaceName || "",
      workspaceId: "",
      workspacePath: activeWorkspacePath || "",
      preview: uniquePreview(recentActivity?.highlightedThreadPreview, recentActivity?.highlightedThreadPreview || activeSessionId),
      archived: false,
      needsAttention: false,
      attentionKind: "",
      requestId: "",
      approvalSource: "",
      mirroredOnly: false,
      running: true,
      pinned: pinnedKeys.has(key),
      statusReason: "正在执行",
      recentEvent: "active_session",
      updatedAtEpochMs: generatedAtEpochMs,
    });
  }

  const boardTasks = tasks.filter((task) => {
    if (task.archived) {
      return false;
    }
    if (task.needsAttention || task.running) {
      return true;
    }
    return task.pinned;
  });

  const needsAttentionTasks = boardTasks
    .filter((task) => task.needsAttention)
    .sort(compareTasks)
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

  return {
    needsAttention: needsAttentionTasks,
    running: runningTasks,
    pinnedIdle: pinnedIdleTasks,
    counts: {
      needsAttention: boardTasks.filter((task) => task.needsAttention).length,
      running: boardTasks.filter((task) => !task.needsAttention && task.running).length,
      pinnedIdle: boardTasks.filter((task) => !task.needsAttention && !task.running && task.pinned).length,
      total: tasks.length,
    },
    generatedAtEpochMs,
  };
}
