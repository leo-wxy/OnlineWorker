import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { useProviderSessionEventStream } from "../../hooks/useProviderSessionEventStream";
import type {
  ComposerAttachment,
  ProviderSessionSendResult,
  SessionStreamEvent,
  SessionTurn,
} from "../../types";
import { shouldClearReplyWatch } from "../../utils/replyWatch.js";
import { applySessionStreamEvent } from "../../utils/sessionEventModel.js";
import { ProviderSessionBadges } from "./badges";
import {
  buildSnapshotSignature,
  countAssistantEntries,
  hasSessionSnapshotChanged,
  pollAssistantReply,
  startActiveSessionRefresh,
} from "../../utils/sessionPolling.js";
import {
  fetchProviderSession,
  sendProviderSessionMessage,
  startProviderSessionMessage,
} from "./api";
import { useStagedAttachments } from "./composerAttachments";
import { getProviderUi, type UnifiedSession } from "./presentation";
import { providerSessionMetadataFromUnifiedSession } from "./sessionData";
import {
  BACKGROUND_REPLY_POLL,
  CODEX_BACKGROUND_REPLY_POLL,
  CODEX_FOREGROUND_REPLY_POLL,
  FOREGROUND_REPLY_POLL,
  limitSessionTurns,
  mergeSessionTurns,
  overlayPendingUserTurn,
  SessionChatHeader,
  SessionComposer,
  SessionMessages,
  type ReplyWatchState,
} from "./shared";

function isSessionMetadataRich(session: UnifiedSession) {
  const providerSession = providerSessionMetadataFromUnifiedSession(session);
  return Boolean(
    providerSession.modelProvider ||
    providerSession.source ||
    providerSession.approvalMode ||
    providerSession.sandboxPolicy != null ||
    providerSession.isSmoke
  );
}

function usesExtendedReplyPolling(session: UnifiedSession) {
  return isSessionMetadataRich(session);
}

