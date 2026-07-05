import test from "node:test";
import assert from "node:assert/strict";

import { mergeSessionTurns, overlayPendingUserTurn } from "../src/utils/sessionTurnMerge.js";

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

test("mergeSessionTurns replaces optimistic user turn with attachment-enriched snapshot", () => {
  const existing = [
    { role: "user", content: "图片里面主要是什么内容" },
    { role: "assistant", content: "等待中...", pending: true },
  ];
  const incoming = [
    {
      role: "user",
      content: "图片里面主要是什么内容\n[Attached image] Image #1",
    },
    { role: "assistant", content: "图片主色调是偏青绿色。", displayMode: "markdown" },
  ];

  const merged = mergeSessionTurns(existing, incoming);

  assert.deepEqual(
    merged.map((turn) => [turn.role, turn.content]),
    [
      ["user", "图片里面主要是什么内容\n[Attached image] Image #1"],
      ["assistant", "图片主色调是偏青绿色。"],
    ],
  );
});

test("overlayPendingUserTurn appends last accepted user message when snapshot is still empty", () => {
  const next = overlayPendingUserTurn([], {
    lastUserMessage: "这个工程的主要作用是什么？",
    lastEventKind: "message.user.accepted",
  });

  assert.deepEqual(next, [
    {
      role: "user",
      content: "这个工程的主要作用是什么？",
      displayMode: "plain",
    },
  ]);
});

test("overlayPendingUserTurn does not duplicate a user turn already present in snapshot", () => {
  const next = overlayPendingUserTurn(
    [{ role: "user", content: "这个工程的主要作用是什么？", displayMode: "plain" }],
    {
      lastUserMessage: "这个工程的主要作用是什么？",
      lastEventKind: "message.user.accepted",
    },
  );

  assert.deepEqual(next, [
    { role: "user", content: "这个工程的主要作用是什么？", displayMode: "plain" },
  ]);
});

test("overlayPendingUserTurn ignores non-user-terminal activity states", () => {
  const next = overlayPendingUserTurn([], {
    lastUserMessage: "这个工程的主要作用是什么？",
    lastEventKind: "message.assistant.final",
  });

  assert.deepEqual(next, []);
});
