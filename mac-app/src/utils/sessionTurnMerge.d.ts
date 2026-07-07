import type { SessionTurn } from "../types";

export function limitSessionTurns<T>(turns: T[]): T[];

export function mergeSessionTurns(
  existing: SessionTurn[],
  incoming: SessionTurn[],
): SessionTurn[];

export function overlayPendingUserTurn(
  turns: SessionTurn[],
  raw: Record<string, unknown>,
): SessionTurn[];

export function overlayLocalUserTurns(
  turns: SessionTurn[],
  localTurns: Array<{
    content?: string | null;
    afterAssistantCount?: number | null;
  }>,
): SessionTurn[];
