import { useEffect, useRef, useState } from "react";
import type { AccountFeatureApi } from "../../../../../mac-app/src/components/AccountFeatureHost";
import { pluginResult } from "./plugin_result";


const TABS = ["OAuth 授权", "Token / JSON", "API Key", "导入"] as const;

export function AddAccountModal({ open, api, onClose, onImported }: { open: boolean; api: AccountFeatureApi; onClose: () => void; onImported: () => Promise<void> }) {
  const [tab, setTab] = useState<(typeof TABS)[number]>(TABS[0]);
  const [content, setContent] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [label, setLabel] = useState("");
  const [callbackUrl, setCallbackUrl] = useState("");
  const [loopbackHandle, setLoopbackHandle] = useState("");
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

  return (
    <dialog ref={dialogRef} aria-labelledby="add-codex-account-title" className="ow-native-dialog ow-modal-panel max-h-[90vh] w-[calc(100%_-_2rem)] max-w-2xl overflow-y-auto rounded-[28px] p-5 sm:p-7" onCancel={(event) => { event.preventDefault(); if (!busy) close(); }}>
        <div className="flex items-start justify-between gap-4">
          <div><h2 id="add-codex-account-title" className="text-xl font-extrabold text-[var(--ow-text)]">添加 Codex 账号</h2><p className="mt-1 text-sm text-[var(--ow-muted)]">导入只保存到账号库，不会自动切换当前账号。</p></div>
          <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-bold" disabled={busy} onClick={close}>关闭</button>
        </div>

        <div className="ow-segment mt-5 grid grid-cols-2 gap-1 rounded-2xl p-1 sm:grid-cols-4" role="tablist" aria-label="账号导入方式">
          {TABS.map((item) => <button key={item} type="button" role="tab" aria-selected={tab === item} className={`rounded-xl px-3 py-2 text-sm font-bold ${tab === item ? "ow-segment-button-active" : "ow-segment-button"}`} onClick={() => { setTab(item); setError(""); }}>{item}</button>)}
        </div>

        {error && <p role="alert" className="mt-4 rounded-2xl border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-3 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}

        <div className="mt-5">
          {tab === "OAuth 授权" && <div className="space-y-4"><p className="text-sm leading-6 text-[var(--ow-muted)]">在系统浏览器完成 OpenAI 授权。监听失败时可手动粘贴回调地址。</p><button type="button" disabled={busy} className="w-full rounded-xl bg-[var(--ow-blue)] px-4 py-3 text-sm font-bold text-[var(--ow-on-accent)] disabled:opacity-60" onClick={() => void run(startOAuth)}>在浏览器中授权</button><label className="block text-sm font-semibold text-[var(--ow-text)]">手动回调地址<input value={callbackUrl} onChange={(event) => setCallbackUrl(event.target.value)} className="mt-2 w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-3 py-2 text-sm" placeholder="http://127.0.0.1:1455/auth/callback?..." /></label><button type="button" disabled={busy || !callbackUrl.trim()} className="ow-btn w-full rounded-xl px-4 py-3 text-sm font-bold" onClick={() => void run(() => completeOAuth(callbackUrl.trim()))}>我已授权，继续</button></div>}
          {tab === "Token / JSON" && <div className="space-y-4"><label className="block text-sm font-semibold text-[var(--ow-text)]">账号 JSON<textarea value={content} onChange={(event) => setContent(event.target.value)} className="mt-2 min-h-48 w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] p-3 font-mono text-xs" placeholder="粘贴 Cockpit Tools 导出的账号对象或数组" /></label><button type="button" disabled={busy || !content.trim()} className="w-full rounded-xl bg-[var(--ow-blue)] px-4 py-3 text-sm font-bold text-[var(--ow-on-accent)] disabled:opacity-60" onClick={() => void run(async () => { pluginResult(await api.invoke("accounts.import", { content, source: "token_json" }), "导入失败"); await onImported(); })}>导入账号</button></div>}
          {tab === "API Key" && <div className="space-y-4"><label className="block text-sm font-semibold text-[var(--ow-text)]">API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="mt-2 w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-3 py-2" autoComplete="off" /></label><label className="block text-sm font-semibold text-[var(--ow-text)]">显示名称<input value={label} onChange={(event) => setLabel(event.target.value)} className="mt-2 w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-3 py-2" placeholder="API Key" /></label><button type="button" disabled={busy || !apiKey.trim()} className="w-full rounded-xl bg-[var(--ow-blue)] px-4 py-3 text-sm font-bold text-[var(--ow-on-accent)] disabled:opacity-60" onClick={() => void run(async () => { pluginResult(await api.invoke("accounts.import_api_key", { apiKey, label }), "导入失败"); setApiKey(""); await onImported(); })}>导入 API Key</button></div>}
          {tab === "导入" && <div className="space-y-4"><p className="text-sm leading-6 text-[var(--ow-muted)]">选择本地 `auth.json` 或 Cockpit Tools 导出的 JSON 文件。文件路径不会传给页面。</p><button type="button" disabled={busy} className="w-full rounded-xl bg-[var(--ow-blue)] px-4 py-3 text-sm font-bold text-[var(--ow-on-accent)] disabled:opacity-60" onClick={() => void run(async () => { const handle = await api.chooseOpen(); if (!handle) return; pluginResult(await api.invoke("accounts.import_file", {}, [{ handleId: handle.handleId, mode: "open" }]), "导入失败"); await onImported(); })}>选择文件导入</button></div>}
        </div>
    </dialog>
  );
}
