import type { UnifiedSession } from "../components/session-browser/presentation";
import type { TaskBoardSessionActivity } from "./taskBoard";

export function sessionPreviewText(session: UnifiedSession): string | null;

export function mergeSessionListSnapshot(
  previousSessions?: UnifiedSession[],
  nextSessions?: UnifiedSession[],
  options?: {
    preserveOnEmpty?: boolean;
  },
): UnifiedSession[];

export function resolveSessionSnapshotUpdate(
  previousSessions?: UnifiedSession[],
  nextSessions?: UnifiedSession[],
  options?: {
    preserveOnEmpty?: boolean;
    emptyRetryBudget?: number;
    emptyRetryCount?: number;
  },
): {
  sessions: UnifiedSession[];
  accepted: boolean;
  preserved: boolean;
  shouldRetry: boolean;
};

export function nextSelectedSessionId(
  sessions?: UnifiedSession[],
  selectedSessionId?: string | null,
  options?: {
    preserveMissing?: boolean;
  },
): string | null;

export function hasPendingSelectedSession(
  sessions?: UnifiedSession[],
  selectedSessionId?: string | null,
): boolean;

export function mergeLiveSessionActivities(
  sessions: UnifiedSession[],
  activities?: TaskBoardSessionActivity[],
): UnifiedSession[];
