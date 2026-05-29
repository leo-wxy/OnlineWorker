import type { AiScenarioMetadata, AiServiceMetadata } from "../../types";
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
            <h3 className="text-base font-bold text-gray-950">
              {activeView === "services" ? labels.servicesTitle : labels.scenariosTitle}
            </h3>
            <p className="mt-1 text-xs font-medium leading-5 text-slate-500">
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
                    : "ow-segment-button hover:text-gray-700"
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
          const badge = serviceBadge(service, labels);
          return (
            <button
              key={service.id}
              type="button"
              onClick={() => onSelectService(service.id)}
              className={`grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border px-4 py-3 text-left transition-colors ${
                selected
                  ? service.enabled
                    ? "border-emerald-200 bg-emerald-50/80 shadow-sm"
                    : "border-blue-200 bg-white shadow-sm"
                  : service.enabled
                    ? "border-emerald-100 bg-emerald-50/45 hover:border-emerald-200 hover:bg-emerald-50/75"
                    : "border-transparent bg-white/45 hover:border-[var(--ow-line)] hover:bg-white/82"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-gray-950">{serviceTitle(service, labels)}</span>
                <span className="mt-1 block truncate text-xs font-medium text-slate-500">
                  {service.defaultModel || labels.noModel}
                </span>
              </span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                service.enabled
                  ? "bg-emerald-600 text-white shadow-sm shadow-emerald-200"
                  : "bg-slate-100 text-slate-500"
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
                    ? "border-emerald-200 bg-emerald-50/80 shadow-sm"
                    : "border-blue-200 bg-white shadow-sm"
                  : scenario.enabled
                    ? "border-emerald-100 bg-emerald-50/45 hover:border-emerald-200 hover:bg-emerald-50/75"
                    : "border-transparent bg-white/45 hover:border-[var(--ow-line)] hover:bg-white/82"
              }`}
            >
              <span className="min-w-0">
                <span className="block truncate text-sm font-bold text-gray-950">{scenarioTitle(scenario, labels)}</span>
                <span className="mt-1 block truncate text-xs font-medium text-slate-500">
                  {service ? serviceTitle(service, labels) : labels.noServiceSelected}
                </span>
              </span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                scenario.enabled
                  ? "bg-emerald-600 text-white shadow-sm shadow-emerald-200"
                  : "bg-slate-100 text-slate-500"
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
