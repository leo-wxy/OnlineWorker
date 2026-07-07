/**
 * 统计快照里的 assistant 条目数。
 *
 * @param {Array<{ role?: string }>} snapshot
 * @returns {number}
 */
export function countAssistantEntries(snapshot) {
  return snapshot.reduce(
    (count, item) => count + (item?.role === "assistant" && item?.pending !== true ? 1 : 0),
    0,
  );
}

function buildTurnSignature(turn) {
  if (!turn || turn.role !== "assistant" || turn.pending === true) {
    return null;
  }

  const content = typeof turn.content === "string" ? turn.content.trim() : "";
  if (!content) {
    return null;
  }

  return JSON.stringify({
    role: turn.role,
    content,
    timestamp: turn.timestamp ?? null,
  });
}

function getLastAssistantSignature(snapshot) {
  if (!Array.isArray(snapshot)) {
    return null;
  }

  for (let index = snapshot.length - 1; index >= 0; index -= 1) {
    const signature = buildTurnSignature(snapshot[index]);
    if (signature) {
      return signature;
    }
  }

  return null;
}

export function hasAdvancedAssistantReply(previousSnapshot, nextSnapshot) {
  if (countAssistantEntries(nextSnapshot) > countAssistantEntries(previousSnapshot)) {
    return true;
  }

  const nextSignature = getLastAssistantSignature(nextSnapshot);
  if (!nextSignature) {
    return false;
  }

  return nextSignature !== getLastAssistantSignature(previousSnapshot);
}

/**
 * 生成快照签名，用于判断内容是否还在变化。
 *
 * @param {unknown} snapshot
 * @returns {string}
 */
export function buildSnapshotSignature(snapshot) {
  return JSON.stringify(snapshot);
}

export function hasSessionSnapshotChanged(
  currentSnapshot,
  nextSnapshot,
  getSignature = buildSnapshotSignature,
) {
  return getSignature(currentSnapshot ?? []) !== getSignature(nextSnapshot ?? []);
}

export function startActiveSessionRefresh({
  intervalMs = 3000,
  getCurrentSnapshot,
  loadSnapshot,
  onSnapshot,
  shouldSkip = () => false,
  setTimer = (callback, timeoutMs) => setTimeout(callback, timeoutMs),
  clearTimer = (timer) => clearTimeout(timer),
  onError = (error) => {
    console.warn("active session refresh failed", error);
  },
}) {
  let stopped = false;
  let timer = null;

  const schedule = () => {
    if (stopped) {
      return;
    }
    timer = setTimer(tick, intervalMs);
  };

  const tick = async () => {
    if (stopped) {
      return;
    }

    try {
      if (!shouldSkip()) {
        const nextSnapshot = await loadSnapshot();
        if (
          !stopped &&
          hasSessionSnapshotChanged(getCurrentSnapshot(), nextSnapshot)
        ) {
          onSnapshot(nextSnapshot);
        }
      }
    } catch (error) {
      if (!stopped) {
        onError(error);
      }
    } finally {
      schedule();
    }
  };

  schedule();

  return () => {
    stopped = true;
    if (timer !== null) {
      clearTimer(timer);
    }
  };
}

/**
 * 轮询 assistant 回复，并返回“是否真正稳定收到回复”的状态。
 *
 * @template T
 * @param {{
 *   loadSnapshot: () => Promise<T[]>,
 *   getAssistantCount: (snapshot: T[]) => number,
 *   getSignature: (snapshot: T[]) => string,
 *   baselineAssistantCount: number,
 *   baselineSnapshot?: T[],
 *   onUpdate?: (snapshot: T[]) => void,
 *   intervalMs?: number,
 *   maxAttempts?: number,
 *   stablePollsRequired?: number,
 *   shouldContinue?: () => boolean,
 * }} options
 * @returns {Promise<{
 *   snapshot: T[],
 *   settled: boolean,
 *   assistantAppeared: boolean,
 *   cancelled: boolean,
 * }>}
 */
export async function pollAssistantReply(options) {
  const {
    loadSnapshot,
    getAssistantCount,
    getSignature,
    baselineAssistantCount,
    baselineSnapshot,
    onUpdate,
    intervalMs = 500,
    maxAttempts = 20,
    stablePollsRequired = 2,
    shouldContinue = () => true,
  } = options;

  let latestSnapshot = await loadSnapshot();
  onUpdate?.(latestSnapshot);

  let lastSignature = getSignature(latestSnapshot);
  let stablePolls = 0;

  for (let attempt = 1; attempt < maxAttempts; attempt += 1) {
    const assistantCount = getAssistantCount(latestSnapshot);
    const assistantAppeared = assistantCount > baselineAssistantCount ||
      (Array.isArray(baselineSnapshot) && hasAdvancedAssistantReply(baselineSnapshot, latestSnapshot));
    if (assistantAppeared && stablePolls >= stablePollsRequired) {
      return {
        snapshot: latestSnapshot,
        settled: true,
        assistantAppeared: true,
        cancelled: false,
      };
    }

    if (!shouldContinue()) {
      return {
        snapshot: latestSnapshot,
        settled: false,
        assistantAppeared,
        cancelled: true,
      };
    }

    if (intervalMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    if (!shouldContinue()) {
      return {
        snapshot: latestSnapshot,
        settled: false,
        assistantAppeared,
        cancelled: true,
      };
    }

    latestSnapshot = await loadSnapshot();
    onUpdate?.(latestSnapshot);

    const nextSignature = getSignature(latestSnapshot);
    stablePolls = nextSignature === lastSignature ? stablePolls + 1 : 0;
    lastSignature = nextSignature;
  }

  return {
    snapshot: latestSnapshot,
    settled: false,
    assistantAppeared: getAssistantCount(latestSnapshot) > baselineAssistantCount ||
      (Array.isArray(baselineSnapshot) && hasAdvancedAssistantReply(baselineSnapshot, latestSnapshot)),
    cancelled: false,
  };
}
