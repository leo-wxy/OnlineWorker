import { useEffect, useMemo, useState } from "react";
import { useCommandRegistry } from "../hooks";
import { useI18n } from "../i18n";
import { fetchProviderMetadata } from "../components/session-browser/api";
import {
  buildCommandBackendViews,
  countCommandsForBackendView,
  matchesCommandBackendView,
} from "../utils/commandRegistryView.js";
import type {
  CommandBackend,
  CommandRegistryEntry,
  CommandRegistryResponse,
  CommandScope,
  ProviderMetadata,
} from "../types";

type BackendView = string;
type SecondaryView = "command" | "skill";

interface CommandRegistryViewProps {
  registry: CommandRegistryResponse | null;
  loading: boolean;
  refreshing: boolean;
  publishing: boolean;
  updatingCommandId: string | null;
  error: string | null;
  onRefresh: () => Promise<void>;
  onPublish: () => Promise<void>;
  onToggle: (commandId: string, enabled: boolean) => Promise<void>;
  notice?: string | null;
  providers?: ProviderMetadata[];
}

function getDuplicateCommandNames(commands: CommandRegistryEntry[]): string[] {
  const counts = new Map<string, number>();

  for (const command of commands) {
    counts.set(command.name, (counts.get(command.name) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .filter(([, count]) => count > 1)
    .map(([name]) => name)
    .sort();
}

function backendLabel(
  backend: CommandBackend,
  labels: Record<string, string>,
): string {
  return labels[backend] ?? backend;
}

function matchesSearchQuery(command: CommandRegistryEntry, normalizedQuery: string): boolean {
  if (!normalizedQuery) {
    return true;
  }

  const haystack = [
    command.name,
    command.telegramName,
    command.description,
    command.id,
    command.source,
    command.backend,
    command.scope,
  ]
    .join(" ")
    .toLowerCase();

  return haystack.includes(normalizedQuery);
}

function matchesSecondaryView(
  command: CommandRegistryEntry,
  secondaryView: SecondaryView,
): boolean {
  if (secondaryView === "skill") {
    return command.source === "skill";
  }
  return command.source !== "skill";
}

function compareCommands(left: CommandRegistryEntry, right: CommandRegistryEntry): number {
  const statusRank = left.status === right.status
    ? 0
    : left.status === "active" ? -1 : 1;
  if (statusRank !== 0) {
    return statusRank;
  }

  const publishedRank = left.publishedToTelegram === right.publishedToTelegram
    ? 0
    : left.publishedToTelegram ? -1 : 1;
  if (publishedRank !== 0) {
    return publishedRank;
  }

  return left.name.localeCompare(right.name) || left.id.localeCompare(right.id);
}

function countCommands(
  commands: CommandRegistryEntry[],
  backendView: BackendView,
  secondaryView?: SecondaryView,
): number {
  return countCommandsForBackendView(
    commands,
    backendView,
    secondaryView
      ? (command: CommandRegistryEntry) => matchesSecondaryView(command, secondaryView)
      : null,
  );
}

export function CommandRegistryView({
  registry,
  loading,
  refreshing,
  publishing,
  updatingCommandId,
  error,
  onRefresh,
  onPublish,
  onToggle,
  notice = null,
  providers = [],
}: CommandRegistryViewProps) {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [backendView, setBackendView] = useState<BackendView>("bot");
  const [secondaryView, setSecondaryView] = useState<SecondaryView>("command");
  const [publishMessage, setPublishMessage] = useState<string | null>(null);

  const commands = registry?.commands ?? [];
  const visibleProviders = useMemo(
    () => providers.filter((provider) => provider.visible === true),
    [providers],
  );
  const backendViews = useMemo(
    () => buildCommandBackendViews(visibleProviders) as BackendView[],
    [visibleProviders],
  );
  const providerLabels = useMemo(() => Object.fromEntries(
    visibleProviders.map((provider) => [provider.id, provider.label || provider.id]),
  ) as Record<string, string>, [visibleProviders]);

  useEffect(() => {
    if (!backendViews.includes(backendView)) {
      setBackendView(backendViews[0] ?? "bot");
      setSecondaryView("command");
    }
  }, [backendView, backendViews]);

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const currentViewCommands = commands
    .filter((command) => matchesCommandBackendView(command, backendView))
    .filter((command) => (backendView === "bot" ? true : matchesSecondaryView(command, secondaryView)))
    .filter((command) => matchesSearchQuery(command, normalizedQuery))
    .sort(compareCommands);

  const enabledCount = commands.filter((command) => command.enabledForTelegram).length;
  const selectedActiveCommands = commands.filter(
    (command) => command.enabledForTelegram && command.status === "active",
  );
  const aliasedSelectedNames = selectedActiveCommands
    .filter((command) => command.telegramName !== command.name)
    .map((command) => `${command.name} -> ${command.telegramName}`)
    .filter((value, index, items) => items.indexOf(value) === index)
    .sort();
  const duplicateSelectedNames = getDuplicateCommandNames(selectedActiveCommands);
  const backendCounts = Object.fromEntries(
    backendViews.map((view) => [view, countCommands(commands, view)]),
  ) as Record<string, number>;
  const secondaryCounts: Record<SecondaryView, number> = {
    command: countCommands(commands, backendView, "command"),
    skill: countCommands(commands, backendView, "skill"),
  };
  const backendViewLabels: Record<string, string> = {
    bot: t.commands.filterBot,
    ...providerLabels,
  };

  const backendLabels: Record<string, string> = {
    local: t.commands.backendLocal,
    shared: t.commands.backendShared,
    ...providerLabels,
  };
  const scopeLabels: Record<CommandScope, string> = {
    global: t.commands.scopeGlobal,
    workspace: t.commands.scopeWorkspace,
    thread: t.commands.scopeThread,
  };

  const handleRefresh = async () => {
    setPublishMessage(null);
    await onRefresh();
  };

  const handlePublish = async () => {
    setPublishMessage(null);
    try {
      await onPublish();
      setPublishMessage(t.commands.publishSuccess);
    } catch {
      setPublishMessage(null);
    }
  };

  const handleToggle = async (commandId: string, enabled: boolean) => {
    setPublishMessage(null);
    try {
      await onToggle(commandId, enabled);
    } catch {
      // Error handled by hook
    }
  };

  const renderCommandCard = (command: CommandRegistryEntry) => {
    const isUpdating = updatingCommandId === command.id;
    const isSkill = command.source === "skill";

    let iconContainerClass = "";
    let icon = null;
    let providerTextClass = "";
    let providerLabel = "";

    if (isSkill) {
      iconContainerClass = "bg-orange-50 border-orange-100";
      icon = <svg className="w-4 h-4 text-orange-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>;
      providerTextClass = "text-orange-600";
      providerLabel = "Skill";
    } else if (command.source === "bot") {
      iconContainerClass = "bg-gray-100 border-gray-200";
      icon = <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>;
      providerTextClass = "text-gray-500";
      providerLabel = "Bot Built-in";
    } else {
      iconContainerClass = "bg-sky-50 border-sky-100";
      icon = <svg className="w-4 h-4 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"></path></svg>;
      providerTextClass = "text-sky-600";
      providerLabel = backendLabel(command.backend, backendLabels);
    }

    let scopeClass = "";
    if (command.scope === "global") {
      scopeClass = "bg-blue-50 text-blue-600 border-blue-100";
    } else if (command.scope === "thread") {
      scopeClass = "bg-green-50 text-green-600 border-green-100";
    } else {
      scopeClass = "bg-gray-100 text-gray-600 border-gray-200";
    }

    return (
      <div key={command.id} className={`flex items-center justify-between px-5 py-4 hover:bg-blue-50/50 transition-colors row-hover group ${!command.enabledForTelegram ? 'opacity-75 hover:opacity-100' : ''}`}>
        <div className="flex items-center gap-4 w-1/3">
          <input 
            type="checkbox" 
            className="mac-checkbox ml-1" 
            checked={command.enabledForTelegram}
            disabled={isUpdating || publishing || refreshing}
            onChange={(event) => {
              void handleToggle(command.id, event.target.checked);
            }}
          />
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-lg border flex items-center justify-center flex-shrink-0 ${iconContainerClass}`}>
              {icon}
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <p className="font-mono text-[13px] font-bold text-gray-900 group-hover:text-blue-700 transition-colors">
                  {isSkill ? `@${command.name}` : `/${command.name}`}
                </p>
                {command.status === "missing" && (
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400" title={t.commands.missingBadge}></span>
                )}
              </div>
              <p className={`text-[10px] font-semibold uppercase tracking-wide mt-0.5 ${providerTextClass}`}>
                {providerLabel}
              </p>
            </div>
          </div>
        </div>
        
        <div className="w-1/2 pr-4">
          <p className="text-[13px] text-gray-600 leading-relaxed line-clamp-2">
            {command.description || t.commands.emptyDescription}
          </p>
          {command.telegramName !== command.name && (
            <p className="text-[11px] text-amber-600 mt-1">{t.commands.telegramAliasLabel(`/${command.telegramName}`)}</p>
          )}
        </div>
        
        <div className="w-1/6 flex items-center justify-end gap-3 pr-2">
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold border uppercase tracking-wider ${scopeClass}`}>
            {scopeLabels[command.scope]}
          </span>
          <button className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:bg-gray-200 hover:text-gray-800 transition-all opacity-0 row-action" title="Edit Command">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="ow-page-frame flex flex-1 flex-col min-h-0 w-full overflow-hidden rounded-[30px]">
      <style>{`
        .mac-checkbox {
          appearance: none;
          background-color: #fff;
          margin: 0;
          font: inherit;
          color: currentColor;
          width: 1.15em;
          height: 1.15em;
          border: 1px solid #d1d5db;
          border-radius: 0.25em;
          display: grid;
          place-content: center;
          transition: all 0.1s ease-in-out;
          cursor: pointer;
        }
        .mac-checkbox::before {
          content: "";
          width: 0.65em;
          height: 0.65em;
          transform: scale(0);
          transition: 120ms transform ease-in-out;
          box-shadow: inset 1em 1em white;
          background-color: transparent;
          transform-origin: center;
          clip-path: polygon(14% 44%, 0 65%, 50% 100%, 100% 16%, 80% 0%, 43% 62%);
        }
        .mac-checkbox:checked {
          background-color: #3b82f6;
          border-color: #3b82f6;
        }
        .mac-checkbox:checked::before {
          transform: scale(1);
        }
        .row-hover:hover .row-action {
          opacity: 1;
        }
      `}</style>
      
      {/* Top Action Bar */}
      <div className="border-b border-[var(--ow-line-soft)] px-4 py-3 flex-shrink-0">
        <div className="ow-toolbar mx-auto flex max-w-5xl flex-col gap-3 rounded-[24px] px-4 py-4">
          <div className="flex justify-between items-start gap-4">
            <div>
              <h2 className="text-[24px] font-extrabold tracking-[-0.03em] text-gray-950">{t.commands.title}</h2>
              <p className="mt-1 text-sm text-slate-500">{t.commands.browserSectionDescription}</p>
            </div>
            <div className="flex items-center gap-3">
              <button 
                onClick={() => void handleRefresh()}
                disabled={loading || refreshing || publishing}
                className="ow-btn inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-slate-700 transition-all group disabled:opacity-50"
              >
                <svg className="w-4 h-4 text-slate-400 group-hover:text-blue-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
                {refreshing ? t.commands.refreshing : t.commands.refresh}
              </button>
              <button 
                onClick={() => void handlePublish()}
                disabled={loading || refreshing || publishing || !registry}
                className="ow-btn-primary inline-flex items-center gap-2 rounded-xl px-5 py-2 text-sm font-semibold disabled:opacity-50"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                {publishing ? t.commands.publishing : t.commands.publish}
              </button>
            </div>
          </div>

          {/* Big Search Bar */}
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <svg className="w-5 h-5 text-slate-400 group-focus-within:text-blue-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
            </div>
            <input 
              type="text" 
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              className="w-full rounded-2xl border border-[var(--ow-line)] bg-white/90 py-2.5 pl-11 pr-4 text-base text-gray-900 placeholder:text-slate-400 focus:outline-none focus:border-blue-400 focus:ring-4 focus:ring-blue-500/10 transition-all shadow-sm" 
              placeholder={t.commands.searchPlaceholder}
            />
            <div className="absolute inset-y-0 right-0 pr-4 flex items-center">
              <kbd className="hidden sm:inline-flex items-center rounded border border-slate-200 bg-white px-2 py-0.5 text-xs font-mono text-slate-400">⌘K</kbd>
            </div>
          </div>

          {/* Segmented Filter */}
          <div className="mt-3 flex flex-wrap gap-4 items-center justify-between">
            <div className="flex flex-wrap gap-4 items-center">
              <div className="ow-segment inline-flex rounded-2xl p-1 overflow-x-auto">
                {(backendViews.map((value) => [
                  value,
                  backendViewLabels[value],
                ]) as ReadonlyArray<readonly [BackendView, string]>).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => {
                      setBackendView(value);
                      if (value === "bot") {
                        setSecondaryView("command");
                      }
                    }}
                    className={backendView === value 
                      ? "ow-segment-button-active px-4 py-1.5 text-sm font-semibold rounded-xl whitespace-nowrap"
                      : "ow-segment-button px-4 py-1.5 text-sm font-semibold rounded-xl transition-colors whitespace-nowrap hover:text-gray-700"}
                  >
                    {label}
                    <span className={`ml-1.5 rounded px-1.5 text-xs font-semibold ${backendView === value ? 'bg-slate-100 text-slate-500' : 'bg-white/60 text-slate-400'}`}>
                      {backendCounts[value]}
                    </span>
                  </button>
                ))}
              </div>
              
              {backendView !== "bot" && (
                <div className="ow-segment inline-flex rounded-2xl p-1 overflow-x-auto">
                  {(["command", "skill"] as const).map((value) => (
                    <button
                      key={value}
                      onClick={() => setSecondaryView(value)}
                      className={secondaryView === value
                        ? "ow-segment-button-active px-4 py-1.5 text-sm font-semibold rounded-xl whitespace-nowrap"
                        : "ow-segment-button px-4 py-1.5 text-sm font-semibold rounded-xl transition-colors whitespace-nowrap hover:text-gray-700"}
                    >
                      {value === "command" ? t.commands.secondaryCommand : t.commands.secondarySkill}
                      <span className={`ml-1.5 rounded px-1.5 text-xs font-semibold ${secondaryView === value ? 'bg-slate-100 text-slate-500' : 'bg-white/60 text-slate-400'}`}>
                        {secondaryCounts[value]}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            
            <div className="flex items-center gap-2 text-sm text-slate-500 font-medium">
              {registry?.hasUnpublishedChanges && (
                <span className="w-2 h-2 rounded-full bg-amber-400 mr-2" title={t.commands.unpublishedChanges}></span>
              )}
              <span className="w-2 h-2 rounded-full bg-green-500"></span>
              <span>{enabledCount} Selected</span>
            </div>
          </div>
        </div>
      </div>

      {/* List Content */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="max-w-5xl mx-auto w-full">
          
          {/* Warnings */}
          {notice && <div className="ow-page-frame-soft mb-4 rounded-2xl px-4 py-3 text-sm text-sky-800 border-sky-200 bg-sky-50/85">{notice}</div>}
          {aliasedSelectedNames.length > 0 && <div className="ow-page-frame-soft mb-4 rounded-2xl px-4 py-3 text-sm text-sky-800 border-sky-200 bg-sky-50/85">{t.commands.aliasedNamesWarning(aliasedSelectedNames.join(", "))}</div>}
          {duplicateSelectedNames.length > 0 && <div className="ow-page-frame-soft mb-4 rounded-2xl px-4 py-3 text-sm text-amber-800 border-amber-200 bg-amber-50/85">{t.commands.duplicateNamesWarning(duplicateSelectedNames.join(", "))}</div>}
          {publishMessage && <div className="ow-page-frame-soft mb-4 rounded-2xl px-4 py-3 text-sm text-emerald-800 border-emerald-200 bg-emerald-50/85">{publishMessage}</div>}
          {error && <div className="ow-page-frame-soft mb-4 rounded-2xl px-4 py-3 text-sm text-rose-800 border-rose-200 bg-rose-50/85">{t.commands.publishError(error)}</div>}

          {/* Modern List Container */}
          <div className="ow-page-frame-soft overflow-hidden rounded-[26px]">
            
            {/* List Header */}
            <div className="hidden sm:flex items-center justify-between border-b border-[var(--ow-line-soft)] bg-white/55 px-5 py-3 text-xs font-bold uppercase tracking-[0.12em] text-slate-500">
              <div className="flex items-center gap-4 w-1/3">
                <span className="ml-7">Command / Source</span>
              </div>
              <div className="w-1/2">Description</div>
              <div className="w-1/6 text-right pr-4">Scope</div>
            </div>

            {/* List Items */}
            <div className="divide-y divide-[var(--ow-line-soft)]">
              {loading ? (
                <div className="flex min-h-[240px] items-center justify-center py-10 text-center text-sm text-slate-500">
                  {t.common.loading}
                </div>
              ) : currentViewCommands.length === 0 ? (
                <div className="flex min-h-[240px] items-center justify-center py-10 text-center text-sm text-slate-500">
                  {t.commands.noResults}
                </div>
              ) : (
                currentViewCommands.map(renderCommandCard)
              )}
            </div>
          </div>
          
          <div className="mt-6 text-center pb-8">
            <p className="flex items-center justify-center gap-1.5 text-xs text-slate-400">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
              {t.commands.telegramRulesHint}
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}

export function CommandRegistry() {
  const {
    registry,
    loading,
    refreshing,
    publishing,
    updatingCommandId,
    error,
    refresh,
    setTelegramEnabled,
    publish,
  } = useCommandRegistry();
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);

  useEffect(() => {
    let cancelled = false;
    void fetchProviderMetadata()
      .then((metadata) => {
        if (!cancelled) {
          setProviders(metadata);
        }
      })
      .catch((error) => {
        console.warn("Failed to load command provider metadata", error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <CommandRegistryView
      registry={registry}
      loading={loading}
      refreshing={refreshing}
      publishing={publishing}
      updatingCommandId={updatingCommandId}
      error={error}
      onRefresh={refresh}
      onPublish={publish}
      onToggle={setTelegramEnabled}
      providers={providers}
    />
  );
}
