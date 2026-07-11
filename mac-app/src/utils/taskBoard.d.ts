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
  attentionKind: string;
  requestId: string;
  approvalSource: string;
  mirroredOnly?: boolean;
  canInterrupt?: boolean;
  canRecover?: boolean;
  controlReason?: string;
  controlMode?: "owned" | "external" | string;
  recentEvents?: TaskBoardRecentEvent[];
  lastUserMessage: string;
  lastAssistantMessage: string;
  lastFinalMessage: string;
  lastEventKind: string;
  updatedAt: number;
}

export interface TaskBoardRecentEvent {
  kind: string;
  createdAt: number;
  summary: string;
}

export interface TaskBoardActivityStreamEvent {
  kind: "snapshot" | "activity" | "remove" | "error";
  activities?: TaskBoardSessionActivity[];
  activity?: TaskBoardSessionActivity | null;
  providerId?: string;
  sessionId?: string;
  error?: string | null;
}

export interface TaskBoardTask {
  id: string;
  sessionId: string;
  providerId: string;
  providerLabel: string;
  title: string;
  workspace: string;
  workspaceId: string;
  workspacePath: string;
  preview: string | null;
  archived: boolean;
  needsAttention: boolean;
  status: string;
  attentionKind: string;
  requestId: string;
  approvalSource: string;
  mirroredOnly: boolean;
  canInterrupt: boolean;
  canRecover: boolean;
  controlReason: string;
  controlMode: string;
  recentEvents: TaskBoardRecentEvent[];
  lastUserMessage: string;
  lastAssistantMessage: string;
  interrupted: boolean;
  canContinue: boolean;
  recentEnded: boolean;
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
  recentEnded: TaskBoardTask[];
  counts: {
    needsAttention: number;
    running: number;
    pinnedIdle: number;
    recentEnded: number;
    total: number;
  };
  generatedAtEpochMs: number;
}

export function isLowSignalTaskBoardText(value: unknown): boolean;

export function taskBoardActivityKey(activity: TaskBoardSessionActivity): string;

export function taskBoardSessionKey(providerId: string, sessionId: string): string;

export function upsertTaskBoardActivity(
  activities: TaskBoardSessionActivity[],
  activity: TaskBoardSessionActivity,
): TaskBoardSessionActivity[];

export function removeTaskBoardActivity(
  activities: TaskBoardSessionActivity[],
  providerId: string,
  sessionId: string,
): TaskBoardSessionActivity[];

export function selectRecentConversationTurns(
  turns: Array<{ role?: string; content?: string }> | null | undefined,
  limit?: number,
): Array<{ role: "user" | "assistant"; content: string }>;

export function collectTaskBoardPreviewHydrationPlan(input?: {
  sessions?: UnifiedSession[];
  taskBoardState?: TaskBoardState | null;
  pinnedLimit?: number;
  lowSignalLimit?: number;
}): {
  keys: string[];
  pinnedKeys: string[];
};

export function buildTaskBoardModel(input: {
  sessions: UnifiedSession[];
  sessionActivities?: TaskBoardSessionActivity[];
  dashboardState: DashboardState | null;
  taskBoardState?: TaskBoardState | null;
  providerLabels: Record<string, string>;
  nowEpochMs?: number;
}): TaskBoardModel;
