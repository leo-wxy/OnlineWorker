import { useCallback, useEffect, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import { useCodexThreadStream } from "../../hooks/useCodexThreadStream";
import { applyCodexStreamEvent } from "../../utils/codexSessionStream.js";
import { shouldClearReplyWatch } from "../../utils/replyWatch.js";
import {
  buildSnapshotSignature,
  countAssistantEntries,
  pollAssistantReply,
} from "../../utils/sessionPolling.js";
import type {
  CodexSession,
  CodexThreadCursor,
  CodexThreadStreamEvent,
  ComposerAttachment,
  SessionTurn,
} from "../../types";
import {
  fetchCodexSessions,
  fetchCodexThreadState,
  fetchCodexThreadUpdates,
  fetchProviderSession,
  sendCodexMessage,
} from "./api";
import { CodexSessionBadges } from "./badges";
import { useStagedAttachments } from "./composerAttachments";
import { PROVIDER_UI, type UnifiedSession } from "./presentation";
import {
  CODEX_BACKGROUND_REPLY_POLL,
  CODEX_FOREGROUND_REPLY_POLL,
  limitSessionTurns,
  mergeSessionTurns,
  SessionChatHeader,
  SessionComposer,
  SessionMessages,
  type ReplyWatchState,
} from "./shared";

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function CodexChat({ session }: { session: UnifiedSession }) {
  const { t } = useI18n();
  const rawSession = session.raw as CodexSession;
  const providerSupportsAttachments = true;
  const [activeSession, setActiveSession] = useState<CodexSession>(rawSession);

  const [turns, setTurns] = useState<SessionTurn[]>([]);
  const [turnsLoading, setTurnsLoading] = useState(false);
  const [turnsError, setTurnsError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [attachments, setAttachments] = useState<ComposerAttachment[]>([]);
  const { stagingAttachments, handlePickFiles } = useStagedAttachments({
    supportsAttachments: providerSupportsAttachments,
    unsupportedMessage: t.sessions.attachmentUnsupported,
    setError: setTurnsError,
    setAttachments,
  });
  const [replyWatchState, setReplyWatchState] = useState<ReplyWatchState | null>(null);
  const turnsEndRef = useRef<HTMLDivElement>(null);
  const replyWatchTokenRef = useRef(0);
  const turnsRef = useRef<SessionTurn[]>([]);
  const codexCursorRef = useRef<CodexThreadCursor | null>(null);
  const [codexStreamCursor, setCodexStreamCursor] = useState<CodexThreadCursor | null>(null);

  const resolveCodexSessionByThreadId = useCallback(async (threadId: string) => {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      const sessions = await fetchCodexSessions();
      const matched = sessions.find((item) => item.threadId === threadId);
      if (matched?.rolloutPath) {
        return matched;
      }
      await sleepMs(100);
    }
    throw new Error(`Failed to resolve remapped Codex session: ${threadId}`);
  }, []);

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
      const [history, snapshot] = await Promise.all([
        fetchProviderSession("codex", activeSession.threadId, activeSession.cwd),
        fetchCodexThreadState(activeSession.rolloutPath ?? ""),
      ]);
      codexCursorRef.current = snapshot.cursor;
      turnsRef.current = history;
      setTurns(history);
      setCodexStreamCursor(snapshot.cursor);
      setReplyWatchState((current) => (current === "expired" ? null : current));
    } catch (loadError) {
      setTurnsError((loadError as Error).message);
    } finally {
      setTurnsLoading(false);
    }
  }, [activeSession.rolloutPath]);

  useEffect(() => {
    setActiveSession(rawSession);
  }, [
    session.id,
    rawSession.rolloutPath,
    rawSession.threadId,
    rawSession.cwd,
    rawSession.title,
    rawSession.archived,
    rawSession.modelProvider,
    rawSession.source,
    rawSession.isSmoke,
  ]);

  useEffect(() => {
    cancelReplyWatch();
    setAttachments([]);
    void loadTurns();
    return () => {
      replyWatchTokenRef.current += 1;
    };
  }, [session.id, activeSession.rolloutPath, loadTurns, cancelReplyWatch]);

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
    enabled: Boolean(activeSession.rolloutPath && codexStreamCursor),
    rolloutPath: activeSession.rolloutPath ?? null,
    cursor: codexStreamCursor,
    onEvent: handleCodexStreamEvent,
  });

  const handleSend = async (text: string, nextAttachments: ComposerAttachment[]) => {
    if (!activeSession.rolloutPath || (!text.trim() && nextAttachments.length === 0) || sending) {
      return;
    }

    const trimmedText = text.trim();
    let rolloutPath = activeSession.rolloutPath;
    const threadId = activeSession.threadId;
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
      const sendResult = await sendCodexMessage(threadId, trimmedText, nextAttachments, activeSession.cwd);
      let effectiveThreadId = threadId;
      let effectiveWorkspaceCwd = activeSession.cwd;
      if (sendResult.threadId && sendResult.threadId !== threadId) {
        const remappedSession = await resolveCodexSessionByThreadId(sendResult.threadId);
        setActiveSession(remappedSession);
        rolloutPath = remappedSession.rolloutPath ?? "";
        effectiveThreadId = remappedSession.threadId;
        effectiveWorkspaceCwd = remappedSession.cwd;
      } else if (sendResult.threadId) {
        effectiveThreadId = sendResult.threadId;
      }
      setAttachments([]);

      const shouldContinue = () => replyWatchTokenRef.current === replyWatchToken;
      const loadSnapshot = async () => {
        const currentCursor = codexCursorRef.current;
        const cursorResult = currentCursor
          ? await fetchCodexThreadUpdates(rolloutPath, currentCursor)
          : await fetchCodexThreadState(rolloutPath);
        if (shouldContinue()) {
          codexCursorRef.current = cursorResult.cursor;
        }
        const nextTurns = await fetchProviderSession("codex", effectiveThreadId, effectiveWorkspaceCwd);
        const mergedTurns = mergeSessionTurns(previousTurns, nextTurns);
        if (shouldContinue()) {
          turnsRef.current = mergedTurns;
        }
        return mergedTurns;
      };
      const applySnapshot = (snapshot: SessionTurn[]) => {
        const nextTurns = mergeSessionTurns(previousTurns, snapshot);
        if (shouldContinue()) {
          turnsRef.current = nextTurns;
          setTurns(nextTurns);
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

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white/58 shadow-[0_18px_40px_rgba(15,23,42,0.06)] backdrop-blur-xl">
      <SessionChatHeader
        title={activeSession.title || session.title}
        shortId={activeSession.threadId.slice(0, 12)}
        loading={turnsLoading}
        reloadTitle={t.sessions.reloadMessages}
        badge={(
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] ${PROVIDER_UI.codex.chip}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${PROVIDER_UI.codex.dot}`}></span>
            Codex
          </span>
        )}
        onReload={() => void loadTurns()}
      >
        <CodexSessionBadges session={activeSession} />
      </SessionChatHeader>

      <SessionMessages
        loading={turnsLoading}
        error={turnsError}
        messages={turns}
        assistantLabel="Codex"
        labels={{
          loading: t.common.loading,
          noMessages: t.sessions.noMessages,
          waitingForReply: t.sessions.waitingForReply,
          waitingInBackground: t.sessions.waitingInBackground,
          waitingExpired: t.sessions.waitingExpired,
        }}
        endRef={turnsEndRef}
        replyWatchState={replyWatchState}
      />

      <SessionComposer
        resetKey={session.id}
        sending={sending}
        stagingAttachments={stagingAttachments}
        disabled={!activeSession.rolloutPath}
        placeholder={t.sessions.sendPlaceholder}
        sendLabel={t.sessions.send}
        assistantLabel="Codex"
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
