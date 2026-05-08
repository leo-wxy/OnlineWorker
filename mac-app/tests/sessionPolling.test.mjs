import test from "node:test";
import assert from "node:assert/strict";

import {
  buildSnapshotSignature,
  countAssistantEntries,
  pollAssistantReply,
  pollForSettledAssistantReply,
} from "../src/utils/sessionPolling.js";

test("pollForSettledAssistantReply keeps polling past first codex commentary snapshot", async () => {
  const baselineTurns = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
  ];

  const snapshots = [
    [
      ...baselineTurns,
      { role: "user", content: "new question" },
      { role: "assistant", content: "我先看一下当前改动范围。" },
    ],
    [
      ...baselineTurns,
      { role: "user", content: "new question" },
      { role: "assistant", content: "我先看一下当前改动范围。" },
    ],
    [
      ...baselineTurns,
      { role: "user", content: "new question" },
      { role: "assistant", content: "我先看一下当前改动范围。" },
      { role: "assistant", content: "已经确认，下面是完整结论。" },
    ],
    [
      ...baselineTurns,
      { role: "user", content: "new question" },
      { role: "assistant", content: "我先看一下当前改动范围。" },
      { role: "assistant", content: "已经确认，下面是完整结论。" },
    ],
    [
      ...baselineTurns,
      { role: "user", content: "new question" },
      { role: "assistant", content: "我先看一下当前改动范围。" },
      { role: "assistant", content: "已经确认，下面是完整结论。" },
    ],
  ];

  let index = 0;
  const updates = [];

  const result = await pollForSettledAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineTurns),
    onUpdate: (snapshot) => updates.push(snapshot),
    intervalMs: 0,
    maxAttempts: 5,
    stablePollsRequired: 2,
  });

  assert.equal(result.at(-1)?.content, "已经确认，下面是完整结论。");
  assert.equal(updates.at(-1)?.at(-1)?.content, "已经确认，下面是完整结论。");
  assert.equal(index, 5);
});

test("pollForSettledAssistantReply waits for delayed session assistant reply", async () => {
  const baselineMessages = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
  ];

  const snapshots = [
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "new answer" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "new answer" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "new answer" },
    ],
  ];

  let index = 0;

  const result = await pollForSettledAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineMessages),
    intervalMs: 0,
    maxAttempts: 5,
    stablePollsRequired: 2,
  });

  assert.equal(
    result.at(-1)?.content,
    "new answer",
  );
  assert.equal(index, 5);
});

test("pollAssistantReply reports timeout when no assistant reply lands in the foreground window", async () => {
  const baselineMessages = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
  ];

  const snapshots = [
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
  ];

  let index = 0;

  const result = await pollAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineMessages),
    intervalMs: 0,
    maxAttempts: 3,
    stablePollsRequired: 2,
  });

  assert.equal(result.settled, false);
  assert.equal(result.assistantAppeared, false);
  assert.equal(result.snapshot.at(-1)?.content, "new question");
});

test("countAssistantEntries ignores pending assistant placeholder", () => {
  const snapshot = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
    { role: "assistant", content: "最终回复" },
  ];

  assert.equal(countAssistantEntries(snapshot), 1);
});

test("pollAssistantReply can settle after a later background-style retry window", async () => {
  const baselineMessages = [
    { role: "user", content: "old question" },
    { role: "assistant", content: "old answer" },
  ];

  const snapshots = [
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "slow answer" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "slow answer" },
    ],
    [
      ...baselineMessages,
      { role: "user", content: "new question" },
      { role: "assistant", content: "slow answer" },
    ],
  ];

  let index = 0;

  const foreground = await pollAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineMessages),
    intervalMs: 0,
    maxAttempts: 2,
    stablePollsRequired: 2,
  });

  assert.equal(foreground.settled, false);
  assert.equal(foreground.assistantAppeared, false);

  const background = await pollAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineMessages),
    intervalMs: 0,
    maxAttempts: 4,
    stablePollsRequired: 2,
  });

  assert.equal(background.settled, true);
  assert.equal(background.assistantAppeared, true);
  assert.equal(background.snapshot.at(-1)?.content, "slow answer");
});

test("pollAssistantReply settles when customprovider truncation keeps assistant count unchanged", async () => {
  const baselineMessages = Array.from({ length: 10 }, (_, index) => ([
    { role: "user", content: `问题 ${index + 1}` },
    { role: "assistant", content: `回复 ${index + 1}` },
  ])).flat();

  const snapshots = [
    [
      ...baselineMessages.slice(1),
      { role: "user", content: "问题 11" },
    ],
    [
      ...baselineMessages.slice(1),
      { role: "user", content: "问题 11" },
    ],
    [
      ...baselineMessages.slice(2),
      { role: "user", content: "问题 11" },
      { role: "assistant", content: "回复 11" },
    ],
    [
      ...baselineMessages.slice(2),
      { role: "user", content: "问题 11" },
      { role: "assistant", content: "回复 11" },
    ],
    [
      ...baselineMessages.slice(2),
      { role: "user", content: "问题 11" },
      { role: "assistant", content: "回复 11" },
    ],
    [
      ...baselineMessages.slice(2),
      { role: "user", content: "问题 11" },
      { role: "assistant", content: "回复 11" },
    ],
  ];

  let index = 0;

  const result = await pollAssistantReply({
    loadSnapshot: async () => {
      const snapshot = snapshots[Math.min(index, snapshots.length - 1)];
      index += 1;
      return snapshot;
    },
    getAssistantCount: countAssistantEntries,
    getSignature: buildSnapshotSignature,
    baselineAssistantCount: countAssistantEntries(baselineMessages),
    baselineSnapshot: baselineMessages,
    intervalMs: 0,
    maxAttempts: 6,
    stablePollsRequired: 2,
  });

  assert.equal(result.settled, true);
  assert.equal(result.assistantAppeared, true);
  assert.equal(result.snapshot.at(-1)?.content, "回复 11");
});
