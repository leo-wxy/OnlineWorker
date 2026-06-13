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
  files: boolean;
  usage: boolean;
  launchMethods: boolean;
  commandWrappers: string[];
  controlModes: string[];
  messageRewrite?: ProviderMessageRewriteCapabilities | null;
}

export interface ProviderMessageRewriteCapabilities {
  appSend: boolean;
  telegram: boolean;
  externalCli?: string | null;
  wrapper?: string | null;
}

export interface ProviderMessageHookStatus {
  enabled: boolean;
  mode: string;
}

export interface ProviderMessageHooksMetadata {
  abusiveLanguageNormalization: ProviderMessageHookStatus;
}

export interface ProviderExternalCliConfig {
  upstreamBaseUrl?: string | null;
  authToken?: string | null;
  model?: string | null;
  launcherWrapsClaude: boolean;
}

export interface ProviderLaunchMethodConfig {
  id: string;
  label: string;
  bin: string;
}

export interface ComposerAttachment {
  id: string;
  kind: "image" | "file";
  name: string;
  mimeType?: string | null;
  sizeBytes: number;
  path: string;
}

export interface ProviderInstallMetadata {
  cliNames?: string[];
}

export interface ProviderProcessMetadata {
  cleanupMatchers?: string[];
}

export interface ProviderIconMetadata {
  path?: string;
  url?: string;
  source?: string;
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
  messageHooks?: ProviderMessageHooksMetadata | null;
  externalCli: ProviderExternalCliConfig;
  launchMethods?: ProviderLaunchMethodConfig[];
  install?: ProviderInstallMetadata;
  process?: ProviderProcessMetadata;
  icon?: ProviderIconMetadata | null;
}

export interface NotificationChannelMetadata {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
  builtin: boolean;
  config: Record<string, unknown>;
  settingsFields: NotificationSettingsField[];
  icon?: ProviderIconMetadata | null;
  setupGuide?: NotificationSetupGuide | null;
}

export interface NotificationSetupGuide {
  type: "html" | string;
  assets: Record<string, string>;
}

export type NotificationSettingsFieldType = "string" | "number" | "boolean" | "select" | "secret";

export interface NotificationSettingsOption {
  value: string;
  label: string;
}

export interface NotificationSettingsField {
  key: string;
  label: string;
  type: NotificationSettingsFieldType;
  required: boolean;
  default?: unknown;
  description: string;
  options: NotificationSettingsOption[];
}

export interface AiServiceMetadata {
  id: string;
  name: string;
  protocol: string;
  baseUrl?: string | null;
  endpoint?: string | null;
  apiKey?: string | null;
  models: string[];
  defaultModel: string;
  timeoutSeconds: number;
  enabled: boolean;
}

export interface AiScenarioMetadata {
  id: string;
  enabled: boolean;
  serviceId: string;
  model: string;
  outputSchema: string;
  fallback: string;
  limits: Record<string, number>;
  promptTemplate: string;
}

export interface AiConfigMetadata {
  services: AiServiceMetadata[];
  scenarios: AiScenarioMetadata[];
}

export interface AiConnectionTestResult {
  ok: boolean;
  status?: number | null;
  message: string;
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

export interface ProviderDashboardStatus {
  id: string;
  label?: string | null;
  description?: string | null;
  capabilities?: ProviderCapabilitiesMetadata | null;
  icon?: ProviderIconMetadata | null;
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
  activeWorkspacePath?: string | null;
  activeTool?: string | null;
  activeSessionId?: string | null;
  activeSessionTool?: string | null;
  highlightedThreadPreview?: string | null;
  activeThreadCount: number;
}

export interface DashboardState {
  overall: SystemHealth;
  bot: BotDashboardStatus;
  providers: ProviderDashboardStatus[];
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
  sandboxPolicy?: unknown | null;
  approvalMode?: string | null;
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

export interface CodexSendResult {
  threadId: string;
  requestedThreadId?: string | null;
  workspaceId?: string | null;
  createdNewThread: boolean;
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
