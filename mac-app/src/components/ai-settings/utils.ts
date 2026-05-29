import type { useI18n } from "../../i18n";
import type { AiScenarioMetadata, AiServiceMetadata } from "../../types";

export type AiView = "services" | "scenarios";
export type AiLabels = ReturnType<typeof useI18n>["t"]["ai"];

export const BUILTIN_SERVICE_IDS = ["openai_default", "claude_default"];

export function serviceBadge(service: AiServiceMetadata, labels: AiLabels) {
  if (!service.enabled) {
    return labels.disabled;
  }
  if (!service.apiKey?.trim() || !service.defaultModel.trim()) {
    return labels.needsConfig;
  }
  return labels.configured;
}

export function scenarioBadge(
  scenario: AiScenarioMetadata,
  services: AiServiceMetadata[],
  labels: AiLabels,
) {
  if (!scenario.enabled) {
    return labels.disabled;
  }
  const service = services.find((item) => item.id === scenario.serviceId);
  if (!service || !service.enabled || !service.defaultModel.trim()) {
    return labels.needsConfig;
  }
  return labels.configured;
}

export function statusText(status: number | null | undefined) {
  return status ? `HTTP ${status}` : "-";
}

export function serviceTitle(service: AiServiceMetadata, labels: AiLabels) {
  if (service.id === "openai_default") {
    return labels.openaiService;
  }
  if (service.id === "claude_default") {
    return labels.claudeService;
  }
  return service.name || service.id;
}

export function serviceDescription(service: AiServiceMetadata, labels: AiLabels) {
  if (service.id === "openai_default") {
    return labels.openaiServiceDescription;
  }
  if (service.id === "claude_default") {
    return labels.claudeServiceDescription;
  }
  return labels.customServiceDescription;
}

export function scenarioTitle(scenario: AiScenarioMetadata, labels: AiLabels) {
  if (scenario.id === "notification_summary") {
    return labels.notificationSummaryScenario;
  }
  return scenario.id;
}

export function scenarioLimitEntries(scenario: AiScenarioMetadata): Array<[string, number]> {
  const limits = scenario.limits || {};
  if (scenario.id === "notification_summary") {
    return [
      ["preview_title", Number(limits.preview_title || 16)],
    ];
  }
  return Object.entries(limits).map(([key, value]) => [key, Number(value || 1)]);
}

export function limitLabel(key: string, labels: AiLabels) {
  return labels.limitLabels[key] || key;
}

export function serviceForSave(service: AiServiceMetadata) {
  return {
    id: service.id.trim(),
    name: service.name.trim(),
    protocol: service.protocol.trim(),
    baseUrl: (service.baseUrl || "").trim(),
    endpoint: (service.endpoint || "").trim(),
    apiKey: (service.apiKey || "").trim(),
    models: service.models.map((model) => model.trim()).filter(Boolean),
    defaultModel: service.defaultModel.trim(),
    timeoutSeconds: Math.max(1, Number(service.timeoutSeconds || 20)),
    enabled: service.enabled,
  };
}

export function servicesForSave(services: AiServiceMetadata[]) {
  return services.map(serviceForSave);
}

export function scenariosForSave(scenarios: AiScenarioMetadata[]) {
  return Object.fromEntries(
    scenarios.map((scenario) => [
      scenario.id,
      {
        enabled: scenario.enabled,
        serviceId: scenario.serviceId.trim(),
        model: "",
        outputSchema: scenario.outputSchema.trim(),
        fallback: scenario.fallback.trim(),
        limits: scenario.id === "notification_summary"
          ? { preview_title: Number(scenario.limits?.preview_title || 16) }
          : scenario.limits,
        promptTemplate: scenario.promptTemplate,
      },
    ]),
  );
}
