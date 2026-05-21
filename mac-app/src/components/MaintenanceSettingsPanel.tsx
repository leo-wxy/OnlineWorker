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
    </div>
  );
}
