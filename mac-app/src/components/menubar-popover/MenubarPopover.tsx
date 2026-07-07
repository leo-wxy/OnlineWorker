import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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
  statusTone,
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
    setLoading(true);
    try {
      const next = await invoke<MenubarPopoverSnapshot>("get_menubar_popover_snapshot");
      setSnapshot(next);
      setError(null);
    } catch (loadError) {
      console.error("Failed to load menubar popover snapshot", loadError);
      setError(loadError instanceof Error ? loadError.message : "Failed to load popover data");
    } finally {
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
      <div className="relative flex h-full flex-col overflow-hidden rounded-[22px] border border-slate-200/80 bg-[rgba(255,255,255,0.98)] backdrop-blur-2xl">
        <section className="shrink-0 border-b border-slate-200/70 bg-gradient-to-b from-white to-slate-50/86 px-3.5 pb-3 pt-3.5">
          <div className="flex items-center gap-2">
            <div className="ow-segment grid min-w-0 flex-1 auto-cols-fr grid-flow-col gap-1 rounded-[14px] p-1">
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
              className="grid h-9 w-9 shrink-0 place-items-center rounded-[12px] border border-slate-200/80 bg-white/86 text-slate-500 transition hover:border-slate-300 hover:text-gray-950 disabled:cursor-wait disabled:opacity-60"
              disabled={loading}
              title="Refresh"
            >
              <RefreshIcon className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </section>

        {error && (
          <div className="shrink-0 border-b border-rose-100 bg-rose-50/90 px-3.5 py-2 text-[11px] font-semibold text-rose-700">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{error}</span>
              <button
                type="button"
                onClick={() => void loadSnapshot()}
                className="rounded-lg border border-rose-100 bg-white px-2 py-1 text-[10px] font-extrabold text-rose-700"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto bg-slate-50/42">
          {selectedProvider ? (
            <ProviderPanel
              provider={selectedProvider}
              lane={laneByProviderId.get(selectedProvider.providerId) ?? null}
              busyKey={busyKey}
              nowMs={nowMs}
              onOpenSession={openSession}
            />
          ) : (
            <OverviewPanel
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

        <div className="grid h-11 shrink-0 grid-cols-3 border-t border-slate-200/70 bg-white/90">
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

function OverviewPanel({
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
    <div className="space-y-3 px-3.5 py-3">
      <section className="rounded-[18px] border border-slate-200/76 bg-white px-4 py-3.5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-slate-400">
              Today usage
            </p>
            <div className="mt-1 text-[30px] font-black leading-none tracking-normal text-gray-950">
              {loading ? "..." : totalTokensText}
            </div>
          </div>
          <div className="grid shrink-0 grid-cols-2 gap-2">
            <MetricTile label="Active" value={activeSessionCount} tone="green" />
            <MetricTile label="Reply" value={needsAttentionCount} tone="amber" />
          </div>
        </div>
      </section>

      <section className="rounded-[18px] border border-slate-200/76 bg-white">
        <SectionTitle title="Providers" subtitle="Token summary" />
        <div className="divide-y divide-slate-100">
          {providers.length > 0 ? (
            providers.map((provider) => (
              <ProviderUsageRow key={provider.providerId} provider={provider} />
            ))
          ) : (
            <EmptyLine label={loading ? "Loading providers" : "No providers available"} />
          )}
        </div>
      </section>

      <section className="rounded-[18px] border border-slate-200/76 bg-white">
        <SectionTitle title="Latest sessions" subtitle="One recent session per provider" />
        <div className="divide-y divide-slate-100">
          {lanes.length > 0 ? (
            lanes.map((lane) => (
              <LatestSessionRow
                key={lane.providerId}
                compact
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

function ProviderPanel({
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
    { label: "Tokens today", value: formatPopoverTokenCount(provider.tokensToday, provider.estimated) },
    { label: "Input", value: formatPopoverTokenCount(provider.inputTokens) },
    { label: "Output", value: formatPopoverTokenCount(provider.outputTokens) },
    { label: "Cache write", value: formatPopoverTokenCount(provider.cacheCreationTokens) },
    { label: "Cache read", value: formatPopoverTokenCount(provider.cacheReadTokens) },
    { label: "Cost", value: formatUsd(provider.totalCostUsd) },
  ];

  return (
    <div className="space-y-3 px-3.5 py-3">
      <section className={`rounded-[18px] border ${accent.cardBorder} bg-white px-4 py-3.5`}>
        <div className="flex items-center gap-3">
          <ProviderAvatar provider={provider} />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-[17px] font-black leading-5 text-gray-950">
                {provider.label}
              </h2>
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-extrabold uppercase tracking-[0.05em] ${statusTone(status).chip}`}>
                {status}
              </span>
            </div>
            <p className="mt-1 truncate text-[11px] font-semibold text-slate-500">
              {workspaceText}
            </p>
          </div>
        </div>
      </section>

      <section className="rounded-[18px] border border-slate-200/76 bg-white">
        <SectionTitle title="Usage" subtitle="Input / Output / Cache" />
        <div className="grid grid-cols-2 gap-2 px-3.5 pb-3.5">
          {breakdown.map((item) => (
            <UsageBreakdownCell key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
      </section>

      <section className="rounded-[18px] border border-slate-200/76 bg-white">
        <SectionTitle title="Latest session" subtitle={lane?.updatedAtEpoch ? formatRelativeAge(lane.updatedAtEpoch, nowMs) : "No activity"} />
        {lane ? (
          <LatestSessionRow
            lane={lane}
            busyKey={busyKey}
            nowMs={nowMs}
            onOpenSession={onOpenSession}
          />
        ) : (
          <EmptyLine label="No recent session" />
        )}
      </section>
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
      className={`h-7 min-w-0 rounded-[10px] px-2 text-[12px] font-extrabold transition ${
        active
          ? "bg-white text-gray-950"
          : "text-slate-500 hover:bg-white/70 hover:text-gray-900"
      }`}
      title={label}
    >
      <span className="block truncate">{label}</span>
    </button>
  );
}

function ProviderUsageRow({ provider }: { provider: MenubarPopoverUsageProvider }) {
  const accent = providerAccent(provider.providerId);
  return (
    <div className="flex min-h-[46px] items-center justify-between gap-3 px-3.5 py-2.5">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${accent.laneDot}`} />
        <span className="truncate text-[12px] font-extrabold text-slate-800">{provider.label}</span>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-[13px] font-black text-gray-950">
          {formatPopoverTokenCount(provider.tokensToday, provider.estimated)}
        </div>
        <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-slate-400">
          tokens
        </div>
      </div>
    </div>
  );
}

function LatestSessionRow({
  lane,
  compact = false,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  lane: MenubarPopoverSessionLane;
  compact?: boolean;
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
      <div className="flex min-h-[54px] items-center gap-2.5 px-3.5 py-2.5">
        <span className={`h-2 w-2 shrink-0 rounded-full ${accent.laneDot}`} />
        <div className="min-w-0">
          <p className="truncate text-[12px] font-extrabold text-slate-700">{lane.label}</p>
          <p className="truncate text-[11px] font-semibold text-slate-400">No recent session</p>
        </div>
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onOpenSession(lane)}
      disabled={Boolean(isBusy)}
      className={`group grid w-full grid-cols-[minmax(0,1fr)_32px] items-center gap-2 px-3.5 text-left transition hover:bg-slate-50/92 disabled:cursor-wait disabled:opacity-70 ${
        compact ? "min-h-[78px] py-2.5" : "min-h-[96px] py-3"
      }`}
    >
      <div className="min-w-0">
        <div className="mb-1 flex min-w-0 items-center gap-2">
          {compact && (
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-extrabold ${accent.tileBg} ${accent.tileText}`}>
              {lane.label}
            </span>
          )}
          <span className="min-w-0 truncate text-[10px] font-bold text-slate-500">
            {workspaceText}
          </span>
          <span className="shrink-0 text-[9px] font-bold text-slate-400">
            {formatRelativeAge(lane.updatedAtEpoch, nowMs)}
          </span>
        </div>
        <p className="truncate text-[14px] font-black leading-5 text-gray-950">
          {titleText}
        </p>
        {previewText && (
          <p className="mt-0.5 truncate text-[11px] font-medium leading-4 text-slate-500">
            {previewText}
          </p>
        )}
      </div>
      <span className={`grid h-8 w-8 place-items-center rounded-[10px] ${accent.actionText} opacity-70 transition group-hover:bg-white group-hover:opacity-100`}>
        <ArrowUpRightIcon />
      </span>
    </button>
  );
}

function UsageBreakdownCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-[14px] border border-slate-200/70 bg-slate-50/66 px-3 py-2.5">
      <p className="truncate text-[9px] font-extrabold uppercase tracking-[0.08em] text-slate-400">
        {label}
      </p>
      <p className="mt-1 truncate text-[15px] font-black leading-5 text-gray-950">{value}</p>
    </div>
  );
}

function ProviderAvatar({ provider }: { provider: MenubarPopoverUsageProvider }) {
  const accent = providerAccent(provider.providerId);
  const initials = provider.label
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase() || provider.providerId.slice(0, 2).toUpperCase();

  return (
    <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-[15px] ${accent.avatarBg} ${accent.tileText} text-[13px] font-black`}>
      {initials}
    </div>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3.5 py-3">
      <h3 className="truncate text-[12px] font-black text-gray-950">{title}</h3>
      <p className="shrink-0 truncate text-[10px] font-bold text-slate-400">{subtitle}</p>
    </div>
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
      className="flex h-11 items-center justify-center gap-1.5 border-r border-slate-200/70 px-2 text-[10px] font-extrabold text-slate-600 transition last:border-r-0 hover:bg-slate-50 hover:text-gray-950 disabled:cursor-wait disabled:opacity-70"
    >
      <span className="text-slate-400">{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "green" | "amber";
}) {
  const className =
    tone === "green"
      ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)]"
      : "bg-[var(--ow-amber-soft)] text-[var(--ow-amber)]";
  return (
    <div className={`min-w-[58px] rounded-[14px] px-2.5 py-2 text-center ${className}`}>
      <div className="text-[17px] font-black leading-5">{value}</div>
      <div className="text-[8px] font-extrabold uppercase tracking-[0.08em]">{label}</div>
    </div>
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
