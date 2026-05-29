import { useI18n } from "../../i18n";
import type { CodexSession } from "../../types";

export function CodexSessionBadges({
  session,
  compact = false,
}: {
  session: CodexSession;
  compact?: boolean;
}) {
  const { t } = useI18n();
  const badges = [
    session.modelProvider ? t.sessions.providerBadge(session.modelProvider) : null,
    session.source ? t.sessions.sourceBadge(session.source) : null,
    session.isSmoke ? t.sessions.smokeBadge : null,
  ].filter((value): value is string => Boolean(value));

  if (badges.length === 0) {
    return null;
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "" : "mt-3"}`}>
      {badges.map((badge) => (
        <span
          key={badge}
          className="inline-flex items-center rounded-full border border-slate-200 bg-white/88 px-2.5 py-1 text-[10px] font-semibold tracking-[0.04em] text-slate-500"
        >
          {badge}
        </span>
      ))}
    </div>
  );
}
