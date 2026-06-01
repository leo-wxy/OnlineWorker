import type { AppTexts } from "../../i18n";
import type { DashboardAlert } from "../../types";
import {
  alertStyles,
  resolveAlertActionKey,
  resolveAlertActionLabel,
  resolveAlertDetail,
  resolveAlertTitle,
} from "./model";

interface Props {
  alerts: DashboardAlert[];
  onOpenLogs: () => void;
  onOpenSetup: () => void;
  texts: AppTexts;
}

function DashboardAlertItem({
  alert,
  index,
  onOpenLogs,
  onOpenSetup,
  texts,
}: {
  alert: DashboardAlert;
  index: number;
  onOpenLogs: () => void;
  onOpenSetup: () => void;
  texts: AppTexts;
}) {
  const actionLabel = resolveAlertActionLabel(alert, texts);
  const actionKey = resolveAlertActionKey(alert);

  return (
    <div key={`${alert.title}-${index}`} className={`ow-inline-alert ${alertStyles[alert.level]}`}>
      <div className="ow-inline-alert-mark">{alert.level === "error" ? "!" : "i"}</div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900">{resolveAlertTitle(alert, texts)}</p>
        <p className="mt-1 text-xs leading-5 text-current/90">
          {resolveAlertDetail(alert, texts)}
        </p>
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

export function DashboardAlerts({ alerts, onOpenLogs, onOpenSetup, texts }: Props) {
  if (alerts.length === 0) {
    return null;
  }

  return (
    <div className="ow-page-frame-soft rounded-[26px] p-5">
      <div className="mb-2">
        <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">
          {texts.dashboard.alertsTitle}
        </h3>
      </div>
      <div className="ow-inline-alert-list">
        {alerts.map((alert, index) => (
          <DashboardAlertItem
            key={`${alert.title}-${index}`}
            alert={alert}
            index={index}
            onOpenLogs={onOpenLogs}
            onOpenSetup={onOpenSetup}
            texts={texts}
          />
        ))}
      </div>
    </div>
  );
}
