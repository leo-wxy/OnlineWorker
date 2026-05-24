import { startTransition, useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type {
  NotificationChannelMetadata,
  NotificationSettingsField,
  ServiceStatus,
} from "../types";
import { useI18n, type AppTexts } from "../i18n";

type ChannelDrafts = Record<string, Record<string, unknown>>;
type NotificationTexts = AppTexts["notifications"];
type DetailTab = "config" | "guide";

function hasSecretFields(channel: NotificationChannelMetadata) {
  return channel.settingsFields.some((field) => field.type === "secret");
}

function hasConfiguredSecretFields(channel: NotificationChannelMetadata, drafts: ChannelDrafts) {
  const secretFields = channel.settingsFields.filter((field) => field.type === "secret");
  if (secretFields.length === 0) {
    return false;
  }
  return secretFields.every((field) => Boolean(String(drafts[channel.id]?.[field.key] ?? "").trim()));
}

function ChannelIcon({
  channel,
  size = "md",
}: {
  channel: NotificationChannelMetadata;
  size?: "sm" | "md" | "lg";
}) {
  const iconUrl = channel.icon?.url?.trim();
  const sizeClass = size === "lg" ? "h-12 w-12" : size === "sm" ? "h-9 w-9" : "h-10 w-10";
  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt=""
        className={`${sizeClass} rounded-2xl border border-[var(--ow-line-soft)] bg-white object-contain p-1.5 shadow-sm`}
      />
    );
  }
  return (
    <span className={`${sizeClass} grid place-items-center rounded-2xl border border-[var(--ow-line-soft)] bg-white text-sm font-bold text-slate-500 shadow-sm`}>
      {channel.label.trim().slice(0, 1).toUpperCase() || "N"}
    </span>
  );
}

