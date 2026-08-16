import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { ProviderMetadata } from "../../types";
import type {
  MenubarPopoverSessionLane,
  MenubarPopoverSnapshot,
  MenubarPopoverTab,
  MenubarPopoverUsageProvider,
} from "./types";
import {
  formatRelativeAge,
  lanePreviewText,
  providerAccent,
  statusTone,
} from "../../utils/menubarPopover";

const OVERVIEW_TAB_ID = "overview";
const SNAPSHOT_UPDATED_EVENT = "menubar:snapshot-updated";

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
  const prefix = estimated ? "~" : "";
  if (value >= 1_000_000) {
    return `${prefix}${Number((value / 1_000_000).toFixed(2))}M`;
  }
  if (value >= 1_000) {
    return `${prefix}${Number((value / 1_000).toFixed(1))}k`;
  }
  return `${prefix}${value}`;
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

function formatFreshness(generatedAtEpoch: number | null, nowMs: number) {
  return formatRelativeAge(generatedAtEpoch, nowMs).replace(/ ago$/, "");
}

export function MenubarPopover() {
  const [snapshot, setSnapshot] = useState<MenubarPopoverSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [selectedTab, setSelectedTab] = useState(OVERVIEW_TAB_ID);
  const [providerIconUrls, setProviderIconUrls] = useState<Record<string, string>>({});
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

  const loadSnapshot = useCallback(async (forceRefresh = false) => {
    if (snapshotLoadInFlight.current) {
      return;
    }
    snapshotLoadInFlight.current = true;
    if (forceRefresh) {
      setLoading(true);
    }
    try {
      const next = await invoke<MenubarPopoverSnapshot>("get_menubar_popover_snapshot", {
        forceRefresh,
      });
      setSnapshot(next);
      setError(null);
    } catch (loadError) {
      console.error("Failed to load menubar popover snapshot", loadError);
      setError(loadError instanceof Error ? loadError.message : "Failed to load popover data");
    } finally {
      snapshotLoadInFlight.current = false;
      if (forceRefresh) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let unsubscribe: (() => void) | null = null;

    void listen<MenubarPopoverSnapshot>(SNAPSHOT_UPDATED_EVENT, ({ payload }) => {
      if (!disposed) {
        setSnapshot(payload);
        setError(null);
      }
    }).then((unlisten) => {
      unsubscribe = unlisten;
      return loadSnapshot(false);
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

  useEffect(() => {
    let disposed = false;
    void invoke<ProviderMetadata[]>("get_provider_metadata")
      .then((metadata) => {
        if (disposed) {
          return;
        }
        const nextIconUrls = Object.fromEntries(
          metadata.flatMap((provider) => {
            const iconUrl = provider.icon?.url?.trim();
            return iconUrl ? [[provider.id, iconUrl]] : [];
          }),
        );
        setProviderIconUrls(nextIconUrls);
      })
      .catch(() => {
        // Provider icons are optional in non-Tauri previews.
      });
    return () => {
      disposed = true;
    };
  }, []);

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
      }
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
  }, []);

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
  const totalCostUsd = useMemo(() => {
    const pricedProviders = providers.filter((provider) => provider.totalCostUsd !== null);
    if (pricedProviders.length === 0) {
      return null;
    }
    return pricedProviders.reduce((sum, provider) => sum + (provider.totalCostUsd ?? 0), 0);
  }, [providers]);
  const freshnessText = snapshot
    ? formatFreshness(snapshot.generatedAtEpoch, nowMs)
    : loading
      ? "syncing"
      : "--";

  return (
    <div className="h-screen w-screen overflow-hidden bg-transparent p-[1px] text-[var(--ow-text)]">
      <div className="relative flex h-full flex-col overflow-hidden rounded-[16px] border border-[var(--ow-line)] bg-[var(--ow-panel)] [box-shadow:var(--ow-shadow-md)] backdrop-blur-2xl">
        <header className="flex h-[84px] shrink-0 items-center justify-between gap-4 border-b border-[var(--ow-line)] bg-[var(--ow-panel)] px-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[var(--ow-green)]" aria-hidden="true" />
              <h1 className="truncate text-[18px] font-bold tracking-[-0.02em] text-[var(--ow-text)]">
                OnlineWorker
              </h1>
            </div>
            <p className="mt-1 flex items-center gap-1.5 text-[12px] font-medium text-[var(--ow-muted)]" aria-live="polite">
              <span>Live</span>
              <span className="h-1 w-1 rounded-full bg-[var(--ow-green)]" aria-hidden="true" />
              <span>{freshnessText}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadSnapshot(true)}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-[8px] text-[var(--ow-muted)] transition-colors hover:bg-[var(--ow-hover)] hover:text-[var(--ow-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ow-focus)] disabled:cursor-wait disabled:text-[var(--ow-disabled)]"
            disabled={loading}
            title="Refresh"
            aria-label="Refresh menubar data"
          >
            <RefreshIcon className={loading ? "animate-spin" : ""} />
          </button>
        </header>

        <nav className="flex h-12 shrink-0 items-stretch border-b border-[var(--ow-line)] bg-[var(--ow-toolbar)]" aria-label="Provider views">
          <div className="flex min-w-0 flex-1 items-stretch overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
        </nav>

        {error && (
          <div className="shrink-0 border-b border-[var(--ow-red-soft)] bg-[var(--ow-red-soft)] px-3.5 py-2 text-[11px] font-semibold text-[var(--ow-error-text)]">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate">{error}</span>
              <button
                type="button"
                onClick={() => void loadSnapshot(true)}
                className="rounded-[6px] border border-[var(--ow-red-soft)] bg-[var(--ow-input)] px-2 py-1 text-[10px] font-bold text-[var(--ow-error-text)] hover:bg-[var(--ow-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ow-focus)]"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        <main className="min-h-0 flex-1 overflow-y-auto bg-[var(--ow-panel)]">
          {selectedProvider ? (
            <ProviderRailPanel
              provider={selectedProvider}
              lane={laneByProviderId.get(selectedProvider.providerId) ?? null}
              iconUrl={providerIconUrls[selectedProvider.providerId]}
              busyKey={busyKey}
              nowMs={nowMs}
              onOpenSession={openSession}
            />
          ) : (
            <OverviewRailPanel
              loading={loading && !snapshot}
              providers={providers}
              lanes={lanes}
              providerIconUrls={providerIconUrls}
              totalTokensText={totalTokensText}
              totalCostText={formatUsd(totalCostUsd)}
              busyKey={busyKey}
              nowMs={nowMs}
              onOpenSession={openSession}
            />
          )}
        </main>

        <div className="grid h-[52px] shrink-0 grid-cols-3 border-t border-[var(--ow-line)] bg-[var(--ow-toolbar)]">
          <PopoverActionButton
            label="Tasks"
            icon={<TaskBoardIcon />}
            active={false}
            busy={busyKey === "tab:tasks"}
            onClick={() => void openTab("tasks")}
          />
          <PopoverActionButton
            label="Sessions"
            icon={<SessionsIcon />}
            active
            busy={busyKey === "tab:sessions"}
            onClick={() => void openTab("sessions")}
          />
          <PopoverActionButton
            label="Usage"
            icon={<UsageIcon />}
            active={false}
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
  providerIconUrls,
  totalTokensText,
  totalCostText,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  loading: boolean;
  providers: MenubarPopoverUsageProvider[];
  lanes: MenubarPopoverSessionLane[];
  providerIconUrls: Record<string, string>;
  totalTokensText: string;
  totalCostText: string;
  busyKey: string | null;
  nowMs: number;
  onOpenSession: (lane: MenubarPopoverSessionLane) => void;
}) {
  return (
    <div>
      <section className="border-b border-[var(--ow-line)] bg-[var(--ow-panel)]">
        <div className="flex h-11 items-end px-5 pb-2">
          <h2 className="text-[15px] font-bold tracking-[-0.01em] text-[var(--ow-text)]">Sessions</h2>
        </div>
        <div className="divide-y divide-[var(--ow-line)]">
          {lanes.length > 0 ? (
            lanes.map((lane) => (
              <SessionRailRow
                key={lane.providerId}
                lane={lane}
                iconUrl={providerIconUrls[lane.providerId]}
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

      <section className="bg-[var(--ow-panel)] px-5 pb-4 pt-3.5">
        <h2 className="text-[15px] font-bold tracking-[-0.01em] text-[var(--ow-text)]">Usage</h2>
        <p className="mt-1.5 text-[11px] font-medium text-[var(--ow-muted)]">
          Today
          <strong className="ml-2 font-bold text-[var(--ow-text)]">
            {loading ? "..." : totalTokensText} tokens
          </strong>
          <span className="mx-1.5 text-[var(--ow-subtle)]">·</span>
          <strong className="font-bold text-[var(--ow-text)]">{totalCostText}</strong>
        </p>
        <UsageSegments providers={providers} showLegend />
      </section>
    </div>
  );
}

function ProviderRailPanel({
  provider,
  lane,
  iconUrl,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  provider: MenubarPopoverUsageProvider;
  lane: MenubarPopoverSessionLane | null;
  iconUrl?: string;
  busyKey: string | null;
  nowMs: number;
  onOpenSession: (lane: MenubarPopoverSessionLane) => void;
}) {
  const workspaceText = lane?.workspaceName || lane?.workspace || "No active workspace";
  const breakdown = [
    { label: "Input", value: formatPopoverTokenCount(provider.inputTokens) },
    { label: "Output", value: formatPopoverTokenCount(provider.outputTokens) },
    { label: "Cache W", value: formatPopoverTokenCount(provider.cacheCreationTokens) },
    { label: "Cache R", value: formatPopoverTokenCount(provider.cacheReadTokens) },
  ];

  return (
    <div className="bg-[var(--ow-panel)]">
      <section className="border-b border-[var(--ow-line)] px-5 pb-4 pt-4">
        <div className="flex min-w-0 items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <ProviderIconTile
              providerId={provider.providerId}
              label={provider.label}
              iconUrl={iconUrl}
              size="compact"
            />
            <div className="min-w-0">
              <h2 className="truncate text-[15px] font-bold text-[var(--ow-text)]">{provider.label}</h2>
              <p className="mt-0.5 truncate text-[10px] font-medium text-[var(--ow-muted)]">
                {workspaceText}
              </p>
            </div>
          </div>
          <p className="shrink-0 text-[10px] font-semibold text-[var(--ow-muted)]">
            {formatUsd(provider.totalCostUsd)}
          </p>
        </div>
        <div className="mt-4 text-[30px] font-bold leading-none tracking-[-0.03em] text-[var(--ow-text)]">
          {formatPopoverTokenCount(provider.tokensToday, provider.estimated)}
          {" "}
          <span className="ml-1.5 text-[11px] font-semibold tracking-normal text-[var(--ow-muted)]">tokens today</span>
        </div>
        <div className="mt-4 grid grid-cols-4 gap-2">
          {breakdown.map((item) => (
            <ProviderMetric key={item.label} label={item.label} value={item.value} />
          ))}
        </div>
      </section>

      <div className="flex h-11 items-end justify-between gap-3 px-5 pb-2">
        <h3 className="text-[14px] font-bold text-[var(--ow-text)]">Latest session</h3>
        <p className="text-[10px] font-medium text-[var(--ow-muted)]">
          {lane?.updatedAtEpoch ? formatRelativeAge(lane.updatedAtEpoch, nowMs) : "No activity"}
        </p>
      </div>

      <div className="border-y border-[var(--ow-line)] bg-[var(--ow-panel)]">
        {lane ? (
          <SessionRailRow
            lane={lane}
            iconUrl={iconUrl}
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

function UsageSegments({
  providers,
  showLegend = false,
}: {
  providers: MenubarPopoverUsageProvider[];
  showLegend?: boolean;
}) {
  const visibleProviders = providers.filter((provider) => (provider.tokensToday ?? 0) > 0);
  const total = visibleProviders.reduce((sum, provider) => sum + (provider.tokensToday ?? 0), 0);

  return (
    <div className="mt-3">
      <div className="flex h-1.5 overflow-hidden rounded-[2px] bg-[var(--ow-disabled-surface)]">
        {total > 0 ? (
          visibleProviders.map((provider) => {
            const accent = providerAccent(provider.providerId);
            return (
              <span
                key={provider.providerId}
                className={`h-full border-r border-[var(--ow-panel)] last:border-r-0 ${accent.laneDot}`}
                style={{ width: `${((provider.tokensToday ?? 0) / total) * 100}%` }}
                title={`${provider.label}: ${formatPopoverTokenCount(provider.tokensToday, provider.estimated)}`}
              />
            );
          })
        ) : (
          <span className="h-full w-full bg-[var(--ow-disabled)]" />
        )}
      </div>
      {showLegend && visibleProviders.length > 0 && (
        <div className="mt-2.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
          {visibleProviders.map((provider) => {
            const accent = providerAccent(provider.providerId);
            return (
              <div key={provider.providerId} className="flex min-w-0 items-center gap-1.5 text-[10px] font-medium text-[var(--ow-muted)]">
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${accent.laneDot}`} aria-hidden="true" />
                <span className="truncate">{provider.label}</span>
                <span className="shrink-0">{formatPopoverTokenCount(provider.tokensToday, provider.estimated)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ProviderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <span className="block truncate text-[8px] font-semibold text-[var(--ow-muted)]">{label}</span>
      <strong className="mt-1 block truncate font-mono text-[11px] font-bold text-[var(--ow-text)]">
        {value}
      </strong>
    </div>
  );
}

function ProviderIconTile({
  providerId,
  label,
  iconUrl,
  size = "regular",
}: {
  providerId: string;
  label: string;
  iconUrl?: string;
  size?: "compact" | "regular";
}) {
  const accent = providerAccent(providerId);
  const sizeClass = size === "compact" ? "h-10 w-10 rounded-[9px]" : "h-[52px] w-[52px] rounded-[10px]";
  const imageClass = size === "compact" ? "h-5 w-5" : "h-7 w-7";

  return (
    <span
      className={`grid shrink-0 place-items-center border ${sizeClass} ${accent.cardBorder} ${accent.cardBg}`}
      aria-hidden="true"
    >
      {iconUrl ? (
        <img src={iconUrl} alt="" className={`${imageClass} object-contain`} />
      ) : (
        <span className={`text-[13px] font-bold ${accent.laneText}`}>{label.slice(0, 1).toUpperCase()}</span>
      )}
    </span>
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
      className={`relative min-w-[112px] shrink-0 px-4 text-[13px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ow-focus)] ${
        active ? "text-[var(--ow-blue)]" : "text-[var(--ow-muted)] hover:bg-[var(--ow-hover)] hover:text-[var(--ow-text)]"
      }`}
      title={label}
    >
      {label}
      {active && <span className="absolute inset-x-5 bottom-0 h-[2px] rounded-t bg-[var(--ow-blue)]" aria-hidden="true" />}
    </button>
  );
}

function SessionRailRow({
  lane,
  iconUrl,
  busyKey,
  nowMs,
  onOpenSession,
}: {
  lane: MenubarPopoverSessionLane;
  iconUrl?: string;
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
  const statusText = lane.status?.trim() || "";
  const tone = statusTone(lane.status);

  if (!lane.sessionId) {
    return (
      <div className="flex min-h-[76px] items-center gap-3 px-5 py-3">
        <ProviderIconTile providerId={lane.providerId} label={lane.label} iconUrl={iconUrl} />
        <div className="flex min-w-0 flex-1 items-center">
          <div className="min-w-0">
            <p className={`truncate text-[11px] font-semibold ${accent.laneText}`}>{lane.label}</p>
            <p className="mt-1 truncate text-[12px] font-semibold text-[var(--ow-muted)]">No recent session</p>
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
      className="group flex min-h-[94px] w-full items-center gap-3 bg-[var(--ow-panel)] px-5 py-3 text-left transition-colors hover:bg-[var(--ow-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ow-focus)] disabled:cursor-wait disabled:bg-[var(--ow-disabled-surface)] disabled:text-[var(--ow-disabled)] disabled:opacity-70"
    >
      <ProviderIconTile providerId={lane.providerId} label={lane.label} iconUrl={iconUrl} />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold text-[var(--ow-muted)]">
          <span className={`shrink-0 ${accent.laneText}`}>{lane.label}</span>
          <span className="text-[var(--ow-subtle)]" aria-hidden="true">·</span>
          <span className="min-w-0 truncate">{workspaceText}</span>
        </div>
        <p className="mt-1 truncate text-[13px] font-bold leading-[18px] text-[var(--ow-text)]">
          {titleText}
        </p>
        {previewText && (
          <p className="mt-0.5 truncate text-[10px] font-normal leading-[14px] text-[var(--ow-muted)]">
            {previewText}
          </p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2.5">
        <div className="flex items-center gap-2 text-right">
          {statusText && <p className={`text-[11px] font-semibold ${tone.text}`}>{statusText}</p>}
          <p className="text-[10px] font-medium text-[var(--ow-muted)]">
            {formatFreshness(lane.updatedAtEpoch, nowMs)}
          </p>
        </div>
        <span className="grid place-items-center text-[var(--ow-subtle)] transition-colors group-hover:text-[var(--ow-text)]">
          <ChevronRightIcon />
        </span>
      </div>
    </button>
  );
}

function EmptyLine({ label }: { label: string }) {
  return (
    <div className="px-5 py-6 text-[12px] font-semibold text-[var(--ow-subtle)]">
      {label}
    </div>
  );
}

function PopoverActionButton({
  label,
  icon,
  active,
  busy,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  active: boolean;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`flex h-[52px] items-center justify-center gap-1.5 border-r border-[var(--ow-line)] px-2 text-[11px] font-semibold transition-colors last:border-r-0 hover:bg-[var(--ow-hover)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ow-focus)] disabled:cursor-wait disabled:text-[var(--ow-disabled)] disabled:opacity-70 ${
        active ? "text-[var(--ow-blue)]" : "text-[var(--ow-muted)] hover:text-[var(--ow-text)]"
      }`}
    >
      <span className={active ? "text-[var(--ow-blue)]" : "text-[var(--ow-subtle)]"}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function ChevronRightIcon() {
  return (
    <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7" />
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
    <svg className={`h-[18px] w-[18px] ${className}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20 11a8.1 8.1 0 00-15.5-2M4 5v4h4m-4 4a8.1 8.1 0 0015.5 2M20 19v-4h-4" />
    </svg>
  );
}
