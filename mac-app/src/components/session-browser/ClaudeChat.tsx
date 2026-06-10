import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { useProviderSessionEventStream } from "../../hooks/useProviderSessionEventStream";
import type {
  ClaudeSession,
  ComposerAttachment,
  SessionStreamEvent,
  SessionTurn,
} from "../../types";
import { shouldClearReplyWatch } from "../../utils/replyWatch.js";
import { applySessionStreamEvent } from "../../utils/sessionEventModel.js";
import {
  buildSnapshotSignature,
  countAssistantEntries,
  pollAssistantReply,
} from "../../utils/sessionPolling.js";
import {
  fetchClaudeMessages,
  sendClaudeMessage,
} from "./api";
import { useStagedAttachments } from "./composerAttachments";
import { PROVIDER_UI, type UnifiedSession } from "./presentation";
import {
  BACKGROUND_REPLY_POLL,
  FOREGROUND_REPLY_POLL,
  limitSessionTurns,
  mergeSessionTurns,
  SessionChatHeader,
  SessionComposer,
  SessionMessages,
  type ReplyWatchState,
} from "./shared";

export function ClaudeChat({
  session,
  refreshSessions,
}: {
  session: UnifiedSession;
  refreshSessions: () => Promise<void>;
}) {
  const { t } = useI18n();
  const rawSession = session.raw as ClaudeSession;

  const [messages, setMessages] = useState<SessionTurn[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgError, setMsgError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const providerSupportsAttachments = true;
  const { stagingAttachments, handlePickFiles } = useStagedAttachments({
    supportsAttachments: providerSupportsAttachments,
    unsupportedMessage: t.sessions.attachmentUnsupported,
    setError: setMsgError,
    setAttachments,
  });
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
    setAttachments([]);
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

  const handleSessionEvent = useCallback((event: SessionStreamEvent) => {
    if (event?.kind === "stream_ready") {
      return;
    }
    if (event?.kind === "error") {
      if (messagesRef.current.length === 0) {
        setMsgError(event.error ?? "provider session stream error");
      } else {
        console.warn("Claude session event stream error", event.error);
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
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    if (shouldClearReplyWatch(previousMessages, nextMessages, event)) {
      cancelReplyWatch();
    }
  }, [cancelReplyWatch]);

  useProviderSessionEventStream({
    enabled: Boolean(rawSession.sessionId),
    providerId: "claude",
    sessionId: rawSession.sessionId,
    workspaceDir: rawSession.workspace ?? null,
    onEvent: handleSessionEvent,
  });

  const handleSend = async (text: string, nextAttachments: ComposerAttachment[]) => {
    if ((!text.trim() && nextAttachments.length === 0) || sending) {
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
        nextAttachments,
        rawSession.workspace,
      );
      setAttachments([]);
      const activeSessionId = sendResult.sessionId || originalSessionId;
      const bridgePrefix = activeSessionId === originalSessionId ? [] : previousMessages;

      if (activeSessionId !== originalSessionId) {
        // Refresh the parent list so a newly created Claude session can become selectable.
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

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <SessionChatHeader
        title={session.title}
        shortId={session.id.slice(0, 12)}
        loading={msgLoading}
        reloadTitle={t.sessions.reloadMessages}
        badge={(
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${PROVIDER_UI.claude.chip}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${PROVIDER_UI.claude.dot}`}></span>
            Claude
          </span>
        )}
        onReload={() => void loadMessages()}
      />

      <SessionMessages
        loading={msgLoading}
        error={msgError}
        messages={messages}
        assistantLabel="Claude"
        labels={{
          loading: t.common.loading,
          noMessages: t.sessions.noMessages,
          waitingForReply: t.sessions.waitingForReply,
          waitingInBackground: t.sessions.waitingInBackground,
          waitingExpired: t.sessions.waitingExpired,
        }}
        endRef={msgEndRef}
        replyWatchState={replyWatchState}
      />

      <SessionComposer
        resetKey={session.id}
        sending={sending}
        stagingAttachments={stagingAttachments}
        placeholder={t.sessions.sendPlaceholder}
        sendLabel={t.sessions.send}
        assistantLabel="Claude"
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
