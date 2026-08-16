interface Props {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}

export function SettingSwitch({ checked, disabled, onChange }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-10 rounded-full transition-colors ${
        checked ? "bg-[var(--ow-blue)]" : "bg-[var(--ow-disabled-surface)]"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <span
        className={`absolute top-1 h-4 w-4 rounded-full bg-[var(--ow-panel)] shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  );
}
