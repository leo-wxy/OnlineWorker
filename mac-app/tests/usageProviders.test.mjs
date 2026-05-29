import test from "node:test";
import assert from "node:assert/strict";
import { visibleUsageProviders } from "../src/utils/usageProviders.js";

test("visibleUsageProviders returns managed providers that advertise usage", () => {
  const providers = [
    {
      id: "codex",
      visible: true,
      managed: true,
      capabilities: { usage: true },
    },
    {
      id: "overlay-tool",
      visible: true,
      managed: true,
      capabilities: { usage: true },
    },
    {
      id: "hidden-tool",
      visible: false,
      managed: true,
      capabilities: { usage: true },
    },
    {
      id: "session-only",
      visible: true,
      managed: true,
      capabilities: { sessions: true },
    },
    {
      id: "disabled-tool",
      visible: true,
      managed: false,
      capabilities: { usage: true },
    },
  ];

  assert.deepEqual(
    visibleUsageProviders(providers).map((provider) => provider.id),
    ["codex", "overlay-tool"],
  );
});
