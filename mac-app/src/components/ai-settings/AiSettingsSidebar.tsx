import type { AiConnectionTestResult, AiScenarioMetadata, AiServiceMetadata } from "../../types";
import type { AiLabels, AiView } from "./utils";
import {
  scenarioBadge,
  scenarioTitle,
  serviceBadge,
  serviceTitle,
} from "./utils";

export function AiSettingsSidebar({
  activeView,
  labels,
  services,
  scenarios,
  testResults,
  testingServiceId,
  selectedServiceId,
  selectedScenarioId,
  onViewChange,
  onSelectService,
  onSelectScenario,
}: {
  activeView: AiView;
  labels: AiLabels;
  services: AiServiceMetadata[];
  scenarios: AiScenarioMetadata[];
  testResults: Record<string, AiConnectionTestResult>;
  testingServiceId: string | null;
  selectedServiceId: string;
  selectedScenarioId: string;
  onViewChange: (view: AiView) => void;
  onSelectService: (id: string) => void;
  onSelectScenario: (id: string) => void;
}) {
  return (
    <aside className="ow-page-frame-soft flex min-h-0 flex-col overflow-hidden rounded-[26px]">
      <div className="border-b border-[var(--ow-line-soft)] px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-bold text-[var(--ow-text)]">
              {activeView === "services" ? labels.servicesTitle : labels.scenariosTitle}
            </h3>
            <p className="mt-1 text-xs font-medium leading-5 text-[var(--ow-muted)]">
              {activeView === "services" ? labels.servicesDescription : labels.scenariosDescription}
            </p>
          </div>
          <div className="ow-segment grid shrink-0 grid-cols-2 rounded-2xl p-1">
            {(["services", "scenarios"] as AiView[]).map((view) => (
              <button
                key={view}
                type="button"
                onClick={() => onViewChange(view)}
                className={`rounded-xl px-3 py-1.5 text-xs font-bold transition-colors ${
                  activeView === view
                    ? "ow-segment-button-active"
                    : "ow-segment-button hover:text-[var(--ow-text)]"
                }`}
              >
                {view === "services" ? labels.servicesTab : labels.scenariosTab}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {activeView === "services" && services.map((service) => {
          const selected = selectedServiceId === service.id;
          const testResult = testResults[service.id];
          const checking = testingServiceId === service.id;
          const badge = serviceBadge(service, labels, testResult, checking);
          const badgeFailed = service.enabled && testResult && !testResult.ok;
          return (
            <button
              key={service.id}
              type="button"
              onClick={() => onSelectService(service.id)}
              className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-colors ${
                selected
                  ? service.enabled
                    ? "border-[var(--ow-green)] bg-[var(--ow-green-soft)] shadow-sm"
                    : "border-[var(--ow-blue)] bg-[var(--ow-panel)] shadow-sm"
                  : service.enabled
                    ? "border-[var(--ow-green)] bg-[var(--ow-green-soft)] hover:brightness-105"
                    : "border-transparent bg-[var(--ow-panel)] hover:border-[var(--ow-line)] hover:bg-[var(--ow-hover)]"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-[var(--ow-text)]">{serviceTitle(service, labels)}</span>
                <span className="mt-1 block truncate text-xs font-medium text-[var(--ow-muted)]">
                  {service.description || service.defaultModel || labels.noModel}
                </span>
              </span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                badgeFailed
                  ? "bg-[var(--ow-red)] text-[var(--ow-on-accent)] shadow-sm"
                  : service.enabled
                  ? "bg-[var(--ow-green)] text-[var(--ow-on-accent)] shadow-sm"
                  : "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]"
              }`}>
                {badge}
              </span>
            </button>
          );
        })}

        {activeView === "scenarios" && scenarios.map((scenario) => {
          const selected = selectedScenarioId === scenario.id;
          const badge = scenarioBadge(scenario, services, labels);
          const service = services.find((item) => item.id === scenario.serviceId);
          return (
            <button
              key={scenario.id}
              type="button"
              onClick={() => onSelectScenario(scenario.id)}
              className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-colors ${
                selected
                  ? scenario.enabled
                    ? "border-[var(--ow-green)] bg-[var(--ow-green-soft)] shadow-sm"
                    : "border-[var(--ow-blue)] bg-[var(--ow-panel)] shadow-sm"
                  : scenario.enabled
                    ? "border-[var(--ow-green)] bg-[var(--ow-green-soft)] hover:brightness-105"
                    : "border-transparent bg-[var(--ow-panel)] hover:border-[var(--ow-line)] hover:bg-[var(--ow-hover)]"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-[var(--ow-text)]">{scenarioTitle(scenario, labels)}</span>
                <span className="mt-1 block truncate text-xs font-medium text-[var(--ow-muted)]">
                  {service ? serviceTitle(service, labels) : labels.noServiceSelected}
                </span>
              </span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                scenario.enabled
                  ? "bg-[var(--ow-green)] text-[var(--ow-on-accent)] shadow-sm"
                  : "bg-[var(--ow-panel-soft)] text-[var(--ow-muted)]"
              }`}>
                {badge}
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
