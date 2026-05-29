import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import type { ComposerAttachment, SessionTurn } from "../../types";
import {
  buildSnapshotSignature,
  countAssistantEntries,
  pollAssistantReply,
} from "../../utils/sessionPolling.js";
import {
  fetchProviderSession,
  sendProviderSessionMessage,
} from "./api";
import { useStagedAttachments } from "./composerAttachments";
import { getProviderUi, type UnifiedSession } from "./presentation";
import {
  BACKGROUND_REPLY_POLL,
  FOREGROUND_REPLY_POLL,
  limitSessionTurns,
  SessionChatHeader,
  SessionComposer,
  SessionMessages,
  type ReplyWatchState,
} from "./shared";

export function GenericProviderChat({
  session,
  providerSupportsAttachments,
}: {
  session: UnifiedSession;
  providerSupportsAttachments: boolean;
}) {
  const { t } = useI18n();
  const providerLabel = getProviderUi(session.type).label;
  const [messages, setMessages] = useState<SessionTurn[]>([]);
  const [loading, setLoading] = useState(false);
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

  const cancelReplyWatch = useCallback(() => {
    replyWatchTokenRef.current += 1;
    setReplyWatchState(null);
  }, []);

  const loadMessages = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMessages([]);
    messagesRef.current = [];
    try {
      const turns = await fetchProviderSession(session.type, session.id, session.workspace);
      messagesRef.current = turns;
      setMessages(turns);
      setReplyWatchState((current) => (current === "expired" ? null : current));
    } catch (loadError) {
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
    }
  }, [session.id, session.type, session.workspace]);

  useEffect(() => {
    cancelReplyWatch();
    setAttachments([]);
    void loadMessages();
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [loadMessages, cancelReplyWatch]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

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
    messagesRef.current = optimisticMessages;
    setMessages(optimisticMessages);
    setReplyWatchState("foreground");

    const baselineAssistantCount = countAssistantEntries(previousMessages);

    try {
      await sendProviderSessionMessage(session.type, session.id, trimmedText, nextAttachments, session.workspace);
      setAttachments([]);

      const loadSnapshot = async () => {
        const snapshot = await fetchProviderSession(session.type, session.id, session.workspace);
        if (shouldContinue()) {
          messagesRef.current = snapshot;
        }
        return snapshot;
      };
      const applySnapshot = (snapshot: SessionTurn[]) => {
        if (shouldContinue()) {
          messagesRef.current = snapshot;
          setMessages(snapshot);
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
          loadSnapshot,
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
      setError((sendError as Error).message);
      messagesRef.current = previousMessages;
      setMessages(previousMessages);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <SessionChatHeader
        title={session.title}
        shortId={session.id.slice(0, 12)}
        loading={loading}
        reloadTitle={t.sessions.reloadMessages}
        badge={(
          <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-700">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-500"></span>
            {providerLabel}
          </span>
        )}
        onReload={() => void loadMessages()}
      />

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
        resetKey={session.id}
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
