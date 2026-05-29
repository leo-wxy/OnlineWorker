import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("codex send flow merges snapshot back into optimistic turns", () => {
  const codexChat = readFileSync(join(root, "src", "components", "session-browser", "CodexChat.tsx"), "utf8");

  assert.match(codexChat, /mergeSessionTurns\(previousTurns, snapshot\)/);
  assert.match(codexChat, /mergeSessionTurns\(previousTurns, nextTurns\)/);
});
