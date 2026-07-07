export function providerShowsPort(provider) {
  return typeof provider?.port === "number" && provider.port > 0;
}
