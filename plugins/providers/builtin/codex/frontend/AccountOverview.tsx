import { useCallback, useEffect, useState } from "react";
import type { AccountFeatureApi } from "../../../../../mac-app/src/components/AccountFeatureHost";
import { AddAccountModal } from "./AddAccountModal";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import {
  loadAccountSummaries,
  parseAccountSummaries,
  saveAccountSummaries,
  type AccountSummary,
  type QuotaWindow,
} from "./accountSummaryStorage";
import { pluginResult } from "./plugin_result";
import { SessionAssetsPage } from "./SessionAssetsPage";

function quotaLabel(window: QuotaWindow | null | undefined, fallback: string) {
  const seconds = window?.windowSeconds || 0;
  if (seconds >= 7 * 86400) return `${Math.round(seconds / 604800)} 周`;
  if (seconds >= 86400) return `${Math.round(seconds / 86400)} 天`;
  if (seconds >= 3600) return `${Math.round(seconds / 3600)} 小时`;
  return fallback;
}

function formatReset(value: string | null | undefined) {
  if (!value) return "重置时间未知";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "重置时间未知" : `${new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date)} 重置`;
}

function authLabel(value: string) {
  if (value === "token") return "OAuth / Token";
  if (value === "apikey") return "API Key";
  return "Agent Identity";
}

function sourceLabel(source: string, authMode: string) {
  if (source === "oauth") return "OAuth";
  if (source === "token_json") return "Token / JSON";
  if (source === "api_key") return "API Key";
  if (source === "file_import") return "文件导入";
  return authLabel(authMode);
}

