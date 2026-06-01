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
  const badges = readFileSync(join(root, "src", "components", "session-browser", "badges.tsx"), "utf8");
  const codexChat = readFileSync(join(root, "src", "components", "session-browser", "CodexChat.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /modelProvider\?: string \| null;/);
  assert.match(types, /source\?: string \| null;/);
  assert.match(types, /isSmoke\?: boolean;/);

  assert.match(api, /modelProvider:\s*thread\.modelProvider \?\? thread\.model_provider \?\? null/);
  assert.match(api, /source:\s*thread\.source \?\? null/);
  assert.match(api, /isSmoke:\s*Boolean\(thread\.isSmoke \?\? thread\.is_smoke\)/);

  assert.match(badges, /export function CodexSessionBadges/);
  assert.match(badges, /providerBadge\(session\.modelProvider\)/);
  assert.match(badges, /sourceBadge\(session\.source\)/);
  assert.match(badges, /smokeBadge/);
  assert.match(codexChat, /<CodexSessionBadges session=\{activeSession\} \/>/);
  assert.match(sessionBrowser, /<CodexSessionBadges session=\{session\.raw as CodexSession\} compact \/>/);
});

test("generic provider sessions render a reusable chat surface with composer wiring", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(api, /export async function fetchProviderSession\(/);
  assert.match(api, /export async function sendProviderSessionMessage\(/);
  assert.match(sessionBrowser, /<GenericProviderChat/);
  assert.match(genericChat, /export function GenericProviderChat/);
  assert.match(genericChat, /const turns = await fetchProviderSession\(session\.type, session\.id, session\.workspace\)/);
  assert.match(
    genericChat,
    /await sendProviderSessionMessage\(session\.type,\s*session\.id,\s*trimmedText,\s*nextAttachments,\s*session\.workspace\)/,
  );
  assert.match(genericChat, /<SessionComposer/);
  assert.doesNotMatch(genericChat, /chat is not available/);
});

test("claude session composer sends through the provider owner bridge", () => {
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");

  assert.match(api, /await sendProviderSessionMessage\(\s*"claude",\s*sessionId,\s*text,\s*attachments,\s*workspaceDir/);
  assert.doesNotMatch(api, /send_claude_session_message/);
});

test("session locale strings expose provider, source, and smoke labels", () => {
  for (const locale of ["en", "zh"]) {
    const source = readFileSync(join(root, "src", "i18n", "locales", `${locale}.ts`), "utf8");
    assert.match(source, /providerBadge:\s*\(provider: string\)\s*=>/);
    assert.match(source, /sourceBadge:\s*\(source: string\)\s*=>/);
    assert.match(source, /smokeBadge:\s*"Smoke"/);
  }
});
