import type { SessionStreamEvent, SessionTurn } from "../types";

export function shouldClearReplyWatch(
  previousSnapshot: SessionTurn[],
  nextSnapshot: SessionTurn[],
  event: SessionStreamEvent,
): boolean;
