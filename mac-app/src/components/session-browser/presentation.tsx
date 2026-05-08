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

export const PROVIDER_UI: Record<
  ServiceType,
  {
    label: string;
    dot: string;
    chip: string;
    tabActive: string;
    iconActive: string;
    workspaceActive: string;
    sessionActive: string;
  }
> = {
  codex: {
    label: "Codex",
    dot: "bg-violet-500",
    chip: "bg-violet-50 text-violet-700 border-violet-100",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-violet-50 text-violet-600",
    workspaceActive: "border-violet-200 bg-violet-50/72",
    sessionActive: "border-violet-200 bg-violet-50/70",
  },
  claude: {
    label: "Claude",
    dot: "bg-slate-500",
    chip: "bg-slate-100 text-slate-700 border-slate-200",
    tabActive: "bg-white text-gray-950 shadow-[0_10px_24px_rgba(15,23,42,0.08)]",
    iconActive: "bg-slate-100 text-slate-700",
    workspaceActive: "border-slate-200 bg-slate-100/80",
    sessionActive: "border-slate-200 bg-slate-100/76",
  },
};

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
  const ui = PROVIDER_UI[providerId] ?? GENERIC_PROVIDER_UI;
  return {
    ...ui,
    label: label || ui.label || providerId,
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
