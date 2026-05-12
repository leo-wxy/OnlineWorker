import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchProviderUsageSummary } from "../components/session-browser/api";
import { StatePanel, getProviderUi } from "../components/session-browser/presentation";
import { useI18n } from "../i18n";
import type { ProviderUsageQuery, ProviderUsageSummary } from "../types";

const PROVIDER_TABS = ["codex", "claude"] as const;
const DEFAULT_RANGE_DAYS = 7;
type UsageProviderTab = typeof PROVIDER_TABS[number];

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatCost(value?: number | null) {
  if (value == null) {
    return "-";
  }
  return `$${value.toFixed(2)}`;
}

function chartBackground(providerId: UsageProviderTab) {
  if (providerId === "codex") {
    return "linear-gradient(180deg, rgba(139,92,246,0.95) 0%, rgba(167,139,250,0.82) 100%)";
  }
  return "linear-gradient(180deg, rgba(71,85,105,0.95) 0%, rgba(148,163,184,0.82) 100%)";
}

function isoDateOffset(daysAgo: number) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return date.toISOString().slice(0, 10);
}

function buildDefaultQuery(): ProviderUsageQuery {
  return {
    startDate: isoDateOffset(DEFAULT_RANGE_DAYS - 1),
    endDate: isoDateOffset(0),
  };
}

