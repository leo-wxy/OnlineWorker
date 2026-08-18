import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("..", import.meta.url);

test("account host uses one build-time builtin registry and a fixed sidebar entry", async () => {
  const host = await readFile(new URL("src/components/AccountFeatureHost.tsx", root), "utf8");
  const app = await readFile(new URL("src/App.tsx", root), "utf8");
  const vite = await readFile(new URL("vite.config.ts", root), "utf8");
  assert.match(host, /import\.meta\.glob/);
  assert.match(host, /plugins\/providers\/builtin\/\*\/frontend\/account_entry\.tsx/);
  assert.doesNotMatch(host, /iframe|WebView|provider_id\s*===|feature_id\s*===\s*["']codex/);
  assert.doesNotMatch(app, /accountFeaturesAvailable/);
  assert.equal((app.match(/>账号</g) || []).length, 1);
  assert.match(vite, /plugins\/providers\/builtin/);
  assert.doesNotMatch(vite, /codex/);
});
