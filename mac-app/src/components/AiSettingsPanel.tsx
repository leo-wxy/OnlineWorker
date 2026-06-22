import { useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type {
  AiConfigMetadata,
  AiConnectionTestResult,
  AiScenarioMetadata,
  AiServiceMetadata,
} from "../types";
import { useI18n } from "../i18n";
import { AiScenarioEditor } from "./ai-settings/AiScenarioEditor";
import { AiServiceEditor } from "./ai-settings/AiServiceEditor";
import { AiSettingsSidebar } from "./ai-settings/AiSettingsSidebar";
import type { AiView } from "./ai-settings/utils";
import {
  scenariosForSave,
  serviceForSave,
  servicesForSave,
} from "./ai-settings/utils";

export function AiSettingsPanel() {
  const { t } = useI18n();
  const labels = t.ai;
  const common = t.common;
  const [activeView, setActiveView] = useState<AiView>("services");
  const [metadata, setMetadata] = useState<AiConfigMetadata>({ services: [], scenarios: [] });
  const [selectedServiceId, setSelectedServiceId] = useState("openai_default");
  const [selectedScenarioId, setSelectedScenarioId] = useState("notification_summary");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testingServiceId, setTestingServiceId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, AiConnectionTestResult>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const config = await invoke<AiConfigMetadata>("get_ai_config");
      setMetadata(config);
      setSelectedServiceId((current) => {
        if (config.services.some((service) => service.id === current)) {
          return current;
        }
        return config.services[0]?.id || "openai_default";
      });
      setSelectedScenarioId((current) => {
        if (config.scenarios.some((scenario) => scenario.id === current)) {
          return current;
        }
        return config.scenarios[0]?.id || "notification_summary";
      });
      setError(null);
    } catch (err) {
      setError(labels.loadError(String(err)));
    } finally {
      setLoading(false);
    }
  }, [labels]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedService = useMemo(
    () => metadata.services.find((service) => service.id === selectedServiceId) || metadata.services[0],
    [metadata.services, selectedServiceId],
  );
  const selectedScenario = useMemo(
    () => metadata.scenarios.find((scenario) => scenario.id === selectedScenarioId) || metadata.scenarios[0],
    [metadata.scenarios, selectedScenarioId],
  );
  const selectedScenarioService = selectedScenario
    ? metadata.services.find((service) => service.id === selectedScenario.serviceId) || null
    : null;

  const updateService = (id: string, patch: Partial<AiServiceMetadata>) => {
    setMetadata((current) => ({
      ...current,
      services: current.services.map((service) => service.id === id ? { ...service, ...patch } : service),
    }));
    setSaved(false);
  };

  const updateScenario = (id: string, patch: Partial<AiScenarioMetadata>) => {
    setMetadata((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario) => scenario.id === id ? { ...scenario, ...patch } : scenario),
    }));
    setSaved(false);
  };

  const updateScenarioLimit = (id: string, key: string, value: number) => {
    setMetadata((current) => ({
      ...current,
      scenarios: current.scenarios.map((scenario) => (
        scenario.id === id
          ? { ...scenario, limits: { ...scenario.limits, [key]: Math.max(1, Number(value || 1)) } }
          : scenario
      )),
    }));
    setSaved(false);
  };

  const persistMetadata = async (nextMetadata: AiConfigMetadata) => {
    setSaving(true);
    try {
      await invoke("set_ai_config", {
        services: servicesForSave(nextMetadata.services),
        scenarios: scenariosForSave(nextMetadata.scenarios),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1800);
      setError(null);
    } catch (err) {
      setError(labels.saveError(String(err)));
      void load();
    } finally {
      setSaving(false);
    }
  };

  const setServiceEnabled = (id: string, enabled: boolean) => {
    const nextMetadata = {
      ...metadata,
      services: metadata.services.map((service) => service.id === id ? { ...service, enabled } : service),
    };
    setMetadata(nextMetadata);
    setSaved(false);
    void persistMetadata(nextMetadata);
  };

  const setScenarioEnabled = (id: string, enabled: boolean) => {
    const nextMetadata = {
      ...metadata,
      scenarios: metadata.scenarios.map((scenario) => scenario.id === id ? { ...scenario, enabled } : scenario),
    };
    setMetadata(nextMetadata);
    setSaved(false);
    void persistMetadata(nextMetadata);
  };

  const deleteService = (serviceId: string) => {
    const service = metadata.services.find((item) => item.id === serviceId);
    if (service?.pluginOwned) {
      return;
    }
    setMetadata((current) => {
      const nextServices = current.services.filter((service) => service.id !== serviceId);
      const fallbackServiceId = nextServices[0]?.id || "";
      return {
        services: nextServices,
        scenarios: current.scenarios.map((scenario) => (
          scenario.serviceId === serviceId ? { ...scenario, serviceId: fallbackServiceId } : scenario
        )),
      };
    });
    setSelectedServiceId((current) => current === serviceId ? metadata.services[0]?.id || "" : current);
    setSaved(false);
  };

  const save = async () => {
    await persistMetadata(metadata);
    void load();
  };

  const testConnection = async (service: AiServiceMetadata) => {
    setTestingServiceId(service.id);
    try {
      const result = await invoke<AiConnectionTestResult>("test_ai_service_connection", {
        service: serviceForSave(service),
      });
      setTestResults((current) => ({ ...current, [service.id]: result }));
    } catch (err) {
      setTestResults((current) => ({
        ...current,
        [service.id]: { ok: false, status: null, message: String(err) },
      }));
    } finally {
      setTestingServiceId(null);
    }
  };

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-5">
      <div className="shrink-0">
        <h2 className="text-xl font-extrabold tracking-[-0.02em] text-gray-950">{labels.title}</h2>
        <p className="mt-1 max-w-3xl text-sm font-medium text-slate-500">{labels.description}</p>
      </div>

      {loading && (
        <div className="ow-page-frame-soft rounded-[24px] p-5 text-sm font-medium text-slate-500">
          {labels.loading}
        </div>
      )}

      {error && (
        <div className="ow-page-frame-soft rounded-[24px] border-rose-200 bg-rose-50/85 p-4 text-sm font-medium text-rose-700">
          {error}
        </div>
      )}

      {!loading && !error && (
        <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <AiSettingsSidebar
            activeView={activeView}
            labels={labels}
            services={metadata.services}
            scenarios={metadata.scenarios}
            selectedServiceId={selectedService?.id || selectedServiceId}
            selectedScenarioId={selectedScenario?.id || selectedScenarioId}
            onViewChange={setActiveView}
            onSelectService={setSelectedServiceId}
            onSelectScenario={setSelectedScenarioId}
          />

          <section className="ow-page-frame flex min-h-0 flex-col overflow-hidden rounded-[26px]">
            {activeView === "services" && selectedService && (
              <AiServiceEditor
                common={common}
                labels={labels}
                service={selectedService}
                saving={saving}
                saved={saved}
                testingServiceId={testingServiceId}
                testResult={testResults[selectedService.id]}
                onUpdate={updateService}
                onSetEnabled={setServiceEnabled}
                onDelete={deleteService}
                onSave={() => void save()}
                onTestConnection={(service) => void testConnection(service)}
              />
            )}

            {activeView === "scenarios" && selectedScenario && (
              <AiScenarioEditor
                common={common}
                labels={labels}
                scenario={selectedScenario}
                services={metadata.services}
                selectedService={selectedScenarioService}
                saving={saving}
                saved={saved}
                onUpdate={updateScenario}
                onUpdateLimit={updateScenarioLimit}
                onSetEnabled={setScenarioEnabled}
                onSave={() => void save()}
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
