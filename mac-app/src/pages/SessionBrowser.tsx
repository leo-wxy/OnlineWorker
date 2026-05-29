import { useState, useEffect, useCallback, useRef, useMemo, type MouseEvent } from "react";
import { useI18n } from "../i18n";
import {
  fetchClaudeSessions,
  fetchCodexSessions,
  fetchProviderMetadata,
  fetchProviderSessions,
} from "../components/session-browser/api";
import {
  archiveSessionWithFeedback,
  SessionActionMenu,
  type ArchiveNotice,
  type SessionActionMenuState,
} from "../components/session-browser/archive";
import { CodexSessionBadges } from "../components/session-browser/badges";
import { ClaudeChat } from "../components/session-browser/ClaudeChat";
import { CodexChat } from "../components/session-browser/CodexChat";
import { GenericProviderChat } from "../components/session-browser/GenericProviderChat";
import { normalizeGenericProviderSessions } from "../components/session-browser/sessionData";
import {
  SessionListPanel,
  SessionProviderToolbar,
  WorkspaceSidebar,
} from "../components/session-browser/navigation";
import {
  StatePanel,
  type ArchiveFilter,
  type ProviderFilter,
  type UnifiedSession,
} from "../components/session-browser/presentation";
import { visibleSessionProviders } from "../utils/sessionProviders.js";
import type {
  ClaudeSession,
  CodexSession,
  ProviderMetadata,
} from "../types";

