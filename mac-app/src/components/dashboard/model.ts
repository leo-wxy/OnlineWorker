import type { AppTexts } from "../../i18n";
import type {
  AlertLevel,
  ConnectionStatus,
  DashboardAlert,
  DashboardState,
  ProviderDashboardStatus,
  ServiceHealth,
  SystemHealth,
} from "../../types";

export type ServiceAction = "start" | "stop" | "restart";

export interface ServiceControlStatus {
  running: boolean;
  pid: number | null;
}

export interface OverallStyle {
  badge: string;
  panel: string;
  title: string;
  detail: string;
}

export interface ServiceStyle {
  badge: string;
  dot: string;
  label: string;
}

export interface TelegramStyle {
  badge: string;
  label: string;
}

export const alertStyles: Record<AlertLevel, string> = {
  warning: "ow-inline-alert-warning",
  error: "ow-inline-alert-error",
};

export function getOverallStyles(texts: AppTexts): Record<SystemHealth, OverallStyle> {
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

export function getServiceStyles(texts: AppTexts): Record<ServiceHealth, ServiceStyle> {
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

export function getTelegramStyles(texts: AppTexts): Record<ConnectionStatus, TelegramStyle> {
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

export function formatEpochAge(epoch: number | null | undefined, texts: AppTexts): string {
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

export function resolveAlertActionKey(alert: DashboardAlert): string | null {
  return (
    alert.actionCode ??
    (alert.action === "Open Setup"
      ? "open_setup"
      : alert.action === "Open Logs"
        ? "open_logs"
        : null)
  );
}

export function resolveAlertActionLabel(alert: DashboardAlert, texts: AppTexts): string | null {
  switch (resolveAlertActionKey(alert)) {
    case "open_setup":
      return texts.alerts.openSetup;
    case "open_logs":
      return texts.alerts.openLogs;
    default:
      return null;
  }
}

export function resolveAlertTitle(alert: DashboardAlert, texts: AppTexts): string {
  switch (alert.code) {
    case "configuration_incomplete":
      return texts.alerts.configurationIncomplete.title;
    case "provider_degraded":
      return alert.title;
    case "telegram_unavailable":
      return texts.alerts.telegramUnavailable.title;
    default:
      return alert.title;
  }
}

export function resolveAlertDetail(alert: DashboardAlert, texts: AppTexts): string {
  switch (alert.code) {
    case "configuration_incomplete":
      if (alert.missingFields && alert.missingFields.length > 0) {
        return texts.alerts.configurationIncomplete.missingFields(
          alert.missingFields.join(", ")
        );
      }
      return texts.alerts.configurationIncomplete.missingFiles;
    case "provider_degraded":
      return alert.detail;
    case "telegram_unavailable":
      return alert.detail || texts.alerts.telegramUnavailable.detail;
    default:
      return alert.detail;
  }
}

export function buildServiceControlStatus(
  state: DashboardState | null
): ServiceControlStatus | null {
  if (!state) {
    return null;
  }
  return {
    running: state.bot.process === "healthy",
    pid: state.bot.pid ?? null,
  };
}

export function resolveProviders(state: DashboardState | null): ProviderDashboardStatus[] {
  if (!state) {
    return [];
  }
  return state.providers ?? [];
}

export function canOpenProviderTuiHost(state: DashboardState | null): boolean {
  const recentActivity = state?.recentActivity;
  const activeTool = recentActivity?.activeSessionTool?.trim();
  const activeProvider = (state?.providers ?? []).find((provider) => provider.id === activeTool);
  const sidecarArgs = activeProvider?.tuiHost?.sidecarArgs ?? [];
  return (
    Boolean(activeTool) &&
    sidecarArgs.length > 0 &&
    Boolean(recentActivity?.activeWorkspacePath?.trim()) &&
    Boolean(recentActivity?.activeSessionId?.trim())
  );
}

export function describeProvider(provider: ProviderDashboardStatus, texts: AppTexts): string {
  if (provider.description) {
    return provider.description;
  }
  return `${texts.dashboard.ownerTransportLabel}: ${provider.transport ?? "-"}`;
}

export function providerDetail(provider: ProviderDashboardStatus, texts: AppTexts): string {
  if (!provider.managed) {
    return texts.dashboard.providerUnmanagedDetail;
  }
  if (!provider.autostart) {
    return texts.dashboard.providerAutostartDisabledDetail;
  }
  return provider.detail ?? `${texts.dashboard.ownerTransportLabel}: ${provider.transport ?? "-"}`;
}

const providerAccentOptions = [
  {
    icon: "border-violet-100 bg-violet-50 text-violet-600",
    bar: "bg-violet-500/70",
  },
  {
    icon: "border-sky-100 bg-sky-50 text-sky-600",
    bar: "bg-sky-500/70",
  },
  {
    icon: "border-emerald-100 bg-emerald-50 text-emerald-600",
    bar: "bg-emerald-500/70",
  },
  {
    icon: "border-amber-100 bg-amber-50 text-amber-700",
    bar: "bg-amber-500/70",
  },
  {
    icon: "border-slate-200 bg-slate-50 text-slate-700",
    bar: "bg-slate-400/70",
  },
];

function stableProviderIndex(providerId: string): number {
  let hash = 0;
  for (let i = 0; i < providerId.length; i += 1) {
    hash = (hash * 31 + providerId.charCodeAt(i)) >>> 0;
  }
  return hash % providerAccentOptions.length;
}

export function providerAccent(provider: ProviderDashboardStatus) {
  return providerAccentOptions[stableProviderIndex(provider.id)];
}
