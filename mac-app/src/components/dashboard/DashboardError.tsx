import type { AppTexts } from "../../i18n";

interface Props {
  error: string | null;
  texts: AppTexts;
}

export function DashboardError({ error, texts }: Props) {
  if (!error) {
    return null;
  }

  return (
    <div className="ow-page-frame-soft rounded-[26px] p-5">
      <h3 className="text-base font-extrabold tracking-[-0.02em] text-[var(--ow-text)]">
        {texts.dashboard.alertsTitle}
      </h3>
      <div className="mt-3 rounded-2xl border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-3 text-sm text-[var(--ow-error-text)]">
        {texts.dashboard.failedToLoad(error)}
      </div>
    </div>
  );
}
