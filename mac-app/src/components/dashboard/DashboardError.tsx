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
      <h3 className="text-base font-extrabold tracking-[-0.02em] text-gray-950">
        {texts.dashboard.alertsTitle}
      </h3>
      <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50/85 px-4 py-3 text-sm text-rose-700">
        {texts.dashboard.failedToLoad(error)}
      </div>
    </div>
  );
}
