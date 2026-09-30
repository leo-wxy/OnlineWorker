import test from "node:test";
import assert from "node:assert/strict";

import {
  countAssistantEntries,
} from "../src/utils/sessionPolling.js";

test("countAssistantEntries ignores pending assistant placeholder", () => {
  const snapshot = [
    { role: "user", content: "继续" },
    { role: "assistant", content: "思考中...", pending: true },
    { role: "assistant", content: "最终回复" },
  ];

  assert.equal(countAssistantEntries(snapshot), 1);
});
