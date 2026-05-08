import { startTransition, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useDashboardState } from "../hooks";
import { useI18n, type AppTexts } from "../i18n";
import type {
  AlertLevel,
  ConnectionStatus,
  DashboardAlert,
  DashboardState,
  ProviderDashboardStatus,
  ServiceHealth,
  SystemHealth,
} from "../types";

interface Props {
  onOpenLogs: () => void;
  onOpenSetup: () => void;
  onOpenSessions: () => void;
}

type ServiceAction = "start" | "stop" | "restart";

function getOverallStyles(
  texts: AppTexts
): Record<SystemHealth, { badge: string; panel: string; title: string; detail: string }> {
  return {
    healthy: {
      badge: "bg-emerald-100 text-emerald-700",
      panel: "border-emerald-200 bg-emerald-50/78",
      title: texts.dashboard.overallTitle.healthy,
      detail: texts.dashboard.overallDetail.healthy,
    },
    degraded: {
      badge: "bg-amber-100 text-amber-700",
      panel: "border-amber-200 bg-amber-50/78",
      title: texts.dashboard.overallTitle.degraded,
      detail: texts.dashboard.overallDetail.degraded,
    },
    misconfigured: {
      badge: "bg-orange-100 text-orange-700",
      panel: "border-orange-200 bg-orange-50/78",
      title: texts.dashboard.overallTitle.misconfigured,
      detail: texts.dashboard.overallDetail.misconfigured,
    },
    stopped: {
      badge: "bg-rose-100 text-rose-700",
      panel: "border-rose-200 bg-rose-50/78",
      title: texts.dashboard.overallTitle.stopped,
      detail: texts.dashboard.overallDetail.stopped,
    },
    unknown: {
      badge: "bg-slate-100 text-slate-700",
      panel: "border-slate-200 bg-slate-50/78",
      title: texts.dashboard.overallTitle.unknown,
      detail: texts.dashboard.overallDetail.unknown,
    },
  };
}

function getServiceStyles(
  texts: AppTexts
): Record<ServiceHealth, { badge: string; dot: string; label: string }> {
  return {
    healthy: {
      badge: "bg-emerald-50 text-emerald-700 border-emerald-100",
      dot: "bg-emerald-500",
      label: texts.common.healthy,
    },
    degraded: {
      badge: "bg-amber-50 text-amber-700 border-amber-100",
      dot: "bg-amber-500",
      label: texts.common.degraded,
    },
    stopped: {
      badge: "bg-rose-50 text-rose-700 border-rose-100",
      dot: "bg-rose-500",
      label: texts.common.stopped,
    },
    unknown: {
      badge: "bg-slate-100 text-slate-600 border-slate-200",
      dot: "bg-slate-400",
      label: texts.common.unknown,
    },
  };
}

function getTelegramStyles(
  texts: AppTexts
): Record<ConnectionStatus, { badge: string; label: string }> {
  return {
    connected: {
      badge: "bg-emerald-100 text-emerald-700",
      label: texts.common.connected,
    },
    disconnected: {
      badge: "bg-rose-100 text-rose-700",
      label: texts.common.disconnected,
    },
    unknown: {
      badge: "bg-slate-100 text-slate-600",
      label: texts.common.unknown,
    },
  };
}

const alertStyles: Record<AlertLevel, string> = {
  warning: "ow-inline-alert-warning",
  error: "ow-inline-alert-error",
};

function TelegramBadge({ status }: { status: ConnectionStatus }) {
  const { t } = useI18n();
  const style = getTelegramStyles(t)[status];
  return (
    <span className={`ow-badge rounded-full px-2.5 py-1 text-[10px] ${style.badge}`}>
      {style.label}
    </span>
  );
}

function formatEpochAge(epoch: number | null | undefined, texts: AppTexts): string {
  if (!epoch) {
    return "-";
  }
  const age = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (age < 60) {
    return texts.common.secondsAgo(age);
  }
  if (age < 3600) {
    return texts.common.minutesAgo(Math.round(age / 60));
  }
  return texts.common.hoursAgo(Math.round(age / 3600));
}

