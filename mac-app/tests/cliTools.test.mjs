import test from "node:test";
import assert from "node:assert/strict";

import { buildSetupCliToolsFromProviderMetadata } from "../src/utils/cliTools.js";

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
