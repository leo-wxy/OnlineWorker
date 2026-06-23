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

const ABSOLUTE_PATH_RE = /(^|\s)(\/(?:Users|Volumes|Applications|private|tmp|var|opt|Library|System)\/[\w./~:-]+)/g;

function sanitizeSummaryText(value) {
  const text = normalizedString(value);
  if (!text) {
    return "";
  }
  return text.replace(ABSOLUTE_PATH_RE, (_, prefix) => `${prefix}[path]`);
}

export function formatSessionPreviewText(value) {
  let text = sanitizeSummaryText(value).replace(/\s+/g, " ");
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

export function sessionPreviewFromRaw(raw) {
  const preview = firstNonEmptyString(
    raw?.highlightedThreadPreview,
    raw?.lastAssistantMessage,
    raw?.last_assistant_message,
    raw?.lastFinalMessage,
    raw?.last_final_message,
    raw?.lastUserMessage,
    raw?.last_user_message,
    raw?.lastUserMessageText,
    raw?.lastMessage,
    raw?.last_message,
    raw?.latestMessage,
    raw?.latest_message,
    raw?.preview,
    raw?.summary,
    raw?.lastAssistantSummary,
    raw?.lastAssistantSummaryText,
  );
  const text = preview ? formatSessionPreviewText(preview) : "";
  return text || null;
}

function isPlaceholderTitle(title, sessionId) {
  const text = normalizedString(title);
  if (!text) {
    return true;
  }
  return text === normalizedString(sessionId);
}

function normalizeActivityTimestamp(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return 0;
  }
  return value > 1_000_000_000_000 ? value : value * 1000;
}

function normalizedActivityStatus(activity) {
  return normalizedString(activity?.status).toLowerCase();
}

function activityCreatesSyntheticSession(activity) {
  const status = normalizedActivityStatus(activity);
  return status === "running" || status === "needs_attention" || status === "failed";
}

export function sessionPreviewText(session) {
  return sessionPreviewFromRaw(session?.raw ?? {});
}

function mergeRawSessionSummary(previousRaw = {}, nextRaw = {}) {
  const mergedPreview = firstNonEmptyString(nextRaw.preview, previousRaw.preview);
  const mergedSummary = firstNonEmptyString(nextRaw.summary, previousRaw.summary);
  const mergedLastMessage = firstNonEmptyString(
    nextRaw.lastMessage,
    nextRaw.last_message,
    previousRaw.lastMessage,
    previousRaw.last_message,
  );

  return {
    ...previousRaw,
    ...nextRaw,
    preview: mergedPreview,
    summary: mergedSummary,
    lastMessage: mergedLastMessage,
  };
}

export function cloneSessionEntry(session) {
  return {
    ...session,
    raw: { ...(session?.raw ?? {}) },
  };
}

export function mergeSessionListSnapshot(previousSessions, nextSessions, options = {}) {
  const preserveOnEmpty = options?.preserveOnEmpty === true;
  if (preserveOnEmpty && (nextSessions ?? []).length === 0 && (previousSessions ?? []).length > 0) {
    return (previousSessions ?? []).map(cloneSessionEntry);
  }

  const previousByKey = new Map(
    (previousSessions ?? []).map((session) => [`${session.type}:${session.id}`, session]),
  );

  return (nextSessions ?? []).map((session) => {
    const key = `${session.type}:${session.id}`;
    const previous = previousByKey.get(key);
    if (!previous) {
      return session;
    }

    const mergedRaw = mergeRawSessionSummary(previous.raw ?? {}, session.raw ?? {});
    const nextTitle = normalizedString(session.title);
    const previousTitle = normalizedString(previous.title);
    const mergedTitle = nextTitle || previousTitle || session.id;

    return {
      ...session,
      title: mergedTitle,
      workspace: normalizedString(session.workspace) || normalizedString(previous.workspace),
      archived: Boolean(session.archived),
      raw: mergedRaw,
    };
  });
}

export function resolveSessionSnapshotUpdate(previousSessions, nextSessions, options = {}) {
  const previous = Array.isArray(previousSessions) ? previousSessions : [];
  const next = Array.isArray(nextSessions) ? nextSessions : [];
  const preserveOnEmpty = options?.preserveOnEmpty === true;
  const emptyRetryBudget = Number.isFinite(options?.emptyRetryBudget)
    ? Math.max(0, Math.trunc(options.emptyRetryBudget))
    : 0;
  const emptyRetryCount = Number.isFinite(options?.emptyRetryCount)
    ? Math.max(0, Math.trunc(options.emptyRetryCount))
    : 0;

  if (next.length === 0 && preserveOnEmpty && previous.length > 0) {
    return {
      sessions: previous.map(cloneSessionEntry),
      accepted: emptyRetryCount >= emptyRetryBudget,
      preserved: true,
      shouldRetry: emptyRetryCount < emptyRetryBudget,
    };
  }

  if (next.length === 0 && emptyRetryCount < emptyRetryBudget) {
    return {
      sessions: previous.map(cloneSessionEntry),
      accepted: false,
      preserved: previous.length > 0,
      shouldRetry: true,
    };
  }

  return {
    sessions: mergeSessionListSnapshot(previous, next),
    accepted: true,
    preserved: false,
    shouldRetry: false,
  };
}

