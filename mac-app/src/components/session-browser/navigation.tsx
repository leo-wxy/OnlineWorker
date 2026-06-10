import type { MouseEvent, ReactNode } from "react";
import type { ArchiveNotice } from "./archive";
import { ArchiveNoticeBanner } from "./archive";
import {
  StatePanel,
  getProviderUi,
  type ArchiveFilter,
  type ProviderFilter,
  type UnifiedSession,
} from "./presentation";
import type { ProviderMetadata } from "../../types";

export function SessionProviderToolbar({
  providers,
  providerFilter,
  loading,
  onProviderChange,
  onRefresh,
}: {
  providers: ProviderMetadata[];
  providerFilter: ProviderFilter;
  loading: boolean;
  onProviderChange: (provider: ProviderFilter) => void;
  onRefresh: () => void;
}) {
  return (
    <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
      <div className="ow-toolbar flex items-center justify-between gap-3 rounded-[22px] px-3 py-2.5">
        <div className="ow-segment inline-flex rounded-2xl p-1">
          {providers.map((provider) => {
            const p = provider.id;
            const ui = getProviderUi(p, provider.label);
            return (
              <button
                key={p}
                onClick={() => onProviderChange(p)}
                className={`inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition-all ${
                  providerFilter === p
                    ? `${ui.tabActive}`
                    : "text-slate-500 hover:text-gray-800"
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${ui.dot}`}></span>
                {ui.label}
              </button>
            );
          })}
        </div>

        <button
          onClick={onRefresh}
          className="ow-btn inline-flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold text-slate-600 transition-colors hover:text-gray-900"
        >
          <svg className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
          </svg>
          Refresh
        </button>
      </div>
    </div>
  );
}

