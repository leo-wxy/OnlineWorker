import type { useI18n } from "../../i18n";
import type { AiConnectionTestResult, AiServiceMetadata } from "../../types";
import { NumberField, TextField, Toggle } from "./fields";
import type { AiLabels } from "./utils";
import {
  serviceDescription,
  serviceTitle,
  statusText,
} from "./utils";

type CommonLabels = ReturnType<typeof useI18n>["t"]["common"];

export function AiServiceEditor({
  common,
  labels,
  service,
  saving,
  saved,
  testingServiceId,
  testResult,
  onUpdate,
  onSetEnabled,
  onDelete,
  onSave,
  onTestConnection,
}: {
  common: CommonLabels;
  labels: AiLabels;
  service: AiServiceMetadata;
  saving: boolean;
  saved: boolean;
  testingServiceId: string | null;
  testResult?: AiConnectionTestResult;
  onUpdate: (id: string, patch: Partial<AiServiceMetadata>) => void;
  onSetEnabled: (id: string, enabled: boolean) => void;
  onDelete: (id: string) => void;
  onSave: () => void;
  onTestConnection: (service: AiServiceMetadata) => void;
}) {
  return (
    <>
      <div className="border-b border-[var(--ow-line-soft)] px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">{labels.serviceConfigTitle}</p>
            <h3 id={`ai-service-${service.id}-title`} className="mt-1 text-xl font-extrabold tracking-[-0.02em] text-gray-950">
              {serviceTitle(service, labels)}
            </h3>
            <p className="mt-3 max-w-2xl text-sm font-medium leading-6 text-slate-500">
              {serviceDescription(service, labels)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {saved && <span className="text-xs font-bold text-emerald-700">{common.saved}</span>}
            {saving && <span className="text-xs font-bold text-blue-600">{common.saving}</span>}
            {!service.pluginOwned && (
              <button
                type="button"
                onClick={() => onDelete(service.id)}
                disabled={saving}
                className="rounded-xl border border-rose-100 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {labels.deleteService}
              </button>
            )}
            <label className={`flex items-center gap-3 rounded-xl border border-[var(--ow-line-soft)] bg-slate-50 px-3 py-2 ${saving ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
              <span className="text-sm font-semibold text-slate-700">{labels.enableService}</span>
              <Toggle
                checked={service.enabled}
                disabled={saving}
                labelledBy={`ai-service-${service.id}-title`}
                onChange={(checked) => onSetEnabled(service.id, checked)}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        <div className="ow-page-frame-soft divide-y divide-[var(--ow-line-soft)] overflow-hidden rounded-[24px] shadow-none">
          <TextField
            id={`ai-service-${service.id}-key`}
            label={labels.apiKey}
            type="password"
            value={service.apiKey || ""}
            disabled={saving}
            onChange={(value) => onUpdate(service.id, { apiKey: value })}
          />
          <TextField
            id={`ai-service-${service.id}-url`}
            label={labels.requestUrl}
            value={service.endpoint || service.baseUrl || ""}
            disabled={saving}
            onChange={(value) => onUpdate(
              service.id,
              service.protocol === "anthropic_messages" ? { endpoint: value } : { baseUrl: value },
            )}
          />
          <TextField
            id={`ai-service-${service.id}-models`}
            label={labels.models}
            value={service.models.join(", ")}
            disabled={saving}
            onChange={(value) => {
              const models = value.split(",").map((item) => item.trim()).filter(Boolean);
              onUpdate(service.id, {
                models,
                defaultModel: models.includes(service.defaultModel) ? service.defaultModel : models[0] || "",
              });
            }}
          />
          <div className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]">
            <label htmlFor={`ai-service-${service.id}-model`} className="text-sm font-bold text-gray-950">
              {labels.defaultModel}
            </label>
            <select
              id={`ai-service-${service.id}-model`}
              value={service.defaultModel}
              disabled={saving}
              onChange={(event) => onUpdate(service.id, { defaultModel: event.target.value })}
              className="block w-full rounded-2xl border border-[var(--ow-line)] bg-white/92 px-4 py-3 text-sm font-medium text-gray-900 outline-none transition-colors focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
            >
              {service.models.map((model) => (
                <option key={model} value={model}>{model}</option>
              ))}
              {!service.models.includes(service.defaultModel) && service.defaultModel && (
                <option value={service.defaultModel}>{service.defaultModel}</option>
              )}
            </select>
          </div>
          <NumberField
            id={`ai-service-${service.id}-timeout`}
            label={labels.timeout}
            value={service.timeoutSeconds}
            disabled={saving}
            onChange={(value) => onUpdate(service.id, { timeoutSeconds: value })}
          />
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <div className="min-h-10 flex-1">
            {testResult && (
              <div
                className={`rounded-xl border px-4 py-3 text-sm font-semibold ${
                  testResult.ok
                    ? "border-emerald-100 bg-emerald-50 text-emerald-800"
                    : "border-rose-100 bg-rose-50 text-rose-800"
                }`}
              >
                {testResult.ok
                  ? labels.connectionOk(statusText(testResult.status))
                  : labels.connectionFailed(
                      statusText(testResult.status),
                      testResult.message,
                    )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => onTestConnection(service)}
              disabled={testingServiceId === service.id}
              className="rounded-xl border border-[var(--ow-line)] bg-white px-5 py-2.5 text-sm font-semibold text-gray-900 shadow-sm transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {testingServiceId === service.id ? labels.testing : labels.testConnection}
            </button>
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
      </div>
    </>
  );
}
