export function providerShowsPort(provider) {
  return typeof provider?.port === "number" && provider.port > 0;
}

export function providerStatusValue(provider, fallback) {
  return providerShowsPort(provider) ? provider.port : fallback;
}
