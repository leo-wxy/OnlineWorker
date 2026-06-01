import type { AppTexts } from "../../i18n";
import type { DashboardState } from "../../types";
import type { OverallStyle, ServiceAction, ServiceControlStatus } from "./model";
import { formatEpochAge } from "./model";

interface Props {
  dashboardState: DashboardState | null;
  loading: boolean;
  overall: OverallStyle;
  serviceAction: ServiceAction | null;
  serviceBusy: boolean;
  controlStatus: ServiceControlStatus | null;
  texts: AppTexts;
  onOpenLogs: () => void;
  onServiceAction: (action: ServiceAction) => void;
}

export function DashboardHero({
  dashboardState,
  loading,
  overall,
  serviceAction,
  serviceBusy,
  controlStatus,
  texts,
  onOpenLogs,
  onServiceAction,
}: Props) {
  return (
    <div className={`ow-page-frame rounded-[28px] px-5 py-5 md:px-6 md:py-6 ${overall.panel}`}>
      <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
        <div className="min-w-0">
          <div className="flex items-start gap-4">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-white/70 bg-white/85 shadow-sm">
              <svg
                className={`w-6 h-6 ${overall.badge.split(" ")[1]}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[24px] font-extrabold tracking-[-0.03em] text-gray-950">
                  {overall.title}
                </h2>
                <span className={`ow-badge rounded-full px-2.5 py-1 text-[10px] ${overall.badge}`}>
                  {dashboardState?.overall ?? "unknown"}
                </span>
              </div>
              <p className="mt-1 text-sm font-medium text-slate-600">{overall.detail}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-semibold">
                  {texts.dashboard.snapshot}: {formatEpochAge(dashboardState?.generatedAtEpoch, texts)}
                </span>
                {controlStatus?.pid && (
                  <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-mono font-semibold">
                    PID {controlStatus.pid}
                  </span>
                )}
                <span className="rounded-full border border-white/80 bg-white/70 px-3 py-1 font-semibold">
                  {controlStatus?.running ? "Running" : texts.common.stopped}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={onOpenLogs}
            className="ow-btn rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-white"
          >
            {texts.serviceControl?.logs ?? "Logs"}
          </button>
          <button
            onClick={() => onServiceAction(controlStatus?.running ? "stop" : "start")}
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
                ? (texts.serviceControl?.stop ?? "Stop")
                : (texts.serviceControl?.start ?? "Start")}
          </button>
          <button
            onClick={() => onServiceAction("restart")}
            disabled={!controlStatus?.running || serviceBusy || loading}
            className="ow-btn-primary rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {serviceAction === "restart" ? "..." : (texts.serviceControl?.restart ?? "Restart")}
          </button>
        </div>
      </div>
    </div>
  );
}
