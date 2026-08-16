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
    dot: "bg-[var(--ow-purple)]",
    chip: "bg-[var(--ow-purple-soft)] text-[var(--ow-purple)] border-[var(--ow-purple)]",
    tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
    iconActive: "bg-[var(--ow-purple-soft)] text-[var(--ow-purple)]",
    workspaceActive: "border-[var(--ow-purple)] bg-[var(--ow-purple-soft)]",
    sessionActive: "border-[var(--ow-purple)] bg-[var(--ow-purple-soft)]",
  },
  {
    dot: "bg-[var(--ow-blue)]",
    chip: "bg-[var(--ow-blue-soft)] text-[var(--ow-blue)] border-[var(--ow-blue)]",
    tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
    iconActive: "bg-[var(--ow-blue-soft)] text-[var(--ow-blue)]",
    workspaceActive: "border-[var(--ow-blue)] bg-[var(--ow-blue-soft)]",
    sessionActive: "border-[var(--ow-blue)] bg-[var(--ow-blue-soft)]",
  },
  {
    dot: "bg-[var(--ow-green)]",
    chip: "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]",
    tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
    iconActive: "bg-[var(--ow-green-soft)] text-[var(--ow-green)]",
    workspaceActive: "border-[var(--ow-green)] bg-[var(--ow-green-soft)]",
    sessionActive: "border-[var(--ow-green)] bg-[var(--ow-green-soft)]",
  },
  {
    dot: "bg-[var(--ow-amber)]",
    chip: "bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)] border-[var(--ow-amber)]",
    tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
    iconActive: "bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)]",
    workspaceActive: "border-[var(--ow-amber)] bg-[var(--ow-amber-soft)]",
    sessionActive: "border-[var(--ow-amber)] bg-[var(--ow-amber-soft)]",
  },
  {
    dot: "bg-[var(--ow-muted)]",
    chip: "bg-[var(--ow-panel-soft)] text-[var(--ow-text)] border-[var(--ow-line)]",
    tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
    iconActive: "bg-[var(--ow-panel-soft)] text-[var(--ow-text)]",
    workspaceActive: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)]",
    sessionActive: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)]",
  },
];

const GENERIC_PROVIDER_UI = {
  label: "Provider",
  dot: "bg-[var(--ow-muted)]",
  chip: "bg-[var(--ow-panel-soft)] text-[var(--ow-text)] border-[var(--ow-line)]",
  tabActive: "bg-[var(--ow-panel)] text-[var(--ow-text)] [box-shadow:var(--ow-shadow-md)]",
  iconActive: "bg-[var(--ow-panel-soft)] text-[var(--ow-text)]",
  workspaceActive: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)]",
  sessionActive: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)]",
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
      ? "border-[var(--ow-red)] bg-[var(--ow-red-soft)] text-[var(--ow-error-text)]"
      : tone === "warning"
        ? "border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)]"
        : "border-[var(--ow-line-soft)] bg-[var(--ow-panel)] text-[var(--ow-muted)]";

  return (
    <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
      <div className={`ow-page-frame-soft flex max-w-sm flex-col items-center rounded-[28px] border px-6 py-7 text-center shadow-none ${toneClass}`}>
        <div className="mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-[var(--ow-panel)] text-[var(--ow-subtle)] shadow-sm">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" d="M8 10h.01M12 10h.01M16 10h.01M9 16h6M7 4h10a3 3 0 013 3v10a3 3 0 01-3 3H7a3 3 0 01-3-3V7a3 3 0 013-3z"></path>
          </svg>
        </div>
        <p className="text-sm font-medium leading-6">{message}</p>
      </div>
    </div>
  );
}
