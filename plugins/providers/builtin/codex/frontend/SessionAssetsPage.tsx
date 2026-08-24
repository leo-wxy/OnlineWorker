import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

let cachedUsage: UsageSummary | null = null;

function resultMessage(value: Record<string, unknown>) {
  const importResult = value.importResult as { items?: Array<{ status?: string }>; imported?: number } | undefined;
  if (importResult) {
    const items = Array.isArray(importResult.items) ? importResult.items : [];
    const imported = importResult.imported ?? items.filter((item) => item.status === "imported").length;
    const skipped = items.filter((item) => item.status === "skipped").length;
    const conflict = items.filter((item) => item.status === "conflict").length;
    return `会话导入完成 · 新增 ${imported} · 跳过 ${skipped} · 冲突 ${conflict}`;
  }
  const exported = value.export as { fileName?: string; count?: number } | undefined;
  if (exported) return `已导出 ${exported.count ?? 0} 条会话${exported.fileName ? ` · ${exported.fileName}` : ""}`;
  const trash = value.trash as { count?: number } | undefined;
  if (trash) return `已将 ${trash.count ?? 0} 条会话移到废纸篓`;
  const restore = value.restore as { count?: number } | undefined;
  if (restore) return `已恢复 ${restore.count ?? 0} 条会话`;
  const repair = value.repair as { rowsChanged?: number; rolloutsChanged?: number } | undefined;
  if (repair) return `可见性修复完成 · 索引 ${repair.rowsChanged ?? 0} · 会话 ${repair.rolloutsChanged ?? 0}`;
  return "会话操作完成";
}

