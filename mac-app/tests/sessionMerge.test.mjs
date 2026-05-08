import test from "node:test";
import assert from "node:assert/strict";

import { mergeSessionTurns } from "../src/utils/sessionTurnMerge.js";

test("mergeSessionTurns removes stale pending assistant when final snapshot arrives", () => {
  const existing = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
    { role: "assistant", content: "等待回复中...", pending: true },
    { role: "user", content: "new question" },
  ];
  const incoming = [
    { role: "user", content: "new question" },
    { role: "assistant", content: "## final answer", displayMode: "markdown" },
  ];

  const merged = mergeSessionTurns(existing, incoming);

  assert.equal(
    merged.some((turn) => turn.role === "assistant" && turn.pending === true),
    false,
  );
  assert.deepEqual(
    merged.map((turn) => [turn.role, turn.content]),
    [
      ["user", "old question"],
      ["assistant", "old answer"],
      ["user", "new question"],
      ["assistant", "## final answer"],
    ],
  );
});

test("mergeSessionTurns deduplicates optimistic user turn before final snapshot", () => {
  const existing = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
    { role: "user", content: "new question" },
  ];
  const incoming = [
    { role: "user", content: "new question" },
    { role: "assistant", content: "## final answer", displayMode: "markdown" },
  ];

  const merged = mergeSessionTurns(existing, incoming);

  assert.deepEqual(
    merged.map((turn) => [turn.role, turn.content]),
    [
      ["user", "old question"],
      ["assistant", "old answer"],
      ["user", "new question"],
      ["assistant", "## final answer"],
    ],
  );
});
