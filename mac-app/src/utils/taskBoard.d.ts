import type { DashboardState } from "../types";
import type { UnifiedSession } from "../components/session-browser/presentation";

export interface TaskBoardSessionRef {
  providerId: string;
  sessionId: string;
  updatedAtEpoch: number;
}

export interface TaskBoardState {
  version: number;
  pinned: TaskBoardSessionRef[];
}

export interface TaskBoardSessionActivity {
  providerId: string;
  workspaceId: string;
  workspacePath: string;
  sessionId: string;
  title: string;
  status: string;
  attentionReason: string;
  lastUserMessage: string;
  lastAssistantMessage: string;
  lastFinalMessage: string;
  lastEventKind: string;
  updatedAt: number;
}

export interface TaskBoardTask {
  id: string;
  sessionId: string;
  providerId: string;
  providerLabel: string;
  title: string;
  workspace: string;
  preview: string | null;
  archived: boolean;
  needsAttention: boolean;
  running: boolean;
  pinned: boolean;
  statusReason: string;
  recentEvent: string | null;
  updatedAtEpochMs: number | null;
}

export interface TaskBoardModel {
  needsAttention: TaskBoardTask[];
  running: TaskBoardTask[];
  pinnedIdle: TaskBoardTask[];
  counts: {
    needsAttention: number;
    running: number;
    pinnedIdle: number;
    total: number;
  };
  generatedAtEpochMs: number;
}

export function buildTaskBoardModel(input: {
  sessions: UnifiedSession[];
  sessionActivities?: TaskBoardSessionActivity[];
  dashboardState: DashboardState | null;
  taskBoardState?: TaskBoardState | null;
  providerLabels: Record<string, string>;
  nowEpochMs?: number;
}): TaskBoardModel;
