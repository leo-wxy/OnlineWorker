import { useState, useEffect, useCallback } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ConnectivityTest } from "../components/ConnectivityTest";
import { useI18n } from "../i18n";
import { buildSetupCliToolsFromProviderMetadata } from "../utils/cliTools.js";
import type { ProviderMetadata } from "../types";

interface EnvStatus {
  token: string;
  userId: string;
  chatId: string;
  loaded: boolean;
  error: string | null;
}

interface CliToolStatus {
  name: string;
  label?: string;
  bin: string;
  install?: ProviderMetadata["install"] | null;
  installed: boolean | null;
}

const BOTFATHER_COMPLETED_STORAGE_KEY = "onlineworker.setup.botfather.completed";

interface Props {
  onComplete?: () => void;
  onOpenAdvancedConfig?: () => void;
}

function readBotFatherCompleted(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.localStorage.getItem(BOTFATHER_COMPLETED_STORAGE_KEY) === "1";
}

export function SetupWizard({ onComplete }: Props) {
  const { t } = useI18n();
  const setup = t.setup;
  const common = t.common;

  const [env, setEnv] = useState<EnvStatus>({
    token: "",
    userId: "",
    chatId: "",
    loaded: false,
    error: null,
  });
  const [cliTools, setCliTools] = useState<CliToolStatus[]>([]);
  const [cliChecking, setCliChecking] = useState(false);

  const [editToken, setEditToken] = useState("");
  const [editUserId, setEditUserId] = useState("");
  const [editChatId, setEditChatId] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showToken, setShowToken] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [botFatherCompleted, setBotFatherCompleted] = useState(readBotFatherCompleted);
  const [openInfo, setOpenInfo] = useState<number | null>(null);

  const checkCli = useCallback(async (tools: CliToolStatus[]) => {
    setCliChecking(true);
    const results = await Promise.all(
      tools.map(async (tool) => {
        try {
          const installed = await invoke<boolean>("check_cli", { bin: tool.bin });
          return { ...tool, installed };
        } catch {
          return { ...tool, installed: false };
        }
      })
    );
    setCliTools(results);
    setCliChecking(false);
  }, []);

  const loadProviderCliTools = useCallback(async () => {
    try {
      const providers = await invoke<ProviderMetadata[]>("get_provider_metadata");
      const tools = buildSetupCliToolsFromProviderMetadata(providers).map((tool) => ({
        ...tool,
        installed: null,
      }));
      setCliTools(tools);
      await checkCli(tools);
    } catch {
      setCliTools([]);
      setCliChecking(false);
    }
  }, [checkCli]);

  const loadEnv = useCallback(async () => {
    try {
      const [token, userId, chatId] = await Promise.all([
        invoke<string>("reveal_env_field", { key: "TELEGRAM_TOKEN" }).catch(() => ""),
        invoke<string>("read_env_field", { key: "ALLOWED_USER_ID" }).catch(() => ""),
        invoke<string>("read_env_field", { key: "GROUP_CHAT_ID" }).catch(() => ""),
      ]);
      setEnv({
        token,
        userId,
        chatId,
        loaded: true,
        error: null,
      });
      setEditToken(token);
      setEditUserId(userId);
      setEditChatId(chatId);
    } catch {
      setEnv({
        token: "",
        userId: "",
        chatId: "",
        loaded: true,
        error: null,
      });
    }
  }, []);

  useEffect(() => {
    void loadEnv();
    void loadProviderCliTools();
  }, [loadEnv, loadProviderCliTools]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(
      BOTFATHER_COMPLETED_STORAGE_KEY,
      botFatherCompleted ? "1" : "0"
    );
  }, [botFatherCompleted]);

  const anyCliInstalled = cliTools.some((tool) => tool.installed === true);
  const allConfigured = env.token.length > 0 && env.userId.length > 0 && env.chatId.length > 0;
  const hasChanges =
    editToken !== env.token ||
    editUserId !== env.userId ||
    editChatId !== env.chatId;
  const canLaunch = anyCliInstalled && allConfigured && botFatherCompleted;

  const persistEnv = async (): Promise<boolean> => {
    setSaving(true);
    setSaved(false);
    try {
      await invoke("write_env_field", { key: "TELEGRAM_TOKEN", value: editToken });
      await invoke("write_env_field", { key: "ALLOWED_USER_ID", value: editUserId });
      await invoke("write_env_field", { key: "GROUP_CHAT_ID", value: editChatId });
      await invoke("create_default_config");
      setEnv({
        token: editToken,
        userId: editUserId,
        chatId: editChatId,
        loaded: true,
        error: null,
      });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
      return true;
    } catch (e) {
      setEnv((prev) => ({ ...prev, error: String(e) }));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const saveEnv = async () => {
    await persistEnv();
  };

  const launchService = async () => {
    setLaunchError(null);
    setLaunching(true);
    try {
      if (hasChanges) {
        const persisted = await persistEnv();
        if (!persisted) {
          return;
        }
      }
      await invoke<string>("service_start");
      onComplete?.();
    } catch (e) {
      const errorText = String(e);
      setLaunchError(errorText);
      setEnv((prev) => ({ ...prev, error: errorText }));
    } finally {
      setLaunching(false);
    }
  };

  if (!env.loaded) {
    return <p className="py-8 text-center text-sm text-[var(--ow-subtle)]">{common.loading}</p>;
  }

  const toggleInfo = (id: number) => {
    setOpenInfo(openInfo === id ? null : id);
  };

  return (
    <div className="relative h-full w-full">
      <div className="mx-auto w-full max-w-4xl space-y-6 pb-32">
        
        <div>
          <h2 className="text-[28px] font-extrabold tracking-[-0.03em] text-[var(--ow-text)]">{setup.pageTitle}</h2>
          <p className="mt-2 text-sm font-medium text-[var(--ow-muted)]">{setup.pageDescription}</p>
        </div>

        <div className="relative space-y-6">
          {/* Vertical Line */}
          <div className="absolute left-[45px] top-10 bottom-0 hidden w-[2px] bg-[var(--ow-line-soft)] z-0 sm:block"></div>
          
          {/* Step 0: CLI */}
          <div className="ow-page-frame relative z-10 rounded-[26px] p-6">
            <div className="flex items-start gap-5">
              <div className="relative z-10 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--ow-green)] text-[var(--ow-on-accent)] shadow-sm ring-4 ring-[var(--ow-glass-highlight)]">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" /></svg>
              </div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[var(--ow-text)] text-base">{setup.step0Title}</h3>
                  <span className={`px-2.5 py-1 text-[10px] font-bold tracking-wider uppercase rounded-full border ${anyCliInstalled ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]" : "bg-[var(--ow-blue-soft)] text-[var(--ow-blue)] border-[var(--ow-blue)] shadow-sm"}`}>
                    {anyCliInstalled ? common.done : common.pending}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--ow-muted)]">{setup.step0Description}</p>
                
                <button onClick={() => toggleInfo(0)} className="ow-btn mt-4 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ow-muted)] hover:text-[var(--ow-green)]">
                  <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${openInfo === 0 ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" /></svg>
                  View Status
                </button>
                
                <div className={openInfo === 0 ? "mt-4" : "hidden mt-4"}>
                  <div className="ow-page-frame-soft space-y-3 rounded-2xl p-4 text-sm text-[var(--ow-muted)] shadow-none">
                    {cliTools.map((tool) => (
                      <div key={tool.name} className="flex items-center justify-between border-b border-[var(--ow-line)] pb-3 last:border-0 last:pb-0">
                        <div className="flex items-center gap-3">
                          <div className={`w-2.5 h-2.5 rounded-full ${tool.installed ? "bg-[var(--ow-green)] [box-shadow:var(--ow-shadow-sm)]" : tool.installed === false ? "bg-[var(--ow-red)] [box-shadow:var(--ow-shadow-sm)]" : "bg-[var(--ow-disabled-surface)] animate-pulse"}`}></div>
                          <p className="font-medium text-[var(--ow-text)]">{tool.label ?? tool.name}</p>
                          <p className="font-mono text-xs text-[var(--ow-muted)] bg-[var(--ow-panel)] px-2 py-0.5 rounded-md border border-[var(--ow-line)] shadow-sm">{tool.bin}</p>
                        </div>
                        {tool.installed === null ? (
                           <span className="text-xs font-medium text-[var(--ow-muted)] bg-[var(--ow-panel-soft)] px-2 py-0.5 rounded shadow-sm">{common.checking}</span>
                        ) : tool.installed ? (
                           <span className="text-xs font-medium text-[var(--ow-green)] bg-[var(--ow-green-soft)] px-2 py-0.5 rounded shadow-sm">{common.installed}</span>
                        ) : (
                           <span className="text-xs font-medium text-[var(--ow-error-text)] bg-[var(--ow-red-soft)] px-2 py-0.5 rounded shadow-sm">{common.notFound}</span>
                        )}
                      </div>
                    ))}
                    <div className="pt-2">
                       <button onClick={() => void checkCli(cliTools)} disabled={cliChecking} className="text-xs text-[var(--ow-blue)] hover:underline font-medium disabled:opacity-50">
                         {cliChecking ? common.checking : common.recheck}
                       </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 1: Token */}
          <div className="ow-page-frame relative z-10 rounded-[26px] p-6">
            <div className="flex items-start gap-5">
              <div className="relative z-10 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--ow-blue)] text-[var(--ow-on-accent)] shadow-sm ring-4 ring-[var(--ow-glass-highlight)]">
                <span className="font-bold text-lg leading-none">1</span>
              </div>
              <div className="flex-1 w-full">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[var(--ow-text)] text-base">{setup.step1Title}</h3>
                  <span className={`px-2.5 py-1 text-[10px] font-bold tracking-wider uppercase rounded-full border ${env.token.length > 0 ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]" : "bg-[var(--ow-blue-soft)] text-[var(--ow-blue)] border-[var(--ow-blue)] shadow-sm"}`}>
                    {env.token.length > 0 ? common.done : "Action Required"}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--ow-muted)]">{setup.step1Description}</p>
                
                <button onClick={() => toggleInfo(1)} className="ow-btn mt-4 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ow-muted)] hover:text-[var(--ow-blue)]">
                  <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${openInfo === 1 ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" /></svg>
                  How to do this?
                </button>
                
                <div className={openInfo === 1 ? "mt-4" : "hidden mt-4"}>
                  <div className="ow-page-frame-soft space-y-3 rounded-2xl border-[var(--ow-blue)] bg-[var(--ow-blue-soft)] p-5 text-sm text-[var(--ow-blue)] shadow-none">
                    <ol className="list-decimal list-inside space-y-2">
                      {setup.step1Instructions.map((inst: string, idx: number) => (
                        <li key={idx} dangerouslySetInnerHTML={{ __html: inst.replace('@BotFather', '<strong>@BotFather</strong>').replace('/newbot', '<code className="bg-[var(--ow-panel)] border border-[var(--ow-blue)] px-1.5 py-0.5 rounded-md font-mono text-xs shadow-sm">/newbot</code>') }}></li>
                      ))}
                    </ol>
                  </div>
                </div>
                
                <div className="mt-6 relative">
                  <label className="block text-xs font-bold text-[var(--ow-muted)] uppercase tracking-wider mb-2 ml-1">{setup.botToken}</label>
                  <div className="relative">
                    <input 
                      type={showToken ? "text" : "password"}
                      value={editToken}
                      onChange={(e) => setEditToken(e.target.value)}
                      placeholder={setup.tokenPlaceholder} 
                      className="w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] shadow-inner px-4 py-3 pr-10 text-sm font-mono focus:outline-none focus:ring-4 focus:ring-[var(--ow-focus)] focus:border-[var(--ow-blue)] focus:bg-[var(--ow-panel)] transition-colors placeholder:text-[var(--ow-subtle)] text-[var(--ow-text)]"
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken(!showToken)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 px-1 text-sm text-[var(--ow-subtle)] hover:text-[var(--ow-muted)]"
                      title={showToken ? setup.hideToken : setup.showToken}
                    >
                      {showToken ? (
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>
                      ) : (
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Step 2: User ID */}
          <div className="ow-page-frame relative z-10 rounded-[26px] p-6">
            <div className="flex items-start gap-5">
              <div className="relative z-10 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--ow-purple)] text-[var(--ow-on-accent)] shadow-sm ring-4 ring-[var(--ow-glass-highlight)]">
                <span className="font-bold text-lg leading-none">2</span>
              </div>
              <div className="flex-1 w-full">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[var(--ow-text)] text-base">{setup.step2Title}</h3>
                  <span className={`px-2.5 py-1 text-[10px] font-bold tracking-wider uppercase rounded-full border ${env.userId.length > 0 ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]" : "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)] border-[var(--ow-line)] shadow-sm"}`}>
                    {env.userId.length > 0 ? common.done : common.pending}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--ow-muted)]">{setup.step2Description}</p>
                
                <button onClick={() => toggleInfo(2)} className="ow-btn mt-4 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ow-muted)] hover:text-[var(--ow-purple)]">
                  <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${openInfo === 2 ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" /></svg>
                  How to do this?
                </button>
                
                <div className={openInfo === 2 ? "mt-4" : "hidden mt-4"}>
                  <div className="ow-page-frame-soft space-y-3 rounded-2xl border-[var(--ow-purple)] bg-[var(--ow-purple-soft)] p-5 text-sm text-[var(--ow-purple)] shadow-none">
                    <ol className="list-decimal list-inside space-y-2">
                      {setup.step2Instructions.map((inst: string, idx: number) => (
                        <li key={idx} dangerouslySetInnerHTML={{ __html: inst.replace('@userinfobot', '<strong>@userinfobot</strong>') }}></li>
                      ))}
                    </ol>
                  </div>
                </div>
                
                <div className="mt-6">
                  <label className="block text-xs font-bold text-[var(--ow-muted)] uppercase tracking-wider mb-2 ml-1">{setup.userId}</label>
                  <input 
                    type="text" 
                    value={editUserId}
                    onChange={(e) => setEditUserId(e.target.value.replace(/[^0-9]/g, ""))}
                    placeholder={setup.userIdPlaceholder} 
                    className="w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] shadow-inner px-4 py-3 text-sm font-mono focus:outline-none focus:ring-4 focus:ring-[var(--ow-purple)] focus:border-[var(--ow-purple)] focus:bg-[var(--ow-panel)] transition-colors placeholder:text-[var(--ow-subtle)] text-[var(--ow-text)]"
                  />
                  <p className="mt-2 text-xs text-[var(--ow-subtle)] ml-1">{setup.step2Hint}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Step 3: Group ID */}
          <div className="ow-page-frame relative z-10 rounded-[26px] p-6">
            <div className="flex items-start gap-5">
              <div className="relative z-10 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--ow-red)] text-[var(--ow-on-accent)] shadow-sm ring-4 ring-[var(--ow-glass-highlight)]">
                <span className="font-bold text-lg leading-none">3</span>
              </div>
              <div className="flex-1 w-full">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[var(--ow-text)] text-base">{setup.step3Title}</h3>
                  <span className={`px-2.5 py-1 text-[10px] font-bold tracking-wider uppercase rounded-full border ${env.chatId.length > 0 ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]" : "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)] border-[var(--ow-line)] shadow-sm"}`}>
                    {env.chatId.length > 0 ? common.done : common.pending}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--ow-muted)]">{setup.step3Description}</p>
                
                <button onClick={() => toggleInfo(3)} className="ow-btn mt-4 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ow-muted)] hover:text-[var(--ow-error-text)]">
                  <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${openInfo === 3 ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" /></svg>
                  How to do this?
                </button>
                
                <div className={openInfo === 3 ? "mt-4" : "hidden mt-4"}>
                  <div className="ow-page-frame-soft space-y-3 rounded-2xl border-[var(--ow-red)] bg-[var(--ow-red-soft)] p-5 text-sm text-[var(--ow-error-text)] shadow-none">
                    <p className="font-medium mt-1">{setup.step3SectionA}</p>
                    <ol className="list-decimal list-inside space-y-1">
                      {setup.step3A.map((inst: string, idx: number) => <li key={idx}>{inst}</li>)}
                    </ol>
                    <p className="font-medium mt-3">{setup.step3SectionB}</p>
                    <ol className="list-decimal list-inside space-y-1">
                      {setup.step3B.map((inst: string, idx: number) => <li key={idx} dangerouslySetInnerHTML={{ __html: inst.replace('@getidsbot', '<strong>@getidsbot</strong>') }}></li>)}
                    </ol>
                  </div>
                </div>
                
                <div className="mt-6">
                  <label className="block text-xs font-bold text-[var(--ow-muted)] uppercase tracking-wider mb-2 ml-1">{setup.groupChatId}</label>
                  <input 
                    type="text" 
                    value={editChatId}
                    onChange={(e) => setEditChatId(e.target.value.replace(/[^0-9-]/g, ""))}
                    placeholder={setup.groupChatIdPlaceholder} 
                    className="w-full rounded-xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] shadow-inner px-4 py-3 text-sm font-mono focus:outline-none focus:ring-4 focus:ring-[var(--ow-red)] focus:border-[var(--ow-red)] focus:bg-[var(--ow-panel)] transition-colors placeholder:text-[var(--ow-subtle)] text-[var(--ow-text)]"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Step 4: BotFather Settings */}
          <div className="ow-page-frame relative z-10 rounded-[26px] p-6">
            <div className="flex items-start gap-5">
              <div className="relative z-10 flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-[var(--ow-amber)] text-[var(--ow-on-accent)] shadow-sm ring-4 ring-[var(--ow-glass-highlight)]">
                <span className="font-bold text-lg leading-none">4</span>
              </div>
              <div className="flex-1 w-full">
                <div className="flex items-center justify-between">
                  <h3 className="font-bold text-[var(--ow-text)] text-base">{setup.step4Title}</h3>
                  <span className={`px-2.5 py-1 text-[10px] font-bold tracking-wider uppercase rounded-full border ${botFatherCompleted ? "bg-[var(--ow-green-soft)] text-[var(--ow-green)] border-[var(--ow-green)]" : "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)] border-[var(--ow-line)] shadow-sm"}`}>
                    {botFatherCompleted ? common.done : common.pending}
                  </span>
                </div>
                <p className="mt-1 text-sm text-[var(--ow-muted)]">{setup.step4Description}</p>
                
                <button onClick={() => toggleInfo(4)} className="ow-btn mt-4 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-[var(--ow-muted)] hover:text-[var(--ow-warning-text)]">
                  <svg className={`w-3.5 h-3.5 transition-transform duration-300 ${openInfo === 4 ? "rotate-90" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" /></svg>
                  How to do this?
                </button>
                
                <div className={openInfo === 4 ? "mt-4" : "hidden mt-4"}>
                  <div className="ow-page-frame-soft space-y-3 rounded-2xl border-[var(--ow-amber)] bg-[var(--ow-amber-soft)] p-5 text-sm text-[var(--ow-warning-text)] shadow-none">
                    <p className="font-medium mt-1">{setup.step4Required}</p>
                    <ol className="list-decimal list-inside space-y-2">
                      {setup.step4RequiredSteps.map((inst: string, idx: number) => (
                        <li key={idx} dangerouslySetInnerHTML={{ __html: inst.replace('@BotFather', '<strong>@BotFather</strong>').replace('/mybots', '<code className="bg-[var(--ow-panel)] border border-[var(--ow-amber)] px-1.5 py-0.5 rounded-md font-mono text-xs shadow-sm">/mybots</code>') }}></li>
                      ))}
                    </ol>
                  </div>
                </div>
                
                <label className="ow-page-frame-soft mt-6 flex cursor-pointer items-center gap-4 rounded-2xl p-5 shadow-none transition-colors hover:border-[var(--ow-amber)] hover:bg-[var(--ow-panel)]">
                  <input 
                    type="checkbox" 
                    checked={botFatherCompleted}
                    onChange={(e) => setBotFatherCompleted(e.target.checked)}
                    className="w-5 h-5 border-[var(--ow-line)] rounded text-[var(--ow-warning-text)] focus:ring-[var(--ow-amber)] cursor-pointer shadow-sm"
                  />
                  <span className="text-sm font-medium text-[var(--ow-text)]">{setup.step4MarkDone}</span>
                </label>
              </div>
            </div>
          </div>
          
        </div>

        {/* Connectivity Test block (if fields filled) */}
        {env.token && env.chatId && (
          <div className="ow-page-frame mt-8 rounded-[26px] p-6">
            <ConnectivityTest token={editToken || env.token} chatId={editChatId || env.chatId} />
          </div>
        )}

      </div>

      {/* Floating Action Bar (Mac Dock Style) */}
      <div className="fixed bottom-6 left-1/2 md:left-[calc(50%+120px)] -translate-x-1/2 z-40 w-[90%] max-w-2xl">
        <div className="ow-floating-dock rounded-[26px] border border-[var(--ow-line-soft)] px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="hidden items-center gap-2 text-sm font-medium text-[var(--ow-muted)] sm:flex">
              <div className={`w-2 h-2 rounded-full ${canLaunch ? "bg-[var(--ow-green)] animate-pulse" : "bg-[var(--ow-amber)]"}`}></div>
              {canLaunch ? setup.launchReady : setup.summaryNextAction}
            </div>
            <div className="flex w-full items-center justify-end gap-3 sm:w-auto">
              <button 
                onClick={saveEnv} 
                disabled={!hasChanges || saving || launching}
                className="ow-btn rounded-xl px-5 py-2.5 text-sm font-semibold text-[var(--ow-text)] transition-colors disabled:opacity-50"
              >
                {saving ? common.saving : saved ? common.saved : setup.saveChanges}
              </button>
              <button 
                onClick={launchService} 
                disabled={!canLaunch || saving || launching}
                className="ow-btn-primary rounded-xl px-5 py-2.5 text-sm font-semibold disabled:opacity-50"
              >
                {launching ? setup.launching : hasChanges ? setup.saveAndLaunch : setup.launchAndOpen}
              </button>
            </div>
          </div>
        </div>
      </div>
      
      {/* Error Messages overlay */}
      {(env.error || launchError) && (
        <div className="fixed top-24 left-1/2 -translate-x-1/2 z-50 w-[90%] max-w-md">
          <div className="rounded-xl border border-[var(--ow-red)] bg-[var(--ow-red-soft)] px-4 py-3 text-sm text-[var(--ow-error-text)] shadow-lg flex justify-between items-start">
             <span>{launchError ? setup.launchError(launchError) : env.error}</span>
             <button onClick={() => { setLaunchError(null); setEnv(p => ({...p, error: null})) }} className="text-[var(--ow-error-text)] hover:opacity-70 ml-3">✕</button>
          </div>
        </div>
      )}
    </div>
  );
}

export const GuideTab = SetupWizard;
