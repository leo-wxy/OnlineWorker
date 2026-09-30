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

export function getLastAssistantSignature(snapshot) {
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
