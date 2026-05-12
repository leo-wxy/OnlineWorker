// Service status from launchctl
export interface ServiceStatus {
  running: boolean;
  pid: number | null;
}

export type SystemHealth = "healthy" | "degraded" | "misconfigured" | "stopped" | "unknown";
export type ServiceHealth = "healthy" | "degraded" | "stopped" | "unknown";
export type ConnectionStatus = "connected" | "disconnected" | "unknown";
export type AlertLevel = "warning" | "error";
export type CommandSource = "bot" | "downstream" | "skill";
export type CommandBackend = "local" | "shared" | string;
export type CommandScope = "global" | "workspace" | "thread";
export type CommandStatus = "active" | "missing";

export interface ProviderTransportMetadata {
  owner: string;
  live: string;
  type: string;
  appServerPort?: number | null;
  appServerUrl?: string | null;
}

export interface ProviderCapabilitiesMetadata {
  sessions: boolean;
  send: boolean;
  commands: boolean;
  approvals: boolean;
  questions: boolean;
  photos: boolean;
  commandWrappers: string[];
  controlModes: string[];
}

export interface ProviderInstallMetadata {
  cliNames?: string[];
}

export interface ProviderProcessMetadata {
  cleanupMatchers?: string[];
}

export interface ProviderMetadata {
  id: string;
  runtimeId: string;
  label: string;
  description: string;
  visible: boolean;
  managed: boolean;
  autostart: boolean;
  bin?: string | null;
  transport: ProviderTransportMetadata;
  liveTransport: string;
  controlMode?: string | null;
  capabilities: ProviderCapabilitiesMetadata;
  install?: ProviderInstallMetadata;
  process?: ProviderProcessMetadata;
}

export interface DashboardAlert {
  level: AlertLevel;
  code?: string;
  title: string;
  detail: string;
  action?: string | null;
  actionCode?: string | null;
  missingFields?: string[] | null;
}

export interface BotDashboardStatus {
  process: ServiceHealth;
  telegram: ConnectionStatus;
  pid: number | null;
  lastHeartbeat?: string | null;
}

export interface ToolDashboardStatus {
  health: ServiceHealth;
  port?: number | null;
  detail?: string | null;
}

export interface ProviderDashboardStatus {
  id: string;
  label?: string | null;
  description?: string | null;
  capabilities?: ProviderCapabilitiesMetadata | null;
  managed: boolean;
  autostart: boolean;
  health: ServiceHealth;
  port?: number | null;
  detail?: string | null;
  transport?: string | null;
  liveTransport?: string | null;
  controlMode?: string | null;
  bin?: string | null;
}

export interface RecentActivitySummary {
  activeWorkspaceId?: string | null;
  activeWorkspaceName?: string | null;
  activeTool?: string | null;
  activeSessionId?: string | null;
  activeSessionTool?: string | null;
  highlightedThreadPreview?: string | null;
  activeThreadCount: number;
}

export interface DashboardState {
  overall: SystemHealth;
  bot: BotDashboardStatus;
  providers?: ProviderDashboardStatus[];
  codex: ToolDashboardStatus;
  alerts: DashboardAlert[];
  recentActivity?: RecentActivitySummary | null;
  generatedAtEpoch: number;
}

export interface ProviderUsageDay {
  date: string;
  inputTokens: number;
  outputTokens: number;
  cacheCreationTokens: number;
  cacheReadTokens: number;
  totalTokens: number;
  totalCostUsd?: number | null;
}

export interface ProviderUsageQuery {
  startDate: string;
  endDate: string;
}

export interface ProviderUsageSummary {
  providerId: string;
  days: ProviderUsageDay[];
  updatedAtEpoch: number;
  unsupportedReason?: string | null;
}

// Config file content
export interface ConfigContent {
  raw: string;
  path: string;
}

// Env file content (sensitive fields masked by default)
export interface EnvContent {
  lines: EnvLine[];
  path: string;
}

export interface EnvLine {
  key: string;
  value: string;      // "***" for masked fields
  masked: boolean;    // whether this field is a sensitive field
}

// Session types
export interface CodexSession {
  threadId: string;
  cwd: string;
  title?: string;
  rolloutPath?: string;
  archived?: boolean;
  modelProvider?: string | null;
  source?: string | null;
  isSmoke?: boolean;
}

export interface SessionTurn {
  role: "user" | "assistant";
  content: string;
  timestamp?: string;
  pending?: boolean;
  displayMode?: "plain" | "markdown";
}

export type CodexTurn = SessionTurn;

export interface CodexThreadCursor {
  offset: number;
}

export interface CodexThreadReadResult {
  turns: SessionTurn[];
  cursor: CodexThreadCursor;
  replace: boolean;
}

export interface SessionStreamEvent {
  kind: string;
  semanticKind?: string | null;
  turn?: SessionTurn | null;
  snapshot?: SessionTurn[] | null;
  cursor?: CodexThreadCursor | null;
  reason?: string | null;
  error?: string | null;
  sessionTabVisibleAt?: number | null;
}

export type CodexThreadStreamEvent = SessionStreamEvent;

export interface ClaudeSession {
  sessionId: string;
  title?: string;
  workspace?: string;
  archived?: boolean;
}

export type ClaudeSessionTurn = SessionTurn;

// Log streaming
export interface LogLine {
  raw: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | "UNKNOWN";
  timestamp?: string;
  message: string;
}

// Telegram connectivity test results
export interface BotInfo {
  ok: boolean;
  username: string;
  bot_id: number;
  first_name: string;
}

export interface GroupInfo {
  ok: boolean;
  title: string;
  chat_type: string;
  is_forum: boolean;
}

export interface PermissionInfo {
  ok: boolean;
  status: string;
  can_manage_topics: boolean;
  can_delete_messages: boolean;
  can_pin_messages: boolean;
}

export interface CommandRegistryEntry {
  id: string;
  name: string;
  telegramName: string;
  source: CommandSource;
  backend: CommandBackend;
  scope: CommandScope;
  description: string;
  enabledForTelegram: boolean;
  publishedToTelegram: boolean;
  status: CommandStatus;
}

export interface CommandRegistryResponse {
  commands: CommandRegistryEntry[];
  lastRefreshedEpoch: number | null;
  lastPublishedEpoch: number | null;
  hasUnpublishedChanges: boolean;
}
