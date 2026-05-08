export const SESSION_BROWSER_VISIBLE_TURNS = 50;

export function limitSessionTurns(turns) {
  return turns.length <= SESSION_BROWSER_VISIBLE_TURNS
    ? turns
    : turns.slice(-SESSION_BROWSER_VISIBLE_TURNS);
}

export function mergeSessionTurns(existing, incoming) {
  if (incoming.length === 0) {
    return existing;
  }

  const incomingHasCompletedAssistant = incoming.some(
    (turn) => turn.role === "assistant" && turn.pending !== true && turn.content.trim().length > 0,
  );
  const merged = incomingHasCompletedAssistant
    ? existing.filter((turn) => !(turn.role === "assistant" && turn.pending === true))
    : [...existing];
  for (const turn of incoming) {
    const last = merged[merged.length - 1];
    if (last?.role === "assistant" && last?.pending && turn.role === "assistant") {
      merged[merged.length - 1] = {
        ...turn,
        pending: Boolean(turn.pending),
      };
      continue;
    }
    if (last && last.role === turn.role && last.content === turn.content) {
      continue;
    }
    merged.push(turn);
  }

  return limitSessionTurns(merged);
}