export function nextSelectedSessionId(sessions, selectedSessionId, options = {}) {
  const list = Array.isArray(sessions) ? sessions : [];
  const preserveMissing = options?.preserveMissing === true;
  const currentId = normalizedString(selectedSessionId);
  if (!currentId) {
    return list[0]?.id ?? null;
  }
  if (list.some((session) => session?.id === currentId)) {
    return currentId;
  }
  if (preserveMissing) {
    return currentId;
  }
  return list[0]?.id ?? null;
}

export function hasPendingSelectedSession(sessions, selectedSessionId) {
  const currentId = normalizedString(selectedSessionId);
  if (!currentId) {
    return false;
  }
  const list = Array.isArray(sessions) ? sessions : [];
  return !list.some((session) => session?.id === currentId);
}

export function mergeLiveSessionActivities(sessions, activities) {
  const liveActivities = (activities ?? []).filter(activityCreatesSyntheticSession);
  const activeKeys = new Set(
    liveActivities
      .filter((activity) => activity?.providerId && activity?.sessionId)
      .map((activity) => `${activity.providerId}:${activity.sessionId}`),
  );
  const nextSessions = sessions.map((session) => ({
    ...session,
    raw: {
      ...(session.raw ?? {}),
      ...(activeKeys.has(`${session.type}:${session.id}`)
        ? null
        : {
            providerActive: false,
            highlightedThreadPreview: "",
            lastAssistantMessage: "",
            lastFinalMessage: "",
          }),
    },
  }));
  const sessionIndex = new Map(
    nextSessions.map((session, index) => [`${session.type}:${session.id}`, index]),
  );

  for (const activity of liveActivities) {
    if (!activity?.providerId || !activity?.sessionId) {
      continue;
    }
    const key = `${activity.providerId}:${activity.sessionId}`;
    const title = normalizedString(activity.title);
    const preview = formatSessionPreviewText(
      activity.lastAssistantMessage || activity.lastFinalMessage || activity.lastUserMessage || title,
    );
    const workspace = normalizedString(activity.workspacePath) || normalizedString(activity.workspaceId);
    const providerActive = activity.status === "running" || activity.lastEventKind === "message.assistant.delta";
    const updatedAt = normalizeActivityTimestamp(activity.updatedAt);

    if (sessionIndex.has(key)) {
      const session = nextSessions[sessionIndex.get(key)];
      const raw = {
        ...(session.raw ?? {}),
        providerActive,
        updatedAt: updatedAt || session.raw?.updatedAt || 0,
        createdAt: session.raw?.createdAt || updatedAt || 0,
        lastUserMessage: normalizedString(activity.lastUserMessage) || session.raw?.lastUserMessage || "",
        lastAssistantMessage:
          normalizedString(activity.lastAssistantMessage) || session.raw?.lastAssistantMessage || "",
        lastFinalMessage:
          normalizedString(activity.lastFinalMessage) || session.raw?.lastFinalMessage || "",
        highlightedThreadPreview:
          preview || session.raw?.highlightedThreadPreview || session.raw?.preview || "",
      };
      nextSessions[sessionIndex.get(key)] = {
        ...session,
        workspace: workspace || session.workspace,
        title: !isPlaceholderTitle(session.title, session.id) ? session.title : title || session.title,
        archived: Boolean(session.archived),
        raw,
      };
      continue;
    }

    nextSessions.push({
      id: activity.sessionId,
      type: activity.providerId,
      workspace: workspace || normalizedString(activity.workspacePath) || "",
      title: title || activity.sessionId,
      archived: false,
      raw: {
        providerActive,
        updatedAt,
        createdAt: updatedAt,
        lastUserMessage: normalizedString(activity.lastUserMessage),
        lastAssistantMessage: normalizedString(activity.lastAssistantMessage),
        lastFinalMessage: normalizedString(activity.lastFinalMessage),
        highlightedThreadPreview: preview,
      },
    });
  }

  nextSessions.sort((left, right) => {
    const leftTime = Number(left.raw?.updatedAt ?? left.raw?.createdAt ?? 0);
    const rightTime = Number(right.raw?.updatedAt ?? right.raw?.createdAt ?? 0);
    if (rightTime !== leftTime) {
      return rightTime - leftTime;
    }
    return left.title.localeCompare(right.title);
  });

  return nextSessions;
}
