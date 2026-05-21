export function countAssistantEntries<T extends { role?: string }>(
  snapshot: T[],
): number;

export function buildSnapshotSignature(snapshot: unknown): string;

export function hasSessionSnapshotChanged<T>(
  currentSnapshot: T[] | null | undefined,
  nextSnapshot: T[] | null | undefined,
  getSignature?: (snapshot: T[] | null | undefined) => string,
): boolean;

export function startActiveSessionRefresh<T>(options: {
  intervalMs?: number;
  getCurrentSnapshot: () => T[];
  loadSnapshot: () => Promise<T[]>;
  onSnapshot: (snapshot: T[]) => void;
  shouldSkip?: () => boolean;
  setTimer?: (callback: () => void | Promise<void>, timeoutMs: number) => unknown;
  clearTimer?: (timer: unknown) => void;
  onError?: (error: unknown) => void;
}): () => void;

export function getLastAssistantSignature<
  T extends { role?: string; content?: string; timestamp?: string }
>(snapshot: T[]): string | null;

export function hasAdvancedAssistantReply<
  T extends { role?: string; content?: string; timestamp?: string }
>(previousSnapshot: T[], nextSnapshot: T[]): boolean;

export function pollAssistantReply<T>(options: {
  loadSnapshot: () => Promise<T[]>;
  getAssistantCount: (snapshot: T[]) => number;
  getSignature: (snapshot: T[]) => string;
  baselineAssistantCount: number;
  baselineSnapshot?: T[];
  onUpdate?: (snapshot: T[]) => void;
  intervalMs?: number;
  maxAttempts?: number;
  stablePollsRequired?: number;
  shouldContinue?: () => boolean;
}): Promise<{
  snapshot: T[];
  settled: boolean;
  assistantAppeared: boolean;
  cancelled: boolean;
}>;

export function pollForSettledAssistantReply<T>(options: {
  loadSnapshot: () => Promise<T[]>;
  getAssistantCount: (snapshot: T[]) => number;
  getSignature: (snapshot: T[]) => string;
  baselineAssistantCount: number;
  baselineSnapshot?: T[];
  onUpdate?: (snapshot: T[]) => void;
  intervalMs?: number;
  maxAttempts?: number;
  stablePollsRequired?: number;
  shouldContinue?: () => boolean;
}): Promise<T[]>;
