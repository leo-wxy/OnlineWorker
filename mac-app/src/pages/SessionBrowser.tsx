import { useState, useEffect, useCallback, useRef, useMemo, type MouseEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../i18n";
import {
  fetchProviderMetadata,
  fetchProviderSessions,
} from "../components/session-browser/api";
import {
  archiveSessionWithFeedback,
  SessionActionMenu,
  type ArchiveNotice,
  type SessionActionMenuState,
} from "../components/session-browser/archive";
import { ProviderSessionBadges } from "../components/session-browser/badges";
import { GenericProviderChat } from "../components/session-browser/GenericProviderChat";
import {
  providerSessionMetadataFromUnifiedSession,
  mergeSessionSnapshotsByProvider,
  normalizeGenericProviderSessions,
  readCachedProviderSessionSnapshot,
  writeCachedProviderSessionSnapshot,
} from "../components/session-browser/sessionData";
import {
  hasPendingSelectedSession,
  mergeLiveSessionActivities,
  nextSelectedSessionId,
  resolveSessionSnapshotUpdate,
} from "../utils/sessionBrowserState.js";
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
import {
  WorkspaceActionMenu,
  type WorkspaceActionMenuState,
} from "../components/session-browser/workspaceActions";
import { visibleSessionProviders } from "../utils/sessionProviders.js";
import type { TaskBoardSessionActivity, TaskBoardState } from "../utils/taskBoard";
import type {
  ProviderMetadata,
  ProviderSessionSendResult,
} from "../types";

interface SessionBrowserOpenTarget {
  providerId: string;
  sessionId: string;
  workspace?: string;
}

interface Props {
  openTarget?: SessionBrowserOpenTarget | null;
  taskBoardActivities?: TaskBoardSessionActivity[];
  active?: boolean;
}

const DEFAULT_TASK_BOARD_STATE: TaskBoardState = {
  version: 1,
  pinned: [],
};

function sessionTaskBoardKey(session: UnifiedSession) {
  return `${session.type}:${session.id}`;
}

export function SessionBrowser({ openTarget = null, taskBoardActivities = [], active = true }: Props) {
  const { t } = useI18n();
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [genericSessionsByProvider, setGenericSessionsByProvider] = useState<Record<string, UnifiedSession[]>>(() => ({}));
  
  const [loading, setLoading] = useState(false);
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>(() => openTarget?.providerId || "");
  const [archiveFilter, setArchiveFilter] = useState<ArchiveFilter>("active");
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionActionMenuState | null>(null);
  const [workspaceContextMenu, setWorkspaceContextMenu] = useState<WorkspaceActionMenuState | null>(null);
  const [archivingSessionId, setArchivingSessionId] = useState<string | null>(null);
  const [archiveNotice, setArchiveNotice] = useState<ArchiveNotice | null>(null);
  const [taskBoardState, setTaskBoardState] = useState<TaskBoardState>(DEFAULT_TASK_BOARD_STATE);
  const [providerReloadTick, setProviderReloadTick] = useState(0);
  const loadedProvidersRef = useRef<Set<ProviderFilter>>(new Set());
  const activatedProvidersRef = useRef<Set<ProviderFilter>>(new Set());
  const loadingProvidersRef = useRef<Set<ProviderFilter>>(new Set());
  const emptyForceRefreshAttemptsRef = useRef<Map<ProviderFilter, number>>(new Map());
  const loadTokenRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
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
  const pinnedSessionIds = useMemo(
    () => new Set(taskBoardState.pinned.map((item) => `${item.providerId}:${item.sessionId}`)),
    [taskBoardState],
  );

  useEffect(() => {
    return () => {
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
      }
    };
  }, []);

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
    let cancelled = false;
    void invoke<TaskBoardState>("get_task_board_state")
      .then((state) => {
        if (!cancelled) {
          setTaskBoardState(state);
        }
      })
      .catch((error) => {
        console.warn("Failed to load task board pinned sessions", error);
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
    if (openTarget?.providerId === providerFilter) {
      return;
    }
    setSelectedWorkspace(null);
    setSelectedSessionId(null);
    setSessionContextMenu(null);
    setWorkspaceContextMenu(null);
    setArchiveNotice(null);
  }, [openTarget?.providerId, providerFilter]);

  useEffect(() => {
    if (sessionContextMenu === null && workspaceContextMenu === null) {
      return;
    }

    const closeMenu = () => {
      setSessionContextMenu(null);
      setWorkspaceContextMenu(null);
    };
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
  }, [sessionContextMenu, workspaceContextMenu]);

  const loadProvider = useCallback(async (
    provider: ProviderFilter,
    options?: { force?: boolean; forceRefresh?: boolean; acceptEmptySnapshot?: boolean },
  ) => {
    if (!provider) {
      return;
    }
    const force = options?.force ?? false;
    if (!force && loadedProvidersRef.current.has(provider)) {
      return;
    }

    const cachedSessions = readCachedProviderSessionSnapshot(provider);
    if (cachedSessions.length > 0) {
      loadedProvidersRef.current.add(provider);
      setGenericSessionsByProvider((current) => mergeSessionSnapshotsByProvider(
        current,
        provider,
        cachedSessions,
      ));
    }

    const token = ++loadTokenRef.current;
    loadingProvidersRef.current.add(provider);
    setLoading(true);
    try {
      const sessions = await fetchProviderSessions(provider, { forceRefresh: options?.forceRefresh ?? false });
      const normalizedSessions = normalizeGenericProviderSessions(
        provider,
        sessions,
        t.sessions.workspaceFallback,
      );
      const acceptEmptySnapshot = options?.acceptEmptySnapshot === true;
      const emptyRetryCount = emptyForceRefreshAttemptsRef.current.get(provider) ?? 0;
      const snapshotUpdate = resolveSessionSnapshotUpdate(cachedSessions, normalizedSessions, {
        preserveOnEmpty: !acceptEmptySnapshot,
        emptyRetryBudget: options?.forceRefresh && !acceptEmptySnapshot ? 1 : 0,
        emptyRetryCount,
      });
      const cachedMerged = writeCachedProviderSessionSnapshot(provider, snapshotUpdate.sessions, {
        preserveOnEmpty: snapshotUpdate.preserved,
      });
      setGenericSessionsByProvider((current) => mergeSessionSnapshotsByProvider(
        current,
        provider,
        cachedMerged,
        { preserveOnEmpty: snapshotUpdate.preserved },
      ));
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      if (normalizedSessions.length > 0) {
        emptyForceRefreshAttemptsRef.current.delete(provider);
      } else if (snapshotUpdate.shouldRetry) {
        emptyForceRefreshAttemptsRef.current.set(provider, emptyRetryCount + 1);
        retryTimerRef.current = window.setTimeout(() => {
          setProviderReloadTick((current) => current + 1);
        }, 750);
        return false;
      } else {
        emptyForceRefreshAttemptsRef.current.delete(provider);
      }
      loadedProvidersRef.current.add(provider);
      return snapshotUpdate.accepted;
    } catch (error) {
      console.warn(`Failed to load ${provider} sessions`, error);
      if (retryTimerRef.current !== null) {
        window.clearTimeout(retryTimerRef.current);
      }
      retryTimerRef.current = window.setTimeout(() => {
        setProviderReloadTick((current) => current + 1);
      }, 750);
      return false;
    } finally {
      loadingProvidersRef.current.delete(provider);
      if (loadTokenRef.current === token) {
        setLoading(loadingProvidersRef.current.size > 0);
      }
    }
  }, [t.sessions.workspaceFallback]);

  useEffect(() => {
    if (!active || !providerFilter) {
      return;
    }
    const hasLoadedProvider = loadedProvidersRef.current.has(providerFilter);
    const hasActivatedProvider = activatedProvidersRef.current.has(providerFilter);
    if (hasLoadedProvider && hasActivatedProvider) {
      return;
    }

    void (async () => {
      const loaded = await loadProvider(providerFilter, {
        force: true,
        forceRefresh: false,
      });
      if (loaded) {
        activatedProvidersRef.current.add(providerFilter);
      }
    })();
  }, [active, loadProvider, providerFilter, providerReloadTick]);

  useEffect(() => {
    if (!openTarget) {
      return;
    }
    setProviderFilter(openTarget.providerId);
    setArchiveFilter("active");
    setSelectedWorkspace(openTarget.workspace?.trim() || null);
    setSelectedSessionId(openTarget.sessionId);
    setSessionContextMenu(null);
    setWorkspaceContextMenu(null);
    setArchiveNotice(null);
  }, [openTarget?.providerId, openTarget?.sessionId, openTarget?.workspace]);

  useEffect(() => {
    if (!active || !openTarget || openTarget.providerId !== providerFilter) {
      return;
    }
    const providerSessions = genericSessionsByProvider[openTarget.providerId] ?? [];
    const targetWorkspace = openTarget.workspace?.trim() || "";
    const hasTargetSession = providerSessions.some((session) => {
      if (session.id !== openTarget.sessionId) {
        return false;
      }
      if (!targetWorkspace) {
        return true;
      }
      return session.workspace === targetWorkspace;
    });
    if (hasTargetSession) {
      return;
    }
    void loadProvider(openTarget.providerId, {
      force: true,
      forceRefresh: true,
    });
  }, [
    active,
    genericSessionsByProvider,
    loadProvider,
    openTarget,
    providerFilter,
  ]);

  const refreshCurrentProvider = useCallback(async () => {
    await loadProvider(providerFilter, {
      force: true,
      forceRefresh: true,
      acceptEmptySnapshot: true,
    });
  }, [loadProvider, providerFilter]);

  const openSessionContextMenu = useCallback((
    event: MouseEvent<HTMLElement>,
    session: UnifiedSession,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setArchiveNotice(null);
    setWorkspaceContextMenu(null);
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
    setWorkspaceContextMenu(null);
    setSessionContextMenu({
      session,
      x: Math.min(Math.max(rect.right - 176, 8), window.innerWidth - 180),
      y: Math.min(rect.bottom + 6, window.innerHeight - 72),
    });
  }, []);

  const openWorkspaceContextMenu = useCallback((
    event: MouseEvent<HTMLElement>,
    workspace: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    setSessionContextMenu(null);
    setWorkspaceContextMenu({
      workspace,
      x: Math.min(event.clientX, window.innerWidth - 196),
      y: Math.min(event.clientY, window.innerHeight - 118),
    });
  }, []);

  const handleOpenWorkspaceInTerminal = useCallback((workspace: string) => {
    setWorkspaceContextMenu(null);
    void invoke("open_terminal", { workspacePath: workspace }).catch((error) => {
      console.warn("Failed to open workspace in terminal", error);
    });
  }, []);

  const handleOpenWorkspaceInFinder = useCallback((workspace: string) => {
    setWorkspaceContextMenu(null);
    void invoke("open_finder", { workspacePath: workspace }).catch((error) => {
      console.warn("Failed to open workspace in Finder", error);
    });
  }, []);

  const handleCopyWorkspacePath = useCallback((workspace: string) => {
    setWorkspaceContextMenu(null);
    void navigator.clipboard.writeText(workspace).catch((error) => {
      console.warn("Failed to copy workspace path", error);
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

  const handleTogglePinSession = useCallback(async (session: UnifiedSession) => {
    const isPinned = pinnedSessionIds.has(sessionTaskBoardKey(session));
    try {
      const nextState = await invoke<TaskBoardState>(
        isPinned ? "unpin_task_board_session" : "pin_task_board_session",
        {
          providerId: session.type,
          sessionId: session.id,
        },
      );
      setTaskBoardState(nextState);
    } catch (error) {
      console.warn("Failed to update task board pinned session", error);
    }
  }, [pinnedSessionIds]);

  const unifiedSessions = useMemo<UnifiedSession[]>(() => {
    const sessions = genericSessionsByProvider[providerFilter] ?? [];
    return mergeLiveSessionActivities(
      sessions,
      taskBoardActivities.filter((activity) => activity.providerId === providerFilter),
    );
  }, [genericSessionsByProvider, providerFilter, taskBoardActivities]);

  const handleSessionRemapped = useCallback(async (
    previousSession: UnifiedSession,
    sendResult: ProviderSessionSendResult,
  ) => {
    const nextSessionId = sendResult.threadId?.trim();
    if (!nextSessionId || nextSessionId === previousSession.id) {
      return;
    }

    await loadProvider(previousSession.type, {
      force: true,
      forceRefresh: true,
    });
    setSelectedWorkspace(previousSession.workspace || null);
    setSelectedSessionId(nextSessionId);
  }, [loadProvider]);

  const workspaces = useMemo(() => {
    const list = Array.from(new Set(unifiedSessions.map(s => s.workspace)));
    return list.sort();
  }, [unifiedSessions]);

  useEffect(() => {
    if (selectedWorkspace && workspaces.length > 0 && !workspaces.includes(selectedWorkspace)) {
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

  const providerListReady = loadedProvidersRef.current.has(providerFilter);
  const waitingForProviderList = useMemo(() => (
    active &&
    Boolean(providerFilter) &&
    !providerListReady &&
    loading
  ), [active, loading, providerFilter, providerListReady]);

  const waitingForOpenTargetSession = useMemo(() => (
    Boolean(
      active &&
      openTarget &&
      openTarget.providerId === providerFilter &&
      selectedSessionId === openTarget.sessionId &&
      !selectedSession,
    )
  ), [active, openTarget, providerFilter, selectedSession, selectedSessionId]);

  const effectiveSelectedSession = useMemo(() => (
    selectedSession ?? (!selectedSessionId ? filteredSessions[0] ?? null : null)
  ), [filteredSessions, selectedSession, selectedSessionId]);

  const pendingSelectedSession = useMemo(() => (
    hasPendingSelectedSession(unifiedSessions, selectedSessionId) &&
    (loading || waitingForOpenTargetSession)
  ), [loading, selectedSessionId, unifiedSessions, waitingForOpenTargetSession]);

  useEffect(() => {
    const nextSessionId = nextSelectedSessionId(
      filteredSessions,
      selectedSessionId,
      { preserveMissing: waitingForOpenTargetSession },
    );
    if (nextSessionId !== selectedSessionId) {
      setSelectedSessionId(nextSessionId);
    }
  }, [filteredSessions, selectedSessionId, waitingForOpenTargetSession]);

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
          loading={waitingForProviderList}
          noSessionsLabel={waitingForProviderList ? t.common.loading : t.sessions.noSessions}
          onSelectWorkspace={setSelectedWorkspace}
          onOpenWorkspaceContextMenu={openWorkspaceContextMenu}
        />

        <SessionListPanel
          sessions={filteredSessions}
          providerFilter={providerFilter}
          providerLabels={providerLabels}
          selectedSessionId={selectedSessionId}
          archiveFilter={archiveFilter}
          archivingSessionId={archivingSessionId}
          archiveNotice={archiveNotice}
          loading={waitingForProviderList}
          labels={{
            active: "Active",
            archived: "Archived",
            archivingSession: t.sessions.archivingSession,
            noSessions: waitingForProviderList ? t.common.loading : t.sessions.noSessions,
            pinSession: t.sessions.pinSession,
            unpinSession: t.sessions.unpinSession,
            sessionActions: t.sessions.sessionActions,
          }}
          pinnedSessionIds={pinnedSessionIds}
          renderSessionMeta={(session) => (
            session.type === providerFilter ? (
              <div className="pl-1">
                <ProviderSessionBadges session={providerSessionMetadataFromUnifiedSession(session)} compact />
              </div>
            ) : null
          )}
          onArchiveFilterChange={setArchiveFilter}
          onSelectSession={setSelectedSessionId}
          onTogglePinSession={(session) => void handleTogglePinSession(session)}
          onOpenContextMenu={openSessionContextMenu}
          onOpenActionMenu={openSessionActionMenu}
        />

        <div className="min-w-0 flex-1 overflow-hidden rounded-[28px]">
          {effectiveSelectedSession ? (
            <GenericProviderChat
              session={effectiveSelectedSession}
              key={effectiveSelectedSession.id}
              providerSupportsAttachments={Boolean(
                providerCapabilities[effectiveSelectedSession.type]?.files ||
                providerCapabilities[effectiveSelectedSession.type]?.photos
              )}
              onSessionRemapped={
                effectiveSelectedSession.type === providerFilter ? handleSessionRemapped : undefined
              }
              active={active}
            />
          ) : pendingSelectedSession ? (
            <div className="ow-page-frame-soft flex h-full items-center justify-center rounded-[28px]">
              <StatePanel message={t.common.loading} />
            </div>
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
      {workspaceContextMenu ? (
        <WorkspaceActionMenu
          menu={workspaceContextMenu}
          labels={{
            openInTerminal: t.sessions.openWorkspaceInTerminal,
            openInFinder: t.sessions.openWorkspaceInFinder,
            copyPath: t.sessions.copyWorkspacePath,
          }}
          onOpenTerminal={handleOpenWorkspaceInTerminal}
          onOpenFinder={handleOpenWorkspaceInFinder}
          onCopyPath={handleCopyWorkspacePath}
        />
      ) : null}
    </div>
  );
}
