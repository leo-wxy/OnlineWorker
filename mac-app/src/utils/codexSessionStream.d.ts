import type { CodexTurn, CodexThreadStreamEvent } from "../types";

export function buildCodexAbortedTurn(reason?: string | null): CodexTurn | null;
export function applyCodexStreamEvent(
  turns: CodexTurn[],
  event: CodexThreadStreamEvent,
): CodexTurn[];