export function AccountOverview({ api }: { api: AccountFeatureApi }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>(loadAccountSummaries);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(accounts.length === 0);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [pendingApply, setPendingApply] = useState<AccountSummary | null>(null);
  const [surface, setSurface] = useState<"accounts" | "sessions">("accounts");

  const load = useCallback(async () => {
    setError("");
    try {
      const value = pluginResult(await api.invoke("accounts.list"));
      const next = parseAccountSummaries(value.accounts);
      setAccounts(next);
      saveAccountSummaries(next);
      setSelected((current) => new Set([...current].filter((id) => next.some((account) => account.id === id))));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "账号读取失败");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);

  const run = async (label: string, action: () => Promise<void>, reload = true) => {
    setBusy(label);
    setError("");
    setMessage("");
    try {
      await action();
      if (reload) await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "账号操作失败");
    } finally {
      setBusy("");
    }
  };

  const exportIds = async (ids: string[]) => {
    if (!ids.length) return;
    const handle = await api.chooseSave("codex-accounts.json");
    if (!handle) return;
    const value = pluginResult(await api.invoke("accounts.export", { accountIds: ids }, [{ handleId: handle.handleId, mode: "save" }]));
    const summary = value.export as { fileName?: string; count?: number } | undefined;
    setMessage(`已导出 ${summary?.count || ids.length} 个账号 · ${summary?.fileName || "codex-accounts.json"}`);
  };

  const selectedIds = [...selected];
  const allSelected = accounts.length > 0 && accounts.every((account) => selected.has(account.id));

  return (
    <div className="codex-account-surface flex min-h-0 w-full min-w-0 flex-col gap-5">
      <header className="codex-account-page-header flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-extrabold tracking-[-0.03em] text-[var(--ow-text)]">{surface === "accounts" ? "账号" : "会话资产"}</h1>
          <p className="mt-1 text-sm text-[var(--ow-muted)]">{surface === "accounts" ? "管理本地账号凭据。导入不会自动应用账号。" : "按工作目录管理当前 Codex Home 的本地会话。"}</p>
        </div>
        <div className="codex-account-page-actions flex flex-nowrap items-center justify-end gap-2">
          <div className="codex-account-tabs ow-segment grid grid-cols-2 rounded-xl p-1" role="tablist" aria-label="Codex 账号功能">
            <button type="button" role="tab" aria-selected={surface === "accounts"} className={`rounded-lg px-4 py-2 text-sm font-bold ${surface === "accounts" ? "ow-segment-button-active" : "ow-segment-button"}`} onClick={() => setSurface("accounts")}>账号</button>
            <button type="button" role="tab" aria-selected={surface === "sessions"} className={`rounded-lg px-4 py-2 text-sm font-bold ${surface === "sessions" ? "ow-segment-button-active" : "ow-segment-button"}`} onClick={() => setSurface("sessions")}>会话资产</button>
          </div>
        </div>
      </header>

      {surface === "accounts" ? <>
        <section className="flex min-w-0 flex-col gap-3">
          <div aria-live="polite">
            {message && <p className="rounded-lg border border-[var(--ow-green)] bg-[var(--ow-green-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-green)]">{message}</p>}
            {error && <p role="alert" className="rounded-lg border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}
          </div>

          {loading ? (
            <div aria-live="polite" className="ow-page-frame grid min-h-44 place-items-center rounded-xl text-sm text-[var(--ow-muted)]">正在加载账号…</div>
          ) : accounts.length === 0 ? (
            <div className="ow-page-frame grid min-h-52 place-items-center rounded-[24px] p-8 text-center">
              <div>
                <p className="text-base font-bold text-[var(--ow-text)]">暂无账号</p>
                <p className="mt-2 text-sm text-[var(--ow-muted)]">通过 OAuth 或 Token / JSON 添加第一个账号。</p>
                <button type="button" className="ow-btn-primary mt-5 rounded-xl px-4 py-2.5 text-sm font-bold" disabled={Boolean(busy)} onClick={() => setShowAdd(true)}>添加第一个账号</button>
              </div>
            </div>
          ) : (
            <div className="codex-account-list ow-page-frame min-w-0 overflow-hidden rounded-[24px]">
              <div className="codex-account-list-header flex flex-wrap items-center justify-between gap-4 px-5 py-4">
                <div>
                  <h2 className="text-sm font-bold text-[var(--ow-text)]">账号库</h2>
                  <p className="mt-1 text-xs text-[var(--ow-muted)]">{accounts.length} 个账号 · {accounts.filter((account) => account.isCurrent).length} 个正在使用</p>
                </div>
                <button type="button" className="ow-btn-primary rounded-xl px-4 py-2.5 text-sm font-bold" disabled={Boolean(busy)} onClick={() => setShowAdd(true)}>添加账号</button>
              </div>

              <div className="codex-account-list-toolbar flex flex-wrap items-center gap-3 px-5 py-2.5">
                <label className="flex items-center gap-2 text-xs font-semibold text-[var(--ow-text)]">
                  <input type="checkbox" aria-label="全选账号" checked={allSelected} onChange={(event) => setSelected(event.target.checked ? new Set(accounts.map((account) => account.id)) : new Set())} />
                  全选当前结果
                </label>
                <span className="text-xs text-[var(--ow-muted)]">{selectedIds.length ? `已选择 ${selectedIds.length} 项` : "可批量导出或刷新额度"}</span>
                <div className="codex-account-toolbar-actions ml-auto flex flex-wrap items-center gap-1">
                  {selectedIds.length > 0 && <button type="button" className="codex-account-text-action" disabled={Boolean(busy)} onClick={() => setSelected(new Set())}>清除选择</button>}
                  <button type="button" className="codex-account-text-action" disabled={Boolean(busy) || !selectedIds.length} onClick={() => void run("export", () => exportIds(selectedIds), false)}>{busy === "export" ? "正在导出…" : "导出选中"}</button>
                  <button type="button" className="codex-account-text-action" disabled={Boolean(busy) || !accounts.length} onClick={() => void run("refresh:all", async () => { pluginResult(await api.invoke("accounts.refresh")); setMessage("全部账号额度已刷新"); })}>{busy === "refresh:all" ? "刷新中…" : "刷新全部额度"}</button>
                </div>
              </div>

              <div className="codex-account-list-body">
                {accounts.map((account) => {
                  const quota = account.quota;
                  const windows = [[quotaLabel(quota?.primary, "短周期"), quota?.primary], [quotaLabel(quota?.secondary, "周"), quota?.secondary]] as const;
                  return <article key={account.id} className={`codex-account-row ${account.isCurrent ? "codex-account-row-current" : ""}`}>
                    <div className="codex-account-row-identity flex min-w-0 items-start gap-3">
                      <input className="mt-1" aria-label={`选择 ${account.stableIdentityDisplay}`} type="checkbox" checked={selected.has(account.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); event.target.checked ? next.add(account.id) : next.delete(account.id); return next; })} />
                      <div className="min-w-0 flex-1">
                        <div className="codex-account-identity-heading min-w-0">
                          <h3 className="min-w-0 truncate text-sm font-bold text-[var(--ow-text)]">{account.stableIdentityDisplay}</h3>
                          <span className={`codex-account-state ${account.isCurrent ? "codex-account-state-current" : "codex-account-state-idle"}`}><span aria-hidden="true" />{account.isCurrent ? "当前账号" : "未应用"}</span>
                        </div>
                        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs font-medium text-[var(--ow-muted)]">
                          <span>{sourceLabel(account.source, account.authMode)}</span>
                          {quota?.planType && <><span aria-hidden="true">·</span><span>{quota.planType}</span></>}
                        </p>
                        <p className="mt-1.5 text-xs leading-5 text-[var(--ow-subtle)]">{account.isCurrent ? "当前 Codex Home 正在使用" : "应用后写入当前 Codex Home"}</p>
                      </div>
                    </div>

                    <div className="codex-account-row-quota min-w-0">
                      {quota?.status === "ok" && windows.some(([, window]) => window) ? <div className="codex-account-quota-grid grid gap-4">
                        {windows.map(([label, window]) => window ? <div key={label} className="codex-account-quota-window min-w-0">
                          <div className="flex items-baseline justify-between gap-3"><span className="text-xs font-medium text-[var(--ow-muted)]">{label}</span><strong className="text-xs font-bold text-[var(--ow-text)]">{Math.round(window.remainingPercent || 0)}%</strong></div>
                          <progress className="codex-account-quota-progress mt-2 w-full" max="100" value={window.remainingPercent || 0} aria-label={`${label}剩余额度`} />
                          <p className="mt-1 truncate text-[11px] text-[var(--ow-subtle)]">{formatReset(window.resetAt)}</p>
                        </div> : null)}
                      </div> : <p className="codex-account-quota-empty text-xs leading-5 text-[var(--ow-muted)]">{quota?.status === "unsupported" ? "此认证方式不提供订阅额度" : quota?.status === "error" ? `额度暂不可用 · ${quota.errorCode || "未知错误"}` : "尚未刷新额度"}</p>}
                    </div>

                    <div className="codex-account-row-actions">
                      <button type="button" className={`codex-account-primary-action ${account.isCurrent ? "ow-btn" : "codex-account-apply"} rounded-lg px-3 py-2 text-xs font-bold`} disabled={Boolean(busy)} onClick={() => setPendingApply(account)}>{busy === `apply:${account.id}` ? "正在应用…" : account.isCurrent ? "重新应用" : "应用"}</button>
                      <button type="button" className="codex-account-text-action" disabled={Boolean(busy)} onClick={() => void run(`refresh:${account.id}`, async () => { pluginResult(await api.invoke("accounts.refresh", { accountIds: [account.id] })); setMessage("额度已刷新"); })}>{busy === `refresh:${account.id}` ? "正在刷新…" : "刷新"}</button>
                      <button type="button" className="codex-account-text-action" disabled={Boolean(busy)} onClick={() => void run("export", () => exportIds([account.id]), false)}>{busy === "export" ? "正在导出…" : "导出"}</button>
                    </div>
                  </article>;
                })}
              </div>
            </div>
          )}
        </section>

        <ConfirmActionDialog
          open={Boolean(pendingApply)}
          title="应用此账号？"
          description="这只会更新当前 Codex 凭据文件，不会停止、重启或重新连接任何进程。"
          confirmLabel={pendingApply?.isCurrent ? "重新应用" : "应用"}
          onClose={() => setPendingApply(null)}
          onConfirm={() => {
            const account = pendingApply;
            if (!account) return;
            setPendingApply(null);
            void run(`apply:${account.id}`, async () => {
              pluginResult(await api.invoke("accounts.apply", { accountId: account.id }));
              setMessage(account.isCurrent ? "当前账号已重新应用。" : "账号已应用到当前 Codex Home。");
            });
          }}
        />
        <AddAccountModal open={showAdd} api={api} onClose={() => setShowAdd(false)} onImported={async () => { setShowAdd(false); setMessage("账号已导入，尚未应用"); await load(); }} />
      </> : <SessionAssetsPage api={api} />}
    </div>
  );
}
