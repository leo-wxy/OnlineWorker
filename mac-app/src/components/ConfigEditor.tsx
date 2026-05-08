import { type ReactNode, useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { ConfigContent, EnvContent } from "../types";
import { useI18n } from "../i18n";

type FilePanel = "yaml" | "env";
type PanelMode = "view" | "edit";

function RawCodeBlock({ value }: { value: string }) {
  return (
    <pre className="max-h-[62vh] min-h-[420px] overflow-auto bg-slate-950 px-5 py-4 font-mono text-xs leading-6 text-slate-100">
      {value || "\n"}
    </pre>
  );
}

function RawTextarea({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <textarea
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="block h-[62vh] min-h-[420px] w-full resize-none border-0 bg-white px-5 py-4 font-mono text-xs leading-6 text-gray-900 outline-none focus:ring-0"
      spellCheck={false}
    />
  );
}

function FileChoiceRow({
  title,
  description,
  active,
  onView,
  onEdit,
}: {
  title: string;
  description: string;
  active: boolean;
  onView: () => void;
  onEdit: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className={`rounded-xl border px-4 py-4 transition-colors ${
      active ? "border-blue-200 bg-blue-50/70" : "border-gray-200 bg-white"
    }`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <p className="mt-1 text-sm leading-6 text-gray-600">{description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={onView}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            {t.common.view}
          </button>
          <button
            onClick={onEdit}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            {t.common.edit}
          </button>
        </div>
      </div>
    </div>
  );
}

function PanelShell({
  title,
  description,
  path,
  mode,
  saving,
  saved,
  error,
  onModeChange,
  onSave,
  onClose,
  children,
}: {
  title: string;
  description: string;
  path: string;
  mode: PanelMode;
  saving: boolean;
  saved: boolean;
  error: string | null;
  onModeChange: (mode: PanelMode) => void;
  onSave: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-[620px] flex-col">
      <div className="border-b border-gray-200 bg-white px-5 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-base font-semibold text-gray-950">{title}</p>
            <p className="mt-1 text-sm leading-6 text-gray-600">{description}</p>
            <p className="mt-2 truncate font-mono text-xs text-gray-400">{path}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1">
              <button
                onClick={() => onModeChange("view")}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  mode === "view" ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {t.common.view}
              </button>
              <button
                onClick={() => onModeChange("edit")}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  mode === "edit" ? "bg-white text-gray-900 shadow-sm" : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {t.common.edit}
              </button>
            </div>
            {mode === "edit" && (
              <button
                onClick={onSave}
                disabled={saving}
                className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? t.common.saving : saved ? t.common.saved : t.common.save}
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-600 transition-colors hover:bg-gray-50 hover:text-gray-900"
            >
              {t.common.close}
            </button>
          </div>
        </div>
        {error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
    </div>
  );
}

function EmptyPanel() {
  const { t } = useI18n();

  return (
    <div className="flex h-full min-h-[620px] items-center justify-center bg-white px-8">
      <div className="max-w-sm text-center">
        <p className="text-base font-semibold text-gray-900">{t.config.emptyTitle}</p>
        <p className="mt-2 text-sm leading-6 text-gray-600">{t.config.emptyDescription}</p>
      </div>
    </div>
  );
}

function YamlPanel({
  mode,
  onModeChange,
  onClose,
}: {
  mode: PanelMode;
  onModeChange: (mode: PanelMode) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [configRaw, setConfigRaw] = useState("");
  const [configPath, setConfigPath] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const content = await invoke<ConfigContent>("read_config");
      setConfigRaw(content.raw);
      setConfigPath(content.path);
      setEditContent(content.raw);
      setError(null);
    } catch (event) {
      setError(String(event));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  useEffect(() => {
    if (mode === "edit") {
      setEditContent(configRaw);
    }
  }, [mode, configRaw]);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await invoke("write_config", { content: editContent });
      const latest = await invoke<ConfigContent>("read_config");
      setConfigRaw(latest.raw);
      setConfigPath(latest.path);
      setEditContent(latest.raw);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      setError(null);
      onModeChange("view");
    } catch (event) {
      setError(String(event));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="py-10 text-center text-sm text-gray-400">{t.common.loading}</div>;
  }

  return (
    <PanelShell
      title={t.config.yamlTab}
      description={t.config.yamlDescription}
      path={configPath}
      mode={mode}
      saving={saving}
      saved={saved}
      error={error}
      onModeChange={onModeChange}
      onSave={save}
      onClose={onClose}
    >
      {mode === "edit" ? (
        <RawTextarea value={editContent} onChange={setEditContent} />
      ) : (
        <RawCodeBlock value={configRaw} />
      )}
    </PanelShell>
  );
}

function EnvPanel({
  mode,
  onModeChange,
  onClose,
}: {
  mode: PanelMode;
  onModeChange: (mode: PanelMode) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [envContent, setEnvContent] = useState<EnvContent | null>(null);
  const [rawContent, setRawContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");

  const loadEnv = useCallback(async () => {
    setLoading(true);
    try {
      const [masked, raw] = await Promise.all([
        invoke<EnvContent>("read_env"),
        invoke<ConfigContent>("read_env_raw"),
      ]);
      setEnvContent(masked);
      setRawContent(raw.raw);
      setEditContent(raw.raw);
      setError(null);
    } catch (event) {
      setError(String(event));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEnv();
  }, [loadEnv]);

  useEffect(() => {
    if (mode === "edit") {
      setEditContent(rawContent);
    }
  }, [mode, rawContent]);

  const save = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await invoke("write_env", { content: editContent });
      const [masked, raw] = await Promise.all([
        invoke<EnvContent>("read_env"),
        invoke<ConfigContent>("read_env_raw"),
      ]);
      setEnvContent(masked);
      setRawContent(raw.raw);
      setEditContent(raw.raw);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      setError(null);
      onModeChange("view");
    } catch (event) {
      setError(String(event));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="py-10 text-center text-sm text-gray-400">{t.common.loading}</div>;
  }

  return (
    <PanelShell
      title={t.config.envTab}
      description={t.config.envDescription}
      path={envContent?.path ?? t.config.envTab}
      mode={mode}
      saving={saving}
      saved={saved}
      error={error}
      onModeChange={onModeChange}
      onSave={save}
      onClose={onClose}
    >
      {mode === "edit" ? (
        <RawTextarea value={editContent} onChange={setEditContent} />
      ) : (
        <div className="h-full overflow-auto bg-white">
          <div className="border-b border-gray-100 px-5 py-3 text-xs leading-5 text-gray-500">
            {t.config.envMaskedHint}
          </div>
          <div className="divide-y divide-gray-100">
            {envContent?.lines.map((line, index) => {
              if (!line.value && line.key) {
                return (
                  <div key={index} className="bg-gray-50 px-5 py-2">
                    <span className="font-mono text-xs text-gray-400">{line.key}</span>
                  </div>
                );
              }

              if (!line.key && !line.value) {
                return <div key={index} className="h-2 bg-white" />;
              }

              return (
                <div
                  key={index}
                  className="grid grid-cols-[minmax(180px,220px)_minmax(0,1fr)] items-center gap-4 px-5 py-3"
                >
                  <span className="truncate font-mono text-xs font-semibold text-gray-700">
                    {line.key}
                  </span>
                  <span className={`truncate font-mono text-xs ${
                    line.masked ? "text-gray-400 tracking-widest" : "text-gray-800"
                  }`}>
                    {line.value || <span className="italic text-gray-300">{t.common.empty}</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </PanelShell>
  );
}

export function ConfigEditor() {
  const { t } = useI18n();
  const [activePanel, setActivePanel] = useState<FilePanel | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>("view");

  const openPanel = (panel: FilePanel, mode: PanelMode) => {
    setActivePanel(panel);
    setPanelMode(mode);
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4">
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Advanced</p>
        <h2 className="text-2xl font-semibold text-gray-950">{t.setup.advancedConfigTitle}</h2>
        <p className="max-w-2xl text-sm leading-6 text-gray-600">{t.setup.advancedConfigDescription}</p>
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
        <div className="grid min-h-[620px] md:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="border-b border-gray-200 bg-gray-50/70 p-4 md:border-b-0 md:border-r">
            <div className="mb-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{t.config.rawFilesTitle}</p>
              <p className="mt-1 text-sm leading-6 text-gray-600">{t.config.rawFilesDescription}</p>
            </div>

            <div className="space-y-2">
              <FileChoiceRow
                title={t.config.yamlTab}
                description={t.config.yamlDescription}
                active={activePanel === "yaml"}
                onView={() => openPanel("yaml", "view")}
                onEdit={() => openPanel("yaml", "edit")}
              />
              <FileChoiceRow
                title={t.config.envTab}
                description={t.config.envDescription}
                active={activePanel === "env"}
                onView={() => openPanel("env", "view")}
                onEdit={() => openPanel("env", "edit")}
              />
            </div>

            <div className="mt-4 rounded-xl border border-gray-200 bg-white px-4 py-3 text-xs leading-5 text-gray-500">
              {t.config.providerHint}
            </div>
          </aside>

          <section className="min-w-0 bg-white">
            {activePanel === "yaml" ? (
              <YamlPanel
                mode={panelMode}
                onModeChange={setPanelMode}
                onClose={() => setActivePanel(null)}
              />
            ) : activePanel === "env" ? (
              <EnvPanel
                mode={panelMode}
                onModeChange={setPanelMode}
                onClose={() => setActivePanel(null)}
              />
            ) : (
              <EmptyPanel />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