function resolveAlertActionLabel(alert: DashboardAlert, texts: AppTexts): string | null {
  const actionKey =
    alert.actionCode ??
    (alert.action === "Open Setup"
      ? "open_setup"
      : alert.action === "Open Logs"
        ? "open_logs"
        : null);

  switch (actionKey) {
    case "open_setup":
      return texts.alerts.openSetup;
    case "open_logs":
      return texts.alerts.openLogs;
    default:
      return null;
  }
}

function resolveAlertTitle(alert: DashboardAlert, texts: AppTexts): string {
  switch (alert.code) {
    case "configuration_incomplete":
      return texts.alerts.configurationIncomplete.title;
    case "codex_degraded":
      return texts.alerts.codexDegraded.title;
    case "claude_degraded":
      return texts.alerts.claudeDegraded.title;
    case "telegram_unavailable":
      return texts.alerts.telegramUnavailable.title;
    default:
      return alert.title;
  }
}

function resolveAlertDetail(alert: DashboardAlert, texts: AppTexts): string {
  switch (alert.code) {
    case "configuration_incomplete":
      if (alert.missingFields && alert.missingFields.length > 0) {
        return texts.alerts.configurationIncomplete.missingFields(
          alert.missingFields.join(", ")
        );
      }
      return texts.alerts.configurationIncomplete.missingFiles;
    case "codex_degraded":
      return texts.alerts.codexDegraded.detail;
    case "claude_degraded":
      return texts.alerts.claudeDegraded.detail;
    case "telegram_unavailable":
      return texts.alerts.telegramUnavailable.detail;
    default:
      return alert.detail;
  }
}

