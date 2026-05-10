import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("codex session metadata badges are wired through the session browser", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /modelProvider\?: string \| null;/);
  assert.match(types, /source\?: string \| null;/);
  assert.match(types, /isSmoke\?: boolean;/);

  assert.match(api, /modelProvider:\s*thread\.model_provider \?\? null/);
  assert.match(api, /source:\s*thread\.source \?\? null/);
  assert.match(api, /isSmoke:\s*Boolean\(thread\.is_smoke\)/);

  assert.match(sessionBrowser, /function CodexSessionBadges/);
  assert.match(sessionBrowser, /<CodexSessionBadges session=\{rawSession\} \/>/);
  assert.match(sessionBrowser, /<CodexSessionBadges session=\{session\.raw as CodexSession\} compact \/>/);
});

test("session locale strings expose provider, source, and smoke labels", () => {
  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /providerBadge:\s*\(provider: string\)\s*=>/);
    assert.match(source, /sourceBadge:\s*\(source: string\)\s*=>/);
    assert.match(source, /smokeBadge:\s*"Smoke"/);
  }
});
