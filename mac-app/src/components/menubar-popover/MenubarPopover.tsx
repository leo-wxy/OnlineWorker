import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type {
  MenubarPopoverSessionLane,
  MenubarPopoverSnapshot,
  MenubarPopoverTab,
  MenubarPopoverUsageProvider,
} from "./types";
import {
  formatRelativeAge,
  formatTokenCount,
  lanePreviewText,
  providerAccent,
} from "../../utils/menubarPopover";

const OVERVIEW_TAB_ID = "overview";

async function hideCurrentWindow() {
  try {
    await getCurrentWindow().hide();
  } catch {
    // Ignore non-Tauri environments.
  }
}

function formatPopoverTokenCount(value: number | null, estimated = false) {
  if (value === null || Number.isNaN(value)) {
    return "--";
  }
  return `${estimated ? "~" : ""}${formatTokenCount(value, false)}`;
}

function formatUsd(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "--";
  }
  if (value === 0) {
    return "$0";
  }
  return `$${value.toFixed(value < 1 ? 3 : 2)}`;
}

export function MenubarPopover() {
  const [snapshot, setSnapshot] = useState<MenubarPopoverSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState(OVERVIEW_TAB_ID);
  const snapshotLoadInFlight = useRef(false);

  useEffect(() => {
    const previousHtmlBackground = document.documentElement.style.background;
    const previousBodyBackground = document.body.style.background;
    const previousRootBackground = document.getElementById("root")?.style.background ?? "";
    document.documentElement.style.background = "transparent";
    document.body.style.background = "transparent";
    const root = document.getElementById("root");
    if (root) {
      root.style.background = "transparent";
    }
    return () => {
      document.documentElement.style.background = previousHtmlBackground;
      document.body.style.background = previousBodyBackground;
      if (root) {
        root.style.background = previousRootBackground;
      }
    };
  }, []);

  const loadSnapshot = useCallback(async () => {
    if (snapshotLoadInFlight.current) {
      return;
    }
    snapshotLoadInFlight.current = true;
    setLoading(true);
    try {
      const next = await invoke<MenubarPopoverSnapshot>("get_menubar_popover_snapshot");
      setSnapshot(next);
      setError(null);
    } catch (loadError) {
      console.error("Failed to load menubar popover snapshot", loadError);
      setError(loadError instanceof Error ? loadError.message : "Failed to load popover data");
    } finally {
      snapshotLoadInFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSnapshot();
  }, [loadSnapshot]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 30_000);
    return () => {
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        void hideCurrentWindow();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let unsubscribe: (() => void) | null = null;

    void getCurrentWindow().onFocusChanged(({ payload: focused }) => {
      if (disposed) {
        return;
      }
      if (!focused) {
        void hideCurrentWindow();
        return;
      }
      void loadSnapshot();
    }).then((unlisten) => {
      unsubscribe = unlisten;
    }).catch(() => {
      // Ignore non-Tauri environments.
    });

    return () => {
      disposed = true;
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, [loadSnapshot]);

  const providers = useMemo(() => snapshot?.usage.providers ?? [], [snapshot]);
  const lanes = useMemo(() => snapshot?.latestSessions ?? [], [snapshot]);
  const laneByProviderId = useMemo(() => {
    return new Map(lanes.map((lane) => [lane.providerId, lane]));
  }, [lanes]);

  useEffect(() => {
    if (selectedTab === OVERVIEW_TAB_ID) {
      return;
    }
    if (!providers.some((provider) => provider.providerId === selectedTab)) {
      setSelectedTab(OVERVIEW_TAB_ID);
    }
  }, [providers, selectedTab]);

  const openSession = useCallback(async (lane: MenubarPopoverSessionLane) => {
    if (!lane.sessionId) {
      return;
    }
    const actionKey = `session:${lane.providerId}:${lane.sessionId}`;
    setBusyKey(actionKey);
    try {
      await invoke("open_menubar_popover_session", {
        providerId: lane.providerId,
        sessionId: lane.sessionId,
        workspaceDir: lane.workspace ?? null,
      });
    } finally {
      setBusyKey(null);
    }
  }, []);

  const openTab = useCallback(async (tab: MenubarPopoverTab) => {
    setBusyKey(`tab:${tab}`);
    try {
      await invoke("open_menubar_tab", { tab });
    } finally {
      setBusyKey(null);
    }
  }, []);

  const selectedProvider = providers.find((provider) => provider.providerId === selectedTab);
  const totalTokensText = formatPopoverTokenCount(snapshot?.usage.totalTokensToday ?? null);
  const activeSessionCount = snapshot?.usage.activeSessionCount ?? 0;
  const needsAttentionCount = snapshot?.usage.needsAttentionCount ?? 0;

  return (
    <div className="h-screen w-screen overflow-hidden bg-transparent p-[1px] text-[var(--ow-text)]">
      <div className="relative flex h-full flex-col overflow-hidden rounded-[16px] border border-slate-200/90 bg-slate-50">
        <header className="flex h-[50px] shrink-0 items-center gap-2 border-b border-slate-200/80 bg-white px-3">
          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <ProviderTabButton
              active={selectedTab === OVERVIEW_TAB_ID}
              label="总览"
              onClick={() => setSelectedTab(OVERVIEW_TAB_ID)}
            />
            {providers.map((provider) => (
              <ProviderTabButton
                key={provider.providerId}
                active={selectedTab === provider.providerId}
                label={provider.label}
                onClick={() => setSelectedTab(provider.providerId)}
              />
            ))}
          </div>
          <button
            type="button"
            onClick={() => void loadSnapshot()}
            className="grid h-[30px] w-[30px] shrink-0 place-items-center rounded-[7px] text-slate-500 transition hover:bg-slate-100 hover:text-gray-950 disabled:cursor-wait disabled:opacity-60"
            disabled={loading}
            title="Refresh"
          >
            <RefreshIcon className={loading ? "animate-spin" : ""} />
          </button>
        </header>

        {error && (
          <div className="shrink-0 border-b border-rose-100 bg-rose-50 px-3.5 py-2 text-[11px] font-semibold text-rose-700">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{error}</span>
              <button
                type="button"
                onClick={() => void loadSnapshot()}
                className="rounded-[6px] border border-rose-200 bg-white px-2 py-1 text-[10px] font-bold text-rose-700"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50">
          {selectedProvider ? (
            <ProviderRailPanel
              provider={selectedProvider}
              lane={laneByProviderId.get(selectedProvider.providerId) ?? null}
              busyKey={busyKey}
              nowMs={nowMs}
              onOpenSession={openSession}
            />
          ) : (
            <OverviewRailPanel
              loading={loading && !snapshot}
              providers={providers}
              lanes={lanes}
              totalTokensText={totalTokensText}
              activeSessionCount={activeSessionCount}
              needsAttentionCount={needsAttentionCount}
              busyKey={busyKey}
              nowMs={nowMs}
              onOpenSession={openSession}
            />
          )}
        </main>

        <div className="grid h-11 shrink-0 grid-cols-3 border-t border-slate-200/80 bg-white">
          <PopoverActionButton
            label="Tasks"
            icon={<TaskBoardIcon />}
            busy={busyKey === "tab:tasks"}
            onClick={() => void openTab("tasks")}
          />
          <PopoverActionButton
            label="Sessions"
            icon={<SessionsIcon />}
            busy={busyKey === "tab:sessions"}
            onClick={() => void openTab("sessions")}
          />
          <PopoverActionButton
            label="Usage"
            icon={<UsageIcon />}
            busy={busyKey === "tab:usage"}
            onClick={() => void openTab("usage")}
          />
        </div>
      </div>
    </div>
  );
}

function OverviewRailPanel({
  loading,
  providers,
  lanes,
  totalTokensText,
  activeSessionCount,
  needsAttentionCount,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  loading: boolean;
  providers: MenubarPopoverUsageProvider[];
  lanes: MenubarPopoverSessionLane[];
  totalTokensText: string;
  activeSessionCount: number;
  needsAttentionCount: number;
  busyKey: string | null;
  nowMs: number;
  onOpenSession: (lane: MenubarPopoverSessionLane) => void;
}) {
  return (
    <div>
      <section className="min-h-[138px] border-b border-slate-200/80 bg-white px-[18px] pb-4 pt-5">
        <p className="text-[10px] font-bold text-slate-500">Today usage</p>
        <div className="mt-2 flex items-end justify-between gap-4">
          <div className="min-w-0 truncate text-[39px] font-bold leading-none text-gray-950">
            {loading ? "..." : totalTokensText}
            <span className="ml-1 text-[12px] font-semibold text-slate-500">tokens</span>
          </div>
          <div className="flex shrink-0 gap-4 pb-0.5">
            <OverviewPulse
              label="Active"
              value={activeSessionCount}
              className="text-[var(--ow-green)]"
            />
            <OverviewPulse
              label="Reply"
              value={needsAttentionCount}
              className="text-[var(--ow-amber)]"
            />
          </div>
        </div>
        <UsageSegments providers={providers} />
      </section>

      <section className="px-3.5 pb-3.5">
        <div className="flex h-11 items-center justify-between gap-3">
          <h3 className="text-[12px] font-bold text-gray-950">Active sessions</h3>
          <p className="text-[10px] font-medium text-slate-500">
            Latest from each provider
          </p>
        </div>
        <div className="overflow-hidden rounded-[9px] border border-slate-200 bg-white">
          {lanes.length > 0 ? (
            lanes.map((lane) => (
              <SessionRailRow
                key={lane.providerId}
                lane={lane}
                busyKey={busyKey}
                nowMs={nowMs}
                onOpenSession={onOpenSession}
              />
            ))
          ) : (
            <EmptyLine label={loading ? "Loading sessions" : "No recent session"} />
          )}
        </div>
      </section>
    </div>
  );
}

function ProviderRailPanel({
  provider,
  lane,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  provider: MenubarPopoverUsageProvider;
  lane: MenubarPopoverSessionLane | null;
  busyKey: string | null;
  nowMs: number;
  onOpenSession: (lane: MenubarPopoverSessionLane) => void;
}) {
  const accent = providerAccent(provider.providerId);
  const workspaceText = lane?.workspaceName || lane?.workspace || "No active workspace";
  const status = lane?.status || (lane?.sessionId ? "Active" : "Idle");
  const breakdown = [
    { label: "Input", value: formatPopoverTokenCount(provider.inputTokens) },
    { label: "Output", value: formatPopoverTokenCount(provider.outputTokens) },
    { label: "Cache W", value: formatPopoverTokenCount(provider.cacheCreationTokens) },
    { label: "Cache R", value: formatPopoverTokenCount(provider.cacheReadTokens) },
  ];

  return (
    <div className="space-y-0 px-3.5 py-3.5">
      <section className="relative min-h-[148px] overflow-hidden rounded-[9px] border border-slate-200 bg-white px-4 py-4">
        <span className={`absolute inset-y-0 left-0 w-[3px] ${accent.laneDot}`} />
        <div className="flex min-w-0 items-center justify-between gap-3">
          <h2 className="truncate text-[15px] font-bold text-gray-950">{provider.label}</h2>
          <p className="min-w-0 truncate text-[9px] font-medium text-slate-500">
            {workspaceText} · {status}
          </p>
        </div>
        <div className="mt-4 text-[32px] font-bold leading-none text-gray-950">
          {formatPopoverTokenCount(provider.tokensToday, provider.estimated)}
        </div>
        <div className="mt-4 grid grid-cols-4 gap-2">
          {breakdown.map((item) => (
            <ProviderMetric key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
      </section>

      <div className="flex h-11 items-center justify-between gap-3 px-0.5">
        <h3 className="text-[12px] font-bold text-gray-950">Latest session</h3>
        <p className="text-[10px] font-medium text-slate-500">
          {lane?.updatedAtEpoch ? formatRelativeAge(lane.updatedAtEpoch, nowMs) : "No activity"}
          {" · "}
          {formatUsd(provider.totalCostUsd)}
        </p>
      </div>

      <div className="overflow-hidden rounded-[9px] border border-slate-200 bg-white">
        {lane ? (
          <SessionRailRow
            lane={lane}
            busyKey={busyKey}
            nowMs={nowMs}
            onOpenSession={onOpenSession}
          />
        ) : (
          <EmptyLine label="No recent session" />
        )}
      </div>
    </div>
  );
}

function OverviewPulse({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className: string;
}) {
  return (
    <div className="text-right">
      <strong className={`block text-[18px] font-bold leading-5 ${className}`}>{value}</strong>
      <span className="mt-0.5 block text-[9px] font-semibold text-slate-500">{label}</span>
    </div>
  );
}

function UsageSegments({ providers }: { providers: MenubarPopoverUsageProvider[] }) {
  const visibleProviders = providers.filter((provider) => (provider.tokensToday ?? 0) > 0);
  const total = visibleProviders.reduce((sum, provider) => sum + (provider.tokensToday ?? 0), 0);

  return (
    <div className="mt-4 flex h-1 overflow-hidden rounded-sm bg-slate-200">
      {total > 0 ? (
        visibleProviders.map((provider) => {
          const accent = providerAccent(provider.providerId);
          return (
            <span
              key={provider.providerId}
              className={`h-full ${accent.laneDot}`}
              style={{ width: `${((provider.tokensToday ?? 0) / total) * 100}%` }}
              title={`${provider.label}: ${formatPopoverTokenCount(provider.tokensToday, provider.estimated)}`}
            />
          );
        })
      ) : (
        <span className="h-full w-full bg-slate-300" />
      )}
    </div>
  );
}

function ProviderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="block truncate text-[8px] font-semibold text-slate-500">{label}</span>
      <strong className="mt-1 block truncate font-mono text-[11px] font-bold text-gray-950">
        {value}
      </strong>
    </div>
  );
}

function ProviderTabButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`h-7 shrink-0 rounded-[7px] px-2.5 text-[11px] font-semibold transition ${
        active
          ? "bg-slate-100 text-gray-950"
          : "text-slate-500 hover:bg-slate-50 hover:text-gray-900"
      }`}
      title={label}
    >
      {label}
    </button>
  );
}

function SessionRailRow({
  lane,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  lane: MenubarPopoverSessionLane;
  busyKey: string | null;
  nowMs: number;
  onOpenSession: (lane: MenubarPopoverSessionLane) => void;
}) {
  const accent = providerAccent(lane.providerId);
  const isBusy = busyKey === `session:${lane.providerId}:${lane.sessionId}`;
  const workspaceText = lane.workspaceName || lane.workspace || "Unknown workspace";
  const titleText = lane.title?.trim() || lane.sessionId || "Untitled session";
  const rawPreview = lanePreviewText(lane);
  const previewText = rawPreview !== titleText && rawPreview !== "No recent message" ? rawPreview : "";

  if (!lane.sessionId) {
    return (
      <div className="grid min-h-[66px] grid-cols-[3px_minmax(0,1fr)] border-b border-slate-100 last:border-b-0">
        <span className={accent.laneDot} />
        <div className="flex min-w-0 items-center px-3 py-2.5">
          <div className="min-w-0">
            <p className="truncate text-[10px] font-semibold text-slate-500">{lane.label}</p>
            <p className="mt-1 truncate text-[12px] font-semibold text-slate-700">No recent session</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onOpenSession(lane)}
      disabled={Boolean(isBusy)}
      className="group grid min-h-[74px] w-full grid-cols-[3px_minmax(0,1fr)_30px] border-b border-slate-100 bg-white text-left transition last:border-b-0 hover:bg-slate-50 disabled:cursor-wait disabled:opacity-70"
    >
      <span className={accent.laneDot} />
      <div className="min-w-0 px-3 py-2.5">
        <div className="flex min-w-0 items-center justify-between gap-3 text-[9px] font-semibold text-slate-500">
          <span className="min-w-0 truncate">
            {workspaceText}
            <span className={`ml-1.5 ${accent.laneText}`}>· {lane.label}</span>
          </span>
          <span className="shrink-0">{formatRelativeAge(lane.updatedAtEpoch, nowMs)}</span>
        </div>
        <p className="mt-1 truncate text-[12px] font-bold leading-4 text-gray-950">
          {titleText}
        </p>
        {previewText && (
          <p className="mt-0.5 truncate text-[10px] font-normal leading-[14px] text-slate-500">
            {previewText}
          </p>
        )}
      </div>
      <span className="grid place-items-center text-slate-400 transition group-hover:text-gray-900">
        <ArrowUpRightIcon />
      </span>
    </button>
  );
}

function EmptyLine({ label }: { label: string }) {
  return (
    <div className="px-3.5 py-4 text-[12px] font-semibold text-slate-400">
      {label}
    </div>
  );
}

function PopoverActionButton({
  label,
  icon,
  busy,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="flex h-11 items-center justify-center gap-1.5 border-r border-slate-200/80 px-2 text-[10px] font-semibold text-slate-600 transition last:border-r-0 hover:bg-slate-50 hover:text-gray-950 disabled:cursor-wait disabled:opacity-70"
    >
      <span className="text-slate-400">{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function ArrowUpRightIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 17L17 7m0 0H9m8 0v8" />
    </svg>
  );
}

function TaskBoardIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

function SessionsIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v6a2 2 0 01-2 2h-4" />
    </svg>
  );
}

function UsageIcon() {
  return (
    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 12h3m4-6h3m-3 12h7m-7-6h7M7 6h.01M7 12h.01M7 18h.01" />
    </svg>
  );
}

function RefreshIcon({ className = "" }: { className?: string }) {
  return (
    <svg className={`h-4 w-4 ${className}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20 11a8.1 8.1 0 00-15.5-2M4 5v4h4m-4 4a8.1 8.1 0 0015.5 2M20 19v-4h-4" />
    </svg>
  );
}