function renderAlert(
  alert: DashboardAlert,
  index: number,
  onOpenLogs: () => void,
  onOpenSetup: () => void,
  texts: AppTexts
) {
  const actionLabel = resolveAlertActionLabel(alert, texts);
  const actionKey =
    alert.actionCode ??
    (alert.action === "Open Setup"
      ? "open_setup"
      : alert.action === "Open Logs"
        ? "open_logs"
        : null);

  return (
    <div key={`${alert.title}-${index}`} className={`ow-inline-alert ${alertStyles[alert.level]}`}>
      <div className="ow-inline-alert-mark">
        {alert.level === "error" ? "!" : "i"}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900">{resolveAlertTitle(alert, texts)}</p>
        <p className="mt-1 text-xs leading-5 text-current/90">{resolveAlertDetail(alert, texts)}</p>
      </div>
      <div className="flex justify-end">
        {actionKey === "open_setup" && actionLabel && (
          <button
            onClick={onOpenSetup}
            className="ow-btn rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap hover:border-amber-200 hover:bg-amber-50/70"
          >
            {actionLabel}
          </button>
        )}
        {actionKey === "open_logs" && actionLabel && (
          <button
            onClick={onOpenLogs}
            className="ow-btn rounded-xl px-3 py-1.5 text-xs font-semibold whitespace-nowrap hover:border-rose-200 hover:bg-rose-50/70"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  );
}

function buildServiceControlStatus(state: DashboardState | null) {
  if (!state) {
    return null;
  }
  return {
    running: state.bot.process === "healthy",
    pid: state.bot.pid ?? null,
  };
}

function resolveProviders(state: DashboardState | null, texts: AppTexts): ProviderDashboardStatus[] {
  if (!state) {
    return [];
  }
  if (state.providers && state.providers.length > 0) {
    return state.providers;
  }
  return [
    {
      id: "codex",
      label: "Codex",
      description: texts.dashboard.codexDescription,
      managed: true,
      autostart: true,
      health: state.codex.health,
      port: state.codex.port ?? null,
      detail: state.codex.detail ?? null,
      transport: "stdio",
      liveTransport: "owner_bridge",
      controlMode: "app",
      bin: null,
    },
  ];
}

function describeProvider(provider: ProviderDashboardStatus, texts: AppTexts): string {
  if (provider.description) {
    return provider.description;
  }
  switch (provider.id) {
    case "codex":
      return texts.dashboard.codexDescription;
    case "claude":
      return texts.dashboard.claudeDescription;
    default:
      return `${texts.dashboard.ownerTransportLabel}: ${provider.transport ?? "-"}`;
  }
}

function providerDetail(provider: ProviderDashboardStatus, texts: AppTexts): string {
  if (!provider.managed) {
    return texts.dashboard.providerUnmanagedDetail;
  }
  if (!provider.autostart) {
    return texts.dashboard.providerAutostartDisabledDetail;
  }
  if (provider.id === "codex") {
    return provider.detail ?? texts.dashboard.codexFallbackDetail;
  }
  if (provider.id === "claude") {
    return provider.detail ?? texts.dashboard.claudeDescription;
  }
  return provider.detail ?? `${texts.dashboard.ownerTransportLabel}: ${provider.transport ?? "-"}`;
}

function providerAccent(provider: ProviderDashboardStatus) {
  if (provider.id === "codex") {
    return {
      icon: "border-violet-100 bg-violet-50 text-violet-600",
      bar: "bg-violet-500/70",
    };
  }
  return {
    icon: "border-slate-200 bg-slate-50 text-slate-700",
    bar: "bg-slate-400/70",
  };
}

function ProviderIcon({ provider }: { provider: ProviderDashboardStatus }) {
  if (provider.id === "codex") {
    return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>;
  }
  if (provider.id === "claude") {
    return <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm4.5 16.5c-2.485 0-4.5-2.015-4.5-4.5s2.015-4.5 4.5-4.5 4.5 2.015 4.5 4.5-2.015 4.5-4.5 4.5zm-9 0C5.015 16.5 3 14.485 3 12s2.015-4.5 4.5-4.5S12 9.515 12 12s-2.015 4.5-4.5 4.5z" /></svg>;
  }
  return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>;
}

function SettingSwitch({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-10 rounded-full transition-colors ${
        checked ? "bg-blue-500" : "bg-slate-300"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <span
        className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export function Dashboard({ onOpenLogs, onOpenSetup, onOpenSessions }: Props) {
  const { t } = useI18n();
  const { dashboardState, loading, error, refresh } = useDashboardState();
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [serviceAction, setServiceAction] = useState<ServiceAction | null>(null);

  const overall = getOverallStyles(t)[dashboardState?.overall ?? "unknown"];
  const controlStatus = buildServiceControlStatus(dashboardState);
  const providers = resolveProviders(dashboardState, t);
  const serviceBusy = serviceAction !== null;

  const handleProviderFlagsChange = async (
    provider: ProviderDashboardStatus,
    nextManaged: boolean,
    nextAutostart: boolean
  ) => {
    setSavingProviderId(provider.id);
    try {
      await invoke("set_provider_flags", {
        providerId: provider.id,
        managed: nextManaged,
        autostart: nextManaged && nextAutostart,
      });
      if (controlStatus?.running) {
        await invoke("service_restart");
      }
      window.setTimeout(() => {
        startTransition(() => {
          void refresh();
        });
      }, controlStatus?.running ? 1200 : 200);
    } catch (err) {
      console.error("Provider flag update error:", err);
      alert(String(err));
    } finally {
      setSavingProviderId(null);
    }
  };

  const handleServiceAction = async (nextAction: ServiceAction) => {
    setServiceAction(nextAction);
    try {
      if (nextAction === "restart") {
        await invoke("service_restart");
      } else if (nextAction === "stop") {
        await invoke("service_stop");
      } else {
        await invoke("service_start");
      }
      window.setTimeout(() => void refresh(), 800);
    } catch (err) {
      console.error("Service action error:", err);
      alert(String(err));
    } finally {
      setServiceAction(null);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className={`ow-page-frame rounded-[28px] px-5 py-5 md:px-6 md:py-6 ${overall.panel}`}>
        <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0">
            <div className="flex items-start gap-4">
              <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white/70 bg-white/85 shadow-sm">
                <svg className={`w-6 h-6 ${overall.badge.split(" ")[1]}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[24px] font-extrabold tracking-[-0.03em] text-gray-950">{overall.title}</h2>
                  <span className={`ow-badge rounded-full px-2.5 py-1 text-[10px] ${overall.badge}`}>
                    {dashboardState?.overall ?? "unknown"}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium text-slate-600">{overall.detail}</p>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-semibold">
                    {t.dashboard.snapshot}: {formatEpochAge(dashboardState?.generatedAtEpoch, t)}
                  </span>
                  {controlStatus?.pid && (
                    <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-mono font-semibold">
                      PID {controlStatus.pid}
                    </span>
                  )}
                  <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-semibold">
                    {controlStatus?.running ? "Running" : t.common.stopped}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button onClick={onOpenLogs} className="ow-btn rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white">
              {t.serviceControl?.logs ?? "Logs"}
            </button>
            <button
              onClick={() => void handleServiceAction(controlStatus?.running ? "stop" : "start")}
              disabled={serviceBusy || loading}
              className={`ow-btn rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50 ${
                controlStatus?.running
                  ? "text-rose-700 hover:border-rose-200 hover:bg-rose-50/80"
                  : "text-emerald-700 hover:border-emerald-200 hover:bg-emerald-50/80"
              }`}
            >
              {serviceBusy && serviceAction !== "restart"
                ? "..."
                : controlStatus?.running
                  ? (t.serviceControl?.stop ?? "Stop")
                  : (t.serviceControl?.start ?? "Start")}
            </button>
            <button
              onClick={() => void handleServiceAction("restart")}
              disabled={!controlStatus?.running || serviceBusy || loading}
              className="ow-btn-primary rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
            >
              {serviceAction === "restart" ? "..." : (t.serviceControl?.restart ?? "Restart")}
            </button>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-6">
          <div className="ow-page-frame rounded-[26px] p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">{t.dashboard.telegramBotTitle}</h3>
                <p className="mt-1 text-sm text-slate-500">{t.dashboard.snapshot}: {formatEpochAge(dashboardState?.generatedAtEpoch, t)}</p>
              </div>
              <TelegramBadge status={dashboardState?.bot.telegram ?? "unknown"} />
            </div>

            <div className="mt-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4">
              <div className="flex items-center gap-3">
                <div className="grid h-10 w-10 place-items-center rounded-2xl bg-blue-50 text-blue-600">
                  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.295-.6.295-.002 0-.003 0-.005 0l.213-3.054 5.56-5.022c.24-.213-.054-.334-.373-.121l-6.869 4.326-2.96-.924c-.64-.203-.658-.64.135-.954l11.566-4.458c.538-.196 1.006.128.832.94z"/></svg>
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900">{t.dashboard.telegramLabel}</p>
                  <p className="text-xs text-slate-500">{t.dashboard.activeThreads(dashboardState?.recentActivity?.activeThreadCount ?? 0)}</p>
                </div>
              </div>

              <div className="mt-4 grid gap-3">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{t.dashboard.activeWorkspace}</p>
                  <p className="mt-1 text-sm font-semibold text-gray-800">
                    {dashboardState?.recentActivity?.activeWorkspaceName ?? t.dashboard.noWorkspaceSelected ?? t.dashboard.noWorkspace}
                  </p>
                </div>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{t.dashboard.highlightedThreadLabel}</p>
                  <p className="mt-1 text-sm font-semibold text-gray-800">
                    {t.dashboard.activeThreads(dashboardState?.recentActivity?.activeThreadCount ?? 0)}
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div className="ow-page-frame rounded-[26px] p-5">
            <div className="mb-4">
              <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">{t.dashboard.quickActionsTitle}</h3>
            </div>

            <div className="space-y-3">
              <button onClick={onOpenSessions} className="group flex w-full items-center gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4 text-left transition-all hover:border-blue-200 hover:bg-blue-50/70">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-blue-100 text-blue-600">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z"></path></svg>
                </div>
                <div className="min-w-0">
                  <h4 className="font-semibold text-gray-900 group-hover:text-blue-800">{t.dashboard.openSessionsTitle}</h4>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{t.dashboard.openSessionsDescription}</p>
                </div>
              </button>

              <button onClick={onOpenSetup} className="group flex w-full items-center gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4 text-left transition-all hover:border-violet-200 hover:bg-violet-50/70">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-violet-100 text-violet-600">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path></svg>
                </div>
                <div className="min-w-0">
                  <h4 className="font-semibold text-gray-900 group-hover:text-violet-800">{t.dashboard.openSetupTitle}</h4>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{t.dashboard.openSetupDescription}</p>
                </div>
              </button>

              <button onClick={onOpenLogs} className="group flex w-full items-center gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4 text-left transition-all hover:border-amber-200 hover:bg-amber-50/70">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-amber-100 text-amber-600">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                </div>
                <div className="min-w-0">
                  <h4 className="font-semibold text-gray-900 group-hover:text-amber-800">{t.dashboard.openLogsTitle}</h4>
                  <p className="mt-1 text-xs leading-5 text-slate-500">{t.dashboard.openLogsDescription}</p>
                </div>
              </button>
            </div>
          </div>

          {dashboardState?.alerts && dashboardState.alerts.length > 0 && (
            <div className="ow-page-frame-soft rounded-[26px] p-5">
              <div className="mb-2">
                <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">{t.dashboard.alertsTitle}</h3>
              </div>
              <div className="ow-inline-alert-list">
                {dashboardState.alerts.map((alert, index) => renderAlert(alert, index, onOpenLogs, onOpenSetup, t))}
              </div>
            </div>
          )}

          {error && (
            <div className="ow-page-frame-soft rounded-[26px] p-5">
              <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">{t.dashboard.alertsTitle}</h3>
              <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50/85 px-4 py-3 text-sm text-rose-700">
                {t.dashboard.failedToLoad(error)}
              </div>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div className="flex items-end justify-between gap-4">
            <div>
              <h3 className="text-lg font-extrabold tracking-[-0.02em] text-gray-950">{t.dashboard.subsystemsTitle}</h3>
              <p className="mt-1 text-sm text-slate-500">{t.dashboard.subsystemsDescription}</p>
            </div>
            <button onClick={() => void refresh()} disabled={loading} className="ow-btn rounded-xl p-2 text-slate-600 hover:bg-white" title={t.common.refresh}>
              <svg className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
            </button>
          </div>

          <div className="space-y-4">
            {providers.map((provider) => {
              const providerBusy = savingProviderId === provider.id;
              const accent = providerAccent(provider);
              const statusStyle = getServiceStyles(t)[provider.health] ?? getServiceStyles(t).unknown;
              const unavailable = provider.health === "stopped" || !provider.managed;

              return (
                <div key={provider.id} className={`ow-page-frame rounded-[26px] p-5 ${unavailable ? "opacity-60 grayscale" : ""}`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex min-w-0 items-center gap-4">
                      <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border ${accent.icon}`}>
                        <ProviderIcon provider={provider} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">{provider.label ?? provider.id}</h4>
                          <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${statusStyle.badge}`}>
                            <span className={`h-1.5 w-1.5 rounded-full ${statusStyle.dot}`}></span>
                            {statusStyle.label}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-slate-500">{describeProvider(provider, t)}</p>
                      </div>
                    </div>
                    {providerBusy && (
                      <span className="text-xs font-semibold text-blue-600 animate-pulse">{t.common.saving}</span>
                    )}
                  </div>

                  <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200/70 bg-slate-50/75 p-4 md:grid-cols-3">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{t.dashboard.ownerTransportLabel}</p>
                      <p className="mt-1 text-sm font-mono text-gray-800">{provider.transport ?? "-"}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{provider.port ? (t.dashboard.portLabel ?? "Port") : "Status"}</p>
                      <p className="mt-1 text-sm text-gray-800">{provider.port ?? providerDetail(provider, t)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">{t.dashboard.binaryLabel}</p>
                      <p className="mt-1 truncate text-sm font-mono text-gray-800" title={provider.bin ?? "-"}>
                        {provider.bin ?? "-"}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
                    <div className={`h-1.5 w-16 rounded-full ${accent.bar}`}></div>
                    <div className="flex flex-wrap items-center gap-6">
                      <label className={`flex items-center gap-3 ${providerBusy || loading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                        <SettingSwitch
                          checked={provider.managed}
                          disabled={providerBusy || loading}
                          onChange={(checked) => {
                            void handleProviderFlagsChange(provider, checked, checked ? provider.autostart : false);
                          }}
                        />
                        <span className="text-sm font-semibold text-gray-700">{t.dashboard.managedLabel}</span>
                      </label>

                      <label className={`flex items-center gap-3 ${!provider.managed || providerBusy || loading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                        <SettingSwitch
                          checked={provider.managed && provider.autostart}
                          disabled={!provider.managed || providerBusy || loading}
                          onChange={(checked) => {
                            void handleProviderFlagsChange(provider, true, checked);
                          }}
                        />
                        <span className="text-sm font-semibold text-gray-700">{t.dashboard.autostartLabel}</span>
                      </label>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
