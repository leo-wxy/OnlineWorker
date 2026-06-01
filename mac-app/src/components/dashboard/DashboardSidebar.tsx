import type { AppTexts } from "../../i18n";
import type { DashboardState } from "../../types";
import { formatEpochAge } from "./model";
import { TelegramBadge } from "./TelegramBadge";

interface Props {
  dashboardState: DashboardState | null;
  canOpenCodexTuiHost: boolean;
  texts: AppTexts;
  onOpenCodexTuiHost: () => void;
  onOpenLogs: () => void;
  onOpenSetup: () => void;
  onOpenSessions: () => void;
}

export function DashboardSidebar({
  dashboardState,
  canOpenCodexTuiHost,
  texts,
  onOpenCodexTuiHost,
  onOpenLogs,
  onOpenSetup,
  onOpenSessions,
}: Props) {
  return (
    <div className="space-y-6">
      <div className="ow-page-frame rounded-[26px] p-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">
              {texts.dashboard.telegramBotTitle}
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              {texts.dashboard.snapshot}: {formatEpochAge(dashboardState?.generatedAtEpoch, texts)}
            </p>
          </div>
          <TelegramBadge status={dashboardState?.bot.telegram ?? "unknown"} />
        </div>

        <div className="mt-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-blue-50 text-blue-600">
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.446 1.394c-.14.18-.357.295-.6.295-.002 0-.003 0-.005 0l.213-3.054 5.56-5.022c.24-.213-.054-.334-.373-.121l-6.869 4.326-2.96-.924c-.64-.203-.658-.64.135-.954l11.566-4.458c.538-.196 1.006.128.832.94z" />
              </svg>
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-gray-900">{texts.dashboard.telegramLabel}</p>
              <p className="text-xs text-slate-500">
                {texts.dashboard.activeThreads(dashboardState?.recentActivity?.activeThreadCount ?? 0)}
              </p>
            </div>
          </div>

          <div className="mt-4 grid gap-3">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
                {texts.dashboard.activeWorkspace}
              </p>
              <p className="mt-1 text-sm font-semibold text-gray-800">
                {dashboardState?.recentActivity?.activeWorkspaceName ??
                  texts.dashboard.noWorkspaceSelected ??
                  texts.dashboard.noWorkspace}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
                {texts.dashboard.highlightedThreadLabel}
              </p>
              <p className="mt-1 text-sm font-semibold text-gray-800">
                {texts.dashboard.activeThreads(dashboardState?.recentActivity?.activeThreadCount ?? 0)}
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="ow-page-frame rounded-[26px] p-5">
        <div className="mb-4">
          <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">
            {texts.dashboard.quickActionsTitle}
          </h3>
        </div>

        <div className="space-y-3">
          {canOpenCodexTuiHost && (
            <button
              onClick={onOpenCodexTuiHost}
              className="group flex w-full items-center gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4 text-left transition-all hover:border-emerald-200 hover:bg-emerald-50/70"
            >
              <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-emerald-100 text-emerald-600">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M8 9l3 3-3 3m5-6h3m-3 6h3M5 5h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2z"
                  ></path>
                </svg>
              </div>
              <div className="min-w-0">
                <h4 className="font-semibold text-gray-900 group-hover:text-emerald-800">
                  {texts.dashboard.openCodexTuiHostTitle}
                </h4>
                <p className="mt-1 text-xs leading-5 text-slate-500">
                  {texts.dashboard.openCodexTuiHostDescription}
                </p>
              </div>
            </button>
          )}

          <QuickAction
            tone="blue"
            title={texts.dashboard.openSessionsTitle}
            description={texts.dashboard.openSessionsDescription}
            onClick={onOpenSessions}
            iconPath="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z"
          />
          <QuickAction
            tone="violet"
            title={texts.dashboard.openSetupTitle}
            description={texts.dashboard.openSetupDescription}
            onClick={onOpenSetup}
            iconPath="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
          />
          <QuickAction
            tone="amber"
            title={texts.dashboard.openLogsTitle}
            description={texts.dashboard.openLogsDescription}
            onClick={onOpenLogs}
            iconPath="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </div>
      </div>
    </div>
  );
}

const quickActionTones = {
  blue: {
    hover: "hover:border-blue-200 hover:bg-blue-50/70",
    icon: "bg-blue-100 text-blue-600",
    title: "group-hover:text-blue-800",
  },
  violet: {
    hover: "hover:border-violet-200 hover:bg-violet-50/70",
    icon: "bg-violet-100 text-violet-600",
    title: "group-hover:text-violet-800",
  },
  amber: {
    hover: "hover:border-amber-200 hover:bg-amber-50/70",
    icon: "bg-amber-100 text-amber-600",
    title: "group-hover:text-amber-800",
  },
};

function QuickAction({
  description,
  iconPath,
  onClick,
  title,
  tone,
}: {
  description: string;
  iconPath: string;
  onClick: () => void;
  title: string;
  tone: keyof typeof quickActionTones;
}) {
  const styles = quickActionTones[tone];
  return (
    <button
      onClick={onClick}
      className={`group flex w-full items-center gap-4 rounded-2xl border border-slate-200/70 bg-slate-50/80 p-4 text-left transition-all ${styles.hover}`}
    >
      <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-2xl ${styles.icon}`}>
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={iconPath}></path>
        </svg>
      </div>
      <div className="min-w-0">
        <h4 className={`font-semibold text-gray-900 ${styles.title}`}>{title}</h4>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
    </button>
  );
}
