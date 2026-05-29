import { createPortal } from "react-dom";
import { archiveProviderSession } from "./api";
import type { UnifiedSession } from "./presentation";

export type SessionActionMenuState = {
  session: UnifiedSession;
  x: number;
  y: number;
};

export type ArchiveNotice = {
  tone: "success" | "error";
  text: string;
};

export function SessionActionMenu({
  menu,
  archivingSessionId,
  labels,
  onArchive,
}: {
  menu: SessionActionMenuState;
  archivingSessionId: string | null;
  labels: {
    archiveSession: string;
    archivingSession: string;
    alreadyArchived: string;
  };
  onArchive: (session: UnifiedSession) => void;
}) {
  const menuItemLabel = archivingSessionId === menu.session.id
    ? labels.archivingSession
    : menu.session.archived
      ? labels.alreadyArchived
      : labels.archiveSession;

  return createPortal(
    <div
      role="menu"
      className="fixed z-[1000] min-w-[176px] overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-[0_18px_48px_rgba(15,23,42,0.22)]"
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
    >
      <button
        role="menuitem"
        disabled={menu.session.archived || archivingSessionId !== null}
        onClick={() => onArchive(menu.session)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold text-slate-800 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-400 disabled:hover:bg-transparent"
      >
        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M5 8h14M7 8v10a2 2 0 002 2h6a2 2 0 002-2V8M9 4h6l1 4H8l1-4z"></path>
        </svg>
        <span>{menuItemLabel}</span>
      </button>
    </div>,
    document.body,
  );
}

export function ArchiveNoticeBanner({ notice }: { notice: ArchiveNotice | null }) {
  if (!notice) {
    return null;
  }

  return (
    <div className="border-b border-[var(--ow-line-soft)] px-3 py-2">
      <div className={`rounded-2xl border px-3 py-2 text-xs font-medium leading-5 ${
        notice.tone === "error"
          ? "border-rose-200/80 bg-rose-50/92 text-rose-700"
          : "border-emerald-200/80 bg-emerald-50/92 text-emerald-700"
      }`}>
        {notice.text}
      </div>
    </div>
  );
}

export async function archiveSessionWithFeedback({
  session,
  selectedSessionId,
  refreshCurrentProvider,
  onArchivedSelection,
  successText,
  failureText,
}: {
  session: UnifiedSession;
  selectedSessionId: string | null;
  refreshCurrentProvider: () => Promise<void>;
  onArchivedSelection: () => void;
  successText: string;
  failureText: (error: string) => string;
}): Promise<ArchiveNotice> {
  try {
    await archiveProviderSession(session.type, session.id, session.workspace, session.title);
    if (selectedSessionId === session.id) {
      onArchivedSelection();
    }
    await refreshCurrentProvider();
    return {
      tone: "success",
      text: successText,
    };
  } catch (error) {
    return {
      tone: "error",
      text: failureText((error as Error).message),
    };
  }
}