export function UsageBrowser() {
  const { t } = useI18n();
  const [activeProvider, setActiveProvider] = useState<UsageProviderTab>("codex");
  const [query, setQuery] = useState<ProviderUsageQuery>(() => buildDefaultQuery());
  const [draftQuery, setDraftQuery] = useState<ProviderUsageQuery>(() => buildDefaultQuery());
  const [summary, setSummary] = useState<ProviderUsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasLoadedRef = useRef(false);

  const loadSummary = useCallback(async (providerId: UsageProviderTab, query: ProviderUsageQuery) => {
    const hasLoadedBefore = hasLoadedRef.current;
    setLoading(!hasLoadedBefore);
    setRefreshing(hasLoadedBefore);
    try {
      const next = await fetchProviderUsageSummary(providerId, query);
      setSummary(next);
      setError(null);
      hasLoadedRef.current = true;
    } catch (loadError) {
      setSummary(null);
      setError((loadError as Error).message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadSummary(activeProvider, query);
  }, [activeProvider, loadSummary, query]);

  useEffect(() => {
    setDraftQuery(query);
  }, [query]);

  const providerUi = useMemo(() => {
    return getProviderUi(activeProvider, t.usage.providerTabs[activeProvider]);
  }, [activeProvider, t]);

  const totals = useMemo(() => {
    const days = summary?.days ?? [];
    return days.reduce(
      (acc, day) => {
        acc.totalTokens += day.totalTokens;
        acc.inputTokens += day.inputTokens;
        acc.outputTokens += day.outputTokens;
        return acc;
      },
      { totalTokens: 0, inputTokens: 0, outputTokens: 0 },
    );
  }, [summary]);

  const maxTokens = useMemo(() => {
    return Math.max(1, ...(summary?.days ?? []).map((day) => day.totalTokens));
  }, [summary]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-extrabold tracking-[-0.03em] text-gray-950">{t.usage.title}</h1>
          <p className="mt-1 text-sm text-slate-500">{t.usage.description}</p>
        </div>
        <button
          type="button"
          onClick={() => void loadSummary(activeProvider, query)}
          className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold"
          disabled={loading || refreshing}
        >
          {refreshing ? t.usage.applying : t.usage.refresh}
        </button>
      </div>

      <div className="ow-segment grid w-full grid-cols-2 rounded-2xl p-1">
        {PROVIDER_TABS.map((providerId) => {
          const ui = getProviderUi(providerId, t.usage.providerTabs[providerId]);
          const selected = providerId === activeProvider;
          return (
            <button
              key={providerId}
              type="button"
              onClick={() => setActiveProvider(providerId)}
              className={`rounded-xl px-3 py-2 text-sm font-bold transition-all ${
                selected ? "ow-segment-button-active" : "ow-segment-button hover:text-gray-700"
              }`}
            >
              {ui.label}
            </button>
          );
        })}
      </div>

      <div className="ow-page-frame-soft flex items-center justify-between rounded-2xl px-4 py-3">
        <div className="flex items-center gap-3">
          <span className={`h-2.5 w-2.5 rounded-full ${providerUi.dot}`}></span>
          <div>
            <p className="text-sm font-semibold text-gray-900">{providerUi.label}</p>
            <p className="text-xs text-slate-500">
              {summary ? t.usage.updatedAt(t.common.secondsAgo(Math.max(0, Math.floor(Date.now() / 1000 - summary.updatedAtEpoch)))) : t.common.noData}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            const next = buildDefaultQuery();
            setDraftQuery(next);
            setQuery(next);
          }}
          className="rounded-xl border border-[var(--ow-line-soft)] bg-white px-3 py-2 text-xs font-semibold text-slate-600"
        >
          {t.usage.rangeLast7Days}
        </button>
      </div>

      <div className="relative">
        {(loading || refreshing) && (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-[28px] bg-white/78 backdrop-blur-[2px]">
            <div className="ow-page-frame-soft flex items-center gap-3 rounded-2xl border border-[var(--ow-line-soft)] bg-white/96 px-4 py-3 text-sm font-semibold text-slate-700 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
              <span>{t.usage.applying}</span>
            </div>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
          <div className="ow-page-frame-soft rounded-2xl p-4">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-900">{t.usage.chartTitle}</p>
              <p className="text-xs text-slate-500">{query.startDate} - {query.endDate}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <label className="flex min-w-0 flex-col gap-1 text-xs font-semibold text-slate-500">
              <span>{t.usage.startDate}</span>
              <input
                type="date"
                value={draftQuery.startDate}
                max={draftQuery.endDate}
                onChange={(event) => setDraftQuery((current) => ({ ...current, startDate: event.target.value }))}
                className="rounded-xl border border-[var(--ow-line-soft)] bg-white px-3 py-2 text-sm font-medium text-gray-900"
              />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs font-semibold text-slate-500">
              <span>{t.usage.endDate}</span>
              <input
                type="date"
                value={draftQuery.endDate}
                min={draftQuery.startDate}
                onChange={(event) => setDraftQuery((current) => ({ ...current, endDate: event.target.value }))}
                className="rounded-xl border border-[var(--ow-line-soft)] bg-white px-3 py-2 text-sm font-medium text-gray-900"
              />
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={() => setQuery(draftQuery)}
                disabled={loading || refreshing || draftQuery.startDate > draftQuery.endDate}
                className="w-full rounded-xl border border-[var(--ow-line-soft)] bg-white px-3 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t.usage.applyFilters}
              </button>
            </div>
          </div>

          {!loading && !error && summary && !summary.unsupportedReason && summary.days.length > 0 && (
            <div className="mt-5">
              <div className="flex h-56 items-end gap-3 rounded-2xl bg-slate-50/80 px-4 pb-4 pt-6">
                {summary.days.slice().reverse().map((day) => {
                  const height = Math.max(12, Math.round((day.totalTokens / maxTokens) * 180));
                  return (
                    <div key={day.date} className="flex min-w-0 flex-1 flex-col items-center gap-2">
                      <div className="text-[11px] font-bold text-slate-400">{formatNumber(day.totalTokens)}</div>
                      <div
                        className="w-full rounded-t-xl shadow-[inset_0_1px_0_rgba(255,255,255,0.32)]"
                        style={{
                          height: `${height}px`,
                          background: chartBackground(activeProvider),
                        }}
                      />
                      <div className="text-[11px] font-medium text-slate-500">{day.date.slice(5)}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-1">
            <div className="ow-page-frame-soft rounded-2xl p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">{t.usage.summaryTotalTokens}</p>
              <p className="mt-2 text-2xl font-extrabold tracking-[-0.03em] text-gray-950">{formatNumber(totals.totalTokens)}</p>
            </div>
            <div className="ow-page-frame-soft rounded-2xl p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">{t.usage.summaryInputTokens}</p>
              <p className="mt-2 text-2xl font-extrabold tracking-[-0.03em] text-gray-950">{formatNumber(totals.inputTokens)}</p>
            </div>
            <div className="ow-page-frame-soft rounded-2xl p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.08em] text-slate-500">{t.usage.summaryOutputTokens}</p>
              <p className="mt-2 text-2xl font-extrabold tracking-[-0.03em] text-gray-950">{formatNumber(totals.outputTokens)}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {loading && <StatePanel message={t.usage.applying} />}
        {!loading && error && <StatePanel message={error} tone="error" />}
        {!loading && !error && summary?.unsupportedReason && (
          <StatePanel message={summary.unsupportedReason || t.usage.unavailable} tone="warning" />
        )}
        {!loading && !error && !summary?.unsupportedReason && (!summary || summary.days.length === 0) && (
          <StatePanel message={t.usage.empty} />
        )}
        {!loading && !error && summary && !summary.unsupportedReason && summary.days.length > 0 && (
          <div className="overflow-auto rounded-2xl border border-[var(--ow-line-soft)] bg-white">
            <table className="min-w-full border-collapse text-sm">
              <thead className="bg-slate-50/90">
                <tr className="text-left text-slate-500">
                  <th className="px-4 py-3 font-semibold">{t.usage.today}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.inputTokens}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.outputTokens}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.cacheCreationTokens}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.cacheReadTokens}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.totalTokens}</th>
                  <th className="px-4 py-3 font-semibold">{t.usage.totalCost}</th>
                </tr>
              </thead>
              <tbody>
                {summary.days.map((day) => (
                  <tr key={day.date} className="border-t border-slate-100 text-gray-800">
                    <td className="px-4 py-3 font-semibold">{day.date}</td>
                    <td className="px-4 py-3">{formatNumber(day.inputTokens)}</td>
                    <td className="px-4 py-3">{formatNumber(day.outputTokens)}</td>
                    <td className="px-4 py-3">{formatNumber(day.cacheCreationTokens)}</td>
                    <td className="px-4 py-3">{formatNumber(day.cacheReadTokens)}</td>
                    <td className="px-4 py-3">{formatNumber(day.totalTokens)}</td>
                    <td className="px-4 py-3">{formatCost(day.totalCostUsd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
