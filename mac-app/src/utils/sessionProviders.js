export function visibleSessionProviders(providers) {
  return (providers ?? []).filter((provider) => {
    if (!provider?.id || provider.visible !== true || provider.managed !== true) {
      return false;
    }
    return provider.capabilities?.sessions !== false;
  });
}
