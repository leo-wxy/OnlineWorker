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
    <dialog ref={dialogRef} aria-labelledby="codex-confirm-title" aria-describedby="codex-confirm-description" className="ow-native-dialog ow-modal-panel w-[calc(100%_-_2rem)] max-w-md rounded-[24px] p-5 sm:p-6" onCancel={(event) => { event.preventDefault(); onClose(); }}>
        <h2 id="codex-confirm-title" className="text-lg font-extrabold text-[var(--ow-text)]">{title}</h2>
        <p id="codex-confirm-description" className="mt-2 text-sm leading-6 text-[var(--ow-muted)]">{description}</p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" className="ow-btn rounded-xl px-4 py-2.5 text-sm font-bold text-[var(--ow-muted)]" onClick={onClose}>取消</button>
          <button type="button" className={`rounded-xl px-4 py-2.5 text-sm font-bold text-[var(--ow-on-accent)] ${tone === "danger" ? "bg-[var(--ow-red)]" : "ow-btn-primary"}`} onClick={onConfirm}>{confirmLabel}</button>
        </div>
    </dialog>
  );
}
