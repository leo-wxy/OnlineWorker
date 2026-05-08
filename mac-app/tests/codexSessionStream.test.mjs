import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

import {
  applyCodexStreamEvent,
  buildCodexAbortedTurn,
} from "../src/utils/codexSessionStream.js";

const semanticSequenceFixture = JSON.parse(
  fs.readFileSync(new URL("../../tests/fixtures/codex_semantic_sequences.json", import.meta.url), "utf8"),
);

test("applyCodexStreamEvent appends assistant turn and deduplicates adjacent duplicates", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "先看代码。" },
  ];

  const appended = applyCodexStreamEvent(initial, {
    kind: "assistant_completed",
    turn: { role: "assistant", content: "再补测试。" },
  });
  assert.equal(appended.length, 3);
  assert.equal(appended.at(-1)?.content, "再补测试。");

  const deduped = applyCodexStreamEvent(appended, {
    kind: "assistant_completed",
    turn: { role: "assistant", content: "再补测试。" },
  });
  assert.deepEqual(deduped, appended);
});

test("buildCodexAbortedTurn hides abort notice without partial text", () => {
  const turn = buildCodexAbortedTurn("interrupted");
  assert.equal(turn, null);
});

test("applyCodexStreamEvent ignores bare turn_aborted notice", () => {
  const initial = [{ role: "user", content: "继续" }];
  const next = applyCodexStreamEvent(initial, {
    kind: "turn_aborted",
    reason: "interrupted",
  });

  assert.deepEqual(next, initial);
});

test("applyCodexStreamEvent replaces pending assistant when semantic abort lands", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "我先检查一下。", pending: true },
  ];
  const next = applyCodexStreamEvent(initial, {
    kind: "turn_completed",
    semanticKind: "turn_aborted",
    reason: "interrupted",
  });

  assert.equal(next.length, 2);
  assert.equal(next[1].role, "assistant");
  assert.equal(next[1].pending, undefined);
  assert.equal(next[1].content, "我先检查一下。");
  assert.doesNotMatch(next[1].content, /已中断|已终止|不完整|Request interrupted/);
});

test("applyCodexStreamEvent renders final assistant reply from semantic turn_completed", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
  ];

  const next = applyCodexStreamEvent(initial, {
    kind: "turn_completed",
    semanticKind: "turn_completed",
    turn: { role: "assistant", content: "最终回复。" },
  });

  assert.equal(next.length, 2);
  assert.equal(next[1].content, "最终回复。");
  assert.equal(next[1].pending, undefined);
  assert.equal(next[1].displayMode, "markdown");
});

test("codex semantic final fixture converges to one completed assistant turn", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
  ];
  const next = semanticSequenceFixture.final_sequence.reduce(
    (turns, event) => applyCodexStreamEvent(turns, event),
    initial,
  );

  assert.equal(next.length, 2);
  assert.equal(next[1].role, "assistant");
  assert.equal(next[1].content, "已经确认根因，开始修改。");
  assert.equal(next[1].pending, undefined);
  assert.equal(next[1].displayMode, "markdown");
});

test("codex semantic abort fixture preserves commentary and replaces pending assistant", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
  ];
  const next = semanticSequenceFixture.abort_sequence.reduce(
    (turns, event) => applyCodexStreamEvent(turns, event),
    initial,
  );

  assert.equal(next.length, 2);
  assert.equal(next[1].role, "assistant");
  assert.equal(next[1].pending, undefined);
  assert.match(next[1].content, /我先检查一下当前链路。/);
  assert.doesNotMatch(next[1].content, /已中断|已终止|不完整|Request interrupted/);
});
