import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useI18n, type AppTexts } from "../i18n";
import { parseCliEntriesFromConfigRaw } from "../utils/configProviders.js";
import { getCliInstallInfo } from "../utils/cliTools.js";

// ─── Types ─────────────────────────────────────────────────────────────────

interface CliEntry {
  name: string;   // tool name, e.g. "codex"
  bin: string;    // raw bin path from config
}

interface CliStatus extends CliEntry {
  installed: boolean | null;  // null = checking
}

// ─── CopyButton ────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const { t } = useI18n();
  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <button
      onClick={copy}
      className="text-xs text-gray-400 hover:text-gray-600 flex-shrink-0 ml-2 transition-colors"
      title={copied ? t.common.copied : t.common.copy}
    >
      {copied ? "✓" : "⎘"}
    </button>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export function CliChecker({ configRaw }: { configRaw: string }) {
  const { t } = useI18n();
  const [statuses, setStatuses] = useState<CliStatus[]>([]);
  const [checking, setChecking] = useState(false);

  const check = useCallback(async (raw: string) => {
    const entries = parseCliEntriesFromConfigRaw(raw) as CliEntry[];
    if (entries.length === 0) {
      setStatuses([]);
      setChecking(false);
      return;
    }

    // Initialize with null (checking)
    setStatuses(entries.map((e) => ({ ...e, installed: null })));
    setChecking(true);

    // Check all in parallel
    const results = await Promise.all(
      entries.map(async (e) => {
        try {
          const installed = await invoke<boolean>("check_cli", { bin: e.bin });
          return { ...e, installed };
        } catch {
          return { ...e, installed: false };
        }
      })
    );
    setStatuses(results);
    setChecking(false);
  }, []);

  useEffect(() => {
    if (configRaw) void check(configRaw);
  }, [configRaw, check]);

  if (statuses.length === 0) return null;

  const missing = statuses.filter((s) => s.installed === false);
  const allOk = statuses.every((s) => s.installed === true);

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">{t.cliChecker.title}</span>
          {checking && <span className="text-xs text-gray-400">{t.common.checking}</span>}
          {!checking && allOk && (
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">{t.cliChecker.allInstalled}</span>
          )}
          {!checking && missing.length > 0 && (
            <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full font-medium">
              {t.cliChecker.missingCount(missing.length)}
            </span>
          )}
        </div>
        <button
          onClick={() => void check(configRaw)}
          disabled={checking}
          className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-40"
        >
          ↻ {t.common.recheck}
        </button>
      </div>

      {/* Status rows */}
      <div className="divide-y divide-gray-100">
        {statuses.map((s) => {
          const info = getCliInstallInfo(s.name, s.bin, t.cliChecker as AppTexts["cliChecker"]);
          return (
            <div key={s.name}>
              {/* CLI row */}
              <div className="flex items-center px-4 py-3 gap-3">
                {/* Status indicator */}
                <span className="flex-shrink-0 w-4 h-4 flex items-center justify-center">
                  {s.installed === null ? (
                    <span className="w-3 h-3 rounded-full bg-gray-200 animate-pulse" />
                  ) : s.installed ? (
                    <span className="text-green-500 text-base leading-none">✓</span>
                  ) : (
                    <span className="text-red-400 text-base leading-none">✗</span>
                  )}
                </span>

                {/* Name + bin */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800">{s.name}</p>
                  <p className="text-xs text-gray-400 font-mono truncate">{s.bin}</p>
                </div>

                {/* Installed badge */}
                {s.installed === true && (
                  <span className="text-xs text-green-600 flex-shrink-0">{t.common.installed}</span>
                )}
                {s.installed === false && (
                  <span className="text-xs text-red-500 flex-shrink-0">{t.common.notFound}</span>
                )}
              </div>

              {/* Install instructions — only shown when missing */}
              {s.installed === false && (
                <div className="mx-4 mb-3 bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                  <p className="text-xs font-medium text-amber-800">{t.cliChecker.installInstructions(info.label)}</p>
                  {info.steps.map((step, i) => (
                    <div key={i}>
                      <p className="text-xs text-amber-700 mb-1">{step.desc}</p>
                      <div className="flex items-center bg-gray-900 rounded px-3 py-2">
                        <code className="text-xs text-green-400 font-mono flex-1 select-all break-all">
                          {step.cmd}
                        </code>
                        <CopyButton text={step.cmd} />
                      </div>
                    </div>
                  ))}
                  {info.docsUrl && (
                    <p className="text-xs text-amber-600">
                      {t.cliChecker.docs}: <span className="font-mono">{info.docsUrl}</span>
                    </p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
