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

function installDescription(method, texts, bin) {
  if (method === "official") {
    return texts.installViaOfficialInstaller;
  }
  if (method === "npm") {
    return texts.installViaNpm;
  }
  return texts.installManually(bin);
}

export function getCliInstallInfo(toolName, bin, texts, install = null) {
  const command = String(install?.command || "").trim();
  if (command) {
    const label = String(install?.label || "").trim() || toolName || bin;
    const method = String(install?.method || "").trim();
    const docsUrl = String(install?.docsUrl || "").trim();
    return {
      label,
      steps: [{ desc: installDescription(method, texts, bin), cmd: command }],
      ...(docsUrl ? { docsUrl } : {}),
    };
  }

  return {
    label: toolName || bin,
    steps: [{ desc: texts.installManually(bin), cmd: `# install ${bin}` }],
  };
}
