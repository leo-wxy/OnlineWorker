import test from "node:test";
import assert from "node:assert/strict";

import {
  extensionProviderSettings,
  primaryProviderSettings,
} from "../src/utils/settingsProviders.js";

const PROVIDERS = [
  { id: "codex", label: "Codex", visible: true, visibility: "public", managed: true, autostart: true },
  { id: "customprovider", label: "Custom Provider", visible: true, managed: false, autostart: false },
  { id: "claude", label: "Claude", visible: true, visibility: "public", managed: true, autostart: false },
  { id: "hidden", label: "Hidden", visible: false, managed: true, autostart: true },
];

test("primaryProviderSettings keeps default public agents in stable order", () => {
  assert.deepEqual(primaryProviderSettings(PROVIDERS), [
    { id: "codex", label: "Codex", enabled: true, autostart: true },
    { id: "claude", label: "Claude", enabled: true, autostart: false },
  ]);
});

test("extensionProviderSettings exposes non-default discovered providers", () => {
  assert.deepEqual(extensionProviderSettings(PROVIDERS), [
    { id: "customprovider", label: "Custom Provider", enabled: false, autostart: false },
    { id: "hidden", label: "Hidden", enabled: true, autostart: true },
  ]);
});

test("provider settings preserve the configured CLI bin for availability checks", () => {
  const providers = [
    {
      id: "customprovider",
      label: "Custom Provider",
      visible: true,
      managed: false,
      autostart: false,
      bin: "~/.customprovider/bin/customprovider",
    },
  ];

  assert.deepEqual(extensionProviderSettings(providers), [
    {
      id: "customprovider",
      label: "Custom Provider",
      enabled: false,
      autostart: false,
      bin: "~/.customprovider/bin/customprovider",
    },
  ]);
});

test("primaryProviderSettings follows public visibility instead of a hard-coded provider id list", () => {
  const providers = [
    { id: "zeta", label: "Zeta", visible: true, visibility: "private", managed: false, autostart: false },
    { id: "alpha", label: "Alpha", visible: true, visibility: "public", managed: true, autostart: false },
    { id: "beta", label: "Beta", visible: true, visibility: "public", managed: true, autostart: true },
  ];

  assert.deepEqual(primaryProviderSettings(providers), [
    { id: "alpha", label: "Alpha", enabled: true, autostart: false },
    { id: "beta", label: "Beta", enabled: true, autostart: true },
  ]);

  assert.deepEqual(extensionProviderSettings(providers), [
    { id: "zeta", label: "Zeta", enabled: false, autostart: false },
  ]);
});
