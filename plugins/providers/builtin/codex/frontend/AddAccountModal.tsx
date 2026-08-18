import { useEffect, useRef, useState } from "react";
import type { AccountFeatureApi } from "../../../../../mac-app/src/components/AccountFeatureHost";
import { pluginResult } from "./plugin_result";

const METHODS = [
  { id: "oauth", label: "OAuth" },
  { id: "token", label: "Token / JSON" },
] as const;

type MethodId = (typeof METHODS)[number]["id"];

export function AddAccountModal({ open, api, onClose, onImported }: { open: boolean; api: AccountFeatureApi; onClose: () => void; onImported: () => Promise<void> }) {
  const [method, setMethod] = useState<MethodId>("oauth");
  const [content, setContent] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [loopbackHandle, setLoopbackHandle] = useState("");
  const [showFallback, setShowFallback] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (open && !dialog?.open) dialog?.showModal();
    if (!open && dialog?.open) dialog.close();
  }, [open]);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : "导入失败"); } finally { setBusy(false); }
  };

  const completeOAuth = async (url: string) => {
    const result = await api.invoke("oauth.complete", { callbackUrl: url });
    pluginResult(result, "导入失败");
    await onImported();
  };

  const startOAuth = async () => {
    const loopback = await api.beginLoopback(1455, "/auth/callback", 5 * 60 * 1000);
    setLoopbackHandle(loopback.handleId);
    const started = await api.invoke("oauth.start", { redirectUri: loopback.redirectUri });
    pluginResult(started, "导入失败");
    const authorizationUrl = started.authorizationUrl;
    if (typeof authorizationUrl !== "string") throw new Error("OAuth 授权地址无效");
    await api.openBrowser(authorizationUrl);
    const result = await api.awaitLoopback(loopback.handleId);
    setLoopbackHandle("");
    if (result.status === "completed" && result.callbackUrl) {
      await completeOAuth(result.callbackUrl);
    } else {
      setShowFallback(true);
      setError("未收到浏览器回调，可粘贴完整回调地址继续。");
    }
  };

  const close = () => {
    if (loopbackHandle) {
      void api.cancelLoopback(loopbackHandle);
      void api.invoke("oauth.cancel");
    }
    onClose();
  };

  const submitPrimary = () => {
    if (method === "oauth") {
      void run(startOAuth);
      return;
    }
    void run(async () => {
      pluginResult(await api.invoke("accounts.import", { content, source: "token_json" }), "导入失败");
      await onImported();
    });
  };

  const primaryDisabled = busy
    || (method === "token" && !content.trim());
  const primaryLabel = busy
    ? (method === "oauth" ? "正在等待浏览器授权…" : "正在导入账号…")
    : method === "oauth"
      ? "在浏览器中继续"
      : "导入账号";

  const moveTabFocus = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? METHODS.length - 1
        : (index + (event.key === "ArrowRight" ? 1 : -1) + METHODS.length) % METHODS.length;
    const next = METHODS[nextIndex];
    setMethod(next.id);
    setError("");
    requestAnimationFrame(() => document.getElementById(`add-account-${next.id}-tab`)?.focus());
  };

  return (
    <dialog ref={dialogRef} aria-labelledby="add-codex-account-title" aria-describedby="add-codex-account-description" aria-modal="true" className="codex-account-modal ow-native-dialog ow-modal-panel max-h-[90vh] overflow-hidden rounded-[24px] p-0" onCancel={(event) => { event.preventDefault(); if (!busy) close(); }}>
      <div className="codex-account-modal-header flex items-start justify-between gap-4 px-5 pb-4 pt-5 sm:px-6 sm:pt-6">
        <div className="min-w-0">
          <h2 id="add-codex-account-title" className="text-lg font-bold tracking-[-0.02em] text-[var(--ow-text)]">添加账号</h2>
          <p id="add-codex-account-description" className="mt-1 text-sm leading-5 text-[var(--ow-muted)]">选择一种方式，将凭据安全地加入本地账号库。</p>
        </div>
        <button type="button" aria-label="关闭添加账号弹窗" className="codex-account-modal-close shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-semibold" disabled={busy} onClick={close}>关闭</button>
      </div>

      <div className="codex-account-modal-tabs flex overflow-x-auto border-b border-[var(--ow-line-soft)] px-5 sm:px-6" role="tablist" aria-label="账号导入方式">
        {METHODS.map((item, index) => <button key={item.id} id={`add-account-${item.id}-tab`} type="button" role="tab" aria-controls={`add-account-${item.id}-panel`} aria-selected={method === item.id} tabIndex={method === item.id ? 0 : -1} className={`codex-account-modal-tab ${method === item.id ? "codex-account-modal-tab-active" : ""}`} disabled={busy} onKeyDown={(event) => moveTabFocus(event, index)} onClick={() => { setMethod(item.id); setError(""); }}>{item.label}</button>)}
      </div>

      <div className="codex-account-modal-body overflow-y-auto px-5 py-5 sm:px-6">
        {error && <p role="alert" className="mb-4 rounded-xl border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-3 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}

        {method === "oauth" && (
          <section id="add-account-oauth-panel" role="tabpanel" aria-labelledby="add-account-oauth-tab" className="codex-account-modal-mode">
            <p className="codex-account-modal-kicker">推荐方式</p>
            <h3 className="mt-1 text-base font-bold text-[var(--ow-text)]">使用浏览器授权</h3>
            <p className="mt-2 text-sm leading-6 text-[var(--ow-muted)]">我们会打开系统浏览器完成 OpenAI 授权，并自动接收本地回调。账号导入后不会自动切换。</p>
            <details className="codex-account-modal-fallback mt-5 rounded-xl" open={showFallback} onToggle={(event) => setShowFallback(event.currentTarget.open)}>
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-[var(--ow-text)]">没有收到回调？</summary>
              <div className="border-t border-[var(--ow-line-soft)] px-4 pb-4 pt-3">
                <p className="text-xs leading-5 text-[var(--ow-muted)]">粘贴浏览器最终打开的完整回调 URL，继续完成导入。</p>
                <label className="mt-3 block text-xs font-semibold text-[var(--ow-text)]">回调 URL
                  <input type="url" value={callbackUrl} onChange={(event) => setCallbackUrl(event.target.value)} className="codex-account-field mt-2 w-full rounded-lg px-3 py-2.5 text-sm" placeholder="http://127.0.0.1:1455/auth/callback?..." autoComplete="off" spellCheck={false} />
                </label>
                <div className="mt-3 flex justify-end">
                  <button type="button" disabled={busy || !callbackUrl.trim()} className="ow-btn rounded-lg px-3 py-2 text-xs font-bold" onClick={() => void run(() => completeOAuth(callbackUrl.trim()))}>使用回调 URL</button>
                </div>
              </div>
            </details>
          </section>
        )}

        {method === "token" && (
          <section id="add-account-token-panel" role="tabpanel" aria-labelledby="add-account-token-tab" className="codex-account-modal-mode">
            <h3 className="text-base font-bold text-[var(--ow-text)]">粘贴 Token 或账号 JSON</h3>
            <p className="mt-2 text-sm leading-6 text-[var(--ow-muted)]">内容只在本地完成结构与身份校验，不会发送到其他服务。</p>
            <label className="mt-4 block text-xs font-semibold text-[var(--ow-text)]">Token / 账号 JSON
              <textarea value={content} onChange={(event) => setContent(event.target.value)} className="codex-account-field mt-2 min-h-36 w-full resize-y rounded-lg p-3 font-mono text-xs leading-5" placeholder="粘贴账号对象或数组" spellCheck={false} />
            </label>
          </section>
        )}

      </div>

      <div className="codex-account-modal-footer flex flex-col gap-3 border-t border-[var(--ow-line-soft)] px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p role="status" className="min-h-5 text-xs text-[var(--ow-muted)]">{busy ? primaryLabel : ""}</p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row">
          <button type="button" className="ow-btn rounded-xl px-4 py-2.5 text-sm font-semibold" disabled={busy} onClick={close}>取消</button>
          <button type="button" className="ow-btn-primary rounded-xl px-4 py-2.5 text-sm font-bold" disabled={primaryDisabled} onClick={submitPrimary}>{primaryLabel}</button>
        </div>
      </div>
    </dialog>
  );
}