export function GenericProviderChat({
  session,
  providerSupportsAttachments,
  onSessionRemapped,
  onNewSessionStarted,
  onNewSessionPending,
  mode = "session",
  focusComposerKey,
  active = true,
}: {
  session: UnifiedSession;
  providerSupportsAttachments: boolean;
  onSessionRemapped?: (previousSession: UnifiedSession, sendResult: ProviderSessionSendResult) => Promise<void> | void;
  onNewSessionStarted?: (sendResult: ProviderSessionSendResult) => Promise<void> | void;
  onNewSessionPending?: (sendResult: ProviderSessionSendResult, text: string) => Promise<void> | void;
  mode?: "session" | "new-session";
  focusComposerKey?: number;
  active?: boolean;
}) {
  const { t } = useI18n();
  const providerLabel = getProviderUi(session.type).label;
  const [activeSession, setActiveSession] = useState(session);
  const [messages, setMessages] = useState<SessionTurn[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const { stagingAttachments, handlePickFiles } = useStagedAttachments({
    supportsAttachments: providerSupportsAttachments,
    unsupportedMessage: t.sessions.attachmentUnsupported,
    setError,
    setAttachments,
  });
  const [replyWatchState, setReplyWatchState] = useState<ReplyWatchState | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const replyWatchTokenRef = useRef(0);
  const messagesRef = useRef<SessionTurn[]>([]);
  const liveRefreshBlockedRef = useRef(true);
  const liveStreamReadyRef = useRef(false);
  const hasLoadedRef = useRef(false);
  const pendingScrollBehaviorRef = useRef<ScrollBehavior>("auto");
  const pendingUserMessage = typeof activeSession.raw?.lastUserMessage === "string"
    ? activeSession.raw.lastUserMessage.trim()
    : typeof activeSession.raw?.last_user_message === "string"
      ? activeSession.raw.last_user_message.trim()
      : "";
  const pendingEventKind = typeof activeSession.raw?.lastEventKind === "string"
    ? activeSession.raw.lastEventKind.trim()
    : typeof activeSession.raw?.last_event_kind === "string"
      ? activeSession.raw.last_event_kind.trim()
      : "";
  const sessionOverlayRaw = {
    lastUserMessage: pendingUserMessage,
    lastEventKind: pendingEventKind,
  };

  const cancelReplyWatch = useCallback(() => {
    replyWatchTokenRef.current += 1;
    setReplyWatchState(null);
  }, []);

  const applyMessages = useCallback((
    nextMessages: SessionTurn[],
    scrollBehavior: ScrollBehavior = "auto",
  ) => {
    messagesRef.current = nextMessages;
    pendingScrollBehaviorRef.current = scrollBehavior;
    setMessages(nextMessages);
  }, []);

  useEffect(() => {
    liveStreamReadyRef.current = false;
    setActiveSession(session);
  }, [session.id, session.type, session.workspace]);

  useEffect(() => {
    setActiveSession((current) => {
      if (
        current.id !== session.id ||
        current.type !== session.type ||
        current.workspace !== session.workspace
      ) {
        return current;
      }
      return {
        ...current,
        title: session.title,
        archived: session.archived,
        raw: session.raw,
      };
    });
  }, [session.archived, session.raw, session.title, session.id, session.type, session.workspace]);

  const loadMessages = useCallback(async () => {
    if (mode === "new-session") {
      applyMessages([], "auto");
      hasLoadedRef.current = true;
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const turns = await fetchProviderSession(activeSession.type, activeSession.id, activeSession.workspace);
      const nextTurns = overlayPendingUserTurn(turns, sessionOverlayRaw);
      const overlayed = nextTurns !== turns;
      applyMessages(nextTurns, "auto");
      hasLoadedRef.current = true;
      setReplyWatchState((current) => overlayed ? (current ?? "background") : (current === "expired" ? null : current));
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [
    activeSession.id,
    activeSession.type,
    activeSession.workspace,
    applyMessages,
    mode,
    pendingEventKind,
    pendingUserMessage,
  ]);

  const refreshMessagesSilently = useCallback(async () => {
    if (mode === "new-session") {
      return;
    }
    try {
      const turns = await fetchProviderSession(activeSession.type, activeSession.id, activeSession.workspace);
      const nextTurns = overlayPendingUserTurn(turns, sessionOverlayRaw);
      const overlayed = nextTurns !== turns;
      hasLoadedRef.current = true;
      if (!hasSessionSnapshotChanged(messagesRef.current, nextTurns)) {
        setReplyWatchState((current) => overlayed ? (current ?? "background") : (current === "expired" ? null : current));
        return;
      }
      applyMessages(nextTurns, "auto");
      setReplyWatchState((current) => overlayed ? (current ?? "background") : (current === "expired" ? null : current));
    } catch (loadError) {
      if (messagesRef.current.length === 0) {
        setError((loadError as Error).message);
      } else {
        console.warn("Provider session silent refresh failed", loadError);
      }
    }
  }, [
    activeSession.id,
    activeSession.type,
    activeSession.workspace,
    applyMessages,
    mode,
    pendingEventKind,
    pendingUserMessage,
  ]);

  useEffect(() => {
    if (!active) {
      return;
    }
    cancelReplyWatch();
    setAttachments([]);
    if (hasLoadedRef.current && messagesRef.current.length > 0) {
      void refreshMessagesSilently();
    } else {
      void loadMessages();
    }
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [active, loadMessages, refreshMessagesSilently, cancelReplyWatch]);

  useEffect(() => {
    liveRefreshBlockedRef.current =
      loading || sending || (replyWatchState !== null && replyWatchState !== "expired");
  }, [loading, sending, replyWatchState]);

  useEffect(() => {
    const behavior = pendingScrollBehaviorRef.current;
    endRef.current?.scrollIntoView({ behavior });
    pendingScrollBehaviorRef.current = "auto";
  }, [messages]);

  const handleSessionEvent = useCallback((event: SessionStreamEvent) => {
    if (event?.kind === "stream_ready") {
      liveStreamReadyRef.current = true;
      return;
    }
    if (event?.kind === "error") {
      liveStreamReadyRef.current = false;
      if (messagesRef.current.length === 0) {
        setError(event.error ?? "provider session stream error");
      } else {
        console.warn("Provider session event stream error", event.error);
      }
      replyWatchTokenRef.current += 1;
      setReplyWatchState((current) => (current ? "expired" : current));
      return;
    }

    const previousMessages = messagesRef.current;
    const nextMessages = limitSessionTurns(applySessionStreamEvent(previousMessages, event));
    if (nextMessages === previousMessages) {
      return;
    }
    applyMessages(nextMessages, "auto");
    if (shouldClearReplyWatch(previousMessages, nextMessages, event)) {
      cancelReplyWatch();
    }
  }, [applyMessages, cancelReplyWatch]);

  useProviderSessionEventStream({
    enabled: active && mode !== "new-session" && Boolean(activeSession.id),
    providerId: activeSession.type,
    sessionId: activeSession.id,
    workspaceDir: activeSession.workspace ?? null,
    onEvent: handleSessionEvent,
  });

  useEffect(() => {
    if (!active) {
      return;
    }
    if (mode === "new-session") {
      return;
    }
    if (!activeSession.id) {
      return;
    }

    const cleanup = startActiveSessionRefresh({
      intervalMs: 3000,
      getCurrentSnapshot: () => messagesRef.current,
      loadSnapshot: async () => {
        return overlayPendingUserTurn(await fetchProviderSession(
          activeSession.type,
          activeSession.id,
          activeSession.workspace,
        ), sessionOverlayRaw);
      },
      onSnapshot: (snapshot) => {
        const overlayed = Boolean(
          pendingUserMessage
          && (pendingEventKind === "message.user.submitted" || pendingEventKind === "message.user.accepted")
          && snapshot[snapshot.length - 1]?.role === "user"
          && snapshot[snapshot.length - 1]?.content === pendingUserMessage,
        );
        applyMessages(snapshot, "auto");
        setReplyWatchState((current) => overlayed ? (current ?? "background") : (current === "expired" ? null : current));
      },
      shouldSkip: () => liveRefreshBlockedRef.current,
      onError: (error) => {
        console.warn("Provider session snapshot refresh failed", error);
      },
    });

    return cleanup;
  }, [
    active,
    activeSession.id,
    activeSession.type,
    activeSession.workspace,
    mode,
    pendingEventKind,
    pendingUserMessage,
  ]);

  const handleSend = async (trimmedText: string, nextAttachments: ComposerAttachment[]) => {
    if (!trimmedText.trim() && nextAttachments.length === 0) {
      return;
    }

    const previousMessages = messagesRef.current;
    const optimisticMessages = limitSessionTurns([
      ...previousMessages,
      {
        role: "user" as const,
        content: trimmedText,
        displayMode: "plain" as const,
      },
    ]);

    const replyWatchToken = replyWatchTokenRef.current + 1;
    replyWatchTokenRef.current = replyWatchToken;
    const shouldContinue = () => replyWatchTokenRef.current === replyWatchToken;

    setSending(true);
    setError(null);
    applyMessages(optimisticMessages, "smooth");
    setReplyWatchState("foreground");

    const baselineAssistantCount = countAssistantEntries(previousMessages);

    try {
      const sendResult = mode === "new-session"
        ? await startProviderSessionMessage(
            activeSession.type,
            activeSession.workspace,
            trimmedText,
            nextAttachments,
          )
        : await sendProviderSessionMessage(
            activeSession.type,
            activeSession.id,
            trimmedText,
            nextAttachments,
            activeSession.workspace,
      );
      const remappedSessionId = sendResult.threadId?.trim();
      if (mode === "new-session" && !remappedSessionId) {
        if (sendResult.pending && sendResult.accepted !== false) {
          await onNewSessionPending?.(sendResult, trimmedText);
          setAttachments([]);
          setReplyWatchState("background");
          return true;
        }
        throw new Error("provider did not return a real session id");
      }
      if (remappedSessionId && remappedSessionId !== activeSession.id) {
        const nextSession = {
          ...activeSession,
          id: remappedSessionId,
        };
        setActiveSession(nextSession);
        if (mode === "new-session") {
          await onNewSessionStarted?.(sendResult);
        } else {
          await onSessionRemapped?.(activeSession, sendResult);
        }
      }
      setAttachments([]);
      if (mode === "new-session") {
        setReplyWatchState("background");
        return true;
      }

      const loadSnapshot = async () => {
        const currentSession = remappedSessionId && remappedSessionId !== activeSession.id
          ? {
              ...activeSession,
              id: remappedSessionId,
            }
          : activeSession;
        const snapshot = await fetchProviderSession(
          currentSession.type,
          currentSession.id,
          currentSession.workspace,
        );
        const overlaySnapshot = overlayPendingUserTurn(snapshot, {
          lastUserMessage: trimmedText,
          lastEventKind: "message.user.accepted",
        });
        const shouldMergeSnapshot = remappedSessionId && remappedSessionId !== activeSession.id;
        const nextSnapshot = shouldMergeSnapshot
          ? mergeSessionTurns(previousMessages, overlaySnapshot)
          : overlaySnapshot;
        if (shouldContinue()) {
          messagesRef.current = nextSnapshot;
        }
        return nextSnapshot;
      };
      const applySnapshot = (snapshot: SessionTurn[]) => {
        const shouldMergeSnapshot = remappedSessionId && remappedSessionId !== activeSession.id;
        const nextSnapshot = shouldMergeSnapshot
          ? mergeSessionTurns(previousMessages, snapshot)
          : snapshot;
        if (shouldContinue()) {
          applyMessages(nextSnapshot, "auto");
        }
      };

      const foregroundResult = await pollAssistantReply({
        loadSnapshot,
        getAssistantCount: countAssistantEntries,
        getSignature: buildSnapshotSignature,
        baselineAssistantCount,
        baselineSnapshot: previousMessages,
        onUpdate: applySnapshot,
        shouldContinue,
        ...(usesExtendedReplyPolling(activeSession) ? CODEX_FOREGROUND_REPLY_POLL : FOREGROUND_REPLY_POLL),
      });
      if (!shouldContinue()) {
        return;
      }

      applyMessages(foregroundResult.snapshot, "auto");
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
          baselineSnapshot: previousMessages,
          onUpdate: applySnapshot,
          shouldContinue,
          ...(usesExtendedReplyPolling(activeSession) ? CODEX_BACKGROUND_REPLY_POLL : BACKGROUND_REPLY_POLL),
        });
        if (!shouldContinue()) {
          return;
        }

        applyMessages(backgroundResult.snapshot, "auto");
        setReplyWatchState(backgroundResult.settled ? null : "expired");
      })();
    } catch (sendError) {
      cancelReplyWatch();
      setError((sendError as Error).message);
      applyMessages(previousMessages, "auto");
      return false;
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <SessionChatHeader
        title={activeSession.title}
        shortId={activeSession.id.slice(0, 12)}
        loading={loading}
        reloadTitle={t.sessions.reloadMessages}
        badge={(
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-700">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-500"></span>
            {providerLabel}
          </span>
        )}
        onReload={() => void loadMessages()}
      >
        {isSessionMetadataRich(activeSession) ? (
          <ProviderSessionBadges session={providerSessionMetadataFromUnifiedSession(activeSession)} />
        ) : null}
      </SessionChatHeader>

      <SessionMessages
        loading={loading}
        error={error}
        messages={messages}
        assistantLabel={providerLabel}
        labels={{
          loading: t.common.loading,
          noMessages: t.sessions.noMessages,
          waitingForReply: t.sessions.waitingForReply,
          waitingInBackground: t.sessions.waitingInBackground,
          waitingExpired: t.sessions.waitingExpired,
        }}
        endRef={endRef}
        replyWatchState={replyWatchState}
        minHeight={false}
      />

      <SessionComposer
        resetKey={activeSession.id}
        focusKey={focusComposerKey}
        sending={sending}
        placeholder={t.sessions.sendPlaceholder}
        sendLabel={t.sessions.send}
        assistantLabel={providerLabel}
        stagingAttachments={stagingAttachments}
        attachments={attachments}
        onAttachmentsChange={setAttachments}
        supportsAttachments={providerSupportsAttachments}
        onPickFiles={handlePickFiles}
        attachmentButtonLabel={t.sessions.attachFile}
        imageButtonLabel={t.sessions.attachImage}
        onSend={handleSend}
      />
    </div>
  );
}