export function SessionBrowser() {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [codexSessions, setCodexSessions] = useState<CodexSession[]>([]);
  const [claudeSessions, setClaudeSessions] = useState<ClaudeSession[]>([]);
  const [genericSessionsByProvider, setGenericSessionsByProvider] = useState<Record<string, UnifiedSession[]>>({});
  
  const [loading, setLoading] = useState(false);
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>("codex");
  const [archiveFilter, setArchiveFilter] = useState<ArchiveFilter>("active");
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionActionMenuState | null>(null);
  const [archivingSessionId, setArchivingSessionId] = useState<string | null>(null);
  const [archiveNotice, setArchiveNotice] = useState<ArchiveNotice | null>(null);
  const loadedProvidersRef = useRef<Set<ProviderFilter>>(new Set());
  const loadTokenRef = useRef(0);
  const visibleProviders = useMemo(
    () => visibleSessionProviders(providers) as ProviderMetadata[],
    [providers],
  );
  const providerLabels = useMemo(() => Object.fromEntries(
    visibleProviders.map((provider) => [provider.id, provider.label || provider.id]),
  ) as Record<string, string>, [visibleProviders]);
  const providerCapabilities = useMemo(() => Object.fromEntries(
    visibleProviders.map((provider) => [provider.id, provider.capabilities]),
  ) as Record<string, ProviderMetadata["capabilities"]>, [visibleProviders]);

  useEffect(() => {
    let cancelled = false;
    void fetchProviderMetadata()
      .then((metadata) => {
        if (!cancelled) {
          setProviders(metadata);
        }
      })
      .catch((error) => {
        console.warn("Failed to load session provider metadata", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (visibleProviders.length === 0) {
      return;
    }
    if (!visibleProviders.some((provider) => provider.id === providerFilter)) {
      setProviderFilter(visibleProviders[0].id);
    }
  }, [providerFilter, visibleProviders]);

  useEffect(() => {
    setSelectedWorkspace(null);
    setSelectedSessionId(null);
    setSessionContextMenu(null);
    setArchiveNotice(null);
  }, [providerFilter]);

  useEffect(() => {
    if (sessionContextMenu === null) {
      return;
    }

    const closeMenu = () => setSessionContextMenu(null);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMenu();
      }
    };

    window.addEventListener("click", closeMenu);
    window.addEventListener("contextmenu", closeMenu);
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("blur", closeMenu);
    return () => {
      window.removeEventListener("click", closeMenu);
      window.removeEventListener("contextmenu", closeMenu);
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("blur", closeMenu);
    };
  }, [sessionContextMenu]);

  const loadProvider = useCallback(async (
    provider: ProviderFilter,
    options?: { force?: boolean },
  ) => {
    const force = options?.force ?? false;
    if (!force && loadedProvidersRef.current.has(provider)) {
      return;
    }

    const token = ++loadTokenRef.current;
    setLoading(true);
    try {
      if (provider === "codex") {
        const sessions = await fetchCodexSessions();
        setCodexSessions(sessions);
      } else if (provider === "claude") {
        const sessions = await fetchClaudeSessions();
        setClaudeSessions(sessions);
      } else {
        const sessions = await fetchProviderSessions(provider);
        setGenericSessionsByProvider((current) => ({
          ...current,
          [provider]: normalizeGenericProviderSessions(
            provider,
            sessions,
            t.sessions.workspaceFallback,
          ),
        }));
      }
      loadedProvidersRef.current.add(provider);
    } catch (error) {
      console.warn(`Failed to load ${provider} sessions`, error);
    } finally {
      if (loadTokenRef.current === token) {
        setLoading(false);
      }
    }
  }, [t.sessions.workspaceFallback]);

  useEffect(() => {
    void loadProvider(providerFilter);
  }, [loadProvider, providerFilter]);

  const refreshCurrentProvider = useCallback(async () => {
    await loadProvider(providerFilter, { force: true });
  }, [loadProvider, providerFilter]);

  const openSessionContextMenu = useCallback((
    event: MouseEvent<HTMLElement>,
    session: UnifiedSession,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setArchiveNotice(null);
    setSessionContextMenu({
      session,
      x: Math.min(event.clientX, window.innerWidth - 180),
      y: Math.min(event.clientY, window.innerHeight - 72),
    });
  }, []);

  const openSessionActionMenu = useCallback((
    event: MouseEvent<HTMLElement>,
    session: UnifiedSession,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    setArchiveNotice(null);
    setSessionContextMenu({
      session,
      x: Math.min(Math.max(rect.right - 176, 8), window.innerWidth - 180),
      y: Math.min(rect.bottom + 6, window.innerHeight - 72),
    });
  }, []);

  const handleArchiveSession = useCallback(async (session: UnifiedSession) => {
    setSessionContextMenu(null);
    if (session.archived || archivingSessionId !== null) {
      return;
    }

    setArchivingSessionId(session.id);
    setArchiveNotice(null);
    const nextNotice = await archiveSessionWithFeedback({
      session,
      selectedSessionId,
      refreshCurrentProvider,
      onArchivedSelection: () => setSelectedSessionId(null),
      successText: t.sessions.archiveSucceeded,
      failureText: t.sessions.archiveFailed,
    });
    setArchiveNotice(nextNotice);
    setArchivingSessionId(null);
  }, [archivingSessionId, refreshCurrentProvider, selectedSessionId, t.sessions]);

  const unifiedSessions = useMemo<UnifiedSession[]>(() => {
    if (providerFilter === "codex") {
      return codexSessions.map(s => ({
        id: s.threadId,
        type: "codex" as const,
        workspace: s.cwd || t.sessions.workspaceFallback,
        title: s.title || s.threadId,
        archived: s.archived ?? false,
        raw: s
      }));
    }
    if (providerFilter === "claude") {
      return claudeSessions.map(s => ({
      id: s.sessionId,
      type: "claude" as const,
      workspace: s.workspace || t.sessions.workspaceFallback,
      title: s.title || s.sessionId,
      archived: s.archived ?? false,
      raw: s
      }));
    }
    return genericSessionsByProvider[providerFilter] ?? [];
  }, [providerFilter, codexSessions, claudeSessions, genericSessionsByProvider, t]);

  const workspaces = useMemo(() => {
    const list = Array.from(new Set(unifiedSessions.map(s => s.workspace)));
    return list.sort();
  }, [unifiedSessions]);

  useEffect(() => {
    if (selectedWorkspace && !workspaces.includes(selectedWorkspace)) {
      setSelectedWorkspace(null);
    }
  }, [workspaces, selectedWorkspace]);

  const filteredSessions = useMemo(() => {
    return unifiedSessions.filter(s => {
      if (selectedWorkspace && s.workspace !== selectedWorkspace) return false;
      if (archiveFilter === "active" && s.archived) return false;
      if (archiveFilter === "archived" && !s.archived) return false;
      return true;
    });
  }, [unifiedSessions, selectedWorkspace, archiveFilter]);

  const selectedSession = useMemo(() => {
    return unifiedSessions.find(s => s.id === selectedSessionId) || null;
  }, [unifiedSessions, selectedSessionId]);

  return (
    <div className="ow-page-frame flex h-full flex-1 flex-col overflow-hidden rounded-[30px]">
      <SessionProviderToolbar
        providers={visibleProviders}
        providerFilter={providerFilter}
        loading={loading}
        onProviderChange={setProviderFilter}
        onRefresh={() => void refreshCurrentProvider()}
      />

      <div className="flex flex-1 gap-3 overflow-hidden p-3">
        <WorkspaceSidebar
          workspaces={workspaces}
          sessions={unifiedSessions}
          providerFilter={providerFilter}
          providerLabels={providerLabels}
          selectedWorkspace={selectedWorkspace}
          noSessionsLabel={t.sessions.noSessions}
          onSelectWorkspace={setSelectedWorkspace}
        />

        <SessionListPanel
          sessions={filteredSessions}
          providerFilter={providerFilter}
          providerLabels={providerLabels}
          selectedSessionId={selectedSessionId}
          archiveFilter={archiveFilter}
          archivingSessionId={archivingSessionId}
          archiveNotice={archiveNotice}
          labels={{
            active: "Active",
            archived: "Archived",
            archivingSession: t.sessions.archivingSession,
            noSessions: t.sessions.noSessions,
            sessionActions: t.sessions.sessionActions,
          }}
          renderSessionMeta={(session) => (
            session.type === "codex" ? (
              <div className="pl-1">
                <CodexSessionBadges session={session.raw as CodexSession} compact />
              </div>
            ) : null
          )}
          onArchiveFilterChange={setArchiveFilter}
          onSelectSession={setSelectedSessionId}
          onOpenContextMenu={openSessionContextMenu}
          onOpenActionMenu={openSessionActionMenu}
        />

        <div className="min-w-0 flex-1 overflow-hidden rounded-[28px]">
          {selectedSession ? (
            selectedSession.type === "codex" ? <CodexChat session={selectedSession} key={selectedSession.id} /> :
            selectedSession.type === "claude" ? <ClaudeChat session={selectedSession} key={selectedSession.id} refreshSessions={refreshCurrentProvider} /> :
            <GenericProviderChat
              session={selectedSession}
              key={selectedSession.id}
              providerSupportsAttachments={Boolean(
                providerCapabilities[selectedSession.type]?.files ||
                providerCapabilities[selectedSession.type]?.photos
              )}
            />
          ) : (
            <div className="ow-page-frame-soft flex h-full items-center justify-center rounded-[28px]">
              <StatePanel message={t.sessions.selectSession} />
            </div>
          )}
        </div>
      </div>
      {sessionContextMenu ? (
        <SessionActionMenu
          menu={sessionContextMenu}
          archivingSessionId={archivingSessionId}
          labels={{
            archiveSession: t.sessions.archiveSession,
            archivingSession: t.sessions.archivingSession,
            alreadyArchived: t.sessions.alreadyArchived,
          }}
          onArchive={(session) => void handleArchiveSession(session)}
        />
      ) : null}
    </div>
  );
}
