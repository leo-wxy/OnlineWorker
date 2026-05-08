import test from "node:test";
import assert from "node:assert/strict";

import { buildSetupCliToolsFromProviderMetadata, getCliInstallInfo } from "../src/utils/cliTools.js";

test("buildSetupCliToolsFromProviderMetadata defaults to visible providers only", () => {
  assert.deepEqual(buildSetupCliToolsFromProviderMetadata([
    { id: "codex", label: "Codex", visible: true, bin: "codex" },
    { id: "customprovider", label: "Custom Provider", visible: false, bin: "customprovider" },
    { id: "claude", label: "Claude", visible: true, bin: "claude" },
  ]), [
    { name: "codex", label: "Codex", bin: "codex" },
    { name: "claude", label: "Claude", bin: "claude" },
  ]);
});

test("getCliInstallInfo returns official Claude Code install metadata", () => {
  const texts = {
    installViaNpm: "Install via npm",
    installViaOfficialInstaller: "Install via official installer",
    installManually: (bin) => `Install ${bin} manually`,
  };

  assert.deepEqual(getCliInstallInfo("claude", "claude", texts), {
    label: "Anthropic Claude Code CLI",
    steps: [
      {
        desc: "Install via npm",
        cmd: "npm install -g @anthropic-ai/claude-code",
      },
    ],
    docsUrl: "https://docs.anthropic.com/en/docs/claude-code/getting-started",
  });
});
