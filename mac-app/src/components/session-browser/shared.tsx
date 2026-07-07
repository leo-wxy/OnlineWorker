import { type ReactNode, type RefObject, useEffect, useState } from "react";
import type { ComposerAttachment, SessionTurn } from "../../types";
import { StatePanel } from "./presentation";
import { SessionMarkdown } from "./SessionMarkdown";

function AssistantAvatar({ label }: { label: string }) {
  return (
    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 via-blue-500 to-sky-500 text-white shadow-[0_12px_28px_rgba(37,99,235,0.24)]">
      <span className="text-[11px] font-extrabold uppercase tracking-[0.08em]">
        {label.slice(0, 2)}
      </span>
    </div>
  );
}

function TurnBubble({
  turn,
  assistantLabel,
}: {
  turn: SessionTurn;
  assistantLabel: string;
}) {
  if (!turn.content && !turn.pending) {
    return null;
  }

  const isUser = turn.role === "user";

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[78%]">
          <div className="rounded-[22px] rounded-br-md bg-gradient-to-br from-blue-600 to-blue-500 px-5 py-3.5 text-white shadow-[0_16px_32px_rgba(37,99,235,0.18)]">
            <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">{turn.content}</p>
          </div>
        </div>
      </div>
    );
  }

  if (turn.pending) {
    const pendingText = turn.content?.trim();

    return (
      <div className="flex items-end gap-3">
        <AssistantAvatar label={assistantLabel} />
        <div className="max-w-[82%]">
          <div className="mb-1.5 pl-1">
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-600">
              {assistantLabel}
            </span>
          </div>
          <div className="rounded-[22px] rounded-bl-md border border-slate-200/80 bg-white/92 px-4 py-3 shadow-sm">
            {pendingText ? (
              <p className="text-[15px] leading-relaxed text-gray-800 whitespace-pre-wrap break-words">{pendingText}</p>
            ) : null}
            <div className={`flex items-center gap-1.5 ${pendingText ? "mt-3" : "h-5"}`}>
              <div className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: "0ms" }}></div>
              <div className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: "150ms" }}></div>
              <div className="h-2 w-2 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: "300ms" }}></div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-end gap-3">
      <AssistantAvatar label={assistantLabel} />
      <div className="max-w-[82%]">
        <div className="mb-1.5 pl-1">
          <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-blue-700">
            {assistantLabel}
          </span>
        </div>
        <div className="rounded-[22px] rounded-bl-md border border-slate-200/80 bg-white/94 px-5 py-4 shadow-sm backdrop-blur">
          {turn.displayMode === "markdown" ? (
            <SessionMarkdown content={turn.content} />
          ) : (
            <p className="text-[15px] leading-relaxed text-gray-800 whitespace-pre-wrap break-words">{turn.content}</p>
          )}
        </div>
      </div>
    </div>
  );
}

