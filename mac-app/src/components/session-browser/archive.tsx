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

function archiveErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return "unknown error";
}

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
      className="fixed z-[1000] min-w-[176px] overflow-hidden rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel)] p-1 [box-shadow:var(--ow-shadow-md)]"
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
    >
      <button
        role="menuitem"
        disabled={menu.session.archived || archivingSessionId !== null}
        onClick={() => onArchive(menu.session)}
        className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold text-[var(--ow-text)] transition-colors hover:bg-[var(--ow-panel-soft)] disabled:cursor-not-allowed disabled:text-[var(--ow-subtle)] disabled:hover:bg-transparent"
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
          ? "border-[var(--ow-red)] bg-[var(--ow-red-soft)] text-[var(--ow-error-text)]"
          : "border-[var(--ow-green)] bg-[var(--ow-green-soft)] text-[var(--ow-green)]"
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
      text: failureText(archiveErrorMessage(error)),
    };
  }
}