function Toggle({
  checked,
  disabled,
  labelledBy,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  labelledBy?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-labelledby={labelledBy}
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

function fieldValue(channel: NotificationChannelMetadata, field: NotificationSettingsField) {
  const value = channel.config?.[field.key];
  if (value !== undefined && value !== null) {
    return value;
  }
  return field.default ?? (field.type === "boolean" ? false : "");
}

function configDraftFor(channel: NotificationChannelMetadata) {
  const draft: Record<string, unknown> = {};
  for (const field of channel.settingsFields) {
    draft[field.key] = fieldValue(channel, field);
  }
  return draft;
}

function guideHtmlFor(channel: NotificationChannelMetadata, locale: string) {
  const guide = channel.setupGuide;
  if (!guide || guide.type !== "html") {
    return "";
  }
  const assets = guide.assets ?? {};
  return (
    assets[locale] ||
    assets[locale === "zh" ? "zh-CN" : "en-US"] ||
    assets[locale === "zh" ? "zh_CN" : "en_US"] ||
    assets[locale === "zh" ? "en" : "zh"] ||
    Object.values(assets)[0] ||
    ""
  );
}

function FieldInput({
  channelId,
  field,
  value,
  disabled,
  onChange,
  labels,
}: {
  channelId: string;
  field: NotificationSettingsField;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
  labels: Pick<NotificationTexts, "enabled" | "disabled">;
}) {
  const id = `notification-${channelId}-${field.key}`;
  const baseClass = "block w-full rounded-2xl border border-[var(--ow-line)] bg-white/92 px-4 py-3 text-sm font-medium text-gray-900 outline-none transition-colors placeholder:text-slate-400 focus:border-blue-300 focus:ring-4 focus:ring-blue-500/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400";

  if (field.type === "boolean") {
    return (
      <label className={`flex items-center gap-3 ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
        <Toggle
          checked={Boolean(value)}
          disabled={disabled}
          onChange={onChange}
        />
        <span className="text-sm font-semibold text-slate-700">{Boolean(value) ? labels.enabled : labels.disabled}</span>
      </label>
    );
  }

  if (field.type === "select") {
    return (
      <select
        id={id}
        value={String(value ?? "")}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={baseClass}
      >
        {field.options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    );
  }

  return (
    <input
      id={id}
      type={field.type === "number" ? "number" : field.type === "secret" ? "password" : "text"}
      value={String(value ?? "")}
      disabled={disabled}
      onChange={(event) => {
        if (field.type === "number") {
          const raw = event.target.value;
          onChange(raw === "" ? "" : Number(raw));
          return;
        }
        onChange(event.target.value);
      }}
      className={baseClass}
    />
  );
}

export function NotificationSettingsPanel() {
  const { locale, t } = useI18n();
  const common = t.common;
  const notifications = t.notifications;
  const [channels, setChannels] = useState<NotificationChannelMetadata[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<ChannelDrafts>({});
  const [loading, setLoading] = useState(true);
  const [savingChannelId, setSavingChannelId] = useState<string | null>(null);
  const [savedChannelId, setSavedChannelId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("config");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const metadata = await invoke<NotificationChannelMetadata[]>("get_notification_channels");
      setChannels(metadata);
      setSelectedChannelId((current) => {
        if (current && metadata.some((channel) => channel.id === current)) {
          return current;
        }
        return metadata[0]?.id ?? null;
      });
      setDrafts(Object.fromEntries(metadata.map((channel) => [channel.id, configDraftFor(channel)])));
      setError(null);
    } catch (err) {
      setError(notifications.loadError(String(err)));
    } finally {
      setLoading(false);
    }
  }, [notifications]);

  useEffect(() => {
    void load();
  }, [load]);

  const byId = useMemo(
    () => new Map(channels.map((channel) => [channel.id, channel])),
    [channels]
  );
  const selectedChannel = selectedChannelId ? byId.get(selectedChannelId) : channels[0];
  const guideHtml = selectedChannel ? guideHtmlFor(selectedChannel, locale) : "";

  const labelForField = (channel: NotificationChannelMetadata, field: NotificationSettingsField) =>
    notifications.fieldLabels[channel.id]?.[field.key] || field.label;

  const descriptionForField = (channel: NotificationChannelMetadata, field: NotificationSettingsField) =>
    notifications.fieldDescriptions[channel.id]?.[field.key] || field.description;

  const descriptionForChannel = (channel: NotificationChannelMetadata) =>
    notifications.channelDescriptions[channel.id] || channel.description || notifications.channelDescriptionFallback;

  const restartIfRunning = async () => {
    const status = await invoke<ServiceStatus>("service_status");
    if (status.running) {
      await invoke("service_restart");
    }
  };

  const finishSave = (channelId: string) => {
    setSavedChannelId(channelId);
    setTimeout(() => setSavedChannelId((current) => current === channelId ? null : current), 1800);
    startTransition(() => {
      void load();
    });
  };

  const saveChannelEnabled = async (channelId: string, enabled: boolean) => {
    setSavingChannelId(channelId);
    try {
      await invoke("set_notification_channel_enabled", { channelId, enabled });
      await restartIfRunning();
      finishSave(channelId);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingChannelId(null);
    }
  };

  const saveChannelConfig = async (channelId: string) => {
    const channel = byId.get(channelId);
    if (!channel) {
      return;
    }
    setSavingChannelId(channelId);
    try {
      await invoke("set_notification_channel_config", {
        channelId,
        config: drafts[channelId] ?? {},
      });

      await restartIfRunning();
      finishSave(channelId);
    } catch (err) {
      setError(String(err));
    } finally {
      setSavingChannelId(null);
    }
  };

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col gap-5">
      <div className="shrink-0">
        <h2 className="text-xl font-extrabold tracking-[-0.02em] text-gray-950">{notifications.title}</h2>
        <p className="mt-1 max-w-3xl text-sm font-medium text-slate-500">{notifications.description}</p>
      </div>

      {loading && (
        <div className="ow-page-frame-soft rounded-[24px] p-5 text-sm font-medium text-slate-500">
          {notifications.loading}
        </div>
      )}

      {error && (
        <div className="ow-page-frame-soft rounded-[24px] border-rose-200 bg-rose-50/85 p-4 text-sm font-medium text-rose-700">
          {error}
        </div>
      )}

      {!loading && channels.length === 0 && (
        <div className="ow-page-frame rounded-[26px] p-6">
          <h3 className="text-base font-bold text-gray-950">{notifications.noChannelsTitle}</h3>
          <p className="mt-1 text-sm font-medium text-slate-500">{notifications.noChannelsDescription}</p>
        </div>
      )}

      {!loading && channels.length > 0 && selectedChannel && (
        <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="ow-page-frame-soft flex min-h-0 flex-col overflow-hidden rounded-[26px]">
            <div className="border-b border-[var(--ow-line-soft)] px-5 py-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-bold text-gray-950">{notifications.channelsTitle}</h3>
                  <p className="mt-1 text-xs font-medium leading-5 text-slate-500">{notifications.channelsDescription}</p>
                </div>
                <span className="shrink-0 rounded-xl bg-white/80 px-2.5 py-1 text-xs font-bold text-slate-500">
                  {notifications.channelCount(channels.length)}
                </span>
              </div>
            </div>

            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
              {channels.map((channel) => {
                const selected = channel.id === selectedChannel.id;
                const needsKey = hasSecretFields(channel);
                const keyReady = hasConfiguredSecretFields(channel, drafts);
                return (
                  <button
                    key={channel.id}
                    type="button"
                    onClick={() => setSelectedChannelId(channel.id)}
                    className={`grid w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-3 rounded-2xl border px-3 py-3 text-left transition-colors ${
                      selected
                        ? channel.enabled
                          ? "border-emerald-200 bg-emerald-50/80 shadow-sm"
                          : "border-blue-200 bg-white shadow-sm"
                        : channel.enabled
                          ? "border-emerald-100 bg-emerald-50/45 hover:border-emerald-200 hover:bg-emerald-50/75"
                          : "border-transparent bg-white/45 hover:border-[var(--ow-line)] hover:bg-white/82"
                    }`}
                  >
                    <ChannelIcon channel={channel} size="sm" />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-bold text-gray-950">{channel.label}</span>
                      <span className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="text-xs font-medium text-slate-500">
                          {channel.builtin ? notifications.builtin : notifications.custom}
                        </span>
                        {needsKey && (
                          <span className={`rounded-lg px-2 py-0.5 text-[11px] font-bold ${
                            keyReady
                              ? "bg-emerald-100 text-emerald-700"
                              : "bg-amber-50 text-amber-700"
                          }`}>
                            {keyReady ? notifications.configured : notifications.needsConfig}
                          </span>
                        )}
                      </span>
                    </span>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${
                      channel.enabled
                        ? "bg-emerald-600 text-white shadow-sm shadow-emerald-200"
                        : "bg-slate-100 text-slate-500"
                    }`}>
                      {channel.enabled ? notifications.enabled : notifications.disabled}
                    </span>
                  </button>
                );
              })}
            </div>
          </aside>

          <section className="ow-page-frame flex min-h-0 flex-col overflow-hidden rounded-[26px]">
            {(() => {
              const channel = selectedChannel;
              const busy = savingChannelId === channel.id;
              const saved = savedChannelId === channel.id;
              const channelDraft = drafts[channel.id] ?? {};
              return (
                <>
                  <div className="border-b border-[var(--ow-line-soft)] px-6 py-5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <div className="flex items-center gap-4">
                          <ChannelIcon channel={channel} size="lg" />
                          <div>
                            <p className="text-xs font-bold uppercase tracking-wider text-slate-400">
                              {notifications.configTitle}
                            </p>
                            <h3 id={`notification-${channel.id}-title`} className="mt-1 text-xl font-extrabold tracking-[-0.02em] text-gray-950">
                              {channel.label}
                            </h3>
                          </div>
                        </div>
                        <p className="mt-4 max-w-2xl text-sm font-medium leading-6 text-slate-500">
                          {descriptionForChannel(channel)}
                        </p>
                        <p className="mt-2 text-xs font-mono text-slate-400">
                          {notifications.pluginIdLabel}: {channel.id}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        {saved && <span className="text-xs font-bold text-emerald-700">{common.saved}</span>}
                        {busy && <span className="text-xs font-bold text-blue-600">{common.saving}</span>}
                        <label className={`flex items-center gap-3 rounded-xl border border-[var(--ow-line-soft)] bg-slate-50 px-3 py-2 ${busy ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}>
                          <span className="text-sm font-semibold text-slate-700">{notifications.enableChannel}</span>
                          <Toggle
                            checked={channel.enabled}
                            disabled={busy}
                            labelledBy={`notification-${channel.id}-title`}
                            onChange={(checked) => {
                              void saveChannelEnabled(channel.id, checked);
                            }}
                          />
                        </label>
                      </div>
                    </div>
                  </div>

                  <div className="flex min-h-0 flex-1 flex-col">
                    <div className="border-b border-[var(--ow-line-soft)] px-6 py-3">
                      <div className="ow-segment inline-flex rounded-2xl p-1">
                        {([
                          ["config", notifications.configTab],
                          ["guide", notifications.guideTab],
                        ] as const).map(([tab, label]) => (
                          <button
                            key={tab}
                            type="button"
                            onClick={() => setDetailTab(tab)}
                            className={`rounded-xl px-4 py-1.5 text-sm font-semibold transition-colors ${
                              detailTab === tab
                                ? "ow-segment-button-active"
                                : "ow-segment-button hover:text-gray-700"
                            }`}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>

                    {detailTab === "config" ? (
                      <div className="min-h-0 flex-1 overflow-y-auto p-6">
                        {channel.settingsFields.length === 0 ? (
                          <div className="ow-page-frame-soft rounded-[24px] p-5 shadow-none">
                            <h4 className="text-sm font-bold text-gray-950">{notifications.noFieldsTitle}</h4>
                            <p className="mt-1 text-sm font-medium text-slate-500">{notifications.noFieldsDescription}</p>
                          </div>
                        ) : (
                          <div className="ow-page-frame-soft divide-y divide-[var(--ow-line-soft)] overflow-hidden rounded-[24px] shadow-none">
                            {channel.settingsFields.map((field) => {
                              const fieldDescription = descriptionForField(channel, field);
                              return (
                                <div
                                  key={field.key}
                                  className="grid gap-4 px-5 py-5 md:grid-cols-[220px_minmax(0,1fr)]"
                                >
                                  <div>
                                    <label
                                      htmlFor={`notification-${channel.id}-${field.key}`}
                                      className="text-sm font-bold text-gray-950"
                                    >
                                      {labelForField(channel, field)}
                                      {field.required && <span className="ml-1 text-rose-600">*</span>}
                                    </label>
                                    {fieldDescription && (
                                      <p className="mt-1 text-xs font-medium leading-5 text-slate-500">{fieldDescription}</p>
                                    )}
                                  </div>
                                  <FieldInput
                                    channelId={channel.id}
                                    field={field}
                                    value={channelDraft[field.key]}
                                    disabled={busy}
                                    labels={notifications}
                                    onChange={(value) => {
                                      setDrafts((current) => ({
                                        ...current,
                                        [channel.id]: {
                                          ...(current[channel.id] ?? {}),
                                          [field.key]: value,
                                        },
                                      }));
                                    }}
                                  />
                                </div>
                              );
                            })}
                          </div>
                        )}

                        <div className="mt-5 flex justify-end">
                          {channel.settingsFields.length > 0 && (
                            <button
                              type="button"
                              onClick={() => void saveChannelConfig(channel.id)}
                              disabled={busy}
                              className="ow-btn-primary rounded-xl px-5 py-2.5 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
                            >
                              {busy ? common.saving : notifications.saveConfiguration}
                            </button>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="min-h-0 flex-1 p-6">
                        {guideHtml ? (
                          <iframe
                            title={`${channel.label} ${notifications.guideTab}`}
                            srcDoc={guideHtml}
                            sandbox=""
                            className="h-full min-h-[420px] w-full rounded-2xl border border-[var(--ow-line-soft)] bg-white"
                          />
                        ) : (
                          <div className="ow-page-frame-soft rounded-[24px] p-5 shadow-none">
                            <h4 className="text-sm font-bold text-gray-950">{notifications.noGuideTitle}</h4>
                            <p className="mt-1 text-sm font-medium text-slate-500">{notifications.noGuideDescription}</p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </>
              );
            })()}
          </section>
        </div>
      )}
    </div>
  );
}
