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
                className="text-xl font-extrabold tracking-[-0.025em] text-slate-950"
              >
                {title}
              </h2>
              <p
                id="action-guide-description"
                className="mt-2 text-sm leading-6 text-slate-500"
              >
                {description}
              </p>
            </div>
            <button
              ref={closeButtonRef}
              type="button"
              onClick={onClose}
              className="ow-btn shrink-0 rounded-xl px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-white"
            >
              {closeLabel}
            </button>
          </div>

          <ol className="mt-5 space-y-3">
            {steps.map((step, index) => (
              <li key={`${index}-${step}`} className="flex items-center gap-3">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-blue-50 text-xs font-extrabold text-blue-600 ring-1 ring-inset ring-blue-100">
                  {index + 1}
                </span>
                <span className="text-sm font-semibold leading-6 text-slate-800">{step}</span>
              </li>
            ))}
          </ol>

          {command ? (
            <div className="mt-5 flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 p-2.5 pl-4">
              <code className="min-w-0 flex-1 select-all font-mono text-base font-semibold text-slate-900">
                {command}
              </code>
              <button
                type="button"
                onClick={() => void copyCommand()}
                className="ow-btn shrink-0 rounded-xl px-3.5 py-2 text-xs font-bold text-slate-700 hover:bg-white"
              >
                {copied ? copiedLabel : copyLabel}
              </button>
            </div>
          ) : null}

          {note ? (
            <p className="mt-4 rounded-2xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs font-medium leading-5 text-blue-700">
              {note}
            </p>
          ) : null}

          <div className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:justify-end">
            <button
              type="button"
              disabled={busy}
              onClick={onPrimary}
              className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-bold text-white shadow-[0_10px_24px_rgba(37,99,235,0.22)] transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {primaryLabel}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="ow-btn rounded-xl px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-white"
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
