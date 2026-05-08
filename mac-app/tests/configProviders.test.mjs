import test from "node:test";
import assert from "node:assert/strict";

import {
  parseCliEntriesFromConfigRaw,
  providerCliEntriesFromMetadata,
  visibleProviderMetadata,
} from "../src/utils/configProviders.js";

test("parseCliEntriesFromConfigRaw supports provider schema and includes claude", () => {
  const raw = `
schema_version: 2
providers:
  codex:
    managed: true
    bin: codex
    owner_transport: stdio
  customprovider:
    managed: true
    visible: false
    bin: customprovider
    owner_transport: http
  claude:
    managed: false
    bin: claude
    owner_transport: stdio
`;

  assert.deepEqual(parseCliEntriesFromConfigRaw(raw), [
    { name: "codex", bin: "codex" },
    { name: "claude", bin: "claude" },
  ]);
});

test("parseCliEntriesFromConfigRaw includes explicit visible customprovider provider", () => {
  const raw = `
schema_version: 2
providers:
  codex:
    managed: true
    bin: codex
  customprovider:
    managed: true
    visible: true
    bin: customprovider
`;

  assert.deepEqual(parseCliEntriesFromConfigRaw(raw), [
    { name: "codex", bin: "codex" },
    { name: "customprovider", bin: "customprovider" },
  ]);
});

test("parseCliEntriesFromConfigRaw still supports legacy tools schema", () => {
  const raw = `
tools:
  - name: codex
    codex_bin: codex
  - name: customprovider
    codex_bin: customprovider
  - name: claude
    codex_bin: claude
`;

  assert.deepEqual(parseCliEntriesFromConfigRaw(raw), [
    { name: "codex", bin: "codex" },
    { name: "customprovider", bin: "customprovider" },
    { name: "claude", bin: "claude" },
  ]);
});

test("visibleProviderMetadata omits runtime-enabled hidden customprovider", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, bin: "codex" },
    { id: "customprovider", label: "Custom Provider", visible: false, managed: true, bin: "customprovider" },
    { id: "claude", label: "Claude", visible: true, bin: "claude" },
  ];

  assert.deepEqual(visibleProviderMetadata(providers).map((provider) => provider.id), [
    "codex",
    "claude",
  ]);
  assert.deepEqual(providerCliEntriesFromMetadata(providers), [
    { name: "codex", label: "Codex", bin: "codex" },
    { name: "claude", label: "Claude", bin: "claude" },
  ]);
});
