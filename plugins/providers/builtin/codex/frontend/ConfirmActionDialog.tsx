import { useEffect, useRef } from "react";

interface ConfirmActionDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  tone?: "primary" | "danger";
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmActionDialog({
  open,
  title,
  description,
  confirmLabel,
  tone = "primary",
  onConfirm,
  onClose,
}: ConfirmActionDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);

  return (
    <dialog ref={dialogRef} aria-labelledby="codex-confirm-title" aria-describedby="codex-confirm-description" className="codex-confirm-dialog ow-native-dialog ow-modal-panel w-[calc(100%_-_2rem)] max-w-md overflow-hidden rounded-[28px] p-0" onCancel={(event) => { event.preventDefault(); onClose(); }}>
      <div className="px-5 pb-5 pt-6 sm:px-6">
        <p className="codex-account-modal-kicker">确认操作</p>
        <h2 id="codex-confirm-title" className="mt-1 text-xl font-extrabold tracking-[-0.025em] text-[var(--ow-text)]">{title}</h2>
        <p id="codex-confirm-description" className="mt-4 rounded-2xl border border-[var(--ow-line-soft)] bg-[var(--ow-panel-soft)] px-4 py-3 text-sm leading-6 text-[var(--ow-muted)]">{description}</p>
      </div>
      <div className="flex flex-col-reverse gap-2 border-t border-[var(--ow-line-soft)] px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
        <button type="button" className="ow-btn rounded-xl px-4 py-2.5 text-sm font-bold text-[var(--ow-muted)]" onClick={onClose}>取消</button>
        <button type="button" className={`rounded-xl px-4 py-2.5 text-sm font-bold text-[var(--ow-on-accent)] ${tone === "danger" ? "bg-[var(--ow-red)] [box-shadow:var(--ow-shadow-md)]" : "ow-btn-primary"}`} onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}
