import assert from "node:assert/strict";
import test from "node:test";
import { buildTaskBoardModel } from "../src/utils/taskBoard.js";

test("task detail receives updated conversation through the existing bus activity projection", () => {
  const activity = {
    providerId: "codex", sessionId: "sample-session", status: "running",
    conversationTurns: [{ role: "assistant", content: "old reply" }], updatedAt: 1,
  };
  const model = value => buildTaskBoardModel({ sessions: [], providerLabels: {}, sessionActivities: [value] }).running[0];
  assert.equal(model(activity).conversationTurns[0].content, "old reply");
  const next = { ...activity, conversationTurns: [{ role: "assistant", content: "new reply" }], updatedAt: 2 };
  assert.strictEqual(model(next).conversationTurns, next.conversationTurns);
  assert.equal(model(next).conversationTurns[0].content, "new reply");
  assert.deepEqual(model({ ...next, conversationTurns: undefined }).conversationTurns, []);
});
