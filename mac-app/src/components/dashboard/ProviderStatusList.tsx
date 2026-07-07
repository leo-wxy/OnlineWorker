import type { AppTexts } from "../../i18n";
import type { ProviderDashboardStatus } from "../../types";
import { providerShowsPort } from "../../utils/dashboardProviderStatus.js";
import {
  describeProvider,
  getServiceStyles,
  providerAccent,
  providerDetail,
} from "./model";
import { ProviderIcon } from "./ProviderIcon";
import { SettingSwitch } from "./SettingSwitch";

interface Props {
  loading: boolean;
  providers: ProviderDashboardStatus[];
  savingProviderId: string | null;
  texts: AppTexts;
  onProviderFlagsChange: (
    provider: ProviderDashboardStatus,
    nextManaged: boolean,
    nextAutostart: boolean
  ) => void;
  onRefresh: () => void;
}

type StatusTone = "healthy" | "warning" | "error" | "neutral";

interface ParsedStatusItem {
  label: string | null;
  tone: StatusTone;
  icon: string | null;
  badgeText: string;
  note: string | null;
}

const statusToneStyles: Record<StatusTone, string> = {
  healthy: "bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-100",
  warning: "bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-100",
  error: "bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-100",
  neutral: "bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200",
};

function parseStatusTone(value: string): { tone: StatusTone; icon: string | null; content: string } {
  const trimmed = value.trim();
  if (trimmed.startsWith("✅")) {
    return {
      tone: "healthy",
      icon: "✅",
      content: trimmed.replace(/^✅\s*/, "").trim(),
    };
  }
  if (trimmed.startsWith("⚠️")) {
    return {
      tone: "warning",
      icon: "⚠️",
      content: trimmed.replace(/^⚠️\s*/, "").trim(),
    };
  }
  if (trimmed.startsWith("❌")) {
    return {
      tone: "error",
      icon: "❌",
      content: trimmed.replace(/^❌\s*/, "").trim(),
    };
  }
  return {
    tone: "neutral",
    icon: null,
    content: trimmed,
  };
}

function parseProviderStatusItems(detail: string | null | undefined): ParsedStatusItem[] {
  const raw = detail?.trim();
  if (!raw) {
    return [];
  }

  const segments = raw
    .replace(/\r/g, "")
    .replace(/\n+/g, "\n")
    .replace(/\s*•\s*/g, "\n• ")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  return segments.map((segment) => {
    const cleaned = segment.replace(/^[•\-]\s*/, "").trim();
    const match = cleaned.match(/^([^:：]+?)\s*[:：]\s*(.+)$/);
    const label = match ? match[1].trim() : null;
    const rawValue = match ? match[2].trim() : cleaned;
    const parsedTone = parseStatusTone(rawValue);
    const detailMatch = parsedTone.content.match(/^([^:：]+?)\s*[:：]\s*(.+)$/);

    return {
      label,
      tone: parsedTone.tone,
      icon: parsedTone.icon,
      badgeText: detailMatch ? detailMatch[1].trim() : parsedTone.content,
      note: detailMatch ? detailMatch[2].trim() : null,
    };
  });
}

function formatStatusBadgeText(item: ParsedStatusItem): string {
  if (item.label && item.badgeText) {
    return `${item.label} ${item.badgeText}`;
  }
  return item.label ?? item.badgeText;
}

