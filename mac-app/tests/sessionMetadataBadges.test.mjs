import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

test("codex session metadata badges are wired through the session browser", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const sessionData = readFileSync(join(root, "src", "components", "session-browser", "sessionData.ts"), "utf8");
  const badges = readFileSync(join(root, "src", "components", "session-browser", "badges.tsx"), "utf8");
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");
  const types = readFileSync(join(root, "src", "types.ts"), "utf8");

  assert.match(types, /modelProvider\?: string \| null;/);
  assert.match(types, /source\?: string \| null;/);
  assert.match(types, /isSmoke\?: boolean;/);

  assert.match(sessionData, /export function providerSessionMetadataFromUnifiedSession/);
  assert.match(sessionData, /modelProvider:\s*typeof raw\.modelProvider === "string"/);
  assert.match(sessionData, /source:\s*typeof raw\.source === "string" \? raw\.source : null/);
  assert.match(sessionData, /isSmoke:\s*Boolean\(raw\.isSmoke \?\? raw\.is_smoke\)/);

  assert.match(badges, /export function ProviderSessionBadges/);
  assert.match(badges, /providerBadge\(session\.modelProvider\)/);
  assert.match(badges, /sourceBadge\(session\.source\)/);
  assert.match(badges, /smokeBadge/);
  assert.match(genericChat, /isSessionMetadataRich/);
  assert.match(genericChat, /<ProviderSessionBadges session=\{providerSessionMetadataFromUnifiedSession\(activeSession\)\} \/>/);
  assert.match(sessionBrowser, /<ProviderSessionBadges session=\{providerSessionMetadataFromUnifiedSession\(session\)\} compact \/>/);
  assert.doesNotMatch(sessionBrowser, /<CodexChat/);
});

test("generic provider sessions render a reusable chat surface with composer wiring", () => {
  const sessionBrowser = readFileSync(join(root, "src", "pages", "SessionBrowser.tsx"), "utf8");
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");
  const navigation = readFileSync(join(root, "src", "components", "session-browser", "navigation.tsx"), "utf8");
  const sessionState = readFileSync(join(root, "src", "utils", "sessionBrowserState.js"), "utf8");

  assert.match(sessionBrowser, /useState<ProviderFilter>\(\(\) => openTarget\?\.providerId \|\| ""\)/);
  assert.equal(sessionBrowser.includes('useState<ProviderFilter>("codex")'), false);
  assert.match(sessionBrowser, /if \(!active \|\| !providerFilter\) \{\s*return;\s*\}/s);
  assert.match(sessionBrowser, /taskBoardActivities = \[\]/);
  assert.match(sessionBrowser, /active = true/);
  assert.match(sessionBrowser, /mergeLiveSessionActivities\(/);
  assert.match(sessionState, /export function mergeLiveSessionActivities\(/);
  assert.match(sessionState, /export function sessionPreviewText\(/);
  assert.match(api, /export async function fetchProviderSession\(/);
  assert.match(api, /export async function sendProviderSessionMessage\(/);
  assert.match(navigation, /sessionPreviewText\(session\)/);
  assert.match(sessionBrowser, /<GenericProviderChat/);
  assert.match(genericChat, /export function GenericProviderChat/);
  assert.match(genericChat, /const turns = await fetchProviderSession\(activeSession\.type, activeSession\.id, activeSession\.workspace\)/);
  assert.match(
    genericChat,
    /await sendProviderSessionMessage\(\s*activeSession\.type,\s*activeSession\.id,\s*trimmedText,\s*nextAttachments,\s*activeSession\.workspace,\s*\)/s,
  );
  assert.match(genericChat, /active = true/);
  assert.match(genericChat, /enabled: active && mode !== "new-session" && Boolean\(activeSession\.id\)/);
  assert.match(genericChat, /<SessionComposer/);
  assert.doesNotMatch(genericChat, /chat is not available/);
});

test("generic provider chat keeps header state aligned without remounting on live list updates", () => {
  const genericChat = readFileSync(join(root, "src", "components", "session-browser", "GenericProviderChat.tsx"), "utf8");

  assert.match(genericChat, /useEffect\(\(\) => \{\s*liveStreamReadyRef\.current = false;\s*setActiveSession\(session\);\s*\}, \[session\.id, session\.type, session\.workspace\]\);/s);
  assert.match(genericChat, /if \(!active\) \{\s*return;\s*\}/s);
  assert.match(genericChat, /enabled: active && mode !== "new-session" && Boolean\(activeSession\.id\)/);
  assert.match(genericChat, /if \(hasLoadedRef\.current && messagesRef\.current\.length > 0\) \{\s*void refreshMessagesSilently\(\);\s*\} else \{\s*void loadMessages\(\);\s*\}/s);
  assert.match(genericChat, /if \(!hasSessionSnapshotChanged\(messagesRef\.current, nextTurns\)\) \{/);
});

test("provider session composer sends through the provider owner bridge", () => {
  const api = readFileSync(join(root, "src", "components", "session-browser", "api.ts"), "utf8");

  assert.match(api, /export async function sendProviderSessionMessage\(/);
  assert.match(api, /invoke<Record<string, unknown> \| null>\("send_provider_session_message"/);
  assert.match(api, /export async function fetchProviderSession\(/);
  assert.match(api, /invoke<SessionTurn\[]>\("read_provider_session"/);
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
