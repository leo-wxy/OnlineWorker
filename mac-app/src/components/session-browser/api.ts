import { invoke } from "@tauri-apps/api/core";
import type {
  ClaudeSession,
  CodexSession,
  CodexThreadCursor,
  CodexThreadReadResult,
  ProviderMetadata,
  ProviderUsageQuery,
  ProviderUsageSummary,
  SessionTurn,
} from "../../types";
import { limitSessionTurns } from "./shared";

function normalizeDisplayMode(role: string): "plain" | "markdown" {
  return role === "assistant" ? "markdown" : "plain";
}

function normalizeSessionTurns(turns: SessionTurn[] | null | undefined): SessionTurn[] {
  return (turns ?? []).map((turn) => ({
    ...turn,
    displayMode: turn.displayMode ?? normalizeDisplayMode(turn.role),
  }));
}

interface CodexThreadRaw {
  id: string;
  title: string;
  cwd: string;
  archived: boolean;
  rollout_path: string;
  model_provider?: string | null;
  source?: string | null;
  is_smoke?: boolean;
}

interface ClaudeSessionRaw {
  id: string;
  title: string;
  directory: string;
  archived: boolean;
}

interface ClaudeTurnRow {
  role: string;
  content: string;
}

interface ClaudeSendResult {
  sessionId: string;
  createdNewSession: boolean;
}

export async function fetchCodexSessions(): Promise<CodexSession[]> {
  const threads = await invoke<CodexThreadRaw[]>("list_codex_threads");
  return threads
    .map((thread) => ({
      threadId: thread.id,
      cwd: thread.cwd,
      title: thread.title || thread.cwd.split("/").pop() || thread.id.slice(0, 8),
      rolloutPath: thread.rollout_path,
      archived: thread.archived,
      modelProvider: thread.model_provider ?? null,
      source: thread.source ?? null,
      isSmoke: Boolean(thread.is_smoke),
    }));
}

export async function fetchProviderMetadata(): Promise<ProviderMetadata[]> {
  return invoke<ProviderMetadata[]>("get_provider_metadata");
}

export async function fetchProviderUsageSummary(
  providerId: string,
  query: ProviderUsageQuery,
): Promise<ProviderUsageSummary> {
  return invoke<ProviderUsageSummary>("get_provider_usage_summary", {
    providerId,
    startDate: query.startDate,
    endDate: query.endDate,
  });
}

export async function fetchProviderSessions(providerId: string): Promise<unknown[]> {
  return invoke<unknown[]>("list_provider_sessions", { providerId });
}

export async function fetchProviderSession(
  providerId: string,
  sessionId: string,
  workspaceDir?: string | null,
): Promise<SessionTurn[]> {
  const turns = await invoke<SessionTurn[]>("read_provider_session", {
    providerId,
    sessionId,
    workspaceDir: workspaceDir ?? null,
  });
  return limitSessionTurns(normalizeSessionTurns(turns));
}

export async function sendProviderSessionMessage(
  providerId: string,
  sessionId: string,
  text: string,
  workspaceDir?: string | null,
): Promise<unknown> {
  return invoke("send_provider_session_message", {
    providerId,
    sessionId,
    text,
    workspaceDir: workspaceDir ?? null,
  });
}

export async function fetchCodexThreadState(rolloutPath: string): Promise<CodexThreadReadResult> {
  const result = await invoke<CodexThreadReadResult>("read_codex_thread_state", { rolloutPath });
  return {
    ...result,
    turns: limitSessionTurns(normalizeSessionTurns(result.turns)),
  };
}

export async function fetchCodexThreadUpdates(
  rolloutPath: string,
  cursor: CodexThreadCursor,
): Promise<CodexThreadReadResult> {
  const result = await invoke<CodexThreadReadResult>("read_codex_thread_updates", { rolloutPath, cursor });
  return {
    ...result,
    turns: limitSessionTurns(normalizeSessionTurns(result.turns)),
  };
}

export async function sendCodexMessage(threadId: string, text: string, cwd?: string | null): Promise<void> {
  await invoke("send_codex_thread_message", {
    threadId,
    text,
    cwd: cwd ?? null,
  });
}

export async function fetchClaudeSessions(): Promise<ClaudeSession[]> {
  const rows = await invoke<ClaudeSessionRaw[]>("list_claude_sessions");
  return rows.map((session) => ({
    sessionId: session.id,
    title: session.title,
    workspace: session.directory,
    archived: session.archived,
  }));
}

export async function fetchClaudeMessages(
  sessionId: string,
  workspaceDir?: string | null,
): Promise<SessionTurn[]> {
  const turns = await invoke<ClaudeTurnRow[]>("read_claude_session", {
    sessionId,
    workspaceDir: workspaceDir ?? null,
  });
  return limitSessionTurns(normalizeSessionTurns(turns.map((turn) => ({
    role: (turn.role === "user" ? "user" : "assistant") as "user" | "assistant",
    content: turn.content,
  }))));
}

export async function sendClaudeMessage(
  sessionId: string,
  text: string,
  workspaceDir?: string | null,
): Promise<ClaudeSendResult> {
  return invoke<ClaudeSendResult>("send_claude_session_message", {
    sessionId,
    text,
    workspaceDir: workspaceDir ?? null,
  });
}
