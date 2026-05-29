import type { ProviderFilter, UnifiedSession } from "./presentation";

type GenericProviderSessionRaw = {
  id?: string;
  sessionId?: string;
  session_id?: string;
  title?: string;
  directory?: string;
  workspace?: string;
  cwd?: string;
  archived?: boolean;
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
