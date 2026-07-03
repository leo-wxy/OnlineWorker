import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ProviderMetadata, ProviderValidationReport, ServiceStatus } from "../types";
import { useI18n } from "../i18n";
import {
  extensionProviderSettings,
  primaryProviderSettings,
} from "../utils/settingsProviders.js";

type ProviderSettingsMode = "agents" | "extensions";

interface Props {
  mode: ProviderSettingsMode;
}

function ProviderIcon({ provider }: { provider?: ProviderMetadata }) {
  const iconUrl = provider?.icon?.url?.trim();
  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt=""
        className="h-11 w-11 shrink-0 rounded-2xl border border-slate-200 bg-white object-contain p-1.5 shadow-sm"
      />
    );
  }
  const label = provider?.label?.trim() || provider?.id || "?";
  return (
    <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl border border-slate-200 bg-white text-sm font-bold text-slate-500 shadow-sm">
      {label.slice(0, 1).toUpperCase()}
    </span>
  );
}

function providerSettingClass(enabled: boolean) {
  return enabled
    ? "border-blue-100 bg-blue-50/70"
    : "border-slate-200/80 bg-slate-50/80 opacity-75";
}

function validationToneClass(report: ProviderValidationReport) {
  if (!report.ok) {
    return "border-rose-200 bg-rose-50/78 text-rose-800";
  }
  if (report.checks.some((check) => check.severity === "warning" && !check.ok)) {
    return "border-amber-200 bg-amber-50/80 text-amber-800";
  }
  return "border-emerald-200 bg-emerald-50/78 text-emerald-800";
}

function validationCheckDotClass(severity: string, ok: boolean) {
  if (severity === "error" || !ok) {
    return "bg-rose-500";
  }
  if (severity === "warning") {
    return "bg-amber-500";
  }
  return "bg-emerald-500";
}

function supportsLaunchMethods(provider: ProviderMetadata | undefined) {
  return provider?.capabilities.launchMethods === true;
}

function supportsExternalCliAuthConfig(provider: ProviderMetadata | undefined) {
  return provider?.capabilities.messageRewrite?.externalCli === "http_proxy";
}

function supportsExternalCliLauncherWrap(provider: ProviderMetadata | undefined) {
  return supportsLaunchMethods(provider) && supportsExternalCliAuthConfig(provider);
}

function showsManagedRemoteProxyAlias(provider: ProviderMetadata | undefined) {
  return Boolean(managedRemoteProxyAlias(provider));
}

const CIVILITY_MODE_SEALED = true;

function managedRemoteProxyAlias(provider: ProviderMetadata | undefined) {
  if (provider?.capabilities.messageRewrite?.externalCli !== "remote_proxy") {
    return "";
  }
  return provider.capabilities.messageRewrite.proxyAlias?.trim() ?? "";
}

interface ProviderCliDraft {
  bin: string;
  authToken: string;
  baseUrl: string;
  model: string;
  launchesManagedChildCli: boolean;
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
  const [validatingProviderId, setValidatingProviderId] = useState<string | null>(null);
  const [validationReports, setValidationReports] = useState<Record<string, ProviderValidationReport>>({});
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
            authToken: provider.externalCli?.authToken ?? "",
            baseUrl: provider.externalCli?.upstreamBaseUrl ?? "",
            model: provider.externalCli?.model ?? "",
            launchesManagedChildCli: provider.externalCli?.launchesManagedChildCli ?? false,
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

