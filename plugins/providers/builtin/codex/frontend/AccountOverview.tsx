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

type CurrentAccountState = "matched" | "unmanaged" | "ambiguous" | "none";

export function AccountOverview({ api }: { api: AccountFeatureApi }) {
  const [accounts, setAccounts] = useState<AccountSummary[]>(loadAccountSummaries);
  const [currentState, setCurrentState] = useState<CurrentAccountState>("none");
  const [currentResolved, setCurrentResolved] = useState(false);
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
      const state = (value.current as { state?: unknown } | undefined)?.state;
      setCurrentState(state === "matched" || state === "unmanaged" || state === "ambiguous" ? state : "none");
      setCurrentResolved(true);
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
    <div className="codex-account-surface mx-auto flex min-h-0 w-full max-w-6xl min-w-0 flex-col gap-5">
      <header className="codex-account-page-header flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-extrabold tracking-[-0.03em] text-[var(--ow-text)]">{surface === "accounts" ? "账号管理" : "会话资产"}</h1>
          <p className="mt-1 text-sm text-[var(--ow-muted)]">{surface === "accounts" ? "管理本地 AI 服务账号。导入后需手动应用到对应客户端。" : "按工作目录管理本地会话资产。"}</p>
        </div>
        {surface === "accounts" && accounts.length > 0 && <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={Boolean(busy)} onClick={() => void run("refresh:all", async () => { pluginResult(await api.invoke("accounts.refresh")); setMessage("全部账号额度已刷新"); })}>{busy === "refresh:all" ? "刷新中…" : "刷新全部额度"}</button>
          <button type="button" className="ow-btn-primary rounded-xl px-4 py-2 text-sm font-bold" disabled={Boolean(busy)} onClick={() => setShowAdd(true)}>添加账号</button>
        </div>}
      </header>

      <div className="codex-account-tabs ow-segment flex w-full gap-1 overflow-x-auto rounded-2xl p-1" role="tablist" aria-label="账号管理功能">
          <button type="button" role="tab" aria-selected={surface === "accounts"} className={`rounded-xl px-4 py-2 text-sm font-bold ${surface === "accounts" ? "ow-segment-button-active" : "ow-segment-button"}`} onClick={() => setSurface("accounts")}>账号</button>
          <button type="button" role="tab" aria-selected={surface === "sessions"} className={`rounded-xl px-4 py-2 text-sm font-bold ${surface === "sessions" ? "ow-segment-button-active" : "ow-segment-button"}`} onClick={() => setSurface("sessions")}>会话资产</button>
      </div>

      {surface === "accounts" ? <>
        <section className="flex min-w-0 flex-col gap-4">
          {(message || error || currentState === "unmanaged" || currentState === "ambiguous") && <div className="codex-account-notices" aria-live="polite">
            {message && <p className="rounded-lg border border-[var(--ow-green)] bg-[var(--ow-green-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-green)]">{message}</p>}
            {error && <p role="alert" className="rounded-lg border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}
            {currentState === "unmanaged" && <p className="rounded-lg border border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-warning-text)]">检测到未托管的当前账号。导入后再决定是否加入账号库。</p>}
            {currentState === "ambiguous" && <p className="rounded-lg border border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-warning-text)]">当前凭据与多个账号匹配，无法确认正在使用的账号。</p>}
          </div>}

          {loading ? (
            <div aria-live="polite" className="codex-account-loading ow-page-frame-soft">正在加载账号…</div>
          ) : accounts.length === 0 ? (
            <section className="codex-account-empty ow-page-frame" aria-labelledby="codex-account-empty-title">
              <div className="codex-account-empty-copy">
                <p className="codex-account-empty-eyebrow">账号库为空</p>
                <h2 id="codex-account-empty-title">添加第一个账号</h2>
                <p>通过 OAuth 或 Token / JSON 导入凭据。导入后由你决定何时应用，不会自动切换当前账号。</p>
                <button type="button" className="ow-btn-primary codex-account-empty-action" disabled={Boolean(busy)} onClick={() => setShowAdd(true)}>添加账号</button>
              </div>
              <ol className="codex-account-empty-steps" aria-label="账号使用流程">
                <li>
                  <span aria-hidden="true">01</span>
                  <div><strong>安全导入</strong><p>选择 OAuth，或粘贴 Token / JSON。</p></div>
                </li>
                <li>
                  <span aria-hidden="true">02</span>
                  <div><strong>手动应用</strong><p>确认账号后，再应用到当前客户端。</p></div>
                </li>
              </ol>
            </section>
          ) : (
            <div className="codex-account-list flex min-w-0 flex-col gap-4">
              <div className="codex-account-list-toolbar">
                <div className="codex-account-toolbar-summary">
                  <h2 className="text-sm font-bold text-[var(--ow-text)]">账号库</h2>
                  <p className="mt-0.5 text-xs text-[var(--ow-muted)]">{accounts.length} 个账号 · {currentResolved ? `${accounts.filter((account) => account.isCurrent).length} 个正在使用` : error ? "当前账号状态未知" : "正在校准当前账号"}</p>
                </div>
                <div className="codex-account-toolbar-selection">
                  <label>
                    <input type="checkbox" aria-label="全选账号" checked={allSelected} onChange={(event) => setSelected(event.target.checked ? new Set(accounts.map((account) => account.id)) : new Set())} />
                    全选当前结果
                  </label>
                  <span>{selectedIds.length ? `已选择 ${selectedIds.length} 项` : "可批量导出或刷新额度"}</span>
                </div>
                <div className="codex-account-toolbar-actions">
                  {selectedIds.length > 0 && <button type="button" className="codex-account-text-action" disabled={Boolean(busy)} onClick={() => setSelected(new Set())}>清除选择</button>}
                  <button type="button" className="codex-account-text-action" disabled={Boolean(busy) || !selectedIds.length} onClick={() => void run("export", () => exportIds(selectedIds), false)}>{busy === "export" ? "正在导出…" : "导出选中"}</button>
                </div>
              </div>

              <div className="codex-account-list-body">
                {accounts.map((account) => {
                  const quota = account.quota;
                  const isCurrent = currentResolved && account.isCurrent;
                  const windows = [["primary", quotaLabel(quota?.primary, "短周期"), quota?.primary], ["secondary", quotaLabel(quota?.secondary, "周"), quota?.secondary]] as const;
                  return <article key={account.id} className={`codex-account-row ${isCurrent ? "codex-account-row-current" : ""}`}>
                    <div className="codex-account-row-identity">
                      <input aria-label={`选择 ${account.stableIdentityDisplay}`} type="checkbox" checked={selected.has(account.id)} onChange={(event) => setSelected((current) => { const next = new Set(current); event.target.checked ? next.add(account.id) : next.delete(account.id); return next; })} />
                      <div className="codex-account-identity-copy">
                        <div className="codex-account-identity-heading">
                          <h3>{account.stableIdentityDisplay}</h3>
                          <div className="codex-account-badges">
                            <span className={`codex-account-state ${isCurrent ? "codex-account-state-current" : "codex-account-state-idle"}`}><span aria-hidden="true" />{currentResolved ? isCurrent ? "当前账号" : "未应用" : "校准中"}</span>
                            {quota?.planType && <span className="codex-account-plan">{quota.planType}</span>}
                          </div>
                        </div>
                        <p className="codex-account-identity-meta"><span>{sourceLabel(account.source, account.authMode)}</span><span aria-hidden="true">·</span><span>{currentResolved ? isCurrent ? "Codex Home 使用中" : "等待应用" : "正在读取 Codex Home"}</span></p>
                      </div>
                    </div>

                    <div className="codex-account-row-quota">
                      <div className="codex-account-quota-heading"><span>额度概览</span><span>剩余</span></div>
                      {quota?.status === "ok" && windows.some(([, , window]) => window) ? <div className="codex-account-quota-grid">
                        {windows.map(([windowKey, label, window]) => {
                          if (!window) return null;
                          const remaining = Math.round(window.remainingPercent || 0);
                          return <div key={windowKey} className={`codex-account-quota-window ${remaining < 50 ? "codex-account-quota-warning" : "codex-account-quota-healthy"}`}>
                            <div className="codex-account-quota-window-heading"><span>{label}</span><strong className="codex-account-quota-value">{remaining}%</strong></div>
                            <progress className="codex-account-quota-progress" max="100" value={window.remainingPercent || 0} aria-label={`${label}剩余额度`} />
                            <p>{formatReset(window.resetAt)}</p>
                          </div>;
                        })}
                      </div> : <p className="codex-account-quota-empty">{quota?.status === "unsupported" ? "此认证方式不提供订阅额度" : quota?.status === "error" ? `额度暂不可用 · ${quota.errorCode || "未知错误"}` : "尚未刷新额度"}</p>}
                    </div>

                    <div className="codex-account-row-actions">
                      <button type="button" className={`codex-account-primary-action ${isCurrent ? "ow-btn" : "codex-account-apply"} rounded-xl px-4 py-2.5 text-sm font-bold`} disabled={Boolean(busy)} onClick={() => setPendingApply(account)}>{busy === `apply:${account.id}` ? "正在应用…" : isCurrent ? "重新应用" : "应用"}</button>
                      <div className="codex-account-secondary-actions">
                        <button type="button" className="codex-account-secondary-action" disabled={Boolean(busy)} onClick={() => void run(`refresh:${account.id}`, async () => { pluginResult(await api.invoke("accounts.refresh", { accountIds: [account.id] })); setMessage("额度已刷新"); })}>{busy === `refresh:${account.id}` ? "刷新中…" : "刷新"}</button>
                        <button type="button" className="codex-account-secondary-action" disabled={Boolean(busy)} onClick={() => void run("export", () => exportIds([account.id]), false)}>{busy === "export" ? "导出中…" : "导出"}</button>
                      </div>
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
          confirmLabel={pendingApply && currentResolved && pendingApply.isCurrent ? "重新应用" : "应用"}
          onClose={() => setPendingApply(null)}
          onConfirm={() => {
            const account = pendingApply;
            if (!account) return;
            setPendingApply(null);
            void run(`apply:${account.id}`, async () => {
              pluginResult(await api.invoke("accounts.apply", { accountId: account.id }));
              setMessage(currentResolved && account.isCurrent ? "当前账号已重新应用。" : "账号已应用到当前 Codex Home。");
            });
          }}
        />
        <AddAccountModal open={showAdd} api={api} onClose={() => setShowAdd(false)} onImported={async (closeModal = true) => { if (closeModal) setShowAdd(false); setMessage("账号已导入，尚未应用"); await load(); }} />
      </> : <SessionAssetsPage api={api} />}
    </div>
  );
}
