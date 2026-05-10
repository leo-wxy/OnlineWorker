import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useI18n } from "../i18n";
import { useCodexThreadStream } from "../hooks/useCodexThreadStream";
import {
  fetchClaudeMessages,
  fetchClaudeSessions,
  fetchCodexSessions,
  fetchCodexThreadState,
  fetchCodexThreadUpdates,
  fetchProviderMetadata,
  fetchProviderSessions,
  sendClaudeMessage,
  sendCodexMessage,
} from "../components/session-browser/api";
import {
  BACKGROUND_REPLY_POLL,
  CODEX_BACKGROUND_REPLY_POLL,
  CODEX_FOREGROUND_REPLY_POLL,
  FOREGROUND_REPLY_POLL,
  limitSessionTurns,
  mergeSessionTurns,
  ReplyWatchState,
  SessionComposer,
  TurnBubble,
} from "../components/session-browser/shared";
import {
  PROVIDER_UI,
  StatePanel,
  getProviderUi,
  type ArchiveFilter,
  type ProviderFilter,
  type UnifiedSession,
} from "../components/session-browser/presentation";
import { applyCodexStreamEvent } from "../utils/codexSessionStream.js";
import { visibleSessionProviders } from "../utils/sessionProviders.js";
import {
  buildSnapshotSignature,
  countAssistantEntries,
  pollAssistantReply,
} from "../utils/sessionPolling.js";
import { shouldClearReplyWatch } from "../utils/replyWatch.js";
import type {
  ClaudeSession,
  CodexSession,
  CodexThreadCursor,
  CodexThreadStreamEvent,
  ProviderMetadata,
  SessionTurn,
} from "../types";

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