function compactNumber(value: number) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
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
  const [usage, setUsage] = useState<UsageSummary | null>(() => cachedUsage);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<SessionKind>("conversation");
  const [trash, setTrash] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(usage === null);
  const [busy, setBusy] = useState(false);
  const [pendingAction, setPendingAction] = useState<"repair" | "trash" | null>(null);
  const [pickerGroup, setPickerGroup] = useState<SessionGroup | null>(null);
  const [pickerQuery, setPickerQuery] = useState("");
  const [draftSelected, setDraftSelected] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [usageError, setUsageError] = useState("");
  const pickerDialogRef = useRef<HTMLDialogElement>(null);

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
    setUsageError("");
    try {
      const value = pluginResult(await api.invoke("sessions.usage"), "会话操作失败");
      const next = (value.usage30d as UsageSummary) || {};
      setUsage(next);
      cachedUsage = next;
    } catch (reason) {
      setUsageError(reason instanceof Error ? reason.message : "用量统计失败，请重试");
    } finally {
      setUsageLoading(false);
    }
  }, [api]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!loading) void loadUsage(); }, [loading, loadUsage]);
  useEffect(() => {
    const dialog = pickerDialogRef.current;
    if (!dialog) return;
    if (pickerGroup && !dialog.open) dialog.showModal();
    if (!pickerGroup && dialog.open) dialog.close();
  }, [pickerGroup]);

  const run = async (action: () => Promise<Record<string, unknown> | null>, reload = true, refreshUsage = false) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const actionResult = await action();
      if (!actionResult) return;
      const value = pluginResult(actionResult, "会话操作失败");
      setMessage(resultMessage(value));
      if (reload) await load();
      if (refreshUsage) void loadUsage();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "会话操作失败");
    } finally {
      setBusy(false);
    }
  };

  const groups = useMemo(() => grouped(sessions), [sessions]);
  const ids = useMemo(() => [...selected], [selected]);
  const allSelected = sessions.length > 0 && sessions.every((item) => selected.has(item.sessionId));
  const pickerSessions = useMemo(() => {
    if (!pickerGroup) return [];
    const needle = pickerQuery.trim().toLocaleLowerCase();
    if (!needle) return pickerGroup.sessions;
    return pickerGroup.sessions.filter((session) => [session.title, session.sessionId]
      .some((value) => value.toLocaleLowerCase().includes(needle)));
  }, [pickerGroup, pickerQuery]);
  const pickerAllSelected = pickerSessions.length > 0 && pickerSessions.every((item) => draftSelected.has(item.sessionId));
  const metric = (value: number | undefined) => usageLoading && !usage ? "—" : typeof value === "number" ? compactNumber(value) : "不可用";

  const openSessionPicker = (group: SessionGroup) => {
    const groupIds = group.sessions.map((session) => session.sessionId);
    setDraftSelected(new Set(groupIds.filter((id) => selected.has(id))));
    setPickerQuery("");
    setPickerGroup(group);
  };

  const closeSessionPicker = () => {
    setPickerGroup(null);
    setPickerQuery("");
  };

  const toggleDraftIds = (targetIds: string[]) => setDraftSelected((current) => {
    const next = new Set(current);
    const checked = targetIds.every((id) => next.has(id));
    for (const id of targetIds) checked ? next.delete(id) : next.add(id);
    return next;
  });

  const confirmSessionPicker = () => {
    if (!pickerGroup) return;
    const groupIds = new Set(pickerGroup.sessions.map((session) => session.sessionId));
    setSelected((current) => {
      const next = new Set([...current].filter((id) => !groupIds.has(id)));
      for (const id of draftSelected) next.add(id);
      return next;
    });
    closeSessionPicker();
  };

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
    <section className="codex-session-surface flex min-w-0 flex-col gap-4">
      <div className="codex-session-metrics grid gap-3">
        <div className="codex-session-period-card ow-page-frame rounded-[22px] p-4">
          <p className="text-sm font-extrabold text-[var(--ow-text)]">近 30 天</p>
          <p className="mt-1 text-xs font-semibold text-[var(--ow-blue)]">{usageLoading ? "正在更新统计" : usageError ? "统计未更新" : "Codex 本地数据"}</p>
        </div>
        {[["输入", metric(usage?.inputTokens)], ["缓存", metric(usage?.cachedInputTokens)], ["输出", metric(usage?.outputTokens)], ["合计", metric(usage?.totalTokens)], ["费用", usageLoading && !usage ? "—" : "不可用"]].map(([label, value]) => <div key={label} className="codex-session-metric-card ow-page-frame-soft rounded-[22px] p-4"><span className="block text-xs font-semibold text-[var(--ow-muted)]">{label}</span><strong className="mt-2 block text-xl font-extrabold tracking-[-0.03em] text-[var(--ow-text)]">{value}</strong></div>)}
      </div>

      <div className="codex-session-toolbar ow-toolbar rounded-[22px] p-3">
        <form className="codex-session-filter-form flex min-w-0 flex-1 flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); setSearch(query.trim()); }}>
          <label className="sr-only" htmlFor="codex-session-search">按标题搜索会话</label>
          <input id="codex-session-search" value={query} onChange={(event) => setQuery(event.target.value)} className="codex-session-search-field min-w-[220px] flex-1 rounded-xl border border-[var(--ow-line)] bg-[var(--ow-input)] px-3 py-2.5 text-sm text-[var(--ow-text)]" placeholder="搜索会话标题或工作目录" />
          {query && <button type="button" className="ow-btn rounded-xl px-3 py-2.5 text-sm font-semibold" onClick={() => { setQuery(""); setSearch(""); }}>清空</button>}
          <label className="sr-only" htmlFor="codex-session-kind">会话类型</label>
          <select id="codex-session-kind" value={kind} disabled={trash} onChange={(event) => setKind(event.target.value as SessionKind)} className="rounded-xl border border-[var(--ow-line)] bg-[var(--ow-input)] px-3 py-2.5 text-sm text-[var(--ow-text)]">
            <option value="conversation">对话</option><option value="external">外部</option><option value="subagent">子代理</option><option value="all">全部类型</option>
          </select>
          <button type="submit" className="ow-btn rounded-xl px-4 py-2.5 text-sm font-semibold">搜索</button>
        </form>
        <div className="codex-session-tool-actions flex flex-wrap gap-2">
          <button type="button" className="ow-btn rounded-xl px-3 py-2.5 text-sm font-semibold" disabled={busy} onClick={() => void run(importZip, true, true)}>导入 ZIP</button>
          <button type="button" className="ow-btn rounded-xl px-3 py-2.5 text-sm font-semibold" disabled={busy || trash} onClick={() => setPendingAction("repair")}>修复可见性</button>
          <button type="button" className={`rounded-xl px-3 py-2.5 text-sm font-semibold ${trash ? "ow-btn-primary" : "ow-btn"}`} disabled={busy} onClick={() => setTrash((value) => !value)}>{trash ? "返回当前会话" : "废纸篓"}</button>
          <button type="button" className="ow-btn rounded-xl px-3 py-2.5 text-sm font-semibold" disabled={busy} onClick={() => void load().then(loadUsage)}>刷新</button>
        </div>
      </div>

      {(message || error || usageError) && <div className="codex-account-notices" aria-live="polite">
        {message && <p className="border-b border-[var(--ow-green)] bg-[var(--ow-green-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-green)]">{message}</p>}
        {error && <p role="alert" className="border-b border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-red)]">{error}</p>}
        {usageError && <p role="alert" className="flex items-center justify-between gap-3 border-b border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] px-4 py-2.5 text-sm font-semibold text-[var(--ow-warning-text)]"><span>{usageError}</span><button type="button" className="codex-account-text-action" disabled={usageLoading} onClick={() => void loadUsage()}>重试统计</button></p>}
      </div>}

      <div className="codex-session-list ow-page-frame min-w-0 overflow-hidden rounded-[28px]">
        <div className="codex-session-list-header flex flex-wrap items-center justify-between gap-4 px-5 py-5 sm:px-6">
          <div>
            <h2 className="text-lg font-extrabold tracking-[-0.02em] text-[var(--ow-text)]">{trash ? "废纸篓" : kind === "conversation" ? "当前对话" : kind === "subagent" ? "子代理" : kind === "external" ? "外部会话" : "全部类型"}</h2>
            <p className="mt-1 text-sm text-[var(--ow-muted)]">{groups.length} 个工作目录 · {sessions.length} 个会话 · 按最近活动排序</p>
          </div>
          <div className="codex-session-batch-actions flex flex-wrap gap-2">
            {ids.length > 0 && <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy} onClick={() => setSelected(new Set())}>清除选择</button>}
            <button type="button" className="ow-btn rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy || !ids.length || trash} onClick={() => void run(exportZip, false)}>导出选中</button>
            {!trash ? <button type="button" className="rounded-xl bg-[var(--ow-red)] px-3 py-2 text-sm font-semibold text-[var(--ow-on-accent)] disabled:opacity-40" disabled={busy || !ids.length} onClick={() => setPendingAction("trash")}>移到废纸篓</button> : <button type="button" className="ow-btn-primary rounded-xl px-3 py-2 text-sm font-semibold" disabled={busy || !ids.length} onClick={() => void run(() => api.invoke("sessions.restore", { sessionIds: ids }), true, true)}>恢复</button>}
          </div>
        </div>

        <div className="codex-session-selection-bar flex flex-wrap items-center gap-3 px-5 py-3 sm:px-6">
          <label className="flex items-center gap-2 text-sm font-semibold text-[var(--ow-text)]">
            <input type="checkbox" aria-label="全选当前结果" checked={allSelected} onChange={() => setSelected(allSelected ? new Set() : new Set(sessions.map((item) => item.sessionId)))} />
            全选当前结果
          </label>
          <span className="text-xs text-[var(--ow-muted)]">{ids.length ? `已选择 ${ids.length} 项` : "选择会话后可导出或移到废纸篓"}</span>
        </div>

        {loading ? <div aria-live="polite" className="grid min-h-52 place-items-center text-sm font-semibold text-[var(--ow-muted)]">正在读取本地会话数据…</div> : groups.length === 0 ? <div className="grid min-h-52 place-items-center p-6 text-sm font-semibold text-[var(--ow-muted)]">{search ? "没有匹配的会话或工作目录。" : "暂无本地会话"}</div> : <div className="codex-session-project-grid">
          {groups.map((group) => {
            const groupIds = group.sessions.map((session) => session.sessionId);
            const selectedCount = groupIds.filter((id) => selected.has(id)).length;
            return <article key={`${trash ? "trash" : "active"}-${group.cwd}`} className="codex-session-project-card">
              <div className="codex-session-project-heading">
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-sm font-extrabold text-[var(--ow-text)]" title={group.label}>{group.label}</h3>
                  <p className="mt-1 truncate text-[11px] text-[var(--ow-subtle)]" title={group.cwd || group.label}>{group.cwd || "未标注工作目录"}</p>
                </div>
                {selectedCount > 0 && <span className="codex-session-selected-badge">已选 {selectedCount}</span>}
              </div>
              <div className="codex-session-project-meta">
                <span>{group.sessions.length} 个对话</span>
                <span>最近活动 {relativeTime(group.latestUpdatedAt)}</span>
              </div>
              <div className="codex-session-project-recent">
                {group.sessions.slice(0, 2).map((session) => <div key={session.sessionId} className="codex-session-project-recent-row">
                  <span title={session.title || "未命名会话"}>{session.title || "未命名会话"}</span>
                  <time>{relativeTime(session.updatedAt)}</time>
                </div>)}
              </div>
              <button type="button" className="codex-session-picker-button ow-btn" disabled={busy} onClick={() => openSessionPicker(group)}>选择会话</button>
            </article>;
          })}
        </div>}
      </div>
      <dialog
        ref={pickerDialogRef}
        className="codex-session-picker-dialog ow-native-dialog ow-modal-panel overflow-hidden rounded-[24px] border-0 p-0"
        aria-labelledby="codex-session-picker-title"
        aria-modal="true"
        onCancel={(event) => { event.preventDefault(); closeSessionPicker(); }}
        onClick={(event) => { if (event.target === event.currentTarget) closeSessionPicker(); }}
      >
        <div className="codex-session-picker-shell">
          <div className="codex-session-picker-header">
            <div className="min-w-0">
              <h2 id="codex-session-picker-title" className="truncate text-xl font-extrabold tracking-[-0.025em] text-[var(--ow-text)]">{pickerGroup?.label || "选择会话"}</h2>
              <p className="mt-1 truncate text-xs text-[var(--ow-muted)]" title={pickerGroup?.cwd}>{pickerGroup?.cwd || "从当前工作目录选择会话"}</p>
            </div>
            <button type="button" className="codex-account-text-action" aria-label="关闭会话选择" onClick={closeSessionPicker}>关闭</button>
          </div>
          <div className="codex-session-picker-controls ow-toolbar">
            <label className="sr-only" htmlFor="codex-session-picker-search">搜索当前工作目录的会话</label>
            <input id="codex-session-picker-search" className="codex-session-picker-search" value={pickerQuery} onChange={(event) => setPickerQuery(event.target.value)} placeholder="搜索当前工作目录的会话" autoFocus />
            <label className="codex-session-picker-select-all">
              <input type="checkbox" checked={pickerAllSelected} disabled={pickerSessions.length === 0} onChange={() => toggleDraftIds(pickerSessions.map((session) => session.sessionId))} />
              全选当前结果
            </label>
          </div>
          <div className="codex-session-picker-list">
            {pickerSessions.length === 0 ? <div className="codex-session-picker-empty">没有匹配的会话。</div> : pickerSessions.map((session) => <label key={session.sessionId} className="codex-session-picker-row">
              <input type="checkbox" checked={draftSelected.has(session.sessionId)} onChange={() => toggleDraftIds([session.sessionId])} />
              <span className="min-w-0 flex-1">
                <strong title={session.title || "未命名会话"}>{session.title || "未命名会话"}</strong>
                <small>会话 ID：{shortId(session.sessionId)}</small>
              </span>
              <time>{relativeTime(session.updatedAt)}</time>
            </label>)}
          </div>
          <div className="codex-session-picker-footer">
            <span aria-live="polite">已选择 {draftSelected.size} / {pickerGroup?.sessions.length || 0} 个会话</span>
            <div>
              <button type="button" className="ow-btn rounded-xl px-4 py-2.5 text-sm font-semibold" onClick={closeSessionPicker}>取消</button>
              <button type="button" className="ow-btn-primary rounded-xl px-4 py-2.5 text-sm font-semibold" onClick={confirmSessionPicker}>确认选择</button>
            </div>
          </div>
        </div>
      </dialog>
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
            void run(() => api.invoke("sessions.trash", { sessionIds: ids }), true, true);
          } else if (action === "repair") {
            void run(() => api.invoke("sessions.repair"));
          }
        }}
      />
    </section>
  );
}
