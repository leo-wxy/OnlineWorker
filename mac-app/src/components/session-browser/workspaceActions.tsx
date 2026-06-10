import type { ReactNode } from "react";
import { createPortal } from "react-dom";

export type WorkspaceActionMenuState = {
  workspace: string;
  x: number;
  y: number;
};

export function WorkspaceActionMenu({
  menu,
  labels,
  onOpenTerminal,
  onOpenFinder,
  onCopyPath,
}: {
  menu: WorkspaceActionMenuState;
  labels: {
    openInTerminal: string;
    openInFinder: string;
    copyPath: string;
  };
  onOpenTerminal: (workspace: string) => void;
  onOpenFinder: (workspace: string) => void;
  onCopyPath: (workspace: string) => void;
}) {
  return createPortal(
    <div
      role="menu"
      className="fixed z-[1000] min-w-[188px] overflow-hidden rounded-xl border border-slate-200 bg-white p-1 shadow-[0_18px_48px_rgba(15,23,42,0.22)]"
      style={{ left: menu.x, top: menu.y }}
      onClick={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
    >
      <WorkspaceActionMenuButton onClick={() => onOpenTerminal(menu.workspace)}>
        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M5 6.5h14A1.5 1.5 0 0120.5 8v8a1.5 1.5 0 01-1.5 1.5H5A1.5 1.5 0 013.5 16V8A1.5 1.5 0 015 6.5zM7.5 10l2 2-2 2M11.5 14h4.5" />
        </svg>
        <span>{labels.openInTerminal}</span>
      </WorkspaceActionMenuButton>
      <WorkspaceActionMenuButton onClick={() => onOpenFinder(menu.workspace)}>
        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M3 7.5A2.5 2.5 0 015.5 5h4.8l2 2H18.5A2.5 2.5 0 0121 9.5v7A2.5 2.5 0 0118.5 19h-13A2.5 2.5 0 013 16.5v-9z" />
        </svg>
        <span>{labels.openInFinder}</span>
      </WorkspaceActionMenuButton>
      <WorkspaceActionMenuButton onClick={() => onCopyPath(menu.workspace)}>
        <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M8 8V6.5A2.5 2.5 0 0110.5 4h6A2.5 2.5 0 0119 6.5v6A2.5 2.5 0 0116.5 15H15M5 9h6.5A2.5 2.5 0 0114 11.5v6A2.5 2.5 0 0111.5 20h-6A2.5 2.5 0 013 17.5v-6A2.5 2.5 0 015.5 9z" />
        </svg>
        <span>{labels.copyPath}</span>
      </WorkspaceActionMenuButton>
    </div>,
    document.body,
  );
}

function WorkspaceActionMenuButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      role="menuitem"
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-semibold text-slate-800 transition-colors hover:bg-slate-100"
    >
      {children}
    </button>
  );
}
