import type { ProviderSessionMetadata } from "../../types";
import type { ProviderFilter, UnifiedSession } from "./presentation";
import { cloneSessionEntry, mergeSessionListSnapshot } from "../../utils/sessionBrowserState.js";

const providerSessionSnapshotCache = new Map<ProviderFilter, UnifiedSession[]>();

type GenericProviderSessionRaw = {
  id?: string;
  sessionId?: string;
  session_id?: string;
  title?: string;
  directory?: string;
  workspace?: string;
  cwd?: string;
  archived?: boolean;
  rolloutPath?: string;
  rollout_path?: string;
  modelProvider?: string | null;
  model_provider?: string | null;
  source?: string | null;
  sandboxPolicy?: unknown | null;
  sandbox_policy?: unknown | null;
  approvalMode?: string | null;
  approval_mode?: string | null;
  isSmoke?: boolean;
  is_smoke?: boolean;
};

export function normalizeGenericProviderSessions(
  provider: ProviderFilter,
  rows: unknown[],
  fallbackWorkspace: string,
): UnifiedSession[] {
  return rows.flatMap((row, index) => {
    const session = row as GenericProviderSessionRaw;
    const id = session.id ?? session.sessionId ?? session.session_id;
    if (!id) {
      return [];
    }
    const workspace = session.workspace ?? session.directory ?? session.cwd ?? fallbackWorkspace;
    return [{
      id,
      type: provider,
      workspace,
      title: session.title || id,
      archived: session.archived ?? false,
      raw: { ...session, index },
    }];
  });
}

export function mergeSessionSnapshotsByProvider(
  current: Record<string, UnifiedSession[]>,
  provider: ProviderFilter,
  incoming: UnifiedSession[],
  options?: { preserveOnEmpty?: boolean },
): Record<string, UnifiedSession[]> {
  return {
    ...current,
    [provider]: mergeSessionListSnapshot(current[provider] ?? [], incoming, {
      preserveOnEmpty: options?.preserveOnEmpty === true,
    }),
  };
}

export function readCachedProviderSessionSnapshot(provider: ProviderFilter): UnifiedSession[] {
  return (providerSessionSnapshotCache.get(provider) ?? []).map(cloneSessionEntry);
}

export function readCachedProviderSessionSnapshotRows(providers?: ProviderFilter[]): UnifiedSession[] {
  const providerIds = providers && providers.length > 0
    ? providers
    : Array.from(providerSessionSnapshotCache.keys());
  return providerIds.flatMap((provider) => readCachedProviderSessionSnapshot(provider));
}

export function writeCachedProviderSessionSnapshot(
  provider: ProviderFilter,
  incoming: UnifiedSession[],
  options?: { preserveOnEmpty?: boolean },
): UnifiedSession[] {
  const merged = mergeSessionListSnapshot(
    providerSessionSnapshotCache.get(provider) ?? [],
    incoming,
    {
      preserveOnEmpty: options?.preserveOnEmpty === true,
    },
  );
  providerSessionSnapshotCache.set(provider, merged.map(cloneSessionEntry));
  return merged.map(cloneSessionEntry);
}

export function providerSessionMetadataFromUnifiedSession(session: UnifiedSession): ProviderSessionMetadata {
  const raw = (session.raw ?? {}) as GenericProviderSessionRaw;
  return {
    threadId: session.id,
    cwd: session.workspace,
    title: session.title,
    rolloutPath: typeof raw.rolloutPath === "string"
      ? raw.rolloutPath
      : typeof raw.rollout_path === "string"
        ? raw.rollout_path
        : undefined,
    archived: session.archived ?? false,
    modelProvider: typeof raw.modelProvider === "string"
      ? raw.modelProvider
      : typeof raw.model_provider === "string"
        ? raw.model_provider
        : null,
    source: typeof raw.source === "string" ? raw.source : null,
    sandboxPolicy: raw.sandboxPolicy ?? raw.sandbox_policy ?? null,
    approvalMode: typeof raw.approvalMode === "string"
      ? raw.approvalMode
      : typeof raw.approval_mode === "string"
        ? raw.approval_mode
        : null,
    isSmoke: Boolean(raw.isSmoke ?? raw.is_smoke),
  };
}
