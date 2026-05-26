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

export function ProviderSettingsPanel({ mode }: Props) {
  const { t } = useI18n();
  const texts = t.providerSettings;
  const [providers, setProviders] = useState<ProviderMetadata[]>([]);
  const [cliAvailability, setCliAvailability] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const metadata = await invoke<ProviderMetadata[]>("get_provider_metadata");
      setProviders(metadata);
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
          const cliAvailable = cliAvailability[setting.id] !== false;
          const canEnable = setting.enabled || cliAvailable;
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
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
