import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("codex send flow merges snapshot back into optimistic turns", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");

  assert.match(sessionBrowser, /mergeSessionTurns\(previousTurns, snapshot\)/);
  assert.match(sessionBrowser, /mergeSessionTurns\(previousTurns, nextTurns\)/);
});
