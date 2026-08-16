import type { AppTexts } from "../../i18n";
import type { ProviderDashboardStatus } from "../../types";
import { providerShowsPort, providerStatusValue } from "../../utils/dashboardProviderStatus.js";
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
  onOpenActionGuide: (guideId: string) => void;
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
  healthy: "bg-[var(--ow-green-soft)] text-[var(--ow-green)] ring-1 ring-inset ring-[var(--ow-green)]",
  warning: "bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)] ring-1 ring-inset ring-[var(--ow-amber)]",
  error: "bg-[var(--ow-red-soft)] text-[var(--ow-error-text)] ring-1 ring-inset ring-[var(--ow-red)]",
  neutral: "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)] ring-1 ring-inset ring-[var(--ow-line)]",
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
    const cleaned = segment
      .replace(/^[•\-]\s*/, "")
      .replace(/\s*·\s*$/, "")
      .trim();
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

function statusActionGuideId(
  provider: ProviderDashboardStatus,
  item: ParsedStatusItem
): string | null {
  if (
    provider.id === "codex" &&
    item.tone === "warning" &&
    item.label?.toLowerCase() === "codex hook ingress" &&
    item.badgeText.includes("待信任")
  ) {
    return "codex-hook-trust";
  }
  return null;
}

export function ProviderStatusList({
  loading,
  providers,
  savingProviderId,
  texts,
  onProviderFlagsChange,
  onRefresh,
  onOpenActionGuide,
}: Props) {
  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h3 className="text-lg font-extrabold tracking-[-0.02em] text-[var(--ow-text)]">
            {texts.dashboard.subsystemsTitle}
          </h3>
          <p className="mt-1 text-sm text-[var(--ow-muted)]">{texts.dashboard.subsystemsDescription}</p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="ow-btn rounded-xl p-2 text-[var(--ow-muted)] hover:bg-[var(--ow-panel)]"
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
            onOpenActionGuide={onOpenActionGuide}
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
  onOpenActionGuide,
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
  onOpenActionGuide: (guideId: string) => void;
}) {
  const accent = providerAccent(provider);
  const statusStyle = getServiceStyles(texts)[provider.health] ?? getServiceStyles(texts).unknown;
  const unavailable = provider.health === "stopped" || !provider.managed;
  const statusText = providerDetail(provider, texts);
  const statusItems = parseProviderStatusItems(statusText);
  const needsAction = statusItems.some((item) => statusActionGuideId(provider, item));

  return (
    <div className={`ow-page-frame rounded-[26px] p-5 ${unavailable ? "opacity-60 grayscale" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-4">
          <div className={`grid h-12 w-12 shrink-0 place-items-center rounded-2xl border ${accent.icon}`}>
            <ProviderIcon provider={provider} />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-base font-extrabold tracking-[-0.02em] text-[var(--ow-text)]">
                {provider.label ?? provider.id}
              </h4>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${statusStyle.badge}`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${statusStyle.dot}`}></span>
                {needsAction ? texts.dashboard.needsActionLabel : statusStyle.label}
              </span>
            </div>
            <p className="mt-1 text-sm text-[var(--ow-muted)]">{describeProvider(provider, texts)}</p>
          </div>
        </div>
        {providerBusy && (
          <span className="text-xs font-semibold text-[var(--ow-blue)] animate-pulse">
            {texts.common.saving}
          </span>
        )}
      </div>

      <div className="mt-4 grid gap-4 rounded-2xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] p-4 md:grid-cols-[minmax(0,9rem)_minmax(0,1.1fr)_minmax(0,1.35fr)]">
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--ow-subtle)]">
            {texts.dashboard.ownerTransportLabel}
          </p>
          <p className="mt-1 text-sm font-mono text-[var(--ow-text)]">{provider.transport ?? "-"}</p>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--ow-subtle)]">
            {providerShowsPort(provider) ? (texts.dashboard.portLabel ?? "Port") : "Status"}
          </p>
          <div className="mt-2 space-y-2.5">
            {providerShowsPort(provider) && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex items-center rounded-full bg-[var(--ow-blue-soft)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ow-blue)] ring-1 ring-inset ring-[var(--ow-focus)]">
                  {texts.dashboard.portLabel ?? "Port"}
                </span>
                <span className="text-sm font-mono text-[var(--ow-text)]">
                  {providerStatusValue(provider, statusText)}
                </span>
              </div>
            )}
            {statusItems.length > 0 ? (
              statusItems.map((item, index) => {
                const actionGuideId = statusActionGuideId(provider, item);
                return (
                  <div
                    key={`${provider.id}-status-${index}`}
                    className={`rounded-2xl px-3 py-2.5 ${statusToneStyles[item.tone]}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
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
                      {actionGuideId ? (
                        <button
                          type="button"
                          onClick={() => onOpenActionGuide(actionGuideId)}
                          className="shrink-0 rounded-lg bg-[var(--ow-panel)] px-2.5 py-1.5 text-xs font-bold text-[var(--ow-warning-text)] ring-1 ring-inset ring-[var(--ow-amber)] transition-colors hover:bg-[var(--ow-hover)]"
                        >
                          {texts.dashboard.viewGuide}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-sm leading-6 text-[var(--ow-text)]">{statusText}</p>
            )}
          </div>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--ow-subtle)]">
            {texts.dashboard.binaryLabel}
          </p>
          <div className="mt-2 rounded-xl bg-[var(--ow-panel)] px-3 py-2 ring-1 ring-inset ring-[var(--ow-line)]">
            <p
              className="whitespace-normal break-words [overflow-wrap:anywhere] text-[13px] leading-6 font-mono text-[var(--ow-text)] select-all"
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
            <span className="text-sm font-semibold text-[var(--ow-text)]">{texts.dashboard.managedLabel}</span>
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
            <span className="text-sm font-semibold text-[var(--ow-text)]">
              {texts.dashboard.autostartLabel}
            </span>
          </label>
        </div>
      </div>
    </div>
  );
}