function normalizeGenericProviderSessions(
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

function CodexSessionBadges({ session, compact = false }: { session: CodexSession; compact?: boolean }) {
  const { t } = useI18n();
  const badges = [
    session.modelProvider ? t.sessions.providerBadge(session.modelProvider) : null,
    session.source ? t.sessions.sourceBadge(session.source) : null,
    session.isSmoke ? t.sessions.smokeBadge : null,
  ].filter((value): value is string => Boolean(value));

  if (badges.length === 0) {
    return null;
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "" : "mt-3"}`}>
      {badges.map((badge) => (
        <span
          key={badge}
          className="inline-flex items-center rounded-full border border-slate-200 bg-white/88 px-2.5 py-1 text-[10px] font-semibold tracking-[0.04em] text-slate-500"
        >
          {badge}
        </span>
      ))}
    </div>
  );
}

function CodexChat({ session }: { session: UnifiedSession }) {
  const { t } = useI18n();
  const rawSession = session.raw as CodexSession;
  
  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [turnsError, setTurnsError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [replyWatchState, setReplyWatchState] = useState<ReplyWatchState | null>(null);
  const turnsEndRef = useRef<HTMLDivElement>(null);
  const replyWatchTokenRef = useRef(0);
  const turnsRef = useRef<SessionTurn[]>([]);
  const codexCursorRef = useRef<CodexThreadCursor | null>(null);
  const [codexStreamCursor, setCodexStreamCursor] = useState<CodexThreadCursor | null>(null);

  const cancelReplyWatch = useCallback(() => {
    replyWatchTokenRef.current += 1;
    setReplyWatchState(null);
  }, []);

  const loadTurns = useCallback(async () => {
    setTurnsLoading(true);
    setTurnsError(null);
    setTurns([]);
    turnsRef.current = [];
    codexCursorRef.current = null;
    setCodexStreamCursor(null);
    try {
      const snapshot = await fetchCodexThreadState(rawSession.rolloutPath ?? "");
      codexCursorRef.current = snapshot.cursor;
      turnsRef.current = snapshot.turns;
      setTurns(snapshot.turns);
      setCodexStreamCursor(snapshot.cursor);
      setReplyWatchState((current) => (current === "expired" ? null : current));
    } catch (loadError) {
      setTurnsError((loadError as Error).message);
    } finally {
      setTurnsLoading(false);
    }
  }, [rawSession.rolloutPath]);

  useEffect(() => {
    cancelReplyWatch();
    void loadTurns();
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [session.id, loadTurns, cancelReplyWatch]);

  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  useEffect(() => {
    turnsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  const handleCodexStreamEvent = useCallback((event: CodexThreadStreamEvent) => {
    if (event.cursor) {
      codexCursorRef.current = event.cursor;
    }
    if (event.kind === "error") {
      setTurnsError(event.error ?? "codex stream error");
      cancelReplyWatch();
      return;
    }

    const previousTurns = turnsRef.current;
    const nextTurns = limitSessionTurns(applyCodexStreamEvent(previousTurns, event));
    turnsRef.current = nextTurns;
    setTurns(nextTurns);

    if (shouldClearReplyWatch(previousTurns, nextTurns, event)) {
      cancelReplyWatch();
    }
  }, [cancelReplyWatch]);

  useCodexThreadStream({
    enabled: Boolean(rawSession.rolloutPath && codexStreamCursor),
    rolloutPath: rawSession.rolloutPath ?? null,
    cursor: codexStreamCursor,
    onEvent: handleCodexStreamEvent,
  });

  const handleSend = async (text: string) => {
    if (!rawSession.rolloutPath || !text.trim() || sending) {
      return;
    }

    const trimmedText = text.trim();
    const rolloutPath = rawSession.rolloutPath;
    const threadId = rawSession.threadId;
    const previousTurns = turnsRef.current;
    const baselineAssistantCount = countAssistantEntries(previousTurns);
    const replyWatchToken = replyWatchTokenRef.current + 1;
    const optimisticTurns = limitSessionTurns([
      ...previousTurns,
      { role: "user" as const, content: trimmedText },
    ]);

    replyWatchTokenRef.current = replyWatchToken;

    setSending(true);
    setTurnsError(null);
    setReplyWatchState("foreground");
    turnsRef.current = optimisticTurns;
    setTurns(optimisticTurns);

    try {
      await sendCodexMessage(threadId, trimmedText, rawSession.cwd);

      const shouldContinue = () => replyWatchTokenRef.current === replyWatchToken;
      const loadSnapshot = async () => {
        const currentCursor = codexCursorRef.current;
        const result = currentCursor
          ? await fetchCodexThreadUpdates(rolloutPath, currentCursor)
          : await fetchCodexThreadState(rolloutPath);
        if (shouldContinue()) {
          codexCursorRef.current = result.cursor;
        }
        const baseTurns = turnsRef.current;
        const nextTurns = result.replace
          ? limitSessionTurns(result.turns)
          : mergeSessionTurns(baseTurns, result.turns);
        if (shouldContinue()) {
          turnsRef.current = nextTurns;
        }
        return nextTurns;
      };
      const applySnapshot = (snapshot: SessionTurn[]) => {
        if (shouldContinue()) {
          turnsRef.current = snapshot;
          setTurns(snapshot);
        }
      };

      const foregroundResult = await pollAssistantReply({
        loadSnapshot,
        getAssistantCount: countAssistantEntries,
        getSignature: buildSnapshotSignature,
        baselineAssistantCount,
        baselineSnapshot: previousTurns,
        onUpdate: applySnapshot,
        shouldContinue,
        ...CODEX_FOREGROUND_REPLY_POLL,
      });
      if (!shouldContinue()) {
        return;
      }

      turnsRef.current = foregroundResult.snapshot;
      setTurns(foregroundResult.snapshot);
      if (foregroundResult.settled) {
        setReplyWatchState(null);
        return;
      }

      setReplyWatchState("background");
      void (async () => {
        const backgroundResult = await pollAssistantReply({
          loadSnapshot,
          getAssistantCount: countAssistantEntries,
          getSignature: buildSnapshotSignature,
          baselineAssistantCount,
          baselineSnapshot: previousTurns,
          onUpdate: applySnapshot,
          shouldContinue,
          ...CODEX_BACKGROUND_REPLY_POLL,
        });
        if (!shouldContinue()) {
          return;
        }

        turnsRef.current = backgroundResult.snapshot;
        setTurns(backgroundResult.snapshot);
        setReplyWatchState(backgroundResult.settled ? null : "expired");
      })();
    } catch (sendError) {
      cancelReplyWatch();
      setTurnsError((sendError as Error).message);
      turnsRef.current = previousTurns;
      setTurns(previousTurns);
    } finally {
      setSending(false);
    }
  };

  const replyWatchText = replyWatchState === "foreground"
    ? t.sessions.waitingForReply
    : replyWatchState === "background"
      ? t.sessions.waitingInBackground
      : replyWatchState === "expired"
        ? t.sessions.waitingExpired
        : null;

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <div className="border-b border-[var(--ow-line-soft)] bg-white/74 px-5 py-4 backdrop-blur-xl">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${PROVIDER_UI.codex.chip}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${PROVIDER_UI.codex.dot}`}></span>
                Codex
              </span>
              <span className="rounded-full border border-slate-200 bg-white/88 px-2.5 py-1 font-mono text-[10px] text-slate-500">
                {session.id.slice(0, 12)}
              </span>
            </div>
            <h3 className="truncate text-base font-bold tracking-[-0.02em] text-gray-950">{session.title}</h3>
            <CodexSessionBadges session={rawSession} />
          </div>

          <button
            onClick={() => void loadTurns()}
            disabled={turnsLoading}
            className="ow-btn inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-slate-600 transition-colors hover:text-gray-900 disabled:opacity-50"
            title={t.sessions.reloadMessages}
          >
            <svg className={`h-4 w-4 ${turnsLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            Reload
          </button>
        </div>
      </div>

      <div className="chat-bg flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto flex max-w-4xl flex-col gap-6">
          {turnsLoading ? (
            <StatePanel message={t.common.loading} />
          ) : turnsError ? (
            <StatePanel message={turnsError} tone="error" />
          ) : turns.length === 0 ? (
            <StatePanel message={t.sessions.noMessages} />
          ) : (
            turns.map((turn, index) => (
              <TurnBubble key={`${turn.role}-${index}-${turn.content}`} turn={turn} assistantLabel="Codex" />
            ))
          )}
          {replyWatchText && (
            <p className={`px-3 pb-1 text-center text-xs ${replyWatchState === "expired" ? "text-amber-600" : "text-slate-400"}`}>
              {replyWatchText}
            </p>
          )}
          <div ref={turnsEndRef} />
        </div>
      </div>

      <SessionComposer
        resetKey={session.id}
        sending={sending}
        disabled={!rawSession.rolloutPath}
        placeholder={t.sessions.sendPlaceholder}
        sendLabel={t.sessions.send}
        assistantLabel="Codex"
        onSend={handleSend}
      />
    </div>
  );
}

function ClaudeChat({ session, refreshSessions }: { session: UnifiedSession; refreshSessions: () => Promise<void> }) {
  const { t } = useI18n();
  const rawSession = session.raw as ClaudeSession;
  
  const [messages, setMessages] = useState<SessionTurn[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [replyWatchState, setReplyWatchState] = useState<ReplyWatchState | null>(null);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const replyWatchTokenRef = useRef(0);
  const messagesRef = useRef<SessionTurn[]>([]);

  const cancelReplyWatch = useCallback(() => {
    replyWatchTokenRef.current += 1;
    setReplyWatchState(null);
  }, []);

  const loadMessages = useCallback(async () => {
    setMsgLoading(true);
    setMsgError(null);
    setMessages([]);
    messagesRef.current = [];
    try {
      const nextMessages = await fetchClaudeMessages(rawSession.sessionId, rawSession.workspace);
      messagesRef.current = nextMessages;
      setMessages(nextMessages);
      setReplyWatchState((current) => (current === "expired" ? null : current));
    } catch (loadError) {
      setMsgError((loadError as Error).message);
    } finally {
      setMsgLoading(false);
    }
  }, [rawSession.sessionId, rawSession.workspace]);

  useEffect(() => {
    cancelReplyWatch();
    void loadMessages();
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [session.id, loadMessages, cancelReplyWatch]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = async (text: string) => {
    if (!text.trim() || sending) {
      return;
    }

    const trimmedText = text.trim();
    const originalSessionId = rawSession.sessionId;
    const previousMessages = messagesRef.current;
    const baselineAssistantCount = countAssistantEntries(previousMessages);
    const replyWatchToken = replyWatchTokenRef.current + 1;

    replyWatchTokenRef.current = replyWatchToken;

    setSending(true);
    setMsgError(null);
    setReplyWatchState("foreground");

    const tempMsg: SessionTurn = {
      role: "user",
      content: trimmedText,
    };
    messagesRef.current = limitSessionTurns([...previousMessages, tempMsg]);
    setMessages(messagesRef.current);

    try {
      const sendResult = await sendClaudeMessage(
        originalSessionId,
        trimmedText,
        rawSession.workspace,
      );
      const activeSessionId = sendResult.sessionId || originalSessionId;
      const bridgePrefix = activeSessionId === originalSessionId ? [] : previousMessages;

      if (activeSessionId !== originalSessionId) {
        // Here we just refresh sessions, since the parent will update the selected session
        // we might not get the immediate re-render here, but the data will be fresh
        void refreshSessions();
      }

      const shouldContinue = () => replyWatchTokenRef.current === replyWatchToken;
      const applySnapshot = (snapshot: SessionTurn[]) => {
        const nextSnapshot = bridgePrefix.length === 0
          ? snapshot
          : mergeSessionTurns(bridgePrefix, snapshot);
        if (shouldContinue()) {
          messagesRef.current = nextSnapshot;
          setMessages(nextSnapshot);
        }
      };

      const foregroundResult = await pollAssistantReply({
        loadSnapshot: async () => {
          const snapshot = await fetchClaudeMessages(activeSessionId, rawSession.workspace);
          return bridgePrefix.length === 0
            ? snapshot
            : mergeSessionTurns(bridgePrefix, snapshot);
        },
        getAssistantCount: countAssistantEntries,
        getSignature: buildSnapshotSignature,
        baselineAssistantCount,
        baselineSnapshot: previousMessages,
        onUpdate: applySnapshot,
        shouldContinue,
        ...FOREGROUND_REPLY_POLL,
      });
      if (!shouldContinue()) {
        return;
      }

      messagesRef.current = foregroundResult.snapshot;
      setMessages(foregroundResult.snapshot);
      if (foregroundResult.settled) {
        setReplyWatchState(null);
        return;
      }

      setReplyWatchState("background");
      void (async () => {
        const backgroundResult = await pollAssistantReply({
          loadSnapshot: async () => {
            const snapshot = await fetchClaudeMessages(activeSessionId, rawSession.workspace);
            return bridgePrefix.length === 0
              ? snapshot
              : mergeSessionTurns(bridgePrefix, snapshot);
          },
          getAssistantCount: countAssistantEntries,
          getSignature: buildSnapshotSignature,
          baselineAssistantCount,
          baselineSnapshot: previousMessages,
          onUpdate: applySnapshot,
          shouldContinue,
          ...BACKGROUND_REPLY_POLL,
        });
        if (!shouldContinue()) {
          return;
        }

        messagesRef.current = backgroundResult.snapshot;
        setMessages(backgroundResult.snapshot);
        setReplyWatchState(backgroundResult.settled ? null : "expired");
      })();
    } catch (sendError) {
      cancelReplyWatch();
      setMsgError((sendError as Error).message);
      messagesRef.current = previousMessages;
      setMessages(previousMessages);
    } finally {
      setSending(false);
    }
  };

  const replyWatchText = replyWatchState === "foreground"
    ? t.sessions.waitingForReply
    : replyWatchState === "background"
      ? t.sessions.waitingInBackground
      : replyWatchState === "expired"
        ? t.sessions.waitingExpired
        : null;

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <div className="border-b border-[var(--ow-line-soft)] bg-white/74 px-5 py-4 backdrop-blur-xl">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${PROVIDER_UI.claude.chip}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${PROVIDER_UI.claude.dot}`}></span>
                Claude
              </span>
              <span className="rounded-full border border-slate-200 bg-white/88 px-2.5 py-1 font-mono text-[10px] text-slate-500">
                {session.id.slice(0, 12)}
              </span>
            </div>
            <h3 className="truncate text-base font-bold tracking-[-0.02em] text-gray-950">{session.title}</h3>
          </div>

          <button
            onClick={() => void loadMessages()}
            disabled={msgLoading}
            className="ow-btn inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-slate-600 transition-colors hover:text-gray-900 disabled:opacity-50"
            title={t.sessions.reloadMessages}
          >
            <svg className={`h-4 w-4 ${msgLoading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            Reload
          </button>
        </div>
      </div>

      <div className="chat-bg flex-1 overflow-y-auto px-5 py-5">
        <div className="mx-auto flex max-w-4xl flex-col gap-6">
          {msgLoading ? (
            <StatePanel message={t.common.loading} />
          ) : msgError ? (
            <StatePanel message={msgError} tone="error" />
          ) : messages.length === 0 ? (
            <StatePanel message={t.sessions.noMessages} />
          ) : (
            messages.map((turn, index) => (
              <TurnBubble key={`${turn.role}-${index}-${turn.content}`} turn={turn} assistantLabel="Claude" />
            ))
          )}
          {replyWatchText && (
            <p className={`px-3 pb-1 text-center text-xs ${replyWatchState === "expired" ? "text-amber-600" : "text-slate-400"}`}>
              {replyWatchText}
            </p>
          )}
          <div ref={msgEndRef} />
        </div>
      </div>

      <SessionComposer
        resetKey={session.id}
        sending={sending}
        placeholder={t.sessions.sendPlaceholder}
        sendLabel={t.sessions.send}
        assistantLabel="Claude"
        onSend={handleSend}
      />
    </div>
  );
}

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
  const loadedProvidersRef = useRef<Set<ProviderFilter>>(new Set());
  const loadTokenRef = useRef(0);
  const visibleProviders = useMemo(
    () => visibleSessionProviders(providers) as ProviderMetadata[],
    [providers],
  );
  const providerLabels = useMemo(() => Object.fromEntries(
    visibleProviders.map((provider) => [provider.id, provider.label || provider.id]),
  ) as Record<string, string>, [visibleProviders]);

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
  }, [providerFilter]);

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
      <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
        <div className="ow-toolbar flex items-center justify-between gap-3 rounded-[22px] px-3 py-2.5">
          <div className="ow-segment inline-flex rounded-2xl p-1">
            {visibleProviders.map((provider) => {
              const p = provider.id;
              const ui = getProviderUi(p, provider.label);
              return (
              <button
                key={p}
                onClick={() => setProviderFilter(p)}
                className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-all ${
                  providerFilter === p
                    ? `${ui.tabActive}`
                    : "text-slate-500 hover:text-gray-800"
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${ui.dot}`}></span>
                {ui.label}
              </button>
              );
            })}
          </div>

          <button
            onClick={() => void refreshCurrentProvider()}
            className="ow-btn inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-600 transition-colors hover:text-gray-900"
          >
            <svg className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            Refresh
          </button>
        </div>
      </div>

      <div className="flex flex-1 gap-3 overflow-hidden p-3">
        <div className="ow-page-frame-soft flex w-[268px] shrink-0 flex-col overflow-hidden rounded-[26px]">
          <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Workspaces</p>
                <p className="mt-1 text-xs text-slate-400">Filter by project path</p>
              </div>
              <span className="rounded-full border border-white/80 bg-white/85 px-2.5 py-1 text-[11px] font-semibold text-slate-500 shadow-sm">
                {workspaces.length}
              </span>
            </div>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
            {workspaces.length === 0 ? (
              <StatePanel message={t.sessions.noSessions} />
            ) : workspaces.map((ws) => {
              const name = ws.split("/").pop() || ws;
              const count = unifiedSessions.filter((s) => s.workspace === ws).length;
              const isActive = selectedWorkspace === ws;
              const providerUi = getProviderUi(providerFilter, providerLabels[providerFilter]);
              const activeClasses = isActive
                ? providerUi.workspaceActive
                : "border-transparent bg-white/50 hover:border-[var(--ow-line)] hover:bg-white/88";

              return (
                <button
                  key={ws}
                  onClick={() => setSelectedWorkspace(isActive ? null : ws)}
                  className={`group flex w-full items-center gap-3 rounded-[20px] border px-3 py-3 text-left transition-all ${activeClasses}`}
                >
                  <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-2xl ${
                    isActive
                      ? providerUi.iconActive
                      : "bg-white/88 text-slate-400 group-hover:text-slate-600"
                  }`}>
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                    </svg>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-sm ${isActive ? "font-semibold text-gray-950" : "font-medium text-gray-700"}`}>{name}</span>
                    <span className="mt-1 block truncate text-[11px] text-slate-400">{ws}</span>
                  </span>
                  <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                    isActive
                      ? "border border-white/80 bg-white/92 text-slate-700 shadow-sm"
                      : "bg-slate-100/90 text-slate-500"
                  }`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="ow-page-frame-soft flex w-[328px] shrink-0 flex-col overflow-hidden rounded-[26px]">
          <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Sessions</p>
                <p className="mt-1 text-xs text-slate-400">Keep the reading path unchanged</p>
              </div>
              {(() => {
                const providerUi = getProviderUi(providerFilter, providerLabels[providerFilter]);
                return (
                  <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${providerUi.chip}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${providerUi.dot}`}></span>
                    {providerUi.label}
                  </span>
                );
              })()}
            </div>

            <div className="ow-segment mt-3 grid grid-cols-2 rounded-2xl p-1">
              <button
                onClick={() => setArchiveFilter("active")}
                className={`rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
                  archiveFilter === "active"
                    ? "ow-segment-button-active"
                    : "ow-segment-button hover:text-gray-700"
                }`}
              >
                Active
              </button>
              <button
                onClick={() => setArchiveFilter("archived")}
                className={`rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
                  archiveFilter === "archived"
                    ? "ow-segment-button-active"
                    : "ow-segment-button hover:text-gray-700"
                }`}
              >
                Archived
              </button>
            </div>
          </div>

          <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
            {filteredSessions.length === 0 ? (
              <StatePanel message={t.sessions.noSessions} />
            ) : filteredSessions.map((session) => {
              const isActive = selectedSessionId === session.id;
              const ui = getProviderUi(session.type, providerLabels[session.type]);

              return (
                <button
                  key={session.id}
                  onClick={() => setSelectedSessionId(session.id)}
                  className={`relative flex w-full flex-col rounded-[22px] border px-4 py-4 text-left transition-all ${
                    isActive
                      ? `${ui.sessionActive} shadow-[0_12px_28px_rgba(15,23,42,0.08)]`
                      : "border-transparent bg-white/72 hover:border-[var(--ow-line)] hover:bg-white"
                  }`}
                >
                  {isActive && (
                    <span className={`absolute left-0 top-4 bottom-4 w-1 rounded-r-full ${ui.dot}`}></span>
                  )}
                  <div className="mb-2 flex items-center justify-between gap-2 pl-1">
                    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${ui.chip}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${ui.dot}`}></span>
                      {ui.label}
                    </span>
                  </div>
                  <h4 className={`line-clamp-2 pl-1 text-sm leading-6 ${isActive ? "font-semibold text-gray-950" : "font-medium text-gray-700"}`}>
                    {session.title}
                  </h4>
                  {session.type === "codex" ? (
                    <div className="pl-1">
                      <CodexSessionBadges session={session.raw as CodexSession} compact />
                    </div>
                  ) : null}
                  <p className="mt-2 truncate pl-1 font-mono text-[11px] text-slate-400">
                    {session.id.slice(0, 12)}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        <div className="min-w-0 flex-1 overflow-hidden rounded-[28px]">
          {selectedSession ? (
            selectedSession.type === "codex" ? <CodexChat session={selectedSession} key={selectedSession.id} /> :
            selectedSession.type === "claude" ? <ClaudeChat session={selectedSession} key={selectedSession.id} refreshSessions={refreshCurrentProvider} /> :
            <div className="ow-page-frame-soft flex h-full items-center justify-center rounded-[28px]">
              <StatePanel message={`${providerLabels[selectedSession.type] ?? selectedSession.type} chat is not available`} />
            </div>
          ) : (
            <div className="ow-page-frame-soft flex h-full items-center justify-center rounded-[28px]">
              <StatePanel message={t.sessions.selectSession} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
