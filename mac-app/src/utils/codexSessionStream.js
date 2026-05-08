import {
  applySessionStreamEvent,
  buildAbortedSessionTurn,
} from "./sessionEventModel.js";
import { getSessionStreamKind } from "./sessionStreamKinds.js";

export function buildCodexAbortedTurn(reason) {
  return buildAbortedSessionTurn(reason);
}

export function normalizeCodexStreamEvent(event) {
  const semanticKind = getSessionStreamKind(event, { preferSemantic: true });
  if (!semanticKind) {
    return event;
  }

  switch (semanticKind) {
    case "assistant_progress":
      return {
        ...event,
        kind: "assistant_progress",
      };
    case "turn_completed":
      if (event?.turn?.role === "assistant") {
        return {
          ...event,
          kind: "assistant_completed",
        };
      }
      return {
        ...event,
        kind: "turn_completed",
      };
    case "turn_aborted":
      return {
        ...event,
        kind: "turn_aborted",
      };
    default:
      return event;
  }
}

export function applyCodexStreamEvent(turns, event) {
  return applySessionStreamEvent(turns, normalizeCodexStreamEvent(event));
}
