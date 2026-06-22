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

function isPublicProvider(provider) {
  return provider?.visibility === "public";
}

export function primaryProviderSettings(providers) {
  return (providers ?? [])
    .filter((provider) => provider?.visible === true && isPublicProvider(provider))
    .map(toProviderSetting);
}

export function extensionProviderSettings(providers) {
  return (providers ?? [])
    .filter((provider) => provider?.id)
    .filter((provider) => !isPublicProvider(provider))
    .map(toProviderSetting);
}
