export function visibleUsageProviders(providers) {
  return (providers ?? []).filter((provider) => {
    return Boolean(
      provider
        && provider.visible
        && provider.managed
        && provider.capabilities
        && provider.capabilities.usage,
    );
  });
}
