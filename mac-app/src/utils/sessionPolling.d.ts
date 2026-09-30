export function countAssistantEntries<T extends { role?: string }>(
  snapshot: T[],
): number;

export function getLastAssistantSignature<
  T extends { role?: string; content?: string; timestamp?: string }
>(snapshot: T[]): string | null;

export function hasAdvancedAssistantReply<
  T extends { role?: string; content?: string; timestamp?: string }
>(previousSnapshot: T[], nextSnapshot: T[]): boolean;
