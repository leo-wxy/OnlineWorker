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
  sendProviderSessionMessage,
  startProviderSessionMessage,
} from "./api";
import { useStagedAttachments } from "./composerAttachments";
import { sessionIdentityKey } from "../../utils/sessionBrowserState.js";
import { getProviderUi, type UnifiedSession } from "./presentation";
import { providerSessionMetadataFromUnifiedSession } from "./sessionData";
import {
  limitSessionTurns,
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
    scopeKey: sessionIdentityKey(session),
    supportsAttachments: providerSupportsAttachments,
    unsupportedMessage: t.sessions.attachmentUnsupported,
    setError,
    setAttachments,
  });
  const [replyWatchState, setReplyWatchState] = useState<ReplyWatchState | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const replyWatchTokenRef = useRef(0);
  const newSessionRequestRef = useRef<{ payload: string; id: string } | null>(null);
  const messagesRef = useRef<SessionTurn[]>([]);
  const scopeGenerationRef = useRef(0);
  useEffect(() => {
    scopeGenerationRef.current += 1;
    return () => { scopeGenerationRef.current += 1; };
  }, [session.id, session.type, session.workspace]);
  const [streamReloadKey, setStreamReloadKey] = useState(0);
  const pendingScrollBehaviorRef = useRef<ScrollBehavior>("auto");

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

  const loadMessages = useCallback(() => {
    if (mode === "new-session") {
      applyMessages([], "auto");
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    setStreamReloadKey((current) => current + 1);
  }, [applyMessages, mode]);

  useEffect(() => {
    if (!active) {
      return;
    }
    cancelReplyWatch();
    setAttachments([]);
    if (mode === "new-session") loadMessages();
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [active, loadMessages, mode, cancelReplyWatch]);

  useEffect(() => {
    const behavior = pendingScrollBehaviorRef.current;
    endRef.current?.scrollIntoView({ behavior });
    pendingScrollBehaviorRef.current = "auto";
  }, [messages]);

  const handleSessionEvent = useCallback((event: SessionStreamEvent) => {
    if (event?.kind === "stream_ready") {
      return;
    }
    if (event?.kind === "send_failed") {
      setError(event.error ?? "消息发送失败");
      setReplyWatchState("expired");
      return;
    }
    if (event?.kind === "error") {
      if (messagesRef.current.length === 0) setLoading(false);
      if (event.semanticKind === "message.user.send_failed" || messagesRef.current.length === 0) {
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
    setLoading(false);
    setError(event.error ?? null);
    if (shouldClearReplyWatch(previousMessages, nextMessages, event)) {
      cancelReplyWatch();
    }
  }, [applyMessages, cancelReplyWatch]);

  useProviderSessionEventStream({
    enabled: active && mode !== "new-session" && Boolean(activeSession.id),
    providerId: activeSession.type,
    sessionId: activeSession.id,
    workspaceDir: activeSession.workspace ?? null,
    reloadKey: streamReloadKey,
    onEvent: handleSessionEvent,
  });

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
    const scopeGeneration = scopeGenerationRef.current;
    const isCurrentScope = () => scopeGenerationRef.current === scopeGeneration;

    setSending(true);
    setError(null);
    applyMessages(optimisticMessages, "smooth");
    setReplyWatchState("foreground");
    if (mode === "new-session") {
      const payload = JSON.stringify([sessionIdentityKey(activeSession), trimmedText, nextAttachments]);
      if (newSessionRequestRef.current?.payload !== payload) {
        newSessionRequestRef.current = { payload, id: crypto.randomUUID() };
      }
    }

    try {
      const sendResult = mode === "new-session"
        ? await startProviderSessionMessage(
            activeSession.type,
            activeSession.workspace,
            trimmedText,
            nextAttachments,
            newSessionRequestRef.current?.id,
          )
        : await sendProviderSessionMessage(
            activeSession.type,
            activeSession.id,
            trimmedText,
            nextAttachments,
            activeSession.workspace,
      );
      if (!isCurrentScope()) return;
      if (sendResult.error) setError(sendResult.error);
      if (sendResult.accepted === false) {
        cancelReplyWatch();
        applyMessages(previousMessages, "auto");
        return false;
      }
      const remappedSessionId = sendResult.threadId?.trim();
      if (mode === "new-session" && !remappedSessionId) {
        if (sendResult.pending) {
          await onNewSessionPending?.(sendResult, trimmedText);
          if (!isCurrentScope()) return;
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
        if (!isCurrentScope()) return;
      }
      setAttachments([]);
      if (mode === "new-session") {
        setReplyWatchState("background");
        return true;
      }

      setReplyWatchState((current) => current === "foreground" ? "background" : current);
      return true;
    } catch (sendError) {
      if (!isCurrentScope()) return;
      cancelReplyWatch();
      setError((sendError as Error).message);
      applyMessages(previousMessages, "auto");
      return false;
    } finally {
      if (isCurrentScope()) setSending(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-[var(--ow-line-soft)] bg-[var(--ow-panel)] [box-shadow:var(--ow-shadow-md)] backdrop-blur-xl">
      <SessionChatHeader
        title={activeSession.title}
        shortId={activeSession.id.slice(0, 12)}
        loading={loading}
        reloadTitle={t.sessions.reloadMessages}
        badge={(
          <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--ow-text)]">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--ow-muted)]"></span>
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