  const clearProviderValidationReport = (providerId: string) => {
    setValidationReports((current) => {
      if (!current[providerId]) {
        return current;
      }
      const remaining = { ...current };
      delete remaining[providerId];
      return remaining;
    });
  };

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
      clearProviderValidationReport(providerId);
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
    clearProviderValidationReport(providerId);
    setCliDrafts((current) => {
      const provider = byId.get(providerId);
      const previous = current[providerId] ?? {
        bin: provider?.bin ?? provider?.install?.cliNames?.[0] ?? providerId,
        authToken: provider?.externalCli?.authToken ?? "",
        baseUrl: provider?.externalCli?.upstreamBaseUrl ?? "",
        model: provider?.externalCli?.model ?? "",
        launchesManagedChildCli: provider?.externalCli?.launchesManagedChildCli ?? false,
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
      authToken: provider.externalCli?.authToken ?? "",
      baseUrl: provider.externalCli?.upstreamBaseUrl ?? "",
      model: provider.externalCli?.model ?? "",
      launchesManagedChildCli: provider.externalCli?.launchesManagedChildCli ?? false,
      launchCommands: provider.launchMethods?.length
        ? provider.launchMethods.map((method) => method.bin).join("\n")
        : provider.bin ?? provider.install?.cliNames?.[0] ?? provider.id,
    };
    const canEditLaunchMethods = supportsLaunchMethods(provider);
    const supportsExternalCliAuth = supportsExternalCliAuthConfig(provider);
    const supportsExternalCliLauncher = supportsExternalCliLauncherWrap(provider);
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
          upstreamBaseUrl: supportsExternalCliAuth ? draft.baseUrl.trim() || null : null,
          authToken: supportsExternalCliAuth ? draft.authToken.trim() || null : null,
          model: supportsExternalCliAuth ? draft.model.trim() || null : null,
          launchesManagedChildCli: supportsExternalCliLauncher && draft.launchesManagedChildCli,
        },
        launchMethods,
      });
      clearProviderValidationReport(provider.id);
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
      clearProviderValidationReport(providerId);
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

  const validateProviderConfig = async (providerId: string) => {
    if (validatingProviderId) {
      return;
    }
    setValidatingProviderId(providerId);
    try {
      const report = await invoke<ProviderValidationReport>("validate_provider_config", { providerId });
      setValidationReports((current) => ({
        ...current,
        [providerId]: report,
      }));
      setError(null);
    } catch (err) {
      setError(String(err));
    } finally {
      setValidatingProviderId(null);
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
          const validating = validatingProviderId === setting.id;
          const report = validationReports[setting.id];
          const hiddenByDefault = provider?.visible === false;
          const cliAvailable = cliAvailability[setting.id] !== false;
          const canEnable = setting.enabled || cliAvailable;
          const supportsExternalCliRewrite = Boolean(provider?.capabilities.messageRewrite?.externalCli);
          const remoteProxyAlias = managedRemoteProxyAlias(provider);
          const showManagedRemoteProxyAlias = showsManagedRemoteProxyAlias(provider);
          const canEditLaunchMethods = supportsLaunchMethods(provider);
          const supportsExternalCliAuth = supportsExternalCliAuthConfig(provider);
          const supportsExternalCliChildLauncher = supportsExternalCliLauncherWrap(provider);
          const supportsMessageRewrite = !CIVILITY_MODE_SEALED && Boolean(
            provider?.capabilities.messageRewrite?.appSend ||
            provider?.capabilities.messageRewrite?.telegram ||
            provider?.capabilities.messageRewrite?.externalCli
          );
          const civilityModeEnabled = provider?.messageHooks?.abusiveLanguageNormalization.enabled ?? true;
          const draft = cliDrafts[setting.id] ?? {
            bin: provider?.bin ?? provider?.install?.cliNames?.[0] ?? setting.id,
            authToken: provider?.externalCli?.authToken ?? "",
            baseUrl: provider?.externalCli?.upstreamBaseUrl ?? "",
            model: provider?.externalCli?.model ?? "",
            launchesManagedChildCli: provider?.externalCli?.launchesManagedChildCli ?? false,
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
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderIcon provider={provider} />
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
                      {hiddenByDefault && (
                        <span className="rounded-full bg-violet-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-violet-700">
                          {texts.hiddenByDefault}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      {provider?.description || provider?.runtimeId || setting.id}
                    </p>
                    <p className="mt-2 truncate text-xs font-mono text-slate-500" title={provider?.bin ?? undefined}>
                      {provider?.bin ?? provider?.install?.cliNames?.[0] ?? setting.id}
                    </p>
                    {hiddenByDefault && (
                      <p className="mt-2 text-xs font-medium text-violet-700">
                        {texts.hiddenByDefaultHint}
                      </p>
                    )}
                    {!cliAvailable && (
                      <p className="mt-2 text-xs font-semibold text-amber-700">
                        {texts.installCliHint}
                      </p>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                  {busy && <span className="text-xs font-semibold text-blue-600">{texts.saving}</span>}
                  <button
                    type="button"
                    disabled={Boolean(validatingProviderId)}
                    onClick={() => void validateProviderConfig(setting.id)}
                    className="h-8 rounded-lg border border-slate-200 bg-white/90 px-2.5 text-xs font-bold text-slate-700 transition hover:border-blue-200 hover:text-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {validating ? texts.validatingConfig : texts.validateConfig}
                  </button>
                </div>
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

              {report && (
                <div className={`mt-5 rounded-xl border p-4 ${validationToneClass(report)}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h4 className="text-sm font-bold">
                        {!report.ok
                          ? texts.validationFailed
                          : report.checks.some((check) => check.severity === "warning" && !check.ok)
                            ? texts.validationWarning
                            : texts.validationOk}
                      </h4>
                      <p className="mt-1 text-xs font-medium opacity-85">{report.summary}</p>
                    </div>
                    <span className="rounded-full bg-white/70 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] opacity-80">
                      {report.status}
                    </span>
                  </div>
                  <div className="mt-3 grid gap-2">
                    {report.checks.map((check) => (
                      <div key={check.id} className="flex gap-2 rounded-lg bg-white/58 px-3 py-2 text-xs">
                        <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${validationCheckDotClass(check.severity, check.ok)}`}></span>
                        <span className="min-w-0">
                          <span className="block font-bold">{check.label}</span>
                          {check.detail && <span className="mt-0.5 block opacity-80">{check.detail}</span>}
                          {check.remediation && <span className="mt-0.5 block font-semibold opacity-90">{check.remediation}</span>}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-3 break-all text-[11px] font-semibold opacity-75">
                    {texts.validationSource}: {report.sources.configPath}
                  </p>
                </div>
              )}

              {provider && (supportsExternalCliRewrite || showManagedRemoteProxyAlias || canEditLaunchMethods) && (
                <div className="mt-5 grid gap-3 rounded-xl border border-slate-200/80 bg-white/70 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-sm font-bold text-gray-900">{texts.cliConfigTitle}</h4>
                    {cliBusy && <span className="text-xs font-semibold text-blue-600">{texts.saving}</span>}
                  </div>
                  {showManagedRemoteProxyAlias && (
                    <div className="grid gap-2 border-l-2 border-blue-200 pl-3">
                      <div className="flex items-center justify-between gap-3">
                          <div className="min-w-0">
                          <div className="text-xs font-bold text-blue-900">{texts.externalCliProxyAliasTitle}</div>
                          <div className="mt-0.5 text-xs font-medium text-blue-700">{texts.externalCliProxyAliasDescription}</div>
                        </div>
                        <CopyCommandButton text={remoteProxyAlias} />
                      </div>
                      <code className="block break-all rounded-md bg-slate-950 px-2.5 py-2 text-xs font-semibold text-slate-100">
                        {remoteProxyAlias}
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
                        {supportsExternalCliAuth && (
                          <>
                            <label className="grid gap-1.5 text-xs font-bold text-slate-600">
                              {texts.externalCliAuthToken}
                              <input
                                type="password"
                                value={draft.authToken}
                                disabled={cliBusy}
                                onChange={(event) => updateCliDraft(setting.id, { authToken: event.currentTarget.value })}
                                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-mono text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                                placeholder={texts.externalCliAuthTokenPlaceholder}
                                autoComplete="off"
                                spellCheck={false}
                              />
                            </label>
                            <label className="grid gap-1.5 text-xs font-bold text-slate-600">
                              {texts.externalCliBaseUrl}
                              <input
                                type="text"
                                value={draft.baseUrl}
                                disabled={cliBusy}
                                onChange={(event) => updateCliDraft(setting.id, { baseUrl: event.currentTarget.value })}
                                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-mono text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                                placeholder={texts.externalCliBaseUrlPlaceholder}
                                autoComplete="off"
                                spellCheck={false}
                              />
                            </label>
                            <label className="grid gap-1.5 text-xs font-bold text-slate-600">
                              {texts.externalCliModel}
                              <input
                                type="text"
                                value={draft.model}
                                disabled={cliBusy}
                                onChange={(event) => updateCliDraft(setting.id, { model: event.currentTarget.value })}
                                className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-sm font-mono text-slate-800 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100"
                                placeholder={texts.externalCliModelPlaceholder}
                                autoComplete="off"
                                spellCheck={false}
                              />
                            </label>
                          </>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-3">
                        {supportsExternalCliChildLauncher && (
                          <label className={`mr-auto flex items-center gap-3 ${cliBusy ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                            <Toggle
                              checked={draft.launchesManagedChildCli}
                              disabled={cliBusy}
                              onChange={(checked) => updateCliDraft(setting.id, { launchesManagedChildCli: checked })}
                            />
                            <span className="text-sm font-semibold text-gray-700">{texts.externalCliLaunchesManagedChildCli}</span>
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
