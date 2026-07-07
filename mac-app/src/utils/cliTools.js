export function buildSetupCliToolsFromProviderMetadata(providers) {
  return (providers ?? [])
    .filter((provider) => provider?.visible === true)
    .map((provider) => ({
      name: provider.id,
      label: provider.label || provider.id,
      bin: provider.bin || provider.install?.cliNames?.[0] || provider.id,
      install: provider.install ?? null,
    }))
    .filter((tool) => tool.name && tool.bin);
}
