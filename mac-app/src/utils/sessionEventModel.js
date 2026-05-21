import {
  mergeSessionTurns,
} from "./sessionTurnMerge.js";

function normalizeSessionTurn(turn) {
  if (!turn?.role || !turn?.content) {
    return null;
  }

  const role = turn.role === "user" ? "user" : turn.role === "assistant" ? "assistant" : null;
  const content = String(turn.content).trim();
  if (!role || !content) {
    return null;
  }

  const displayMode = role === "assistant" && turn.displayMode === "markdown"
    ? "markdown"
    : "plain";

  return {
    role,
    content,
    displayMode,
    ...(turn.timestamp ? { timestamp: turn.timestamp } : {}),
    ...(turn.pending ? { pending: true } : {}),
  };
}

function appendSessionTurn(turns, turn) {
  const normalizedTurn = normalizeSessionTurn(turn);
  if (!normalizedTurn) {
    return turns;
  }

  const last = turns[turns.length - 1];
  return mergeSessionTurns(turns, [normalizedTurn]);
}

function replaceLastSessionTurn(turns, turn) {
  const normalizedTurn = normalizeSessionTurn(turn);
  if (!normalizedTurn || turns.length === 0) {
    return turns;
  }

  const next = [...turns];
  next[next.length - 1] = normalizedTurn;
  return next;
}

function replaceTrailingUserTurnBeforePendingAssistant(turns, turn) {
  const normalizedTurn = normalizeSessionTurn(turn);
  if (!normalizedTurn || normalizedTurn.role !== "user" || turns.length < 2) {
    return null;
  }

  const last = turns[turns.length - 1];
  const previous = turns[turns.length - 2];
  if (!isPendingAssistantTurn(last) || previous?.role !== "user") {
    return null;
  }

  const candidate = mergeSessionTurns([previous], [normalizedTurn]);
  if (candidate.length !== 1) {
    return null;
  }

  const next = [...turns];
  next[next.length - 2] = candidate[0];
  return next;
}

function isPendingAssistantTurn(turn) {
  return turn?.role === "assistant" && turn?.pending === true;
}

export function buildAbortedSessionTurn(reason, partialText = "") {
  const base = typeof partialText === "string" ? partialText.trim() : "";
  if (!base) {
    return null;
  }

  return {
    role: "assistant",
    content: base,
    displayMode: "plain",
  };
}

export function applySessionStreamEvent(turns, event) {
  const eventKind = typeof event?.kind === "string" && event.kind
    ? event.kind
    : typeof event?.semanticKind === "string" && event.semanticKind
      ? event.semanticKind
      : null;

  if (!Array.isArray(turns) || !eventKind) {
    return Array.isArray(turns) ? turns : [];
  }

  switch (eventKind) {
    case "replace_snapshot":
      return Array.isArray(event.snapshot)
        ? event.snapshot.reduce((acc, turn) => appendSessionTurn(acc, turn), [])
        : turns;
    case "assistant_progress":
      if (isPendingAssistantTurn(turns[turns.length - 1])) {
        return replaceLastSessionTurn(turns, {
          ...event.turn,
          displayMode: "plain",
          pending: true,
        });
      }
      return appendSessionTurn(turns, {
        ...event.turn,
        displayMode: "plain",
        pending: true,
      });
    case "assistant_completed":
      if (isPendingAssistantTurn(turns[turns.length - 1])) {
        return replaceLastSessionTurn(turns, {
          ...event.turn,
          displayMode: "markdown",
          pending: false,
        });
      }
      return appendSessionTurn(turns, {
        ...event.turn,
        displayMode: "markdown",
        pending: false,
      });
    case "user_message":
      {
        const replaced = replaceTrailingUserTurnBeforePendingAssistant(turns, {
          ...event.turn,
          displayMode: "plain",
          pending: false,
        });
        if (replaced) {
          return replaced;
        }
      }
      return appendSessionTurn(turns, {
        ...event.turn,
        displayMode: "plain",
        pending: false,
      });
    case "turn_aborted":
      if (isPendingAssistantTurn(turns[turns.length - 1])) {
        const abortedTurn = buildAbortedSessionTurn(event.reason, turns[turns.length - 1]?.content);
        return abortedTurn
          ? replaceLastSessionTurn(turns, abortedTurn)
          : turns.slice(0, -1);
      }
      return appendSessionTurn(turns, buildAbortedSessionTurn(event.reason));
    default:
      return turns;
  }
}
