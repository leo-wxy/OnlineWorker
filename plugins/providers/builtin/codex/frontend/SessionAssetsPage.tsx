import { useCallback, useEffect, useMemo, useState } from "react";
import type { AccountFeatureApi } from "../../../../../mac-app/src/components/AccountFeatureHost";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { pluginResult } from "./plugin_result";

type SessionKind = "conversation" | "external" | "subagent" | "all";

interface SessionRow {
  sessionId: string;
  title: string;
  cwd?: string;
  updatedAt?: string;
}

interface UsageSummary {
  inputTokens?: number;
  cachedInputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  cost?: { status?: string };
}

interface SessionGroup {
  cwd: string;
  label: string;
  latestUpdatedAt?: string;
  sessions: SessionRow[];
}

function compactNumber(value: number | undefined) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
}

function groupLabel(cwd: string) {
  const parts = cwd.replace(/\\/g, "/").replace(/\/$/, "").split("/").filter(Boolean);
  return parts[parts.length - 1] || "未标注工作目录";
}

function relativeTime(value: string | undefined) {
  const timestamp = value ? new Date(value).getTime() : 0;
  if (!timestamp || Number.isNaN(timestamp)) return "时间未知";
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 3600) return `${Math.max(1, Math.floor(seconds / 60))} 分钟`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)} 天`;
  return `${Math.floor(seconds / 604800)} 周`;
}

function grouped(rows: SessionRow[]): SessionGroup[] {
  const values = new Map<string, SessionRow[]>();
  for (const session of rows) {
    const cwd = session.cwd || "";
    values.set(cwd, [...(values.get(cwd) || []), session]);
  }
  return [...values.entries()].map(([cwd, sessions]) => {
    sessions.sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")));
    return { cwd, label: groupLabel(cwd), latestUpdatedAt: sessions[0]?.updatedAt, sessions };
  }).sort((left, right) => String(right.latestUpdatedAt || "").localeCompare(String(left.latestUpdatedAt || "")));
}

function shortId(value: string) {
  return value.length > 20 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export function SessionAssetsPage({ api }: { api: AccountFeatureApi }) {
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<SessionKind>("conversation");
  const [trash, setTrash] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<"repair" | "trash" | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const value = pluginResult(await api.invoke("sessions.list", { query: search, kind, trash }), "会话操作失败");
      setSessions((value.sessions as SessionRow[]) || []);
      setSelected(new Set());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话读取失败");
    } finally {
      setLoading(false);
    }
  }, [api, kind, search, trash]);

  const loadUsage = useCallback(async () => {
    setUsageLoading(true);
    try {
      const value = pluginResult(await api.invoke("sessions.usage"), "会话操作失败");
      setUsage((value.usage30d as UsageSummary) || {});
    } catch {
      setUsage(null);
    } finally {
      setUsageLoading(false);
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { void loadUsage(); }, [loadUsage]);

  const run = async (action: () => Promise<Record<string, unknown> | null>, success: string, reload = true) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const actionResult = await action();
      if (!actionResult) return;
      const value = pluginResult(actionResult, "会话操作失败");
      const detail = (value.importResult || value.trash || value.restore || value.repair || value.export) as { count?: number; imported?: number } | undefined;
      const count = detail?.count ?? detail?.imported;
      setMessage(`${success}${typeof count === "number" ? ` · ${count} 条` : ""}`);
      if (reload) await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话操作失败");
    } finally {
      setBusy(false);
    }
  };

  const groups = useMemo(() => grouped(sessions), [sessions]);
  const ids = useMemo(() => [...selected], [selected]);
  const allSelected = sessions.length > 0 && sessions.every((item) => selected.has(item.sessionId));
  const metric = (value: number | undefined) => usageLoading ? "—" : usage ? compactNumber(value) : "不可用";

  const toggleIds = (targetIds: string[]) => setSelected((current) => {
    const next = new Set(current);
    const checked = targetIds.every((id) => next.has(id));
    for (const id of targetIds) checked ? next.delete(id) : next.add(id);
    return next;
  });

  const importZip = async () => {
    const handle = await api.chooseOpen();
    if (!handle) return null;
    return api.invoke("sessions.import", {}, [{ handleId: handle.handleId, mode: "open" }]);
  };

  const exportZip = async () => {
    const handle = await api.chooseSave("codex-sessions.zip");
    if (!handle) return null;
    return api.invoke("sessions.export", { sessionIds: ids }, [{ handleId: handle.handleId, mode: "save" }]);
  };

  return (
    <section className="ow-page-frame min-w-0 overflow-hidden rounded-[24px]">
      <div className="codex-session-metrics grid border-b border-[var(--ow-line-soft)]">
        <div className="px-4 py-3">
          <p className="text-sm font-extrabold text-[var(--ow-text)]">近 30 天</p>
          <p className="mt-0.5 text-[11px] font-semibold text-[var(--ow-blue)]">{usageLoading ? "正在统计" : "Codex 本地数据"}</p>
        </div>
        {[["输入", metric(usage?.inputTokens)], ["缓存", metric(usage?.cachedInputTokens)], ["输出", metric(usage?.outputTokens)], ["合计", metric(usage?.totalTokens)], ["费用", usageLoading ? "—" : usage?.cost?.status === "unavailable" ? "不可用" : "$0"]].map(([label, value]) => <div key={label} className="border-l border-[var(--ow-line-soft)] px-4 py-3"><span className="block text-[11px] text-[var(--ow-muted)]">{label}</span><strong className="mt-0.5 block text-sm text-[var(--ow-text)]">{value}</strong></div>)}
      </div>

      <form className="ow-toolbar flex flex-wrap gap-2 border-x-0 border-t-0 px-3 py-3 shadow-none" onSubmit={(event) => { event.preventDefault(); setSearch(query.trim()); }}>
        <label className="sr-only" htmlFor="codex-session-search">按标题搜索会话</label>
        <input id="codex-session-search" value={query} onChange={(event) => setQuery(event.target.value)} className="min-w-[220px] flex-1 rounded-xl border border-[var(--ow-line)] bg-[var(--ow-input)] px-3 py-2 text-sm text-[var(--ow-text)]" placeholder="搜索会话标题或工作目录" />
        {query && <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" onClick={() => { setQuery(""); setSearch(""); }}>清空</button>}
        <label className="sr-only" htmlFor="codex-session-kind">会话类型</label>
        <select id="codex-session-kind" value={kind} disabled={trash} onChange={(event) => setKind(event.target.value as SessionKind)} className="rounded-xl border border-[var(--ow-line)] bg-[var(--ow-input)] px-3 py-2 text-sm text-[var(--ow-text)]">
          <option value="conversation">对话</option><option value="external">外部</option><option value="subagent">子代理</option><option value="all">全部类型</option>
        </select>
        <button type="submit" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold">搜索</button>
        <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => void run(importZip, "会话资产已导入")}>导入 ZIP</button>
        <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy || trash} onClick={() => setPendingAction("repair")}>修复可见性</button>
        <button type="button" className={`rounded-xl px-3 py-2 text-sm font-semibold ${trash ? "ow-btn-primary" : "ow-btn"}`} disabled={busy} onClick={() => setTrash((value) => !value)}>{trash ? "返回当前会话" : "废纸篓"}</button>
        <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => { void load(); void loadUsage(); }}>刷新</button>
      </form>

      <div className="flex flex-wrap items-center gap-3 border-b border-[var(--ow-line-soft)] px-4 py-3">
        <label className="flex items-center gap-2 text-sm font-semibold text-[var(--ow-text)]">
          <input type="checkbox" aria-label="全选当前结果" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(sessions.map((item) => item.sessionId)))} />
          全选当前结果
        </label>
        <span className="text-xs text-[var(--ow-muted)]">{ids.length ? `已选择 ${ids.length} 项` : `${groups.length} 个工作目录 · ${sessions.length} 个会话`}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          {ids.length > 0 && <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => setSelected(new Set())}>清除选择</button>}
          <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy || !ids.length || trash} onClick={() => void run(exportZip, "会话资产已导出", false)}>导出选中</button>
          {!trash ? <button type="button" className="rounded-xl bg-[var(--ow-red)] px-3 py-2 text-sm font-semibold text-[var(--ow-on-accent)] disabled:opacity-40" disabled={busy || !ids.length} onClick={() => setPendingAction("trash")}>移到废纸篓</button> : <button type="button" className="ow-btn-primary rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy || !ids.length} onClick={() => void run(() => api.invoke("sessions.restore", { sessionIds: ids }), "会话已恢复")}>恢复</button>}
        </div>
      </div>

      <div aria-live="polite">
        {message && <p className="border-b border-[var(--ow-green)] bg-[var(--ow-green-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-green)]">{message}</p>}
        {error && <p role="alert" className="border-b border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}
      </div>

      <div className="flex items-center gap-3 border-b border-[var(--ow-line-soft)] bg-[var(--ow-panel-soft)] px-4 py-2.5">
        <span className="text-sm font-bold text-[var(--ow-text)]">{trash ? "废纸篓" : kind === "conversation" ? "当前对话" : kind === "subagent" ? "子代理" : kind === "external" ? "外部会话" : "全部类型"}</span>
        <span className="text-xs text-[var(--ow-muted)]">默认按工作目录折叠</span>
      </div>
      {loading ? <div aria-live="polite" className="grid min-h-44 place-items-center text-sm text-[var(--ow-muted)]">正在读取本地会话数据…</div> : groups.length === 0 ? <div className="grid min-h-44 place-items-center p-6 text-sm text-[var(--ow-muted)]">{search ? "没有匹配的会话标题。" : "暂无本地会话"}</div> : <div className="divide-y divide-[var(--ow-line-soft)]">
          {groups.map((group) => {
            const groupIds = group.sessions.map((session) => session.sessionId);
            const groupSelected = groupIds.every((id) => selected.has(id));
            return <div key={`${trash ? "trash" : "active"}-${group.cwd}`} className="codex-session-group grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-start px-4">
              <input className="mt-[15px]" type="checkbox" aria-label={`选择工作目录 ${group.label}`} checked={groupSelected} onChange={() => toggleIds(groupIds)} />
              <details className="min-w-0">
                <summary className="cursor-pointer py-3 pl-3 text-sm text-[var(--ow-text)] hover:bg-[var(--ow-hover)]">
                  <span className="codex-session-summary-content ml-2 inline-flex min-w-0 items-center gap-3 align-middle">
                    <span className="min-w-0 flex-1 truncate font-extrabold" title={group.cwd || group.label}>{group.label}</span>
                    <span className="shrink-0 text-xs text-[var(--ow-subtle)]">{group.sessions.length} 个对话</span>
                    <span className="w-16 shrink-0 text-right text-xs font-semibold text-[var(--ow-muted)]">{relativeTime(group.latestUpdatedAt)}</span>
                  </span>
                </summary>
                <div className="border-t border-[var(--ow-line-soft)] bg-[var(--ow-panel-soft)] py-1">
                {group.sessions.map((session) => <div key={session.sessionId} className="flex min-w-0 items-center gap-3 border-b border-[var(--ow-line-soft)] px-4 py-3 last:border-b-0 hover:bg-[var(--ow-hover)]">
                  <input type="checkbox" aria-label={`选择 ${session.title}`} checked={selected.has(session.sessionId)} onChange={() => toggleIds([session.sessionId])} />
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-bold text-[var(--ow-text)]">{session.title || "未命名会话"}</span><span className="mt-1 block truncate text-[11px] text-[var(--ow-subtle)]">会话 ID：{shortId(session.sessionId)}</span></span>
                  <span className="shrink-0 text-xs text-[var(--ow-muted)]">{relativeTime(session.updatedAt)}</span>
                </div>)}
                </div>
              </details>
            </div>;
          })}
      </div>}
      <ConfirmActionDialog
        open={Boolean(pendingAction)}
        title={pendingAction === "trash" ? "移到废纸篓？" : "开始修复可见性？"}
        description={pendingAction === "trash" ? "会话历史不会被永久删除，之后可以在废纸篓中恢复。" : "仅修复本地 Codex 会话索引的可见性，不会删除会话内容。"}
        confirmLabel={pendingAction === "trash" ? "移到废纸篓" : "开始修复"}
        tone={pendingAction === "trash" ? "danger" : "primary"}
        onClose={() => setPendingAction(null)}
        onConfirm={() => {
          const action = pendingAction;
          setPendingAction(null);
          if (action === "trash") {
            void run(() => api.invoke("sessions.trash", { sessionIds: ids }), "已移到废纸篓，可在废纸篓中恢复");
          } else if (action === "repair") {
            void run(() => api.invoke("sessions.repair"), "可见性修复完成");
          }
        }}
      />
    </section>
  );
}
