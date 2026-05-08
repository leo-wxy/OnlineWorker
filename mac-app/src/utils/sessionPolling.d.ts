export function countAssistantEntries<T extends { role?: string }>(
  snapshot: T[],
): number;

export function buildSnapshotSignature(snapshot: unknown): string;

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
