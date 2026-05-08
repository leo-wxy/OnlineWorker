const PRIMARY_PROVIDER_IDS = ["codex", "claude"];

function toProviderSetting(provider) {
  const setting = {
    id: provider.id,
    label: provider.label || provider.id,
    enabled: provider.managed === true,
    autostart: provider.managed === true && provider.autostart === true,
  };
  if (provider.bin) {
    setting.bin = provider.bin;
  }
  return setting;
}

export function primaryProviderSettings(providers) {
  const byId = new Map(
    (providers ?? [])
      .filter((provider) => provider?.visible === true && provider?.id)
      .map((provider) => [provider.id, provider])
  );

  return PRIMARY_PROVIDER_IDS
    .map((id) => byId.get(id))
    .filter(Boolean)
    .map(toProviderSetting);
}

export function extensionProviderSettings(providers) {
  return (providers ?? [])
    .filter((provider) => provider?.visible === true && provider?.id)
    .filter((provider) => !PRIMARY_PROVIDER_IDS.includes(provider.id))
    .map(toProviderSetting);
}
