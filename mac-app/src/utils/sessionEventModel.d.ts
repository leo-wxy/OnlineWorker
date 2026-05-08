import type { SessionStreamEvent, SessionTurn } from "../types";

export function buildAbortedSessionTurn(reason?: string | null, partialText?: string): SessionTurn | null;

export function applySessionStreamEvent(
  turns: SessionTurn[],
  event: SessionStreamEvent,
): SessionTurn[];
