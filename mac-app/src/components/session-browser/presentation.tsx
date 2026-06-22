export type ServiceType = string;

export type UnifiedSession = {
  id: string;
  type: ServiceType;
  workspace: string;
  title: string;
  archived: boolean;
  raw: any;
};

export type ArchiveFilter = "active" | "archived";
export type ProviderFilter = ServiceType;

const PROVIDER_UI_STYLES = [
  {
    dot: "bg-violet-500",
    chip: "bg-violet-50 text-violet-700 border-violet-100",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-violet-50 text-violet-600",
    workspaceActive: "border-violet-200 bg-violet-50/72",
    sessionActive: "border-violet-200 bg-violet-50/70",
  },
  {
    dot: "bg-sky-500",
    chip: "bg-sky-50 text-sky-700 border-sky-100",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-sky-50 text-sky-600",
    workspaceActive: "border-sky-200 bg-sky-50/72",
    sessionActive: "border-sky-200 bg-sky-50/70",
  },
  {
    dot: "bg-emerald-500",
    chip: "bg-emerald-50 text-emerald-700 border-emerald-100",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-emerald-50 text-emerald-600",
    workspaceActive: "border-emerald-200 bg-emerald-50/72",
    sessionActive: "border-emerald-200 bg-emerald-50/70",
  },
  {
    dot: "bg-amber-500",
    chip: "bg-amber-50 text-amber-700 border-amber-100",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-amber-50 text-amber-700",
    workspaceActive: "border-amber-200 bg-amber-50/72",
    sessionActive: "border-amber-200 bg-amber-50/70",
  },
  {
    dot: "bg-slate-500",
    chip: "bg-slate-100 text-slate-700 border-slate-200",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-slate-100 text-slate-700",
    workspaceActive: "border-slate-200 bg-slate-100/80",
    sessionActive: "border-slate-200 bg-slate-100/76",
  },
];

const GENERIC_PROVIDER_UI = {
  label: "Provider",
  dot: "bg-slate-500",
  chip: "bg-slate-100 text-slate-700 border-slate-200",
  tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
  iconActive: "bg-slate-100 text-slate-700",
  workspaceActive: "border-slate-200 bg-slate-100/80",
  sessionActive: "border-slate-200 bg-slate-100/76",
};

export function getProviderUi(providerId: ServiceType, label?: string | null) {
  const hash = providerId
    .split("")
    .reduce((value, char) => ((value * 31) + char.charCodeAt(0)) >>> 0, 0);
  const ui = providerId ? PROVIDER_UI_STYLES[hash % PROVIDER_UI_STYLES.length] : GENERIC_PROVIDER_UI;
  return {
    ...GENERIC_PROVIDER_UI,
    ...ui,
    label: label || providerId || GENERIC_PROVIDER_UI.label,
  };
}

export function StatePanel({
  message,
  tone = "muted",
}: {
  message: string;
  tone?: "muted" | "warning" | "error";
}) {
  const toneClass =
    tone === "error"
      ? "border-rose-200/80 bg-rose-50/90 text-rose-700"
      : tone === "warning"
        ? "border-amber-200/80 bg-amber-50/90 text-amber-700"
        : "border-[var(--ow-line-soft)] bg-white/86 text-slate-500";

  return (
    <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
      <div className={`ow-page-frame-soft flex max-w-sm flex-col items-center rounded-[28px] border px-6 py-7 text-center shadow-none ${toneClass}`}>
        <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-white/80 text-slate-400 shadow-sm">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M8 10h.01M12 10h.01M16 10h.01M9 16h6M7 4h10a3 3 0 013 3v10a3 3 0 01-3 3H7a3 3 0 01-3-3V7a3 3 0 013-3z"></path>
          </svg>
        </div>
        <p className="text-sm font-medium leading-6">{message}</p>
      </div>
    </div>
  );
}
