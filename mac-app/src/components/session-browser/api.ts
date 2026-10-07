import { invoke } from "@tauri-apps/api/core";
import type {
  ComposerAttachment,
  ProviderMetadata,
  ProviderSessionSendResult,
  UsageQuery,
  UsageSourceCatalogEntry,
  UsageSourceSummary,
  SessionTurn,
  SessionSendRecovery,
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

export async function fetchProviderMetadata(): Promise<ProviderMetadata[]> {
  return invoke<ProviderMetadata[]>("get_provider_metadata");
}

export async function fetchUsageSourceCatalog(): Promise<UsageSourceCatalogEntry[]> {
  return invoke<UsageSourceCatalogEntry[]>("get_usage_source_catalog");
}

export async function fetchUsageSourceSummary(
  pluginId: string,
  sourceId: string,
  query: UsageQuery,
  forceRefresh = false,
): Promise<UsageSourceSummary> {
  return invoke<UsageSourceSummary>("get_usage_source_summary", {
    pluginId,
    sourceId,
    startDate: query.startDate,
    endDate: query.endDate,
    timezone: "local",
    forceRefresh,
  });
}

export async function fetchProviderSessions(
  providerId: string,
  options?: { forceRefresh?: boolean },
): Promise<unknown[]> {
  return invoke<unknown[]>("list_provider_sessions", {
    providerId,
    forceRefresh: options?.forceRefresh ?? false,
  });
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

function normalizeProviderSessionSendResult(
  result: Record<string, unknown> | null,
): ProviderSessionSendResult {
  const payload = result ?? {};
  return {
    accepted: typeof payload.accepted === "boolean" ? payload.accepted : undefined,
    error: typeof payload.error === "string" ? payload.error : null,
    requestId: typeof payload.request_id === "string" ? payload.request_id : null,
    providerId: typeof payload.provider_id === "string"
      ? payload.provider_id
      : typeof payload.providerId === "string"
        ? payload.providerId
        : null,
    threadId: typeof payload.thread_id === "string"
      ? payload.thread_id
      : typeof payload.threadId === "string"
        ? payload.threadId
        : null,
    requestedThreadId: typeof payload.requested_thread_id === "string"
      ? payload.requested_thread_id
      : typeof payload.requestedThreadId === "string"
        ? payload.requestedThreadId
        : null,
    workspaceId: typeof payload.workspace_id === "string"
      ? payload.workspace_id
      : typeof payload.workspaceId === "string"
        ? payload.workspaceId
        : null,
    remapped: typeof payload.remapped === "boolean" ? payload.remapped : undefined,
    createdNewThread: typeof payload.created_new_thread === "boolean"
      ? payload.created_new_thread
      : typeof payload.createdNewThread === "boolean"
        ? payload.createdNewThread
        : undefined,
    pending: typeof payload.pending === "boolean" ? payload.pending : undefined,
    recovery: payload.recovery as SessionSendRecovery | null | undefined,
    session: payload.session ?? null,
  };
}

export async function sendProviderSessionMessage(
  providerId: string,
  sessionId: string,
  text: string,
  attachments: ComposerAttachment[] = [],
  workspaceDir?: string | null,
  requestId?: string,
): Promise<ProviderSessionSendResult> {
  const result = await invoke<Record<string, unknown> | null>("send_provider_session_message", {
    providerId,
    sessionId,
    text,
    attachments,
    workspaceDir: workspaceDir ?? null,
    requestId: requestId ?? null,
  });
  return normalizeProviderSessionSendResult(result);
}

export async function startProviderSessionMessage(
  providerId: string,
  workspaceDir: string,
  text: string,
  attachments: ComposerAttachment[] = [],
  requestId?: string,
): Promise<ProviderSessionSendResult> {
  const result = await invoke<Record<string, unknown> | null>("start_provider_session_message", {
    providerId,
    workspaceDir,
    text,
    attachments,
    requestId: requestId ?? null,
  });
  return normalizeProviderSessionSendResult(result);
}

export async function recheckProviderSessionSend(
  providerId: string,
  workspaceDir: string,
  requestId?: string,
  sessionId?: string,
): Promise<ProviderSessionSendResult> {
  const result = await invoke<Record<string, unknown>>("recheck_provider_session_send", {
    providerId, workspaceDir, requestId: requestId ?? null, sessionId: sessionId ?? null,
  });
  return normalizeProviderSessionSendResult(result);
}

export async function archiveProviderSession(
  providerId: string,
  sessionId: string,
  workspaceDir?: string | null,
): Promise<unknown> {
  return invoke("archive_provider_session", {
    providerId,
    sessionId,
    workspaceDir: workspaceDir ?? null,
  });
}

export async function stageComposerAttachments(
  files: Array<{
    path: string;
    name?: string | null;
    mimeType?: string | null;
    sizeBytes?: number | null;
    base64Data?: string | null;
  }>,
): Promise<ComposerAttachment[]> {
  return invoke<ComposerAttachment[]>("stage_session_composer_attachments", {
    files,
  });
}
