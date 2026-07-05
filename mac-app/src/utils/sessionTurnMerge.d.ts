import type { SessionTurn } from "../types";

export const SESSION_BROWSER_VISIBLE_TURNS: number;

export function limitSessionTurns<T>(turns: T[]): T[];

export function mergeSessionTurns(
  existing: SessionTurn[],
  incoming: SessionTurn[],
): SessionTurn[];

export function overlayPendingUserTurn(
  turns: SessionTurn[],
  raw: Record<string, unknown>,
): SessionTurn[];
