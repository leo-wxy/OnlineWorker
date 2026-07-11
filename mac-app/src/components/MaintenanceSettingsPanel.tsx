import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n } from "../i18n";

interface AttachmentCachePathStats {
  name: string;
  path: string;
  exists: boolean;
  fileCount: number;
  totalBytes: number;
}

interface AttachmentCacheStats {
  fileCount: number;
  totalBytes: number;
  paths: AttachmentCachePathStats[];
}

interface AttachmentCacheClearResult {
  deletedFiles: number;
  deletedDirs: number;
  freedBytes: number;
  failed: string[];
  stats: AttachmentCacheStats;
}

interface DiagnosticCheck {
  id: string;
  label: string;
  status: "pass" | "warning" | "fail";
  summary: string;
  detail: string | null;
  remediation: string | null;
  durationMs: number;
}

interface DiagnosticReport {
  generatedAt: string;
  overall: "pass" | "warning" | "fail";
  checks: DiagnosticCheck[];
}

interface SupportBundleExportResult {
  path: string;
  fileSize: number;
  generatedAt: string;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 10 || unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

export function MaintenanceSettingsPanel() {
  const { t } = useI18n();
  const setup = t.setup;
  const common = t.common;

  const [attachmentCache, setAttachmentCache] = useState<AttachmentCacheStats | null>(null);
  const [cacheLoading, setCacheLoading] = useState(false);
  const [cacheClearing, setCacheClearing] = useState(false);
  const [cacheMessage, setCacheMessage] = useState<string | null>(null);
  const [cacheError, setCacheError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticReport | null>(null);
  const [diagnosticsBusy, setDiagnosticsBusy] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [diagnosticsMessage, setDiagnosticsMessage] = useState<string | null>(null);
  const [supportBundle, setSupportBundle] = useState<SupportBundleExportResult | null>(null);
  const [expandedCheckIds, setExpandedCheckIds] = useState<string[]>([]);

  const loadAttachmentCacheStats = useCallback(async () => {
    setCacheLoading(true);
    setCacheError(null);
    setCacheMessage(null);
    try {
      const stats = await invoke<AttachmentCacheStats>("get_attachment_cache_stats");
      setAttachmentCache(stats);
    } catch (e) {
      setCacheError(setup.attachmentCacheError(String(e)));
    } finally {
      setCacheLoading(false);
    }
  }, [setup.attachmentCacheError]);

  useEffect(() => {
    void loadAttachmentCacheStats();
  }, [loadAttachmentCacheStats]);

  const clearAttachmentCache = async () => {
    setCacheClearing(true);
    setCacheError(null);
    setCacheMessage(null);
    try {
      const result = await invoke<AttachmentCacheClearResult>("clear_attachment_cache");
      setAttachmentCache(result.stats);
      if (result.failed.length > 0) {
        setCacheError(setup.attachmentCachePartialError(result.failed.length));
      } else {
        setCacheMessage(
          setup.attachmentCacheCleared(formatBytes(result.freedBytes), result.deletedFiles)
        );
      }
    } catch (e) {
      setCacheError(setup.attachmentCacheError(String(e)));
    } finally {
      setCacheClearing(false);
    }
  };

  const runDiagnostics = async () => {
    setDiagnosticsBusy(true);
    setDiagnosticsError(null);
    setDiagnosticsMessage(null);
    try {
      const report = await invoke<DiagnosticReport>("run_support_diagnostics");
      setDiagnostics(report);
      setExpandedCheckIds([]);
    } catch (e) {
      setDiagnosticsError(setup.diagnosticsError(String(e)));
    } finally {
      setDiagnosticsBusy(false);
    }
  };

  const copyDiagnostics = async () => {
    if (!diagnostics) return;
    const lines = diagnostics.checks.map(
      (check) => `[${check.status}] ${check.label}: ${check.summary}`
    );
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setDiagnosticsMessage(setup.diagnosticsCopied);
      setDiagnosticsError(null);
    } catch (e) {
      setDiagnosticsError(setup.supportBundleError(String(e)));
    }
  };

  const exportSupportBundle = async () => {
    setExportBusy(true);
    setDiagnosticsError(null);
    setDiagnosticsMessage(null);
    try {
      const result = await invoke<SupportBundleExportResult | null>("export_support_bundle");
      if (result) {
        setSupportBundle(result);
        setDiagnosticsMessage(setup.supportBundleExported(result.path));
      }
    } catch (e) {
      setDiagnosticsError(setup.supportBundleError(String(e)));
    } finally {
      setExportBusy(false);
    }
  };

  const revealSupportBundle = async () => {
    if (!supportBundle) return;
    try {
      await invoke("reveal_support_bundle", { path: supportBundle.path });
    } catch (e) {
      setDiagnosticsError(setup.supportBundleError(String(e)));
    }
  };

  const groupedDiagnostics = (["fail", "warning", "pass"] as const)
    .map((status) => ({
      status,
      checks: diagnostics?.checks.filter((check) => check.status === status) ?? [],
    }))
    .filter((group) => group.checks.length > 0);

  const statusLabel = (status: DiagnosticCheck["status"]) => {
    if (status === "pass") return setup.diagnosticsStatusPass;
    if (status === "warning") return setup.diagnosticsStatusWarning;
    return setup.diagnosticsStatusFail;
  };

  const statusTone = (status: DiagnosticCheck["status"]) => {
    if (status === "pass") return "bg-emerald-500";
    if (status === "warning") return "bg-amber-500";
    return "bg-rose-500";
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
          {setup.maintenanceEyebrow}
        </p>
        <h2 className="mt-1 text-[28px] font-extrabold tracking-[-0.03em] text-gray-950">
          {setup.maintenanceTitle}
        </h2>
        <p className="mt-2 text-sm font-medium text-slate-500">
          {setup.maintenanceDescription}
        </p>
      </div>

      <div className="ow-page-frame rounded-[26px] p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
              {setup.storageTitle}
            </p>
            <h3 className="mt-1 text-base font-bold text-gray-900">
              {setup.attachmentCacheTitle}
            </h3>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              {setup.attachmentCacheDescription}
            </p>
            <p className="mt-3 text-sm font-semibold text-slate-700">
              {cacheLoading
                ? common.loading
                : setup.attachmentCacheSize(
                    formatBytes(attachmentCache?.totalBytes ?? 0),
                    attachmentCache?.fileCount ?? 0
                  )}
            </p>
            {(cacheMessage || cacheError) && (
              <p
                className={`mt-2 text-sm font-medium ${
                  cacheError ? "text-rose-600" : "text-emerald-700"
                }`}
              >
                {cacheError || cacheMessage}
              </p>
            )}
          </div>
          <div className="flex flex-shrink-0 gap-2">
            <button
              onClick={() => void loadAttachmentCacheStats()}
              disabled={cacheLoading || cacheClearing}
              className="ow-btn rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 disabled:opacity-50"
            >
              {common.recheck}
            </button>
            <button
              onClick={() => void clearAttachmentCache()}
              disabled={cacheLoading || cacheClearing || (attachmentCache?.fileCount ?? 0) === 0}
              className="ow-btn-primary rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
            >
              {cacheClearing ? setup.attachmentCacheClearing : setup.attachmentCacheClear}
            </button>
          </div>
        </div>
      </div>

      <section className="ow-page-frame rounded-[26px] p-6" aria-labelledby="diagnostics-title">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h3 id="diagnostics-title" className="text-base font-bold text-gray-900">
              {setup.diagnosticsTitle}
            </h3>
            <p className="mt-1 max-w-2xl text-sm text-slate-500">
              {setup.diagnosticsDescription}
            </p>
            <p className="mt-2 max-w-2xl text-xs text-slate-500">
              {setup.supportBundlePrivacy}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void runDiagnostics()}
            disabled={diagnosticsBusy || exportBusy}
            className="ow-btn-primary h-9 shrink-0 rounded-lg px-4 text-sm font-semibold disabled:opacity-50"
          >
            {diagnosticsBusy ? setup.diagnosticsRunning : setup.runDiagnostics}
          </button>
        </div>

        <div className="mt-5" aria-live="polite">
          {!diagnostics && !diagnosticsBusy && !diagnosticsError ? (
            <p className="text-sm text-slate-400">{setup.diagnosticsNeverRun}</p>
          ) : null}

          {groupedDiagnostics.map((group) => (
            <div key={group.status} className="border-t border-[var(--ow-line-soft)] py-3 first:border-t-0">
              <p className="mb-2 text-xs font-semibold text-slate-500">
                {statusLabel(group.status)} · {group.checks.length}
              </p>
              <ul className="divide-y divide-[var(--ow-line-soft)]">
                {group.checks.map((check) => {
                  const expanded = expandedCheckIds.includes(check.id);
                  const hasDetails = Boolean(check.detail || check.remediation);
                  return (
                    <li key={check.id} className="py-2.5">
                      <div className="flex items-start gap-3">
                        <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${statusTone(check.status)}`} aria-hidden="true" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                            <p className="text-sm font-semibold text-slate-800">{check.label}</p>
                            <span className="text-xs text-slate-400">{check.durationMs} ms</span>
                          </div>
                          <p className="mt-0.5 text-sm text-slate-600">{check.summary}</p>
                          {hasDetails ? (
                            <button
                              type="button"
                              aria-expanded={expanded}
                              onClick={() => setExpandedCheckIds((current) => (
                                current.includes(check.id)
                                  ? current.filter((id) => id !== check.id)
                                  : [...current, check.id]
                              ))}
                              className="mt-1 text-xs font-semibold text-slate-500 hover:text-slate-900"
                            >
                              {expanded ? setup.diagnosticsHideDetails : setup.diagnosticsShowDetails}
                            </button>
                          ) : null}
                          {expanded ? (
                            <div className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
                              {check.detail ? <p className="break-words">{check.detail}</p> : null}
                              {check.remediation ? (
                                <p><span className="font-semibold text-slate-600">{setup.diagnosticsRemediation}：</span>{check.remediation}</p>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}

          {diagnosticsError ? <p className="mt-3 text-sm font-medium text-rose-600">{diagnosticsError}</p> : null}
          {diagnosticsMessage ? <p className="mt-3 break-words text-sm font-medium text-emerald-700">{diagnosticsMessage}</p> : null}
        </div>

        <div className="mt-5 flex flex-wrap gap-2 border-t border-[var(--ow-line-soft)] pt-4">
          <button
            type="button"
            onClick={() => void copyDiagnostics()}
            disabled={!diagnostics || diagnosticsBusy || exportBusy}
            className="ow-btn h-9 rounded-lg px-4 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            {setup.copyDiagnostics}
          </button>
          <button
            type="button"
            onClick={() => void exportSupportBundle()}
            disabled={diagnosticsBusy || exportBusy}
            className="ow-btn h-9 rounded-lg px-4 text-sm font-semibold text-slate-700 disabled:opacity-50"
          >
            {exportBusy ? setup.supportBundleExporting : setup.exportSupportBundle}
          </button>
          {supportBundle ? (
            <button
              type="button"
              onClick={() => void revealSupportBundle()}
              disabled={diagnosticsBusy || exportBusy}
              className="ow-btn h-9 rounded-lg px-4 text-sm font-semibold text-slate-700 disabled:opacity-50"
            >
              {setup.revealSupportBundle}
            </button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
