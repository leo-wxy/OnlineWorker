import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import {
  ConfigEditor,
  LogWindow,
  ProviderSettingsPanel,
} from "./components";
import {
  CommandRegistry,
  Dashboard,
  SessionBrowser,
  SetupWizard,
  UsageBrowser,
} from "./pages";
import { useI18n, type Locale } from "./i18n";
import {
  isSupportedAppTab,
  PRIMARY_APP_TABS,
  type AppTab,
} from "./utils/appTabs.js";

const APP_NAVIGATE_TAB_EVENT = "app:navigate-tab";
const appWindow = getCurrentWindow();

export default function App() {
  const { locale, setLocale, t } = useI18n();
  const [activeTab, setActiveTab] = useState<AppTab>("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [settingsSection, setSettingsSection] = useState<"onlineworker" | "agents" | "extensions" | "advanced">("onlineworker");
  const [showLogs, setShowLogs] = useState(false);
  const [isFirstRun, setIsFirstRun] = useState(false);

  // First-run detection: auto-switch to Guide tab on first launch
  useEffect(() => {
    (async () => {
      try {
        const firstRun = await invoke<boolean>("check_first_run");
        if (firstRun) {
          await invoke("create_default_config");
          setActiveTab("setup");
          setIsFirstRun(true);
        }
      } catch {
        // If the command fails (e.g., dev mode without Tauri), just continue normally
      }
    })();
  }, []);

  useEffect(() => {
    let unlisten: (() => void) | null = null;

    void listen<string>(APP_NAVIGATE_TAB_EVENT, (event) => {
      if (!isSupportedAppTab(event.payload)) {
        return;
      }
      setActiveTab(event.payload);
      setShowLogs(false);
    })
      .then((dispose) => {
        unlisten = dispose;
      })
      .catch(() => {
        // Non-Tauri environments do not expose native event APIs.
      });

    return () => {
      if (unlisten) {
        unlisten();
      }
    };
  }, []);

  const getTabIcon = (tab: AppTab) => {
    switch (tab) {
      case "dashboard": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"></path></svg>;
      case "sessions": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M17 8h2a2 2 0 012 2v6a2 2 0 01-2 2h-2v4l-4-4H9a1.994 1.994 0 01-1.414-.586m0 0L11 14h4a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2v4l.586-.586z"></path></svg>;
      case "usage": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 12h3m4-6h3m-3 12h7m-7-6h7M7 6h.01M7 12h.01M7 18h.01"></path></svg>;
      case "commands": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>;
      case "setup": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>;
      case "config": return <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path></svg>;
      default: return null;
    }
  };

  const handleWindowDrag = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    void appWindow.startDragging().catch((error) => {
      console.error("Failed to start window dragging", error);
    });
  }, []);

  return (
    <div className="relative flex h-screen w-screen overflow-hidden ow-app-shell text-[var(--ow-text)]">
      {/* Sidebar Navigation */}
      <div className={`${sidebarCollapsed ? "w-[84px]" : "w-[248px]"} ow-sidebar flex h-full shrink-0 flex-col p-4 transition-[width] duration-150 ease-out`}>
        <div
          className="mb-3 h-8 shrink-0 select-none"
          data-tauri-drag-region
          onMouseDown={handleWindowDrag}
        />

        <div className={`ow-brand-card mb-5 flex min-h-16 items-center rounded-[22px] p-3 ${sidebarCollapsed ? "justify-center" : "gap-3"}`}>
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-600 via-blue-500 to-sky-500 shadow-[0_12px_26px_rgba(37,99,235,0.22)]">
            <svg className="h-5 w-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
          </div>
          <div
            aria-hidden={sidebarCollapsed}
            className={`min-w-0 overflow-hidden transition-[width,opacity] duration-150 ease-out ${
              sidebarCollapsed ? "w-0 opacity-0" : "flex-1 opacity-100"
            }`}
          >
            <span className="block truncate text-[17px] font-extrabold tracking-[-0.03em] text-gray-950">{t.app.title}</span>
            <span className="mt-0.5 block truncate text-[11px] font-semibold text-slate-500">Local AI workbench</span>
          </div>
        </div>

        <div className="mb-4">
          <button
            type="button"
            onClick={() => setSidebarCollapsed((current) => !current)}
            title={sidebarCollapsed ? t.app.sidebar.expand : t.app.sidebar.collapse}
            className={`ow-sidebar-toggle flex w-full items-center rounded-2xl px-3 py-2.5 text-sm font-bold transition-all ${
              sidebarCollapsed
                ? "justify-center border border-[var(--ow-line-soft)] bg-white/72 text-slate-600 hover:text-gray-900"
                : "gap-3 border border-[var(--ow-line-soft)] bg-white/72 text-slate-600 hover:bg-white/90 hover:text-gray-900"
            }`}
          >
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-white/60 text-slate-500">
              <svg
                className={`h-4 w-4 shrink-0 transition-transform ${sidebarCollapsed ? "rotate-180" : ""}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 19l-7-7 7-7" />
              </svg>
            </span>
            {!sidebarCollapsed && <span>{t.app.sidebar.collapse}</span>}
          </button>
        </div>
        
        <nav className="flex-1 space-y-1.5">
          {PRIMARY_APP_TABS.map((key) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              title={t.app.tabs[key]}
              className={`ow-tab-button w-full flex items-center rounded-2xl px-3 py-2.5 text-sm font-bold transition-all ${
                activeTab === key
                  ? "ow-tab-button-active bg-white/90 text-gray-950 shadow-[0_8px_24px_rgba(15,23,42,0.06)]"
                  : "text-slate-500 hover:bg-white/55 hover:text-gray-900"
              } ${sidebarCollapsed ? "justify-center" : "gap-3"}`}
            >
              <span className={`grid h-8 w-8 place-items-center rounded-xl ${
                activeTab === key ? "bg-blue-50 text-blue-600" : "bg-white/60 text-slate-400"
              }`}>
                {getTabIcon(key)}
              </span>
              {!sidebarCollapsed && t.app.tabs[key]}
            </button>
          ))}
        </nav>
        
        <div className="mt-auto space-y-3">
          {!sidebarCollapsed ? (
            <>
              <div className="ow-page-frame-soft rounded-2xl p-3">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">
                  {t.app.locale.label}
                </p>
                <div className="ow-segment grid w-full grid-cols-2 rounded-xl p-1">
                  {(["en", "zh"] as Locale[]).map((value) => (
                    <button
                      key={value}
                      onClick={() => setLocale(value)}
                      className={`rounded-lg px-3 py-1.5 text-xs font-bold transition-all ${
                        locale === value
                          ? "ow-segment-button-active"
                          : "ow-segment-button hover:text-gray-700"
                      }`}
                      title={value === "en" ? t.app.locale.en : t.app.locale.zh}
                    >
                      {value === "en" ? "EN" : "中文"}
                    </button>
                  ))}
                </div>
              </div>

              <div className="ow-page-frame-soft flex items-center gap-3 rounded-2xl p-3">
                <div className="h-2.5 w-2.5 rounded-full bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.13)]"></div>
                <div className="flex-1">
                  <p className="text-xs font-bold text-emerald-800">Service Active</p>
                  <p className="text-[10px] font-medium text-emerald-600">OnlineWorker</p>
                </div>
              </div>
            </>
          ) : (
            <div className="flex justify-center">
              <button
                type="button"
                onClick={() => setLocale(locale === "en" ? "zh" : "en")}
                className="ow-page-frame-soft flex h-10 w-10 items-center justify-center rounded-2xl text-[11px] font-bold text-slate-600"
                title={locale === "en" ? t.app.locale.zh : t.app.locale.en}
              >
                {locale === "en" ? "EN" : "中"}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="ow-main-surface flex-1 flex flex-col overflow-hidden relative">
        <div
          className="h-8 shrink-0 select-none"
          data-tauri-drag-region
          onMouseDown={handleWindowDrag}
        />

        {/* First-Run Banner */}
        {isFirstRun && (
          <div className="mx-5 mb-2 rounded-2xl border border-blue-100 bg-blue-50/85 px-4 py-2.5 flex items-center justify-between text-sm z-20 relative shadow-sm">
            <div className="flex items-center gap-2 text-blue-800">
              <span><strong>{t.app.firstRun.title}:</strong> {t.app.firstRun.description}</span>
            </div>
            <button
              onClick={() => setIsFirstRun(false)}
              className="text-blue-600 font-semibold hover:text-blue-800 underline"
              title={t.app.firstRun.dismiss}
            >
              {t.app.firstRun.dismiss}
            </button>
          </div>
        )}

        {/* Content */}
        <main
          className={`flex-1 flex flex-col min-h-0 ${
            activeTab === "sessions" || activeTab === "commands" || activeTab === "usage"
              ? "overflow-hidden overscroll-none"
              : "overflow-y-auto"
          }`}
        >
          {activeTab === "dashboard" && (
            <div className="h-full p-5 sm:p-6">
              <Dashboard
                onOpenLogs={() => setShowLogs(true)}
                onOpenSetup={() => setActiveTab("setup")}
                onOpenSessions={() => setActiveTab("sessions")}
              />
            </div>
          )}
          {activeTab === "config" && (
            <div className="h-full p-5 sm:p-6">
              <ConfigEditor />
            </div>
          )}
          {activeTab === "setup" && (
            <div className="h-full p-5 sm:p-6">
              <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
                <div className="ow-segment grid w-full grid-cols-4 rounded-2xl p-1">
                  {([
                    ["onlineworker", "OnlineWorker"],
                    ["agents", "Agents"],
                    ["extensions", "Extensions"],
                    ["advanced", "Advanced"],
                  ] as const).map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setSettingsSection(key)}
                      className={`rounded-xl px-3 py-2 text-sm font-bold transition-all ${
                        settingsSection === key
                          ? "ow-segment-button-active"
                          : "ow-segment-button hover:text-gray-700"
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {settingsSection === "onlineworker" && (
                  <div className="mx-auto w-full max-w-4xl">
                    <SetupWizard
                      onComplete={() => {
                        setIsFirstRun(false);
                        setActiveTab("dashboard");
                      }}
                      onOpenAdvancedConfig={() => setSettingsSection("advanced")}
                    />
                  </div>
                )}
                {settingsSection === "agents" && <ProviderSettingsPanel mode="agents" />}
                {settingsSection === "extensions" && <ProviderSettingsPanel mode="extensions" />}
                {settingsSection === "advanced" && <ConfigEditor />}
              </div>
            </div>
          )}
          {activeTab === "commands" && (
            <div className="flex min-h-0 flex-1 basis-0 flex-col overflow-hidden overscroll-none p-5 sm:p-6">
              <CommandRegistry />
            </div>
          )}
          {activeTab === "usage" && (
            <div className="flex min-h-0 flex-1 flex-col p-5 sm:p-6">
              <UsageBrowser />
            </div>
          )}
          {activeTab === "sessions" && (
            <div className="flex min-h-0 flex-1 flex-col p-5 sm:p-6">
              <SessionBrowser />
            </div>
          )}
        </main>
      </div>

      {/* Log Window modal */}
      {showLogs && <LogWindow onClose={() => setShowLogs(false)} />}
    </div>
  );
}