export function SessionComposer({
  resetKey,
  sending,
  stagingAttachments,
  disabled,
  placeholder,
  sendLabel,
  assistantLabel,
  attachments,
  onAttachmentsChange,
  onPickFiles,
  supportsAttachments = true,
  attachmentButtonLabel,
  imageButtonLabel,
  onSend,
}: {
  resetKey: string;
  sending: boolean;
  stagingAttachments?: boolean;
  disabled?: boolean;
  placeholder: string;
  sendLabel: string;
  assistantLabel?: string;
  attachments: ComposerAttachment[];
  onAttachmentsChange: (attachments: ComposerAttachment[]) => void;
  onPickFiles: (kind: "file" | "image", files: FileList | File[]) => Promise<void>;
  supportsAttachments?: boolean;
  attachmentButtonLabel: string;
  imageButtonLabel: string;
  onSend: (text: string, attachments: ComposerAttachment[]) => Promise<boolean | void>;
}) {
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setDraft("");
  }, [resetKey]);

  const handleSubmit = async () => {
    const text = draft.trim();
    if ((!text && attachments.length === 0) || sending || stagingAttachments || disabled) {
      return;
    }

    setDraft("");
    onAttachmentsChange([]);
    try {
      const accepted = await onSend(text, attachments);
      if (accepted === false) {
        onAttachmentsChange(attachments);
        setDraft((current) => current || text);
      }
    } catch (error) {
      onAttachmentsChange(attachments);
      setDraft((current) => current || text);
      throw error;
    }
  };

  return (
    <div className="border-t border-slate-200/70 bg-white/68 p-4 backdrop-blur">
      <div className="ow-page-frame-soft rounded-[24px] p-3">
        <div className="rounded-[20px] border border-slate-200/80 bg-white/92 shadow-sm transition-all focus-within:border-blue-200 focus-within:shadow-[0_10px_24px_rgba(37,99,235,0.08)]">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSubmit();
              }
            }}
            disabled={sending || disabled}
            className="min-h-[56px] max-h-48 w-full resize-none bg-transparent px-4 py-3.5 text-[15px] text-gray-800 outline-none placeholder:text-slate-400 disabled:opacity-50"
            placeholder={placeholder}
            rows={1}
          ></textarea>

          {attachments.length > 0 ? (
            <div className="flex flex-wrap gap-2 border-t border-slate-100 px-3 py-3">
              {attachments.map((attachment) => (
                <div
                  key={attachment.id}
                  className="inline-flex max-w-full items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
                >
                  <span className="truncate font-medium text-slate-700">{attachment.name}</span>
                  <span className="shrink-0 text-[11px] text-slate-400">
                    {attachment.kind === "image" ? "image" : "file"}
                  </span>
                  <button
                    type="button"
                    className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-700"
                    title={attachment.name}
                    onClick={() =>
                      onAttachmentsChange(attachments.filter((item) => item.id !== attachment.id))
                    }
                    disabled={sending || stagingAttachments || disabled}
                  >
                    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-3 py-2.5">
            <div className="flex items-center gap-1.5">
              {supportsAttachments ? (
                <>
                  <label
                    className={`rounded-xl p-2 text-slate-400 transition-colors ${
                      sending || stagingAttachments || disabled
                        ? "cursor-not-allowed opacity-40"
                        : "cursor-pointer hover:bg-slate-100 hover:text-slate-700"
                    }`}
                    title={attachmentButtonLabel}
                  >
                    <input
                      type="file"
                      multiple
                      className="sr-only"
                      disabled={sending || stagingAttachments || disabled}
                      onChange={(event) => {
                        const files = event.target.files;
                        if (!files || files.length === 0) {
                          return;
                        }
                        void onPickFiles("file", files);
                        event.currentTarget.value = "";
                      }}
                    />
                    <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
                  </label>
                  <label
                    className={`rounded-xl p-2 text-slate-400 transition-colors ${
                      sending || stagingAttachments || disabled
                        ? "cursor-not-allowed opacity-40"
                        : "cursor-pointer hover:bg-slate-100 hover:text-slate-700"
                    }`}
                    title={imageButtonLabel}
                  >
                    <input
                      type="file"
                      multiple
                      accept="image/*"
                      className="sr-only"
                      disabled={sending || stagingAttachments || disabled}
                      onChange={(event) => {
                        const files = event.target.files;
                        if (!files || files.length === 0) {
                          return;
                        }
                        void onPickFiles("image", files);
                        event.currentTarget.value = "";
                      }}
                    />
                    <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                  </label>
                </>
              ) : null}
              {assistantLabel && (
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-blue-700">
                  {assistantLabel}
                </span>
              )}
            </div>

            <button
              onClick={() => void handleSubmit()}
              disabled={sending || stagingAttachments || disabled || (!draft.trim() && attachments.length === 0)}
              className="ow-btn-primary inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-40"
            >
              {sendLabel}
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
            </button>
          </div>
        </div>
      </div>
      <p className="mt-2 text-center text-[10px] text-slate-400">
        Press <kbd className="rounded border border-slate-200 bg-white px-1 py-0.5 font-mono">Enter</kbd> to send, <kbd className="rounded border border-slate-200 bg-white px-1 py-0.5 font-mono">Shift+Enter</kbd> for new line
      </p>
    </div>
  );
}

export const CODEX_FOREGROUND_REPLY_POLL = {
  intervalMs: 500,
  maxAttempts: 120,
  stablePollsRequired: 2,
};

export const CODEX_BACKGROUND_REPLY_POLL = {
  intervalMs: 1500,
  maxAttempts: 1200,
  stablePollsRequired: 2,
};

export const FOREGROUND_REPLY_POLL = {
  intervalMs: 1000,
  maxAttempts: 60,
  stablePollsRequired: 2,
};

export const BACKGROUND_REPLY_POLL = {
  intervalMs: 3000,
  maxAttempts: 600,
  stablePollsRequired: 2,
};

export type ReplyWatchState = "foreground" | "background" | "expired";

export type ReplyWatchLabels = {
  waitingForReply: string;
  waitingInBackground: string;
  waitingExpired: string;
};

export type SessionMessagesLabels = ReplyWatchLabels & {
  loading: string;
  noMessages: string;
};

function getReplyWatchText(
  replyWatchState: ReplyWatchState | null,
  labels: ReplyWatchLabels,
) {
  if (replyWatchState === "foreground") {
    return labels.waitingForReply;
  }
  if (replyWatchState === "background") {
    return labels.waitingInBackground;
  }
  if (replyWatchState === "expired") {
    return labels.waitingExpired;
  }
  return null;
}

export function SessionChatHeader({
  title,
  shortId,
  loading,
  reloadTitle,
  badge,
  children,
  onReload,
}: {
  title: string;
  shortId: string;
  loading: boolean;
  reloadTitle: string;
  badge: ReactNode;
  children?: ReactNode;
  onReload: () => void;
}) {
  return (
    <div className="border-b border-[var(--ow-line-soft)] bg-white/74 px-5 py-4 backdrop-blur-xl">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            {badge}
            <span className="rounded-full border border-slate-200 bg-white/88 px-2.5 py-1 font-mono text-[10px] text-slate-500">
              {shortId}
            </span>
          </div>
          <h3 className="truncate text-base font-bold tracking-[-0.02em] text-gray-950">{title}</h3>
          {children}
        </div>

        <button
          onClick={onReload}
          disabled={loading}
          className="ow-btn inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold text-slate-600 transition-colors hover:text-gray-900 disabled:opacity-50"
          title={reloadTitle}
        >
          <svg className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
          </svg>
          Reload
        </button>
      </div>
    </div>
  );
}

export function SessionMessages({
  loading,
  error,
  messages,
  assistantLabel,
  labels,
  endRef,
  replyWatchState,
  minHeight = true,
}: {
  loading: boolean;
  error: string | null;
  messages: SessionTurn[];
  assistantLabel: string;
  labels: SessionMessagesLabels;
  endRef: RefObject<HTMLDivElement>;
  replyWatchState: ReplyWatchState | null;
  minHeight?: boolean;
}) {
  const replyWatchText = getReplyWatchText(replyWatchState, labels);
  const showLoadingPanel = loading && messages.length === 0;
  const showErrorPanel = Boolean(error) && messages.length === 0;
  const showEmptyPanel = !loading && !error && messages.length === 0;

  return (
    <div className={`chat-bg ${minHeight ? "min-h-0 " : ""}flex-1 overflow-y-auto px-5 py-5`}>
      <div className="mx-auto flex max-w-4xl flex-col gap-6">
        {showLoadingPanel ? (
          <StatePanel message={labels.loading} />
        ) : showErrorPanel ? (
          <StatePanel message={error ?? labels.noMessages} tone="error" />
        ) : showEmptyPanel ? (
          <StatePanel message={labels.noMessages} />
        ) : (
          <>
            {error ? (
              <p className="px-3 text-center text-xs text-amber-600">{error}</p>
            ) : null}
            {messages.map((turn, index) => (
              <TurnBubble
                key={`${turn.role}-${index}-${turn.content}`}
                turn={turn}
                assistantLabel={assistantLabel}
              />
            ))}
          </>
        )}
        {replyWatchText && (
          <p className={`px-3 pb-1 text-center text-xs ${replyWatchState === "expired" ? "text-amber-600" : "text-slate-400"}`}>
            {replyWatchText}
          </p>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
