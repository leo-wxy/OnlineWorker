import type { useI18n } from "../../i18n";
import type { AiScenarioMetadata, AiServiceMetadata } from "../../types";
import { NumberField, TextField, Toggle } from "./fields";
import type { AiLabels } from "./utils";
import {
  limitLabel,
  scenarioLimitEntries,
  scenarioTitle,
  serviceTitle,
  serviceUsesProviderLogin,
} from "./utils";

type CommonLabels = ReturnType<typeof useI18n>["t"]["common"];

export function AiScenarioEditor({
  common,
  labels,
  scenario,
  services,
  selectedService,
  saving,
  saved,
  onUpdate,
  onUpdateLimit,
  onSetEnabled,
  onSave,
}: {
  common: CommonLabels;
  labels: AiLabels;
  scenario: AiScenarioMetadata;
  services: AiServiceMetadata[];
  selectedService: AiServiceMetadata | null;
  saving: boolean;
  saved: boolean;
  onUpdate: (id: string, patch: Partial<AiScenarioMetadata>) => void;
  onUpdateLimit: (id: string, key: string, value: number) => void;
  onSetEnabled: (id: string, enabled: boolean) => void;
  onSave: () => void;
}) {
  return (
    <>
      <div className="border-b border-[var(--ow-line-soft)] px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-wider text-[var(--ow-subtle)]">{labels.scenarioConfigTitle}</p>
            <h3 id={`ai-scenario-${scenario.id}-title`} className="mt-1 text-xl font-extrabold tracking-[-0.02em] text-[var(--ow-text)]">
              {scenarioTitle(scenario, labels)}
            </h3>
            <p className="mt-3 max-w-2xl text-sm font-medium leading-6 text-[var(--ow-muted)]">
              {labels.scenarioDetailDescription}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {saved && <span className="text-xs font-bold text-[var(--ow-green)]">{common.saved}</span>}
            {saving && <span className="text-xs font-bold text-[var(--ow-blue)]">{common.saving}</span>}
            <label className={`flex items-center gap-3 rounded-xl border border-[var(--ow-line-soft)] bg-[var(--ow-panel-soft)] px-3 py-2 ${saving ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
              <span className="text-sm font-semibold text-[var(--ow-text)]">{labels.enableScenario}</span>
              <Toggle
                checked={scenario.enabled}
                disabled={saving}
                labelledBy={`ai-scenario-${scenario.id}-title`}
                onChange={(checked) => onSetEnabled(scenario.id, checked)}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="ow-page-frame-soft divide-y divide-[var(--ow-line-soft)] overflow-hidden rounded-[24px] shadow-none">
          <div className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
            <label htmlFor={`ai-scenario-${scenario.id}-service`} className="text-sm font-bold text-[var(--ow-text)]">
              {labels.service}
            </label>
            <select
              id={`ai-scenario-${scenario.id}-service`}
              value={scenario.serviceId}
              disabled={saving}
              onChange={(event) => onUpdate(scenario.id, { serviceId: event.target.value, model: "" })}
              className="block w-full rounded-2xl border border-[var(--ow-line)] bg-[var(--ow-panel)] px-4 py-3 text-sm font-medium text-[var(--ow-text)] outline-none transition-colors focus:border-[var(--ow-blue)] focus:ring-4 focus:ring-[var(--ow-focus)] disabled:cursor-not-allowed disabled:bg-[var(--ow-panel-soft)] disabled:text-[var(--ow-subtle)]"
            >
              {services.map((service) => (
                <option key={service.id} value={service.id}>
                  {serviceTitle(service, labels)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
            <span className="text-sm font-bold text-[var(--ow-text)]">{labels.effectiveModel}</span>
            <div className="rounded-2xl border border-[var(--ow-line)] bg-[var(--ow-panel-soft)] px-4 py-3 text-sm font-semibold text-[var(--ow-text)]">
              {serviceUsesProviderLogin(selectedService)
                ? labels.providerDefaultModel
                : selectedService?.defaultModel || labels.noModel}
            </div>
          </div>
          <TextField
            id={`ai-scenario-${scenario.id}-schema`}
            label={labels.outputSchema}
            value={scenario.outputSchema}
            disabled={saving}
            onChange={(value) => onUpdate(scenario.id, { outputSchema: value })}
          />
          <TextField
            id={`ai-scenario-${scenario.id}-fallback`}
            label={labels.fallback}
            value={scenario.fallback}
            disabled={saving}
            onChange={(value) => onUpdate(scenario.id, { fallback: value })}
          />
          {scenarioLimitEntries(scenario).map(([key, value]) => (
            <NumberField
              key={key}
              id={`ai-scenario-${scenario.id}-limit-${key}`}
              label={limitLabel(key, labels)}
              value={value}
              disabled={saving}
              onChange={(nextValue) => onUpdateLimit(scenario.id, key, nextValue)}
            />
          ))}
        </div>

        <div className="mt-5 rounded-[24px] border border-[var(--ow-line-soft)] bg-[var(--ow-panel)] p-5 shadow-none">
          <label htmlFor={`ai-scenario-${scenario.id}-prompt`} className="text-sm font-bold text-[var(--ow-text)]">
            {labels.promptTemplate}
          </label>
          <textarea
            id={`ai-scenario-${scenario.id}-prompt`}
            value={scenario.promptTemplate}
            disabled={saving}
            onChange={(event) => onUpdate(scenario.id, { promptTemplate: event.target.value })}
            placeholder={labels.emptyPrompt}
            className="mt-3 min-h-[300px] w-full resize-y rounded-2xl border border-[var(--ow-line)] bg-[var(--ow-code)] p-4 font-mono text-xs leading-5 text-[var(--ow-text)] outline-none focus:border-[var(--ow-blue)] focus:ring-4 focus:ring-[var(--ow-focus)] disabled:cursor-not-allowed disabled:opacity-70"
          />
        </div>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="ow-btn-primary rounded-xl px-5 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? common.saving : labels.saveConfiguration}
          </button>
        </div>
      </div>
    </>
  );
}
