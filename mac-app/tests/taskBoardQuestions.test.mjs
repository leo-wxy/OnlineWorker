import assert from "node:assert/strict";
import test from "node:test";
import { buildTaskBoardModel, buildTaskBoardQuestionAnswers } from "../src/utils/taskBoard.js";

const question = { questionId: "sample-question", header: "Language", question: "Choose",
  options: [{ label: "Python" }, { label: "Rust" }], multiple: false, custom: true, subIndex: 0, subTotal: 1 };

test("question answers support single choice, multiple choice and custom text", () => {
  assert.deepEqual(buildTaskBoardQuestionAnswers([question], { 0: [1] }, {}), [["Rust"]]);
  assert.deepEqual(buildTaskBoardQuestionAnswers([question], { 0: [-1] }, { 0: "  Other  " }), [["Other"]]);
  assert.deepEqual(buildTaskBoardQuestionAnswers([{ ...question, multiple: true }], { 0: [0, 1, -1] }, { 0: "Other" }), [["Python", "Rust", "Other"]]);
  assert.deepEqual(buildTaskBoardQuestionAnswers([{ ...question, options: [] }], {}, { 0: "Text" }), [["Text"]]);
});

test("incomplete groups, unanswered questions and invalid selections cannot submit", () => {
  for (const [questions, selections, custom] of [
    [[], {}, {}], [[{ ...question, subTotal: 2 }], { 0: [0] }, {}],
    [[question], {}, {}], [[question], { 0: [-1] }, { 0: " " }],
    [[question], { 0: [9] }, {}], [[question], { 0: [0, 1] }, {}],
    [[{ ...question, custom: false }], { 0: [-1] }, { 0: "Other" }],
  ]) assert.equal(buildTaskBoardQuestionAnswers(questions, selections, custom), null);
  const questions = [{ ...question, subTotal: 2 }, { ...question, subIndex: 1, subTotal: 2 }];
  assert.deepEqual(buildTaskBoardQuestionAnswers(questions, { 0: [1], 1: [-1] }, { 1: "Text" }), [["Rust"], ["Text"]]);
});

test("task board carries question fields directly from the bus activity", () => {
  const questions = [question];
  const task = buildTaskBoardModel({ sessions: [], dashboardState: null, providerLabels: {},
    sessionActivities: [{ providerId: "claude", sessionId: "sample-session", status: "needs_attention",
      attentionKind: "question", requestId: "sample-question", questions }] }).needsAttention[0];
  assert.strictEqual(task.questions, questions);
  assert.equal(task.requestId, "sample-question");
});
