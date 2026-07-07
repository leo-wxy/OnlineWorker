export interface MenubarPopoverUsageProvider {
  providerId: string;
  label: string;
  tokensToday: number | null;
  inputTokens: number | null;
  outputTokens: number | null;
  cacheCreationTokens: number | null;
  cacheReadTokens: number | null;
  totalCostUsd: number | null;
  estimated: boolean;
}

export interface MenubarPopoverUsage {
  totalTokensToday: number | null;
  needsAttentionCount: number;
  activeSessionCount: number;
  providers: MenubarPopoverUsageProvider[];
}

export interface MenubarPopoverSessionLane {
  providerId: string;
  label: string;
  sessionId: string | null;
  workspace: string | null;
  workspaceName: string | null;
  title: string | null;
  latestPreview: string | null;
  status: string | null;
  updatedAtEpoch: number | null;
}

export interface MenubarPopoverSnapshot {
  generatedAtEpoch: number;
  usage: MenubarPopoverUsage;
  latestSessions: MenubarPopoverSessionLane[];
}

export type MenubarPopoverTab = "tasks" | "sessions" | "usage";
