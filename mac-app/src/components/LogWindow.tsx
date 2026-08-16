import { invoke } from "@tauri-apps/api/core";
import { useEffect, useRef, useState } from "react";
import { useLogTail } from "../hooks";
import { useI18n } from "../i18n";

type LogLevel = "ALL" | "DEBUG" | "INFO" | "WARNING" | "ERROR";

const FILTERS: LogLevel[] = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"];

const LEVEL_STYLES: Record<string, { badge: string; row: string }> = {
  DEBUG: {
    badge: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]",
    row: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)]",
  },
  INFO: {
    badge: "border-[var(--ow-blue)] bg-[var(--ow-blue-soft)] text-[var(--ow-blue)]",
    row: "border-[var(--ow-blue)] bg-[var(--ow-blue-soft)]",
  },
  WARNING: {
    badge: "border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] text-[var(--ow-warning-text)]",
    row: "border-[var(--ow-amber)] bg-[var(--ow-amber-soft)]",
  },
  ERROR: {
    badge: "border-[var(--ow-red)] bg-[var(--ow-red-soft)] text-[var(--ow-error-text)]",
    row: "border-[var(--ow-red)] bg-[var(--ow-red-soft)]",
  },
  UNKNOWN: {
    badge: "border-[var(--ow-line)] bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]",
    row: "border-[var(--ow-line)] bg-[var(--ow-panel)]",
  },
};

interface Props {
  onClose: () => void;
}

export function LogWindow({ onClose }: Props) {
  const { t } = useI18n();
  const { lines, running, start, stop, clear } = useLogTail();
  const [filter, setFilter] = useState<LogLevel>("ALL");
  const [autoScroll, setAutoScroll] = useState(true);
  const [logPath, setLogPath] = useState("onlineworker.log");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    start();
    return () => {
      stop();
    };
  }, []);

  useEffect(() => {
    invoke<string>("get_log_file_path")
      .then((value) => {
        if (value) {
          setLogPath(value);
        }
      })
      .catch(() => {
        // Ignore in non-Tauri environments.
      });
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [lines, autoScroll]);

  const filteredLines = filter === "ALL"
    ? lines
    : lines.filter((line) => line.level === filter);

  const countSummary = filter === "ALL"
    ? t.common.items(lines.length)
    : `${t.common.items(filteredLines.length)} / ${t.common.items(lines.length)}`;

  return (
    <div
      className="ow-modal-backdrop fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      onClick={onClose}
    >
      <div
        className="ow-modal-panel flex h-[min(84vh,820px)] w-full max-w-6xl flex-col overflow-hidden rounded-[30px]"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="border-b border-[var(--ow-line-soft)] px-5 py-4 sm:px-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="flex items-start gap-3">
                <div className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-[var(--ow-blue-soft)] text-[var(--ow-blue)] [box-shadow:var(--ow-shadow-sm)]">
                  <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 17v-6m3 6V7m3 10v-3m3 6H6a2 2 0 01-2-2V6a2 2 0 012-2h9.586a1 1 0 01.707.293l3.414 3.414a1 1 0 01.293.707V18a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <h2 className="truncate text-base font-semibold text-[var(--ow-text)] sm:text-lg">
                    {t.logs.title(logPath)}
                  </h2>
                  <p className="mt-1 break-all text-xs leading-5 text-[var(--ow-muted)]">
                    {logPath}
                  </p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className={`ow-badge rounded-full border px-2.5 py-1 text-[10px] ${
                      running
                        ? "border-[var(--ow-green)] bg-[var(--ow-green-soft)] text-[var(--ow-green)]"
                        : "border-[var(--ow-line)] bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]"
                    }`}>
                      {running ? t.logs.live : t.logs.paused}
                    </span>
                    <span className="ow-badge rounded-full border border-[var(--ow-line)] bg-[var(--ow-panel)] px-2.5 py-1 text-[10px] text-[var(--ow-muted)]">
                      {countSummary}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <button
                onClick={running ? stop : start}
                className="ow-btn rounded-xl px-3.5 py-2 text-xs font-semibold text-[var(--ow-text)] transition-colors hover:bg-[var(--ow-panel)]"
              >
                {running ? t.logs.pause : t.logs.resume}
              </button>
              <button
                onClick={clear}
                className="ow-btn rounded-xl px-3.5 py-2 text-xs font-semibold text-[var(--ow-text)] transition-colors hover:bg-[var(--ow-panel)]"
              >
                {t.logs.clear}
              </button>
              <button
                onClick={onClose}
                className="ow-btn rounded-xl px-3.5 py-2 text-xs font-semibold text-[var(--ow-text)] transition-colors hover:bg-[var(--ow-panel)]"
              >
                {t.common.close}
              </button>
            </div>
          </div>
        </div>

        <div className="border-b border-[var(--ow-line-soft)] px-5 py-3 sm:px-6">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--ow-muted)]">
                {t.logs.filter}
              </span>
              {FILTERS.map((level) => (
                <button
                  key={level}
                  onClick={() => setFilter(level)}
                  className={`ow-log-filter-chip rounded-full px-3 py-1.5 text-[11px] font-semibold transition-colors ${
                    filter === level ? "ow-log-filter-chip-active" : ""
                  }`}
                >
                  {level}
                </button>
              ))}
            </div>

            <label className="flex select-none items-center gap-2 text-xs font-medium text-[var(--ow-muted)]">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(event) => setAutoScroll(event.target.checked)}
                className="h-3.5 w-3.5 rounded border-[var(--ow-line)] text-[var(--ow-blue)] focus:ring-[var(--ow-focus)]"
              />
              {t.logs.autoScroll}
            </label>
          </div>
        </div>

        <div className="ow-log-stream flex-1 overflow-y-auto px-3 py-3 sm:px-4">
          {filteredLines.length === 0 ? (
            <div className="flex h-full min-h-[260px] items-center justify-center">
              <div className="ow-page-frame-soft max-w-md rounded-3xl px-6 py-8 text-center shadow-none">
                <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]">
                  <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                </div>
                <p className="text-sm font-semibold text-[var(--ow-text)]">
                  {running ? t.logs.waiting : t.logs.noEntries}
                </p>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredLines.map((line, index) => {
                const levelStyle = LEVEL_STYLES[line.level] ?? LEVEL_STYLES.UNKNOWN;
                return (
                  <div
                    key={`${line.timestamp ?? "log"}-${index}`}
                    className={`ow-log-entry rounded-2xl border px-4 py-3 ${levelStyle.row}`}
                    title={line.raw}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      {line.timestamp && (
                        <span className="text-[11px] font-medium text-[var(--ow-muted)]">
                          {line.timestamp}
                        </span>
                      )}
                      <span className={`ow-badge rounded-full border px-2 py-0.5 text-[10px] ${levelStyle.badge}`}>
                        {line.level}
                      </span>
                    </div>
                    <p className="mt-2 break-words font-mono text-[12px] leading-6 text-[var(--ow-text)]">
                      {line.message || line.raw}
                    </p>
                  </div>
                );
              })}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
