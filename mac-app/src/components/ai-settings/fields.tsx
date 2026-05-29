export function Toggle({
  checked,
  disabled,
  labelledBy,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  labelledBy?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-10 shrink-0 rounded-full transition-colors ${
        checked ? "bg-blue-500" : "bg-slate-300"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <span
        className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export function TextField({
  id,
  label,
  value,
  type = "text",
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  type?: "text" | "password";
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
      <label htmlFor={id} className="text-sm font-bold text-gray-950">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="block w-full rounded-2xl border border-[var(--ow-line)] bg-white/92 px-4 py-3 text-sm font-medium text-gray-900 outline-none transition-colors placeholder:text-slate-400 focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
      />
    </div>
  );
}

export function NumberField({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
      <label htmlFor={id} className="text-sm font-bold text-gray-950">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={1}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Math.max(1, Number(event.target.value || 1)))}
        className="block w-full rounded-2xl border border-[var(--ow-line)] bg-white/92 px-4 py-3 text-sm font-medium text-gray-900 outline-none transition-colors focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
      />
    </div>
  );
}
