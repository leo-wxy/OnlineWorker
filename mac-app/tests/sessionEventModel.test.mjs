import test from "node:test";
import assert from "node:assert/strict";

import {
  applySessionStreamEvent,
  buildAbortedSessionTurn,
} from "../src/utils/sessionEventModel.js";

test("applySessionStreamEvent appends assistant turn", () => {
  const initial = [{ role: "user", content: "继续" }];
  const next = applySessionStreamEvent(initial, {
    kind: "assistant_completed",
    turn: { role: "assistant", content: "我先检查一下。" },
  });

  assert.equal(next.length, 2);
  assert.equal(next[1].role, "assistant");
  assert.equal(next[1].content, "我先检查一下。");
});

test("applySessionStreamEvent keeps codex commentary in the same pending assistant turn", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
  ];

  const commentary = applySessionStreamEvent(initial, {
    kind: "assistant_progress",
    turn: { role: "assistant", content: "我先看一下当前链路。", pending: true },
  });

  assert.equal(commentary.length, 2);
  assert.equal(commentary[1].content, "我先看一下当前链路。");
  assert.equal(commentary[1].pending, true);
  assert.equal(commentary[1].displayMode, "plain");

  const final = applySessionStreamEvent(commentary, {
    kind: "assistant_completed",
    turn: { role: "assistant", content: "已经确认根因，开始修复。" },
  });

  assert.equal(final.length, 2);
  assert.equal(final[1].content, "已经确认根因，开始修复。");
  assert.equal(final[1].pending, undefined);
  assert.equal(final[1].displayMode, "markdown");
});

test("assistant_completed replaces pending assistant with markdown display mode", () => {
  const initial = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true, displayMode: "plain" },
  ];

  const next = applySessionStreamEvent(initial, {
    kind: "assistant_completed",
    turn: { role: "assistant", content: "## 最终结果\n\n- 已完成" },
  });

  assert.equal(next.length, 2);
  assert.equal(next[1].pending, undefined);
  assert.equal(next[1].displayMode, "markdown");
  assert.equal(next[1].content, "## 最终结果\n\n- 已完成");
});

test("applySessionStreamEvent replaces snapshot when requested", () => {
  const initial = [{ role: "user", content: "旧问题" }];
  const next = applySessionStreamEvent(initial, {
    kind: "replace_snapshot",
    snapshot: [
      { role: "user", content: "新问题" },
      { role: "assistant", content: "新回复" },
    ],
  });

  assert.equal(next.length, 2);
  assert.equal(next[0].content, "新问题");
  assert.equal(next[1].content, "新回复");
});

test("buildAbortedSessionTurn returns null without partial text", () => {
  const turn = buildAbortedSessionTurn("interrupted");
  assert.equal(turn, null);
});

test("buildAbortedSessionTurn keeps only visible partial text", () => {
  const turn = buildAbortedSessionTurn("interrupted", "我先看一下当前链路。");
  assert.equal(turn.role, "assistant");
  assert.equal(turn.content, "我先看一下当前链路。");
  assert.equal(turn.displayMode, "plain");
});

test("applySessionStreamEvent can fall back to semanticKind when legacy kind is absent", () => {
  const initial = [{ role: "user", content: "继续" }];
  const next = applySessionStreamEvent(initial, {
    semanticKind: "turn_aborted",
    reason: "interrupted",
  });

  assert.equal(next.length, 1);
  assert.equal(next[0].content, "继续");
});

test("replace_snapshot preserves per-turn display mode contract", () => {
  const next = applySessionStreamEvent([], {
    kind: "replace_snapshot",
    snapshot: [
      { role: "user", content: "请整理输出", displayMode: "plain" },
      { role: "assistant", content: "## 最终结果", displayMode: "markdown" },
    ],
  });

  assert.equal(next.length, 2);
  assert.equal(next[0].displayMode, "plain");
  assert.equal(next[1].displayMode, "markdown");
});