export function WorkspaceSidebar({
  workspaces,
  sessions,
  providerFilter,
  providerLabels,
  selectedWorkspace,
  noSessionsLabel,
  onSelectWorkspace,
  onOpenWorkspaceContextMenu,
}: {
  workspaces: string[];
  sessions: UnifiedSession[];
  providerFilter: ProviderFilter;
  providerLabels: Record<string, string>;
  selectedWorkspace: string | null;
  noSessionsLabel: string;
  onSelectWorkspace: (workspace: string | null) => void;
  onOpenWorkspaceContextMenu?: (event: MouseEvent<HTMLElement>, workspace: string) => void;
}) {
  return (
    <div className="ow-page-frame-soft flex w-[268px] shrink-0 flex-col overflow-hidden rounded-[26px]">
      <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Workspaces</p>
            <p className="mt-1 text-xs text-slate-400">Filter by project path</p>
          </div>
          <span className="rounded-full border border-white/80 bg-white/85 px-2.5 py-1 text-[11px] font-semibold text-slate-500 shadow-sm">
            {workspaces.length}
          </span>
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {workspaces.length === 0 ? (
          <StatePanel message={noSessionsLabel} />
        ) : workspaces.map((ws) => {
          const name = ws.split("/").pop() || ws;
          const count = sessions.filter((session) => session.workspace === ws).length;
          const isActive = selectedWorkspace === ws;
          const providerUi = getProviderUi(providerFilter, providerLabels[providerFilter]);
          const activeClasses = isActive
            ? providerUi.workspaceActive
            : "border-transparent bg-white/50 hover:border-[var(--ow-line)] hover:bg-white/88";

          return (
            <button
              key={ws}
              onClick={() => onSelectWorkspace(isActive ? null : ws)}
              onContextMenu={(event) => onOpenWorkspaceContextMenu?.(event, ws)}
              className={`group flex w-full items-center gap-3 rounded-[20px] border px-3 py-3 text-left transition-all ${activeClasses}`}
            >
              <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-2xl ${
                isActive
                  ? providerUi.iconActive
                  : "bg-white/88 text-slate-400 group-hover:text-slate-600"
              }`}>
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"></path>
                </svg>
              </span>
              <span className="min-w-0 flex-1">
                <span className={`block truncate text-sm ${isActive ? "font-semibold text-gray-950" : "font-medium text-gray-700"}`}>{name}</span>
                <span className="mt-1 block truncate text-[11px] text-slate-400">{ws}</span>
              </span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                isActive
                  ? "border border-white/80 bg-white/92 text-slate-700 shadow-sm"
                  : "bg-slate-100/90 text-slate-500"
              }`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function SessionListPanel({
  sessions,
  providerFilter,
  providerLabels,
  selectedSessionId,
  archiveFilter,
  archivingSessionId,
  archiveNotice,
  labels,
  pinnedSessionIds,
  renderSessionMeta,
  onArchiveFilterChange,
  onSelectSession,
  onTogglePinSession,
  onOpenContextMenu,
  onOpenActionMenu,
}: {
  sessions: UnifiedSession[];
  providerFilter: ProviderFilter;
  providerLabels: Record<string, string>;
  selectedSessionId: string | null;
  archiveFilter: ArchiveFilter;
  archivingSessionId: string | null;
  archiveNotice: ArchiveNotice | null;
  labels: {
    active: string;
    archived: string;
    archivingSession: string;
    noSessions: string;
    pinSession: string;
    unpinSession: string;
    sessionActions: string;
  };
  pinnedSessionIds?: Set<string>;
  renderSessionMeta?: (session: UnifiedSession) => ReactNode;
  onArchiveFilterChange: (filter: ArchiveFilter) => void;
  onSelectSession: (sessionId: string) => void;
  onTogglePinSession?: (session: UnifiedSession) => void;
  onOpenContextMenu: (event: MouseEvent<HTMLElement>, session: UnifiedSession) => void;
  onOpenActionMenu: (event: MouseEvent<HTMLElement>, session: UnifiedSession) => void;
}) {
  const providerUi = getProviderUi(providerFilter, providerLabels[providerFilter]);

  return (
    <div className="ow-page-frame-soft flex w-[328px] shrink-0 flex-col overflow-hidden rounded-[26px]">
      <div className="border-b border-[var(--ow-line-soft)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Sessions</p>
            <p className="mt-1 text-xs text-slate-400">Keep the reading path unchanged</p>
          </div>
          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${providerUi.chip}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${providerUi.dot}`}></span>
            {providerUi.label}
          </span>
        </div>

        <div className="ow-segment mt-3 grid grid-cols-2 rounded-2xl p-1">
          <button
            onClick={() => onArchiveFilterChange("active")}
            className={`rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
              archiveFilter === "active"
                ? "ow-segment-button-active"
                : "ow-segment-button hover:text-gray-700"
            }`}
          >
            {labels.active}
          </button>
          <button
            onClick={() => onArchiveFilterChange("archived")}
            className={`rounded-xl px-3 py-2 text-xs font-semibold transition-all ${
              archiveFilter === "archived"
                ? "ow-segment-button-active"
                : "ow-segment-button hover:text-gray-700"
            }`}
          >
            {labels.archived}
          </button>
        </div>
      </div>

      <ArchiveNoticeBanner notice={archiveNotice} />

      <div className="relative flex-1 space-y-2 overflow-y-auto px-3 py-3">
        {sessions.length === 0 ? (
          <StatePanel message={labels.noSessions} />
        ) : sessions.map((session) => {
          const isActive = selectedSessionId === session.id;
          const ui = getProviderUi(session.type, providerLabels[session.type]);
          const isArchiving = archivingSessionId === session.id;
          const isPinned = Boolean(pinnedSessionIds?.has(`${session.type}:${session.id}`));

          return (
            <div
              key={session.id}
              role="button"
              tabIndex={isArchiving ? -1 : 0}
              aria-disabled={isArchiving}
              onClick={() => onSelectSession(session.id)}
              onKeyDown={(event) => {
                if (isArchiving) {
                  return;
                }
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelectSession(session.id);
                }
              }}
              onContextMenu={(event) => onOpenContextMenu(event, session)}
              className={`relative flex w-full cursor-pointer flex-col rounded-[22px] border px-4 py-4 text-left transition-all focus:outline-none focus:ring-2 focus:ring-blue-300/70 ${
                isArchiving
                  ? "cursor-progress opacity-70"
                  : ""
              } ${
                isActive
                  ? `${ui.sessionActive} shadow-[0_12px_28px_rgba(15,23,42,0.08)]`
                  : "border-transparent bg-white/72 hover:border-[var(--ow-line)] hover:bg-white"
              }`}
            >
              {isActive && (
                <span className={`absolute left-0 top-4 bottom-4 w-1 rounded-r-full ${ui.dot}`}></span>
              )}
              <div className="mb-2 flex items-center justify-between gap-2 pl-1">
                <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${ui.chip}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${ui.dot}`}></span>
                  {ui.label}
                </span>
                <div className="flex items-center gap-2">
                  {isArchiving ? (
                    <span className="rounded-full bg-white/88 px-2 py-1 text-[10px] font-semibold text-slate-500">
                      {labels.archivingSession}
                    </span>
                  ) : null}
                  {onTogglePinSession ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        onTogglePinSession(session);
                      }}
                      disabled={isArchiving}
                      aria-pressed={isPinned}
                      aria-label={isPinned ? labels.unpinSession : labels.pinSession}
                      title={isPinned ? labels.unpinSession : labels.pinSession}
                      className={`grid h-7 w-7 shrink-0 place-items-center rounded-full border transition-colors disabled:cursor-progress disabled:opacity-50 ${
                        isPinned
                          ? "border-violet-200 bg-violet-50 text-violet-600"
                          : "border-transparent text-slate-400 hover:border-slate-200 hover:bg-white hover:text-slate-700"
                      }`}
                    >
                      <svg className={`h-4 w-4 ${isPinned ? "fill-current" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.9" d="M11.05 3.6a1 1 0 011.9 0l1.7 5.24h5.5a1 1 0 01.59 1.81l-4.45 3.23 1.7 5.24a1 1 0 01-1.54 1.12L12 17.01l-4.45 3.23a1 1 0 01-1.54-1.12l1.7-5.24-4.45-3.23a1 1 0 01.59-1.81h5.5l1.7-5.24z" />
                      </svg>
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={(event) => onOpenActionMenu(event, session)}
                    disabled={isArchiving}
                    aria-label={labels.sessionActions}
                    title={labels.sessionActions}
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-transparent text-slate-400 transition-colors hover:border-slate-200 hover:bg-white hover:text-slate-700 disabled:cursor-progress disabled:opacity-50"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6.75 12h.01M12 12h.01M17.25 12h.01"></path>
                    </svg>
                  </button>
                </div>
              </div>
              <h4 className={`line-clamp-2 pl-1 text-sm leading-6 ${isActive ? "font-semibold text-gray-950" : "font-medium text-gray-700"}`}>
                {session.title}
              </h4>
              {renderSessionMeta?.(session)}
              <p className="mt-2 truncate pl-1 font-mono text-[11px] text-slate-400">
                {session.id.slice(0, 12)}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
