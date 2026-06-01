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

      <div className="mt-4 grid gap-3 rounded-2xl border border-slate-200/70 bg-slate-50/75 p-4 md:grid-cols-3">
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
          <p className="mt-1 text-sm text-gray-800">
            {providerStatusValue(provider, providerDetail(provider, texts))}
          </p>
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
            {texts.dashboard.binaryLabel}
          </p>
          <p className="mt-1 truncate text-sm font-mono text-gray-800" title={provider.bin ?? "-"}>
            {provider.bin ?? "-"}
          </p>
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
