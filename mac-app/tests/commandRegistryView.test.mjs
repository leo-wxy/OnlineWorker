import test from "node:test";
import assert from "node:assert/strict";

import {
  buildCommandBackendViews,
  countCommandsForBackendView,
  matchesCommandBackendView,
  visibleCommandProviders,
} from "../src/utils/commandRegistryView.js";

const COMMANDS = [
  { id: "bot:help", source: "bot", backend: "local" },
  { id: "downstream:codex:review", source: "downstream", backend: "codex" },
  { id: "downstream:customprovider:review", source: "downstream", backend: "customprovider" },
  { id: "downstream:claude:doctor", source: "downstream", backend: "claude" },
  { id: "skill:find-skills", source: "skill", backend: "shared" },
];

test("buildCommandBackendViews uses visible provider metadata and omits customprovider by default", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true },
    { id: "customprovider", label: "Custom Provider", visible: false },
    { id: "claude", label: "Claude", visible: true, managed: true },
  ];

  assert.deepEqual(visibleCommandProviders(providers).map((provider) => provider.id), [
    "codex",
    "claude",
  ]);
  assert.deepEqual(buildCommandBackendViews(providers), ["bot", "codex", "claude"]);
});

test("matchesCommandBackendView routes shared entries into claude provider view", () => {
  const claudeCommand = COMMANDS.find((command) => command.backend === "claude");
  const sharedSkill = COMMANDS.find((command) => command.backend === "shared");

  assert.equal(matchesCommandBackendView(claudeCommand, "claude"), true);
  assert.equal(matchesCommandBackendView(sharedSkill, "claude"), true);
  assert.equal(matchesCommandBackendView(sharedSkill, "bot"), false);
});

test("countCommandsForBackendView counts provider-specific and shared commands together", () => {
  assert.equal(countCommandsForBackendView(COMMANDS, "claude"), 2);
  assert.equal(countCommandsForBackendView(COMMANDS, "codex"), 2);
  assert.equal(countCommandsForBackendView(COMMANDS, "bot"), 1);
});

test("explicit visible customprovider metadata adds customprovider command view", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true },
    { id: "customprovider", label: "Custom Provider", visible: true, managed: true },
    { id: "claude", label: "Claude", visible: true, managed: true },
  ];

  assert.deepEqual(buildCommandBackendViews(providers), ["bot", "codex", "customprovider", "claude"]);
  assert.equal(countCommandsForBackendView(COMMANDS, "customprovider"), 2);
});

test("visible but disabled extension provider does not add command view", () => {
  const providers = [
    { id: "codex", label: "Codex", visible: true, managed: true },
    { id: "customprovider", label: "Custom Provider", visible: true, managed: false },
    { id: "claude", label: "Claude", visible: true, managed: true },
  ];

  assert.deepEqual(buildCommandBackendViews(providers), ["bot", "codex", "claude"]);
});
