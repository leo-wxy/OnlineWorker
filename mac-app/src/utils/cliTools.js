const INSTALL_MAP = {
  codex: {
    label: "OpenAI Codex CLI",
    installMethod: "npm",
    cmd: "npm install -g @openai/codex",
    docsUrl: "https://github.com/openai/codex",
  },
  claude: {
    label: "Anthropic Claude Code CLI",
    installMethod: "npm",
    cmd: "npm install -g @anthropic-ai/claude-code",
    docsUrl: "https://docs.anthropic.com/en/docs/claude-code/getting-started",
  },
};

export function buildSetupCliToolsFromProviderMetadata(providers) {
  return (providers ?? [])
    .filter((provider) => provider?.visible === true)
    .map((provider) => ({
      name: provider.id,
      label: provider.label || provider.id,
      bin: provider.bin || provider.install?.cliNames?.[0] || provider.id,
    }))
    .filter((tool) => tool.name && tool.bin);
}

export function getCliInstallInfo(toolName, bin, texts) {
  const key = Object.keys(INSTALL_MAP).find(
    (candidate) =>
      toolName.toLowerCase().includes(candidate) ||
      bin.split("/").pop()?.toLowerCase().includes(candidate)
  );

  if (key) {
    const info = INSTALL_MAP[key];
    const desc =
      info.installMethod === "official"
        ? texts.installViaOfficialInstaller
        : texts.installViaNpm;
    return {
      label: info.label,
      steps: [{ desc, cmd: info.cmd }],
      docsUrl: info.docsUrl,
    };
  }

  return {
    label: bin,
    steps: [{ desc: texts.installManually(bin), cmd: `# install ${bin}` }],
  };
}
