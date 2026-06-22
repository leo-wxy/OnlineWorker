import test from "node:test";
import assert from "node:assert/strict";

import { buildSetupCliToolsFromProviderMetadata, getCliInstallInfo } from "../src/utils/cliTools.js";

test("buildSetupCliToolsFromProviderMetadata defaults to visible providers only", () => {
  assert.deepEqual(buildSetupCliToolsFromProviderMetadata([
    {
      id: "primary",
      label: "Primary",
      visible: true,
      bin: "primary",
      install: { cliNames: ["primary"], label: "Primary CLI", method: "npm", command: "npm install -g primary" },
    },
    { id: "customprovider", label: "Custom Provider", visible: false, bin: "customprovider" },
    { id: "secondary", label: "Secondary", visible: true, bin: "secondary" },
  ]), [
    {
      name: "primary",
      label: "Primary",
      bin: "primary",
      install: { cliNames: ["primary"], label: "Primary CLI", method: "npm", command: "npm install -g primary" },
    },
    { name: "secondary", label: "Secondary", bin: "secondary", install: null },
  ]);
});

test("getCliInstallInfo returns provider manifest install metadata", () => {
  const texts = {
    installViaNpm: "Install via npm",
    installViaOfficialInstaller: "Install via official installer",
    installManually: (bin) => `Install ${bin} manually`,
  };

  assert.deepEqual(getCliInstallInfo("primary", "primary", texts, {
    label: "Primary CLI",
    method: "npm",
    command: "npm install -g primary-cli",
    docsUrl: "https://example.test/primary",
  }), {
    label: "Primary CLI",
    steps: [
      {
        desc: "Install via npm",
        cmd: "npm install -g primary-cli",
      },
    ],
    docsUrl: "https://example.test/primary",
  });
});
