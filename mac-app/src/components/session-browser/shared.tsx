import { useEffect, useState } from "react";
import type { SessionTurn } from "../../types";
import {
  limitSessionTurns,
  mergeSessionTurns,
  SESSION_BROWSER_VISIBLE_TURNS,
} from "../../utils/sessionTurnMerge.js";
import { SessionMarkdown } from "./SessionMarkdown";

export { limitSessionTurns, mergeSessionTurns, SESSION_BROWSER_VISIBLE_TURNS };

function AssistantAvatar({ label }: { label: string }) {
  return (
    <div className="grid h-9 w-9 shrink-0 place-items-center rounded-2xl bg-gradient-to-br from-blue-600 via-blue-500 to-sky-500 text-white shadow-[0_12px_28px_rgba(37,99,235,0.24)]">
      <span className="text-[11px] font-extrabold uppercase tracking-[0.08em]">
        {label.slice(0, 2)}
      </span>
    </div>
  );
}

export function TurnBubble({
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
  disabled,
  placeholder,
  sendLabel,
  assistantLabel,
  onSend,
}: {
  resetKey: string;
  sending: boolean;
  disabled?: boolean;
  placeholder: string;
  sendLabel: string;
  assistantLabel?: string;
  onSend: (text: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setDraft("");
  }, [resetKey]);

  const handleSubmit = async () => {
    const text = draft.trim();
    if (!text || sending || disabled) {
      return;
    }

    setDraft("");
    try {
      await onSend(text);
    } catch (error) {
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

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-3 py-2.5">
            <div className="flex items-center gap-1.5">
              <button className="rounded-xl p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700" title="Attach File">
                <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"></path></svg>
              </button>
              <button className="rounded-xl p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700" title="Screenshot Selection">
                <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
              </button>
              {assistantLabel && (
                <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-blue-700">
                  {assistantLabel}
                </span>
              )}
            </div>

            <button
              onClick={() => void handleSubmit()}
              disabled={sending || disabled || !draft.trim()}
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
