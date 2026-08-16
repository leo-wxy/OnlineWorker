import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface ActionGuideDialogProps {
  open: boolean;
  title: string;
  description: string;
  steps: string[];
  command?: string;
  note?: string;
  copyLabel: string;
  copiedLabel: string;
  closeLabel: string;
  primaryLabel: string;
  secondaryLabel: string;
  busy?: boolean;
  onPrimary: () => void;
  onClose: () => void;
}

export function ActionGuideDialog({
  open,
  title,
  description,
  steps,
  command,
  note,
  copyLabel,
  copiedLabel,
  closeLabel,
  primaryLabel,
  secondaryLabel,
  busy = false,
  onPrimary,
  onClose,
}: ActionGuideDialogProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!open) {
      setCopied(false);
      return;
    }
    const previousActiveElement = document.activeElement as HTMLElement | null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    window.setTimeout(() => closeButtonRef.current?.focus(), 0);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      previousActiveElement?.focus();
    };
  }, [onClose, open]);

  if (!open) {
    return null;
  }

  const copyCommand = async () => {
    if (!command) {
      return;
    }
    await navigator.clipboard.writeText(command);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return createPortal(
    <div
      className="ow-modal-backdrop fixed inset-0 z-[1000] flex items-center justify-center p-4 sm:p-6"
      onClick={onClose}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="action-guide-title"
        aria-describedby="action-guide-description"
        className="ow-modal-panel w-full max-w-[540px] overflow-hidden rounded-[28px]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="px-6 pb-6 pt-5 sm:px-7 sm:pb-7 sm:pt-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <h2
                id="action-guide-title"
                className="text-xl font-extrabold tracking-[-0.025em] text-[var(--ow-text)]"
              >
                {title}
              </h2>
              <p
                id="action-guide-description"
                className="mt-2 text-sm leading-6 text-[var(--ow-muted)]"
              >
                {description}
              </p>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              className="ow-btn shrink-0 rounded-xl px-3 py-2 text-xs font-semibold text-[var(--ow-muted)] hover:bg-[var(--ow-panel)]"
            >
              {closeLabel}
            </button>
          </div>

          <ol className="mt-5 space-y-3">
            {steps.map((step, index) => (
              <li key={`${index}-${step}`} className="flex items-center gap-3">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[var(--ow-blue-soft)] text-xs font-extrabold text-[var(--ow-blue)] ring-1 ring-inset ring-[var(--ow-focus)]">
                  {index + 1}
                </span>
                <span className="text-sm font-semibold leading-6 text-[var(--ow-text)]">{step}</span>
              </li>
            ))}
          </ol>

          {command ? (
            <div className="mt-5 flex items-center gap-3 rounded-2xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] p-2.5 pl-4">
              <code className="min-w-0 flex-1 select-all font-mono text-base font-semibold text-[var(--ow-text)]">
                {command}
              </code>
              <button
                type="button"
                onClick={() => void copyCommand()}
                className="ow-btn shrink-0 rounded-xl px-3.5 py-2 text-xs font-bold text-[var(--ow-text)] hover:bg-[var(--ow-panel)]"
              >
                {copied ? copiedLabel : copyLabel}
              </button>
            </div>
          ) : null}

          {note ? (
            <p className="mt-4 rounded-2xl border border-[var(--ow-blue)] bg-[var(--ow-blue-soft)] px-4 py-3 text-xs font-medium leading-5 text-[var(--ow-blue)]">
              {note}
            </p>
          ) : null}

          <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:justify-end">
            <button
              type="button"
              disabled={busy}
              onClick={onPrimary}
              className="rounded-xl bg-[var(--ow-blue)] px-5 py-2.5 text-sm font-bold text-[var(--ow-on-accent)] [box-shadow:var(--ow-shadow-md)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60 disabled:brightness-100"
            >
              {primaryLabel}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ow-btn rounded-xl px-4 py-2.5 text-sm font-bold text-[var(--ow-muted)] hover:bg-[var(--ow-panel)]"
            >
              {secondaryLabel}
            </button>
          </div>
        </div>
      </section>
    </div>,
    document.body,
  );
}
