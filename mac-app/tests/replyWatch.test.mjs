import test from "node:test";
import assert from "node:assert/strict";

import { shouldClearReplyWatch } from "../src/utils/replyWatch.js";

test("shouldClearReplyWatch clears when assistant stream event appends a reply", () => {
  const previous = [{ role: "user", content: "继续" }];
  const next = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "我先检查一下。" },
  ];

  assert.equal(
    shouldClearReplyWatch(previous, next, {
      kind: "assistant_completed",
      turn: { role: "assistant", content: "我先检查一下。" },
    }),
    true,
  );
});

test("shouldClearReplyWatch clears when replace_snapshot introduces assistant reply", () => {
  const previous = [{ role: "user", content: "继续" }];
  const next = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "已经完成。" },
  ];

  assert.equal(
    shouldClearReplyWatch(previous, next, {
      kind: "replace_snapshot",
      snapshot: next,
    }),
    true,
  );
});

test("shouldClearReplyWatch clears when replace_snapshot keeps assistant count but rotates window to a new reply", () => {
  const previous = Array.from({ length: 10 }, (_, index) => ([
    { role: "user", content: `问题 ${index + 1}` },
    { role: "assistant", content: `回复 ${index + 1}` },
  ])).flat();
  const next = [
    ...previous.slice(2),
    { role: "user", content: "问题 11" },
    { role: "assistant", content: "回复 11" },
  ];

  assert.equal(
    shouldClearReplyWatch(previous, next, {
      kind: "replace_snapshot",
      snapshot: next,
    }),
    true,
  );
});

test("shouldClearReplyWatch keeps waiting for user_message echo", () => {
  const previous = [{ role: "user", content: "继续" }];
  const next = [...previous];

  assert.equal(
    shouldClearReplyWatch(previous, next, {
      kind: "user_message",
      turn: { role: "user", content: "继续" },
    }),
    false,
  );
});

test("shouldClearReplyWatch clears immediately for turn_aborted", () => {
  const snapshot = [{ role: "user", content: "继续" }];

  assert.equal(
    shouldClearReplyWatch(snapshot, snapshot, {
      kind: "turn_aborted",
      reason: "interrupted",
    }),
    true,
  );
});

test("shouldClearReplyWatch clears immediately for semantic turn_aborted", () => {
  const snapshot = [{ role: "user", content: "继续" }];

  assert.equal(
    shouldClearReplyWatch(snapshot, snapshot, {
      semanticKind: "turn_aborted",
      reason: "interrupted",
    }),
    true,
  );
});