export function ProviderStatusList({
  loading,
  providers,
  savingProviderId,
  texts,
  onProviderFlagsChange,
  onRefresh,
}: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h3 className="text-lg font-extrabold tracking-[-0.02em] text-gray-950">
            {texts.dashboard.subsystemsTitle}
          </h3>
          <p className="mt-1 text-sm text-slate-500">{texts.dashboard.subsystemsDescription}</p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="ow-btn rounded-xl p-2 text-slate-600 hover:bg-white"
          title={texts.common.refresh}
        >
          <svg
            className={`w-4 h-4 ${loading ? "animate-spin" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            ></path>
          </svg>
        </button>
      </div>

      <div className="space-y-4">
        {providers.map((provider) => (
          <ProviderStatusCard
            key={provider.id}
            loading={loading}
            provider={provider}
            providerBusy={savingProviderId === provider.id}
            texts={texts}
            onProviderFlagsChange={onProviderFlagsChange}
          />
        ))}
      </div>
    </div>
  );
}

function ProviderStatusCard({
  loading,
  provider,
  providerBusy,
  texts,
  onProviderFlagsChange,
}: {
  loading: boolean;
  provider: ProviderDashboardStatus;
  providerBusy: boolean;
  texts: AppTexts;
  onProviderFlagsChange: (
    provider: ProviderDashboardStatus,
    nextManaged: boolean,
    nextAutostart: boolean
  ) => void;
}) {
  const accent = providerAccent(provider);
  const statusStyle = getServiceStyles(texts)[provider.health] ?? getServiceStyles(texts).unknown;
  const unavailable = provider.health === "stopped" || !provider.managed;
  const statusText = providerDetail(provider, texts);
  const statusItems = parseProviderStatusItems(statusText);

  return (
    <div className={`ow-page-frame rounded-[26px] p-5 ${unavailable ? "opacity-60 grayscale" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border ${accent.icon}`}>
            <ProviderIcon provider={provider} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">
                {provider.label ?? provider.id}
              </h4>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${statusStyle.badge}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${statusStyle.dot}`}></span>
                {statusStyle.label}
              </span>
            </div>
            <p className="mt-1 text-sm text-slate-500">{describeProvider(provider, texts)}</p>
          </div>
        </div>
        {providerBusy && (
          <span className="text-xs font-semibold text-blue-600 animate-pulse">
            {texts.common.saving}
          </span>
        )}
      </div>

      <div className="mt-4 grid gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/75 p-4 md:grid-cols-[minmax(0,9rem)_minmax(0,1.1fr)_minmax(0,1.35fr)]">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
            {texts.dashboard.ownerTransportLabel}
          </p>
          <p className="mt-1 text-sm font-mono text-gray-800">{provider.transport ?? "-"}</p>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
            {providerShowsPort(provider) ? (texts.dashboard.portLabel ?? "Port") : "Status"}
          </p>
          <div className="mt-2 space-y-2.5">
            {providerShowsPort(provider) && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-sky-50 px-2.5 py-1 text-[11px] font-semibold text-sky-700 ring-1 ring-inset ring-sky-100">
                  {texts.dashboard.portLabel ?? "Port"}
                </span>
                <span className="text-sm font-mono text-gray-800">{provider.port}</span>
              </div>
            )}
            {statusItems.length > 0 ? (
              statusItems.map((item, index) => (
                <div
                  key={`${provider.id}-status-${index}`}
                  className={`rounded-2xl px-3 py-2.5 ${statusToneStyles[item.tone]}`}
                >
                  <div className="flex items-start gap-1.5 text-[13px] font-semibold leading-5">
                    {item.icon ? <span>{item.icon}</span> : null}
                    <span className="min-w-0">{formatStatusBadgeText(item)}</span>
                  </div>
                  {item.note ? (
                    <span className="mt-1 block text-[13px] leading-5 opacity-80">
                      {item.note}
                    </span>
                  ) : null}
                </div>
              ))
            ) : (
              <p className="text-sm leading-6 text-gray-800">{statusText}</p>
            )}
          </div>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
            {texts.dashboard.binaryLabel}
          </p>
          <div className="mt-2 rounded-xl bg-white/80 px-3 py-2 ring-1 ring-inset ring-slate-200/80">
            <p
              className="whitespace-normal break-words [overflow-wrap:anywhere] text-[13px] leading-6 font-mono text-gray-800 select-all"
              title={provider.bin ?? "-"}
            >
              {provider.bin ?? "-"}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
        <div className={`h-1.5 w-16 rounded-full ${accent.bar}`}></div>
        <div className="flex flex-wrap items-center gap-6">
          <label
            className={`flex items-center gap-3 ${
              providerBusy || loading ? "cursor-not-allowed opacity-60" : "cursor-pointer"
            }`}
          >
            <SettingSwitch
              checked={provider.managed}
              disabled={providerBusy || loading}
              onChange={(checked) => {
                onProviderFlagsChange(provider, checked, checked ? provider.autostart : false);
              }}
            />
            <span className="text-sm font-semibold text-gray-700">{texts.dashboard.managedLabel}</span>
          </label>

          <label
            className={`flex items-center gap-3 ${
              !provider.managed || providerBusy || loading
                ? "cursor-not-allowed opacity-60"
                : "cursor-pointer"
            }`}
          >
            <SettingSwitch
              checked={provider.managed && provider.autostart}
              disabled={!provider.managed || providerBusy || loading}
              onChange={(checked) => {
                onProviderFlagsChange(provider, true, checked);
              }}
            />
            <span className="text-sm font-semibold text-gray-700">
              {texts.dashboard.autostartLabel}
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
