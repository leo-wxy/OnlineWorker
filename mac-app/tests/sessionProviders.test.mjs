import test from "node:test";
import assert from "node:assert/strict";

import {
  visibleSessionProviderIds,
  visibleSessionProviders,
} from "../src/utils/sessionProviders.js";

test("visibleSessionProviderIds omits customprovider from default public session providers", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true, capabilities: { sessions: true } },
    { id: "customprovider", label: "Custom Provider", visible: false, managed: true, capabilities: { sessions: true } },
    { id: "claude", label: "Claude", visible: true, managed: true, capabilities: { sessions: true } },
  ];

  assert.deepEqual(visibleSessionProviderIds(providers), ["codex", "claude"]);
});

test("visibleSessionProviders keeps explicit visible customprovider session provider", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true, capabilities: { sessions: true } },
    { id: "customprovider", label: "Custom Provider", visible: true, managed: true, capabilities: { sessions: true } },
  ];

  assert.deepEqual(visibleSessionProviders(providers).map((provider) => provider.id), [
    "codex",
    "customprovider",
  ]);
});

test("visibleSessionProviderIds omits visible but disabled extension providers", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true, capabilities: { sessions: true } },
    { id: "customprovider", label: "Custom Provider", visible: true, managed: false, capabilities: { sessions: true } },
    { id: "claude", label: "Claude", visible: true, managed: true, capabilities: { sessions: true } },
  ];

  assert.deepEqual(visibleSessionProviderIds(providers), ["codex", "claude"]);
});

test("visibleSessionProviderIds omits providers that explicitly disable sessions", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true, capabilities: { sessions: true } },
    { id: "commands-only", label: "Commands Only", visible: true, managed: true, capabilities: { sessions: false } },
  ];

  assert.deepEqual(visibleSessionProviderIds(providers), ["codex"]);
});
