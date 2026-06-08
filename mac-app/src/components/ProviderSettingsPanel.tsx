import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ProviderMetadata, ServiceStatus } from "../types";
import { useI18n } from "../i18n";
import {
  extensionProviderSettings,
  primaryProviderSettings,
} from "../utils/settingsProviders.js";

type ProviderSettingsMode = "agents" | "extensions";

interface Props {
  mode: ProviderSettingsMode;
}

function providerSettingClass(enabled: boolean) {
  return enabled
    ? "border-blue-100 bg-blue-50/70"
    : "border-slate-200/80 bg-slate-50/80 opacity-75";
}

function supportsLaunchMethods(provider: ProviderMetadata | undefined) {
  return provider?.capabilities.launchMethods === true;
}

const CIVILITY_MODE_SEALED = true;
const CODEX_REMOTE_PROXY_ALIAS =
  "alias codexR='/opt/homebrew/bin/codex --remote \"unix://$HOME/Library/Application Support/OnlineWorker/codex_remote_proxy.sock\" --cd \"$(pwd)\"'";

interface ProviderCliDraft {
  bin: string;
  launcherWrapsClaude: boolean;
  launchCommands: string;
}

function Toggle({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-10 shrink-0 rounded-full transition-colors ${
        checked ? "bg-blue-500" : "bg-slate-300"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <span
        className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function CopyCommandButton({ text }: { text: string }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="h-8 rounded-lg border border-slate-200 bg-white px-2.5 text-xs font-bold text-slate-700 transition hover:border-blue-200 hover:text-blue-700"
      title={copied ? t.common.copied : t.common.copy}
    >
      {copied ? t.common.copied : t.common.copy}
    </button>
  );
}

export function ProviderSettingsPanel({ mode }: Props) {
  const { t } = useI18n();
  const texts = t.providerSettings;
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [cliAvailability, setCliAvailability] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [savingCliProviderId, setSavingCliProviderId] = useState<string | null>(null);
  const [savingHookProviderId, setSavingHookProviderId] = useState<string | null>(null);
  const [cliDrafts, setCliDrafts] = useState<Record<string, ProviderCliDraft>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const metadata = await invoke<ProviderMetadata[]>("get_provider_metadata");
      setProviders(metadata);
      setCliDrafts(Object.fromEntries(
        metadata.map((provider) => [
          provider.id,
          {
            bin: provider.bin ?? provider.install?.cliNames?.[0] ?? provider.id,
            launcherWrapsClaude: provider.externalCli?.launcherWrapsClaude ?? false,
            launchCommands: (provider.launchMethods?.length
              ? provider.launchMethods.map((method) => method.bin).join("\n")
              : provider.bin ?? provider.install?.cliNames?.[0] ?? provider.id),
          },
        ])
      ));
      const availabilityEntries = await Promise.all(
        metadata.map(async (provider) => {
          const bin = provider.bin || provider.install?.cliNames?.[0] || provider.id;
          try {
            const available = await invoke<boolean>("check_cli", { bin });
            return [provider.id, available] as const;
          } catch {
            return [provider.id, false] as const;
          }
        })
      );
      setCliAvailability(Object.fromEntries(availabilityEntries));
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const settings = useMemo(
    () => mode === "agents" ? primaryProviderSettings(providers) : extensionProviderSettings(providers),
    [mode, providers]
  );

  const byId = useMemo(
    () => new Map(providers.map((provider) => [provider.id, provider])),
    [providers]
  );

  const saveProviderFlags = async (
    providerId: string,
    managed: boolean,
    autostart: boolean
  ) => {
    setSavingProviderId(providerId);
    try {
      await invoke("set_provider_flags", {
        providerId,
        managed,
        autostart: managed && autostart,
      });
      const status = await invoke<ServiceStatus>("service_status");
      if (status.running) {
        await invoke("service_restart");
      }
      startTransition(() => {
        void load();
      });
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingProviderId(null);
    }
  };

  const updateCliDraft = (
    providerId: string,
    patch: Partial<ProviderCliDraft>
  ) => {
    setCliDrafts((current) => {
      const provider = byId.get(providerId);
      const previous = current[providerId] ?? {
        bin: provider?.bin ?? provider?.install?.cliNames?.[0] ?? providerId,
        launcherWrapsClaude: provider?.externalCli?.launcherWrapsClaude ?? false,
        launchCommands: provider?.launchMethods?.length
          ? provider.launchMethods.map((method) => method.bin).join("\n")
          : provider?.bin ?? provider?.install?.cliNames?.[0] ?? providerId,
      };
      return {
        ...current,
        [providerId]: {
          ...previous,
          ...patch,
        },
      };
    });
  };

  const saveProviderCliConfig = async (provider: ProviderMetadata) => {
    const draft = cliDrafts[provider.id] ?? {
      bin: provider.bin ?? provider.install?.cliNames?.[0] ?? provider.id,
      launcherWrapsClaude: provider.externalCli?.launcherWrapsClaude ?? false,
      launchCommands: provider.launchMethods?.length
        ? provider.launchMethods.map((method) => method.bin).join("\n")
        : provider.bin ?? provider.install?.cliNames?.[0] ?? provider.id,
    };
    const canEditLaunchMethods = supportsLaunchMethods(provider);
    const launchCommands = draft.launchCommands
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    const primaryBin = canEditLaunchMethods
      ? launchCommands[0] ?? draft.bin.trim()
      : draft.bin.trim();
    const launchMethods = canEditLaunchMethods
      ? launchCommands.map((bin, index) => ({
          id: index === 0 ? "primary" : `method_${index + 1}`,
          label: index === 0 ? "Primary" : `Method ${index + 1}`,
          bin,
        }))
      : null;
    setSavingCliProviderId(provider.id);
    try {
      await invoke("set_provider_cli_config", {
        providerId: provider.id,
        bin: primaryBin,
        externalCli: {
          upstreamBaseUrl: null,
          launcherWrapsClaude: provider.id === "claude" && draft.launcherWrapsClaude,
        },
        launchMethods,
      });
      const status = await invoke<ServiceStatus>("service_status");
      if (status.running) {
        await invoke("service_restart");
      }
      startTransition(() => {
        void load();
      });
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingCliProviderId(null);
    }
  };

  const saveProviderCivilityMode = async (
    providerId: string,
    enabled: boolean
  ) => {
    setSavingHookProviderId(providerId);
    try {
      await invoke("set_provider_message_hook_enabled", {
        providerId,
        hookName: "abusive_language_normalization",
        enabled,
      });
      startTransition(() => {
        void load();
      });
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingHookProviderId(null);
    }
  };

  const title = mode === "agents" ? texts.titleAgents : texts.titleExtensions;
  const description = mode === "agents" ? texts.descriptionAgents : texts.descriptionExtensions;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-extrabold tracking-[-0.02em] text-gray-950">{title}</h2>
        <p className="mt-1 text-sm text-slate-500">{description}</p>
      </div>

      {loading && (
        <div className="rounded-2xl border border-slate-200 bg-white/80 p-5 text-sm text-slate-500">
          {texts.loading}
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/80 p-4 text-sm text-rose-700">
          {error}
        </div>
      )}

      {!loading && settings.length === 0 && (
        <div className="rounded-2xl border border-slate-200 bg-white/80 p-5 text-sm text-slate-500">
          {texts.empty(mode)}
        </div>
      )}

      <div className="grid gap-4">
        {settings.map((setting) => {
          const provider = byId.get(setting.id);
          const busy = savingProviderId === setting.id;
          const cliBusy = savingCliProviderId === setting.id;
          const hookBusy = savingHookProviderId === setting.id;
          const cliAvailable = cliAvailability[setting.id] !== false;
          const canEnable = setting.enabled || cliAvailable;
          const supportsExternalCliRewrite = Boolean(provider?.capabilities.messageRewrite?.externalCli);
          const showCodexRemoteProxyAlias = provider?.id === "codex";
          const canEditLaunchMethods = supportsLaunchMethods(provider);
          const supportsClaudeCliLauncher = provider?.id === "claude";
          const supportsMessageRewrite = !CIVILITY_MODE_SEALED && Boolean(
            provider?.capabilities.messageRewrite?.appSend ||
            provider?.capabilities.messageRewrite?.telegram ||
            provider?.capabilities.messageRewrite?.externalCli
          );
          const civilityModeEnabled = provider?.messageHooks?.abusiveLanguageNormalization.enabled ?? true;
          const draft = cliDrafts[setting.id] ?? {
            bin: provider?.bin ?? provider?.install?.cliNames?.[0] ?? setting.id,
            launcherWrapsClaude: provider?.externalCli?.launcherWrapsClaude ?? false,
            launchCommands: provider?.launchMethods?.length
              ? provider.launchMethods.map((method) => method.bin).join("\n")
              : provider?.bin ?? provider?.install?.cliNames?.[0] ?? setting.id,
          };
          const canSaveCliConfig = canEditLaunchMethods
            ? draft.launchCommands.split("\n").some((line) => line.trim())
            : Boolean(draft.bin.trim());
          return (
            <div
              key={setting.id}
              className={`rounded-2xl border p-5 transition-colors ${providerSettingClass(setting.enabled)} ${
                cliAvailable ? "" : "grayscale"
              }`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-bold text-gray-950">{setting.label}</h3>
                    <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${
                      !cliAvailable
                        ? "bg-amber-100 text-amber-700"
                        : setting.enabled
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-slate-200 text-slate-600"
                    }`}>
                      {!cliAvailable ? texts.cliMissing : setting.enabled ? texts.enabled : texts.disabled}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-slate-500">
                    {provider?.description || provider?.runtimeId || setting.id}
                  </p>
                  <p className="mt-2 truncate text-xs font-mono text-slate-500" title={provider?.bin ?? undefined}>
                    {provider?.bin ?? provider?.install?.cliNames?.[0] ?? setting.id}
                  </p>
                  {!cliAvailable && (
                    <p className="mt-2 text-xs font-semibold text-amber-700">
                      {texts.installCliHint}
                    </p>
                  )}
                </div>
                {busy && <span className="text-xs font-semibold text-blue-600">{texts.saving}</span>}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-6">
                <label className={`flex items-center gap-3 ${busy || !canEnable ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                  <Toggle
                    checked={setting.enabled}
                    disabled={busy || !canEnable}
                    onChange={(checked) => {
                      void saveProviderFlags(setting.id, checked, checked ? setting.autostart : false);
                    }}
                  />
                  <span className="text-sm font-semibold text-gray-700">{texts.enable}</span>
                </label>

                <label className={`flex items-center gap-3 ${!setting.enabled || busy ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                  <Toggle
                    checked={setting.enabled && setting.autostart}
                    disabled={!setting.enabled || busy}
                    onChange={(checked) => {
                      void saveProviderFlags(setting.id, true, checked);
                    }}
                  />
                  <span className="text-sm font-semibold text-gray-700">{texts.autostart}</span>
                </label>

                {provider && supportsMessageRewrite && (
                  <label className={`flex items-center gap-3 ${hookBusy ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                    <Toggle
                      checked={civilityModeEnabled}
                      disabled={hookBusy}
                      onChange={(checked) => {
                        void saveProviderCivilityMode(setting.id, checked);
                      }}
                    />
                    <span className="grid gap-0.5">
                      <span className="text-sm font-semibold text-gray-700">{texts.civilityModeTitle}</span>
                      <span className="text-xs font-medium text-slate-500">{texts.civilityModeDescription}</span>
                    </span>
                  </label>
                )}
              </div>

              {provider && (supportsExternalCliRewrite || showCodexRemoteProxyAlias || canEditLaunchMethods) && (
                <div className="mt-5 grid gap-3 rounded-xl border border-slate-200/80 bg-white/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-bold text-gray-900">{texts.cliConfigTitle}</h4>
                    {cliBusy && <span className="text-xs font-semibold text-blue-600">{texts.saving}</span>}
                  </div>
                  {showCodexRemoteProxyAlias && (
                    <div className="grid gap-2 border-l-2 border-blue-200 pl-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-xs font-bold text-blue-900">{texts.externalCliCodexAliasTitle}</div>
                          <div className="mt-0.5 text-xs font-medium text-blue-700">{texts.externalCliCodexAliasDescription}</div>
                        </div>
                        <CopyCommandButton text={CODEX_REMOTE_PROXY_ALIAS} />
                      </div>
                      <code className="block break-all rounded-md bg-slate-950 px-2.5 py-2 text-xs font-semibold text-slate-100">
                        {CODEX_REMOTE_PROXY_ALIAS}
                      </code>
                    </div>
                  )}
                  {(supportsExternalCliRewrite || canEditLaunchMethods) && (
                    <>
                      <div className="grid gap-3">
                        <label className="grid gap-1.5 text-xs font-bold text-slate-600">
                          {canEditLaunchMethods ? texts.launchMethodCommands : texts.externalCliBin}
                          {canEditLaunchMethods ? (
                            <textarea
                              value={draft.launchCommands}
                              disabled={cliBusy}
                              rows={3}
                              onChange={(event) => updateCliDraft(setting.id, {
                                launchCommands: event.currentTarget.value,
                                bin: event.currentTarget.value.split("\n").map((line) => line.trim()).find(Boolean) ?? draft.bin,
                              })}
                              className="min-h-[84px] resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-mono leading-5 text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                              placeholder={texts.launchMethodCommandsPlaceholder}
                            />
                          ) : (
                            <input
                              value={draft.bin}
                              disabled={cliBusy}
                              onChange={(event) => updateCliDraft(setting.id, { bin: event.currentTarget.value })}
                              className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-mono text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                            />
                          )}
                        </label>
                        {canEditLaunchMethods && (
                          <p className="text-xs font-medium leading-5 text-slate-500">
                            {texts.launchMethodCommandsHint}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-3">
                        {supportsClaudeCliLauncher && (
                          <label className={`mr-auto flex items-center gap-3 ${cliBusy ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                            <Toggle
                              checked={draft.launcherWrapsClaude}
                              disabled={cliBusy}
                              onChange={(checked) => updateCliDraft(setting.id, { launcherWrapsClaude: checked })}
                            />
                            <span className="text-sm font-semibold text-gray-700">{texts.externalCliLauncherWrapsClaude}</span>
                          </label>
                        )}
                        <button
                          type="button"
                          disabled={cliBusy || !canSaveCliConfig}
                          onClick={() => void saveProviderCliConfig(provider)}
                          className="h-9 rounded-lg bg-slate-900 px-3 text-sm font-bold text-white transition hover:bg-slate-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                        >
                          {texts.externalCliSave}
                        </button>
                      </div>
                    </>
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
